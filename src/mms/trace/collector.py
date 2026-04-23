#!/usr/bin/env python3
"""
trace/collector.py — 全局 Tracer 注册表（进程级单例）

各模块通过 get_tracer(ep_id) 获取当前 EP 的 EPTracer 实例。
返回 None 表示追踪未开启，调用方无需任何修改（零开销）。

设计原则：
  - 进程内缓存已激活的 Tracer（避免每次重新读磁盘）
  - 线程安全（多个 Unit 并行执行时不冲突）
  - 懒加载：首次调用 get_tracer 时才从磁盘读取配置

使用示例（各模块中）：

    from mms.trace.collector import get_tracer

    def run_something(ep_id: str, unit_id: str):
        tracer = get_tracer(ep_id)          # None 或 EPTracer
        t0 = time.monotonic()
        result = do_llm_call(...)
        elapsed = (time.monotonic() - t0) * 1000
        if tracer:
            tracer.record_llm(
                step="unit_run",
                unit_id=unit_id,
                model="qwen3-coder-next",
                tokens_in=estimate_tokens(prompt),
                tokens_out=estimate_tokens(result),
                elapsed_ms=elapsed,
            )
"""

from __future__ import annotations

import threading
from typing import Dict, Optional

# 避免循环导入：延迟导入 EPTracer
_lock = threading.Lock()
_registry: Dict[str, object] = {}   # ep_id -> EPTracer | None（None 表示已确认未开启）


def get_tracer(ep_id: str) -> Optional[object]:
    """
    获取指定 EP 的 EPTracer 实例。

    Args:
        ep_id: EP 编号（如 "EP-126"）

    Returns:
        EPTracer 实例（如果追踪已开启），否则 None。

    Note:
        结果在进程内缓存。如果在同一进程中调用了 enable_trace / disable_trace，
        请先调用 invalidate(ep_id) 清除缓存。
    """
    ep_id = ep_id.upper()
    with _lock:
        if ep_id in _registry:
            return _registry[ep_id]

    # 懒加载：从磁盘读取配置
    try:
        from .tracer import EPTracer  # type: ignore[import]
        tracer = EPTracer.from_ep(ep_id)
    except Exception:
        tracer = None

    with _lock:
        _registry[ep_id] = tracer
    return tracer


def register_tracer(ep_id: str, tracer: object) -> None:
    """
    注册一个已创建的 EPTracer（供 ep_wizard 开启追踪后立即注册）。

    Args:
        ep_id:   EP 编号
        tracer:  EPTracer 实例（或 None 表示关闭）
    """
    ep_id = ep_id.upper()
    with _lock:
        _registry[ep_id] = tracer


def invalidate(ep_id: str) -> None:
    """
    清除指定 EP 的缓存，下次 get_tracer 时重新从磁盘加载。
    在 enable / disable 操作后调用。
    """
    ep_id = ep_id.upper()
    with _lock:
        _registry.pop(ep_id, None)


def list_active() -> list:
    """
    列出当前进程中所有已激活（非 None）的 EP Tracer EP ID。
    """
    with _lock:
        return [eid for eid, t in _registry.items() if t is not None]


def estimate_tokens(text: Optional[str]) -> Optional[int]:
    """
    快速估算文本的 token 数（字符数 / 4，与 OpenAI tiktoken 近似）。
    用于在不引入 tokenizer 依赖的情况下统计 token 消耗。
    """
    if text is None:
        return None
    return max(1, len(text) // 4)
