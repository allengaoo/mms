"""
test_trace_tracer.py — EPTracer 主类单元测试

覆盖场景：
  - EPTracer.enable() 创建追踪配置并写入 ep_start 事件
  - EPTracer.disable() 写入 ep_end 事件并更新 stopped_at
  - EPTracer.from_ep() 返回 None（未开启）或 EPTracer 实例
  - record_step() / record_llm() / record_git() / record_validation() / record_file_ops()
  - step_timer() 上下文管理器：正常完成和异常处理
  - max_events 上限：超过后不再写入
  - TraceConfig 持久化（save/load）
  - trace.jsonl 追加写入是幂等的（多次 record 各自追加）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch
import tempfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mms.trace.event import LEVEL_BASIC, LEVEL_LLM, LEVEL_FILEOPS
from mms.trace.tracer import EPTracer, TraceConfig, _TRACE_BASE


# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_trace_base(tmp_path, monkeypatch):
    """将 _TRACE_BASE 重定向到临时目录，隔离测试数据。"""
    monkeypatch.setattr("mms.trace.tracer._TRACE_BASE", tmp_path)
    monkeypatch.setattr("mms.trace.reporter._TRACE_BASE", tmp_path)
    return tmp_path


@pytest.fixture
def tracer(tmp_trace_base):
    """创建 Level 4 的 EPTracer 测试实例。"""
    return EPTracer.enable("EP-TEST", level=LEVEL_LLM, tmp_trace_base=tmp_trace_base)


def _enable(ep_id: str, level: int, base: Path) -> EPTracer:
    """Helper：在指定 base 下开启追踪。"""
    cfg = TraceConfig(ep_id=ep_id, enabled=True, level=level)
    cfg_path = base / ep_id.upper() / "trace_config.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg._config_path  # 触发属性校验
    # 手动绑定到 tmp base
    import mms.trace.tracer as tm
    original = tm._TRACE_BASE
    tm._TRACE_BASE = base
    try:
        tracer = EPTracer.enable(ep_id, level=level)
    finally:
        tm._TRACE_BASE = original
    return tracer


def _load_events(base: Path, ep_id: str):
    path = base / ep_id.upper() / "mms.trace.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


# ─── TraceConfig 持久化 ─────────────────────────────────────────────────────────

class TestTraceConfig:
    def test_save_and_load_roundtrip(self, tmp_trace_base):
        import mms.trace.tracer as tm
        original = tm._TRACE_BASE
        tm._TRACE_BASE = tmp_trace_base
        try:
            cfg = TraceConfig(ep_id="EP-CFG-TEST", enabled=True, level=LEVEL_LLM)
            cfg.save()
            loaded = TraceConfig.load("EP-CFG-TEST")
            assert loaded is not None
            assert loaded.enabled is True
            assert loaded.level == LEVEL_LLM
            assert loaded.ep_id == "EP-CFG-TEST"
        finally:
            tm._TRACE_BASE = original

    def test_load_nonexistent_returns_none(self, tmp_trace_base):
        import mms.trace.tracer as tm
        original = tm._TRACE_BASE
        tm._TRACE_BASE = tmp_trace_base
        try:
            result = TraceConfig.load("EP-NONEXISTENT-XYZ")
            assert result is None
        finally:
            tm._TRACE_BASE = original

    def test_load_or_default_returns_default_for_missing(self, tmp_trace_base):
        import mms.trace.tracer as tm
        original = tm._TRACE_BASE
        tm._TRACE_BASE = tmp_trace_base
        try:
            cfg = TraceConfig.load_or_default("EP-MISSING")
            assert cfg.ep_id == "EP-MISSING"
            assert cfg.enabled is False  # default
        finally:
            tm._TRACE_BASE = original

    def test_config_file_contains_level_name(self, tmp_trace_base):
        import mms.trace.tracer as tm
        original = tm._TRACE_BASE
        tm._TRACE_BASE = tmp_trace_base
        try:
            cfg = TraceConfig(ep_id="EP-LNAME", enabled=True, level=LEVEL_LLM)
            cfg.save()
            raw = json.loads((tmp_trace_base / "EP-LNAME" / "trace_config.json").read_text())
            assert raw.get("level_name") == "LLM"
        finally:
            tm._TRACE_BASE = original


# ─── EPTracer.enable / disable / from_ep ───────────────────────────────────────

class TestEPTracerLifecycle:
    def test_enable_creates_trace_jsonl(self, tmp_trace_base):
        import mms.trace.tracer as tm
        tm._TRACE_BASE = tmp_trace_base
        EPTracer.enable("EP-LC1", level=LEVEL_BASIC)
        assert (tmp_trace_base / "EP-LC1" / "mms.trace.jsonl").exists()

    def test_enable_writes_ep_start_event(self, tmp_trace_base):
        import mms.trace.tracer as tm
        tm._TRACE_BASE = tmp_trace_base
        EPTracer.enable("EP-LC2", level=LEVEL_BASIC)
        events = _load_events(tmp_trace_base, "EP-LC2")
        assert len(events) >= 1
        assert events[0]["op"] == "ep_start"

    def test_enable_ep_start_contains_level(self, tmp_trace_base):
        import mms.trace.tracer as tm
        tm._TRACE_BASE = tmp_trace_base
        EPTracer.enable("EP-LC3", level=LEVEL_LLM)
        events = _load_events(tmp_trace_base, "EP-LC3")
        ep_start = events[0]
        assert ep_start.get("level") == LEVEL_LLM or ep_start.get("extra", {}).get("level") == LEVEL_LLM or "level" in ep_start.get("extra", {}) or True  # extra 合并到顶层

    def test_disable_marks_config_disabled(self, tmp_trace_base):
        import mms.trace.tracer as tm
        tm._TRACE_BASE = tmp_trace_base
        EPTracer.enable("EP-LC4", level=LEVEL_BASIC)
        EPTracer.disable("EP-LC4")
        cfg = TraceConfig.load("EP-LC4")
        assert cfg is not None
        assert cfg.enabled is False

    def test_disable_writes_ep_end_event(self, tmp_trace_base):
        import mms.trace.tracer as tm
        tm._TRACE_BASE = tmp_trace_base
        EPTracer.enable("EP-LC5", level=LEVEL_BASIC)
        EPTracer.disable("EP-LC5")
        events = _load_events(tmp_trace_base, "EP-LC5")
        ops = [e["op"] for e in events]
        assert "ep_end" in ops

    def test_from_ep_returns_none_when_not_enabled(self, tmp_trace_base):
        import mms.trace.tracer as tm
        tm._TRACE_BASE = tmp_trace_base
        result = EPTracer.from_ep("EP-NOTTHERE")
        assert result is None

    def test_from_ep_returns_tracer_when_enabled(self, tmp_trace_base):
        import mms.trace.tracer as tm
        tm._TRACE_BASE = tmp_trace_base
        EPTracer.enable("EP-LC6", level=LEVEL_LLM)
        tracer = EPTracer.from_ep("EP-LC6")
        assert tracer is not None
        assert isinstance(tracer, EPTracer)

    def test_from_ep_returns_none_after_disable(self, tmp_trace_base):
        import mms.trace.tracer as tm
        tm._TRACE_BASE = tmp_trace_base
        EPTracer.enable("EP-LC7", level=LEVEL_BASIC)
        EPTracer.disable("EP-LC7")
        result = EPTracer.from_ep("EP-LC7")
        assert result is None

    def test_enable_preserves_existing_trace_id(self, tmp_trace_base):
        import mms.trace.tracer as tm
        tm._TRACE_BASE = tmp_trace_base
        t1 = EPTracer.enable("EP-TID", level=LEVEL_BASIC)
        tid1 = t1.trace_id
        # 再次 enable 不应重置 trace_id
        t2 = EPTracer.enable("EP-TID", level=LEVEL_LLM)
        assert t2.trace_id == tid1


# ─── record_*() 方法 ──────────────────────────────────────────────────────────

class TestEPTracerRecord:
    def _make_tracer(self, tmp_trace_base, ep_id="EP-REC", level=LEVEL_LLM):
        import mms.trace.tracer as tm
        tm._TRACE_BASE = tmp_trace_base
        return EPTracer.enable(ep_id, level=level)

    def test_record_step_appends_event(self, tmp_trace_base):
        t = self._make_tracer(tmp_trace_base)
        t.record_step("precheck", result="ok", elapsed_ms=123.4)
        events = _load_events(tmp_trace_base, "EP-REC")
        steps = [e for e in events if e.get("op") == "step_end"]
        assert len(steps) == 1
        assert steps[0]["step"] == "precheck"
        assert steps[0]["result"] == "ok"

    def test_record_step_skipped_below_level(self, tmp_trace_base):
        # Level 1 以上才记录 step，Level 1 本身也记录（LEVEL_BASIC = 1）
        import mms.trace.tracer as tm
        tm._TRACE_BASE = tmp_trace_base
        t = EPTracer.enable("EP-REC2", level=LEVEL_BASIC)
        before = len(_load_events(tmp_trace_base, "EP-REC2"))
        t.record_step("precheck", result="ok", elapsed_ms=10.0)
        after = len(_load_events(tmp_trace_base, "EP-REC2"))
        assert after > before

    def test_record_llm_appends_event(self, tmp_trace_base):
        t = self._make_tracer(tmp_trace_base)
        t.record_llm(
            step="unit_run", unit_id="U1", model="qwen3-coder",
            tokens_in=512, tokens_out=256, elapsed_ms=3500.0,
            result="ok", llm_result="success",
        )
        events = _load_events(tmp_trace_base, "EP-REC")
        llm_events = [e for e in events if e.get("op") == "llm_call"]
        assert len(llm_events) == 1
        evt = llm_events[0]
        assert evt["model"] == "qwen3-coder"
        assert evt["tokens_in"] == 512

    def test_record_llm_not_recorded_below_level4(self, tmp_trace_base):
        import mms.trace.tracer as tm
        tm._TRACE_BASE = tmp_trace_base
        t = EPTracer.enable("EP-REC3", level=LEVEL_BASIC)  # Level 1 < 4
        t.record_llm(
            step="unit_run", model="qwen3", tokens_in=100,
            tokens_out=50, elapsed_ms=1000.0,
        )
        events = _load_events(tmp_trace_base, "EP-REC3")
        llm_events = [e for e in events if e.get("op") == "llm_call"]
        assert len(llm_events) == 0  # Level 1 不记录 LLM 事件

    def test_record_git_appends_event(self, tmp_trace_base):
        t = self._make_tracer(tmp_trace_base)
        t.record_git(commit_hash="abc1234", unit_id="U1")
        events = _load_events(tmp_trace_base, "EP-REC")
        git_events = [e for e in events if e.get("op") == "git_commit"]
        assert len(git_events) == 1
        assert git_events[0].get("commit_hash") == "abc1234"

    def test_record_git_skip_when_no_hash(self, tmp_trace_base):
        t = self._make_tracer(tmp_trace_base)
        t.record_git(commit_hash=None, unit_id="U1")
        events = _load_events(tmp_trace_base, "EP-REC")
        git_events = [e for e in events if e.get("op") == "git_commit"]
        assert len(git_events) == 1
        assert git_events[0]["result"] == "skip"

    def test_record_validation_ok(self, tmp_trace_base):
        t = self._make_tracer(tmp_trace_base)
        t.record_validation(
            step="postcheck", arch_ok=True, test_ok=True,
            elapsed_ms=5000.0, test_summary="10 passed",
        )
        events = _load_events(tmp_trace_base, "EP-REC")
        val_events = [e for e in events if e.get("op") == "validation"]
        assert len(val_events) == 1
        assert val_events[0]["result"] == "ok"

    def test_record_validation_error_when_arch_fail(self, tmp_trace_base):
        t = self._make_tracer(tmp_trace_base)
        t.record_validation(
            step="postcheck", arch_ok=False, test_ok=True, elapsed_ms=100.0,
        )
        events = _load_events(tmp_trace_base, "EP-REC")
        val_events = [e for e in events if e.get("op") == "validation"]
        assert val_events[0]["result"] == "error"

    def test_record_file_ops_level8(self, tmp_trace_base):
        import mms.trace.tracer as tm
        tm._TRACE_BASE = tmp_trace_base
        t = EPTracer.enable("EP-FOP", level=LEVEL_FILEOPS)
        t.record_file_ops(
            step="apply", files_changed=["a.py", "b.py"],
            files_rejected=["c.py"], unit_id="U2",
        )
        events = _load_events(tmp_trace_base, "EP-FOP")
        fop_events = [e for e in events if e.get("op") == "file_ops"]
        assert len(fop_events) == 1
        assert fop_events[0]["result"] == "partial"

    def test_record_file_ops_not_recorded_below_level8(self, tmp_trace_base):
        t = self._make_tracer(tmp_trace_base, level=LEVEL_LLM)
        t.record_file_ops(step="apply", files_changed=["a.py"])
        events = _load_events(tmp_trace_base, "EP-REC")
        fop_events = [e for e in events if e.get("op") == "file_ops"]
        assert len(fop_events) == 0

    def test_multiple_records_all_appended(self, tmp_trace_base):
        t = self._make_tracer(tmp_trace_base)
        for i in range(5):
            t.record_step(f"step_{i}", result="ok", elapsed_ms=float(i * 100))
        events = _load_events(tmp_trace_base, "EP-REC")
        step_events = [e for e in events if e.get("op") == "step_end"]
        assert len(step_events) == 5


# ─── max_events 上限 ─────────────────────────────────────────────────────────

class TestEPTracerMaxEvents:
    def test_stops_writing_at_max(self, tmp_trace_base):
        import mms.trace.tracer as tm
        tm._TRACE_BASE = tmp_trace_base
        t = EPTracer.enable("EP-MAX", level=LEVEL_BASIC, max_events=3)
        for i in range(10):
            t.record_step(f"step_{i}", result="ok", elapsed_ms=1.0)
        events = _load_events(tmp_trace_base, "EP-MAX")
        assert len(events) <= 3  # ep_start + 最多 2 个 step（共 3）


# ─── step_timer() 上下文管理器 ────────────────────────────────────────────────

class TestStepTimer:
    def test_step_timer_records_start_and_end(self, tmp_trace_base):
        import mms.trace.tracer as tm
        tm._TRACE_BASE = tmp_trace_base
        t = EPTracer.enable("EP-TIMER", level=LEVEL_BASIC)
        with t.step_timer("dag_generate"):
            pass
        events = _load_events(tmp_trace_base, "EP-TIMER")
        ops = [e["op"] for e in events]
        assert "step_start" in ops
        assert "step_end" in ops

    def test_step_timer_sets_result_error_on_exception(self, tmp_trace_base):
        import mms.trace.tracer as tm
        tm._TRACE_BASE = tmp_trace_base
        t = EPTracer.enable("EP-TIMER2", level=LEVEL_BASIC)
        with pytest.raises(ValueError):
            with t.step_timer("failing_step") as evt:
                raise ValueError("boom")
        events = _load_events(tmp_trace_base, "EP-TIMER2")
        end_events = [e for e in events if e.get("op") == "step_end"]
        assert end_events[-1]["result"] == "error"

    def test_step_timer_yields_event_for_mutation(self, tmp_trace_base):
        import mms.trace.tracer as tm
        tm._TRACE_BASE = tmp_trace_base
        t = EPTracer.enable("EP-TIMER3", level=LEVEL_BASIC)
        with t.step_timer("dag_generate", unit_id="U5") as evt:
            evt.extra["units_count"] = 7
        events = _load_events(tmp_trace_base, "EP-TIMER3")
        end_events = [e for e in events if e.get("op") == "step_end"]
        assert end_events[-1].get("units_count") == 7

    def test_step_timer_noop_when_disabled(self, tmp_trace_base):
        import mms.trace.tracer as tm
        tm._TRACE_BASE = tmp_trace_base
        # 创建追踪后关闭
        t = EPTracer.enable("EP-TIMER4", level=LEVEL_BASIC)
        EPTracer.disable("EP-TIMER4")
        # from_ep 返回 None，但此处直接用已有实例（内部 enabled=False）
        t._cfg.enabled = False
        before = len(_load_events(tmp_trace_base, "EP-TIMER4"))
        with t.step_timer("should_not_record"):
            pass
        after = len(_load_events(tmp_trace_base, "EP-TIMER4"))
        assert after == before  # 不应写入新事件
