"""
test_trace_event.py — TraceEvent 数据结构单元测试

覆盖场景：
  - Level 字段过滤（to_dict Level 1 / 4 / 8 / 12）
  - TraceEvent.start() 工厂方法
  - finish() 计时与链式调用
  - to_jsonl() 输出为合法 JSON 单行
  - 字段默认值与可选字段
  - extra 扩展字段合并
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trace.event import (
    TraceEvent,
    LEVEL_BASIC, LEVEL_LLM, LEVEL_FILEOPS, LEVEL_FULL,
    LEVEL_NAMES,
)


# ─── Level 常量 ────────────────────────────────────────────────────────────────

class TestLevelConstants:
    def test_level_values_are_correct(self):
        assert LEVEL_BASIC == 1
        assert LEVEL_LLM == 4
        assert LEVEL_FILEOPS == 8
        assert LEVEL_FULL == 12

    def test_level_names_map(self):
        assert LEVEL_NAMES[LEVEL_BASIC] == "Basic"
        assert LEVEL_NAMES[LEVEL_LLM] == "LLM"
        assert LEVEL_NAMES[LEVEL_FILEOPS] == "FileOps"
        assert LEVEL_NAMES[LEVEL_FULL] == "Full"


# ─── TraceEvent 创建 ───────────────────────────────────────────────────────────

class TestTraceEventCreation:
    def test_start_factory_sets_required_fields(self):
        evt = TraceEvent.start("llm_call", ep_id="EP-100", trace_id="TID-001")
        assert evt.op == "llm_call"
        assert evt.ep_id == "EP-100"
        assert evt.trace_id == "TID-001"

    def test_start_sets_ts_start(self):
        evt = TraceEvent.start("step_start", ep_id="EP-100", trace_id="TID-001")
        assert evt.ts_start is not None
        assert "T" in evt.ts_start  # ISO format

    def test_start_defaults_result_to_ok(self):
        evt = TraceEvent.start("ep_start", ep_id="EP-100", trace_id="TID-001")
        assert evt.result == "ok"

    def test_start_passes_kwargs_to_fields(self):
        evt = TraceEvent.start(
            "llm_call", ep_id="EP-100", trace_id="TID-001",
            model="qwen3-32b", step="unit_run", unit_id="U1",
        )
        assert evt.model == "qwen3-32b"
        assert evt.step == "unit_run"
        assert evt.unit_id == "U1"

    def test_start_unknown_kwargs_go_to_extra(self):
        evt = TraceEvent.start(
            "llm_call", ep_id="EP-100", trace_id="TID-001",
            custom_field="hello",
        )
        assert evt.extra.get("custom_field") == "hello"

    def test_direct_construction(self):
        evt = TraceEvent(op="git_commit", ep_id="EP-200", trace_id="TID-002")
        assert evt.op == "git_commit"
        assert evt.ts_end is None
        assert evt.elapsed_ms is None


# ─── finish() 计时 ─────────────────────────────────────────────────────────────

class TestTraceEventFinish:
    def test_finish_sets_ts_end(self):
        evt = TraceEvent.start("step_end", ep_id="EP-100", trace_id="TID-001")
        evt.finish(result="ok")
        assert evt.ts_end is not None

    def test_finish_computes_elapsed_ms(self):
        evt = TraceEvent.start("llm_call", ep_id="EP-100", trace_id="TID-001")
        time.sleep(0.01)
        evt.finish()
        assert evt.elapsed_ms is not None
        assert evt.elapsed_ms >= 10  # 至少 10ms（sleep 0.01s = 10ms）

    def test_finish_sets_result(self):
        evt = TraceEvent.start("step_end", ep_id="EP-100", trace_id="TID-001")
        evt.finish(result="error", error_msg="something failed")
        assert evt.result == "error"
        assert evt.error_msg == "something failed"

    def test_finish_returns_self_for_chaining(self):
        evt = TraceEvent.start("ep_end", ep_id="EP-100", trace_id="TID-001")
        returned = evt.finish()
        assert returned is evt

    def test_finish_updates_known_kwargs(self):
        evt = TraceEvent.start("llm_call", ep_id="EP-100", trace_id="TID-001")
        evt.finish(model="gemini-2.5-pro", tokens_in=512)
        assert evt.model == "gemini-2.5-pro"
        assert evt.tokens_in == 512

    def test_finish_puts_unknown_kwargs_in_extra(self):
        evt = TraceEvent.start("llm_call", ep_id="EP-100", trace_id="TID-001")
        evt.finish(unknown_field="value")
        assert evt.extra.get("unknown_field") == "value"


# ─── to_dict() Level 过滤 ────────────────────────────────────────────────────

class TestTraceEventToDict:
    def _make_full_event(self) -> TraceEvent:
        evt = TraceEvent(
            op="llm_call",
            ep_id="EP-100",
            trace_id="TID-001",
            step="unit_run",
            unit_id="U1",
            model="qwen3-coder",
            tokens_in=512,
            tokens_out=256,
            llm_attempt=2,
            llm_max_attempts=3,
            llm_result="success",
            arch_ok=True,
            test_ok=True,
            test_summary="5 passed",
            files_changed=["foo.py"],
            files_rejected=[],
            lines_added=10,
            lines_removed=3,
            prompt_preview="You are...",
            response_preview="===BEGIN-CHANGES===",
        )
        evt.finish(result="ok", elapsed_ms=1500.0)
        return evt

    def test_level1_includes_base_fields(self):
        evt = self._make_full_event()
        d = evt.to_dict(level=LEVEL_BASIC)
        assert "op" in d
        assert "ep_id" in d
        assert "trace_id" in d
        assert "result" in d
        assert "elapsed_ms" in d

    def test_level1_excludes_llm_fields(self):
        evt = self._make_full_event()
        d = evt.to_dict(level=LEVEL_BASIC)
        assert "model" not in d
        assert "tokens_in" not in d
        assert "tokens_out" not in d

    def test_level1_excludes_file_fields(self):
        evt = self._make_full_event()
        d = evt.to_dict(level=LEVEL_BASIC)
        assert "files_changed" not in d
        assert "lines_added" not in d

    def test_level1_excludes_preview(self):
        evt = self._make_full_event()
        d = evt.to_dict(level=LEVEL_BASIC)
        assert "prompt_preview" not in d
        assert "response_preview" not in d

    def test_level4_includes_llm_fields(self):
        evt = self._make_full_event()
        d = evt.to_dict(level=LEVEL_LLM)
        assert "model" in d
        assert "tokens_in" in d
        assert "tokens_out" in d
        assert "arch_ok" in d
        assert "test_ok" in d

    def test_level4_excludes_file_fields(self):
        evt = self._make_full_event()
        d = evt.to_dict(level=LEVEL_LLM)
        assert "files_changed" not in d

    def test_level4_excludes_preview(self):
        evt = self._make_full_event()
        d = evt.to_dict(level=LEVEL_LLM)
        assert "prompt_preview" not in d

    def test_level8_includes_file_fields(self):
        evt = self._make_full_event()
        d = evt.to_dict(level=LEVEL_FILEOPS)
        assert "files_changed" in d
        assert "lines_added" in d
        assert "lines_removed" in d

    def test_level8_excludes_preview(self):
        evt = self._make_full_event()
        d = evt.to_dict(level=LEVEL_FILEOPS)
        assert "prompt_preview" not in d

    def test_level12_includes_preview(self):
        evt = self._make_full_event()
        d = evt.to_dict(level=LEVEL_FULL)
        assert "prompt_preview" in d
        assert "response_preview" in d

    def test_none_fields_are_excluded(self):
        evt = TraceEvent(op="step_end", ep_id="EP-100", trace_id="TID-001")
        d = evt.to_dict(level=LEVEL_LLM)
        # None 字段不应出现在输出中
        assert "error_msg" not in d
        assert "model" not in d

    def test_step_and_unit_id_included_when_set(self):
        evt = TraceEvent(
            op="llm_call", ep_id="EP-100", trace_id="TID-001",
            step="unit_run", unit_id="U3",
        )
        d = evt.to_dict(level=LEVEL_BASIC)
        assert d["step"] == "unit_run"
        assert d["unit_id"] == "U3"

    def test_extra_dict_merged_at_all_levels(self):
        evt = TraceEvent(
            op="custom", ep_id="EP-100", trace_id="TID-001",
            extra={"custom_key": "custom_val"},
        )
        for level in [LEVEL_BASIC, LEVEL_LLM, LEVEL_FILEOPS, LEVEL_FULL]:
            d = evt.to_dict(level=level)
            assert d.get("custom_key") == "custom_val"


# ─── to_jsonl() ────────────────────────────────────────────────────────────────

class TestTraceEventToJsonl:
    def test_to_jsonl_is_valid_json(self):
        evt = TraceEvent.start("llm_call", ep_id="EP-100", trace_id="TID-001")
        evt.finish()
        line = evt.to_jsonl()
        parsed = json.loads(line)
        assert parsed["op"] == "llm_call"

    def test_to_jsonl_is_single_line(self):
        evt = TraceEvent.start("llm_call", ep_id="EP-100", trace_id="TID-001")
        evt.finish()
        line = evt.to_jsonl()
        assert "\n" not in line

    def test_to_jsonl_handles_unicode(self):
        evt = TraceEvent(
            op="step_end", ep_id="EP-100", trace_id="TID-001",
            extra={"desc": "本体数据管道"},
        )
        line = evt.to_jsonl()
        parsed = json.loads(line)
        assert parsed["desc"] == "本体数据管道"

    def test_to_jsonl_level_filters(self):
        evt = TraceEvent(
            op="llm_call", ep_id="EP-100", trace_id="TID-001",
            model="qwen3", tokens_in=100,
        )
        line_basic = evt.to_jsonl(level=LEVEL_BASIC)
        line_llm = evt.to_jsonl(level=LEVEL_LLM)
        parsed_basic = json.loads(line_basic)
        parsed_llm = json.loads(line_llm)
        assert "model" not in parsed_basic
        assert "model" in parsed_llm
