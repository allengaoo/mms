"""
evaluator.py — 评估器核心
===========================
负责：
  1. 加载 queries.yaml 和 config/
  2. 对每条任务 × 每个系统调用检索器
  3. 计算所有 enabled 指标
  4. 将原始结果逐行写入 raw_YYYYMMDD.jsonl（边跑边写，崩溃不丢数据）
  5. 聚合统计，运行统计显著性检验
  6. 返回 BenchmarkStats 供 reporter.py 生成报告
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

_BENCH_DIR = Path(__file__).parent.parent
_MMS_DIR = _BENCH_DIR.parent
sys.path.insert(0, str(_BENCH_DIR / "src"))
sys.path.insert(0, str(_MMS_DIR))

from schema import (
    ActionabilityLevel, BenchmarkStats, GroundTruth, MetricResult,
    Query, RetrievalResult, SystemStats,
)
from metrics.registry import METRIC_FUNCS
from metrics.statistical import run_all_tests
from retrievers.registry import get_retriever


def load_queries(queries_path=None) -> Tuple[List[Query], dict]:
    """加载 queries.yaml，返回 (Query 列表, metadata 字典)"""
    if queries_path is None:
        path = _BENCH_DIR / "data" / "queries.yaml"
    else:
        path = Path(queries_path)
    raw = yaml.safe_load(path.read_text())
    meta = raw.get("metadata", {})
    queries = [Query.from_dict(q) for q in raw["queries"]]
    return queries, meta


def load_config() -> Tuple[dict, dict]:
    """加载 metrics.yaml 和 systems.yaml"""
    metrics_cfg = yaml.safe_load(
        (_BENCH_DIR / "config" / "metrics.yaml").read_text()
    )
    systems_cfg = yaml.safe_load(
        (_BENCH_DIR / "config" / "systems.yaml").read_text()
    )
    return metrics_cfg, systems_cfg


def _compute_metrics(
    retrieval: RetrievalResult,
    query: Query,
    metrics_cfg: dict,
) -> MetricResult:
    """对单条检索结果计算所有 enabled 指标"""
    gt = query.ground_truth
    mr = MetricResult(
        query_id=query.query_id,
        category=query.category,
        system=retrieval.system,
    )

    enabled_metrics = {
        k: v for k, v in metrics_cfg["metrics"].items()
        if v.get("enabled", True) and k in METRIC_FUNCS
    }

    for metric_name, metric_cfg in enabled_metrics.items():
        fn = METRIC_FUNCS[metric_name]
        try:
            value = fn(retrieval, gt, metric_cfg)
        except Exception as e:
            value = 0.0

        # 写入对应字段
        if metric_name == "layer_accuracy":
            mr.layer_correct = bool(value)
        elif metric_name == "op_accuracy":
            mr.op_correct = bool(value)
        elif metric_name == "recall_at_k":
            mr.recall_at_k = float(value)
        elif metric_name == "mrr":
            mr.mrr = float(value)
        elif metric_name == "path_validity":
            mr.path_validity = float(value)
        elif metric_name == "memory_recall":
            mr.memory_recall = float(value)
        elif metric_name == "context_tokens":
            mr.context_tokens = int(value)
        elif metric_name == "info_density":
            mr.info_density = float(value)
        elif metric_name == "actionability":
            mr.actionability = value if isinstance(value, ActionabilityLevel) else ActionabilityLevel()

    # 从 RetrievalResult 直接拷贝的字段
    mr.latency_ms = retrieval.latency_ms
    mr.returned_file_paths = [d.source_file for d in retrieval.docs]
    mr.returned_memory_ids = [
        d.doc_id for d in retrieval.docs
        if d.doc_id.startswith("MEM-") or d.doc_id.startswith("AD-")
    ]
    mr.executable_cmds = getattr(retrieval, "executable_cmds", [])
    mr.confidence = getattr(retrieval, "confidence", None)
    mr.matched_rule = getattr(retrieval, "matched_rule", None)
    mr.from_llm = getattr(retrieval, "from_llm", False)
    mr.embed_latency_ms = retrieval.embed_latency_ms
    mr.es_latency_ms = retrieval.es_latency_ms
    mr.milvus_latency_ms = retrieval.milvus_latency_ms
    mr.error = retrieval.error

    return mr


def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    idx = (len(sorted_v) - 1) * p / 100
    lo = int(idx)
    hi = min(lo + 1, len(sorted_v) - 1)
    return sorted_v[lo] + (sorted_v[hi] - sorted_v[lo]) * (idx - lo)


def _aggregate(
    results: List[MetricResult],
    system: str,
) -> SystemStats:
    """聚合单个系统的所有指标结果"""
    n = len(results)
    if n == 0:
        return SystemStats(system=system)

    def avg(vals): return sum(vals) / max(len(vals), 1)

    latencies = [r.latency_ms for r in results]
    ctx_tokens = [r.context_tokens for r in results]
    act_levels = [r.actionability.level for r in results]

    stats = SystemStats(
        system=system,
        n_queries=n,
        layer_accuracy=round(avg([float(r.layer_correct) for r in results]), 4),
        op_accuracy=round(avg([float(r.op_correct) for r in results]), 4),
        recall_at_k=round(avg([r.recall_at_k for r in results]), 4),
        mrr=round(avg([r.mrr for r in results]), 4),
        path_validity=round(avg([r.path_validity for r in results]), 4),
        memory_recall=round(avg([r.memory_recall for r in results]), 4),
        avg_latency_ms=round(avg(latencies), 2),
        avg_context_tokens=round(avg(ctx_tokens), 1),
        avg_info_density=round(avg([r.info_density for r in results]), 4),
        avg_actionability=round(avg(act_levels), 3),
        p50_latency_ms=round(_percentile(latencies, 50), 2),
        p95_latency_ms=round(_percentile(latencies, 95), 2),
        max_latency_ms=round(max(latencies, default=0), 2),
    )

    # 按类别分解
    categories = sorted(set(r.category for r in results))
    for cat in categories:
        cat_results = [r for r in results if r.category == cat]
        stats.by_category[cat] = {
            "n": len(cat_results),
            "layer_accuracy": round(avg([float(r.layer_correct) for r in cat_results]), 4),
            "op_accuracy": round(avg([float(r.op_correct) for r in cat_results]), 4),
            "recall_at_k": round(avg([r.recall_at_k for r in cat_results]), 4),
            "mrr": round(avg([r.mrr for r in cat_results]), 4),
            "info_density": round(avg([r.info_density for r in cat_results]), 4),
            "avg_context_tokens": round(avg([r.context_tokens for r in cat_results]), 1),
            "avg_actionability": round(avg([r.actionability.level for r in cat_results]), 3),
        }

    return stats


def run(
    systems: Optional[List[str]] = None,
    include_adversarial: bool = False,
    queries_path: Optional[Path] = None,
    run_id: Optional[str] = None,
) -> BenchmarkStats:
    """
    运行完整 Benchmark。

    Args:
        systems:             要运行的系统列表，None 表示运行所有 enabled 系统
        include_adversarial: 是否包含对抗样本（默认不计入主评估）
        queries_path:        自定义 queries.yaml 路径
        run_id:              运行 ID（默认按时间自动生成）

    Returns:
        BenchmarkStats（同时写入 results/ 目录）
    """
    t_total_start = time.time()
    run_id = run_id or time.strftime("%Y%m%d_%H%M%S")

    queries, meta = load_queries(queries_path)
    metrics_cfg, systems_cfg = load_config()

    # 过滤对抗样本
    if not include_adversarial:
        queries = [q for q in queries if q.category != "adversarial"]

    # 确定要运行的系统
    all_systems = [
        name for name, cfg in systems_cfg["systems"].items()
        if cfg.get("enabled", True)
    ]
    active_systems = systems or all_systems

    # 准备原始结果输出文件（边跑边写）
    results_dir = _BENCH_DIR / "results"
    results_dir.mkdir(exist_ok=True)
    raw_path = results_dir / f"raw_{run_id}.jsonl"
    raw_file = raw_path.open("w", encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"MMS Benchmark Run: {run_id}")
    print(f"任务数: {len(queries)}  系统: {active_systems}")
    print(f"原始数据: {raw_path.name}")
    print(f"{'='*60}\n")

    # 初始化检索器
    retrievers = {}
    for sys_name in active_systems:
        try:
            retrievers[sys_name] = get_retriever(sys_name, systems_cfg)
            print(f"  ✅ 已初始化检索器: {sys_name}")
        except Exception as e:
            print(f"  ❌ 初始化失败 [{sys_name}]: {e}")

    # 主评估循环
    all_results: Dict[str, List[MetricResult]] = {s: [] for s in retrievers}
    top_k = meta.get("top_k", 5)
    total_tasks = len(queries) * len(retrievers)
    done = 0

    for query in queries:
        for sys_name, retriever in retrievers.items():
            try:
                retrieval = retriever.retrieve(query.task, query.query_id, top_k=top_k)
            except Exception as e:
                retrieval = RetrievalResult(
                    system=sys_name, query_id=query.query_id, docs=[], error=str(e)
                )

            mr = _compute_metrics(retrieval, query, metrics_cfg)
            all_results[sys_name].append(mr)

            # 实时写入 JSONL
            raw_record = mr.to_dict()
            raw_record["task"] = query.task          # 方便后续分析
            raw_record["source"] = query.source
            raw_record["gt_layer"] = query.ground_truth.layer
            raw_record["gt_operation"] = query.ground_truth.operation
            raw_record["gt_key_files"] = query.ground_truth.key_files
            raw_record["gt_key_memory_ids"] = query.ground_truth.key_memory_ids
            raw_file.write(json.dumps(raw_record, ensure_ascii=False) + "\n")
            raw_file.flush()

            done += 1
            act = mr.actionability.level
            print(
                f"  [{done:3d}/{total_tasks}] {sys_name:<12} {query.query_id:<8} "
                f"layer={'✅' if mr.layer_correct else '❌'} "
                f"R@5={mr.recall_at_k:.2f} "
                f"density={mr.info_density:.3f} "
                f"act={act} "
                f"lat={mr.latency_ms:.0f}ms "
                f"tok={mr.context_tokens}"
            )

    raw_file.close()

    # 聚合统计
    per_system: Dict[str, SystemStats] = {}
    for sys_name, results in all_results.items():
        per_system[sys_name] = _aggregate(results, sys_name)

    # 统计显著性检验（两两对比）
    sys_names = list(all_results.keys())
    for i in range(len(sys_names)):
        for j in range(i + 1, len(sys_names)):
            a_name, b_name = sys_names[i], sys_names[j]
            a_dicts = [r.to_dict() for r in all_results[a_name]]
            b_dicts = [r.to_dict() for r in all_results[b_name]]
            tests = run_all_tests(a_name, b_name, a_dicts, b_dicts,
                                  alpha=metrics_cfg["metrics"]["statistical_test"]["params"]["alpha"])
            per_system[a_name].significance[b_name] = tests
            per_system[b_name].significance[a_name] = {
                k: v for k, v in tests.items()
            }

    elapsed = time.time() - t_total_start
    bm_stats = BenchmarkStats(
        run_id=run_id,
        n_queries=len(queries),
        systems=active_systems,
        per_system=per_system,
        elapsed_seconds=round(elapsed, 2),
        corpus_stats={},
        config_snapshot={
            "metrics_version": metrics_cfg.get("defaults", {}),
            "top_k": top_k,
        },
    )

    # 保存聚合统计
    stats_path = results_dir / f"stats_{run_id}.json"
    stats_path.write_text(
        json.dumps(bm_stats.to_dict(), ensure_ascii=False, indent=2)
    )
    print(f"\n✅ 聚合统计已保存: {stats_path.name}")
    print(f"✅ 原始数据已保存: {raw_path.name}")

    return bm_stats
