#!/usr/bin/env python3
"""
graph_health.py — 记忆图健康监控（Phase 4-B）

提供 compute_health_metrics() 函数，计算记忆图的质量指标：
  - 节点总数与分层分布
  - cites 边覆盖率（有 cites_files 的节点比例）
  - about 边覆盖率（有 about_concepts 的节点比例）
  - 孤立节点数（无任何边的节点）
  - 平均邻居数
  - 图密度

供 cli.py 的 cmd_status 调用，输出如下格式：
  记忆图健康：
    节点总数：142  热节点：38
    有 cites 边：89/142 (63%)
    有 about 边：61/142 (43%)
    孤立节点（无任何边）：12    ← >20% 时标红
    平均邻居数：3.2
    图密度：0.022               ← >0.1 时警告

版本：v1.0 | 创建于：2026-04-25 | Phase 4-B
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


# ── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class HealthReport:
    """
    记忆图健康报告。

    所有比率字段为 0.0–1.0 浮点数。
    quality_warnings 包含需要关注的质量问题描述。
    """
    total_nodes: int = 0
    hot_nodes: int = 0
    warm_nodes: int = 0
    cold_nodes: int = 0
    archive_nodes: int = 0

    nodes_with_cites: int = 0       # 有 cites_files（非空）的节点数
    nodes_with_about: int = 0       # 有 about_concepts（非空）的节点数
    nodes_with_impacts: int = 0     # 有 impacts（非空）的节点数
    isolated_nodes: int = 0         # 无任何边的节点数（所有边字段均空）

    total_edges: int = 0            # 所有边的总数（related_to + cites + about + impacts + ...）
    avg_neighbors: float = 0.0      # 平均邻居数
    graph_density: float = 0.0      # 图密度 = total_edges / (n * (n-1))

    quality_warnings: List[str] = field(default_factory=list)
    quality_ok: List[str] = field(default_factory=list)

    @property
    def cites_coverage(self) -> float:
        if self.total_nodes == 0:
            return 0.0
        return self.nodes_with_cites / self.total_nodes

    @property
    def about_coverage(self) -> float:
        if self.total_nodes == 0:
            return 0.0
        return self.nodes_with_about / self.total_nodes

    @property
    def isolation_rate(self) -> float:
        if self.total_nodes == 0:
            return 0.0
        return self.isolated_nodes / self.total_nodes

    def format_lines(self, use_color: bool = True) -> List[str]:
        """格式化为 CLI 显示行列表。"""
        R = "\033[91m" if use_color else ""
        Y = "\033[93m" if use_color else ""
        G = "\033[92m" if use_color else ""
        X = "\033[0m" if use_color else ""

        def pct(val: float) -> str:
            return f"{val * 100:.0f}%"

        lines = [
            f"记忆图健康：",
            f"  节点总数：{self.total_nodes}  "
            f"热节点：{self.hot_nodes}  温节点：{self.warm_nodes}  "
            f"冷节点：{self.cold_nodes}  归档：{self.archive_nodes}",
            f"  有 cites 边：{self.nodes_with_cites}/{self.total_nodes} ({pct(self.cites_coverage)})",
            f"  有 about 边：{self.nodes_with_about}/{self.total_nodes} ({pct(self.about_coverage)})",
            f"  有 impacts 边：{self.nodes_with_impacts}/{self.total_nodes}",
        ]

        # 孤立节点（>20% 时标红）
        isolated_str = f"  孤立节点（无任何边）：{self.isolated_nodes}"
        if self.isolation_rate > 0.2:
            isolated_str = f"{R}{isolated_str}  ← 孤立率 {pct(self.isolation_rate)} 过高！{X}"
        elif self.isolation_rate > 0.1:
            isolated_str = f"{Y}{isolated_str}  ← 孤立率 {pct(self.isolation_rate)}{X}"
        lines.append(isolated_str)

        lines.append(f"  平均邻居数：{self.avg_neighbors:.1f}")

        # 图密度（>0.1 时警告）
        density_str = f"  图密度：{self.graph_density:.3f}"
        if self.graph_density > 0.1:
            density_str = f"{Y}{density_str}  ← 密度过高，可能存在无效边{X}"
        lines.append(density_str)

        # 质量提示
        if self.quality_warnings:
            lines.append(f"  {Y}⚠️  质量警告：{X}")
            for w in self.quality_warnings:
                lines.append(f"    - {w}")
        if self.quality_ok:
            lines.append(f"  {G}✅ 质量良好：{X}")
            for o in self.quality_ok:
                lines.append(f"    - {o}")

        return lines


# ── 计算逻辑 ──────────────────────────────────────────────────────────────────

def compute_health_metrics(
    graph=None,  # MemoryGraph 实例，None 时自动创建
    memory_root: Optional[Path] = None,
) -> HealthReport:
    """
    计算记忆图健康指标。

    参数：
        graph       : MemoryGraph 实例（可复用已有实例，避免重复加载）
        memory_root : 记忆根目录（测试用）

    返回：
        HealthReport 数据类
    """
    if graph is None:
        from mms.memory.graph_resolver import MemoryGraph
        graph = MemoryGraph(memory_root=memory_root)

    graph._ensure_loaded()
    nodes = list(graph._nodes.values())
    n = len(nodes)
    report = HealthReport(total_nodes=n)

    if n == 0:
        report.quality_warnings.append("记忆库为空（0 个节点）")
        return report

    # 分层统计
    tier_counts: Dict[str, int] = {}
    for node in nodes:
        tier_counts[node.tier] = tier_counts.get(node.tier, 0) + 1

    report.hot_nodes = tier_counts.get("hot", 0)
    report.warm_nodes = tier_counts.get("warm", 0)
    report.cold_nodes = tier_counts.get("cold", 0)
    report.archive_nodes = tier_counts.get("archive", 0)

    # 边覆盖率统计
    total_edge_count = 0
    for node in nodes:
        has_cites = bool(node.cites_files)
        has_about = bool(node.about_concepts)
        has_impacts = bool(node.impacts)
        has_related = bool(node.related_ids)
        has_contradicts = bool(node.contradicts)
        has_derived = bool(node.derived_from)

        if has_cites:
            report.nodes_with_cites += 1
        if has_about:
            report.nodes_with_about += 1
        if has_impacts:
            report.nodes_with_impacts += 1

        # 孤立节点：无任何边
        if not any([has_cites, has_about, has_impacts, has_related,
                    has_contradicts, has_derived]):
            report.isolated_nodes += 1

        # 统计总边数
        total_edge_count += (
            len(node.cites_files) + len(node.about_concepts) +
            len(node.impacts) + len(node.related_ids) +
            len(node.contradicts) + len(node.derived_from)
        )

    report.total_edges = total_edge_count
    report.avg_neighbors = total_edge_count / n if n > 0 else 0.0

    # 图密度（有向图：edges / (n * (n-1))）
    max_edges = n * (n - 1)
    report.graph_density = total_edge_count / max_edges if max_edges > 0 else 0.0

    # 质量评估
    if report.isolation_rate > 0.2:
        report.quality_warnings.append(
            f"孤立节点比例 {report.isolation_rate * 100:.0f}% 过高，"
            "建议运行 mms distill 重新提炼以建立图连接"
        )
    elif report.isolation_rate > 0.1:
        report.quality_warnings.append(
            f"孤立节点比例 {report.isolation_rate * 100:.0f}%，"
            "建议逐步为这些记忆添加 cites_files 或 about_concepts"
        )

    if report.about_coverage < 0.3 and n > 5:
        report.quality_warnings.append(
            f"about 边覆盖率 {report.about_coverage * 100:.0f}% 偏低，"
            "概念级检索效果受限，建议运行 mms dream 后 promote 记忆以自动建边"
        )

    if report.graph_density > 0.1:
        report.quality_warnings.append(
            f"图密度 {report.graph_density:.3f} 过高，可能存在大量无实际意义的边"
        )

    if report.hot_nodes > 0 and report.cites_coverage > 0.5:
        report.quality_ok.append(
            f"cites 边覆盖率 {report.cites_coverage * 100:.0f}%，代码变更追踪能力良好"
        )

    if report.isolation_rate <= 0.1:
        report.quality_ok.append(
            f"孤立节点比例 {report.isolation_rate * 100:.0f}%，图连通性良好"
        )

    return report


def format_health_for_status(memory_root: Optional[Path] = None, use_color: bool = True) -> str:
    """
    供 cli.py cmd_status 调用的便捷函数，返回格式化字符串。
    """
    try:
        report = compute_health_metrics(memory_root=memory_root)
        return "\n".join(report.format_lines(use_color=use_color))
    except Exception as e:  # noqa: BLE001
        return f"记忆图健康：（读取失败：{e}）"
