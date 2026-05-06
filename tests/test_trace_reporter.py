"""
test_trace_reporter.py — trace/reporter.py 单元测试

覆盖场景：
  - load_events() 正常读取 / 空文件 / 目录不存在
  - TraceSummary 聚合：LLM 调用数/token/重试/验证/文件操作
  - generate_text_report() 包含预期区块（瀑布图 / LLM 明细 / 验证摘要）
  - generate_json_report() 输出合法 JSON 且字段完整
  - generate_html_report() 包含 HTML 标签
  - generate_summary_text() 单段摘要包含关键数字
  - generate_report() 保存到磁盘
  - list_traced_eps() 列出目录
  - 过滤参数（filter_step / filter_unit）仅影响显示，不影响数据
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mms.trace.event import LEVEL_LLM, LEVEL_FILEOPS, LEVEL_FULL
from mms.trace.tracer import EPTracer, TraceConfig
import mms.trace.tracer as _tm
import mms.trace.reporter as _rpt


# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def patch_trace_base(tmp_path, monkeypatch):
    """将 _TRACE_BASE 重定向到临时目录。"""
    monkeypatch.setattr(_tm, "_TRACE_BASE", tmp_path)
    monkeypatch.setattr(_rpt, "_TRACE_BASE", tmp_path)
    return tmp_path


def _write_events(base: Path, ep_id: str, events: list) -> None:
    ep_dir = base / ep_id.upper()
    ep_dir.mkdir(parents=True, exist_ok=True)
    path = ep_dir / "mms.trace.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for evt in events:
            f.write(json.dumps(evt, ensure_ascii=False) + "\n")


def _make_cfg(base: Path, ep_id: str, level: int = LEVEL_LLM) -> TraceConfig:
    cfg = TraceConfig(ep_id=ep_id, enabled=True, level=level)
    cfg_path = base / ep_id.upper() / "trace_config.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        json.dumps({
            "ep_id": ep_id, "enabled": True, "level": level,
            "level_name": "LLM", "trace_id": "MMS-TRACE-TEST",
            "started_at": "2026-04-18T00:00:00Z", "stopped_at": None,
            "event_count": 0, "max_events": 5000, "preview_chars": 200,
        }),
        encoding="utf-8",
    )
    return cfg


def _sample_events() -> list:
    """生成一批典型追踪事件（覆盖各 op 类型）。"""
    return [
        {"op": "ep_start",  "ep_id": "EP-RPT", "trace_id": "TID", "result": "ok", "ts_start": "2026-04-18T01:00:00Z"},
        {"op": "step_end",  "ep_id": "EP-RPT", "trace_id": "TID", "result": "ok", "step": "precheck",  "elapsed_ms": 1200.0},
        {"op": "step_end",  "ep_id": "EP-RPT", "trace_id": "TID", "result": "ok", "step": "unit_run",  "unit_id": "U1", "elapsed_ms": 8500.0},
        {"op": "step_end",  "ep_id": "EP-RPT", "trace_id": "TID", "result": "error", "step": "apply", "unit_id": "U2", "elapsed_ms": 300.0},
        {"op": "llm_call",  "ep_id": "EP-RPT", "trace_id": "TID", "result": "ok",
         "step": "unit_run", "unit_id": "U1", "model": "qwen3-coder",
         "tokens_in": 512, "tokens_out": 256, "elapsed_ms": 6000.0, "llm_attempt": 1, "llm_result": "success"},
        {"op": "llm_call",  "ep_id": "EP-RPT", "trace_id": "TID", "result": "retry",
         "step": "unit_run", "unit_id": "U2", "model": "qwen3-coder",
         "tokens_in": 400, "tokens_out": 100, "elapsed_ms": 4000.0, "llm_attempt": 2, "llm_result": "parse_fail"},
        {"op": "llm_call",  "ep_id": "EP-RPT", "trace_id": "TID", "result": "ok",
         "step": "compare", "unit_id": "U1", "model": "gemini-2.5-pro",
         "tokens_in": 800, "tokens_out": 320, "elapsed_ms": 9000.0, "llm_attempt": 1, "llm_result": "success"},
        {"op": "validation","ep_id": "EP-RPT", "trace_id": "TID", "result": "ok",
         "step": "postcheck", "arch_ok": True, "test_ok": True, "elapsed_ms": 5000.0,
         "test_summary": "12 passed"},
        {"op": "file_ops",  "ep_id": "EP-RPT", "trace_id": "TID", "result": "ok",
         "step": "apply", "unit_id": "U1",
         "files_changed": ["a.py", "b.py"], "files_rejected": [], "lines_added": 50, "lines_removed": 10},
        {"op": "git_commit","ep_id": "EP-RPT", "trace_id": "TID", "result": "ok",
         "step": "unit_run", "unit_id": "U1", "commit_hash": "abc123"},
        {"op": "ep_end",    "ep_id": "EP-RPT", "trace_id": "TID", "result": "ok", "ts_start": "2026-04-18T02:00:00Z"},
    ]


# ─── load_events() ───────────────────────────────────────────────────────────

class TestLoadEvents:
    def test_loads_valid_jsonl(self, tmp_path):
        _write_events(tmp_path, "EP-LE1", _sample_events())
        events = _rpt.load_events("EP-LE1")
        assert len(events) == len(_sample_events())

    def test_returns_empty_for_missing_ep(self, tmp_path):
        events = _rpt.load_events("EP-NOTHERE")
        assert events == []

    def test_skips_invalid_json_lines(self, tmp_path):
        ep_dir = tmp_path / "EP-BAD"
        ep_dir.mkdir()
        (ep_dir / "mms.trace.jsonl").write_text(
            '{"op":"ok"}\nNOT_JSON\n{"op":"ok2"}\n', encoding="utf-8"
        )
        events = _rpt.load_events("EP-BAD")
        assert len(events) == 2

    def test_skips_empty_lines(self, tmp_path):
        ep_dir = tmp_path / "EP-EMPTY"
        ep_dir.mkdir()
        (ep_dir / "mms.trace.jsonl").write_text(
            '\n\n{"op":"ep_start","ep_id":"EP-EMPTY","trace_id":"T"}\n\n',
            encoding="utf-8"
        )
        events = _rpt.load_events("EP-EMPTY")
        assert len(events) == 1


# ─── TraceSummary 聚合 ────────────────────────────────────────────────────────

class TestTraceSummary:
    def setup_method(self):
        pass

    def _make_summary(self, tmp_path):
        _write_events(tmp_path, "EP-RPT", _sample_events())
        return _rpt.TraceSummary("EP-RPT", _sample_events())

    def test_llm_calls_count(self, tmp_path):
        s = self._make_summary(tmp_path)
        assert len(s.llm_calls) == 3

    def test_total_tokens_in(self, tmp_path):
        s = self._make_summary(tmp_path)
        assert s.total_tokens_in == 512 + 400 + 800  # 1712

    def test_total_tokens_out(self, tmp_path):
        s = self._make_summary(tmp_path)
        assert s.total_tokens_out == 256 + 100 + 320

    def test_retries_detected(self, tmp_path):
        s = self._make_summary(tmp_path)
        # U2 第 2 次尝试属于重试
        assert "U2" in s.retries

    def test_step_timings_count(self, tmp_path):
        s = self._make_summary(tmp_path)
        assert len(s.step_timings) == 3  # precheck / unit_run / apply

    def test_validations_count(self, tmp_path):
        s = self._make_summary(tmp_path)
        assert len(s.validations) == 1

    def test_arch_failures_empty(self, tmp_path):
        s = self._make_summary(tmp_path)
        assert s.arch_failures == []

    def test_file_ops_count(self, tmp_path):
        s = self._make_summary(tmp_path)
        assert s.total_files_changed == 2
        assert s.total_lines_added == 50

    def test_git_commits_count(self, tmp_path):
        s = self._make_summary(tmp_path)
        assert len(s.git_commits) == 1

    def test_empty_events(self, tmp_path):
        s = _rpt.TraceSummary("EP-EMPTY", [])
        assert s.llm_calls == []
        assert s.total_tokens == 0


# ─── generate_text_report() ──────────────────────────────────────────────────

class TestTextReport:
    def _make(self, tmp_path) -> str:
        _write_events(tmp_path, "EP-RPT", _sample_events())
        _make_cfg(tmp_path, "EP-RPT")
        s = _rpt.TraceSummary("EP-RPT", _sample_events())
        cfg = _rpt.load_config("EP-RPT")
        return _rpt.generate_text_report("EP-RPT", s, cfg, use_color=False)

    def test_contains_ep_id(self, tmp_path):
        report = self._make(tmp_path)
        assert "EP-RPT" in report

    def test_contains_waterfall_section(self, tmp_path):
        report = self._make(tmp_path)
        assert "步骤耗时" in report

    def test_contains_llm_section(self, tmp_path):
        report = self._make(tmp_path)
        assert "LLM 调用" in report

    def test_contains_validation_section(self, tmp_path):
        report = self._make(tmp_path)
        assert "验证摘要" in report

    def test_contains_level_name(self, tmp_path):
        report = self._make(tmp_path)
        assert "LLM" in report

    def test_filter_step_shows_only_matching(self, tmp_path):
        _write_events(tmp_path, "EP-RPT", _sample_events())
        _make_cfg(tmp_path, "EP-RPT")
        s = _rpt.TraceSummary("EP-RPT", _sample_events())
        cfg = _rpt.load_config("EP-RPT")
        report = _rpt.generate_text_report("EP-RPT", s, cfg, use_color=False, filter_step="precheck")
        assert "precheck" in report

    def test_no_color_mode_no_ansi_codes(self, tmp_path):
        report = self._make(tmp_path)
        assert "\033[" not in report


# ─── generate_json_report() ──────────────────────────────────────────────────

class TestJsonReport:
    def _make(self, tmp_path) -> dict:
        _write_events(tmp_path, "EP-RPT", _sample_events())
        _make_cfg(tmp_path, "EP-RPT")
        s = _rpt.TraceSummary("EP-RPT", _sample_events())
        cfg = _rpt.load_config("EP-RPT")
        raw = _rpt.generate_json_report("EP-RPT", s, cfg)
        return json.loads(raw)

    def test_valid_json(self, tmp_path):
        d = self._make(tmp_path)
        assert isinstance(d, dict)

    def test_has_ep_id(self, tmp_path):
        d = self._make(tmp_path)
        assert d["ep_id"] == "EP-RPT"

    def test_has_llm_section(self, tmp_path):
        d = self._make(tmp_path)
        assert "llm" in d
        assert d["llm"]["calls"] == 3

    def test_has_files_section(self, tmp_path):
        d = self._make(tmp_path)
        assert "files" in d
        assert d["files"]["changed"] == 2

    def test_has_validation_section(self, tmp_path):
        d = self._make(tmp_path)
        assert "validation" in d

    def test_has_step_timings(self, tmp_path):
        d = self._make(tmp_path)
        assert "step_timings" in d
        assert len(d["step_timings"]) == 3

    def test_has_llm_calls_list(self, tmp_path):
        d = self._make(tmp_path)
        assert isinstance(d["llm_calls"], list)
        assert len(d["llm_calls"]) == 3

    def test_no_preview_in_json_report(self, tmp_path):
        """prompt_preview / response_preview 不应出现在 JSON 报告 llm_calls 列表中。"""
        d = self._make(tmp_path)
        for call in d["llm_calls"]:
            assert "prompt_preview" not in call
            assert "response_preview" not in call


# ─── generate_html_report() ──────────────────────────────────────────────────

class TestHtmlReport:
    def _make(self, tmp_path) -> str:
        _write_events(tmp_path, "EP-RPT", _sample_events())
        _make_cfg(tmp_path, "EP-RPT")
        s = _rpt.TraceSummary("EP-RPT", _sample_events())
        cfg = _rpt.load_config("EP-RPT")
        return _rpt.generate_html_report("EP-RPT", s, cfg)

    def test_is_html(self, tmp_path):
        html = self._make(tmp_path)
        assert "<!DOCTYPE html>" in html
        assert "<html" in html

    def test_contains_ep_id(self, tmp_path):
        html = self._make(tmp_path)
        assert "EP-RPT" in html

    def test_contains_table(self, tmp_path):
        html = self._make(tmp_path)
        assert "<table>" in html or "<table" in html


# ─── generate_summary_text() ─────────────────────────────────────────────────

class TestSummaryText:
    def test_contains_ep_id(self, tmp_path):
        _write_events(tmp_path, "EP-SUM", _sample_events()[:3])
        _make_cfg(tmp_path, "EP-SUM")
        summary = _rpt.generate_summary_text("EP-SUM", use_color=False)
        assert "EP-SUM" in summary

    def test_contains_level_name(self, tmp_path):
        _write_events(tmp_path, "EP-SUM2", _sample_events()[:3])
        _make_cfg(tmp_path, "EP-SUM2", level=LEVEL_LLM)
        summary = _rpt.generate_summary_text("EP-SUM2", use_color=False)
        assert "LLM" in summary

    def test_contains_token_count(self, tmp_path):
        _write_events(tmp_path, "EP-SUM3", _sample_events())
        _make_cfg(tmp_path, "EP-SUM3")
        summary = _rpt.generate_summary_text("EP-SUM3", use_color=False)
        # 应包含 token 统计（数字）
        assert "token" in summary.lower() or "Token" in summary


# ─── generate_report() 保存到磁盘 ────────────────────────────────────────────

class TestGenerateReportSave:
    def test_text_report_saved_to_disk(self, tmp_path):
        _write_events(tmp_path, "EP-SAVE", _sample_events())
        _make_cfg(tmp_path, "EP-SAVE")
        _rpt.generate_report("EP-SAVE", fmt="text", use_color=False, save=True)
        report_path = tmp_path / "EP-SAVE" / "report" / "report.txt"
        assert report_path.exists()

    def test_json_report_saved_to_disk(self, tmp_path):
        _write_events(tmp_path, "EP-SAVEJ", _sample_events())
        _make_cfg(tmp_path, "EP-SAVEJ")
        _rpt.generate_report("EP-SAVEJ", fmt="json", save=True)
        report_path = tmp_path / "EP-SAVEJ" / "report" / "report.json"
        assert report_path.exists()
        data = json.loads(report_path.read_text())
        assert data["ep_id"] == "EP-SAVEJ"

    def test_html_report_saved_to_disk(self, tmp_path):
        _write_events(tmp_path, "EP-SAVEH", _sample_events())
        _make_cfg(tmp_path, "EP-SAVEH")
        _rpt.generate_report("EP-SAVEH", fmt="html", save=True)
        report_path = tmp_path / "EP-SAVEH" / "report" / "report.html"
        assert report_path.exists()

    def test_no_save_flag_skips_disk(self, tmp_path):
        _write_events(tmp_path, "EP-NOSAVE", _sample_events())
        _make_cfg(tmp_path, "EP-NOSAVE")
        _rpt.generate_report("EP-NOSAVE", fmt="text", save=False)
        report_path = tmp_path / "EP-NOSAVE" / "report" / "report.txt"
        assert not report_path.exists()


# ─── list_traced_eps() ────────────────────────────────────────────────────────

class TestListTracedEps:
    def test_lists_multiple_eps(self, tmp_path):
        for ep in ["EP-A01", "EP-A02", "EP-A03"]:
            _write_events(tmp_path, ep, [{"op": "ep_start", "ep_id": ep, "trace_id": "T"}])
            _make_cfg(tmp_path, ep)
        result = _rpt.list_traced_eps()
        ep_ids = [r["ep_id"] for r in result]
        assert "EP-A01" in ep_ids
        assert "EP-A02" in ep_ids
        assert "EP-A03" in ep_ids

    def test_returns_empty_for_no_data(self, tmp_path):
        result = _rpt.list_traced_eps()
        assert result == []

    def test_event_count_correct(self, tmp_path):
        _write_events(tmp_path, "EP-CNT", _sample_events())
        _make_cfg(tmp_path, "EP-CNT")
        result = _rpt.list_traced_eps()
        cnt_entry = next(r for r in result if r["ep_id"] == "EP-CNT")
        assert cnt_entry["event_count"] == len(_sample_events())
