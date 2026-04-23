#!/usr/bin/env python3
"""
trace/reporter.py — MMS 诊断报告生成器

类比 Oracle tkprof 工具，将原始 trace.jsonl 聚合为人类可读的报告。

支持三种输出格式：
  text  — 终端彩色报告（默认），含瀑布图、LLM 表格、3-Strike 统计
  json  — 结构化 JSON（供程序消费或进一步分析）
  html  — 带样式的 HTML 报告（可在浏览器查看）

主要报告区块（参考 10046 tkprof 输出结构）：
  ① EP 概览         总耗时、总 token、LLM 调用次数
  ② 步骤耗时瀑布图  类比 SQL 的 Parse/Execute/Fetch 三阶段
  ③ LLM 调用明细    模型/token/耗时/结果（Level 4+）
  ④ 3-Strike 统计   重试次数、失败原因（Level 4+）
  ⑤ Scope Guard     被拒文件列表（Level 8+）
  ⑥ 文件变更摘要    行数增减（Level 8+）
  ⑦ 验证摘要        arch_check / pytest 结果汇总
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .event import (
    LEVEL_BASIC, LEVEL_LLM, LEVEL_FILEOPS, LEVEL_FULL, LEVEL_NAMES
)
from .tracer import TraceConfig, _TRACE_BASE

# ANSI 颜色
_G = "\033[92m"
_Y = "\033[93m"
_R = "\033[91m"
_C = "\033[96m"
_B = "\033[1m"
_D = "\033[2m"
_X = "\033[0m"


def _c(text: str, color: str, use_color: bool = True) -> str:
    return f"{color}{text}{_X}" if use_color else text


# ── 原始事件读取 ──────────────────────────────────────────────────────────────

def load_events(ep_id: str) -> List[Dict[str, Any]]:
    """从 trace.jsonl 加载所有事件，返回字典列表。"""
    path = _TRACE_BASE / ep_id.upper() / "trace.jsonl"
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def load_config(ep_id: str) -> Optional[TraceConfig]:
    return TraceConfig.load(ep_id)


# ── 聚合统计 ──────────────────────────────────────────────────────────────────

class TraceSummary:
    """从事件流中提取统计信息（类比 tkprof 的聚合层）。"""

    def __init__(self, ep_id: str, events: List[Dict]) -> None:
        self.ep_id = ep_id.upper()
        self.events = events
        self._analyze()

    def _analyze(self) -> None:
        evts = self.events

        # EP 总耗时（从 ep_start 到 ep_end）
        ep_start = next((e for e in evts if e.get("op") == "ep_start"), None)
        ep_end = next((e for e in reversed(evts) if e.get("op") == "ep_end"), None)
        self.ep_start_ts = ep_start.get("ts_start") if ep_start else "—"
        self.ep_end_ts = ep_end.get("ts_start") if ep_end else "—"

        # 步骤耗时汇总
        self.step_timings: List[Tuple[str, Optional[str], float, str]] = []
        # [(step, unit_id, elapsed_ms, result)]
        for e in evts:
            if e.get("op") == "step_end" and e.get("elapsed_ms") is not None:
                self.step_timings.append((
                    e.get("step", "?"),
                    e.get("unit_id"),
                    float(e.get("elapsed_ms", 0)),
                    e.get("result", "ok"),
                ))

        # LLM 调用统计
        self.llm_calls: List[Dict] = [e for e in evts if e.get("op") == "llm_call"]
        self.total_tokens_in = sum(e.get("tokens_in") or 0 for e in self.llm_calls)
        self.total_tokens_out = sum(e.get("tokens_out") or 0 for e in self.llm_calls)
        self.total_tokens = self.total_tokens_in + self.total_tokens_out
        self.total_llm_elapsed = sum(e.get("elapsed_ms") or 0 for e in self.llm_calls)

        # 3-Strike 重试统计（按 unit_id 聚合）
        self.retries: Dict[str, List[Dict]] = defaultdict(list)
        for e in self.llm_calls:
            uid = e.get("unit_id")
            if uid and (e.get("llm_attempt") or 1) > 1:
                self.retries[uid].append(e)

        # 验证统计
        self.validations = [e for e in evts if e.get("op") == "validation"]
        self.arch_failures = [v for v in self.validations if not v.get("arch_ok", True)]
        self.test_failures = [v for v in self.validations if not v.get("test_ok", True)]

        # 文件操作统计
        self.file_ops = [e for e in evts if e.get("op") == "file_ops"]
        self.total_files_changed = sum(
            len(e.get("files_changed") or []) for e in self.file_ops
        )
        self.all_rejected = []
        for e in self.file_ops:
            self.all_rejected.extend(e.get("files_rejected") or [])
        self.total_lines_added = sum(e.get("lines_added") or 0 for e in self.file_ops)
        self.total_lines_removed = sum(e.get("lines_removed") or 0 for e in self.file_ops)

        # git 提交
        self.git_commits = [e for e in evts if e.get("op") == "git_commit"]


# ── 文本格式报告（终端） ───────────────────────────────────────────────────────

def _fmt_ms(ms: float) -> str:
    """格式化毫秒为易读字符串。"""
    if ms < 1000:
        return f"{ms:.0f}ms"
    elif ms < 60000:
        return f"{ms/1000:.1f}s"
    else:
        m = int(ms // 60000)
        s = int((ms % 60000) // 1000)
        return f"{m}m{s:02d}s"


def _bar(elapsed_ms: float, max_ms: float, width: int = 30) -> str:
    """生成瀑布图 bar。"""
    if max_ms <= 0:
        return ""
    ratio = min(elapsed_ms / max_ms, 1.0)
    filled = int(ratio * width)
    return "█" * filled + "░" * (width - filled)


def generate_text_report(
    ep_id: str,
    summary: TraceSummary,
    cfg: Optional[TraceConfig],
    use_color: bool = True,
    filter_step: Optional[str] = None,
    filter_unit: Optional[str] = None,
) -> str:
    """生成类 tkprof 的彩色文本报告。"""
    lines = []
    W = 66  # 报告宽度

    def sep(char: str = "─") -> None:
        lines.append(_c(char * W, _D, use_color))

    def hdr(title: str) -> None:
        lines.append("")
        lines.append(_c(f"──── {title} ", _C, use_color) + _c("─" * (W - len(title) - 6), _D, use_color))

    level = cfg.level if cfg else LEVEL_BASIC
    level_name = LEVEL_NAMES.get(level, "?")
    total_events = len(summary.events)

    # ① 标题与 EP 概览
    lines.append(_c("═" * W, _B, use_color))
    lines.append(_c(f"  MMS Trace Report — {ep_id}  |  Level {level} ({level_name})", _B, use_color))
    lines.append(_c("═" * W, _B, use_color))
    lines.append(f"  追踪 ID  : {cfg.trace_id if cfg else '—'}")
    lines.append(f"  开始时间 : {summary.ep_start_ts}")
    lines.append(f"  结束时间 : {summary.ep_end_ts}")
    lines.append(f"  事件总数 : {total_events}")

    # 总耗时（从步骤时间汇总）
    total_step_ms = sum(t[2] for t in summary.step_timings)
    lines.append(f"  步骤总耗时: {_fmt_ms(total_step_ms)}")
    lines.append(
        f"  LLM 调用  : {len(summary.llm_calls)} 次  "
        f"Token ≈ {summary.total_tokens:,}（in:{summary.total_tokens_in:,} / out:{summary.total_tokens_out:,}）"
    )
    lines.append(f"  文件变更  : {summary.total_files_changed} 个  "
                 f"+{summary.total_lines_added} / -{summary.total_lines_removed} 行")
    lines.append(f"  git 提交  : {len(summary.git_commits)} 次")

    if summary.all_rejected:
        lines.append(_c(f"  ⚠️  Scope Guard 拒绝: {len(summary.all_rejected)} 个文件", _Y, use_color))

    # ② 步骤耗时瀑布图
    timings = summary.step_timings
    if filter_step:
        timings = [t for t in timings if filter_step in t[0]]
    if filter_unit:
        timings = [t for t in timings if t[1] == filter_unit]

    if timings:
        hdr("步骤耗时瀑布图")
        max_ms = max(t[2] for t in timings) if timings else 1
        for step, uid, ms, result in timings:
            label = f"{step}" + (f"/{uid}" if uid else "")
            icon = _c("✅", _G, use_color) if result == "ok" else _c("❌", _R, use_color)
            bar = _bar(ms, max_ms)
            time_str = _fmt_ms(ms)
            lines.append(f"  {icon} {label:<28} {_c(bar, _C, use_color)} {time_str:>7}")

    # ③ LLM 调用明细（Level 4+）
    llm_calls = summary.llm_calls
    if filter_unit:
        llm_calls = [e for e in llm_calls if e.get("unit_id") == filter_unit]
    if filter_step:
        llm_calls = [e for e in llm_calls if filter_step in (e.get("step") or "")]

    if llm_calls and level >= LEVEL_LLM:
        hdr("LLM 调用明细")
        lines.append(f"  {'#':<3} {'操作/Unit':<22} {'模型':<22} {'in':>6} {'out':>6} {'耗时':>8} 结果")
        sep()
        for i, e in enumerate(llm_calls, 1):
            op_label = (e.get("step") or "?") + ("/" + e.get("unit_id") if e.get("unit_id") else "")
            model = (e.get("model") or "?")[:20]
            tok_in = e.get("tokens_in") or 0
            tok_out = e.get("tokens_out") or 0
            ms = _fmt_ms(float(e.get("elapsed_ms") or 0))
            res = e.get("result", "ok")
            attempt = e.get("llm_attempt") or 1
            attempt_str = f" ×{attempt}" if attempt > 1 else ""
            res_icon = (_c("✅", _G, use_color) if res == "ok"
                        else _c("⚠️ ", _Y, use_color) if res == "retry"
                        else _c("❌", _R, use_color))
            lines.append(
                f"  {i:<3} {op_label:<22} {model:<22} {tok_in:>6,} {tok_out:>6,} {ms:>8}"
                f" {res_icon}{attempt_str}"
            )

    # ④ 3-Strike 重试统计（Level 4+）
    if summary.retries and level >= LEVEL_LLM:
        hdr("3-Strike 重试统计")
        for uid, retry_evts in summary.retries.items():
            for e in retry_evts:
                attempt = e.get("llm_attempt", "?")
                llm_res = e.get("llm_result") or e.get("result") or "?"
                err = (e.get("error_msg") or "")[:60]
                lines.append(f"  {uid}  第{attempt}次重试 → {_c(llm_res, _Y, use_color)}"
                              + (f"  ({err})" if err else ""))

    # ⑤ Scope Guard 事件（Level 8+）
    if level >= LEVEL_FILEOPS:
        hdr("Scope Guard 事件")
        if summary.all_rejected:
            for f in summary.all_rejected:
                lines.append(f"  {_c('❌ 拒绝', _R, use_color)}: {f}")
        else:
            lines.append(f"  {_c('✅ 无文件被拒绝', _G, use_color)}")

    # ⑥ 文件变更摘要（Level 8+）
    if summary.file_ops and level >= LEVEL_FILEOPS:
        hdr("文件变更摘要")
        for e in summary.file_ops:
            uid = e.get("unit_id", "—")
            changed = e.get("files_changed") or []
            added = e.get("lines_added") or 0
            removed = e.get("lines_removed") or 0
            for f in changed:
                lines.append(f"  {uid}  {f}  (+{added} / -{removed})")

    # ⑦ 验证摘要
    hdr("验证摘要")
    arch_total = len(summary.validations)
    arch_ok_count = arch_total - len(summary.arch_failures)
    test_ok_count = arch_total - len(summary.test_failures)
    arch_icon = _c("✅", _G, use_color) if not summary.arch_failures else _c("❌", _R, use_color)
    test_icon = _c("✅", _G, use_color) if not summary.test_failures else _c("⚠️ ", _Y, use_color)
    lines.append(f"  {arch_icon} arch_check: {arch_ok_count}/{arch_total} 通过")
    lines.append(f"  {test_icon} pytest    : {test_ok_count}/{arch_total} 通过")
    if summary.test_failures:
        for v in summary.test_failures:
            uid = v.get("unit_id", "?")
            summary_line = v.get("test_summary", "")
            lines.append(f"    {_c(uid, _Y, use_color)}: {summary_line}")

    lines.append("")
    lines.append(_c("═" * W, _B, use_color))
    return "\n".join(lines)


# ── JSON 格式报告 ────────────────────────────────────────────────────────────

def generate_json_report(
    ep_id: str,
    summary: TraceSummary,
    cfg: Optional[TraceConfig],
) -> str:
    """生成结构化 JSON 报告（供程序消费）。"""
    data: Dict[str, Any] = {
        "ep_id": ep_id,
        "trace_id": cfg.trace_id if cfg else None,
        "level": cfg.level if cfg else LEVEL_BASIC,
        "ep_start": summary.ep_start_ts,
        "ep_end": summary.ep_end_ts,
        "total_events": len(summary.events),
        "llm": {
            "calls": len(summary.llm_calls),
            "tokens_in": summary.total_tokens_in,
            "tokens_out": summary.total_tokens_out,
            "total_tokens": summary.total_tokens,
            "elapsed_ms": summary.total_llm_elapsed,
        },
        "files": {
            "changed": summary.total_files_changed,
            "rejected": list(summary.all_rejected),
            "lines_added": summary.total_lines_added,
            "lines_removed": summary.total_lines_removed,
        },
        "validation": {
            "total": len(summary.validations),
            "arch_failures": len(summary.arch_failures),
            "test_failures": len(summary.test_failures),
        },
        "retries": {uid: len(evts) for uid, evts in summary.retries.items()},
        "git_commits": len(summary.git_commits),
        "step_timings": [
            {"step": s, "unit_id": u, "elapsed_ms": ms, "result": r}
            for s, u, ms, r in summary.step_timings
        ],
        "llm_calls": [
            {k: v for k, v in e.items() if k not in ("prompt_preview", "response_preview")}
            for e in summary.llm_calls
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


# ── HTML 格式报告 ────────────────────────────────────────────────────────────

def generate_html_report(
    ep_id: str,
    summary: TraceSummary,
    cfg: Optional[TraceConfig],
) -> str:
    """生成带样式的 HTML 报告。"""
    level = cfg.level if cfg else LEVEL_BASIC
    level_name = LEVEL_NAMES.get(level, "?")

    # 步骤瀑布图 HTML
    step_rows = ""
    max_ms = max((t[2] for t in summary.step_timings), default=1)
    for step, uid, ms, result in summary.step_timings:
        label = f"{step}" + (f"/{uid}" if uid else "")
        bar_pct = min(int(ms / max_ms * 100), 100)
        color = "#52c41a" if result == "ok" else "#ff4d4f"
        icon = "✅" if result == "ok" else "❌"
        step_rows += f"""
        <tr>
          <td>{icon} {label}</td>
          <td><div style="background:{color};width:{bar_pct}%;height:14px;border-radius:3px"></div></td>
          <td style="text-align:right">{_fmt_ms(ms)}</td>
          <td>{result}</td>
        </tr>"""

    # LLM 调用表格 HTML
    llm_rows = ""
    for i, e in enumerate(summary.llm_calls, 1):
        op_label = (e.get("step") or "?") + ("/" + e.get("unit_id") if e.get("unit_id") else "")
        res = e.get("result", "ok")
        icon = "✅" if res == "ok" else "⚠️" if res == "retry" else "❌"
        llm_rows += f"""
        <tr>
          <td>{i}</td>
          <td>{op_label}</td>
          <td>{e.get("model","?")}</td>
          <td style="text-align:right">{e.get("tokens_in") or 0:,}</td>
          <td style="text-align:right">{e.get("tokens_out") or 0:,}</td>
          <td style="text-align:right">{_fmt_ms(float(e.get("elapsed_ms") or 0))}</td>
          <td>{icon} {e.get("llm_result") or res}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>MMS Trace — {ep_id}</title>
