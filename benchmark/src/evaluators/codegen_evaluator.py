"""
代码生成质量评估器 (EP-132)

4 级流水线评估：
  Level 1: AST 语法检查（_check_syntax）
  Level 2: 结构契约检查（_check_required_signatures + _check_forbidden_patterns）
  Level 3: 架构约束检查（_run_arch_check）
  Level 4: 参考测试通过率（_run_reference_tests）

设计原则：
  - 评估器本身不调用 LLM（避免评估偏差，EP-132 要求）
  - 层层递进：低级别失败不阻断高级别（独立评分）
  - 可插拔：每级可单独禁用（skip_level 参数）
  - 可扩展：新增检查项只需实现 _check_* 方法并在 evaluate() 中注册

依赖：
  - ast（Python 标准库，Level 1）
  - pytest（Level 4，可选）
  - scripts/mms/arch_check.py（Level 3，可选）
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

_HERE = Path(__file__).resolve().parent
_BENCHMARK_ROOT = _HERE.parent.parent
_MMS_ROOT = _BENCHMARK_ROOT.parent
_REF_CODE_DIR = _BENCHMARK_ROOT / "data" / "reference_code"

# 将 src/ 目录加入路径，支持绝对 import（benchmark/src/metrics/codegen_quality.py）
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

try:
    from metrics.codegen_quality import (  # type: ignore[import]
        CodegenMetricResult,
        LevelResult,
        aggregate_system_scores,
    )
except ImportError:
    from ..metrics.codegen_quality import (  # type: ignore[no-redef]
        CodegenMetricResult,
        LevelResult,
        aggregate_system_scores,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EvaluatorConfig:
    """
    评估器配置（可通过环境变量或参数覆盖，EP-132 硬编码全部在此统一管理）

    环境变量：
      MMS_EVAL_SKIP_LEVELS=3,4  # 跳过 Level 3 和 4
      MMS_EVAL_ARCH_CHECK_TIMEOUT=30  # arch_check 超时（秒）
      MMS_EVAL_PYTEST_TIMEOUT=60  # pytest 超时（秒）
    """
    skip_levels: Set[int] = field(default_factory=set)   # 要跳过的级别集合
    arch_check_timeout: int = 30                          # arch_check 超时（秒）
    pytest_timeout: int = 60                             # pytest 超时（秒）
    max_source_size_bytes: int = 100_000                 # 单文件最大大小（防御）

    @classmethod
    def from_env(cls) -> "EvaluatorConfig":
        """从环境变量读取配置"""
        skip_str = os.environ.get("MMS_EVAL_SKIP_LEVELS", "")
        skip_levels: Set[int] = set()
        if skip_str:
            for s in skip_str.split(","):
                s = s.strip()
                if s.isdigit():
                    skip_levels.add(int(s))

        arch_timeout = int(os.environ.get("MMS_EVAL_ARCH_CHECK_TIMEOUT", "30"))
        pytest_timeout = int(os.environ.get("MMS_EVAL_PYTEST_TIMEOUT", "60"))

        return cls(
            skip_levels=skip_levels,
            arch_check_timeout=arch_timeout,
            pytest_timeout=pytest_timeout,
        )


# ─────────────────────────────────────────────────────────────────────────────
# 评估器
# ─────────────────────────────────────────────────────────────────────────────

class CodeGenEvaluator:
    """
    代码生成质量 4 级流水线评估器（EP-132）

    用法：
        evaluator = CodeGenEvaluator()
        result = evaluator.evaluate(
            task_id="CG-001",
            task_spec=task_dict,
            generated_source="async def get_object_topology...",
            system_name="ontology",
            retrieval_tokens=1200,
        )
        print(result.codegen_score)
    """

    def __init__(self, config: Optional[EvaluatorConfig] = None) -> None:
        self.config = config or EvaluatorConfig.from_env()

    def evaluate(
        self,
        task_id: str,
        task_spec: Dict,
        generated_source: str,
        system_name: str = "",
        retrieval_tokens: int = 0,
    ) -> CodegenMetricResult:
        """
        对单条任务的生成代码执行 4 级评估。

        Args:
            task_id:          任务 ID（如 CG-001）
            task_spec:        YAML 任务配置字典
            generated_source: 待评估的生成代码字符串
            system_name:      索引系统名称（pageindex/hybrid_rag/ontology）
            retrieval_tokens: 该任务的检索 token 消耗

        Returns:
            CodegenMetricResult 包含 4 级结果和综合分
        """
        t0 = time.monotonic()

        result = CodegenMetricResult(
            task_id=task_id,
            category=task_spec.get("category", ""),
            difficulty=task_spec.get("difficulty", ""),
            system_name=system_name,
            retrieval_tokens=retrieval_tokens,
        )

        # 防御：源码过大拒绝评估
        if len(generated_source.encode("utf-8")) > self.config.max_source_size_bytes:
            result.level1_syntax = LevelResult(1, "syntax", 0, 1, errors=["源码超大小限制"], skipped=False)
            return result

        # Level 1: 语法检查
        if 1 not in self.config.skip_levels:
            result.level1_syntax = self._check_syntax(generated_source)
        else:
            result.level1_syntax = LevelResult(1, "syntax", 0, 0, skipped=True, skip_reason="配置跳过")

        # Level 2: 结构契约
        if 2 not in self.config.skip_levels:
            result.level2_contract = self._check_contracts(generated_source, task_spec)
        else:
            result.level2_contract = LevelResult(2, "contract", 0, 0, skipped=True, skip_reason="配置跳过")

        # Level 3: 架构约束（依赖 arch_check.py）
        if 3 not in self.config.skip_levels:
            result.level3_arch = self._run_arch_check(generated_source, task_spec)
        else:
            result.level3_arch = LevelResult(3, "arch_check", 0, 0, skipped=True, skip_reason="配置跳过")

        # Level 4: 参考测试（依赖 pytest + 参考测试文件）
        # v2.0: 同时计算 Pass@1 和 Resolve Rate
        if 4 not in self.config.skip_levels:
            l4 = self._run_reference_tests(generated_source, task_spec, task_id)
            result.level4_test = l4
            # Pass@1: 首次 L4 测试通过 = pass_rate == 1.0（全部 pytest 通过）
            if not l4.skipped and l4.pass_rate == 1.0:
                result._first_attempt_passed = True
                result._resolved = True
                result._feedback_rounds = 0
            else:
                # Resolve Rate: 模拟 Feedback 回退（Benchmark 中以 L4 结果代理）
                # 在真实 UnitRunner 集成中，_feedback_rounds 由 runner 设置
                # Benchmark 简化：若 L4 不通过，resolve=False，feedback_rounds=max_retries
                max_fb = getattr(self.config, 'max_feedback_rounds', 3)
                result._first_attempt_passed = False
                result._resolved = False
                result._feedback_rounds = max_fb
        else:
            result.level4_test = LevelResult(4, "test_pass", 0, 0, skipped=True, skip_reason="配置跳过")

        result.latency_ms = round((time.monotonic() - t0) * 1000, 1)
        result.generated_tokens = _estimate_tokens(generated_source)

        return result

    # ── Level 1: AST 语法检查 ────────────────────────────────────────────────

    def _check_syntax(self, source: str) -> LevelResult:
        """
        Level 1：使用 Python ast 模块验证语法正确性。

        评分：通过 = 1/1；失败 = 0/1
        """
        if not source.strip():
            return LevelResult(1, "syntax", 0, 1, errors=["生成代码为空"])

        try:
            ast.parse(source)
            return LevelResult(1, "syntax", 1, 1)
        except SyntaxError as e:
            return LevelResult(
                1, "syntax", 0, 1,
                errors=[f"SyntaxError at line {e.lineno}: {e.msg}"],
            )
        except Exception as e:
            return LevelResult(1, "syntax", 0, 1, errors=[f"解析异常: {e}"])

    # ── Level 2: 结构契约检查 ────────────────────────────────────────────────

    def _check_contracts(self, source: str, task_spec: Dict) -> LevelResult:
        """
        Level 2：检查 required_signatures（必须包含）和 forbidden_patterns（禁止出现）。

        评分公式：
          passed = 通过的检查项数
          total = len(required_signatures) + len(forbidden_patterns)
          pass_rate = passed / total
        """
        required = task_spec.get("required_signatures", []) or []
        forbidden = task_spec.get("forbidden_patterns", []) or []
        total = len(required) + len(forbidden)

        if total == 0:
            return LevelResult(2, "contract", 0, 0, skipped=True, skip_reason="无契约定义")

        passed = 0
        errors: List[str] = []

        for sig in required:
            if sig and sig in source:
                passed += 1
            elif sig:
                errors.append(f"缺少必需签名: {sig!r}")

        for pattern in forbidden:
            if pattern and pattern not in source:
                passed += 1
            elif pattern:
                errors.append(f"存在禁止模式: {pattern!r}")

        return LevelResult(2, "contract", passed, total, errors=errors)

    # ── Level 3: 架构约束检查 ────────────────────────────────────────────────

    def _run_arch_check(self, source: str, task_spec: Dict) -> LevelResult:
        """
        Level 3：通过 arch_check.py --snippet 检查架构约束。

        注意：arch_check.py 需要实际项目目录，在 benchmark 环境中以
        "无项目目录"模式运行（检查文本级约束，如 import 禁止、信封格式等）。

        如果 arch_check.py 不可用，改为基于文本的简单检查。
        """
        arch_rules = task_spec.get("arch_check_rules", []) or []
        if not arch_rules:
            return LevelResult(3, "arch_check", 0, 0, skipped=True, skip_reason="无架构约束要求")

        arch_check_path = _MMS_ROOT / "arch_check.py"
        if not arch_check_path.exists():
            # 回退：基于文本的轻量架构检查
            return self._fallback_arch_check(source, arch_rules)

        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
                f.write(source)
                tmp_path = f.name

            result = subprocess.run(
                [sys.executable, str(arch_check_path), "--snippet", tmp_path, "--rules",
                 ",".join(arch_rules)],
                capture_output=True,
                text=True,
                timeout=self.config.arch_check_timeout,
            )

            os.unlink(tmp_path)

            if result.returncode == 0:
                return LevelResult(3, "arch_check", len(arch_rules), len(arch_rules))
            else:
                errors = [line for line in result.stdout.splitlines() if "FAIL" in line or "ERROR" in line]
                passed = len(arch_rules) - len(errors)
                return LevelResult(3, "arch_check", max(0, passed), len(arch_rules), errors=errors[:10])

        except subprocess.TimeoutExpired:
            return LevelResult(3, "arch_check", 0, len(arch_rules), errors=["arch_check 超时"])
        except Exception:
            return self._fallback_arch_check(source, arch_rules)

    def _fallback_arch_check(self, source: str, arch_rules: List[str]) -> LevelResult:
        """
        arch_check.py 不可用时的文本级轻量检查。

        规则映射（EP-132）：
          AC-1: 禁止 import pymilvus/aiokafka/elasticsearch
          AC-2: 必须有 ctx: RequestContext / ctx: SecurityContext 参数
          AC-3: 必须有 audit_service 调用
          AC-4: 必须有 ResponseSchema / success_response / ResponseHelper
        """
        if not arch_rules:
            return LevelResult(3, "arch_check", 0, 0, skipped=True, skip_reason="无架构约束要求")

        rule_checks = {
            "AC-1": lambda s: (
                "import pymilvus" not in s
                and "import aiokafka" not in s
                and "import elasticsearch" not in s
            ),
            "AC-2": lambda s: (
                "ctx: RequestContext" in s
                or "ctx: SecurityContext" in s
                or "Depends(get_context)" in s
            ),
            "AC-3": lambda s: "audit_service" in s,
            "AC-4": lambda s: (
                "ResponseSchema" in s
                or "success_response" in s
                or "ResponseHelper" in s
                or "PaginatedData" in s
            ),
        }

        passed = 0
        errors: List[str] = []
        for rule in arch_rules:
            checker = rule_checks.get(rule)
            if checker is None:
                passed += 1  # 未知规则视为通过（宽松）
            elif checker(source):
                passed += 1
            else:
                errors.append(f"架构约束违规: {rule}")

        return LevelResult(3, "arch_check", passed, len(arch_rules), errors=errors)

    # ── Level 4: 参考测试 ─────────────────────────────────────────────────────

    def _run_reference_tests(
        self,
        source: str,
        task_spec: Dict,
        task_id: str,
    ) -> LevelResult:
        """
        Level 4：将生成代码注入测试套件，运行 pytest 测试。

        流程：
          1. 定位参考测试文件（reference_code/CG-NNN/test_*.py）
          2. 创建临时目录，写入生成代码（generated.py）和测试文件
          3. 运行 pytest，解析测试结果（passed / total）
          4. 返回 LevelResult

        注意：
          - 测试文件中的 `generated_source` fixture 通过 conftest.py 注入
          - 不依赖实际 MDP 后端环境（纯结构/签名检查）
        """
        test_code_path_str = task_spec.get("test_code_path")
        if not test_code_path_str:
            return LevelResult(4, "test_pass", 0, 0, skipped=True, skip_reason="无参考测试文件配置")

        test_path = _REF_CODE_DIR / task_id / Path(test_code_path_str).name
        if not test_path.exists():
            return LevelResult(
                4, "test_pass", 0, 0,
                skipped=True,
                skip_reason=f"参考测试文件不存在: {test_path.relative_to(_BENCHMARK_ROOT)}",
            )

        try:
            with tempfile.TemporaryDirectory(prefix="mms_codegen_eval_") as tmpdir:
                tmp = Path(tmpdir)

                # 写入 conftest.py：注入 generated_source fixture
                conftest = tmp / "conftest.py"
                conftest.write_text(
                    f'import pytest\n\n@pytest.fixture\ndef generated_source():\n    return {json.dumps(source)}\n',
                    encoding="utf-8",
                )

                # 复制测试文件
                test_dest = tmp / test_path.name
                test_dest.write_text(test_path.read_text(encoding="utf-8"), encoding="utf-8")

                # 运行 pytest（JSON 报告）
                report_path = tmp / "report.json"
                result = subprocess.run(
                    [
                        sys.executable, "-m", "pytest",
                        str(test_dest),
                        f"--json-report",
                        f"--json-report-file={report_path}",
                        "-q", "--tb=no",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=self.config.pytest_timeout,
                    cwd=str(tmp),
                )

                # 解析 pytest JSON 报告
                if report_path.exists():
                    return _parse_pytest_json_report(report_path)

                # 降级：解析 pytest 文本输出
                return _parse_pytest_text_output(result.stdout + result.stderr)

        except subprocess.TimeoutExpired:
            return LevelResult(4, "test_pass", 0, 1, errors=[f"pytest 超时（>{self.config.pytest_timeout}s）"])
        except Exception as e:
            return LevelResult(4, "test_pass", 0, 1, errors=[f"测试运行异常: {e}"])


# ─────────────────────────────────────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────────────────────────────────────

def _parse_pytest_json_report(report_path: Path) -> LevelResult:
    """解析 pytest-json-report 输出"""
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
        summary = data.get("summary", {})
        passed = summary.get("passed", 0)
        total = summary.get("collected", 0)
        failed_items = [
            t.get("nodeid", "") for t in data.get("tests", [])
            if t.get("outcome") != "passed"
        ]
        errors = [f"FAILED: {n}" for n in failed_items[:5]]
        return LevelResult(4, "test_pass", passed, total, errors=errors)
    except Exception as e:
        return LevelResult(4, "test_pass", 0, 1, errors=[f"JSON 报告解析失败: {e}"])


def _parse_pytest_text_output(output: str) -> LevelResult:
    """降级：从 pytest 文本输出解析结果"""
    passed = 0
    total = 0

    # 匹配 "3 passed, 1 failed" 等模式
    m = re.search(r"(\d+) passed", output)
    if m:
        passed = int(m.group(1))
    m2 = re.search(r"(\d+) (?:failed|error)", output)
    failed = int(m2.group(1)) if m2 else 0
    total = passed + failed or max(1, passed)

    errors: List[str] = []
    if failed > 0:
        errors.append(f"{failed} 个测试失败")

    return LevelResult(4, "test_pass", passed, total, errors=errors)


def _estimate_tokens(text: str) -> int:
    """简单 token 估算（按 4 字符/token）"""
    return max(1, len(text) // 4)


def load_codegen_tasks(yaml_path: Optional[Path] = None) -> List[Dict]:
    """
    加载代码生成测试数据集（EP-132）。

    Args:
        yaml_path: YAML 文件路径，默认使用 benchmark/data/queries_codegen.yaml

    Returns:
        任务字典列表
    """
    import yaml  # type: ignore[import]

    if yaml_path is None:
        yaml_path = _BENCHMARK_ROOT / "data" / "queries_codegen.yaml"

    if not yaml_path.exists():
        return []

    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return data.get("tasks", []) if isinstance(data, dict) else []
