"""
test_codegen_evaluator.py — CodeGenEvaluator 集成测试 (EP-132)

覆盖：
  - EvaluatorConfig.from_env() 环境变量覆盖
  - Level 1: 语法检查（正常/空代码/语法错误）
  - Level 2: 结构契约检查（required_signatures/forbidden_patterns）
  - Level 3: 架构约束降级检查（arch_check.py 不可用时）
  - Level 4: 参考测试（无测试文件时跳过）
  - 综合分计算（全部有效/部分 NaN/全部 NaN）
  - 成本效率计算
  - codegen_quality 指标计算（LevelResult.pass_rate, compare_systems）
  - load_codegen_tasks 数据集加载
  - _repair_and_parse_json：6 种修复策略
  - _fix_json_format：常见格式错误修复
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_MMS_ROOT = _HERE.parent

sys.path.insert(0, str(_MMS_ROOT))
sys.path.insert(0, str(_MMS_ROOT / "benchmark" / "src"))


# ─────────────────────────────────────────────────────────────────────────────
# EvaluatorConfig 测试
# ─────────────────────────────────────────────────────────────────────────────

class TestEvaluatorConfig:
    def test_default_config(self):
        from evaluators.codegen_evaluator import EvaluatorConfig
        cfg = EvaluatorConfig()
        assert cfg.skip_levels == set()
        assert cfg.arch_check_timeout == 30
        assert cfg.pytest_timeout == 60

    def test_from_env_skip_levels(self, monkeypatch):
        from evaluators.codegen_evaluator import EvaluatorConfig
        monkeypatch.setenv("MMS_EVAL_SKIP_LEVELS", "3,4")
        cfg = EvaluatorConfig.from_env()
        assert 3 in cfg.skip_levels
        assert 4 in cfg.skip_levels
        assert 1 not in cfg.skip_levels

    def test_from_env_timeout(self, monkeypatch):
        from evaluators.codegen_evaluator import EvaluatorConfig
        monkeypatch.setenv("MMS_EVAL_ARCH_CHECK_TIMEOUT", "60")
        monkeypatch.setenv("MMS_EVAL_PYTEST_TIMEOUT", "120")
        cfg = EvaluatorConfig.from_env()
        assert cfg.arch_check_timeout == 60
        assert cfg.pytest_timeout == 120

    def test_from_env_invalid_skip(self, monkeypatch):
        """无效的跳过级别不抛异常，仅跳过"""
        from evaluators.codegen_evaluator import EvaluatorConfig
        monkeypatch.setenv("MMS_EVAL_SKIP_LEVELS", "abc,4")
        cfg = EvaluatorConfig.from_env()
        assert 4 in cfg.skip_levels
        assert len(cfg.skip_levels) == 1  # "abc" 被忽略


# ─────────────────────────────────────────────────────────────────────────────
# Level 1: 语法检查
# ─────────────────────────────────────────────────────────────────────────────

class TestLevel1Syntax:
    def _evaluator(self):
        from evaluators.codegen_evaluator import CodeGenEvaluator, EvaluatorConfig
        return CodeGenEvaluator(EvaluatorConfig(skip_levels={2, 3, 4}))

    def test_valid_python(self):
        ev = self._evaluator()
        result = ev._check_syntax("def foo():\n    return 42\n")
        assert result.pass_rate == 1.0
        assert result.errors == []

    def test_syntax_error(self):
        ev = self._evaluator()
        result = ev._check_syntax("def foo(\n    return 42")
        assert result.pass_rate == 0.0
        assert len(result.errors) > 0
        assert "SyntaxError" in result.errors[0]

    def test_empty_source(self):
        ev = self._evaluator()
        result = ev._check_syntax("")
        assert result.pass_rate == 0.0

    def test_valid_async_function(self):
        ev = self._evaluator()
        source = "import asyncio\n\nasync def handler(ctx, dto):\n    await asyncio.sleep(0)\n    return dto\n"
        result = ev._check_syntax(source)
        assert result.pass_rate == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Level 2: 结构契约检查
# ─────────────────────────────────────────────────────────────────────────────

class TestLevel2Contract:
    def _evaluator(self):
        from evaluators.codegen_evaluator import CodeGenEvaluator, EvaluatorConfig
        return CodeGenEvaluator(EvaluatorConfig(skip_levels={1, 3, 4}))

    def _task(self, required=None, forbidden=None):
        return {
            "required_signatures": required or [],
            "forbidden_patterns": forbidden or [],
        }

    def test_all_required_present(self):
        ev = self._evaluator()
        source = "async def get_topology(ctx: RequestContext):\n    return success_response(data={})\n"
        task = self._task(required=["async def get_topology", "RequestContext", "success_response"])
        result = ev._check_contracts(source, task)
        assert result.pass_rate == 1.0
        assert result.errors == []

    def test_missing_required(self):
        ev = self._evaluator()
        source = "def foo(): pass"
        task = self._task(required=["async def foo", "ctx: RequestContext"])
        result = ev._check_contracts(source, task)
        assert result.passed < result.total
        assert any("缺少必需签名" in e for e in result.errors)

    def test_forbidden_present(self):
        ev = self._evaluator()
        source = "import aiokafka\ndef foo(): pass"
        task = self._task(forbidden=["import aiokafka", "import pymilvus"])
        result = ev._check_contracts(source, task)
        assert result.passed < result.total
        assert any("存在禁止模式" in e for e in result.errors)

    def test_all_forbidden_absent(self):
        ev = self._evaluator()
        source = "import asyncio\ndef foo(): pass"
        task = self._task(forbidden=["import aiokafka", "fetchall()"])
        result = ev._check_contracts(source, task)
        assert result.pass_rate == 1.0

    def test_empty_contracts(self):
        ev = self._evaluator()
        source = "def foo(): pass"
        task = self._task()
        result = ev._check_contracts(source, task)
        assert result.skipped is True

    def test_mixed_required_and_forbidden(self):
        """4 个检查项：2 required（全中）+ 2 forbidden（1 中 1 不中）"""
        ev = self._evaluator()
        source = "async def foo(ctx: RequestContext):\n    import aiokafka"
        task = self._task(
            required=["async def foo", "ctx: RequestContext"],
            forbidden=["import aiokafka", "fetchall()"],
        )
        result = ev._check_contracts(source, task)
        assert result.total == 4
        assert result.passed == 3  # 2 required 通过 + 1 forbidden 通过（fetchall 不存在）


# ─────────────────────────────────────────────────────────────────────────────
# Level 3: 架构约束（降级模式）
# ─────────────────────────────────────────────────────────────────────────────

class TestLevel3ArchFallback:
    def _evaluator(self):
        from evaluators.codegen_evaluator import CodeGenEvaluator, EvaluatorConfig
        return CodeGenEvaluator(EvaluatorConfig(skip_levels={1, 2, 4}))

    def test_ac1_no_forbidden_imports(self):
        ev = self._evaluator()
        source = "from app.infrastructure import kafka\ndef foo(): pass"
        result = ev._fallback_arch_check(source, ["AC-1"])
        assert result.passed == 1

    def test_ac1_violation(self):
        ev = self._evaluator()
        source = "import aiokafka\ndef foo(): pass"
        result = ev._fallback_arch_check(source, ["AC-1"])
        assert result.passed == 0
        assert any("AC-1" in e for e in result.errors)

    def test_ac2_has_ctx(self):
        ev = self._evaluator()
        source = "async def foo(ctx: RequestContext): pass"
        result = ev._fallback_arch_check(source, ["AC-2"])
        assert result.passed == 1

    def test_ac4_has_envelope(self):
        ev = self._evaluator()
        source = "return success_response(data=result)"
        result = ev._fallback_arch_check(source, ["AC-4"])
        assert result.passed == 1

    def test_multiple_rules(self):
        ev = self._evaluator()
        source = "async def foo(ctx: RequestContext):\n    return success_response(data=None)"
        result = ev._fallback_arch_check(source, ["AC-1", "AC-2", "AC-4"])
        assert result.passed == 3

    def test_no_rules(self):
        ev = self._evaluator()
        result = ev._fallback_arch_check("def foo(): pass", [])
        assert result.skipped is True


# ─────────────────────────────────────────────────────────────────────────────
# Level 4: 参考测试（无文件时跳过）
# ─────────────────────────────────────────────────────────────────────────────

class TestLevel4TestSkip:
    def _evaluator(self):
        from evaluators.codegen_evaluator import CodeGenEvaluator, EvaluatorConfig
        return CodeGenEvaluator(EvaluatorConfig(skip_levels={1, 2, 3}))

    def test_no_test_path_config(self):
        ev = self._evaluator()
        result = ev._run_reference_tests("def foo(): pass", {}, "CG-999")
        assert result.skipped is True
        assert "无参考测试文件" in (result.skip_reason or "")

    def test_nonexistent_test_file(self):
        ev = self._evaluator()
        task = {"test_code_path": "CG-999/test_nonexistent.py"}
        result = ev._run_reference_tests("def foo(): pass", task, "CG-999")
        assert result.skipped is True


# ─────────────────────────────────────────────────────────────────────────────
# 综合评估
# ─────────────────────────────────────────────────────────────────────────────

class TestFullEvaluation:
    def test_good_endpoint_code(self):
        """好的端点代码：L1/L2 应高分"""
        from evaluators.codegen_evaluator import CodeGenEvaluator, EvaluatorConfig
        ev = CodeGenEvaluator(EvaluatorConfig(skip_levels={3, 4}))

        source = """
