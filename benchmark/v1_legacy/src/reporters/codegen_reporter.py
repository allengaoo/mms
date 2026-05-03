"""
代码生成质量报告生成器 (EP-132)

从 CodegenSystemSummary 生成可读的 Markdown 报告和 JSON 统计数据。
支持三系统对比（pageindex/hybrid_rag/ontology）。

设计原则：
  - 报告器本身无副作用（不调用 LLM，不修改评估结果）
  - 报告格式稳定，方便 CI 自动解析
  - 支持流式追加（大量任务时不占用内存）
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from metrics.codegen_quality import CodegenSystemSummary, compare_systems  # type: ignore[import]
except ImportError:
    from ..metrics.codegen_quality import CodegenSystemSummary, compare_systems  # type: ignore[no-redef]

_BENCH_ROOT = Path(__file__).resolve().parent.parent.parent
_RESULTS_DIR = _BENCH_ROOT / "results"


def generate_codegen_report(
    summaries: List[CodegenSystemSummary],
    run_id: Optional[str] = None,
    output_dir: Optional[Path] = None,
) -> Path:
    """
    生成代码生成质量对比报告（Markdown + JSON）。

    Args:
        summaries:  各系统的评估汇总列表
        run_id:     运行 ID（默认时间戳）
        output_dir: 输出目录（默认 benchmark/results/）

    Returns:
        报告 Markdown 文件路径
    """
    if run_id is None:
        run_id = datetime.now(timezone.utc).strftime("codegen_%Y%m%d_%H%M%S")

    output_dir = output_dir or _RESULTS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    comparison = compare_systems(summaries)

    # 写 JSON 统计
    stats_path = output_dir / f"{run_id}_stats.json"
    stats_data = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "comparison": comparison,
        "systems": {
            s.system_name: {
                "avg_score": _safe_float(s.avg_score),
                "avg_cost_efficiency": _safe_float(s.avg_cost_efficiency),
                "syntax_pass_rate": _safe_float(s.syntax_pass_rate),
                "contract_pass_rate": _safe_float(s.contract_pass_rate),
                "arch_check_pass_rate": _safe_float(s.arch_check_pass_rate),
                "test_pass_rate": _safe_float(s.test_pass_rate),
                "by_category": s.by_category(),
                "by_difficulty": s.by_difficulty(),
                "task_results": [r.to_dict() for r in s.task_results],
            }
            for s in summaries
        },
    }
    stats_path.write_text(json.dumps(stats_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 写 Markdown 报告
    report_path = output_dir / f"{run_id}_report.md"
    lines = _build_markdown(summaries, comparison, run_id)
    report_path.write_text("\n".join(lines), encoding="utf-8")

    return report_path


def _build_markdown(
    summaries: List[CodegenSystemSummary],
    comparison: Dict,
    run_id: str,
) -> List[str]:
    """生成 Markdown 报告内容"""
    lines: List[str] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    winner = comparison.get("winner", "N/A")

    lines += [
        f"# MMS 代码生成质量基准报告",
        f"",
        f"> 运行 ID：`{run_id}` · 生成时间：{now}",
        f"> 评估系统：{', '.join(s.system_name for s in summaries)}",
        f"> 测试数据集：`benchmark/data/queries_codegen.yaml`（MDP 后端代码，20 条任务）",
        f"",
        f"---",
        f"",
        f"## 结论摘要",
        f"",
        f"**综合最优系统：{winner}**",
        f"",
    ]

    # 与最优系统的差值
    deltas = comparison.get("delta_vs_best", {})
    for s in summaries:
        delta = deltas.get(s.system_name)
        if delta is not None and delta < 0:
            lines.append(f"- `{s.system_name}` 落后最优 {abs(delta):.3f} 分")

    lines += ["", "---", "", "## 总体对比（综合分）", ""]

    # 总体对比表
    lines.append("| 系统 | 综合分 | L1 语法 | L2 契约 | L3 架构 | L4 测试 | 成本效率 |")
    lines.append("|------|--------|---------|---------|---------|---------|---------|")
    for ranking in comparison.get("rankings", []):
        sys_name = ranking.get("system", "")
        lines.append(
            f"| `{sys_name}` "
            f"| {_pct(ranking.get('avg_score'))} "
            f"| {_pct(ranking.get('syntax_pass_rate'))} "
            f"| {_pct(ranking.get('contract_pass_rate'))} "
            f"| {_pct(ranking.get('arch_check_pass_rate'))} "
            f"| {_pct(ranking.get('test_pass_rate'))} "
            f"| {_fmt(ranking.get('avg_cost_efficiency'))} |"
        )

    lines += ["", "---", "", "## 按任务类别对比", ""]

    # 按类别对比
    categories = set()
    for s in summaries:
        categories.update(s.by_category().keys())
    if categories:
        lines.append("| 类别 | " + " | ".join(s.system_name for s in summaries) + " |")
        lines.append("|------|" + "|".join(["------"] * len(summaries)) + "|")
        for cat in sorted(categories):
            row = f"| `{cat}` |"
            for s in summaries:
                score = s.by_category().get(cat)
                row += f" {_pct(score)} |"
            lines.append(row)

    lines += ["", "---", "", "## 按难度对比", ""]

    # 按难度对比
    difficulties = ["easy", "medium", "hard"]
    lines.append("| 难度 | " + " | ".join(s.system_name for s in summaries) + " |")
    lines.append("|------|" + "|".join(["------"] * len(summaries)) + "|")
    for diff in difficulties:
        row = f"| {diff} |"
        for s in summaries:
            score = s.by_difficulty().get(diff)
            row += f" {_pct(score)} |"
        lines.append(row)

    lines += ["", "---", "", "## 各任务详细结果", ""]

    # 任务级别详情
    for s in summaries:
        lines += [f"### 系统：`{s.system_name}`", ""]
        lines.append("| 任务 ID | 类别 | 难度 | L1 语法 | L2 契约 | L3 架构 | L4 测试 | 综合分 |")
        lines.append("|---------|------|------|---------|---------|---------|---------|--------|")
        for r in s.task_results:
            lines.append(
                f"| {r.task_id} "
                f"| `{r.category}` "
                f"| {r.difficulty} "
                f"| {r.level1_syntax.pass_rate_pct} "
                f"| {r.level2_contract.pass_rate_pct} "
                f"| {r.level3_arch.pass_rate_pct} "
                f"| {r.level4_test.pass_rate_pct} "
                f"| {_pct(r.codegen_score)} |"
            )
        lines.append("")

    lines += [
        "---",
        "",
        "## 方法论说明",
        "",
        "### 4 级评估指标",
        "",
        "| 级别 | 名称 | 权重 | 计算方法 |",
        "|------|------|------|---------|",
        "| L1 | AST 语法通过率 | 10% | `ast.parse()` 是否抛出 SyntaxError |",
        "| L2 | 结构契约通过率 | 30% | `required_signatures` 包含率 + `forbidden_patterns` 排除率 |",
        "| L3 | 架构约束通过率 | 30% | `arch_check.py --snippet` 检查（AC-1~4） |",
        "| L4 | 参考测试通过率 | 30% | `pytest` 运行参考测试套件（`test_*.py`） |",
        "",
        "### 综合分公式",
        "",
        "```",
        "codegen_score = sum(level_pass_rate × weight / sum_valid_weights)",
        "  其中：NaN 级别（跳过）的权重等比重新分配给有效级别",
        "```",
        "",
        "### 成本效率公式",
        "",
        "```",
        "cost_efficiency = codegen_score / (retrieval_tokens / 1000 + 1e-6)",
        "  解读：每 1000 检索 token 贡献的代码质量分",
        "```",
        "",
        "---",
        f"*由 MMS Benchmark EP-132 自动生成 · {now}*",
    ]

    return lines


def _pct(v: Optional[float]) -> str:
    """格式化为百分比字符串"""
    if v is None or math.isnan(v):
        return "N/A"
    return f"{v * 100:.1f}%"


def _fmt(v: Optional[float]) -> str:
    """格式化为 2 位小数"""
    if v is None or math.isnan(v):
        return "N/A"
    return f"{v:.2f}"


def _safe_float(v: float) -> object:
    return None if math.isnan(v) else round(v, 4)
