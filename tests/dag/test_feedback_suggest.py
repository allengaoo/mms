"""
tests/dag/test_feedback_suggest.py

P2 测试：AIUFeedbackStore.suggest() 策略逻辑

覆盖路径：
  - 样本不足（< _SUGGEST_MIN_SAMPLES）→ 返回 default，不做调整
  - 低成功率（< 0.5）→ model_hint 升级为 capable，附带 warning 文本
  - token 低估（actual >> estimated）→ recommended_tokens 上调
  - token 高估（actual << estimated）→ recommended_tokens 下调
  - 正常估算误差（-30% < error < +20%）→ 保持原 estimated_tokens
  - confidence 随样本数线性增长（样本越多 confidence 越高）
  - token budget 始终在 [_TOKEN_MIN, _TOKEN_MAX] 范围内
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from mms.dag.aiu_feedback import (
    AIUFeedbackStore,
    _SUGGEST_MIN_SAMPLES,
    _WARN_SUCCESS_RATE_THRESHOLD,
    _TOKEN_LOW_ESTIMATE_THRESHOLD,
    _TOKEN_HIGH_ESTIMATE_THRESHOLD,
    _TOKEN_MIN,
    _TOKEN_MAX,
    _FAST_MODEL_MAX_TOKENS,
)


# ─────────────────────────────────────────────────────────────────────────────
# 测试辅助
# ─────────────────────────────────────────────────────────────────────────────

def _make_store(tmp_path: Path) -> AIUFeedbackStore:
    return AIUFeedbackStore(path=tmp_path / "feedback.jsonl")


def _record_batch(
    store: AIUFeedbackStore,
    aiu_type: str,
    success: bool,
    n: int,
    actual_tokens: int = 2000,
    estimated_tokens: int = 2000,
) -> None:
    for i in range(n):
        store.record(
            ep_id="ep_test",
            unit_id="unit_1",
            aiu_id=f"aiu_{i}",
            aiu_type=aiu_type,
            success=success,
            actual_tokens=actual_tokens,
            estimated_tokens=estimated_tokens,
        )


# ─────────────────────────────────────────────────────────────────────────────
# 1. 样本不足 → 返回 default
# ─────────────────────────────────────────────────────────────────────────────

class TestSuggestBelowMinSamples:
    def test_no_records_returns_default(self, tmp_path):
        """无任何历史记录 → 返回默认值（estimated_tokens 原样返回）。"""
        store = _make_store(tmp_path)
        result = store.suggest("SCHEMA_ADD_FIELD", estimated_tokens=3000)

        assert result["recommended_tokens"] == 3000
        assert result["warning"] is None
        assert result["confidence"] == 0.5  # 默认置信度

    def test_fewer_than_min_samples_returns_default(self, tmp_path):
        """记录数 < _SUGGEST_MIN_SAMPLES → 返回默认值。"""
        store = _make_store(tmp_path)
        _record_batch(store, "SCHEMA_ADD_FIELD", success=True, n=_SUGGEST_MIN_SAMPLES - 1)
        result = store.suggest("SCHEMA_ADD_FIELD", estimated_tokens=2500)

        assert result["recommended_tokens"] == 2500  # 不做调整

    def test_exactly_min_samples_triggers_suggest(self, tmp_path):
        """记录数 == _SUGGEST_MIN_SAMPLES → 开始调整（不再返回 default）。"""
        store = _make_store(tmp_path)
        _record_batch(
            store, "SCHEMA_ADD_FIELD", success=True, n=_SUGGEST_MIN_SAMPLES,
            actual_tokens=2000, estimated_tokens=2000,
        )
        result = store.suggest("SCHEMA_ADD_FIELD", estimated_tokens=2000)

        # 误差接近 0，recommended_tokens 接近 2000
        assert abs(result["recommended_tokens"] - 2000) <= 200


# ─────────────────────────────────────────────────────────────────────────────
# 2. 低成功率 → 升级为 capable 模型
# ─────────────────────────────────────────────────────────────────────────────

class TestSuggestLowSuccessRate:
    def test_low_success_upgrades_to_capable(self, tmp_path):
        """
        success_rate < _WARN_SUCCESS_RATE_THRESHOLD → model_hint = 'capable'，
        warning 包含成功率信息。
        """
        store = _make_store(tmp_path)
        # 足够的样本，全部失败 → success_rate = 0.0
        _record_batch(store, "MUTATION_ADD_INSERT", success=False, n=_SUGGEST_MIN_SAMPLES)
        result = store.suggest("MUTATION_ADD_INSERT", estimated_tokens=3000)

        assert result["recommended_model"] == "capable", (
            "低成功率应升级为 capable 模型"
        )
        assert result["warning"] is not None, "低成功率应附带 warning 文本"
        assert "capable" in result["warning"] or "历史成功率" in result["warning"]

    def test_high_success_no_warning(self, tmp_path):
        """
        success_rate ≥ _WARN_SUCCESS_RATE_THRESHOLD → warning = None。
        """
        store = _make_store(tmp_path)
        _record_batch(store, "DOC_SYNC", success=True, n=_SUGGEST_MIN_SAMPLES)
        result = store.suggest("DOC_SYNC", estimated_tokens=2000)

        assert result["warning"] is None, (
            "高成功率不应产生 warning"
        )

    def test_success_rate_in_result(self, tmp_path):
        """suggested 结果包含 historical_success_rate 字段。"""
        store = _make_store(tmp_path)
        _record_batch(store, "TEST_ADD_UNIT", success=True, n=_SUGGEST_MIN_SAMPLES)
        result = store.suggest("TEST_ADD_UNIT", estimated_tokens=2000)

        assert "historical_success_rate" in result
        assert 0.0 <= result["historical_success_rate"] <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# 3. Token 估算误差调整
# ─────────────────────────────────────────────────────────────────────────────

class TestSuggestTokenAdjustment:
    def test_underestimated_tokens_upsize(self, tmp_path):
        """
        actual >> estimated（低估超过 _TOKEN_LOW_ESTIMATE_THRESHOLD=20%）
        → recommended_tokens > estimated_tokens。
        """
        store = _make_store(tmp_path)
        estimated = 2000
        # actual = estimated * 1.5（超过 20% 低估阈值）
        actual = int(estimated * 1.5)
        _record_batch(
            store, "SCHEMA_ADD_FIELD", success=True, n=_SUGGEST_MIN_SAMPLES,
            actual_tokens=actual, estimated_tokens=estimated,
        )
        result = store.suggest("SCHEMA_ADD_FIELD", estimated_tokens=estimated)

        assert result["recommended_tokens"] > estimated, (
            f"低估场景：recommended({result['recommended_tokens']}) 应 > estimated({estimated})"
        )

    def test_overestimated_tokens_downsize(self, tmp_path):
        """
        actual << estimated（高估超过 _TOKEN_HIGH_ESTIMATE_THRESHOLD=30%）
        → recommended_tokens < estimated_tokens。
        """
        store = _make_store(tmp_path)
        estimated = 4000
        # actual = estimated * 0.5（超过 30% 高估阈值）
        actual = int(estimated * 0.5)
        _record_batch(
            store, "SCHEMA_ADD_FIELD", success=True, n=_SUGGEST_MIN_SAMPLES,
            actual_tokens=actual, estimated_tokens=estimated,
        )
        result = store.suggest("SCHEMA_ADD_FIELD", estimated_tokens=estimated)

        assert result["recommended_tokens"] < estimated, (
            f"高估场景：recommended({result['recommended_tokens']}) 应 < estimated({estimated})"
        )

    def test_normal_error_keeps_original(self, tmp_path):
        """
        误差在 [-20%, +15%] 之间 → recommended_tokens = estimated_tokens（不做调整）。
        """
        store = _make_store(tmp_path)
        estimated = 3000
        # actual = estimated * 1.1（10% 误差，低于 20% 阈值）
        actual = int(estimated * 1.1)
        _record_batch(
            store, "ROUTE_ADD_ENDPOINT", success=True, n=_SUGGEST_MIN_SAMPLES,
            actual_tokens=actual, estimated_tokens=estimated,
        )
        result = store.suggest("ROUTE_ADD_ENDPOINT", estimated_tokens=estimated)

        assert result["recommended_tokens"] == estimated, (
            f"正常误差下 recommended({result['recommended_tokens']}) 应等于 estimated({estimated})"
        )

    def test_recommended_tokens_always_in_bounds(self, tmp_path):
        """recommended_tokens 始终在 [_TOKEN_MIN, _TOKEN_MAX] 范围内。"""
        store = _make_store(tmp_path)

        # 极端低估（actual = 100× estimated）→ 上限 _TOKEN_MAX
        _record_batch(
            store, "SCHEMA_ADD_FIELD", success=True, n=_SUGGEST_MIN_SAMPLES,
            actual_tokens=100_000, estimated_tokens=100,
        )
        result = store.suggest("SCHEMA_ADD_FIELD", estimated_tokens=100)
        assert _TOKEN_MIN <= result["recommended_tokens"] <= _TOKEN_MAX

    def test_model_hint_follows_budget(self, tmp_path):
        """
        recommended_tokens ≤ _FAST_MODEL_MAX_TOKENS → recommended_model = 'fast'。
        recommended_tokens > _FAST_MODEL_MAX_TOKENS → recommended_model = 'capable'。
        （注意：低成功率会覆盖此逻辑，强制 capable）
        """
        store = _make_store(tmp_path)
        # 高成功率，小 budget → fast
        _record_batch(
            store, "DOC_SYNC", success=True, n=_SUGGEST_MIN_SAMPLES,
            actual_tokens=1000, estimated_tokens=1000,
        )
        result = store.suggest("DOC_SYNC", estimated_tokens=1000)
        if result["recommended_tokens"] <= _FAST_MODEL_MAX_TOKENS:
            assert result["recommended_model"] == "fast"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Confidence 随样本数增长
# ─────────────────────────────────────────────────────────────────────────────

class TestSuggestConfidence:
    def test_confidence_increases_with_more_samples(self, tmp_path):
        """样本越多，confidence 越高（线性增长，直到 1.0）。"""
        store = _make_store(tmp_path)

        # 写入 3 条（最小样本数）
        _record_batch(store, "TEST_ADD_UNIT", success=True, n=_SUGGEST_MIN_SAMPLES)
        result_low = store.suggest("TEST_ADD_UNIT", estimated_tokens=2000)

        # 再写入更多样本（总计 10 条）
        _record_batch(store, "TEST_ADD_UNIT", success=True, n=7)
        result_high = store.suggest("TEST_ADD_UNIT", estimated_tokens=2000)

        assert result_high["confidence"] >= result_low["confidence"], (
            "更多样本应产生更高的 confidence"
        )

    def test_confidence_capped_at_1(self, tmp_path):
        """confidence 最大为 1.0，不超出。"""
        store = _make_store(tmp_path)
        # 写入远超 _SUGGEST_CONFIDENCE_DENOMINATOR 的样本
        _record_batch(store, "CONFIG_MODIFY", success=True, n=100)
        result = store.suggest("CONFIG_MODIFY", estimated_tokens=2000)

        assert result["confidence"] <= 1.0

    def test_confidence_0_5_with_no_history(self, tmp_path):
        """无历史记录 → confidence = 0.5（默认值）。"""
        store = _make_store(tmp_path)
        result = store.suggest("NON_EXISTENT", estimated_tokens=2000)
        assert result["confidence"] == 0.5
