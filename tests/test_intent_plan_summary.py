"""
test_intent_plan_summary.py — 意图计划摘要 + 磁盘验证 + AIU 质量指标测试（EP-131）

测试覆盖：
  - disk_validate_confidence()：磁盘路径验证修正置信度
  - build_intent_plan_line()：计划摘要行生成
  - calc_aiu_decomp_precision()：AIU 分解精度
  - calc_aiu_decomp_recall()：AIU 分解召回率
  - calc_aiu_order_similarity()：AIU 顺序相似度
  - calc_cost_efficiency()：成本效率指标
  - _quick_syntax_check()：快速语法预验证（来自 unit_runner）
  - AiuOutputCarry：AIU 输出传递快照
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_MMS = _HERE.parent
sys.path.insert(0, str(_MMS))

from mms.memory.intent_classifier import (
    IntentResult,
    disk_validate_confidence,
    build_intent_plan_line,
)
from mms.execution.unit_runner import _quick_syntax_check, AiuOutputCarry, _extract_signature_snippet
from benchmark.src.metrics.aiu_quality import (
    calc_aiu_decomp_precision,
    calc_aiu_decomp_recall,
    calc_aiu_order_similarity,
    calc_cost_efficiency,
    safe_mean,
    _lcs_length,
)


# ── fixtures ─────────────────────────────────────────────────────────────────

def _make_intent_result(
    layer: str = "L4_service",
    operation: str = "create",
    confidence: float = 0.80,
    entry_files_hint: list = None,
    matched_rule_id: str = "test_rule",
) -> IntentResult:
    return IntentResult(
        layer=layer,
        operation=operation,
        confidence=confidence,
        entry_files_hint=entry_files_hint or [],
        matched_rule_id=matched_rule_id,
    )


# ── disk_validate_confidence ──────────────────────────────────────────────────

class TestDiskValidateConfidence:
    def test_boosts_confidence_when_majority_files_exist(self, tmp_path: Path):
        """≥50% 路径存在时，置信度 +0.10"""
        f1 = tmp_path / "backend" / "app" / "services" / "ontology_service.py"
        f1.parent.mkdir(parents=True)
        f1.write_text("# test")

        intent = _make_intent_result(
            confidence=0.75,
            entry_files_hint=[str(f1.relative_to(tmp_path)), "nonexistent/path.py"],
        )
        result = disk_validate_confidence(intent, root=tmp_path)

        # 1/2 存在 = 0.5 ≥ 0.5 → 置信度 +0.10
        assert result.confidence == pytest.approx(0.85, abs=0.01)

    def test_reduces_confidence_when_no_files_exist(self, tmp_path: Path):
        """所有路径不存在时，置信度 × 0.5"""
        intent = _make_intent_result(
            confidence=0.80,
            entry_files_hint=["nonexistent/a.py", "nonexistent/b.py"],
        )
        result = disk_validate_confidence(intent, root=tmp_path)

        assert result.confidence == pytest.approx(0.40, abs=0.01)

    def test_no_change_when_hint_empty(self, tmp_path: Path):
        """hint 为空时不修正置信度"""
        intent = _make_intent_result(confidence=0.75, entry_files_hint=[])
        result = disk_validate_confidence(intent, root=tmp_path)

        assert result.confidence == pytest.approx(0.75, abs=0.001)

    def test_does_not_exceed_0_95(self, tmp_path: Path):
        """置信度不超过 0.95"""
        f1 = tmp_path / "existing.py"
        f1.write_text("# test")

        intent = _make_intent_result(
            confidence=0.90,
            entry_files_hint=["existing.py"],
        )
        result = disk_validate_confidence(intent, root=tmp_path)

        assert result.confidence <= 0.95

    def test_does_not_go_below_0_10(self, tmp_path: Path):
        """置信度不低于 0.10"""
        intent = _make_intent_result(
            confidence=0.10,
            entry_files_hint=["nonexistent.py"],
        )
        result = disk_validate_confidence(intent, root=tmp_path)

        assert result.confidence >= 0.10

    def test_original_object_not_modified(self, tmp_path: Path):
        """原对象不被修改（返回新对象）"""
        intent = _make_intent_result(
            confidence=0.80,
            entry_files_hint=["nonexistent.py"],
        )
        original_confidence = intent.confidence
        result = disk_validate_confidence(intent, root=tmp_path)

        # 原对象未变
        assert intent.confidence == original_confidence
        # 返回新对象（置信度被修正）
        assert result.confidence != original_confidence


# ── build_intent_plan_line ────────────────────────────────────────────────────

class TestBuildIntentPlanLine:
    def test_includes_layer_and_operation(self):
        intent = _make_intent_result(layer="L4_service", operation="create")
        line = build_intent_plan_line(intent, unit_id="U1")
        assert "L4_service" in line
        assert "create" in line

    def test_marks_grey_area(self):
        """置信度 0.72（灰区）时标记 ⚠灰区"""
        intent = _make_intent_result(confidence=0.72)
        line = build_intent_plan_line(intent)
        assert "灰区" in line

    def test_no_grey_tag_for_high_confidence(self):
        """置信度 0.90 时不标记灰区"""
        intent = _make_intent_result(confidence=0.90)
        line = build_intent_plan_line(intent)
        assert "灰区" not in line

    def test_includes_unit_id_when_provided(self):
        intent = _make_intent_result()
        line = build_intent_plan_line(intent, unit_id="U3")
        assert "U3" in line


# ── _quick_syntax_check ───────────────────────────────────────────────────────

class TestQuickSyntaxCheck:
    def test_passes_valid_python(self):
        content = "def hello():\n    return 'world'\n"
        result = _quick_syntax_check({"test.py": content})
        assert result is None

    def test_detects_syntax_error_with_line_number(self):
        content = "def hello(\n    return 'world'\n"
        result = _quick_syntax_check({"test.py": content})
        assert result is not None
        assert "test.py" in result
        assert "语法错误" in result

    def test_skips_non_python_files(self):
        ts_content = "const x = function("  # 无效 TypeScript 但不是 .py
        result = _quick_syntax_check({"component.tsx": ts_content})
        assert result is None

    def test_skips_empty_content(self):
        result = _quick_syntax_check({"test.py": ""})
        assert result is None

    def test_skips_non_string_content(self):
        result = _quick_syntax_check({"test.py": None})  # type: ignore
        assert result is None

    def test_handles_empty_dict(self):
        result = _quick_syntax_check({})
        assert result is None


# ── AiuOutputCarry ────────────────────────────────────────────────────────────

class TestAiuOutputCarry:
    def test_extracts_class_signature_from_python(self):
        content = (
            "from pydantic import BaseModel\n\n"
            "class CreateObjectRequest(BaseModel):\n"
            "    name: str\n"
            "    description: str = ''\n\n"
            "class CreateObjectResponse(BaseModel):\n"
            "    id: str\n"
            "    name: str\n"
        )
        carry = AiuOutputCarry.from_generated_content(
            aiu_type="CONTRACT_ADD_REQUEST",
            file_path="backend/app/api/v1/schemas/ontology.py",
            content=content,
        )
        assert carry.aiu_type == "CONTRACT_ADD_REQUEST"
        assert "CreateObjectRequest" in carry.snippet or len(carry.snippet) > 0

    def test_snippet_within_800_chars(self):
        """carry snippet 严格 ≤ 800 字符"""
        long_content = "\n".join(
            [f"class Model{i}(BaseModel):\n    field_{i}: str" for i in range(50)]
        )
        carry = AiuOutputCarry.from_generated_content(
            aiu_type="CONTRACT_ADD_RESPONSE",
            file_path="test.py",
            content=long_content,
            max_chars=800,
        )
        assert len(carry.snippet) <= 800

    def test_to_prompt_block_contains_aiu_type(self):
        """prompt block 包含 AIU 类型信息"""
        carry = AiuOutputCarry.from_generated_content(
            aiu_type="CONTRACT_ADD_RESPONSE",
            file_path="test.py",
            content="class MyResponse:\n    pass\n",
        )
        block = carry.to_prompt_block()
        assert "CONTRACT_ADD_RESPONSE" in block

    def test_empty_content_produces_empty_snippet(self):
        carry = AiuOutputCarry.from_generated_content(
            aiu_type="SCHEMA_ADD_FIELD",
            file_path="test.py",
            content="",
        )
        assert carry.snippet == ""
        assert carry.to_prompt_block() == ""


# ── AIU 分解精度 ──────────────────────────────────────────────────────────────

class TestAiuDecompPrecision:
    def test_perfect_precision(self):
        """预测类型完全在期望集合中"""
        gt = {"expected_aiu_types": ["CONTRACT_ADD_REQUEST", "MUTATION_ADD_INSERT"]}
        result = calc_aiu_decomp_precision(
            ["CONTRACT_ADD_REQUEST", "MUTATION_ADD_INSERT"], gt
        )
        assert result == pytest.approx(1.0)

    def test_partial_precision(self):
        """2 个预测中 1 个正确"""
        gt = {"expected_aiu_types": ["CONTRACT_ADD_REQUEST", "MUTATION_ADD_INSERT"]}
        result = calc_aiu_decomp_precision(
            ["CONTRACT_ADD_REQUEST", "ROUTE_ADD_ENDPOINT"], gt
        )
        assert result == pytest.approx(0.5)

    def test_forbidden_aiu_applies_penalty(self):
        """出现 forbidden AIU 类型时触发惩罚"""
        gt = {
            "expected_aiu_types": ["CONTRACT_ADD_REQUEST"],
            "forbidden_aiu_types": ["SCHEMA_ADD_FIELD"],
        }
        result_without_forbidden = calc_aiu_decomp_precision(
            ["CONTRACT_ADD_REQUEST"], gt
        )
        result_with_forbidden = calc_aiu_decomp_precision(
            ["CONTRACT_ADD_REQUEST", "SCHEMA_ADD_FIELD"], gt
        )
        assert result_with_forbidden < result_without_forbidden

    def test_returns_nan_for_non_i_category(self):
        """非 I 类查询（无 expected_aiu_types）返回 NaN"""
        gt = {}  # 无 expected_aiu_types
        result = calc_aiu_decomp_precision(["CONTRACT_ADD_REQUEST"], gt)
        assert math.isnan(result)

    def test_empty_predicted_returns_zero(self):
        gt = {"expected_aiu_types": ["CONTRACT_ADD_REQUEST"]}
        result = calc_aiu_decomp_precision([], gt)
        assert result == 0.0


# ── AIU 分解召回率 ────────────────────────────────────────────────────────────

class TestAiuDecompRecall:
    def test_perfect_recall(self):
        gt = {"expected_aiu_types": ["A", "B"]}
        result = calc_aiu_decomp_recall(["A", "B"], gt)
        assert result == pytest.approx(1.0)

    def test_partial_recall(self):
        gt = {"expected_aiu_types": ["A", "B", "C"]}
        result = calc_aiu_decomp_recall(["A", "B"], gt)
        assert result == pytest.approx(2 / 3, abs=0.001)

    def test_returns_nan_when_no_expected(self):
        result = calc_aiu_decomp_recall(["A"], {})
        assert math.isnan(result)


# ── AIU 顺序相似度 ────────────────────────────────────────────────────────────

class TestAiuOrderSimilarity:
    def test_identical_sequence_returns_one(self):
        gt = {
            "expected_aiu_types": ["A", "B", "C"],
            "aiu_order_matters": True,
        }
        result = calc_aiu_order_similarity(["A", "B", "C"], gt)
        assert result == pytest.approx(1.0)

    def test_reversed_sequence_lower_score(self):
        gt = {
            "expected_aiu_types": ["A", "B", "C"],
            "aiu_order_matters": True,
        }
        forward = calc_aiu_order_similarity(["A", "B", "C"], gt)
        reversed_seq = calc_aiu_order_similarity(["C", "B", "A"], gt)
        # 逆序比正序得分低（LCS 更短）
        assert reversed_seq <= forward

    def test_returns_nan_when_order_not_matter(self):
        gt = {
            "expected_aiu_types": ["A", "B", "C"],
            "aiu_order_matters": False,
        }
        result = calc_aiu_order_similarity(["A", "B", "C"], gt)
        assert math.isnan(result)

    def test_returns_nan_when_no_expected_types(self):
        gt = {"aiu_order_matters": True}
        result = calc_aiu_order_similarity(["A", "B"], gt)
        assert math.isnan(result)


# ── 成本效率 ──────────────────────────────────────────────────────────────────

class TestCostEfficiency:
    def test_zero_llm_gives_higher_efficiency(self):
        """零 LLM 调用（Ontology RBO 命中）比有 LLM 调用的效率高"""
        eff_no_llm = calc_cost_efficiency(
            recall_at_k=0.8, context_tokens=1000, latency_ms=10, from_llm=False
        )
        eff_with_llm = calc_cost_efficiency(
            recall_at_k=0.8, context_tokens=1000, latency_ms=10, from_llm=True
        )
        assert eff_no_llm > eff_with_llm

    def test_higher_recall_gives_higher_efficiency(self):
        """更高的 Recall@K 对应更高的成本效率"""
        eff_high = calc_cost_efficiency(
            recall_at_k=1.0, context_tokens=1000, latency_ms=10, from_llm=False
        )
        eff_low = calc_cost_efficiency(
            recall_at_k=0.5, context_tokens=1000, latency_ms=10, from_llm=False
        )
        assert eff_high > eff_low

    def test_more_tokens_gives_lower_efficiency(self):
        """更多 token 消耗对应更低的成本效率"""
        eff_low_tokens = calc_cost_efficiency(
            recall_at_k=0.8, context_tokens=500, latency_ms=10, from_llm=False
        )
        eff_high_tokens = calc_cost_efficiency(
            recall_at_k=0.8, context_tokens=5000, latency_ms=10, from_llm=False
        )
        assert eff_low_tokens > eff_high_tokens

    def test_returns_zero_for_zero_recall(self):
        result = calc_cost_efficiency(
            recall_at_k=0.0, context_tokens=1000, latency_ms=10, from_llm=True
        )
        assert result == pytest.approx(0.0)


# ── safe_mean ─────────────────────────────────────────────────────────────────

class TestSafeMean:
    def test_ignores_nan_values(self):
        import math
        result = safe_mean([1.0, float("nan"), 0.5])
        assert result == pytest.approx(0.75)

    def test_returns_nan_when_all_nan(self):
        result = safe_mean([float("nan"), float("nan")])
        assert math.isnan(result)

    def test_empty_list_returns_nan(self):
        result = safe_mean([])
        assert math.isnan(result)


# ── LCS ───────────────────────────────────────────────────────────────────────

class TestLcsLength:
    def test_identical_sequences(self):
        assert _lcs_length(["A", "B", "C"], ["A", "B", "C"]) == 3

    def test_no_common_elements(self):
        assert _lcs_length(["A", "B"], ["C", "D"]) == 0

    def test_partial_overlap(self):
        assert _lcs_length(["A", "B", "C"], ["A", "C"]) == 2

    def test_empty_sequence(self):
        assert _lcs_length([], ["A", "B"]) == 0
        assert _lcs_length(["A", "B"], []) == 0
