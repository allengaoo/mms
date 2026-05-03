#!/usr/bin/env python3
"""
run_benchmark.py — Benchmark 主入口
=====================================
用法：
    # 运行全部系统（需先运行 run_indexer.py 建立 ES/Milvus 索引）
    python run_benchmark.py

    # 只运行指定系统（跳过 ES/Milvus，快速验证）
    python run_benchmark.py --systems markdown ontology

    # 包含对抗样本
    python run_benchmark.py --include-adversarial

    # 从已有的 stats JSON 重新生成报告（不重新运行评估）
    python run_benchmark.py --report-only results/stats_20260418_120000.json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BENCH_DIR = Path(__file__).parent
sys.path.insert(0, str(_BENCH_DIR / "src"))

from evaluator import run
from reporter import latest_stats, save_report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MMS Benchmark — 三种检索系统对比评估",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python run_benchmark.py                           # 运行全部系统
  python run_benchmark.py --systems markdown ontology   # 只运行两个系统
  python run_benchmark.py --include-adversarial     # 含对抗样本
  python run_benchmark.py --report-only             # 重新生成最新报告
        """,
    )
    parser.add_argument(
        "--systems", nargs="+",
        choices=["markdown", "hybrid_rag", "ontology"],
        help="指定要运行的系统（默认全部）",
    )
    parser.add_argument(
        "--include-adversarial", action="store_true",
        help="包含对抗样本（默认不计入主评估）",
    )
    parser.add_argument(
        "--report-only", nargs="?", const="latest", metavar="STATS_JSON",
        help="只生成报告，不重新运行评估",
    )
    parser.add_argument(
        "--run-id", default=None,
        help="指定运行 ID（默认按时间自动生成）",
    )
    parser.add_argument(
        "--dataset", default=None, metavar="QUERIES_YAML",
        help="指定测试数据集 YAML 文件路径（默认: data/queries.yaml）",
    )
    parser.add_argument(
        "--dataset-version", default=None,
        help="数据集版本标签，追加到 run_id（如 v2）",
    )
    args = parser.parse_args()

    # ── 只生成报告模式 ───────────────────────────────────────────────────────
    if args.report_only is not None:
        if args.report_only == "latest":
            stats_path = latest_stats()
            if stats_path is None:
                print("❌ results/ 目录中没有找到 stats_*.json，请先运行评估")
                sys.exit(1)
        else:
            stats_path = Path(args.report_only)
            if not stats_path.exists():
                print(f"❌ 文件不存在: {stats_path}")
                sys.exit(1)

        print(f"[Reporter] 从 {stats_path.name} 生成报告...")
        report_path = save_report(stats_path)
        print(f"✅ 报告已生成: {report_path}")
        return

    # ── 完整评估模式 ─────────────────────────────────────────────────────────
    print("\n提示：若需要 Hybrid RAG，请确保已运行 python run_indexer.py")
    print("      若只测试 markdown/ontology，可用 --systems 跳过 RAG\n")

    run_id = args.run_id
    if args.dataset_version and run_id is None:
        from datetime import datetime
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{args.dataset_version}"

    stats = run(
        systems=args.systems,
        include_adversarial=args.include_adversarial,
        run_id=run_id,
        queries_path=args.dataset,
    )

    # 生成报告
    results_dir = _BENCH_DIR / "results"
    stats_path = results_dir / f"stats_{stats.run_id}.json"
    raw_path = results_dir / f"raw_{stats.run_id}.jsonl"

    report_path = save_report(stats_path, raw_path)
    print(f"✅ 报告已生成: {report_path.name}")

    # 打印快速摘要
    print(f"\n{'='*60}")
    print("快速摘要（主评估）")
    print(f"{'='*60}")
    for sys_name in stats.systems:
        s = stats.per_system.get(sys_name)
        if s:
            print(
                f"  {sys_name:<14} "
                f"LayerAcc={s.layer_accuracy:.3f} "
                f"R@5={s.recall_at_k:.3f} "
                f"InfoDensity={s.avg_info_density:.4f} "
                f"CtxTok={s.avg_context_tokens:.0f} "
                f"Act={s.avg_actionability:.2f}"
            )
    print(f"\n完整报告: scripts/mms/benchmark/results/report_{stats.run_id}.md")
    print(f"原始数据: scripts/mms/benchmark/results/raw_{stats.run_id}.jsonl")


if __name__ == "__main__":
    main()
