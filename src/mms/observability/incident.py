#!/usr/bin/env python3
"""
observability/incident.py — Mulan 崩溃现场保全（黑匣子）

设计参考 Oracle ADR 的 Incident Dump 机制：
当木兰因大模型幻觉、非预期 JSON 断裂或底层异常崩溃时，
系统不再只是在终端抛 Traceback 然后死掉，而是将完整的"案发现场"
持久化到 MDR，供开发者离线复现。

核心机制：
  1. contextvars 捕获最后一次 LLM 上下文
     调用方（providers/bailian.py）在每次 LLM 调用后调用 set_last_llm_context()，
     无性能开销，仅设置 ContextVar。
     崩溃发生时，promptcontext.txt 可直接复现"有毒提示词"。

  2. sys.excepthook 全局接管
     通过 install_crash_handler() 替换系统异常钩子。
     KeyboardInterrupt 不介入，其他致命异常全部保全现场。

  3. 案发现场目录结构
     docs/memory/private/mdr/incident/{incident_id}/
     ├── call_stack.dmp          — 完整 traceback + 最深帧局部变量
     ├── prompt_context.txt      — 崩溃时的 LLM Prompt + Response（如有）
     └── incident_manifest.json — 结构化元数据（incident_id, ts, exc_type...）

使用方式：
    # cli.py 入口处（一次性安装）
    from mms.observability.incident import install_crash_handler
    install_crash_handler()

    # providers/bailian.py 每次 LLM 调用后
    from mms.observability.incident import set_last_llm_context
    set_last_llm_context(prompt=prompt_str, response=response_str)
"""

from __future__ import annotations

import contextvars
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── 路径解析 ──────────────────────────────────────────────────────────────────
try:
    from mms.utils._paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = Path(__file__).resolve().parent.parent.parent.parent

_MDR_INCIDENT_DIR = _ROOT / "docs" / "memory" / "private" / "mdr" / "incident"

# ── LLM 上下文 ContextVars ───────────────────────────────────────────────────
# 每个异步任务/线程持有独立副本，并发安全
_last_llm_prompt: contextvars.ContextVar[str] = contextvars.ContextVar(
    "mulan_last_llm_prompt", default=""
)
_last_llm_response: contextvars.ContextVar[str] = contextvars.ContextVar(
    "mulan_last_llm_response", default=""
)


def set_last_llm_context(prompt: str, response: str) -> None:
    """
    记录最近一次 LLM 调用的 Prompt 和 Response。

    供 providers/bailian.py 在每次 LLM 完成后调用。
    使用 ContextVar，在 asyncio / 多线程场景下各 EP 互不干扰。
    """
    _last_llm_prompt.set(prompt or "")
    _last_llm_response.set(response or "")


def get_last_llm_context() -> tuple[str, str]:
    """获取当前上下文的最后一次 LLM 输入/输出（调试用）。"""
    return _last_llm_prompt.get(""), _last_llm_response.get("")


# ── Incident Dump 核心 ────────────────────────────────────────────────────────

def _generate_incident_id(exc_type: type) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"inc_{ts}_{exc_type.__name__}"


def _write_call_stack(dump_dir: Path, exc_type: type, exc_value: BaseException, exc_tb: object) -> None:
    """写入 call_stack.dmp：完整 traceback + 最深崩溃帧的局部变量。"""
    lines: list[str] = []
    lines.append(f"FATAL ERROR: {exc_type.__name__}: {exc_value}")
    lines.append("=" * 60)
    lines.append("[TRACEBACK]")
    lines.extend(traceback.format_tb(exc_tb))  # type: ignore[arg-type]

    # 追溯到最深处的崩溃栈帧
    tb = exc_tb
    while getattr(tb, "tb_next", None):
        tb = tb.tb_next  # type: ignore[union-attr]

    if tb is not None:
        lines.append("")
        lines.append("=" * 60)
        lines.append("[LOCAL VARIABLES OF CRASH FRAME]")
        frame = tb.tb_frame  # type: ignore[union-attr]
        lines.append(f"  File: {frame.f_code.co_filename}, Line: {tb.tb_lineno}, in {frame.f_code.co_name}")  # type: ignore[union-attr]
        lines.append("")
        for key, value in frame.f_locals.items():
            try:
                repr_val = repr(value)
                if len(repr_val) > 500:
                    repr_val = repr_val[:500] + "... [truncated]"
            except Exception:
                repr_val = "<repr() failed>"
            lines.append(f"  {key} = {repr_val}")

    (dump_dir / "call_stack.dmp").write_text("\n".join(lines), encoding="utf-8")