from fastapi import APIRouter, Depends
from app.core.context import RequestContext, get_context
from app.core.response import ResponseSchema, success_response
from app.core.rbac import require_permission

router = APIRouter(prefix="/objects", tags=["ontology"])

@router.get("/{object_id}/topology", response_model=ResponseSchema)
@require_permission("ont:object:view")
async def get_object_topology(
    object_id: str,
    ctx: RequestContext = Depends(get_context),
):
    data = {"nodes": [], "edges": []}
    return success_response(data=data)
"""
        task = {
            "id": "CG-001",
            "category": "L5_api",
            "difficulty": "easy",
            "required_signatures": [
                "async def get_object_topology",
                "@router.get",
                "response_model",
                "Depends",
            ],
            "forbidden_patterns": [
                "return []",
                "import aiokafka",
            ],
        }

        result = ev.evaluate("CG-001", task, source, system_name="test")
        assert result.level1_syntax.pass_rate == 1.0
        assert result.level2_contract.pass_rate == 1.0
        assert not math.isnan(result.codegen_score)
        assert result.codegen_score > 0

    def test_bad_code_with_violations(self):
        """有违规的代码：L2 应低分"""
        from evaluators.codegen_evaluator import CodeGenEvaluator, EvaluatorConfig
        ev = CodeGenEvaluator(EvaluatorConfig(skip_levels={3, 4}))

        source = """
