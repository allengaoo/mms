"""
src/mms/bootstrap/schema_evolution.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Schema 演进反馈回路（Phase 8）

功能：
  在每次 Bootstrap 完成后，自动生成两种格式的 Schema 演进报告：
    1. schema_evolution_log.jsonl — 结构化日志，逐行追加（机器可读）
    2. schema_evolution_report.md — 人类可读的 Markdown 报告（每次覆盖最新状态）

报告内容（三类演进信号）：
  A. 字段空值率 > 30% — 违反 P1_density_over_completeness，需要字段重构
  B. 推断模糊记录    — inference_ambiguous=True，说明当前信号规则存在歧义
  C. UNKNOWN 层归类  — 说明信号覆盖不足，需补充 Override 规则

设计原则：
  - 零外部依赖（Python stdlib only）
  - 幂等：多次运行输出结果一致（jsonl 追加，md 覆盖）
  - 不阻塞主流程：任何写入错误只记录 warning，不抛出异常

版本：v5.0 | 创建于：2026-05-06 | Phase 8
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ─── 报告输出路径 ──────────────────────────────────────────────────────────────

_DEFAULT_LOG_FILENAME = "schema_evolution_log.jsonl"
_DEFAULT_REPORT_FILENAME = "schema_evolution_report.md"

# ─── 字段空值率阈值（违反 P1_density_over_completeness）────────────────────────

_NULL_RATE_THRESHOLD = 0.30  # > 30% 空值率触发警告

# ─── 已知的非空关键字段（用于空值率检查）────────────────────────────────────────

_MONITORED_FIELDS = [
    "layer", "tier", "tags", "type",
    "context", "forces", "solution",    # Pattern 特有
    "decision_status", "context", "decision",  # Decision 特有
    "steps_summary", "involves_layers",  # BusinessFlow 特有
    "known_occurrence",                  # AntiPattern 特有
    "ast_pointer", "class_name",         # Bootstrap 生成字段
    "about_concepts",
]


# ─── 数据结构 ─────────────────────────────────────────────────────────────────

class BootstrapRunStats:
    """
    单次 Bootstrap 运行的统计数据，作为 Schema 演进报告的输入。
    由 ontology_populator.bootstrap_project() 在完成后填充。
    """

    def __init__(
        self,
        run_id: str,
        project_path: str,
        weights_profile: str,
        total_files: int,
        total_classes: int,
        memories_generated: int,
        memories_archived: int,
        inferences: Optional[Dict[str, Any]] = None,   # class_fqn → LayerInference
        memory_files: Optional[List[Path]] = None,     # 生成的 .md 文件列表
    ):
        self.run_id = run_id
        self.project_path = project_path
        self.weights_profile = weights_profile
        self.total_files = total_files
        self.total_classes = total_classes
        self.memories_generated = memories_generated
        self.memories_archived = memories_archived
        self.inferences = inferences or {}
        self.memory_files = memory_files or []
        self.timestamp = datetime.now(timezone.utc).isoformat()


# ─── 分析函数 ─────────────────────────────────────────────────────────────────

def _parse_frontmatter(text: str) -> Optional[Dict[str, Any]]:
    """从 Markdown 文件提取 YAML frontmatter（无 PyYAML 依赖的简单版本）。"""
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        import yaml
        return yaml.safe_load(parts[1]) or {}
    except Exception:
        return {}


def _analyze_null_rates(
    memory_files: List[Path],
) -> Dict[str, Dict[str, Any]]:
    """
    分析生成的 .md 文件中各字段的空值率。

    返回：
        {
            field_name: {
                "total": int,       # 检查的记忆总数
                "null_count": int,  # 该字段为空的记忆数
                "null_rate": float, # 空值率（0~1）
                "samples": [...]    # 空值样本（最多 3 个 memory ID）
            }
        }
    """
    field_stats: Dict[str, Dict[str, Any]] = {
        field: {"total": 0, "null_count": 0, "samples": []}
        for field in _MONITORED_FIELDS
    }

    for md_file in memory_files:
        try:
            text = md_file.read_text(encoding="utf-8")
            fm = _parse_frontmatter(text)
            if not fm:
                continue
            mem_id = str(fm.get("id", md_file.name))

            for field in _MONITORED_FIELDS:
                stats = field_stats[field]
                stats["total"] += 1
                value = fm.get(field)
                is_null = (
                    value is None
                    or value == ""
                    or value == []
                    or value == {}
                )
                if is_null:
                    stats["null_count"] += 1
                    if len(stats["samples"]) < 3:
                        stats["samples"].append(mem_id)
        except Exception:
            continue

    for field, stats in field_stats.items():
        total = stats["total"]
        stats["null_rate"] = (
            round(stats["null_count"] / total, 3) if total > 0 else 0.0
        )

    return field_stats


def _collect_ambiguous_inferences(
    inferences: Dict[str, Any],
) -> List[Dict[str, str]]:
    """
    收集推断模糊的类（inference_ambiguous 标记）。

    Args:
        inferences: infer_all() 的返回值 {fqn: (LayerInference, ObjectTypeMapping)}

    Returns:
        模糊推断记录列表 [{fqn, inferred_layer, confidence, all_scores}, ...]
    """
    ambiguous = []
    for fqn, result in inferences.items():
        layer_inf = result[0] if isinstance(result, tuple) else result
        all_scores = getattr(layer_inf, "all_scores", {}) or {}
        if all_scores.get("_ambiguous"):
            ambiguous.append({
                "fqn": fqn,
                "inferred_layer": getattr(layer_inf, "inferred_layer", "?"),
                "confidence": getattr(layer_inf, "confidence", 0.0),
            })
    return ambiguous


def _collect_unknown_inferences(
    inferences: Dict[str, Any],
) -> List[Dict[str, str]]:
    """收集推断结果为 UNKNOWN 的类（信号覆盖不足）。"""
    unknowns = []
    for fqn, result in inferences.items():
        layer_inf = result[0] if isinstance(result, tuple) else result
        if getattr(layer_inf, "inferred_layer", "") == "UNKNOWN":
            unknowns.append({
                "fqn": fqn,
                "confidence": getattr(layer_inf, "confidence", 0.0),
            })
    return unknowns


# ─── JSONL 日志记录 ───────────────────────────────────────────────────────────

def append_jsonl_entry(
    stats: BootstrapRunStats,
    log_path: Path,
    null_rate_analysis: Dict[str, Dict[str, Any]],
    ambiguous: List[Dict[str, str]],
    unknowns: List[Dict[str, str]],
) -> None:
    """
    向 schema_evolution_log.jsonl 追加一条结构化日志记录。
    追加写入（不覆盖），文件不存在时自动创建。
    """
    entry = {
        "timestamp": stats.timestamp,
        "run_id": stats.run_id,
        "project_path": stats.project_path,
        "weights_profile": stats.weights_profile,
        "summary": {
            "total_files": stats.total_files,
            "total_classes": stats.total_classes,
            "memories_generated": stats.memories_generated,
            "memories_archived": stats.memories_archived,
            "ambiguous_count": len(ambiguous),
            "unknown_count": len(unknowns),
        },
        "null_rate_violations": [
            {
                "field": field,
                "null_rate": d["null_rate"],
                "null_count": d["null_count"],
                "total": d["total"],
                "samples": d["samples"],
            }
            for field, d in null_rate_analysis.items()
            if d["null_rate"] > _NULL_RATE_THRESHOLD and d["total"] > 0
        ],
        "ambiguous_inferences": ambiguous[:20],  # 最多记录 20 条
        "unknown_inferences": unknowns[:20],
    }

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        import warnings
        warnings.warn(f"[schema_evolution] Failed to write JSONL log: {e}")


# ─── Markdown 报告生成 ────────────────────────────────────────────────────────

def _format_null_rate_section(null_rate_analysis: Dict[str, Dict[str, Any]]) -> str:
    """生成字段空值率报告段落。"""
    violations = [
        (field, d)
        for field, d in null_rate_analysis.items()
        if d["null_rate"] > _NULL_RATE_THRESHOLD and d["total"] > 0
    ]

    if not violations:
        return "_所有字段空值率均在 30% 阈值以内。✅_\n"

    lines = [
        "| 字段 | 空值率 | 空值数 / 总数 | 样本 Memory ID |",
        "|------|--------|--------------|----------------|",
    ]
    for field, d in sorted(violations, key=lambda x: -x[1]["null_rate"]):
        samples_str = ", ".join(d["samples"]) if d["samples"] else "-"
        lines.append(
            f"| `{field}` | **{d['null_rate']:.0%}** | "
            f"{d['null_count']} / {d['total']} | {samples_str} |"
        )

    return "\n".join(lines) + "\n"


def _format_ambiguous_section(ambiguous: List[Dict[str, str]]) -> str:
    """生成模糊推断报告段落。"""
    if not ambiguous:
        return "_本次 Bootstrap 无模糊推断。✅_\n"

    lines = [
        "| 类 FQN | 推断层级 | 置信度 |",
        "|--------|---------|--------|",
    ]
    for item in ambiguous[:15]:
        fqn = item["fqn"]
        if len(fqn) > 60:
            fqn = "..." + fqn[-57:]
        lines.append(
            f"| `{fqn}` | `{item['inferred_layer']}` | {item['confidence']:.2f} |"
        )
    if len(ambiguous) > 15:
        lines.append(f"| _... 还有 {len(ambiguous) - 15} 条_ | | |")

    return "\n".join(lines) + "\n"


def _format_unknown_section(unknowns: List[Dict[str, str]]) -> str:
    """生成 UNKNOWN 推断报告段落。"""
    if not unknowns:
        return "_本次 Bootstrap 无 UNKNOWN 推断。✅_\n"

    lines = [
        "| 类 FQN | 置信度 |",
        "|--------|--------|",
    ]
    for item in unknowns[:15]:
        fqn = item["fqn"]
        if len(fqn) > 70:
            fqn = "..." + fqn[-67:]
        lines.append(f"| `{fqn}` | {item['confidence']:.2f} |")
    if len(unknowns) > 15:
        lines.append(f"| _... 还有 {len(unknowns) - 15} 条_ | |")

    return "\n".join(lines) + "\n"


def generate_markdown_report(
    stats: BootstrapRunStats,
    null_rate_analysis: Dict[str, Dict[str, Any]],
    ambiguous: List[Dict[str, str]],
    unknowns: List[Dict[str, str]],
) -> str:
    """生成完整的 Markdown 报告内容。"""
    null_violations_count = sum(
        1 for d in null_rate_analysis.values()
        if d["null_rate"] > _NULL_RATE_THRESHOLD and d["total"] > 0
    )

    health_icon = "🟢" if (
        null_violations_count == 0 and len(ambiguous) == 0 and len(unknowns) == 0
    ) else "🟡" if (
        null_violations_count <= 2 and len(unknowns) <= 5
    ) else "🔴"

    ts_human = datetime.fromisoformat(stats.timestamp.replace("Z", "+00:00")).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    report = f"""# Schema 演进反馈报告 {health_icon}

