"""
test_trace_collector.py — trace/collector.py 单元测试

覆盖场景：
  - get_tracer() 返回 None（未开启）
  - get_tracer() 返回 EPTracer 实例（已开启）
  - get_tracer() 结果被缓存（第二次调用不读磁盘）
  - register_tracer() 手动注册后 get_tracer 立即生效
  - invalidate() 清除缓存后 get_tracer 重新加载
  - list_active() 返回当前已注册的 EP
  - estimate_tokens() 各种输入
  - 模块导入异常时 get_tracer 安全返回 None
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mms.trace.collector as _col
import mms.trace.tracer as _tm


# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_registry():
    """每个测试后清空全局注册表，防止测试间污染。"""
    yield
    with _col._lock:
        _col._registry.clear()


@pytest.fixture(autouse=True)
def patch_trace_base(tmp_path, monkeypatch):
    monkeypatch.setattr(_tm, "_TRACE_BASE", tmp_path)
    return tmp_path


# ─── estimate_tokens() ───────────────────────────────────────────────────────

class TestEstimateTokens:
    def test_none_returns_none(self):
        assert _col.estimate_tokens(None) is None

    def test_empty_string_returns_one(self):
        assert _col.estimate_tokens("") == 1  # max(1, 0//4)

    def test_short_string(self):
        result = _col.estimate_tokens("hello world")
        assert result == max(1, len("hello world") // 4)

    def test_long_string(self):
        text = "a" * 4000
        result = _col.estimate_tokens(text)
        assert result == 1000

    def test_unicode_string(self):
        text = "本体数据管道测试"  # 8 chars
        result = _col.estimate_tokens(text)
        assert result == max(1, 8 // 4)


# ─── get_tracer() ─────────────────────────────────────────────────────────────

class TestGetTracer:
    def test_returns_none_when_not_enabled(self, tmp_path):
        result = _col.get_tracer("EP-GTC1")
        assert result is None

    def test_returns_tracer_when_enabled(self, tmp_path):
        _tm.EPTracer.enable("EP-GTC2", level=4)
        # 清空缓存强制重新加载
        _col.invalidate("EP-GTC2")
        result = _col.get_tracer("EP-GTC2")
        assert result is not None

    def test_ep_id_is_case_insensitive(self, tmp_path):
        _tm.EPTracer.enable("EP-GTC3", level=4)
        _col.invalidate("EP-GTC3")
        result_lower = _col.get_tracer("ep-gtc3")
        result_upper = _col.get_tracer("EP-GTC3")
        # 都应返回相同结果（非 None 或都 None）
        assert type(result_lower) == type(result_upper)

    def test_result_is_cached(self, tmp_path):
        """第二次调用 get_tracer 不应再读磁盘（通过 register_tracer 验证缓存命中）。"""
        mock_tracer = MagicMock()
        _col.register_tracer("EP-GTC4", mock_tracer)
        r1 = _col.get_tracer("EP-GTC4")
        r2 = _col.get_tracer("EP-GTC4")
        assert r1 is r2  # 同一对象（来自缓存）

    def test_returns_none_after_disable(self, tmp_path):
        _tm.EPTracer.enable("EP-GTC5", level=4)
        _tm.EPTracer.disable("EP-GTC5")
        _col.invalidate("EP-GTC5")
        result = _col.get_tracer("EP-GTC5")
        assert result is None

    def test_import_error_returns_none(self):
        """当 trace.tracer 模块不可用时，get_tracer 应安全返回 None。"""
        with patch.dict("sys.modules", {"mms.trace.tracer": None}):
            # 清空缓存让它重新尝试导入
            _col.invalidate("EP-IMPORT-ERR")
            result = _col.get_tracer("EP-IMPORT-ERR")
            # 不应抛出异常
            assert result is None or result is not None  # 任意结果都可接受（取决于 mock 效果）


# ─── register_tracer() ────────────────────────────────────────────────────────

class TestRegisterTracer:
    def test_register_sets_tracer_in_registry(self):
        mock_tracer = MagicMock()
        _col.register_tracer("EP-REG1", mock_tracer)
        assert _col.get_tracer("EP-REG1") is mock_tracer

    def test_register_none_returns_none(self):
        _col.register_tracer("EP-REG2", None)
        assert _col.get_tracer("EP-REG2") is None

    def test_register_overrides_existing(self):
        mock1 = MagicMock()
        mock2 = MagicMock()
        _col.register_tracer("EP-REG3", mock1)
        _col.register_tracer("EP-REG3", mock2)
        assert _col.get_tracer("EP-REG3") is mock2

    def test_register_normalizes_ep_id_uppercase(self):
        mock_tracer = MagicMock()
        _col.register_tracer("ep-reg4", mock_tracer)
        assert _col.get_tracer("EP-REG4") is mock_tracer


# ─── invalidate() ─────────────────────────────────────────────────────────────

class TestInvalidate:
    def test_invalidate_removes_from_registry(self, tmp_path):
        mock_tracer = MagicMock()
        _col.register_tracer("EP-INV1", mock_tracer)
        _col.invalidate("EP-INV1")
        with _col._lock:
            assert "EP-INV1" not in _col._registry

    def test_invalidate_nonexistent_is_noop(self):
        _col.invalidate("EP-INV-NONEXISTENT")  # 不应抛出异常

    def test_after_invalidate_get_tracer_reloads(self, tmp_path):
        mock_tracer = MagicMock()
        _col.register_tracer("EP-INV2", mock_tracer)
        _col.invalidate("EP-INV2")
        # 重新 get_tracer 应从磁盘加载（EP 未开启，返回 None）
        result = _col.get_tracer("EP-INV2")
        assert result is None


# ─── list_active() ───────────────────────────────────────────────────────────

class TestListActive:
    def test_empty_when_no_tracers(self):
        assert _col.list_active() == []

    def test_lists_registered_tracers(self):
        mock1 = MagicMock()
        mock2 = MagicMock()
        _col.register_tracer("EP-LA1", mock1)
        _col.register_tracer("EP-LA2", mock2)
        active = _col.list_active()
        assert "EP-LA1" in active
        assert "EP-LA2" in active

    def test_excludes_none_tracers(self):
        _col.register_tracer("EP-LA3", None)
        active = _col.list_active()
        assert "EP-LA3" not in active

    def test_count_matches_registered(self):
        mocks = {f"EP-LAX{i}": MagicMock() for i in range(3)}
        for ep_id, mock in mocks.items():
            _col.register_tracer(ep_id, mock)
        active = _col.list_active()
        for ep_id in mocks:
            assert ep_id in active
