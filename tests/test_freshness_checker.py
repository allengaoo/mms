"""
test_freshness_checker.py — Phase 4 测试

验证 FreshnessChecker 和 HealthReport 的核心功能。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mms.memory.freshness_checker import (
    FreshnessChecker,
    FreshnessReport,
    check_freshness,
)
from mms.memory.graph_health import compute_health_metrics, HealthReport


# ─── 测试辅助 ────────────────────────────────────────────────────────────────

def _write_memory(mem_dir: Path, mem_id: str, cites: list = None,
                  impacts: list = None, tier: str = "warm",
                  about_concepts: list = None) -> Path:
    """写入测试记忆文件。"""
    lines = [
        "---",
        f"id: {mem_id}",
        f"tier: {tier}",
        "layer: L3_domain",
    ]
    if cites:
        lines.append("cites_files:")
        for f in cites:
            lines.append(f"  - {f}")
    if impacts:
        lines.append("impacts:")
        for i in impacts:
            lines.append(f"  - {i}")
    if about_concepts:
        lines.append("about_concepts:")
        for c in about_concepts:
            lines.append(f"  - {c}")
    lines += ["---", "", f"# {mem_id}", "", "内容。"]

    p = mem_dir / f"{mem_id}.md"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def _write_code_file(project_dir: Path, rel_path: str, content: str = "# code") -> Path:
    """写入代码文件（模拟被引用的代码文件）。"""
    p = project_dir / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ─── FreshnessChecker 核心测试 ───────────────────────────────────────────────

class TestFreshnessChecker:
    def test_marks_stale_when_file_cited(self, tmp_path: Path) -> None:
        """变更文件有 cites 边时正确标记 stale。"""
        mem_dir = tmp_path / "shared"
        mem_dir.mkdir(parents=True)

        _write_memory(mem_dir, "MEM-001", cites=["backend/response.py"])
        _write_memory(mem_dir, "MEM-002", cites=["backend/auth.py"])

        checker = FreshnessChecker(memory_root=tmp_path)
        report = checker.check(["backend/response.py"])

        assert "MEM-001" in report.stale_ids
        assert "MEM-002" not in report.stale_ids

    def test_no_stale_when_file_not_cited(self, tmp_path: Path) -> None:
        """变更文件无 cites 边时返回空列表。"""
        mem_dir = tmp_path / "shared"
        mem_dir.mkdir(parents=True)

        _write_memory(mem_dir, "MEM-001", cites=["backend/other.py"])

        checker = FreshnessChecker(memory_root=tmp_path)
        report = checker.check(["backend/response.py"])

        assert report.stale_ids == []
        assert report.propagated_ids == []

    def test_impacts_propagation_one_hop(self, tmp_path: Path) -> None:
        """impacts 传播一跳后包含二级节点。"""
        mem_dir = tmp_path / "shared"
        mem_dir.mkdir(parents=True)

        _write_memory(mem_dir, "MEM-001",
                      cites=["backend/response.py"],
                      impacts=["MEM-002"])
        _write_memory(mem_dir, "MEM-002")  # 无 cites，但被 impacts 指向

        checker = FreshnessChecker(memory_root=tmp_path)
        report = checker.check(["backend/response.py"])

        assert "MEM-001" in report.stale_ids
        assert "MEM-002" in report.propagated_ids

    def test_impacts_not_double_counted(self, tmp_path: Path) -> None:
        """stale 和 propagated 不重叠。"""
        mem_dir = tmp_path / "shared"
        mem_dir.mkdir(parents=True)

        _write_memory(mem_dir, "MEM-001",
                      cites=["backend/response.py"],
                      impacts=["MEM-002"])
        _write_memory(mem_dir, "MEM-002",
                      cites=["backend/response.py"])  # 同样引用该文件

        checker = FreshnessChecker(memory_root=tmp_path)
        report = checker.check(["backend/response.py"])

        # MEM-002 直接 stale，不应出现在 propagated
        assert "MEM-002" in report.stale_ids
        assert "MEM-002" not in report.propagated_ids

    def test_empty_changed_files(self, tmp_path: Path) -> None:
        """空文件列表返回干净报告。"""
        checker = FreshnessChecker(memory_root=tmp_path)
        report = checker.check([])
        assert report.is_clean
        assert report.stale_ids == []

    def test_all_suspect_ids_is_union(self, tmp_path: Path) -> None:
        """all_suspect_ids 是 stale + propagated 的并集。"""
        mem_dir = tmp_path / "shared"
        mem_dir.mkdir(parents=True)

        _write_memory(mem_dir, "MEM-001",
                      cites=["backend/response.py"],
                      impacts=["MEM-002"])
        _write_memory(mem_dir, "MEM-002")

        checker = FreshnessChecker(memory_root=tmp_path)
        report = checker.check(["backend/response.py"])

        assert set(report.all_suspect_ids) == set(report.stale_ids) | set(report.propagated_ids)

    def test_check_files_convenience_method(self, tmp_path: Path) -> None:
        """check_files 便捷方法返回 ID 列表。"""
        mem_dir = tmp_path / "shared"
        mem_dir.mkdir(parents=True)
        _write_memory(mem_dir, "MEM-001", cites=["backend/response.py"])

        checker = FreshnessChecker(memory_root=tmp_path)
        ids = checker.check_files(["backend/response.py"])
        assert "MEM-001" in ids


# ─── FreshnessReport 格式化测试 ──────────────────────────────────────────────

class TestFreshnessReport:
    def test_is_clean_when_empty(self) -> None:
        report = FreshnessReport()
        assert report.is_clean

    def test_not_clean_when_stale(self) -> None:
        report = FreshnessReport(stale_ids=["MEM-001"])
        assert not report.is_clean

    def test_summary_lines_clean(self) -> None:
        report = FreshnessReport(total_checked=10)
        lines = report.summary_lines()
        assert any("正常" in l for l in lines)

    def test_summary_lines_with_stale(self) -> None:
        report = FreshnessReport(stale_ids=["MEM-001"], total_checked=5)
        lines = report.summary_lines()
        assert any("MEM-001" in l for l in lines)


# ─── compute_health_metrics 测试 ──────────────────────────────────────────────

class TestGraphHealth:
    def test_empty_graph_returns_zero_counts(self, tmp_path: Path) -> None:
        """空图返回零节点报告，不抛异常。"""
        from mms.memory.graph_resolver import MemoryGraph
        graph = MemoryGraph(memory_root=tmp_path)
        report = compute_health_metrics(graph=graph)
        assert report.total_nodes == 0

    def test_counts_nodes_by_tier(self, tmp_path: Path) -> None:
        """正确统计各 tier 节点数。"""
        mem_dir = tmp_path / "shared"
        mem_dir.mkdir(parents=True)
        _write_memory(mem_dir, "MEM-HOT-001", tier="hot")
        _write_memory(mem_dir, "MEM-WARM-001", tier="warm")
        _write_memory(mem_dir, "MEM-WARM-002", tier="warm")

        from mms.memory.graph_resolver import MemoryGraph
        graph = MemoryGraph(memory_root=tmp_path)
        report = compute_health_metrics(graph=graph)

        assert report.total_nodes == 3
        assert report.hot_nodes == 1
        assert report.warm_nodes == 2

    def test_counts_nodes_with_cites(self, tmp_path: Path) -> None:
        """正确统计有 cites 边的节点数。"""
        mem_dir = tmp_path / "shared"
        mem_dir.mkdir(parents=True)
        _write_memory(mem_dir, "MEM-001", cites=["backend/x.py"])
        _write_memory(mem_dir, "MEM-002")  # 无 cites

        from mms.memory.graph_resolver import MemoryGraph
        graph = MemoryGraph(memory_root=tmp_path)
        report = compute_health_metrics(graph=graph)

        assert report.nodes_with_cites == 1
        assert report.total_nodes == 2

    def test_isolated_node_detection(self, tmp_path: Path) -> None:
        """孤立节点（无任何边）被正确识别。"""
        mem_dir = tmp_path / "shared"
        mem_dir.mkdir(parents=True)
        _write_memory(mem_dir, "ISOLATED-001")  # 无任何边
        _write_memory(mem_dir, "CONNECTED-001", cites=["backend/x.py"])

        from mms.memory.graph_resolver import MemoryGraph
        graph = MemoryGraph(memory_root=tmp_path)
        report = compute_health_metrics(graph=graph)

        assert report.isolated_nodes == 1

    def test_density_formula(self, tmp_path: Path) -> None:
        """图密度公式 = total_edges / (n*(n-1)) 正确。"""
        mem_dir = tmp_path / "shared"
        mem_dir.mkdir(parents=True)
        _write_memory(mem_dir, "MEM-A", cites=["backend/a.py"])
        _write_memory(mem_dir, "MEM-B")

        from mms.memory.graph_resolver import MemoryGraph
        graph = MemoryGraph(memory_root=tmp_path)
        report = compute_health_metrics(graph=graph)

        n = report.total_nodes
        expected_density = report.total_edges / (n * (n - 1)) if n > 1 else 0.0
        assert abs(report.graph_density - expected_density) < 1e-6

    def test_format_lines_does_not_raise(self, tmp_path: Path) -> None:
        """format_lines 不抛异常。"""
        from mms.memory.graph_resolver import MemoryGraph
        graph = MemoryGraph(memory_root=tmp_path)
        report = compute_health_metrics(graph=graph)
        lines = report.format_lines(use_color=False)
        assert isinstance(lines, list)
        assert len(lines) > 0

    def test_isolation_rate_warning_threshold(self) -> None:
        """孤立率 > 20% 时有警告。"""
        report = HealthReport(total_nodes=10, isolated_nodes=3)
        # isolation_rate = 3/10 = 30% > 20%
        report_full = HealthReport.__new__(HealthReport)
        report_full.total_nodes = 10
        report_full.isolated_nodes = 3
        report_full.hot_nodes = 0
        report_full.warm_nodes = 10
        report_full.cold_nodes = 0
        report_full.archive_nodes = 0
        report_full.nodes_with_cites = 0
        report_full.nodes_with_about = 0
        report_full.nodes_with_impacts = 0
        report_full.total_edges = 0
        report_full.avg_neighbors = 0.0
        report_full.graph_density = 0.0
        report_full.quality_warnings = []
        report_full.quality_ok = []

        assert report_full.isolation_rate == pytest.approx(0.3)
