"""
Layer 2 · D1 准确检索（Accurate Retrieval）

评测 hybrid_search / find_by_concept 能否在给定查询下检索到必要的记忆节点。

指标：
  Recall@K    — 前 K 条结果中，包含了多少"必要记忆"
  Precision@K — 前 K 条结果中，有多少是真正相关的
  MRR         — 平均倒数排名（第一条相关结果的排名倒数均值）
  Hit@1       — 第一条就是相关记忆的比例

扩展方式：
  在 tasks/*.yaml 中添加新 query case，无需修改此文件。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Set

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent.parent.parent
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))


@dataclass
class RetrievalCase:
    case_id:          str
    query:            str
    relevant_ids:     Set[str]           # ground-truth 相关记忆的 ID 集合
    k:                int = 5
    metadata:         Dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievalResult:
    case_id:     str
    recall_at_k: float
    precision_at_k: float
    mrr:         float
    hit_at_1:    float
    retrieved:   List[str]   # 实际检索到的 ID 列表（按排名）
    error:       str = ""


def compute_retrieval_metrics(
    retrieved_ids: List[str],
    relevant_ids: Set[str],
    k: int = 5,
) -> Dict[str, float]:
    """计算单个查询的检索指标"""
    top_k = retrieved_ids[:k]

    # Recall@K：相关且被检索到 / 总相关数
    hits_in_top_k = [r for r in top_k if r in relevant_ids]
    recall_at_k = len(hits_in_top_k) / max(len(relevant_ids), 1)

    # Precision@K：相关且被检索到 / 检索数量
    precision_at_k = len(hits_in_top_k) / max(len(top_k), 1)

    # MRR：第一个相关结果的排名倒数
    mrr = 0.0
    for rank, rid in enumerate(retrieved_ids, start=1):
        if rid in relevant_ids:
            mrr = 1.0 / rank
            break

    # Hit@1：第一条是否相关
    hit_at_1 = 1.0 if (retrieved_ids and retrieved_ids[0] in relevant_ids) else 0.0

    return {
        "recall_at_k":    round(recall_at_k, 4),
        "precision_at_k": round(precision_at_k, 4),
        "mrr":            round(mrr, 4),
        "hit_at_1":       round(hit_at_1, 4),
    }


def evaluate_retrieval(
    case: RetrievalCase,
    memory_root: Path,
) -> RetrievalResult:
    """
    对单个检索 case 执行评测。

    尝试使用 MemoryGraph.hybrid_search；
    若无法加载记忆文件（空库），则返回空结果（不报错）。
    """
    try:
        from mms.memory.graph_resolver import MemoryGraph
        graph = MemoryGraph(memory_root=memory_root)
        nodes = graph.hybrid_search(case.query, top_k=case.k * 2)
        retrieved_ids = [n.id for n in nodes][: case.k]
    except Exception as exc:
        return RetrievalResult(
            case_id=case.case_id,
            recall_at_k=0.0,
            precision_at_k=0.0,
            mrr=0.0,
            hit_at_1=0.0,
            retrieved=[],
            error=str(exc),
        )

    metrics = compute_retrieval_metrics(retrieved_ids, case.relevant_ids, case.k)
    return RetrievalResult(
        case_id=case.case_id,
        retrieved=retrieved_ids,
        **metrics,
    )


def aggregate_retrieval_metrics(results: List[RetrievalResult]) -> Dict[str, float]:
    """聚合多个 case 的检索指标"""
    if not results:
        return {}
    valid = [r for r in results if not r.error]
    if not valid:
        return {"recall_at_k": 0.0, "precision_at_k": 0.0, "mrr": 0.0, "hit_at_1": 0.0}

    return {
        "recall_at_k":    round(sum(r.recall_at_k for r in valid) / len(valid), 4),
        "precision_at_k": round(sum(r.precision_at_k for r in valid) / len(valid), 4),
        "mrr":            round(sum(r.mrr for r in valid) / len(valid), 4),
        "hit_at_1":       round(sum(r.hit_at_1 for r in valid) / len(valid), 4),
    }
