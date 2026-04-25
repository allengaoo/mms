"""
Mulan Benchmark v2 — 共享数据结构

设计原则：
  - 所有跨层共享的数据类型都在此定义
  - 使用 dataclass 而非 dict，确保类型安全
  - 每层 Evaluator 只依赖此模块，不跨层依赖
  - 新增指标：只需在 LayerResult.metrics 中添加 key，无需修改接口
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# 枚举：层级标识
# ─────────────────────────────────────────────────────────────────────────────

class BenchmarkLayer(Enum):
    LAYER1_SWEBENCH = 1   # SWE-bench 信用锚
    LAYER2_MEMORY   = 2   # 记忆质量评测
    LAYER3_SAFETY   = 3   # 安全门控评测（离线）


class RunLevel(Enum):
    """运行级别：决定哪些层会被执行"""
    OFFLINE_ONLY = 0      # 仅 Layer 3（无需 LLM API，< 10s）
    FAST         = 1      # Layer 2 + Layer 3（需 LLM，< 30min）
    FULL         = 2      # 全部三层（需 LLM + Docker，< 2h）


class TaskStatus(Enum):
    PASSED  = "passed"
    FAILED  = "failed"
    SKIPPED = "skipped"
    ERROR   = "error"


# ─────────────────────────────────────────────────────────────────────────────
# 单任务结果
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TaskResult:
    """单条测试任务的评测结果"""
    task_id:          str
    status:           TaskStatus
    score:            float = 0.0          # 0.0 – 1.0
    details:          Dict[str, Any] = field(default_factory=dict)
    error_message:    Optional[str]  = None
    duration_seconds: float          = 0.0

    @property
    def passed(self) -> bool:
        return self.status == TaskStatus.PASSED


# ─────────────────────────────────────────────────────────────────────────────
# 单层汇总结果
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class LayerResult:
    """单个评测层的汇总结果"""
    layer:            BenchmarkLayer
    name:             str
    tasks_total:      int
    tasks_passed:     int
    tasks_skipped:    int
    tasks_failed:     int
    score:            float                         # 该层综合得分 0.0 – 1.0
    metrics:          Dict[str, float] = field(default_factory=dict)  # 层级专属指标
    task_results:     List[TaskResult]  = field(default_factory=list)
    error:            Optional[str]     = None
    duration_seconds: float             = 0.0

    @property
    def pass_rate(self) -> float:
        if self.tasks_total == 0:
            return 0.0
        return self.tasks_passed / self.tasks_total

    @property
    def skip_rate(self) -> float:
        if self.tasks_total == 0:
            return 0.0
        return self.tasks_skipped / self.tasks_total


# ─────────────────────────────────────────────────────────────────────────────
# 整体 Benchmark 结果
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BenchmarkResult:
    """三层 Benchmark 的完整结果"""
    version:       str = "v2.0"
    timestamp:     str = field(
        default_factory=lambda: datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    )
    layer_results: Dict[int, LayerResult] = field(default_factory=dict)
    config:        Dict[str, Any]         = field(default_factory=dict)

    @property
    def overall_score(self) -> float:
        scores = [lr.score for lr in self.layer_results.values()]
        return sum(scores) / len(scores) if scores else 0.0

    def get_layer(self, layer: BenchmarkLayer) -> Optional[LayerResult]:
        return self.layer_results.get(layer.value)


# ─────────────────────────────────────────────────────────────────────────────
# Benchmark 配置
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BenchmarkConfig:
    """
    Benchmark 运行配置

    扩展方式：
      - 新增 domain：在 domains 列表中加入新值，对应 tasks/<domain>/ 目录
      - 新增层：在 layers 中加入新 BenchmarkLayer 值
    """
    level:         RunLevel            = RunLevel.OFFLINE_ONLY
    layers:        List[BenchmarkLayer] = field(
        default_factory=lambda: [BenchmarkLayer.LAYER3_SAFETY]
    )
    domains:       List[str]           = field(
        default_factory=lambda: ["generic_python"]
    )
    max_tasks:     Optional[int]       = None     # None = 运行全部
    dry_run:       bool                = False     # 仅打印将要执行的任务，不实际执行
    llm_available: bool                = False     # 是否有 LLM API 可用
    output_format: str                 = "console" # console | json | markdown
    output_path:   Optional[str]       = None      # 为 None 时输出到 stdout
    repo_root:     Optional[str]       = None      # 项目根目录（自动检测）
    verbose:       bool                = False


# ─────────────────────────────────────────────────────────────────────────────
# 评测器基类（Protocol）
# ─────────────────────────────────────────────────────────────────────────────

class BaseEvaluator:
    """
    所有层级 Evaluator 的基类。

    新增评测层只需：
      1. 继承此类
      2. 实现 run() 和 layer 属性
      3. 在 runner.py 中注册
    """

    @property
    def layer(self) -> BenchmarkLayer:
        raise NotImplementedError

    @property
    def is_offline_capable(self) -> bool:
        """是否可以在无 LLM API 的环境下运行（用于 CI 离线检查）"""
        return False

    def run(self, config: BenchmarkConfig) -> LayerResult:
        raise NotImplementedError

    def _make_skipped_result(self, reason: str) -> LayerResult:
        return LayerResult(
            layer=self.layer,
            name=self.__class__.__name__,
            tasks_total=0,
            tasks_passed=0,
            tasks_skipped=0,
            tasks_failed=0,
            score=0.0,
            error=reason,
        )
