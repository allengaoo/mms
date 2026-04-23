"""
MMS 模型使用统计追踪器（Model Usage Tracker）

每次 LLM 调用完成后，自动写入一条 JSONL 记录到
  docs/memory/_system/model_usage.jsonl

记录字段：
  ts          — ISO-8601 时间戳（UTC）
  model       — 模型名称，如 qwen-plus, qwen-coder-plus
  provider    — 适配器类型，如 bailian, ollama, claude
  task_type   — 使用场景，如 mms_inject, mms_distill, fix_gen（自动检测）
  prompt_tok  — 输入 token 数（None = 不支持）
  output_tok  — 输出 token 数（None = 不支持）
  latency_ms  — 调用耗时（毫秒）
  success     — 是否成功
  error       — 失败时的错误摘要（≤200字）

设计原则：
  - 非阻塞：写入失败时只打印 warning，不影响主流程
  - 线程安全：使用文件追加模式（append），依赖 OS 原子性
  - 零侵入：通过装饰器模式接入，不修改业务逻辑
  - 自动调用方检测：通过调用栈识别 task_type
"""

from __future__ import annotations

import inspect
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# 存储路径（相对于项目根）
_HERE = Path(__file__).resolve().parent
_SYSTEM_DIR = _HERE.parent.parent / "docs" / "memory" / "_system"
_USAGE_FILE = _SYSTEM_DIR / "model_usage.jsonl"

# 调用栈 → task_type 映射（优先级从高到低）
_CALLER_MAP = {
    "memory_distill": "mms_distill",
    "distill":        "mms_distill",
    "injector":       "mms_inject",
    "inject":         "mms_inject",
    "fix_gen":        "fix_gen",
    "arch_check":     "arch_check",
    "verify":         "mms_verify",
    "entropy_scan":   "entropy_scan",
    "doc_drift":      "doc_drift",
    "codemap":        "mms_codemap",
    "funcmap":        "mms_funcmap",
    "cmd_status":     "mms_status",
}


def _detect_task_type() -> str:
    """
    通过调用栈自动检测 task_type。
    向上遍历 frame，取第一个匹配 _CALLER_MAP 的帧文件名。
    """
    try:
        frame = inspect.currentframe()
        depth = 0
        while frame is not None and depth < 20:
            filename = Path(frame.f_code.co_filename).stem  # 不带扩展名
            func_name = frame.f_code.co_name
            # 先匹配文件名
            for key, task in _CALLER_MAP.items():
                if key in filename:
                    return task
            # 再匹配函数名
            for key, task in _CALLER_MAP.items():
                if key in func_name:
                    return task
            frame = frame.f_back
            depth += 1
    except Exception:
        pass
    return "unknown"


