"""
accuracy.py — 准确性指标计算
==============================
实现 5 个准确性指标：
  - layer_accuracy    架构层命中率
  - op_accuracy       操作类型准确率
  - recall_at_k       GT 关键文件召回率（Recall@K）
  - mrr               平均倒数排名
  - path_validity     路径有效率（反幻觉）
  - memory_recall     约束记忆命中率

扩展说明：
    新增指标时，在此文件中添加计算函数，
    并在 registry.py 的 METRIC_FUNCS 中注册。
    函数签名统一为 fn(result, gt, cfg) → float。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List

try:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
    from _paths import _PROJECT_ROOT  # type: ignore[import]
except ImportError:
    _PROJECT_ROOT = Path(__file__).parent.parent.parent.parent  # benchmark/src/metrics → mms root


def layer_accuracy(retrieval_result, gt, cfg: dict) -> float:
    """
    架构层命中率（单条任务）。
    公式：1 if ŷ_layer == y*_layer else 0
    """
    predicted = getattr(retrieval_result, "layer", None)
    if predicted is None:
        # 非本体系统：从 docs 的 layer 字段推断
        predicted = _infer_layer_from_docs(retrieval_result.docs)
    return 1.0 if predicted == gt.layer else 0.0


def op_accuracy(retrieval_result, gt, cfg: dict) -> float:
    """
    操作类型准确率（单条任务）。
    公式：1 if ŷ_op == y*_op else 0
    """
    predicted = getattr(retrieval_result, "operation", None)
    if predicted is None:
        predicted = _infer_op_from_docs(retrieval_result.docs)
    return 1.0 if predicted == gt.operation else 0.0


def recall_at_k(retrieval_result, gt, cfg: dict) -> float:
    """
    GT 关键文件召回率（Recall@K）。

    公式：|TopK_i ∩ F*_i| / |F*_i|
    路径匹配：前缀匹配（GT 为目录时，只要 doc 路径以 GT 路径开头即命中）
    """
    k = cfg.get("params", {}).get("k", 5)
    returned = [doc.source_file for doc in retrieval_result.docs[:k]]
    gt_files = gt.key_files
    if not gt_files:
        return 1.0  # 无 GT 文件要求，视为命中

    hits = 0
    for gt_file in gt_files:
        for ret_file in returned:
            if _path_match(ret_file, gt_file):
                hits += 1
                break
    return hits / len(gt_files)


def mrr(retrieval_result, gt, cfg: dict) -> float:
    """
    平均倒数排名（单条任务）。

    公式：1/rank（第一个 GT 文件在 Top-K 中的排名，未命中为 0）
    """
    k = cfg.get("params", {}).get("k", 5)
    returned = [doc.source_file for doc in retrieval_result.docs[:k]]
    gt_files = gt.key_files
    if not gt_files:
        return 1.0

    # 只检查第一个 GT 文件
    first_gt = gt_files[0]
    for rank, ret_file in enumerate(returned, start=1):
        if _path_match(ret_file, first_gt):
            return 1.0 / rank
    return 0.0


def path_validity(retrieval_result, gt, cfg: dict) -> float:
    """
    路径有效率（反幻觉指标）。

    公式：|{f ∈ R_i : exists(f)}| / |R_i|
    使用 Path.exists() 和 Path.is_dir() 双重判断。
    """
    docs = retrieval_result.docs
    if not docs:
        return 1.0

    valid = 0
    for doc in docs:
        path = _PROJECT_ROOT / doc.source_file
        if path.exists() or path.is_dir():
            valid += 1
        elif doc.source_file.startswith("MEM-") or doc.source_file.startswith("AD-"):
            # 记忆 ID（非文件路径）不计入有效性检查
            valid += 1
    return valid / len(docs)


def memory_recall(retrieval_result, gt, cfg: dict) -> float:
    """
    约束记忆命中率。

    公式：|{m ∈ R_i : m.id ∈ M*_i}| / max(|M*_i|, 1)
    检索结果的 doc.doc_id 或 source_file 中包含记忆 ID 即命中。
    """
    gt_mems = gt.key_memory_ids
    if not gt_mems:
        return 1.0  # 无约束记忆要求，视为命中

    returned_ids = set()
    for doc in retrieval_result.docs:
        mem_id = _extract_memory_id(doc.source_file) or _extract_memory_id(doc.doc_id)
        if mem_id:
            returned_ids.add(mem_id)

    hits = sum(1 for m in gt_mems if m in returned_ids)
    return hits / len(gt_mems)


# ── 辅助函数 ─────────────────────────────────────────────────────────────────

def _path_match(returned: str, gt: str) -> bool:
    """前缀匹配：GT 路径是 returned 的前缀，或完全相等"""
    if returned == gt:
        return True
    # GT 是目录（以 / 结尾或不含扩展名）
    gt_norm = gt.rstrip("/")
    ret_norm = returned.rstrip("/")
    if ret_norm.startswith(gt_norm + "/") or ret_norm == gt_norm:
        return True
    # 文件名匹配（basename 相同）
    if Path(returned).name == Path(gt).name:
        return True
    return False


def _extract_memory_id(path: str) -> str:
    """从路径或 ID 字符串中提取记忆 ID"""
    m = re.search(r'(MEM-[A-Z]+-\d+|AD-\d+|BIZ-\d+|ENV-\d+)', path)
    return m.group(1) if m else ""


def _infer_layer_from_docs(docs) -> str:
    """
    非本体系统的 layer 推断：从 docs 的 source_file 路径推断最可能的架构层。
    这是一个启发式估计，用于给 Markdown/RAG 系统计算 layer_accuracy。
    """
    layer_hints = {
        "scripts/mms/": "L0_mms",
        "backend/app/core/rbac": "L1_security",
        "backend/app/core/security": "L1_security",
        "backend/alembic/": "L2_database",
        "backend/app/core/db": "L2_database",
        "backend/app/models/": "L2_database",
        "backend/app/workers/": "L4_worker",
        "backend/app/services/": "L4_service",
        "backend/app/api/": "L5_api",
        "backend/tests/": "L5_testing",
        "frontend/src/": "L5_frontend",
        "deploy/": "Ops",
    }
    counts = {}
    for doc in docs[:3]:  # 只看前3个文档
        src = doc.source_file
        for prefix, layer in layer_hints.items():
            if prefix in src:
                counts[layer] = counts.get(layer, 0) + 1
                break
    if not counts:
        return "L4_service"  # 兜底
    return max(counts, key=counts.get)


def _infer_op_from_docs(docs) -> str:
    """
    非本体系统的 operation 推断：从内容关键词推断操作类型。
    """
    content_all = " ".join(doc.content[:200] for doc in docs[:3]).lower()
    if any(w in content_all for w in ["新增", "创建", "create", "add", "implement"]):
        return "create"
    if any(w in content_all for w in ["修复", "报错", "debug", "fix", "error", "bug"]):
        return "debug"
    if any(w in content_all for w in ["部署", "docker", "k8s", "deploy"]):
        return "deploy"
    if any(w in content_all for w in ["测试", "test", "pytest"]):
        return "test"
    return "modify_logic"
