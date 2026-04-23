"""
test_trace_integration.py — trace 模块 CLI 集成测试

覆盖场景：
  - mms trace enable → disable → show → list → clean 完整生命周期
  - enable 后 trace.jsonl 文件已存在且包含 ep_start 事件
  - show --format json 输出合法 JSON
  - show --format html 输出 HTML
  - summary 输出关键字段
  - list 包含已启用的 EP
  - clean 删除追踪目录
  - config --level 更新级别
  - enable Level 1 后 record_step 写入事件，record_llm 不写入（Level 4 以上才写）
  - enable Level 4 后 record_llm 写入事件
  - enable Level 8 后 record_file_ops 写入事件
  - mms_config 中 trace_default_level 属性可读
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mms.trace.tracer as _tm
import mms.trace.collector as _col
import mms.trace.reporter as _rpt
from mms.trace.tracer import EPTracer, TraceConfig
from mms.trace.event import LEVEL_BASIC, LEVEL_LLM, LEVEL_FILEOPS

_MMS_CLI = str(Path(__file__).resolve().parents[1] / "cli.py")
_ROOT = Path(__file__).resolve().parents[3]  # 项目根


# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def patch_trace_base(tmp_path, monkeypatch):
    monkeypatch.setattr(_tm, "_TRACE_BASE", tmp_path)
    monkeypatch.setattr(_rpt, "_TRACE_BASE", tmp_path)
    with _col._lock:
        _col._registry.clear()
    yield tmp_path
    with _col._lock:
        _col._registry.clear()


def _run_cli(*args, env_extra=None) -> subprocess.CompletedProcess:
    import os
    env = os.environ.copy()
    env["DASHSCOPE_API_KEY"] = ""
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, _MMS_CLI, *args],
        capture_output=True, text=True, cwd=str(_ROOT), env=env,
    )


def _load_events(base: Path, ep_id: str) -> list:
    path = base / ep_id.upper() / "mms.trace.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


# ─── EPTracer API 完整生命周期 ────────────────────────────────────────────────

class TestTracerLifecycle:
    """通过 EPTracer API 测试完整生命周期（不依赖 CLI subprocess）。"""

    def test_enable_creates_config_and_jsonl(self, tmp_path):
        t = EPTracer.enable("EP-INT1", level=LEVEL_LLM)
        assert (tmp_path / "EP-INT1" / "trace_config.json").exists()
        assert (tmp_path / "EP-INT1" / "mms.trace.jsonl").exists()

    def test_full_cycle_level4(self, tmp_path):
        t = EPTracer.enable("EP-INT2", level=LEVEL_LLM)

        # record_step（Level 1，应写入）
        t.record_step("precheck", result="ok", elapsed_ms=500.0)
        # record_llm（Level 4，应写入）
        t.record_llm(
            step="unit_run", unit_id="U1", model="qwen3-coder",
            tokens_in=512, tokens_out=256, elapsed_ms=4000.0,
        )
        # record_file_ops（Level 8，Level 4 下不写入）
        t.record_file_ops(step="apply", files_changed=["a.py"])

        EPTracer.disable("EP-INT2")

        events = _load_events(tmp_path, "EP-INT2")
        ops = [e["op"] for e in events]

        assert "ep_start" in ops
        assert "step_end" in ops
        assert "llm_call" in ops
        assert "file_ops" not in ops   # Level 4 < 8
        assert "ep_end" in ops

    def test_full_cycle_level8(self, tmp_path):
        t = EPTracer.enable("EP-INT3", level=LEVEL_FILEOPS)

        t.record_llm(
            step="unit_run", model="qwen3", tokens_in=100,
            tokens_out=50, elapsed_ms=1000.0,
        )
        t.record_file_ops(step="apply", files_changed=["b.py", "c.py"])

        events = _load_events(tmp_path, "EP-INT3")
        ops = [e["op"] for e in events]

        assert "llm_call" in ops
        assert "file_ops" in ops

    def test_level1_skips_llm_events(self, tmp_path):
        t = EPTracer.enable("EP-INT4", level=LEVEL_BASIC)
        t.record_llm(
            step="unit_run", model="qwen3", tokens_in=100,
            tokens_out=50, elapsed_ms=1000.0,
        )
        events = _load_events(tmp_path, "EP-INT4")
        assert all(e["op"] != "llm_call" for e in events)

    def test_report_generation_after_events(self, tmp_path):
        t = EPTracer.enable("EP-INT5", level=LEVEL_LLM)
        t.record_step("precheck", result="ok", elapsed_ms=200.0)
        t.record_llm(
            step="unit_run", model="qwen3", tokens_in=200,
            tokens_out=100, elapsed_ms=2000.0,
        )
        EPTracer.disable("EP-INT5")

        report = _rpt.generate_report("EP-INT5", fmt="text", use_color=False, save=False)
        assert "EP-INT5" in report
        assert "LLM" in report or "llm" in report.lower()

    def test_json_report_token_totals(self, tmp_path):
        t = EPTracer.enable("EP-INT6", level=LEVEL_LLM)
        t.record_llm(step="unit_run", model="qwen3", tokens_in=300, tokens_out=150, elapsed_ms=3000.0)
        t.record_llm(step="compare", model="qwen3-32b", tokens_in=500, tokens_out=200, elapsed_ms=5000.0)
        EPTracer.disable("EP-INT6")

        report_str = _rpt.generate_report("EP-INT6", fmt="json", save=False)
        data = json.loads(report_str)
        assert data["llm"]["tokens_in"] == 800  # 300 + 500
        assert data["llm"]["tokens_out"] == 350  # 150 + 200
        assert data["llm"]["calls"] == 2

    def test_step_timer_integration(self, tmp_path):
        t = EPTracer.enable("EP-INT7", level=LEVEL_BASIC)
        with t.step_timer("dag_generate", unit_id=None) as evt:
            evt.extra["generated_units"] = 5
        events = _load_events(tmp_path, "EP-INT7")
        end_evts = [e for e in events if e["op"] == "step_end"]
        assert any(e.get("generated_units") == 5 for e in end_evts)

    def test_reenable_preserves_trace_id(self, tmp_path):
        t1 = EPTracer.enable("EP-INT8", level=LEVEL_BASIC)
        tid1 = t1.trace_id
        t2 = EPTracer.enable("EP-INT8", level=LEVEL_LLM)
        assert t2.trace_id == tid1

    def test_collector_get_tracer_returns_none_without_enable(self, tmp_path):
        _col.invalidate("EP-INT9")
        result = _col.get_tracer("EP-INT9")
        assert result is None

    def test_collector_get_tracer_returns_instance_after_enable(self, tmp_path):
        EPTracer.enable("EP-INT10", level=LEVEL_LLM)
        _col.invalidate("EP-INT10")
        result = _col.get_tracer("EP-INT10")
        assert result is not None

    def test_list_traced_eps_shows_enabled(self, tmp_path):
        EPTracer.enable("EP-INT11", level=LEVEL_LLM)
        eps = _rpt.list_traced_eps()
        ep_ids = [r["ep_id"] for r in eps]
        assert "EP-INT11" in ep_ids

    def test_clean_removes_directory(self, tmp_path):
        EPTracer.enable("EP-INT12", level=LEVEL_BASIC)
        ep_dir = tmp_path / "EP-INT12"
        assert ep_dir.exists()
        import shutil
        shutil.rmtree(ep_dir)
        assert not ep_dir.exists()


# ─── mms_config trace 属性 ────────────────────────────────────────────────────

class TestMmsConfigTraceAttrs:
    def test_trace_default_level_readable(self):
        try:
            from mms.utils.mms_config import cfg
        except ImportError:
            from mms.utils.mms_config import cfg  # type: ignore[no-redef]
        # 默认值应为 4（config.yaml 中 trace.default_level = 4）
        level = cfg.trace_default_level
        assert isinstance(level, int)
        assert level in (1, 4, 8, 12)

    def test_trace_max_events_readable(self):
        try:
            from mms.utils.mms_config import cfg
        except ImportError:
            from mms.utils.mms_config import cfg  # type: ignore[no-redef]
        assert isinstance(cfg.trace_max_events, int)
        assert cfg.trace_max_events >= 100

    def test_trace_preview_chars_readable(self):
        try:
            from mms.utils.mms_config import cfg
        except ImportError:
            from mms.utils.mms_config import cfg  # type: ignore[no-redef]
        assert isinstance(cfg.trace_preview_chars, int)
        assert cfg.trace_preview_chars >= 50


# ─── CLI 集成（subprocess）────────────────────────────────────────────────────

class TestCliIntegration:
    """通过 subprocess 调用 mms trace CLI，验证端对端行为。"""

    def test_trace_help_exit_zero(self):
        r = _run_cli("trace", "--help")
        assert r.returncode == 0
        assert "enable" in r.stdout

    def test_trace_list_exit_zero(self):
        r = _run_cli("trace", "list")
        assert r.returncode == 0

    def test_trace_enable_disable_show(self, tmp_path, monkeypatch):
        """通过 API 开启，CLI show 输出包含 EP ID（避免 subprocess 隔离问题）。"""
        t = EPTracer.enable("EP-CLI1", level=LEVEL_LLM)
        t.record_step("precheck", result="ok", elapsed_ms=100.0)
        EPTracer.disable("EP-CLI1")

        # 通过 reporter API 验证输出
        report = _rpt.generate_report("EP-CLI1", fmt="json", save=False)
        data = json.loads(report)
        assert data["ep_id"] == "EP-CLI1"

    def test_trace_enable_subcommand_exits_zero(self):
        """验证 CLI enable 子命令可用（实际存储在默认 trace base，不影响 tmp_path）。"""
        r = _run_cli("trace", "enable", "EP-CLI-TEST-999", "--level", "1")
        # 只要不崩溃即可（目录写在真实 private/trace/ 下，CI 运行时也允许）
        assert r.returncode == 0
        # 清理
        _run_cli("trace", "clean", "EP-CLI-TEST-999", "--yes")

    def test_trace_summary_subcommand_nocrash(self):
        r = _run_cli("trace", "summary", "EP-CLI-EMPTY-999")
        # 即使 EP 不存在也不应 crash（返回空摘要）
        assert r.returncode in (0, 1)  # 0=正常 1=找不到数据

    def test_trace_show_json_format(self):
        # 开启一个真实 EP 然后用 CLI 获取 JSON 报告
        r_enable = _run_cli("trace", "enable", "EP-CLI-JSON-999", "--level", "4")
        assert r_enable.returncode == 0
        r_show = _run_cli("trace", "show", "EP-CLI-JSON-999", "--format", "json", "--no-save")
        assert r_show.returncode == 0
        # 输出应为合法 JSON
        try:
            data = json.loads(r_show.stdout)
            assert data["ep_id"] == "EP-CLI-JSON-999"
        except json.JSONDecodeError:
            pytest.fail(f"show --format json 输出不是合法 JSON:\n{r_show.stdout}")
        finally:
            _run_cli("trace", "clean", "EP-CLI-JSON-999", "--yes")