> **生成时间**：{ts_human}
> **运行 ID**：`{stats.run_id}`
> **项目路径**：`{stats.project_path}`
> **权重 Profile**：`{stats.weights_profile}`
> **本报告由 `schema_evolution.py` 自动生成，请勿手动编辑**

---

## 执行摘要

| 指标 | 数值 |
|------|------|
| 扫描文件数 | {stats.total_files} |
| 发现类总数 | {stats.total_classes} |
| 生成记忆节点 | {stats.memories_generated} |
| 归档孤立节点 | {stats.memories_archived} |
| 模糊推断数 | {len(ambiguous)} |
| UNKNOWN 推断数 | {len(unknowns)} |
| 字段空值率违规数 | {null_violations_count} |

---

## A. 字段空值率分析（P1_density_over_completeness）

> 阈值：空值率 > 30% 即为违规。建议重构对应字段或拆分 ObjectType。

{_format_null_rate_section(null_rate_analysis)}

---

## B. 推断模糊记录（inference_rules.yaml Stage 2 冲突检测）

> 两个层的得分差 < 0.15 且属于已知冲突对时，标记为 AMBIGUOUS。
> 建议为以下类添加 `.mms/override_rules.yaml` 中的 YAML Override。

{_format_ambiguous_section(ambiguous)}

