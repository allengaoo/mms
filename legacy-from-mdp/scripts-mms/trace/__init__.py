"""
trace — MMS 诊断追踪模块

类比 Oracle 10046 Trace，为 MMS EP 工作流提供全链路诊断能力。

核心组件：
  event.py      TraceEvent 数据结构（Level 1/4/8/12）
  tracer.py     EPTracer 主类（开启/关闭/记录事件）
  collector.py  全局 Tracer 注册表（各模块通过 get_tracer 访问）
  reporter.py   报告生成器（text/json/html，类比 tkprof）

快速使用：
  from trace.tracer import EPTracer
  from trace.collector import get_tracer, estimate_tokens

  # 开启追踪
  tracer = EPTracer.enable("EP-126", level=4)

  # 各模块中（tracer 可为 None，零开销）
  tracer = get_tracer("EP-126")
  if tracer:
      tracer.record_llm(step="unit_run", model="qwen3-coder-next", ...)
"""

from .event import (
    TraceEvent,
    LEVEL_BASIC, LEVEL_LLM, LEVEL_FILEOPS, LEVEL_FULL,
    LEVEL_NAMES,
)
from .tracer import EPTracer, TraceConfig
from .collector import get_tracer, register_tracer, invalidate, estimate_tokens
from .reporter import generate_report, generate_summary_text, list_traced_eps

__all__ = [
    "TraceEvent",
    "LEVEL_BASIC", "LEVEL_LLM", "LEVEL_FILEOPS", "LEVEL_FULL", "LEVEL_NAMES",
    "EPTracer", "TraceConfig",
    "get_tracer", "register_tracer", "invalidate", "estimate_tokens",
    "generate_report", "generate_summary_text", "list_traced_eps",
]
