"""
MMS 审计日志记录器（Append-only JSONL）

审计事件类型：
  route            — 路由决策（任务 → 模型）
  distill          — 知识蒸馏（EP → 新记忆）
  gc               — 垃圾回收（LFU 淘汰）
  read             — 记忆读取（访问模式追踪）
  write            — 记忆写入（新建/更新）
  validate         — Schema 校验
  circuit_open     — 熔断器开路
  circuit_close    — 熔断器闭合
  checkpoint_save  — 断点保存
  checkpoint_restore— 断点恢复

输出文件：
  audit.jsonl      — 操作审计（调试、诊断）
  access_log.jsonl — 记忆访问记录（GC LFU 计算基础）
"""
import datetime
import json
import threading
from pathlib import Path
from typing import Any, Optional

try:
    from mms.utils._paths import DOCS_MEMORY as _MEMORY_ROOT  # type: ignore[import]
except ImportError:
    _MEMORY_ROOT = Path(__file__).resolve().parent.parent / "docs" / "memory"

_SYSTEM_DIR = _MEMORY_ROOT / "_system"

_AUDIT_FILE = _SYSTEM_DIR / "audit.jsonl"
_ACCESS_FILE = _SYSTEM_DIR / "access_log.jsonl"

# 线程锁，防止多线程并发写入损坏文件
_audit_lock = threading.Lock()
_access_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _append_jsonl(path: Path, record: dict) -> None:
    """线程安全的 JSONL 追加写入"""
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


class AuditLogger:
    """
    MMS 审计日志记录器。

    每个实例无状态，可在任何地方安全创建和使用。

    Example:
        logger = AuditLogger()
        logger.log(
            trace_id="MMS-20260411-a1b2c3",
            op="distill",
            ep="EP-108",
            model="deepseek-r1:8b",
            result="ok",
            new_memories=["MEM-L-025"],
            elapsed_ms=3200,
        )
    """

    def log(
        self,
        trace_id: str,
        op: str,
        *,
        result: str = "ok",
        ep: Optional[str] = None,
        task: Optional[str] = None,
        model: Optional[str] = None,
        elapsed_ms: Optional[int] = None,
        new_memories: Optional[list] = None,
        merged_memories: Optional[list] = None,
        error: Optional[str] = None,
        token_estimate: Optional[int] = None,
        **extra: Any,
    ) -> None:
        """
        写入一条审计记录到 audit.jsonl。

        Args:
            trace_id:    操作追踪 ID
            op:          操作类型（route/distill/gc/read/write/validate/...）
            result:      结果（ok / error / fallback / skipped / pending）
            ep:          关联 EP 编号
            task:        任务类型（与 model_router 映射对应）
            model:       实际使用的模型名
            elapsed_ms:  操作耗时（毫秒）
            new_memories: 本次新生成的记忆 ID 列表
            merged_memories: 本次合并的记忆 ID 列表
            error:       错误信息（result=error 时填写）
            token_estimate: 估算 token 数（字符数 / 4）
            **extra:     其他扩展字段
        """
        record: dict = {
            "ts": _now_iso(),
            "trace_id": trace_id,
            "op": op,
            "result": result,
        }
        if ep is not None:
            record["ep"] = ep
        if task is not None:
            record["task"] = task
        if model is not None:
            record["model"] = model
        if elapsed_ms is not None:
            record["elapsed_ms"] = elapsed_ms
        if new_memories is not None:
            record["new_memories"] = new_memories
        if merged_memories is not None:
            record["merged_memories"] = merged_memories
        if error is not None:
            record["error"] = error
        if token_estimate is not None:
            record["token_estimate"] = token_estimate
        record.update(extra)

        with _audit_lock:
            _append_jsonl(_AUDIT_FILE, record)

    def log_access(
        self,
        memory_id: str,
        trace_id: str,
        *,
        ep: Optional[str] = None,
        task: Optional[str] = None,
    ) -> None:
        """
        记录一次记忆访问（写入 access_log.jsonl，供 GC LFU 计算使用）。
        """
        record = {
            "ts": _now_iso(),
            "trace_id": trace_id,
            "memory_id": memory_id,
        }
        if ep is not None:
            record["ep"] = ep
        if task is not None:
            record["task"] = task

        with _access_lock:
            _append_jsonl(_ACCESS_FILE, record)