---

## C. UNKNOWN 层归类（信号覆盖不足）

> 推断结果为 UNKNOWN 说明六路信号均无法产生足够置信度。
> 建议检查类名、目录结构或注解，或添加 Override 规则。

{_format_unknown_section(unknowns)}

---

## 建议行动

"""
    if null_violations_count > 0:
        report += "- **字段重构**：空值率违规字段可能是 God Object 的体现。考虑将其移至子 ObjectType 或标注为 optional。\n"
    if ambiguous:
        report += f"- **添加 Override**：为 {len(ambiguous)} 个模糊类添加 `.mms/override_rules.yaml` 规则，消除推断歧义。\n"
    if unknowns:
        report += f"- **补充信号**：{len(unknowns)} 个 UNKNOWN 类需要更多信号覆盖。检查这些类的目录/命名约定，或为特定框架激活 `signature` 权重。\n"
    if not (null_violations_count or ambiguous or unknowns):
        report += "- Schema 健康度良好，无需立即行动。可继续积累下一轮演进数据。\n"

    report += f"""
---

_报告格式：Schema v5.0 | 设计原则参考：`assets/ontology_schema/_config/ontology_design_principles.yaml`_
_历史日志：`docs/memory/_system/schema_evolution_log.jsonl`_
"""
    return report


def write_markdown_report(
    report_content: str,
    report_path: Path,
) -> None:
    """覆盖写入 Markdown 报告（每次 Bootstrap 更新最新状态）。"""
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_content, encoding="utf-8")
    except Exception as e:
        import warnings
        warnings.warn(f"[schema_evolution] Failed to write Markdown report: {e}")


# ─── 主入口（供 ontology_populator 调用）─────────────────────────────────────

def record_bootstrap_run(
    stats: BootstrapRunStats,
    output_dir: Optional[Path] = None,
) -> Tuple[Path, Path]:
    """
    记录一次 Bootstrap 运行的 Schema 演进数据。

    分析三类演进信号（字段空值率、模糊推断、UNKNOWN 推断），
    分别写入 JSONL 日志（追加）和 Markdown 报告（覆盖）。

    Args:
        stats:      BootstrapRunStats 对象（由 bootstrap_project 填充）
        output_dir: 输出目录（默认 docs/memory/_system/）

    Returns:
        (jsonl_path, markdown_path)
    """
    if output_dir is None:
        # 从 project_path 推断
        output_dir = Path(stats.project_path) / "docs" / "memory" / "_system"

    log_path = output_dir / _DEFAULT_LOG_FILENAME
    report_path = output_dir / _DEFAULT_REPORT_FILENAME

    # ── 分析三类信号 ────────────────────────────────────────────────────────
    null_rate_analysis = _analyze_null_rates(stats.memory_files)
    ambiguous = _collect_ambiguous_inferences(stats.inferences)
    unknowns = _collect_unknown_inferences(stats.inferences)

    # ── 写入 JSONL（追加）────────────────────────────────────────────────────
    append_jsonl_entry(stats, log_path, null_rate_analysis, ambiguous, unknowns)

    # ── 写入 Markdown（覆盖最新状态）────────────────────────────────────────
    report_content = generate_markdown_report(stats, null_rate_analysis, ambiguous, unknowns)
    write_markdown_report(report_content, report_path)

    return log_path, report_path


def record_incremental_stats(
    new_memory_files: List[Path],
    archived_memory_files: List[Path],
    inferences: Optional[Dict[str, Any]] = None,
    output_dir: Optional[Path] = None,
) -> Optional[Path]:
    """
    记录增量应用后的统计数据（供 rule_post_apply_incremental 的 rule_post_07 调用）。

    追加一条轻量级 JSONL 记录（不生成完整 Markdown 报告）。

    Returns:
        jsonl_path（或 None 若 output_dir 未指定）
    """
    if output_dir is None:
        return None

    log_path = output_dir / _DEFAULT_LOG_FILENAME
    inferences = inferences or {}

    ambiguous = _collect_ambiguous_inferences(inferences)
    unknowns = _collect_unknown_inferences(inferences)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_type": "incremental",
        "summary": {
            "new_memories": len(new_memory_files),
            "archived_memories": len(archived_memory_files),
            "ambiguous_count": len(ambiguous),
            "unknown_count": len(unknowns),
        },
        "ambiguous_inferences": ambiguous[:10],
        "unknown_inferences": unknowns[:10],
    }

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        import warnings
        warnings.warn(f"[schema_evolution] Failed to write incremental JSONL: {e}")

    return log_path
