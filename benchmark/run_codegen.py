#!/usr/bin/env python3
"""
run_codegen.py — 代码生成质量 Benchmark 入口 (EP-132)
=======================================================

功能：
  1. 为每条 queries_codegen.yaml 任务，向三个检索系统（pageindex/hybrid_rag/ontology）
     发起检索，获取上下文（retrieval_tokens）
  2. 用检索到的上下文拼装 prompt，调用 bailian_coder（qwen3-coder-next）生成代码
  3. 用 CodeGenEvaluator 的 4 级流水线评估生成代码质量
  4. 输出 Markdown 报告 + JSON 统计，证明"更好的上下文→更好的代码"

用法：
    # 运行全部三个系统（需先索引，默认跳过 L3/L4 评估加快速度）
    python run_codegen.py

    # 只运行本体系统，开启全部 4 级评估
    python run_codegen.py --systems ontology --full-eval

    # dry-run：不调用 LLM，仅测试检索和评估器（适合 CI）
    python run_codegen.py --dry-run

    # 查看所有参数
    python run_codegen.py --help

输出（默认 benchmark/results/）：
    codegen_YYYYMMDD_HHMMSS_report.md   人可读 Markdown 报告
    codegen_YYYYMMDD_HHMMSS_stats.json  机器可读 JSON 统计
    codegen_YYYYMMDD_HHMMSS_raw.jsonl   每条任务的原始生成代码和评估结果

指标公式（见 src/metrics/codegen_quality.py）：
    综合分：L1×0.1 + L2×0.3 + L3×0.3 + L4×0.3（NaN 等比重分配）
    成本效率：codegen_score / (retrieval_tokens / 1000 + 1e-6)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

_BENCH_DIR = Path(__file__).parent
sys.path.insert(0, str(_BENCH_DIR / "src"))
sys.path.insert(0, str(_BENCH_DIR.parent))  # scripts/mms/

from evaluators.codegen_evaluator import (
    CodeGenEvaluator,
    EvaluatorConfig,
    load_codegen_tasks,
)
from metrics.codegen_quality import (
    CodegenMetricResult,
    CodegenSystemSummary,
    aggregate_system_scores,
)
from reporters.codegen_reporter import generate_codegen_report

# ── 系统名称映射 ───────────────────────────────────────────────────────────────
_SYSTEM_NAMES = ["pageindex", "hybrid_rag", "ontology"]


# ─────────────────────────────────────────────────────────────────────────────
# 检索上下文（三个系统共用接口）
# ─────────────────────────────────────────────────────────────────────────────

def _retrieve_context(system_name: str, query: str, context_hint: str, top_k: int = 5) -> tuple:
    """
    向指定系统发起检索，返回 (context_text, retrieval_tokens, latency_ms)。

    Args:
        system_name:   "pageindex" | "hybrid_rag" | "ontology"
        query:         任务描述（自然语言）
        context_hint:  背景提示（辅助检索）
        top_k:         返回文档数

    Returns:
        (context_text: str, retrieval_tokens: int, latency_ms: float)
    """
    t0 = time.monotonic()

    try:
        if system_name == "pageindex":
            ctx, tokens = _retrieve_pageindex(query, context_hint, top_k)
        elif system_name == "hybrid_rag":
            ctx, tokens = _retrieve_hybrid_rag(query, context_hint, top_k)
        elif system_name == "ontology":
            ctx, tokens = _retrieve_ontology(query, context_hint, top_k)
        else:
            ctx, tokens = f"[未知系统: {system_name}]", 0
    except Exception as e:
        ctx = f"[检索失败: {e}]"
        tokens = 0

    latency_ms = round((time.monotonic() - t0) * 1000, 1)
    return ctx, tokens, latency_ms


def _retrieve_pageindex(query: str, context_hint: str, top_k: int) -> tuple:
    """Markdown 索引检索（使用现有 markdown_retriever）"""
    try:
        from retrievers.markdown_retriever import MarkdownRetriever
        from retrievers.registry import load_retriever_config

        cfg = load_retriever_config("pageindex")
        retriever = MarkdownRetriever("pageindex", cfg)
        result = retriever.retrieve(query, query_id="codegen", top_k=top_k)
        return result.context, result.context_tokens_est
    except Exception as e:
        return f"[pageindex 检索失败: {e}]", 0


def _retrieve_hybrid_rag(query: str, context_hint: str, top_k: int) -> tuple:
    """Hybrid RAG 检索（ES + Milvus RRF）"""
    try:
        from retrievers.hybrid_rag_retriever import HybridRAGRetriever
        from retrievers.registry import load_retriever_config

        cfg = load_retriever_config("hybrid_rag")
        retriever = HybridRAGRetriever("hybrid_rag", cfg)
        result = retriever.retrieve(query, query_id="codegen", top_k=top_k)
        return result.context, result.context_tokens_est
    except Exception as e:
        return f"[hybrid_rag 检索失败: {e}]", 0


def _retrieve_ontology(query: str, context_hint: str, top_k: int) -> tuple:
    """本体驱动 MMS 检索"""
    try:
        from retrievers.ontology_retriever import OntologyRetriever
        from retrievers.registry import load_retriever_config

        cfg = load_retriever_config("ontology")
        retriever = OntologyRetriever("ontology", cfg)
        result = retriever.retrieve(query, query_id="codegen", top_k=top_k)
        return result.context, result.context_tokens_est
    except Exception as e:
        return f"[ontology 检索失败: {e}]", 0


# ─────────────────────────────────────────────────────────────────────────────
# 代码生成（调用百炼 qwen3-coder-next）
# ─────────────────────────────────────────────────────────────────────────────

_CODE_GEN_SYSTEM_PROMPT = """你是一个 MDP 企业级后端开发专家，遵循以下约束：
1. 使用 FastAPI + SQLModel + Pydantic v2，Python 3.9 兼容
2. Service 层首参必须是 ctx: RequestContext
3. 所有 WRITE 操作必须调用 audit_service.log()
4. 事务使用 Strategy B（autobegin + explicit commit），禁止 session.begin()
5. 禁止使用 print()，必须用 structlog
6. 禁止裸返回列表/字典，使用 success_response() 或 ResponseSchema
7. 禁止直接 import pymilvus/aiokafka/elasticsearch
8. 只生成任务要求的代码，不添加无关注释"""


def _generate_code(
    task_description: str,
    context: str,
    system_name: str,
    dry_run: bool = False,
) -> tuple:
    """
    调用 bailian_coder 生成代码。

    Args:
        task_description: 任务描述
        context:          检索到的上下文
        system_name:      当前系统名称（用于日志）
        dry_run:          干跑模式（不调用 LLM，返回空字符串）

    Returns:
        (generated_source: str, tokens_generated: int, latency_ms: float)
    """
    if dry_run:
        return f"# dry-run placeholder for {system_name}", 50, 0.0

    t0 = time.monotonic()

    try:
        from providers.factory import auto_detect  # type: ignore[import]
        provider = auto_detect("code_generation")

        # 上下文截断（防止超出 8k token 窗口）
        max_context_chars = 12000  # 约 3000 tokens
        if len(context) > max_context_chars:
            context = context[:max_context_chars] + "\n\n...(上下文已截断)"

        prompt = f"""## 相关记忆上下文（来自 {system_name} 检索）
{context}