<style>
  body {{ font-family: monospace; background: #0d1117; color: #c9d1d9; margin: 24px; }}
  h1 {{ color: #58a6ff; border-bottom: 1px solid #30363d; padding-bottom: 8px; }}
  h2 {{ color: #79c0ff; margin-top: 24px; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 8px; }}
  th {{ background: #161b22; color: #8b949e; text-align: left; padding: 6px 10px; }}
  td {{ border-top: 1px solid #21262d; padding: 5px 10px; }}
  .ok   {{ color: #3fb950; }}
  .err  {{ color: #f85149; }}
  .warn {{ color: #d29922; }}
  .meta {{ color: #8b949e; font-size: 0.9em; }}
</style>
</head>
<body>
<h1>MMS Trace Report — {ep_id}</h1>
<div class="meta">
  Level {level} ({level_name}) &nbsp;|&nbsp;
  事件总数: {len(summary.events)} &nbsp;|&nbsp;
  LLM 调用: {len(summary.llm_calls)} 次 &nbsp;|&nbsp;
  Token ≈ {summary.total_tokens:,}
</div>

<h2>① 步骤耗时瀑布图</h2>
<table>
  <tr><th>步骤</th><th style="width:300px">耗时</th><th>时间</th><th>结果</th></tr>
  {step_rows}
</table>

<h2>② LLM 调用明细</h2>
<table>
  <tr><th>#</th><th>操作/Unit</th><th>模型</th>
      <th>Tokens In</th><th>Tokens Out</th><th>耗时</th><th>结果</th></tr>
  {llm_rows}
</table>

<h2>③ 文件变更摘要</h2>
<p>变更文件: {summary.total_files_changed} 个 &nbsp;|&nbsp;
   +{summary.total_lines_added} / -{summary.total_lines_removed} 行 &nbsp;|&nbsp;
   Scope Guard 拒绝: {len(summary.all_rejected)} 个</p>

<h2>④ 验证摘要</h2>
<p>arch_check: {len(summary.validations) - len(summary.arch_failures)}/{len(summary.validations)} 通过 &nbsp;|&nbsp;
   pytest: {len(summary.validations) - len(summary.test_failures)}/{len(summary.validations)} 通过</p>
</body>
</html>"""
    return html


# ── 主入口：生成并保存报告 ────────────────────────────────────────────────────

def generate_report(
    ep_id: str,
    fmt: str = "text",
    filter_step: Optional[str] = None,
    filter_unit: Optional[str] = None,
    use_color: bool = True,
    save: bool = True,
) -> str:
    """
    生成指定 EP 的诊断报告。

    Args:
        ep_id:        EP 编号
        fmt:          输出格式（text / json / html）
        filter_step:  只显示包含此关键词的步骤
        filter_unit:  只显示此 Unit 的事件
        use_color:    是否使用 ANSI 颜色（text 格式）
        save:         是否保存报告到磁盘

    Returns:
        报告字符串
    """
    ep_id = ep_id.upper()
    events = load_events(ep_id)
    cfg = load_config(ep_id)
    summary = TraceSummary(ep_id, events)

    if fmt == "json":
        report = generate_json_report(ep_id, summary, cfg)
        suffix = "json"
    elif fmt == "html":
        report = generate_html_report(ep_id, summary, cfg)
        suffix = "html"
    else:
        report = generate_text_report(
            ep_id, summary, cfg,
            use_color=use_color,
            filter_step=filter_step,
            filter_unit=filter_unit,
        )
        suffix = "txt"

    if save:
        report_dir = _TRACE_BASE / ep_id / "report"
        report_dir.mkdir(parents=True, exist_ok=True)
        out_path = report_dir / f"report.{suffix}"
        out_path.write_text(report, encoding="utf-8")

    return report


def generate_summary_text(ep_id: str, use_color: bool = True) -> str:
    """快速生成单段摘要（用于 mms trace summary 命令）。"""
    ep_id = ep_id.upper()
    events = load_events(ep_id)
    cfg = load_config(ep_id)
    s = TraceSummary(ep_id, events)

    level = cfg.level if cfg else LEVEL_BASIC
    lines = [
        _c(f"EP {ep_id} 诊断摘要", _B, use_color),
        f"  Level      : {level} ({LEVEL_NAMES.get(level,'?')})",
        f"  步骤耗时   : {_fmt_ms(sum(t[2] for t in s.step_timings))}",
        f"  LLM 调用   : {len(s.llm_calls)} 次  ≈ {s.total_tokens:,} token",
        f"  文件变更   : {s.total_files_changed} 个  (+{s.total_lines_added}/-{s.total_lines_removed})",
        f"  Scope 拒绝 : {len(s.all_rejected)} 个",
        f"  重试次数   : {sum(len(v) for v in s.retries.values())} 次（{len(s.retries)} 个 Unit）",
        f"  arch_check : {'全部通过' if not s.arch_failures else f'{len(s.arch_failures)} 个失败'}",
        f"  pytest     : {'全部通过' if not s.test_failures else f'{len(s.test_failures)} 个失败'}",
        f"  事件总数   : {len(events)}",
    ]
    return "\n".join(lines)


def list_traced_eps() -> List[Dict[str, Any]]:
    """列出所有有诊断记录的 EP。"""
    result = []
    if not _TRACE_BASE.exists():
        return result
    for ep_dir in sorted(_TRACE_BASE.iterdir()):
        if not ep_dir.is_dir():
            continue
        cfg = TraceConfig.load(ep_dir.name)
        trace_file = ep_dir / "trace.jsonl"
        event_count = 0
        if trace_file.exists():
            event_count = sum(1 for line in trace_file.read_text(encoding="utf-8").splitlines() if line.strip())
        result.append({
            "ep_id": ep_dir.name,
            "enabled": cfg.enabled if cfg else False,
            "level": cfg.level if cfg else 0,
            "started_at": cfg.started_at if cfg else "—",
            "event_count": event_count,
        })
    return result