import aiokafka
def get_topology():
    return []
"""
        task = {
            "id": "CG-BAD",
            "category": "L5_api",
            "difficulty": "easy",
            "required_signatures": ["async def get_topology", "response_model"],
            "forbidden_patterns": ["return []", "import aiokafka"],
        }

        result = ev.evaluate("CG-BAD", task, source, system_name="test")
        assert result.level1_syntax.pass_rate == 1.0  # 语法正确
        assert result.level2_contract.pass_rate < 1.0  # 契约违规

    def test_syntax_error_code(self):
        """语法错误的代码"""
        from evaluators.codegen_evaluator import CodeGenEvaluator, EvaluatorConfig
        ev = CodeGenEvaluator(EvaluatorConfig(skip_levels={3, 4}))

        source = "def foo(\n    return 42"  # SyntaxError
        task = {"id": "CG-SYN", "category": "L5_api", "difficulty": "easy"}

        result = ev.evaluate("CG-SYN", task, source, system_name="test")
        assert result.level1_syntax.pass_rate == 0.0

    def test_skip_all_levels(self):
        """全部跳过时综合分为 NaN"""
        from evaluators.codegen_evaluator import CodeGenEvaluator, EvaluatorConfig
        ev = CodeGenEvaluator(EvaluatorConfig(skip_levels={1, 2, 3, 4}))
        result = ev.evaluate("CG-SKIP", {}, "def foo(): pass", system_name="test")
        assert math.isnan(result.codegen_score)


# ─────────────────────────────────────────────────────────────────────────────
# codegen_quality 指标计算
# ─────────────────────────────────────────────────────────────────────────────

class TestCodegenQualityMetrics:
    def test_level_result_pass_rate(self):
        from metrics.codegen_quality import LevelResult
        lr = LevelResult(1, "syntax", 3, 4)
        assert abs(lr.pass_rate - 0.75) < 1e-6

    def test_level_result_nan_when_total_zero(self):
        from metrics.codegen_quality import LevelResult
        lr = LevelResult(1, "syntax", 0, 0, skipped=True)
        assert math.isnan(lr.pass_rate)
        assert lr.pass_rate_pct == "N/A"

    def test_codegen_score_all_valid(self):
        """全部 4 级有效时：加权综合分"""
        from metrics.codegen_quality import CodegenMetricResult, LevelResult
        r = CodegenMetricResult(task_id="T1", category="L5_api", difficulty="easy")
        r.level1_syntax = LevelResult(1, "syntax", 1, 1)      # 1.0
        r.level2_contract = LevelResult(2, "contract", 3, 4)  # 0.75
        r.level3_arch = LevelResult(3, "arch_check", 2, 2)    # 1.0
        r.level4_test = LevelResult(4, "test_pass", 2, 4)     # 0.5

        # 期望：1.0*0.1 + 0.75*0.3 + 1.0*0.3 + 0.5*0.3 = 0.775
        expected = 1.0 * 0.1 + 0.75 * 0.3 + 1.0 * 0.3 + 0.5 * 0.3
        assert abs(r.codegen_score - expected) < 1e-6

    def test_codegen_score_with_nan_level(self):
        """有 NaN 级别时：权重重新归一化"""
        from metrics.codegen_quality import CodegenMetricResult, LevelResult
        r = CodegenMetricResult(task_id="T2", category="L4_service", difficulty="medium")
        r.level1_syntax = LevelResult(1, "syntax", 1, 1)      # 1.0, w=0.1
        r.level2_contract = LevelResult(2, "contract", 2, 2)  # 1.0, w=0.3
        r.level3_arch = LevelResult(3, "arch_check", 0, 0, skipped=True)  # NaN
        r.level4_test = LevelResult(4, "test_pass", 0, 0, skipped=True)   # NaN

        # 有效权重：L1=0.1, L2=0.3 → 归一化后 L1=0.1/0.4=0.25, L2=0.3/0.4=0.75
        # 期望：1.0*0.25 + 1.0*0.75 = 1.0
        assert abs(r.codegen_score - 1.0) < 1e-6

    def test_codegen_score_all_nan(self):
        """全部 NaN 时返回 NaN"""
        from metrics.codegen_quality import CodegenMetricResult, LevelResult
        r = CodegenMetricResult(task_id="T3", category="L5_api", difficulty="hard")
        r.level1_syntax = LevelResult(1, "syntax", 0, 0, skipped=True)
        r.level2_contract = LevelResult(2, "contract", 0, 0, skipped=True)
        r.level3_arch = LevelResult(3, "arch_check", 0, 0, skipped=True)
        r.level4_test = LevelResult(4, "test_pass", 0, 0, skipped=True)
        assert math.isnan(r.codegen_score)

    def test_cost_efficiency(self):
        from metrics.codegen_quality import CodegenMetricResult, LevelResult
        r = CodegenMetricResult(task_id="T4", category="L5_api", difficulty="easy", retrieval_tokens=2000)
        r.level1_syntax = LevelResult(1, "syntax", 1, 1)
        r.level2_contract = LevelResult(2, "contract", 4, 4)
        r.level3_arch = LevelResult(3, "arch_check", 0, 0, skipped=True)
        r.level4_test = LevelResult(4, "test_pass", 0, 0, skipped=True)
        # score = 1.0, efficiency = 1.0 / (2000/1000 + 1e-6) ≈ 0.5
        assert abs(r.cost_efficiency - 0.5) < 0.01

    def test_compare_systems(self):
        from metrics.codegen_quality import CodegenMetricResult, CodegenSystemSummary, LevelResult, compare_systems

        def make_summary(name, score):
            r = CodegenMetricResult(task_id="T1", category="L5_api", difficulty="easy", system_name=name)
            r.level1_syntax = LevelResult(1, "syntax", int(score * 10), 10)
            r.level2_contract = LevelResult(2, "contract", int(score * 10), 10)
            return CodegenSystemSummary(system_name=name, task_results=[r])

        summaries = [make_summary("ontology", 0.9), make_summary("pageindex", 0.6)]
        comparison = compare_systems(summaries)
        assert comparison["winner"] == "ontology"
        assert len(comparison["rankings"]) == 2


# ─────────────────────────────────────────────────────────────────────────────
# load_codegen_tasks 数据集加载
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadCodegenTasks:
    def test_loads_real_dataset(self):
        from evaluators.codegen_evaluator import load_codegen_tasks
        tasks = load_codegen_tasks()
        assert len(tasks) >= 20, f"数据集应有 ≥20 条，实际 {len(tasks)}"

    def test_task_has_required_fields(self):
        from evaluators.codegen_evaluator import load_codegen_tasks
        tasks = load_codegen_tasks()
        for t in tasks:
            assert "id" in t, f"任务缺少 id: {t}"
            assert "category" in t, f"任务 {t['id']} 缺少 category"
            assert "description" in t, f"任务 {t['id']} 缺少 description"
            assert "required_signatures" in t, f"任务 {t['id']} 缺少 required_signatures"
            assert "forbidden_patterns" in t, f"任务 {t['id']} 缺少 forbidden_patterns"

    def test_ids_unique(self):
        from evaluators.codegen_evaluator import load_codegen_tasks
        tasks = load_codegen_tasks()
        ids = [t["id"] for t in tasks]
        assert len(ids) == len(set(ids)), "存在重复的 task_id"

    def test_returns_empty_for_missing_file(self, tmp_path):
        from evaluators.codegen_evaluator import load_codegen_tasks
        tasks = load_codegen_tasks(yaml_path=tmp_path / "nonexistent.yaml")
        assert tasks == []

    def test_custom_yaml_path(self, tmp_path):
        import yaml
        custom_data = {"tasks": [{"id": "T1", "category": "L5_api", "difficulty": "easy",
                                   "description": "test", "required_signatures": [],
                                   "forbidden_patterns": []}]}
        p = tmp_path / "custom.yaml"
        p.write_text(yaml.dump(custom_data), encoding="utf-8")
        from evaluators.codegen_evaluator import load_codegen_tasks
        tasks = load_codegen_tasks(yaml_path=p)
        assert len(tasks) == 1
        assert tasks[0]["id"] == "T1"


# ─────────────────────────────────────────────────────────────────────────────
# JSON 修复（_repair_and_parse_json / _fix_json_format）
# ─────────────────────────────────────────────────────────────────────────────

class TestRepairAndParseJson:
    def _repair(self, text, ep_id=""):
        # 直接导入 unit_generate 的修复函数
        sys.path.insert(0, str(_MMS_ROOT))
        from mms.execution.unit_generate import _repair_and_parse_json
        return _repair_and_parse_json(text, ep_id=ep_id)

    def test_standard_json_array(self):
        data = [{"id": "U1", "title": "test"}]
        result = self._repair(json.dumps(data))
        assert result == data

    def test_markdown_wrapped_json(self):
        data = [{"id": "U1"}]
        text = f"```json\n{json.dumps(data)}\n```"
        result = self._repair(text)
        assert result == data

    def test_extracts_array_from_text(self):
        data = [{"id": "U1"}]
        text = f"以下是 DAG：\n{json.dumps(data)}\n这是一些说明文字。"
        result = self._repair(text)
        assert result == data

    def test_trailing_comma_fixed(self):
        text = '[{"id": "U1",}]'
        result = self._repair(text)
        assert result is not None
        assert result[0]["id"] == "U1"

    def test_python_true_false_none(self):
        text = '[{"active": True, "count": None, "deleted": False}]'
        result = self._repair(text)
        assert result is not None
        assert result[0]["active"] is True
        assert result[0]["count"] is None

    def test_returns_none_for_garbage(self):
        result = self._repair("这完全不是 JSON 内容 !!!@#$")
        assert result is None

    def test_empty_string_returns_none(self):
        result = self._repair("")
        assert result is None

    def test_object_with_units_key(self):
        data = {"units": [{"id": "U1"}], "extra": "ignored"}
        result = self._repair(json.dumps(data))
        assert result == [{"id": "U1"}]
