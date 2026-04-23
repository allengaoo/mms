#!/usr/bin/env python3
"""
trace/event.py — MMS 诊断追踪事件数据结构

设计参考：Oracle 10046 Trace 的事件驱动模型。
每一个可观测的操作产生一个 TraceEvent，追加写入 trace.jsonl。

诊断级别（类比 10046 Level）：
  Level 1  Basic    — 步骤耗时、成功/失败、Unit 状态变更
  Level 4  LLM      — +LLM 调用详情（模型/token/重试次数/结果）
  Level 8  FileOps  — +文件变更详情（路径/行数/Scope Guard 结果）
  Level 12 Full     — +LLM 完整 prompt/response 片段（前 N 字符）

事件类型（op 字段枚举）：
  ep_start / ep_end              — EP 工作流开启/结束
  step_start / step_end          — 向导步骤（precheck/dag_generate/unit_run/...）
  llm_call                       — LLM API 调用
  llm_retry                      — LLM 3-Strike 重试
  arch_check                     — 架构约束扫描
  pytest_run                     — 测试执行
  file_write / file_reject       — 文件写入 / Scope Guard 拒绝
  scope_guard                    — Scope Guard 事件
  git_commit                     — git 提交
  sonnet_save                    — Sonnet 输出保存
  compare                        — 双模型对比
  apply                          — 版本应用
  precheck / postcheck           — 前/后校验
  dag_generate                   — DAG 生成
  distill / dream                — 知识蒸馏 / 草稿生成
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ── 级别常量 ──────────────────────────────────────────────────────────────────

LEVEL_BASIC    = 1   # 步骤级别
LEVEL_LLM      = 4   # LLM 调用级别
LEVEL_FILEOPS  = 8   # 文件操作级别
LEVEL_FULL     = 12  # 全量（含 LLM IO 内容）

LEVEL_NAMES = {
    LEVEL_BASIC:   "Basic",
    LEVEL_LLM:     "LLM",
    LEVEL_FILEOPS:  "FileOps",
    LEVEL_FULL:    "Full",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_ms() -> float:
    return time.monotonic() * 1000


# ── 核心数据结构 ──────────────────────────────────────────────────────────────

@dataclass
class TraceEvent:
    """
    单条诊断追踪事件。

    对应 10046 Trace 中的一行事件记录，包含操作类型、耗时、关联的
    EP/Unit/模型信息以及操作结果。

    使用 TraceEvent.start() 创建，调用 .finish() 记录结束时间。
    """

    # ── 基础字段（Level 1+，所有事件必含）──────────────────────────────────
    op: str                        # 操作类型（见模块文档枚举）
    ep_id: str                     # EP 编号（如 "EP-126"）
    trace_id: str                  # 本次 EP 的追踪 ID
    ts_start: str = field(default_factory=_now_iso)
    ts_end: Optional[str] = None
    elapsed_ms: Optional[float] = None
    result: str = "ok"             # ok / error / retry / skip / rollback
    error_msg: Optional[str] = None

    # 步骤信息
    step: Optional[str] = None     # 所属步骤（synthesize/precheck/dag_generate/unit_run/...）
    unit_id: Optional[str] = None  # Unit ID（如 "U1"）
    phase: Optional[str] = None    # 操作阶段（parse/execute/validate/apply/commit）

    # ── LLM 相关（Level 4+）────────────────────────────────────────────────
    model: Optional[str] = None           # 使用的模型名
    tokens_in: Optional[int] = None       # 输入 token 估算（字符/4）
    tokens_out: Optional[int] = None      # 输出 token 估算
    llm_attempt: Optional[int] = None     # 第几次尝试（3-Strike 中，1-based）
    llm_max_attempts: Optional[int] = None
    llm_result: Optional[str] = None      # success/parse_fail/syntax_error/scope_reject/timeout
    prompt_preview: Optional[str] = None  # prompt 前 N 字符（Level 12）
    response_preview: Optional[str] = None # response 前 N 字符（Level 12）

    # ── 文件操作相关（Level 8+）────────────────────────────────────────────
    files_changed: Optional[List[str]] = None    # 成功写入的文件
    files_rejected: Optional[List[str]] = None   # Scope Guard 拒绝的文件
    lines_added: Optional[int] = None
    lines_removed: Optional[int] = None
    file_action: Optional[str] = None    # create / replace

    # ── 验证相关（Level 4+）────────────────────────────────────────────────
    arch_ok: Optional[bool] = None
    arch_violations: Optional[List[str]] = None
    test_ok: Optional[bool] = None
    test_summary: Optional[str] = None   # pytest 摘要行

    # ── 扩展字段 ────────────────────────────────────────────────────────────
    extra: Dict[str, Any] = field(default_factory=dict)

    # 内部：记录 monotonic 起始时间用于精确计时
    _mono_start: float = field(default_factory=_now_ms, repr=False, compare=False)

    def finish(
        self,
        result: str = "ok",
        error_msg: Optional[str] = None,
        **kwargs: Any,
    ) -> "TraceEvent":
        """
        记录事件结束时间和耗时，更新结果字段。

        Returns:
            self（链式调用）

        Example:
            event = TraceEvent.start("llm_call", ep_id="EP-126", ...)
            ...  # 执行操作
            event.finish(result="ok", tokens_in=512, tokens_out=256)
        """
        self.ts_end = _now_iso()
        self.elapsed_ms = round(_now_ms() - self._mono_start, 1)
        self.result = result
        if error_msg is not None:
            self.error_msg = error_msg
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)
            else:
                self.extra[k] = v
        return self

    @classmethod
    def start(cls, op: str, ep_id: str, trace_id: str, **kwargs: Any) -> "TraceEvent":
        """
        工厂方法：创建并记录起始时间。
        已知字段直接设置，未知字段路由到 extra 字典。
        """
        import dataclasses
        known = {f.name for f in dataclasses.fields(cls) if f.name != "extra"}
        known_kwargs = {k: v for k, v in kwargs.items() if k in known}
        extra_kwargs = {k: v for k, v in kwargs.items() if k not in known}
        evt = cls(op=op, ep_id=ep_id, trace_id=trace_id, **known_kwargs)
        if extra_kwargs:
            evt.extra.update(extra_kwargs)
        return evt

    def to_dict(self, level: int = LEVEL_BASIC) -> Dict[str, Any]:
        """
        将事件序列化为字典，按级别过滤字段。

        Args:
            level: 当前诊断级别，低于字段要求级别的字段被省略
        """
        d: Dict[str, Any] = {
            "op": self.op,
            "ep_id": self.ep_id,
            "trace_id": self.trace_id,
            "ts_start": self.ts_start,
            "result": self.result,
        }
        if self.ts_end is not None:
            d["ts_end"] = self.ts_end
        if self.elapsed_ms is not None:
            d["elapsed_ms"] = self.elapsed_ms
        if self.error_msg is not None:
            d["error_msg"] = self.error_msg
        if self.step is not None:
            d["step"] = self.step
        if self.unit_id is not None:
            d["unit_id"] = self.unit_id
        if self.phase is not None:
            d["phase"] = self.phase

        # Level 4+：LLM 相关
        if level >= LEVEL_LLM:
            for attr in ("model", "tokens_in", "tokens_out", "llm_attempt",
                         "llm_max_attempts", "llm_result", "arch_ok",
                         "arch_violations", "test_ok", "test_summary"):
                v = getattr(self, attr)
                if v is not None:
                    d[attr] = v

        # Level 8+：文件操作相关
        if level >= LEVEL_FILEOPS:
            for attr in ("files_changed", "files_rejected", "lines_added",
                         "lines_removed", "file_action"):
                v = getattr(self, attr)
                if v is not None:
                    d[attr] = v

        # Level 12：LLM IO 内容预览
        if level >= LEVEL_FULL:
            if self.prompt_preview is not None:
                d["prompt_preview"] = self.prompt_preview
            if self.response_preview is not None:
                d["response_preview"] = self.response_preview

        if self.extra:
            d.update(self.extra)

        return d

    def to_jsonl(self, level: int = LEVEL_BASIC) -> str:
        """序列化为单行 JSON（用于追加写入 trace.jsonl）。"""
        return json.dumps(self.to_dict(level), ensure_ascii=False, separators=(",", ":"))
