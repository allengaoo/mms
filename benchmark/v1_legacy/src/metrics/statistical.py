"""
statistical.py — 统计显著性检验
==================================
对系统间差异进行统计假设检验：
  - 二元指标（layer_accuracy / op_accuracy 等）：McNemar 检验
  - 连续指标（recall_at_k / mrr / info_density 等）：Wilcoxon 符号秩检验

结果格式：
    {
      "test": "wilcoxon",
      "statistic": 12.5,
      "p_value": 0.031,
      "significant": true,   # p < alpha
      "n_pairs": 25,
      "effect_size": 0.42,   # Cohen's d（连续）或 odds ratio（二元）
    }
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple


def mcnemar_test(
    a_correct: List[bool],
    b_correct: List[bool],
    alpha: float = 0.05,
) -> Dict:
    """
    McNemar 检验（配对二元指标）。

    适用场景：layer_accuracy / op_accuracy / path_validity（二元化后）

    统计量：χ² = (|b01 - b10| - 1)² / (b01 + b10)
    其中：
      b01 = A 错误、B 正确的对数
      b10 = A 正确、B 错误的对数
    自由度 = 1，使用卡方分布近似 p 值。

    注意：N=25 样本量较小，b01+b10 < 10 时结论不可靠，会在结果中标注。
    """
    if len(a_correct) != len(b_correct):
        raise ValueError("两组数据长度必须相同")

    b01 = sum(1 for a, b in zip(a_correct, b_correct) if not a and b)
    b10 = sum(1 for a, b in zip(a_correct, b_correct) if a and not b)
    n_discordant = b01 + b10

    if n_discordant == 0:
        return {
            "test": "mcnemar",
            "statistic": 0.0,
            "p_value": 1.0,
            "significant": False,
            "n_pairs": len(a_correct),
            "b01": b01,
            "b10": b10,
            "warning": "两组结果完全一致，无法区分",
        }

    # 带连续性校正的 McNemar
    chi2 = (abs(b01 - b10) - 1) ** 2 / n_discordant
    p_value = _chi2_p_value(chi2, df=1)

    return {
        "test": "mcnemar",
        "statistic": round(chi2, 4),
        "p_value": round(p_value, 4),
        "significant": p_value < alpha,
        "n_pairs": len(a_correct),
        "b01": b01,
        "b10": b10,
        "warning": "样本量不足（b01+b10<10），结论仅供参考" if n_discordant < 10 else None,
    }


def wilcoxon_test(
    a_scores: List[float],
    b_scores: List[float],
    alpha: float = 0.05,
    alternative: str = "two-sided",
) -> Dict:
    """
    Wilcoxon 符号秩检验（配对连续指标）。

    适用场景：recall_at_k / mrr / info_density / latency / context_tokens

    算法（不依赖 scipy）：
      1. 计算差值 d_i = a_i - b_i
      2. 排除 d_i == 0 的对
      3. 按 |d_i| 排名，正差值排名之和为 W+
      4. 用正态近似计算 z 统计量和 p 值
    """
    if len(a_scores) != len(b_scores):
        raise ValueError("两组数据长度必须相同")

    diffs = [(a - b, i) for i, (a, b) in enumerate(zip(a_scores, b_scores))]
    diffs_nonzero = [(d, i) for d, i in diffs if d != 0]
    n = len(diffs_nonzero)

    if n == 0:
        return {
            "test": "wilcoxon",
            "statistic": 0.0,
            "p_value": 1.0,
            "significant": False,
            "n_pairs": len(a_scores),
            "n_effective": 0,
            "warning": "所有差值为零，两组数据完全相同",
        }

    # 按绝对值排名
    sorted_by_abs = sorted(diffs_nonzero, key=lambda x: abs(x[0]))
    ranks = list(range(1, n + 1))

    # 处理并列排名（平均排名）
    final_ranks = _average_tied_ranks(sorted_by_abs, ranks)

    w_plus = sum(r for (d, _), r in zip(sorted_by_abs, final_ranks) if d > 0)
    w_minus = n * (n + 1) / 2 - w_plus

    if alternative == "two-sided":
        w_stat = min(w_plus, w_minus)
    elif alternative == "greater":
        w_stat = w_plus
    else:
        w_stat = w_minus

    # 正态近似
    mean_w = n * (n + 1) / 4
    var_w = n * (n + 1) * (2 * n + 1) / 24
    z = (w_stat - mean_w) / math.sqrt(max(var_w, 1e-9))

    if alternative == "two-sided":
        p_value = 2 * _normal_sf(abs(z))
    elif alternative == "greater":
        p_value = _normal_sf(z)
    else:
        p_value = _normal_sf(-z)

    # 效应量：r = z / sqrt(N)
    effect_r = abs(z) / math.sqrt(max(n, 1))

    return {
        "test": "wilcoxon",
        "statistic": round(w_stat, 4),
        "z_score": round(z, 4),
        "p_value": round(p_value, 4),
        "significant": p_value < alpha,
        "n_pairs": len(a_scores),
        "n_effective": n,
        "effect_r": round(effect_r, 4),
        "w_plus": round(w_plus, 2),
        "w_minus": round(w_minus, 2),
        "warning": "样本量较小（N<20），p 值仅供参考" if n < 20 else None,
    }


def run_all_tests(
    system_a: str,
    system_b: str,
    metric_results_a: List[dict],
    metric_results_b: List[dict],
    alpha: float = 0.05,
) -> Dict[str, Dict]:
    """
    对两个系统的所有可测指标运行统计检验。

    Returns:
        {metric_name: test_result_dict}
    """
    assert len(metric_results_a) == len(metric_results_b)

    binary_metrics = ["layer_correct", "op_correct"]
    continuous_metrics = [
        "recall_at_k", "mrr", "path_validity",
        "memory_recall", "info_density",
        "latency_ms", "context_tokens",
    ]

    results = {}

    for m in binary_metrics:
        a_vals = [r.get(m, False) for r in metric_results_a]
        b_vals = [r.get(m, False) for r in metric_results_b]
        results[m] = mcnemar_test(a_vals, b_vals, alpha=alpha)

    for m in continuous_metrics:
        a_vals = [float(r.get(m, 0)) for r in metric_results_a]
        b_vals = [float(r.get(m, 0)) for r in metric_results_b]
        results[m] = wilcoxon_test(a_vals, b_vals, alpha=alpha)

    return results


# ── 数学工具函数（无 scipy 依赖）────────────────────────────────────────────

def _chi2_p_value(chi2: float, df: int = 1) -> float:
    """卡方分布 p 值（自由度=1 的近似）"""
    # 使用正态近似：对 df=1，chi2 ~ z^2，p ≈ 2 * Φ(-|z|)
    z = math.sqrt(max(chi2, 0))
    return 2 * _normal_sf(z)


def _normal_sf(z: float) -> float:
    """标准正态分布的生存函数（1 - CDF(z)），使用 erfc 近似"""
    return 0.5 * math.erfc(z / math.sqrt(2))


def _average_tied_ranks(items: list, ranks: list) -> list:
    """处理并列排名：相同绝对值取平均排名"""
    result = list(ranks)
    i = 0
    while i < len(items):
        j = i
        abs_val = abs(items[i][0])
        while j < len(items) and abs(items[j][0]) == abs_val:
            j += 1
        if j - i > 1:
            avg_rank = sum(ranks[i:j]) / (j - i)
            for k in range(i, j):
                result[k] = avg_rank
        i = j
    return result
