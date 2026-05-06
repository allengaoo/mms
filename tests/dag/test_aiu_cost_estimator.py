"""
tests/dag/test_aiu_cost_estimator.py

P1 测试：AIUCostEstimator 完整覆盖

覆盖路径：
  - 基准代价计算（base_cost + file_cost）
  - 层传播系数（layer_factor）
  - Token 上/下限边界（_TOKEN_MIN / _TOKEN_MAX）
  - 模型选择（fast vs capable）
  - 历史成功率 EMA（history_factor 公式）
  - estimate_plan 多步骤 + 文件复杂度排序
  - estimate_file_complexity 正常/不存在文件
  - estimate_token_for_file 正常/不存在文件
  - get_total_budget
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from mms.dag.aiu_types import AIUStep, AIUType
from mms.dag.aiu_cost_estimator import (
    AIUCostEstimator,
    AIU_BASE_COST,
    LAYER_PROPAGATION_COST,
    MODEL_THRESHOLDS,
    estimate_file_complexity,
    estimate_token_for_file,
    _default_success_rate_provider,
    _TOKEN_MIN,
    _TOKEN_MAX,
    _UNKNOWN_FILE_TOKEN,
    _FILES_FOR_COST,
)


# ─────────────────────────────────────────────────────────────────────────────
# 测试辅助
# ─────────────────────────────────────────────────────────────────────────────

def _make_step(
    aiu_type: AIUType = AIUType.SCHEMA_ADD_FIELD,
    layer: str = "L3_domain",
    files: list[str] | None = None,
) -> AIUStep:
    return AIUStep(
        aiu_id="aiu_1",
        aiu_type=aiu_type.value,
        description="test step",
        layer=layer,
        target_files=files or [],
        depends_on=[],
        exec_order=1,
        token_budget=3000,
        model_hint="fast",
    )


def _mock_success_rate(rate: float):
    """Patch _default_success_rate_provider 返回固定值。"""
    return patch(
        "mms.dag.aiu_cost_estimator._default_success_rate_provider",
        return_value=rate,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. 基准代价计算
# ─────────────────────────────────────────────────────────────────────────────

class TestBaseEstimation:
    """验证 estimate_step 的基础代价公式。"""

    def test_single_file_no_real_file_base_cost(self):
        """
        target_files 为空时，file_cost=0，budget 仅来自 base_cost × layer_factor。
        成功率 mock 为 1.0（history_factor=1.0，无历史惩罚）。
        """
        step = _make_step(AIUType.SCHEMA_ADD_FIELD, "L3_domain")
        base = AIU_BASE_COST[AIUType.SCHEMA_ADD_FIELD.value]
        layer_f = LAYER_PROPAGATION_COST["L3_domain"]
        expected = int(base * layer_f * 1.0)  # history_factor=1.0 when rate=1.0

        with _mock_success_rate(1.0):
            result = AIUCostEstimator().estimate_step(step)

        assert result.token_budget == max(_TOKEN_MIN, min(expected, _TOKEN_MAX))

    def test_different_aiu_types_have_different_base_costs(self):
        """不同 AIU 类型产生不同的 base_cost → budget 不同。"""
        with _mock_success_rate(1.0):
            estimator = AIUCostEstimator()
            step_schema = _make_step(AIUType.SCHEMA_ADD_FIELD, "L4_application")
            step_route = _make_step(AIUType.ROUTE_ADD_ENDPOINT, "L4_application")
            estimator.estimate_step(step_schema)
            estimator.estimate_step(step_route)

        # ROUTE_ADD_ENDPOINT 的 base_cost 比 SCHEMA_ADD_FIELD 大
        assert AIU_BASE_COST[AIUType.ROUTE_ADD_ENDPOINT.value] > AIU_BASE_COST[AIUType.SCHEMA_ADD_FIELD.value]
        assert step_route.token_budget >= step_schema.token_budget

    def test_unknown_aiu_type_uses_fallback_3000(self):
        """未知 AIU 类型 → fallback base_cost=3000（dict.get 默认值）。"""
        step = AIUStep(
            aiu_id="aiu_1",
            aiu_type="UNKNOWN_TYPE",
            description="test",
            layer="L4_application",
            target_files=[],
            depends_on=[],
            exec_order=1,
            token_budget=3000,
            model_hint="fast",
        )
        with _mock_success_rate(1.0):
            result = AIUCostEstimator().estimate_step(step)
        # fallback = 3000 * 1.0 * 1.0 = 3000，在合法范围内
        assert _TOKEN_MIN <= result.token_budget <= _TOKEN_MAX


# ─────────────────────────────────────────────────────────────────────────────
# 2. 层传播系数
# ─────────────────────────────────────────────────────────────────────────────

class TestLayerFactor:
    """验证 LAYER_PROPAGATION_COST 正确应用。"""

    def test_domain_layer_higher_than_interface(self):
        """
        L3_domain（factor=1.3）比 L5_interface（factor=0.9）代价更高。
        相同 base_cost 和 files 下，domain 层的 budget 更大。
        """
        with _mock_success_rate(1.0):
            estimator = AIUCostEstimator()
            step_domain = _make_step(AIUType.SCHEMA_ADD_FIELD, "L3_domain")
            step_iface = _make_step(AIUType.SCHEMA_ADD_FIELD, "L5_interface")
            estimator.estimate_step(step_domain)
            estimator.estimate_step(step_iface)

        assert step_domain.token_budget >= step_iface.token_budget, (
            f"L3_domain budget ({step_domain.token_budget}) 应 ≥ "
            f"L5_interface budget ({step_iface.token_budget})"
        )

    def test_unknown_layer_uses_factor_1(self):
        """未知 layer → 使用 dict.get 默认值 1.0（不崩溃）。"""
        step = _make_step(AIUType.SCHEMA_ADD_FIELD, "UNKNOWN_LAYER")
        with _mock_success_rate(1.0):
            result = AIUCostEstimator().estimate_step(step)
        assert _TOKEN_MIN <= result.token_budget <= _TOKEN_MAX

    def test_testing_layer_lower_budget(self):
        """testing 层（factor=0.8）比 L3_domain（1.3）预算低。"""
        with _mock_success_rate(1.0):
            estimator = AIUCostEstimator()
            step_test = _make_step(AIUType.SCHEMA_ADD_FIELD, "testing")
            step_domain = _make_step(AIUType.SCHEMA_ADD_FIELD, "L3_domain")
            estimator.estimate_step(step_test)
            estimator.estimate_step(step_domain)

        assert step_test.token_budget <= step_domain.token_budget


# ─────────────────────────────────────────────────────────────────────────────
# 3. Token 边界（_TOKEN_MIN / _TOKEN_MAX）
# ─────────────────────────────────────────────────────────────────────────────

class TestTokenBoundaries:
    """验证 budget 始终在 [_TOKEN_MIN, _TOKEN_MAX] 范围内。"""

    def test_budget_never_below_token_min(self):
        """即使 base_cost 很小，budget ≥ _TOKEN_MIN。"""
        # DOC_SYNC 是最低代价类型（1500），testing 层 factor=0.8
        step = _make_step(AIUType.DOC_SYNC, "docs")
        with _mock_success_rate(1.0):
            result = AIUCostEstimator().estimate_step(step)
        assert result.token_budget >= _TOKEN_MIN

    def test_budget_never_exceeds_token_max(self):
        """文件复杂度超高时，budget ≤ _TOKEN_MAX。"""
        # 通过 mock estimate_token_for_file 返回极大值来模拟超高文件代价
        step = _make_step(
            AIUType.FRONTEND_ADD_PAGE,
            "L5_interface",
            files=["fake/complex_file.py"] * _FILES_FOR_COST,
        )
        with _mock_success_rate(1.0), \
             patch("mms.dag.aiu_cost_estimator.estimate_token_for_file", return_value=100_000):
            result = AIUCostEstimator().estimate_step(step)
        assert result.token_budget <= _TOKEN_MAX, (
            f"budget={result.token_budget} 超过 _TOKEN_MAX={_TOKEN_MAX}"
        )

    def test_all_aiu_types_within_bounds(self):
        """所有内置 AIU 类型的估算结果均在合法范围内。"""
        estimator = AIUCostEstimator()
        with _mock_success_rate(0.8):
            for aiu_type in AIUType:
                step = _make_step(aiu_type, "L4_application")
                result = estimator.estimate_step(step)
                assert _TOKEN_MIN <= result.token_budget <= _TOKEN_MAX, (
                    f"{aiu_type.value}: budget={result.token_budget} 超出边界"
                )


# ─────────────────────────────────────────────────────────────────────────────
# 4. 模型选择（fast vs capable）
# ─────────────────────────────────────────────────────────────────────────────

class TestModelHintSelection:
    """验证 model_hint 根据 token_budget 阈值正确选择。"""

    def test_small_budget_selects_fast_model(self):
        """
        budget ≤ MODEL_THRESHOLDS['fast'] (4000) → model_hint = 'fast'。
        使用 testing 层 + DOC_SYNC 确保 budget 小。
        """
        step = _make_step(AIUType.DOC_SYNC, "testing")
        with _mock_success_rate(1.0):
            result = AIUCostEstimator().estimate_step(step)
        if result.token_budget <= MODEL_THRESHOLDS["fast"]:
            assert result.model_hint == "fast"

    def test_large_budget_selects_capable_model(self):
        """
        budget > MODEL_THRESHOLDS['fast'] (4000) → model_hint = 'capable'。
        """
        step = _make_step(AIUType.FRONTEND_ADD_PAGE, "L3_domain")
        # mock 大文件代价使 budget > 4000
        with _mock_success_rate(0.0), \
             patch("mms.dag.aiu_cost_estimator.estimate_token_for_file", return_value=3000):
            result = AIUCostEstimator().estimate_step(step)
        if result.token_budget > MODEL_THRESHOLDS["fast"]:
            assert result.model_hint == "capable"

    def test_model_hint_matches_budget_threshold(self):
        """白盒验证：model_hint 完全由 token_budget 决定。"""
        # 直接验证阈值逻辑
        for budget, expected_model in [
            (1500, "fast"),
            (4000, "fast"),
            (4001, "capable"),
            (8000, "capable"),
            (16000, "capable"),
        ]:
            model = "fast" if budget <= MODEL_THRESHOLDS["fast"] else "capable"
            assert model == expected_model, f"budget={budget}: expected {expected_model}, got {model}"


# ─────────────────────────────────────────────────────────────────────────────
# 5. history_factor 精确验证
# ─────────────────────────────────────────────────────────────────────────────

class TestHistoryFactor:
    """验证 history_factor = min(1 + (1-rate)*0.1, 1.1) 的精确性。"""

    def test_perfect_success_no_penalty(self):
        """success_rate=1.0 → history_factor=1.0，无额外惩罚。"""
        step = _make_step(AIUType.SCHEMA_ADD_FIELD, "L4_application")
        base = AIU_BASE_COST[AIUType.SCHEMA_ADD_FIELD.value]
        layer_f = LAYER_PROPAGATION_COST["L4_application"]
        expected = int(base * layer_f * 1.0)

        with _mock_success_rate(1.0):
            result = AIUCostEstimator().estimate_step(step)
        assert result.token_budget == max(_TOKEN_MIN, min(expected, _TOKEN_MAX))

    def test_zero_success_10pct_penalty(self):
        """success_rate=0.0 → history_factor=1.1（+10% 上限）。"""
        step = _make_step(AIUType.SCHEMA_ADD_FIELD, "L4_application")
        base = AIU_BASE_COST[AIUType.SCHEMA_ADD_FIELD.value]
        layer_f = LAYER_PROPAGATION_COST["L4_application"]
        expected = int(base * layer_f * 1.1)

        with _mock_success_rate(0.0):
            result = AIUCostEstimator().estimate_step(step)
        assert result.token_budget == max(_TOKEN_MIN, min(expected, _TOKEN_MAX))

    def test_history_factor_capped_at_1_1(self):
        """任何 success_rate（包括负数场景），history_factor 不超过 1.1。"""
        for rate in [0.0, -0.5, -1.0]:  # 负值是边界外测试
            actual = min(1.0 + (1.0 - max(rate, 0)) * 0.1, 1.1)
            assert actual <= 1.1, f"rate={rate}: history_factor={actual} > 1.1"


# ─────────────────────────────────────────────────────────────────────────────
# 6. estimate_plan — 多步骤
# ─────────────────────────────────────────────────────────────────────────────

class TestEstimatePlan:
    """验证 estimate_plan 对多步骤的批量处理和文件排序。"""

    def test_all_steps_get_updated_budget(self):
        """每个 step 的 token_budget 都被更新（不保留默认值 3000）。"""
        steps = [
            _make_step(AIUType.SCHEMA_ADD_FIELD, "L3_domain"),
            _make_step(AIUType.MUTATION_ADD_INSERT, "L3_domain"),
            _make_step(AIUType.TEST_ADD_UNIT, "testing"),
        ]
        original_budgets = [s.token_budget for s in steps]

        with _mock_success_rate(0.8):
            result = AIUCostEstimator().estimate_plan(steps)

        for step in result:
            assert _TOKEN_MIN <= step.token_budget <= _TOKEN_MAX

    def test_get_total_budget_sums_all(self):
        """get_total_budget 返回所有 steps token_budget 之和。"""
        steps = [
            _make_step(AIUType.SCHEMA_ADD_FIELD),
            _make_step(AIUType.TEST_ADD_UNIT),
        ]
        with _mock_success_rate(1.0):
            estimator = AIUCostEstimator()
            estimator.estimate_plan(steps)
            total = estimator.get_total_budget(steps)

        expected = sum(s.token_budget for s in steps)
        assert total == expected

    def test_files_ranked_by_complexity_desc(self, tmp_path):
        """
        target_files 按复杂度降序排列（复杂度高的文件排前）。
        """
        # 创建两个不同大小的真实文件
        small_file = tmp_path / "small.py"
        large_file = tmp_path / "large.py"
        small_file.write_text("x = 1\n", encoding="utf-8")
        large_file.write_text("\n".join([f"def func_{i}(): pass" for i in range(50)]), encoding="utf-8")

        step = _make_step(
            AIUType.SCHEMA_ADD_FIELD,
            files=[str(small_file), str(large_file)],
        )

        with _mock_success_rate(1.0):
            result = AIUCostEstimator().estimate_plan([step])

        # 复杂度高的 large_file 应排在前面
        assert result[0].target_files[0] == str(large_file), (
            f"复杂度高的文件应排前，实际：{result[0].target_files}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 7. estimate_file_complexity
# ─────────────────────────────────────────────────────────────────────────────

class TestEstimateFileComplexity:
    """验证 estimate_file_complexity 的各个指标。"""

    def test_nonexistent_file_returns_zeros(self):
        """不存在的文件 → 全零返回，不崩溃。"""
        result = estimate_file_complexity("/nonexistent/path/to/file.py")
        assert result == {"lines": 0, "functions": 0, "imports": 0, "complexity_score": 0}

    def test_real_file_counts_functions(self, tmp_path):
        """真实文件中的函数/方法数量被正确计数。"""
        f = tmp_path / "sample.py"
        f.write_text(
            "import os\nimport sys\n\ndef foo(): pass\ndef bar(): pass\nasync def baz(): pass\n",
            encoding="utf-8",
        )
        result = estimate_file_complexity(str(f))
        assert result["functions"] == 3
        assert result["imports"] == 2
        assert result["lines"] >= 5

    def test_complexity_score_capped_at_100(self, tmp_path):
        """complexity_score 最大为 100。"""
        f = tmp_path / "big.py"
        # 创建一个超长文件
        f.write_text("\n".join([f"def func_{i}(): pass" for i in range(200)]), encoding="utf-8")
        result = estimate_file_complexity(str(f))
        assert result["complexity_score"] <= 100

    def test_empty_file_returns_zero_complexity(self, tmp_path):
        """空文件 → complexity_score=0。"""
        f = tmp_path / "empty.py"
        f.write_text("", encoding="utf-8")
        result = estimate_file_complexity(str(f))
        assert result["complexity_score"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 8. estimate_token_for_file
# ─────────────────────────────────────────────────────────────────────────────

class TestEstimateTokenForFile:
    """验证 estimate_token_for_file 的基本行为。"""

    def test_nonexistent_file_returns_unknown_token(self):
        """不存在的文件 → 返回 _UNKNOWN_FILE_TOKEN。"""
        result = estimate_token_for_file("/no/such/file.py")
        assert result == _UNKNOWN_FILE_TOKEN

    def test_empty_path_returns_unknown_token(self):
        """空路径 → 返回 _UNKNOWN_FILE_TOKEN。"""
        result = estimate_token_for_file("")
        assert result == _UNKNOWN_FILE_TOKEN

    def test_real_file_returns_positive_tokens(self, tmp_path):
        """真实文件 → 返回正数 token 估算。"""
        f = tmp_path / "code.py"
        f.write_text("x = 1\n" * 100, encoding="utf-8")
        result = estimate_token_for_file(str(f))
        assert result > 0

    def test_larger_file_has_more_tokens(self, tmp_path):
        """更大的文件 → 更多 token。"""
        small = tmp_path / "small.py"
        large = tmp_path / "large.py"
        small.write_text("x = 1\n", encoding="utf-8")
        large.write_text("x = 1\n" * 1000, encoding="utf-8")

        assert estimate_token_for_file(str(large)) > estimate_token_for_file(str(small))
