#!/usr/bin/env python3
"""
trace/tracer.py — EPTracer：EP 级别的诊断追踪主类

EPTracer 负责管理单个 EP 的完整追踪生命周期：
  - 创建/加载追踪配置（level、enabled）
  - 线程安全地追加写入 trace.jsonl
  - 提供 record() 接口供各模块在不同 level 下记录事件
  - 提供 step_timer() 上下文管理器自动计时

使用方式（非侵入式，tracer 为 None 时零开销）：

    # 在 ep_wizard 中开启
    tracer = EPTracer.enable("EP-126", level=4)

    # 在各模块中（tracer 可为 None）
    from trace.collector import get_tracer
    tracer = get_tracer("EP-126")
    with tracer.step("dag_generate") if tracer else nullcontext():
        ...

    # 记录 LLM 事件（Level 4）
    if tracer:
        tracer.record_llm(
            step="unit_run", unit_id="U1",
            model="qwen3-coder-next",
            tokens_in=896, tokens_out=1204,
            elapsed_ms=8400, attempt=1,
            llm_result="ok",
        )
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from .event import (
    TraceEvent,
    LEVEL_BASIC, LEVEL_LLM, LEVEL_FILEOPS, LEVEL_FULL,
    LEVEL_NAMES, _now_iso,
)

_HERE = Path(__file__).resolve().parent
try:
    from _paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE.parent.parent.parent
_TRACE_BASE = _ROOT / "docs" / "memory" / "private" / "trace"

_DEFAULT_LEVEL = LEVEL_LLM          # 默认 Level 4
_DEFAULT_MAX_EVENTS = 5000
_DEFAULT_PREVIEW_CHARS = 200

_write_lock = threading.Lock()


def _new_trace_id(ep_id: str) -> str:
    """生成 EP 级别的追踪 ID，格式：MMS-TRACE-EP126-YYYYMMDD-xxxxxx"""
    import secrets
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    ep_slug = ep_id.replace("-", "").upper()
    suffix = secrets.token_hex(3)
    return f"MMS-TRACE-{ep_slug}-{date_str}-{suffix}"


class TraceConfig:
    """单个 EP 的追踪配置（持久化到 trace_config.json）。"""

    def __init__(
        self,
        ep_id: str,
        enabled: bool = False,
        level: int = _DEFAULT_LEVEL,
        trace_id: Optional[str] = None,
        started_at: Optional[str] = None,
        stopped_at: Optional[str] = None,
        event_count: int = 0,
        max_events: int = _DEFAULT_MAX_EVENTS,
        preview_chars: int = _DEFAULT_PREVIEW_CHARS,
    ) -> None:
        self.ep_id = ep_id.upper()
        self.enabled = enabled
        self.level = level
        self.trace_id = trace_id or _new_trace_id(ep_id)
        self.started_at = started_at or _now_iso()
        self.stopped_at = stopped_at
        self.event_count = event_count
        self.max_events = max_events
        self.preview_chars = preview_chars

    @property
    def _config_path(self) -> Path:
        return _TRACE_BASE / self.ep_id / "trace_config.json"

    def save(self) -> None:
        path = self._config_path
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "ep_id": self.ep_id,
            "enabled": self.enabled,
            "level": self.level,
            "level_name": LEVEL_NAMES.get(self.level, "Unknown"),
            "trace_id": self.trace_id,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "event_count": self.event_count,
            "max_events": self.max_events,
            "preview_chars": self.preview_chars,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, ep_id: str) -> Optional["TraceConfig"]:
        ep_id = ep_id.upper()
        path = _TRACE_BASE / ep_id / "trace_config.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in data.items() if k != "level_name"})
        except Exception:
            return None

    @classmethod
    def load_or_default(cls, ep_id: str) -> "TraceConfig":
        cfg = cls.load(ep_id)
        return cfg if cfg is not None else cls(ep_id)


class EPTracer:
    """
    EP 级别的诊断追踪器。

    线程安全。各模块通过 collector.get_tracer(ep_id) 获取实例（可为 None）。
    所有 record_*() 方法在 tracer 级别低于事件要求时自动跳过，保证零开销。
    """

    def __init__(self, config: TraceConfig) -> None:
        self._cfg = config
        self._trace_path = _TRACE_BASE / config.ep_id / "trace.jsonl"
        self._trace_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def ep_id(self) -> str:
        return self._cfg.ep_id

    @property
    def trace_id(self) -> str:
        return self._cfg.trace_id

    @property
    def level(self) -> int:
        return self._cfg.level

    @property
    def enabled(self) -> bool:
        return self._cfg.enabled

    @property
    def preview_chars(self) -> int:
        return self._cfg.preview_chars

    # ── 静态工厂：开启/关闭 ──────────────────────────────────────────────────

    @classmethod
    def enable(
        cls,
        ep_id: str,
        level: int = _DEFAULT_LEVEL,
        max_events: int = _DEFAULT_MAX_EVENTS,
        preview_chars: int = _DEFAULT_PREVIEW_CHARS,
    ) -> "EPTracer":
        """
        开启 EP 的诊断追踪，返回 EPTracer 实例。
        如果已有配置，保留 trace_id，更新 level。
        """
        existing = TraceConfig.load(ep_id)
        if existing:
            existing.enabled = True
            existing.level = level
            existing.stopped_at = None
            existing.started_at = _now_iso()
            cfg = existing
        else:
            cfg = TraceConfig(
                ep_id=ep_id,
                enabled=True,
                level=level,
                max_events=max_events,
                preview_chars=preview_chars,
            )
        cfg.save()
        tracer = cls(cfg)
        # 写入 ep_start 事件
        tracer._append(TraceEvent.start(
            op="ep_start",
            ep_id=cfg.ep_id,
            trace_id=cfg.trace_id,
            step="ep_lifecycle",
            extra={"level": level, "level_name": LEVEL_NAMES.get(level, "?")}
        ).finish(result="ok"))
        return tracer

    @classmethod
    def disable(cls, ep_id: str) -> None:
        """关闭 EP 的诊断追踪，写入 ep_end 事件。"""
        cfg = TraceConfig.load(ep_id)
        if cfg is None:
            return
        cfg.enabled = False
        cfg.stopped_at = _now_iso()
        cfg.save()
        tracer = cls(cfg)
        tracer._append(TraceEvent.start(
            op="ep_end",
            ep_id=cfg.ep_id,
            trace_id=cfg.trace_id,
            step="ep_lifecycle",
        ).finish(result="ok", extra={"total_events": cfg.event_count}))

    @classmethod
    def from_ep(cls, ep_id: str) -> Optional["EPTracer"]:
        """
        获取已开启的 EPTracer 实例。如果追踪未开启或不存在，返回 None。
        这是各模块调用的主入口（通常通过 collector.get_tracer 访问）。
        """
        cfg = TraceConfig.load(ep_id)
        if cfg is None or not cfg.enabled:
            return None
        return cls(cfg)

    # ── 核心写入 ─────────────────────────────────────────────────────────────

    def _append(self, event: TraceEvent) -> None:
        """线程安全追加写入 trace.jsonl。超过 max_events 时停止写入并告警。"""
        if self._cfg.event_count >= self._cfg.max_events:
            return
        line = event.to_jsonl(level=self._cfg.level)
        with _write_lock:
            with self._trace_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            self._cfg.event_count += 1
            # 每 50 个事件保存一次 config（减少 IO）
            if self._cfg.event_count % 50 == 0:
                self._cfg.save()

    # ── 通用记录接口 ─────────────────────────────────────────────────────────

    def record(self, event: TraceEvent) -> None:
        """记录任意 TraceEvent（已调用 .finish() 的）。"""
        if not self._cfg.enabled:
            return
        self._append(event)

    # ── 便捷方法：各操作类型 ─────────────────────────────────────────────────

    def record_step(
        self,
        step: str,
        result: str = "ok",
        elapsed_ms: Optional[float] = None,
        error_msg: Optional[str] = None,
        **extra: Any,
    ) -> None:
        """记录步骤级事件（Level 1）。"""
        if not self._cfg.enabled or self._cfg.level < LEVEL_BASIC:
            return
        evt = TraceEvent(
            op="step_end",
            ep_id=self.ep_id,
            trace_id=self.trace_id,
            step=step,
            result=result,
            error_msg=error_msg,
            extra=extra,
        )
        if elapsed_ms is not None:
            evt.elapsed_ms = elapsed_ms
        self._append(evt)

    def record_llm(
        self,
        step: str,
        model: str,
        tokens_in: Optional[int],
        tokens_out: Optional[int],
        elapsed_ms: float,
        result: str = "ok",
        unit_id: Optional[str] = None,
        attempt: int = 1,
        max_attempts: int = 3,
        llm_result: Optional[str] = None,
        error_msg: Optional[str] = None,
        prompt: Optional[str] = None,
        response: Optional[str] = None,
        **extra: Any,
    ) -> None:
        """记录 LLM 调用事件（Level 4）。"""
        if not self._cfg.enabled or self._cfg.level < LEVEL_LLM:
            return
        pc = self._cfg.preview_chars
        evt = TraceEvent(
            op="llm_call",
            ep_id=self.ep_id,
            trace_id=self.trace_id,
            step=step,
            unit_id=unit_id,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            elapsed_ms=elapsed_ms,
            result=result,
            error_msg=error_msg,
            llm_attempt=attempt,
            llm_max_attempts=max_attempts,
            llm_result=llm_result or result,
            prompt_preview=prompt[:pc] if prompt and self._cfg.level >= LEVEL_FULL else None,
            response_preview=response[:pc] if response and self._cfg.level >= LEVEL_FULL else None,
            extra=extra,
        )
        self._append(evt)

    def record_validation(
        self,
        step: str,
        arch_ok: bool,
        test_ok: bool,
        elapsed_ms: float,
        unit_id: Optional[str] = None,
        arch_violations: Optional[List[str]] = None,
        test_summary: Optional[str] = None,
        **extra: Any,
    ) -> None:
        """记录验证事件（arch_check + pytest，Level 4）。"""
        if not self._cfg.enabled or self._cfg.level < LEVEL_LLM:
            return
        result = "ok" if arch_ok and test_ok else "error"
        evt = TraceEvent(
            op="validation",
            ep_id=self.ep_id,
            trace_id=self.trace_id,
            step=step,
            unit_id=unit_id,
            arch_ok=arch_ok,
            arch_violations=arch_violations,
            test_ok=test_ok,
            test_summary=test_summary,
            elapsed_ms=elapsed_ms,
            result=result,
            extra=extra,
        )
        self._append(evt)

    def record_file_ops(
        self,
        step: str,
        files_changed: Optional[List[str]] = None,
        files_rejected: Optional[List[str]] = None,
        lines_added: Optional[int] = None,
        lines_removed: Optional[int] = None,
        unit_id: Optional[str] = None,
        **extra: Any,
    ) -> None:
        """记录文件操作事件（Level 8）。"""
        if not self._cfg.enabled or self._cfg.level < LEVEL_FILEOPS:
            return
        result = "ok" if not files_rejected else "partial"
        evt = TraceEvent(
            op="file_ops",
            ep_id=self.ep_id,
            trace_id=self.trace_id,
            step=step,
            unit_id=unit_id,
            files_changed=files_changed,
            files_rejected=files_rejected,
            lines_added=lines_added,
            lines_removed=lines_removed,
            result=result,
            extra=extra,
        )
        self._append(evt)

    def record_git(
        self,
        commit_hash: Optional[str],
        unit_id: Optional[str] = None,
        step: str = "unit_run",
        **extra: Any,
    ) -> None:
        """记录 git commit 事件（Level 1）。"""
        if not self._cfg.enabled:
            return
        evt = TraceEvent(
            op="git_commit",
            ep_id=self.ep_id,
            trace_id=self.trace_id,
            step=step,
            unit_id=unit_id,
            result="ok" if commit_hash else "skip",
            extra={"commit_hash": commit_hash, **extra},
        )
        self._append(evt)

    # ── 上下文管理器：自动计时步骤 ───────────────────────────────────────────

    @contextmanager
    def step_timer(
        self,
        step: str,
        unit_id: Optional[str] = None,
        **extra: Any,
    ) -> Generator[TraceEvent, None, None]:
        """
        上下文管理器：自动记录步骤开始和结束事件。

        Example:
            with tracer.step_timer("dag_generate") as evt:
                result = generate_dag(...)
                evt.extra["units_count"] = len(result.units)
        """
        evt = TraceEvent.start(
            op="step_start",
            ep_id=self.ep_id,
            trace_id=self.trace_id,
            step=step,
            unit_id=unit_id,
            extra=extra,
        )
        if self._cfg.enabled:
            self._append(evt)
        try:
            yield evt
            evt.finish(result="ok")
        except Exception as e:
            evt.finish(result="error", error_msg=str(e))
            raise
        finally:
            if self._cfg.enabled:
                end_evt = TraceEvent(
                    op="step_end",
                    ep_id=self.ep_id,
                    trace_id=self.trace_id,
                    step=step,
                    unit_id=unit_id,
                    result=evt.result,
                    error_msg=evt.error_msg,
                    elapsed_ms=evt.elapsed_ms,
                    extra=evt.extra,
                )
                self._append(end_evt)

    def flush(self) -> None:
        """强制保存 config（通常在 EP 结束时调用）。"""
        self._cfg.save()