def _write_prompt_context(dump_dir: Path) -> bool:
    """如有 LLM 上下文，写入 prompt_context.txt，返回是否写入。"""
    prompt = _last_llm_prompt.get("")
    response = _last_llm_response.get("")
    if not prompt and not response:
        return False
    content_parts = [
        "# Mulan Poisonous Prompt Context",
        "# 以下内容是崩溃发生前最后一次 LLM 调用的原始 Prompt 和 Response",
        "# 可直接复制到模型接口复现幻觉行为",
        "",
        "## PROMPT",
        prompt,
        "",
        "## RESPONSE",
        response,
    ]
    (dump_dir / "prompt_context.txt").write_text("\n".join(content_parts), encoding="utf-8")
    return True


def _write_manifest(
    dump_dir: Path,
    incident_id: str,
    exc_type: type,
    exc_value: BaseException,
    has_prompt: bool,
) -> None:
    """写入 incident_manifest.json：结构化元数据。"""
    manifest = {
        "incident_id": incident_id,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "exc_type": exc_type.__name__,
        "exc_message": str(exc_value)[:500],
        "has_prompt_context": has_prompt,
        "files": ["call_stack.dmp"] + (["prompt_context.txt"] if has_prompt else []),
    }
    (dump_dir / "incident_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def mulan_crash_handler(
    exc_type: type,
    exc_value: BaseException,
    exc_traceback: object,
) -> None:
    """
    全局异常接管钩子（sys.excepthook）。

    KeyboardInterrupt 走原始钩子，其他致命异常保全现场到 MDR/incident/。
    本函数自身有双重 try/except 保护，不会因诊断代码 bug 导致二次崩溃。
    """
    # KeyboardInterrupt 不介入，走系统默认处理
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    incident_id = _generate_incident_id(exc_type)
    dump_dir = _MDR_INCIDENT_DIR / incident_id

    try:
        dump_dir.mkdir(parents=True, exist_ok=True)
        _write_call_stack(dump_dir, exc_type, exc_value, exc_traceback)
        has_prompt = _write_prompt_context(dump_dir)
        _write_manifest(dump_dir, incident_id, exc_type, exc_value, has_prompt)

        # 写入全局告警日志
        try:
            from mms.observability.logger import alert_fatal  # type: ignore[import]
            alert_fatal(
                "incident",
                f"致命崩溃 — {exc_type.__name__}: {str(exc_value)[:120]}",
                incident_id=incident_id,
            )
        except Exception:
            pass

        # 用户友好提示
        print(
            f"\n[CRITICAL] Mulan 遇到致命错误：{exc_type.__name__}: {exc_value}",
            file=sys.stderr,
        )
        print(
            f"  案发现场已保存至: {dump_dir}",
            file=sys.stderr,
        )
        print(
            f"  使用 `mulan diag pack {incident_id}` 打包诊断包并附到 GitHub Issue。",
            file=sys.stderr,
        )

    except Exception as inner_exc:
        # 诊断代码自身崩溃时，退化为标准输出，绝对不能二次崩溃
        print(
            f"\n[CRITICAL] {exc_type.__name__}: {exc_value}",
            file=sys.stderr,
        )
        print(
            f"[WARNING] Incident dump 写入失败（诊断模块异常）: {inner_exc}",
            file=sys.stderr,
        )
        # 仍然打印原始 traceback
        traceback.print_exception(exc_type, exc_value, exc_traceback, file=sys.stderr)  # type: ignore[arg-type]


def install_crash_handler() -> None:
    """
    安装全局崩溃处理器（sys.excepthook = mulan_crash_handler）。

    应在 CLI 入口的最早期调用，且只调用一次。
    """
    sys.excepthook = mulan_crash_handler
