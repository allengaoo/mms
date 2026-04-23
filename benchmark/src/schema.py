"""
schema.py — Benchmark 全局数据类型定义
=======================================
所有跨模块共享的数据结构集中在此文件。
当需要新增字段或修改类型时，只改这一个文件。

设计原则：
  - 使用 dataclass 而非 dict，保证字段明确、类型安全
  - 所有字段提供默认值，方便渐进式扩展
  - to_dict() 用于序列化到 JSONL，from_dict() 用于反序列化
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# 测试数据结构
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class GroundTruth:
    """
    单条任务的 Ground Truth 标注。
    GT 的设计独立于任何检索系统，基于"完成任务工程师必须打开哪些文件"的客观判断。
    """
    layer: str                          # 架构层 ID（如 L4_service），来自 layers.yaml
    operation: str                      # 操作类型（如 create），来自 operations.yaml
    key_files: List[str]                # 必须访问的代码文件（磁盘验证过）
    key_memory_ids: List[str]           # 关联的约束记忆 ID（如 MEM-DB-002）
    has_executable_cmd: bool = False    # 是否存在可直接执行的命令

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "GroundTruth":
        return cls(
            layer=d["layer"],
            operation=d["operation"],
            key_files=d.get("key_files", []),
            key_memory_ids=d.get("key_memory_ids", []),
            has_executable_cmd=d.get("has_executable_cmd", False),
        )


@dataclass
class Query:
    """
    单条 Benchmark 测试任务。
    task 字段是用户自然语言描述，措辞模拟真实用户，不直接使用系统关键词。
    """
    query_id: str                       # 唯一 ID（如 A-001）
    category: str                       # A/B/C/D/adversarial
    category_desc: str                  # 类别描述
    task: str                           # 用户自然语言任务描述（核心字段）
    source: str                         # 来源：ep_title / task_history / constructed
    ground_truth: GroundTruth           # GT 标注

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Query":
        return cls(
            query_id=d["query_id"],
            category=d["category"],
            category_desc=d.get("category_desc", ""),
            task=d["task"],
            source=d.get("source", "constructed"),
            ground_truth=GroundTruth.from_dict(d["ground_truth"]),
        )


# ─────────────────────────────────────────────────────────────────────────────
# 检索结果结构
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RetrievedDoc:
    """单个检索到的文档片段"""
    doc_id: str                         # 文档唯一标识（文件路径或记忆 ID）
    content: str                        # 文档内容（原文或摘要）
    score: float = 0.0                  # 检索得分（BM25 / 余弦 / RRF 合并后）
    source_file: str = ""               # 来源文件路径
    # RAG 特有字段
    es_score: Optional[float] = None    # Elasticsearch BM25 分数
    milvus_distance: Optional[float] = None  # Milvus 向量距离（越小越近）
    rrf_rank_es: Optional[int] = None   # ES 排名（RRF 计算用）
    rrf_rank_mv: Optional[int] = None   # Milvus 排名（RRF 计算用）


@dataclass
class RetrievalResult:
    """
    单次检索的完整结果，包含文档列表和性能统计。
    所有检索器（Markdown/HybridRAG/Ontology）均返回此结构，
    保证评估器的接口统一性。
    """
    system: str                         # 检索系统名称（markdown/hybrid_rag/ontology）
    query_id: str
    docs: List[RetrievedDoc] = field(default_factory=list)  # 按相关度排序的文档列表

    # 性能统计
    latency_ms: float = 0.0            # 端到端检索耗时（ms）
    embed_latency_ms: Optional[float] = None   # Embedding API 耗时（ms）
    es_latency_ms: Optional[float] = None      # ES 查询耗时（ms）
    milvus_latency_ms: Optional[float] = None  # Milvus 查询耗时（ms）

    # 本体系统特有字段
    layer: Optional[str] = None        # 预测架构层
    operation: Optional[str] = None    # 预测操作类型
    confidence: Optional[float] = None # 分类置信度
    matched_rule: Optional[str] = None # 命中的规则 ID
    matched_keywords: List[str] = field(default_factory=list)
    from_llm: bool = False             # 是否触发了 LLM 兜底
    executable_cmds: List[str] = field(default_factory=list)  # 可执行命令列表

    # 上下文统计
    context_chars: int = 0             # 返回内容总字符数
    context_tokens_est: int = 0        # 估算 token 数（chars // 4）

    error: Optional[str] = None        # 若检索失败，记录错误信息

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["docs"] = [asdict(doc) for doc in self.docs]
        return d


# ─────────────────────────────────────────────────────────────────────────────
# 评估结果结构
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ActionabilityLevel:
    """
    可执行性等级（0-3 分量表，对三个系统中立）

    Level 0：返回了无关内容（与任务 GT 层无关）
    Level 1：返回了相关领域的文档片段（GT 层相关）
    Level 2：返回了相关且磁盘有效的文件路径
    Level 3：返回了可直接执行的命令（cli_usage / 代码示例）

    设计说明：RAG 系统若记忆文件中包含命令示例也能得 Level 3，
              不因"没有 ActionDef"而被惩罚为 0。
    """
    level: int = 0                      # 0-3
    reason: str = ""                    # 判断依据


@dataclass
class MetricResult:
    """单条任务×单个系统的所有指标计算结果"""
    query_id: str
    category: str
    system: str
    ts: float = field(default_factory=time.time)

    # ── 准确性指标 ───────────────────────────────────────────────────────────
    layer_correct: bool = False         # 预测层 == GT 层
    op_correct: bool = False            # 预测操作 == GT 操作
    recall_at_k: float = 0.0           # GT key_files 中被 Top-K 覆盖的比例
    mrr: float = 0.0                   # 第一个 GT 文件的倒数排名
    path_validity: float = 0.0         # 推荐路径中磁盘有效的比例
    memory_recall: float = 0.0         # GT key_memory_ids 中被命中的比例

    # ── 效率指标 ─────────────────────────────────────────────────────────────
    latency_ms: float = 0.0
    context_tokens: int = 0            # 注入 LLM 的估算 token 数
    info_density: float = 0.0          # = recall_at_k / max(context_tokens/1000, 0.1)
    actionability: ActionabilityLevel = field(
        default_factory=ActionabilityLevel
    )

    # ── 原始数据（用于后续分析）───────────────────────────────────────────────
    returned_file_paths: List[str] = field(default_factory=list)
    returned_memory_ids: List[str] = field(default_factory=list)
    executable_cmds: List[str] = field(default_factory=list)
    confidence: Optional[float] = None
    matched_rule: Optional[str] = None
    from_llm: bool = False
    embed_latency_ms: Optional[float] = None
    es_latency_ms: Optional[float] = None
    milvus_latency_ms: Optional[float] = None
    es_scores: Optional[List[float]] = None
    milvus_distances: Optional[List[float]] = None
    rrf_scores: Optional[List[float]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["actionability"] = asdict(self.actionability)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MetricResult":
        act = d.pop("actionability", {})
        obj = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        obj.actionability = ActionabilityLevel(**act)
        return obj


# ─────────────────────────────────────────────────────────────────────────────
# 聚合统计结构
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SystemStats:
    """单个检索系统在整个 benchmark 上的聚合统计"""
    system: str
    n_queries: int = 0

    # 均值
    layer_accuracy: float = 0.0
    op_accuracy: float = 0.0
    recall_at_k: float = 0.0
    mrr: float = 0.0
    path_validity: float = 0.0
    memory_recall: float = 0.0
    avg_latency_ms: float = 0.0
    avg_context_tokens: float = 0.0
    avg_info_density: float = 0.0
    avg_actionability: float = 0.0     # actionability.level 均值

    # 分位数（延迟）
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    max_latency_ms: float = 0.0

    # 分类分解（category → metric_value）
    by_category: Dict[str, Dict[str, float]] = field(default_factory=dict)

    # 统计显著性（与其他系统对比，key = 对比系统名）
    significance: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkStats:
    """整次 benchmark 运行的完整统计"""
    run_id: str                         # 格式：YYYYMMDD_HHMMSS
    n_queries: int = 0
    systems: List[str] = field(default_factory=list)
    per_system: Dict[str, SystemStats] = field(default_factory=dict)

    # 元数据
    config_snapshot: Dict[str, Any] = field(default_factory=dict)
    corpus_stats: Dict[str, Any] = field(default_factory=dict)
    elapsed_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["per_system"] = {k: v.to_dict() for k, v in self.per_system.items()}
        return d
