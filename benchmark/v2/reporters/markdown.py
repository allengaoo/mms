"""
Markdown Reporter — 生成可直接提交到 GitHub 的评测报告

扩展方式：在 _render_layer_section() 中新增分支处理新层的特殊展示逻辑。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from benchmark.v2.schema import BenchmarkResult, BenchmarkLayer, LayerResult, TaskStatus


def _score_badge(score: float) -> str:
    if score >= 0.8:
        color, label = "brightgreen", "PASS"
    elif score >= 0.5:
        color, label = "yellow", "WARN"
    else:
        color, label = "red", "FAIL"
    pct = int(score * 100)
    return f"![{label}](https://img.shields.io/badge/score-{pct}%25-{color})"


def _progress_bar(score: float, width: int = 20) -> str:
    filled = int(score * width)
    empty  = width - filled
    return f"{'█' * filled}{'░' * empty} {score:.1%}"


def _render_layer_section(lr: LayerResult) -> str:
    lines = []
    score_bar = _progress_bar(lr.score)
    lines.append(f"### Layer {lr.layer.value}: {lr.name}")
    lines.append("")
    lines.append(f"| 指标 | 值 |")
    lines.append(f"|------|-----|")
    lines.append(f"| 综合得分 | `{lr.score:.4f}` {score_bar} |")
    lines.append(f"| 任务总数 | {lr.tasks_total} |")
    lines.append(f"| 通过 | {lr.tasks_passed} |")
    lines.append(f"| 跳过 | {lr.tasks_skipped} |")
    lines.append(f"| 失败 | {lr.tasks_failed} |")
    lines.append(f"| 耗时 | {lr.duration_seconds:.2f}s |")
    lines.append("")

    if lr.metrics:
        lines.append("**详细指标：**")
        lines.append("")
        lines.append("| 指标名 | 值 |")
        lines.append("|--------|-----|")
        for key, val in lr.metrics.items():
            if key.endswith("_total") or key == "mode":
                continue
            lines.append(f"| `{key}` | `{val:.4f}` |")
        lines.append("")

    # 失败任务汇总
    failed_tasks = [t for t in lr.task_results if t.status == TaskStatus.FAILED]
    if failed_tasks:
        lines.append("<details>")
        lines.append(f"<summary>失败任务（{len(failed_tasks)} 条）</summary>")
        lines.append("")
        lines.append("| 任务 ID | 得分 | 错误 |")
        lines.append("|---------|------|------|")
        for t in failed_tasks:
            err = (t.error_message or "")[:80]
            lines.append(f"| `{t.task_id}` | {t.score:.2f} | {err} |")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    return "\n".join(lines)


def generate_markdown(result: BenchmarkResult) -> str:
    lines = []
    lines.append(f"# 木兰（Mulan）Benchmark 报告 v{result.version}")
    lines.append("")
    lines.append(f"> 评测时间：{result.timestamp}")
    lines.append("")
    lines.append(f"## 综合得分")
    lines.append("")
    overall = result.overall_score
    lines.append(f"**{overall:.1%}** — {_progress_bar(overall, width=30)}")
    lines.append("")
    lines.append(_score_badge(overall))
    lines.append("")

    lines.append("## 评测层摘要")
    lines.append("")
    lines.append("| 层 | 名称 | 得分 | 通过/总数 |")
    lines.append("|----|------|------|----------|")
    for layer_num in sorted(result.layer_results.keys()):
        lr = result.layer_results[layer_num]
        lines.append(
            f"| L{layer_num} | {lr.name} | `{lr.score:.4f}` "
            f"| {lr.tasks_passed}/{lr.tasks_total} |"
        )
    lines.append("")

    lines.append("---")
    lines.append("")
    for layer_num in sorted(result.layer_results.keys()):
        lr = result.layer_results[layer_num]
        lines.append(_render_layer_section(lr))
        lines.append("---")
        lines.append("")

    lines.append("## 配置")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(result.config, indent=2, ensure_ascii=False))
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


def save_markdown(result: BenchmarkResult, output_path: Optional[str] = None) -> str:
    content = generate_markdown(result)
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return content
