#!/usr/bin/env python3
"""
observability/logger.py — Mulan 全局告警日志（系统心电图）

设计参考 Oracle ADR 的 alert_<sid>.log：只记录重大系统级事件，
绝对不记录业务代码的生成内容，保持文件小且可 tail -f 实时监控。

写入路径：docs/memory/private/mdr/alert/alert_mulan.log
轮转策略：按天轮转，保留 30 天历史

告警级别：
  INFO  — 正常生命周期事件（启动、关闭、索引就绪）
  WARN  — 降级、资源告警（磁盘空间不足、沙箱挂载失败）
  FATAL — 熔断器开路、致命崩溃、Incident 触发

使用方式（模块级函数，无需实例化）：
    from mms.observability.logger import alert_info, alert_fatal, alert_circuit

    alert_info("cli", "Mulan 引擎启动完毕，加载配置 config.yaml")
    alert_fatal("circuit_breaker", "熔断器开路 — qwen3-coder-next 连续失败 3 次")
    alert_circuit("qwen3-coder-next", "CLOSED", "OPEN", "连续失败 3 次")
"""

from __future__ import annotations

import logging
import threading
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── 路径解析 ──────────────────────────────────────────────────────────────────
try:
    from mms.utils._paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = Path(__file__).resolve().parent.parent.parent.parent  # src/mms/observability → project root

_MDR_ALERT_DIR = _ROOT / "docs" / "memory" / "private" / "mdr" / "alert"
_ALERT_LOG_PATH = _MDR_ALERT_DIR / "alert_mulan.log"

# ── 内部单例 ──────────────────────────────────────────────────────────────────
_logger: logging.Logger | None = None
_init_lock = threading.Lock()


def _get_logger() -> logging.Logger:
    """延迟初始化全局 Logger（首次调用时建目录，避免 import 副作用）。"""
    global _logger
    if _logger is not None:
        return _logger
    with _init_lock:
        if _logger is not None:
            return _logger

        _MDR_ALERT_DIR.mkdir(parents=True, exist_ok=True)

        logger = logging.getLogger("mulan.alert")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False  # 不向上传播到 root logger

        if not logger.handlers:
            # 按天轮转，保留 30 天
            handler = TimedRotatingFileHandler(
                filename=str(_ALERT_LOG_PATH),
                when="midnight",
                interval=1,
                backupCount=30,
                encoding="utf-8",
                utc=True,
            )
            handler.setFormatter(logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ))
            logger.addHandler(handler)

        _logger = logger
    return _logger


# ── 公开 API ─────────────────────────────────────────────────────────────────

def alert_info(module: str, message: str, **kw: Any) -> None:
    """记录 INFO 级告警（正常生命周期事件：启动、关闭、索引就绪）。"""
    _emit("INFO", module, message, **kw)


def alert_warn(module: str, message: str, **kw: Any) -> None:
    """记录 WARN 级告警（资源告警、降级、非致命异常）。"""
    _emit("WARN", module, message, **kw)


def alert_fatal(module: str, message: str, **kw: Any) -> None:
    """记录 FATAL 级告警（熔断器开路、致命崩溃、Incident 触发）。"""
    _emit("FATAL", module, message, **kw)


def alert_circuit(
    model_name: str,
    old_state: str,
    new_state: str,
    reason: str,
) -> None:
    """
    记录熔断器状态转移事件（专用接口，格式固定）。

    Args:
        model_name: 模型名（如 "qwen3-coder-next"）
        old_state:  转移前状态（CLOSED / OPEN / HALF_OPEN）
        new_state:  转移后状态
        reason:     触发原因（如 "连续失败 3 次"）
    """
    level = "FATAL" if new_state == "OPEN" else "WARN" if new_state == "HALF_OPEN" else "INFO"
    message = (
        f"[Circuit Breaker] {model_name}: {old_state} → {new_state} | {reason}"
    )
    _emit(level, "circuit_breaker", message)


def _emit(level: str, module: str, message: str, **kw: Any) -> None:
    """内部：构造日志行并写入，任何内部异常均被静默忽略。"""
    try:
        logger = _get_logger()
        # 附加扩展字段（key=value 形式追加到消息末尾）
        extra_str = ""
        if kw:
            extra_str = " | " + " ".join(f"{k}={v}" for k, v in kw.items())
        full_msg = f"[{module}] {message}{extra_str}"

        if level == "FATAL":
            logger.critical(full_msg)
        elif level == "WARN":
            logger.warning(full_msg)
        else:
            logger.info(full_msg)
    except Exception:
        pass  # 日志模块自身不能崩溃


def get_log_path() -> Path:
    """返回当前 alert_mulan.log 的绝对路径（供 CLI 读取）。"""
    return _ALERT_LOG_PATH


def tail_log(n: int = 50) -> list[str]:
    """
    读取 alert_mulan.log 最后 n 行。

    如果文件不存在，返回空列表。用于 mulan diag status 命令。
    """
    if not _ALERT_LOG_PATH.exists():
        return []
    try:
        lines = _ALERT_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-n:] if len(lines) > n else lines
    except OSError:
        return []
