"""
test_diagnostics.py — 诊断模块单元测试 & 集成测试

涵盖：
  - MemoryVizCollector._parse_frontmatter: 各种 YAML 格式解析
  - MemoryVizCollector.collect: 临时目录中的完整收集流程
  - html_renderer.render_html: HTML 输出结构验证
  - visualize_memory CLI: 端到端 CLI 测试
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# 把 src/ 加入路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mms.diagnostics.memory_viz import (
    MemoryVizCollector,
    _parse_frontmatter,
    AstMapping,
    NodeData,
    VizData,
)
from mms.diagnostics.html_renderer import render_html, _node_to_vis, _edge_to_vis


# ────────────────────────────────────────────────────────────────────────────
# 1. _parse_frontmatter 单元测试
# ────────────────────────────────────────────────────────────────────────────

class TestParseFrontmatter:

    def _make_md(self, frontmatter: str, body: str = "# Test") -> str:
        return f"---\n{frontmatter}\n---\n{body}"

    def test_scalar_fields(self):
        md = self._make_md("id: MEM-L-001\nlayer: CC\ntier: hot\n")
        fm = _parse_frontmatter(md)
        assert fm["id"] == "MEM-L-001"
        assert fm["layer"] == "CC"
        assert fm["tier"] == "hot"

    def test_inline_list(self):
        md = self._make_md("tags: [api, contract, seed]\n")
        fm = _parse_frontmatter(md)
        assert fm["tags"] == ["api", "contract", "seed"]

    def test_multiline_list(self):
        md = self._make_md("cites_files:\n  - src/a.py\n  - src/b.py\n")
        fm = _parse_frontmatter(md)
        assert fm["cites_files"] == ["src/a.py", "src/b.py"]

    def test_empty_list(self):
        md = self._make_md("impacts: []\n")
        fm = _parse_frontmatter(md)
        assert fm["impacts"] == []

    def test_nested_object_ast_pointer(self):
        md = self._make_md(
            "ast_pointer:\n"
            "  file_path: src/foo.py\n"
            "  class_name: MyService\n"
            "  drift: false\n"
        )
        fm = _parse_frontmatter(md)
        assert isinstance(fm["ast_pointer"], dict)
        assert fm["ast_pointer"]["file_path"] == "src/foo.py"
        assert fm["ast_pointer"]["class_name"] == "MyService"
        assert fm["ast_pointer"]["drift"] is False

    def test_nested_object_provenance(self):
        md = self._make_md(
            "provenance:\n"
            "  trigger_type: bootstrap_v2\n"
            "  generated_at: 2026-05-01\n"
            "  layer_confidence: 0.85\n"
        )
        fm = _parse_frontmatter(md)
        assert isinstance(fm["provenance"], dict)
        assert fm["provenance"]["trigger_type"] == "bootstrap_v2"
        assert abs(float(fm["provenance"]["layer_confidence"]) - 0.85) < 0.001

    def test_boolean_casting(self):
        md = self._make_md("drift: true\nactive: false\n")
        fm = _parse_frontmatter(md)
        assert fm["drift"] is True
        assert fm["active"] is False

    def test_integer_casting(self):
        md = self._make_md("version: 3\n")
        fm = _parse_frontmatter(md)
        assert fm["version"] == 3
        assert isinstance(fm["version"], int)

    def test_float_casting(self):
        md = self._make_md("score: 0.75\n")
        fm = _parse_frontmatter(md)
        assert abs(float(fm["score"]) - 0.75) < 0.001

    def test_missing_frontmatter_returns_empty(self):
        md = "No frontmatter here"
        assert _parse_frontmatter(md) == {}

    def test_comment_stripped_from_scalar(self):
        md = self._make_md("layer: CC  # 横切关注点\n")
        fm = _parse_frontmatter(md)
        assert fm["layer"] == "CC"

    def test_full_memory_node_format(self):
        """模拟真实记忆文件格式的完整解析。"""
        md = self._make_md(textwrap.dedent("""\
            id: PAT-TEST-001
            type: pattern
            layer: L4_application
            dimension: architecture
            source_ep: EP-999
            tier: warm
            tags: [service, application, domain]
            cites_files:
              - src/app/services/auth_service.py
            about_concepts: [auth, service]
            impacts: []
            derived_from: []
            ast_pointer:
              file_path: src/app/services/auth_service.py
              class_name: AuthService
              fingerprint: abc123
              drift: false
            provenance:
              trigger_type: bootstrap_v2
              generated_at: 2026-05-01
              layer_confidence: 0.90
            version: 1
            created_at: 2026-05-01
        """))
        fm = _parse_frontmatter(md)
        assert fm["id"] == "PAT-TEST-001"
        assert fm["layer"] == "L4_application"
        assert fm["tags"] == ["service", "application", "domain"]
        assert fm["cites_files"] == ["src/app/services/auth_service.py"]
        assert fm["ast_pointer"]["class_name"] == "AuthService"
        assert fm["ast_pointer"]["drift"] is False
        assert abs(float(fm["provenance"]["layer_confidence"]) - 0.90) < 0.001


# ────────────────────────────────────────────────────────────────────────────
# 2. MemoryVizCollector.collect 集成测试（临时目录）
# ────────────────────────────────────────────────────────────────────────────

def _write_node(mem_root: Path, node_id: str, layer: str, tier: str,
                ast_file: str = "", ast_class: str = "",
                related_to: list | None = None,
                impacts: list | None = None) -> Path:
    """在 mem_root 下写入一个最小化的记忆文件。"""
    subdir = mem_root / "shared" / layer
    subdir.mkdir(parents=True, exist_ok=True)

    ast_block = ""
    if ast_file:
        ast_block = (
            f"ast_pointer:\n"
            f"  file_path: {ast_file}\n"
            f"  class_name: {ast_class}\n"
            f"  drift: false\n"
            f"provenance:\n"
            f"  trigger_type: bootstrap_v2\n"
            f"  generated_at: 2026-05-01\n"
            f"  layer_confidence: 0.80\n"
        )

    related_block = ""
    if related_to:
        related_block = "related_to:\n" + "".join(f"  - {r}\n" for r in related_to)

    impacts_block = ""
    if impacts:
        impacts_block = "impacts:\n" + "".join(f"  - {i}\n" for i in impacts)

    content = (
        f"---\n"
        f"id: {node_id}\n"
        f"type: pattern\n"
        f"layer: {layer}\n"
        f"tier: {tier}\n"
        f"tags: [test]\n"
        f"{ast_block}"
        f"{related_block}"
        f"{impacts_block}"
        f"---\n"
        f"# {node_id} — test node\n"
    )
    path = subdir / f"{node_id}.md"
    path.write_text(content, encoding="utf-8")
    return path


class TestMemoryVizCollector:

    def test_collect_empty_directory(self, tmp_path):
        mem_root = tmp_path / "memory"
        mem_root.mkdir()
        collector = MemoryVizCollector(memory_root=mem_root, project_root=tmp_path)
        data = collector.collect()
        assert data.nodes == []
        assert data.edges == []
        assert data.ast_mappings == []
        assert data.stats["total_nodes"] == 0

    def test_collect_single_node(self, tmp_path):
        mem_root = tmp_path / "memory"
        _write_node(mem_root, "MEM-L-001", "L4_application", "warm",
                    ast_file="src/app/services/auth.py", ast_class="AuthService")
        collector = MemoryVizCollector(memory_root=mem_root, project_root=tmp_path)
        data = collector.collect(project_name="test-project")

        assert len(data.nodes) == 1
        n = data.nodes[0]
        assert n.id == "MEM-L-001"
        assert n.layer == "L4_application"
        assert n.tier == "warm"
        assert n.ast_file == "src/app/services/auth.py"
        assert n.ast_class == "AuthService"
        assert n.ast_drift is False
        assert abs(n.layer_confidence - 0.80) < 0.01

    def test_collect_ast_mappings(self, tmp_path):
        mem_root = tmp_path / "memory"
        _write_node(mem_root, "MEM-L-002", "L3_domain", "hot",
                    ast_file="src/domain/order.py", ast_class="OrderAggregate")
        collector = MemoryVizCollector(memory_root=mem_root, project_root=tmp_path)
        data = collector.collect()

        assert len(data.ast_mappings) == 1
        m = data.ast_mappings[0]
        assert m.source_file == "src/domain/order.py"
        assert m.class_name == "OrderAggregate"
        assert m.memory_id == "MEM-L-002"
        assert m.layer == "L3_domain"

    def test_collect_related_to_edges(self, tmp_path):
        mem_root = tmp_path / "memory"
        _write_node(mem_root, "A-001", "CC", "hot", related_to=["A-002"])
        _write_node(mem_root, "A-002", "CC", "warm")
        collector = MemoryVizCollector(memory_root=mem_root, project_root=tmp_path)
        data = collector.collect()

        assert len(data.edges) == 1
        e = data.edges[0]
        assert e.source == "A-001"
        assert e.target == "A-002"
        assert e.relation == "related_to"

    def test_collect_impacts_edges(self, tmp_path):
        mem_root = tmp_path / "memory"
        _write_node(mem_root, "X-001", "L1_platform", "hot", impacts=["X-002"])
        _write_node(mem_root, "X-002", "L1_platform", "warm")
        collector = MemoryVizCollector(memory_root=mem_root, project_root=tmp_path)
        data = collector.collect()

        impact_edges = [e for e in data.edges if e.relation == "impacts"]
        assert len(impact_edges) == 1
        assert impact_edges[0].source == "X-001"
        assert impact_edges[0].target == "X-002"

    def test_system_dir_excluded(self, tmp_path):
        mem_root = tmp_path / "memory"
        # 在 _system 目录下写文件，不应被收集
        sys_dir = mem_root / "_system" / "shared"
        sys_dir.mkdir(parents=True)
        sys_file = sys_dir / "SYS-001.md"
        sys_file.write_text("---\nid: SYS-001\nlayer: CC\ntier: warm\n---\n# sys\n")

        # 在正常目录下写文件
        _write_node(mem_root, "MEM-001", "CC", "warm")

        collector = MemoryVizCollector(memory_root=mem_root, project_root=tmp_path)
        data = collector.collect()

        ids = {n.id for n in data.nodes}
        assert "SYS-001" not in ids
        assert "MEM-001" in ids

    def test_duplicate_ids_deduplicated(self, tmp_path):
        mem_root = tmp_path / "memory"
        # 写两个同 id 的文件
        _write_node(mem_root, "DUP-001", "CC", "warm")
        # 手动写一个同 id 的文件到另一个子目录
        alt_dir = mem_root / "shared" / "L3_domain"
        alt_dir.mkdir(parents=True, exist_ok=True)
        (alt_dir / "DUP-001.md").write_text("---\nid: DUP-001\nlayer: L3_domain\ntier: hot\n---\n")

        collector = MemoryVizCollector(memory_root=mem_root, project_root=tmp_path)
        data = collector.collect()
        assert sum(1 for n in data.nodes if n.id == "DUP-001") == 1

    def test_stats_structure(self, tmp_path):
        mem_root = tmp_path / "memory"
        _write_node(mem_root, "S-001", "CC", "hot",
                    ast_file="src/foo.py", ast_class="Foo")
        _write_node(mem_root, "S-002", "L4_application", "warm")
        collector = MemoryVizCollector(memory_root=mem_root, project_root=tmp_path)
        data = collector.collect()

        stats = data.stats
        assert stats["total_nodes"] == 2
        assert "CC" in stats["layer_distribution"]
        assert "hot" in stats["tier_distribution"]
        assert stats["has_ast_count"] == 1
        assert stats["total_ast_mappings"] == 1

    def test_collect_on_real_memory_root(self):
        """对真实项目 docs/memory 目录运行，验证基本结构完整性。"""
        project_root = Path(__file__).parent.parent
        memory_root = project_root / "docs" / "memory"
        if not memory_root.exists():
            pytest.skip("docs/memory 目录不存在，跳过真实目录测试")

        collector = MemoryVizCollector(memory_root=memory_root, project_root=project_root)
        data = collector.collect(project_name="mms")

        assert data.stats["total_nodes"] >= 0
        assert data.project_name == "mms"
        assert data.memory_root == str(memory_root)
        # 每个节点都有 id、layer、tier
        for n in data.nodes:
            assert n.id
            assert n.layer
            assert n.tier


# ────────────────────────────────────────────────────────────────────────────
# 3. html_renderer 单元测试
# ────────────────────────────────────────────────────────────────────────────

def _make_minimal_viz_data() -> VizData:
    nodes = [
        NodeData(
            id="MEM-001", label="AuthService", layer="L4_application", tier="warm",
            node_type="pattern", tags=["auth"], file_path="docs/memory/shared/L4/MEM-001.md",
            title="ID: MEM-001\nLayer: L4_application\nTier: warm",
            ast_file="src/app/auth.py", ast_class="AuthService",
            ast_drift=False, layer_confidence=0.85, about_concepts=["auth"],
        ),
        NodeData(
            id="AD-001", label="AD-001", layer="CC", tier="hot",
            node_type="decision", tags=["architecture"], file_path="docs/memory/shared/CC/AD-001.md",
            title="ID: AD-001\nLayer: CC\nTier: hot",
            ast_file="", ast_class="",
            ast_drift=False, layer_confidence=0.0, about_concepts=[],
        ),
    ]
    from mms.diagnostics.memory_viz import EdgeData
    edges = [EdgeData(source="MEM-001", target="AD-001", relation="related_to", label="related")]
    mappings = [AstMapping(
        source_file="src/app/auth.py", class_name="AuthService",
        memory_id="MEM-001", layer="L4_application", tier="warm",
        drift=False, confidence=0.85,
    )]
    stats = {
        "total_nodes": 2, "total_edges": 1, "total_ast_mappings": 1,
        "drift_count": 0, "has_ast_count": 1,
        "layer_distribution": {"L4_application": 1, "CC": 1},
        "tier_distribution": {"warm": 1, "hot": 1},
        "type_distribution": {"pattern": 1, "decision": 1},
    }
    return VizData(
        nodes=nodes, edges=edges, ast_mappings=mappings,
        stats=stats, project_name="test-project",
        memory_root="/tmp/memory",
    )


class TestHtmlRenderer:

    def test_render_returns_string(self):
        data = _make_minimal_viz_data()
        html = render_html(data)
        assert isinstance(html, str)
        assert len(html) > 1000

    def test_render_is_valid_html(self):
        data = _make_minimal_viz_data()
        html = render_html(data)
        assert html.strip().startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_render_contains_vis_network(self):
        data = _make_minimal_viz_data()
        html = render_html(data)
        assert "vis-network" in html

    def test_render_contains_node_data(self):
        data = _make_minimal_viz_data()
        html = render_html(data)
        # nodes JSON 应包含节点 id
        assert "MEM-001" in html
        assert "AD-001" in html

    def test_render_contains_three_tabs(self):
        data = _make_minimal_viz_data()
        html = render_html(data)
        assert "记忆图谱" in html
        assert "AST 文件视图" in html
        assert "AST↔记忆映射" in html

    def test_render_contains_stats(self):
        data = _make_minimal_viz_data()
        html = render_html(data)
        # 统计数字
        assert "2" in html  # total_nodes
        assert "test-project" in html

    def test_render_contains_ast_tree(self):
        data = _make_minimal_viz_data()
        html = render_html(data)
        # AST tree 应包含源码文件路径
        assert "src/app/auth.py" in html
        assert "AuthService" in html

    def test_render_contains_mapping_table(self):
        data = _make_minimal_viz_data()
        html = render_html(data)
        # 映射表应包含内存 ID
        assert "MEM-001" in html

    def test_render_custom_title(self):
        data = _make_minimal_viz_data()
        html = render_html(data, title="My Custom Title")
        assert "My Custom Title" in html

    def test_render_no_nodes(self):
        data = _make_minimal_viz_data()
        data.nodes = []
        data.edges = []
        data.ast_mappings = []
        data.stats["total_nodes"] = 0
        html = render_html(data)
        assert "<!DOCTYPE html>" in html
        assert "暂无 AST 指针数据" in html

    def test_render_drift_warning(self):
        data = _make_minimal_viz_data()
        data.nodes[0].ast_drift = True
        data.nodes[0].title += "\nDrift: ⚠️ YES"
        data.stats["drift_count"] = 1
        html = render_html(data)
        assert "drift" in html.lower()

    def test_node_to_vis_structure(self):
        n = _make_minimal_viz_data().nodes[0]
        vis = _node_to_vis(n)
        assert vis["id"] == "MEM-001"
        assert "color" in vis
        assert "background" in vis["color"]
        assert vis["layer"] == "L4_application"
        assert vis["tier"] == "warm"

    def test_edge_to_vis_structure(self):
        from mms.diagnostics.memory_viz import EdgeData
        e = EdgeData(source="A", target="B", relation="impacts", label="impacts")
        vis = _edge_to_vis(e, 0)
        assert vis["from"] == "A"
        assert vis["to"] == "B"
        assert vis["arrows"] == "to"

    def test_html_nodes_json_is_valid(self):
        """验证嵌入的 nodes JSON 可被解析。"""
        import re as _re
        data = _make_minimal_viz_data()
        html = render_html(data)
        m = _re.search(r"const ALL_NODES = (\[.*?\]);", html, _re.DOTALL)
        assert m, "ALL_NODES JSON not found in HTML"
        parsed = json.loads(m.group(1))
        assert len(parsed) == 2
        ids = {n["id"] for n in parsed}
        assert "MEM-001" in ids
        assert "AD-001" in ids


# ────────────────────────────────────────────────────────────────────────────
# 4. CLI E2E 测试
# ────────────────────────────────────────────────────────────────────────────

class TestCLI:

    def _run_cli(self, *args, **kwargs):
        """运行 visualize_memory.py CLI，返回 CompletedProcess。"""
        project_root = Path(__file__).parent.parent
        script = project_root / "scripts" / "visualize_memory.py"
        return subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True, text=True, **kwargs
        )

    def test_cli_runs_successfully(self, tmp_path):
        output_file = tmp_path / "out.html"
        result = self._run_cli("-o", str(output_file))
        assert result.returncode == 0, result.stderr
        assert output_file.exists()

    def test_cli_output_is_html(self, tmp_path):
        output_file = tmp_path / "out.html"
        self._run_cli("-o", str(output_file))
        content = output_file.read_text(encoding="utf-8")
        assert content.startswith("<!DOCTYPE html>")
        assert "vis-network" in content

    def test_cli_custom_output_path(self, tmp_path):
        output_file = tmp_path / "custom_name.html"
        result = self._run_cli("-o", str(output_file))
        assert result.returncode == 0
        assert output_file.exists()

    def test_cli_custom_project_name(self, tmp_path):
        output_file = tmp_path / "out.html"
        result = self._run_cli("-o", str(output_file), "--project", "TestProj")
        assert result.returncode == 0
        content = output_file.read_text(encoding="utf-8")
        assert "TestProj" in content

    def test_cli_invalid_memory_root(self, tmp_path):
        output_file = tmp_path / "out.html"
        result = self._run_cli(
            "-o", str(output_file),
            "--memory-root", str(tmp_path / "nonexistent"),
        )
        assert result.returncode != 0
        assert "不存在" in result.stderr or "not found" in result.stderr.lower()

    def test_cli_stdout_contains_summary(self, tmp_path):
        output_file = tmp_path / "out.html"
        result = self._run_cli("-o", str(output_file))
        assert "✅ 收集完成" in result.stdout
        assert "节点" in result.stdout
        assert "已生成" in result.stdout