---

## 任务要求
{task_description}

---

请直接输出 Python 代码，不需要解释。代码必须符合 MDP 架构规范。"""

        source = provider.complete(
            f"{_CODE_GEN_SYSTEM_PROMPT}\n\n{prompt}",
            max_tokens=2048,
        ) or ""

        # 清除可能的 markdown 代码块标记
        import re
        source = re.sub(r"^```(?:python)?\s*\n?", "", source.strip(), flags=re.MULTILINE)
        source = re.sub(r"\n?\s*```\s*$", "", source, flags=re.MULTILINE)

        tokens = max(1, len(source) // 4)
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        return source, tokens, latency_ms

    except Exception as e:
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        return f"# 代码生成失败: {e}", 0, latency_ms


# ─────────────────────────────────────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────────────────────────────────────

def run_codegen_benchmark(
    systems: Optional[List[str]] = None,
    full_eval: bool = False,
    dry_run: bool = False,
    tasks_filter: Optional[List[str]] = None,
    run_id: Optional[str] = None,
    output_dir: Optional[Path] = None,
    top_k: int = 5,
) -> Path:
    """
    运行代码生成质量 Benchmark（EP-132）。

    Args:
        systems:       要评估的系统列表（默认全部三个）
        full_eval:     是否开启全部 4 级评估（默认跳过 L3/L4 加快速度）
        dry_run:       干跑模式（不调用 LLM）
        tasks_filter:  只评估指定 task_id（如 ["CG-001", "CG-007"]）
        run_id:        运行 ID
        output_dir:    输出目录
        top_k:         检索返回文档数

    Returns:
        报告 Markdown 文件路径
    """
    if systems is None:
        systems = list(_SYSTEM_NAMES)

    if run_id is None:
        run_id = datetime.now(timezone.utc).strftime("codegen_%Y%m%d_%H%M%S")

    # 配置评估器（默认跳过 L3/L4 以加快速度）
    skip_levels = set() if full_eval else {3, 4}
    eval_config = EvaluatorConfig(skip_levels=skip_levels)
    evaluator = CodeGenEvaluator(config=eval_config)

    # 加载任务数据集
    tasks = load_codegen_tasks()
    if not tasks:
        print("[ERROR] 无法加载测试任务，请确认 benchmark/data/queries_codegen.yaml 存在")
        sys.exit(1)

    if tasks_filter:
        tasks = [t for t in tasks if t.get("id") in tasks_filter]
        if not tasks:
            print(f"[ERROR] tasks_filter 未匹配到任何任务: {tasks_filter}")
            sys.exit(1)

    print(f"\n{'='*60}")
    print(f"MMS 代码生成质量 Benchmark  run_id={run_id}")
    print(f"任务数: {len(tasks)}  系统: {', '.join(systems)}")
    print(f"评估级别: L1+L2{'+L3+L4' if full_eval else ' (L3/L4 跳过，使用 --full-eval 开启)'}")
    print(f"{'='*60}\n")

    all_summaries: List[CodegenSystemSummary] = []
    output_dir = output_dir or (_BENCH_DIR / "results")
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_jsonl_path = output_dir / f"{run_id}_raw.jsonl"
    raw_f = open(raw_jsonl_path, "w", encoding="utf-8")

    try:
        for sys_name in systems:
            print(f"\n[系统: {sys_name}]")
            sys_results: List[CodegenMetricResult] = []

            for task in tasks:
                task_id = task.get("id", "?")
                description = task.get("description", "")
                context_hint = task.get("context_hint", "")

                print(f"  {task_id} ({task.get('difficulty', '?')})... ", end="", flush=True)

                # Step 1: 检索上下文
                ctx_text, ctx_tokens, ctx_latency = _retrieve_context(
                    sys_name, description, context_hint, top_k
                )

                # Step 2: 生成代码
                source, gen_tokens, gen_latency = _generate_code(
                    description, ctx_text, sys_name, dry_run=dry_run
                )

                # Step 3: 4 级评估
                result = evaluator.evaluate(
                    task_id=task_id,
                    task_spec=task,
                    generated_source=source,
                    system_name=sys_name,
                    retrieval_tokens=ctx_tokens,
                )
                result.generated_tokens = gen_tokens
                result.latency_ms = ctx_latency + gen_latency

                sys_results.append(result)

                score_str = f"{result.codegen_score * 100:.0f}%" if result.codegen_score == result.codegen_score else "N/A"
                print(f"score={score_str} L1={result.level1_syntax.pass_rate_pct} L2={result.level2_contract.pass_rate_pct}")

                # 写 raw JSONL
                raw_record = {
                    "run_id": run_id,
                    "system": sys_name,
                    "task_id": task_id,
                    "generated_source": source[:3000] if len(source) > 3000 else source,
                    "eval": result.to_dict(),
                    "retrieval_tokens": ctx_tokens,
                    "gen_tokens": gen_tokens,
                }
                raw_f.write(json.dumps(raw_record, ensure_ascii=False) + "\n")
                raw_f.flush()

            summary = CodegenSystemSummary(system_name=sys_name, task_results=sys_results)
            all_summaries.append(summary)
            print(f"  -> {sys_name} 平均综合分: {_pct(summary.avg_score)}")
    finally:
        raw_f.close()

    # 生成报告
    report_path = generate_codegen_report(all_summaries, run_id=run_id, output_dir=output_dir)

    print(f"\n{'='*60}")
    print(f"报告已生成：{report_path}")
    print(f"原始数据：{raw_jsonl_path}")
    print(f"{'='*60}")

    # 打印简要摘要
    _print_summary(all_summaries)

    return report_path


def _print_summary(summaries: List[CodegenSystemSummary]) -> None:
    """打印终端摘要表"""
    from metrics.codegen_quality import compare_systems
    comparison = compare_systems(summaries)
    winner = comparison.get("winner", "N/A")

    print(f"\n综合最优系统: {winner}")
    print(f"\n{'系统':<15} {'综合分':>8} {'L1 语法':>8} {'L2 契约':>8} {'成本效率':>10}")
    print("-" * 55)
    for ranking in comparison.get("rankings", []):
        print(
            f"{ranking['system']:<15} "
            f"{_pct(ranking.get('avg_score')):>8} "
            f"{_pct(ranking.get('syntax_pass_rate')):>8} "
            f"{_pct(ranking.get('contract_pass_rate')):>8} "
            f"{_fmt(ranking.get('avg_cost_efficiency')):>10}"
        )


def _pct(v) -> str:
    import math
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "N/A"
    return f"{v * 100:.1f}%"


def _fmt(v) -> str:
    import math
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "N/A"
    return f"{v:.2f}"


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="MMS 代码生成质量 Benchmark（EP-132）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python run_codegen.py                                  # 运行全部系统（L1+L2）
  python run_codegen.py --systems ontology --full-eval   # 本体系统 + 全量 4 级评估
  python run_codegen.py --dry-run                        # 干跑（不调用 LLM）
  python run_codegen.py --tasks CG-001 CG-007            # 只评估指定任务
  python run_codegen.py --systems pageindex hybrid_rag   # 只评估两个系统
        """,
    )
    parser.add_argument(
        "--systems", nargs="+",
        choices=_SYSTEM_NAMES,
        default=None,
        help="要评估的系统（默认全部：pageindex hybrid_rag ontology）",
    )
    parser.add_argument(
        "--full-eval", action="store_true",
        help="开启全部 4 级评估（含 L3 arch_check + L4 pytest，较慢）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="干跑模式：不调用 LLM，测试检索和评估器流程",
    )
    parser.add_argument(
        "--tasks", nargs="+", metavar="TASK_ID",
        help="只评估指定任务（如 CG-001 CG-007）",
    )
    parser.add_argument(
        "--top-k", type=int, default=5,
        help="检索返回文档数（默认 5）",
    )
    parser.add_argument(
        "--run-id", default=None,
        help="指定运行 ID（默认按时间自动生成）",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=None,
        help="报告输出目录（默认 benchmark/results/）",
    )

    args = parser.parse_args()

    run_codegen_benchmark(
        systems=args.systems,
        full_eval=args.full_eval,
        dry_run=args.dry_run,
        tasks_filter=args.tasks,
        run_id=args.run_id,
        output_dir=args.output_dir,
        top_k=args.top_k,
    )

    sys.exit(0)


if __name__ == "__main__":
    main()
