"""
aiu_quality.py — AIU 分解质量 + 成本效率指标计算（EP-131）

计算以下 4 个新指标：
  aiu_decomp_precision   — AIU 类型分解精度（仅 I 类查询，仅 ontology 系统）
  aiu_decomp_recall      — AIU 类型分解召回率（仅 I 类查询，仅 ontology 系统）
  aiu_order_similarity   — AIU 执行顺序相似度（aiu_order_matters=true 时）
  cost_efficiency        — 成本效率综合指标（三系统均计算）

设计原则：
  - 遵循 registry.py 的注册模式（通过 registry.get_metric 调用）
  - I 类查询特有指标对 RAG 系统返回 float('nan')（标记 N/A）
  - 所有计算函数为纯函数（无副作用，无全局状态）
  - 异常时返回 0.0（不影响其他指标计算）

EP-131 | 2026-04-18
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


# ── LCS（最长公共子序列）─────────────────────────────────────────────────────

def _lcs_length(seq_a: List[str], seq_b: List[str]) -> int:
    """
    计算两个序列的最长公共子序列长度（动态规划）。

    时间复杂度：O(m×n)
    空间复杂度：O(min(m,n)) 滚动数组优化

    Args:
        seq_a: 序列 A
        seq_b: 序列 B

    Returns:
        LCS 长度
    """
    if not seq_a or not seq_b:
        return 0

    m, n = len(seq_a), len(seq_b)
    # 滚动数组（空间优化）
    prev = [0] * (n + 1)
    for i in range(1, m + 1):
        curr = [0] * (n + 1)
        for j in range(1, n + 1):
            if seq_a[i - 1] == seq_b[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(prev[j], curr[j - 1])
        prev = curr
    return prev[n]


# ── AIU 分解精度 ─────────────────────────────────────────────────────────────

def calc_aiu_decomp_precision(
    predicted_aiu_types: List[str],
    ground_truth: Dict[str, Any],
    params: Optional[Dict[str, Any]] = None,
) -> float:
    """
    计算 AIU 分解精度（仅 I 类查询有意义）。

    公式：
      AIU_Prec = |预测AIU类型集 ∩ 期望AIU类型集| / |预测AIU类型集|
      若出现 forbidden_aiu_types → AIU_Prec × forbidden_penalty

    Args:
        predicted_aiu_types: task_decomposer 实际输出的 AIU 类型列表
        ground_truth:        包含 expected_aiu_types / forbidden_aiu_types 的 GT dict
        params:              配置参数（forbidden_penalty 等）

    Returns:
        精度值 [0.0, 1.0]，或 float('nan')（非 I 类查询）
    """
    params = params or {}
    forbidden_penalty = float(params.get("forbidden_penalty", 0.5))

    expected = ground_truth.get("expected_aiu_types", [])
    forbidden = ground_truth.get("forbidden_aiu_types", [])

    # 非 I 类查询（没有 expected_aiu_types 字段）
    if not expected:
        return float("nan")

    if not predicted_aiu_types:
        return 0.0

    predicted_set = set(predicted_aiu_types)
    expected_set = set(expected)
    forbidden_set = set(forbidden)

    intersection = predicted_set & expected_set
    precision = len(intersection) / len(predicted_set) if predicted_set else 0.0

    # 惩罚：出现 forbidden 类型
    if forbidden_set & predicted_set:
        precision *= forbidden_penalty

    return round(min(precision, 1.0), 4)


# ── AIU 分解召回率 ────────────────────────────────────────────────────────────

def calc_aiu_decomp_recall(
    predicted_aiu_types: List[str],
    ground_truth: Dict[str, Any],
    params: Optional[Dict[str, Any]] = None,
) -> float:
    """
    计算 AIU 分解召回率（仅 I 类查询有意义）。

    公式：
      AIU_Recall = |预测AIU类型集 ∩ 期望AIU类型集| / |期望AIU类型集|

    Args:
        predicted_aiu_types: task_decomposer 实际输出的 AIU 类型列表
        ground_truth:        包含 expected_aiu_types 的 GT dict
        params:              保留参数（当前未使用）

    Returns:
        召回率值 [0.0, 1.0]，或 float('nan')（非 I 类查询）
    """
    expected = ground_truth.get("expected_aiu_types", [])

    if not expected:
        return float("nan")

    if not predicted_aiu_types:
        return 0.0

    predicted_set = set(predicted_aiu_types)
    expected_set = set(expected)

    intersection = predicted_set & expected_set
    recall = len(intersection) / len(expected_set) if expected_set else 0.0

    return round(min(recall, 1.0), 4)


# ── AIU 顺序相似度 ────────────────────────────────────────────────────────────

def calc_aiu_order_similarity(
    predicted_aiu_sequence: List[str],
    ground_truth: Dict[str, Any],
    params: Optional[Dict[str, Any]] = None,
) -> float:
    """
    计算 AIU 执行顺序相似度（仅 aiu_order_matters=true 的 I 类查询）。

    公式：
      OrderSim = LCS_len(预测序列, 期望序列) / max(|预测|, |期望|)

    Args:
        predicted_aiu_sequence: task_decomposer 实际输出的 AIU 类型有序列表
        ground_truth:           包含 expected_aiu_types / aiu_order_matters 的 GT dict
        params:                 保留参数（当前未使用）

    Returns:
        顺序相似度 [0.0, 1.0]，或 float('nan')（顺序不重要或非 I 类查询）
    """
    expected = ground_truth.get("expected_aiu_types", [])
    order_matters = ground_truth.get("aiu_order_matters", False)

    # 非 I 类查询 或 顺序不重要
    if not expected or not order_matters:
        return float("nan")

    if not predicted_aiu_sequence:
        return 0.0

    lcs_len = _lcs_length(predicted_aiu_sequence, expected)
    denominator = max(len(predicted_aiu_sequence), len(expected))
    if denominator == 0:
        return 0.0

    return round(lcs_len / denominator, 4)


# ── 成本效率 ──────────────────────────────────────────────────────────────────

def calc_cost_efficiency(
    recall_at_k: float,
    context_tokens: int,
    latency_ms: float,
    from_llm: bool = False,
    params: Optional[Dict[str, Any]] = None,
) -> float:
    """
    计算成本效率综合指标（三个系统均可计算）。

    公式：
      TotalCost = α × (context_tokens / 1000) + β × llm_calls + γ × (latency_ms / 1000)
      CostEff = Recall@K / max(TotalCost, min_denominator)

    Args:
        recall_at_k:    Recall@K 值（来自 accuracy.py 的计算结果）
        context_tokens: 注入 LLM 的估算 token 数
        latency_ms:     端到端检索耗时（毫秒）
        from_llm:       是否触发了 LLM 调用（Ontology: RBO miss 时为 True；RAG: 始终为 True）
        params:         配置参数（alpha/beta/gamma/min_denominator）

    Returns:
        成本效率值（越高越好，无上限）
    """
    params = params or {}
    alpha = float(params.get("alpha", 1.0))
    beta = float(params.get("beta", 0.5))
    gamma = float(params.get("gamma", 0.1))
    min_denominator = float(params.get("min_denominator", 0.1))

    # llm_calls：from_llm=True 计 1，否则计 0
    llm_calls = 1 if from_llm else 0

    total_cost = (
        alpha * (max(context_tokens, 0) / 1000.0)
        + beta * llm_calls
        + gamma * (max(latency_ms, 0) / 1000.0)
    )

    denominator = max(total_cost, min_denominator)
    cost_eff = recall_at_k / denominator

    return round(cost_eff, 4)


# ── 辅助函数 ─────────────────────────────────────────────────────────────────

def is_i_category(query_id: str, category: str) -> bool:
    """判断是否为 I 类查询（AIU 分解质量测试）"""
    return category == "I" or (query_id and query_id.upper().startswith("I-"))


def is_j_category(query_id: str, category: str) -> bool:
    """判断是否为 J 类查询（冷启动基线测试）"""
    return category == "J" or (query_id and query_id.upper().startswith("J-"))


def safe_mean(values: List[float]) -> float:
    """
    计算均值，跳过 NaN 值（用于 I 类指标的系统级聚合）。
    全为 NaN 时返回 float('nan')。
    """
    valid = [v for v in values if not math.isnan(v)]
    if not valid:
        return float("nan")
    return round(sum(valid) / len(valid), 4)