def record(
    model: str,
    provider: str,
    prompt_tok: Optional[int],
    output_tok: Optional[int],
    latency_ms: float,
    success: bool = True,
    error: Optional[str] = None,
    task_type: Optional[str] = None,
) -> None:
    """
    写入一条模型调用记录。

    Args:
        model:       模型名称（如 qwen-plus）
        provider:    适配器（bailian / ollama / claude）
        prompt_tok:  输入 token（无法统计时传 None）
        output_tok:  输出 token（无法统计时传 None）
        latency_ms:  调用耗时毫秒
        success:     是否成功完成
        error:       失败摘要（success=False 时）
        task_type:   使用场景（None 表示自动检测）
    """
    try:
        _SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts":         datetime.now(timezone.utc).isoformat(),
            "model":      model,
            "provider":   provider,
            "task_type":  task_type or _detect_task_type(),
            "prompt_tok": prompt_tok,
            "output_tok": output_tok,
            "latency_ms": round(latency_ms, 1),
            "success":    success,
            "error":      error[:200] if error else None,
        }
        with open(_USAGE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        # 非阻塞：写入失败只 warn，不中断主流程
        print(f"  [model_tracker] ⚠️  统计写入失败（不影响功能）: {e}")


def load_records(since_days: Optional[int] = None) -> list:
    """
    读取所有使用记录，可按天数过滤。

    Args:
        since_days: 仅返回最近 N 天的记录，None 表示全部

    Returns:
        list of dicts，按时间升序
    """
    if not _USAGE_FILE.exists():
        return []

    records = []
    cutoff_ts = None
    if since_days is not None and since_days > 0:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        cutoff_ts = cutoff.isoformat()
    # since_days=0 → 全部历史，不设置 cutoff

    for line in _USAGE_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            if cutoff_ts and r.get("ts", "") < cutoff_ts:
                continue
            records.append(r)
        except json.JSONDecodeError:
            continue

    return records


def compute_stats(records: list) -> dict:
    """
    聚合统计：按模型、按场景分组。

    Returns:
        {
          "total_calls":    int,
          "total_prompt":   int,    # None 的计为 0
          "total_output":   int,
          "by_model":       {model: {"calls", "prompt_tok", "output_tok", "avg_latency_ms", "errors"}},
          "by_task":        {task_type: {"calls", "prompt_tok", "output_tok"}},
          "recent":         [last 10 records],
        }
    """
    by_model: dict = {}
    by_task:  dict = {}
    total_prompt = 0
    total_output = 0

    for r in records:
        model     = r.get("model", "unknown")
        task      = r.get("task_type", "unknown")
        p_tok     = r.get("prompt_tok") or 0
        o_tok     = r.get("output_tok") or 0
        latency   = r.get("latency_ms", 0)
        success   = r.get("success", True)

        total_prompt += p_tok
        total_output += o_tok

        # by_model
        if model not in by_model:
            by_model[model] = {
                "calls": 0, "prompt_tok": 0, "output_tok": 0,
                "latency_sum": 0.0, "errors": 0,
                "provider": r.get("provider", ""),
            }
        bm = by_model[model]
        bm["calls"]       += 1
        bm["prompt_tok"]  += p_tok
        bm["output_tok"]  += o_tok
        bm["latency_sum"] += latency
        if not success:
            bm["errors"] += 1

        # by_task
        if task not in by_task:
            by_task[task] = {"calls": 0, "prompt_tok": 0, "output_tok": 0}
        bt = by_task[task]
        bt["calls"]      += 1
        bt["prompt_tok"] += p_tok
        bt["output_tok"] += o_tok

    # 计算平均延迟
    for bm in by_model.values():
        calls = bm["calls"]
        bm["avg_latency_ms"] = round(bm["latency_sum"] / calls, 1) if calls else 0
        del bm["latency_sum"]

    return {
        "total_calls":  len(records),
        "total_prompt": total_prompt,
        "total_output": total_output,
        "by_model":     by_model,
        "by_task":      by_task,
        "recent":       records[-10:] if records else [],
    }


def print_report(
    since_days: Optional[int] = 7,
    filter_model: Optional[str] = None,
    fmt: str = "table",
) -> None:
    """
    打印模型使用统计报告（彩色终端输出）。

    Args:
        since_days:   统计时间窗口（天），None = 全部历史
        filter_model: 仅展示该模型的记录，None = 全部
        fmt:          "table"（彩色表格）| "json"（raw JSON）
    """
    records = load_records(since_days)

    if filter_model:
        records = [r for r in records if r.get("model") == filter_model]

    if fmt == "json":
        stats = compute_stats(records)
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return

    # ── 彩色表格输出 ──────────────────────────────────────────────────────────
    _G  = "\033[32m"
    _Y  = "\033[33m"
    _C  = "\033[36m"
    _DIM= "\033[2m"
    _B  = "\033[1m"
    _R  = "\033[0m"

    def sep(char="─", width=68):
        print(f"  {char * width}")

    # 时间范围标题
    if since_days:
        window = f"最近 {since_days} 天"
    else:
        window = "全部历史"

    if filter_model:
        window += f"（筛选模型：{filter_model}）"

    print(f"\n{_B}{'='*70}{_R}")
    print(f"  {_B}MMS 模型使用统计{_R}  ·  {_DIM}{window}{_R}"
          + (f"  · 共 {len(records)} 条记录" if records else ""))
    print(f"{_B}{'='*70}{_R}")

    if not records:
        print(f"\n  {_DIM}暂无记录。当 mms inject / mms distill / fix_gen 调用模型后，"
              f"记录将自动写入。{_R}\n")
        return

    stats = compute_stats(records)

    # ── 总览 ─────────────────────────────────────────────────────────────────
    print(f"\n{_C}【总览】{_R}")
    print(f"  总调用次数：  {_B}{stats['total_calls']}{_R} 次")
    ptok = stats['total_prompt']
    otok = stats['total_output']
    total_tok = ptok + otok
    print(f"  总 Token 消耗：{_B}{total_tok:,}{_R}"
          f"  {_DIM}( ↑ 输入 {ptok:,}  ↓ 输出 {otok:,} ){_R}")
    last_ts = records[-1]["ts"][:19].replace("T", " ") if records else "-"
    print(f"  最后调用：    {_DIM}{last_ts} UTC{_R}")

    # ── 按模型分布 ────────────────────────────────────────────────────────────
    print(f"\n{_C}【按模型分布】{_R}")
    sep()
    hdr = f"  {'模型':<26} {'调用':>6}  {'输入 tok':>10}  {'输出 tok':>9}  {'均延迟':>8}  {'错误':>4}"
    print(hdr)
    sep()
    for model, bm in sorted(stats["by_model"].items(),
                             key=lambda x: -x[1]["calls"]):
        provider = bm["provider"]
        tag = f"{_DIM}(降级){_R}" if provider == "ollama" else ""
        lat_s = f"{bm['avg_latency_ms']/1000:.1f}s"
        err_col = f"{_Y}{bm['errors']}{_R}" if bm["errors"] else f"{_DIM}0{_R}"
        print(
            f"  {_G}{model:<26}{_R}"
            f" {bm['calls']:>6}"
            f"  {bm['prompt_tok']:>10,}"
            f"  {bm['output_tok']:>9,}"
            f"  {lat_s:>8}"
            f"  {err_col:>4}  {tag}"
        )
    sep()

    # ── 按使用场景 ────────────────────────────────────────────────────────────
    print(f"\n{_C}【按使用场景（task_type）】{_R}")
    sep("─", 52)
    print(f"  {'场景':<28} {'调用':>6}  {'Token 合计':>12}")
    sep("─", 52)
    for task, bt in sorted(stats["by_task"].items(),
                            key=lambda x: -x[1]["calls"]):
        total = bt["prompt_tok"] + bt["output_tok"]
        print(
            f"  {_C}{task:<28}{_R}"
            f" {bt['calls']:>6}"
            f"  {total:>12,}"
        )
    sep("─", 52)

    # ── 最近 N 条调用 ─────────────────────────────────────────────────────────
    recent = stats["recent"]
    n = min(5, len(recent))
    print(f"\n{_C}【最近 {n} 次调用】{_R}")
    sep()
    print(f"  {'时间(UTC)':<19} {'模型':<22} {'场景':<18} {'输入/输出':>14}  {'延迟':>7}  {'状态'}")
    sep()
    for r in reversed(recent[-n:]):
        ts    = r["ts"][:19].replace("T", " ")
        model = r.get("model", "?")[:21]
        task  = r.get("task_type", "?")[:17]
        p_tok = r.get("prompt_tok") or 0
        o_tok = r.get("output_tok") or 0
        tok_s = f"{p_tok}/{o_tok}"
        lat   = f"{r.get('latency_ms', 0)/1000:.1f}s"
        ok    = f"{_G}✓{_R}" if r.get("success", True) else f"{_Y}✗{_R}"
        print(f"  {_DIM}{ts}{_R}  {_G}{model:<22}{_R}  {_C}{task:<18}{_R}"
              f"  {tok_s:>14}  {lat:>7}  {ok}")
    sep()
    print()
