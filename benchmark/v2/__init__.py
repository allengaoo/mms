"""
Mulan Benchmark v2 — 三层模块化评测框架

层次结构：
  Layer 1 (SWE-bench) ← 信用锚，与工业标准对齐
  Layer 2 (Memory)    ← 核心价值，评测记忆注入质量
  Layer 3 (Safety)    ← 工程护盾，评测安全门控有效性

快速开始：
  from benchmark.v2.runner import run_benchmark, main
  from benchmark.v2.schema import BenchmarkConfig, RunLevel

  config = BenchmarkConfig(level=RunLevel.OFFLINE_ONLY)
  result = run_benchmark(config)
"""
from benchmark.v2.schema import (
    BenchmarkConfig,
    BenchmarkLayer,
    BenchmarkResult,
    LayerResult,
    RunLevel,
    TaskResult,
    TaskStatus,
)
from benchmark.v2.runner import run_benchmark, report

__all__ = [
    "BenchmarkConfig",
    "BenchmarkLayer",
    "BenchmarkResult",
    "LayerResult",
    "RunLevel",
    "TaskResult",
    "TaskStatus",
    "run_benchmark",
    "report",
]

__version__ = "2.0.0"
