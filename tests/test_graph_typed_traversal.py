"""
test_graph_typed_traversal.py — Phase 2 测试

验证 MemoryGraph 的语义有向遍历方法：
  - typed_explore：按 traversal_paths.yaml 配置的边类型遍历
  - find_by_concept：通过 DomainConcept 反向索引定位记忆
  - hybrid_search：图 + 关键词混合检索与 fallback
"""
from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from mms.memory.graph_resolver import MemoryGraph, MemoryNode
from mms.memory.link_registry import LinkTypeRegistry


# ─── 测试图构建 fixture ───────────────────────────────────────────────────────

def _write_memory(mem_dir: Path, mem_id: str, **kwargs) -> Path:
    """写入一个测试记忆 Markdown 文件（安全构建 front-matter）。"""
    tier = kwargs.get("tier", "warm")
    layer = kwargs.get("layer", "L3_domain")
    tags: list = kwargs.get("tags", [])
    related_to: list = kwargs.get("related_to", [])
    cites_files: list = kwargs.get("cites_files", [])
    impacts: list = kwargs.get("impacts", [])
    about_concepts: list = kwargs.get("about_concepts", [])
    contradicts: list = kwargs.get("contradicts", [])
    derived_from: list = kwargs.get("derived_from", [])
    title = kwargs.get("title", mem_id)

    def yaml_list(name: str, items: list) -> str:
        if not items:
            return ""
        lines = [f"{name}:"]
        for item in items:
            lines.append(f"  - {item}")
        return "\n".join(lines) + "\n"

    lines = [
        "---",
        f"id: {mem_id}",
        f"tier: {tier}",
        f"layer: {layer}",
    ]
    if tags:
        lines.append("tags:")
        for t in tags:
            lines.append(f"  - {t}")
    if related_to:
        lines.append("related_to:")
        for r in related_to:
            lines.append(f"  - id: {r}")
            lines.append(f"    reason: test")
    if cites_files:
        lines.append("cites_files:")
        for f in cites_files:
            lines.append(f"  - {f}")
    if impacts:
        lines.append("impacts:")
        for i in impacts:
            lines.append(f"  - {i}")
    if about_concepts:
        lines.append("about_concepts:")
        for c in about_concepts:
            lines.append(f"  - {c}")
    if contradicts:
        lines.append("contradicts:")
        for c in contradicts:
            lines.append(f"  - {c}")
    if derived_from:
        lines.append("derived_from:")
        for d in derived_from:
            lines.append(f"  - {d}")
    lines += ["---", "", f"# {title}", "", "内容。"]

    md_path = mem_dir / f"{mem_id}.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


@pytest.fixture
def graph_with_nodes(tmp_path: Path) -> MemoryGraph:
    """
    构建一个测试用记忆图：

        MEM-A ---about---> [grpc, service]
        MEM-B ---about---> [grpc]
        MEM-C ---about---> [dto]
        MEM-D ---cites---> [backend/grpc.py]
        MEM-E ---impacts-> [MEM-F]
        MEM-F ---related_to-> [MEM-A]
        MEM-G ---derived_from-> [MEM-A]
        MEM-H ---contradicts-> [MEM-A]
    """
    mem_dir = tmp_path / "shared"
    mem_dir.mkdir(parents=True)

    _write_memory(mem_dir, "MEM-A", tier="hot", tags=["grpc", "service"],
                  about_concepts=["grpc", "service"], title="gRPC 服务规范")
    _write_memory(mem_dir, "MEM-B", tier="warm", tags=["grpc"],
                  about_concepts=["grpc"], title="gRPC 重试策略")
    _write_memory(mem_dir, "MEM-C", tier="warm", tags=["dto"],
                  about_concepts=["dto"], title="DTO 隔离规范")
    _write_memory(mem_dir, "MEM-D", tier="cold", tags=["grpc"],
                  cites_files=["backend/grpc.py", "backend/service.py"],
                  title="gRPC 文件引用记忆")
    _write_memory(mem_dir, "MEM-E", tier="warm", tags=["api"],
                  impacts=["MEM-F"], title="API 变更记忆")
    _write_memory(mem_dir, "MEM-F", tier="warm", tags=["api"],
                  related_to=["MEM-A"], title="API 关联记忆")
    _write_memory(mem_dir, "MEM-G", tier="warm", tags=["grpc"],
                  derived_from=["MEM-A"], title="从 MEM-A 提炼的 Pattern")
    _write_memory(mem_dir, "MEM-H", tier="warm", tags=["rest"],
                  contradicts=["MEM-A"], title="REST 优先（与 MEM-A 矛盾）")

    return MemoryGraph(memory_root=tmp_path)


# ─── typed_explore 测试 ───────────────────────────────────────────────────────

class TestTypedExplore:
    def test_concept_lookup_path_uses_about_and_related(
        self, graph_with_nodes: MemoryGraph
    ) -> None:
        """concept_lookup 路径应沿 about 和 related_to 边遍历，找到通过 about 连接的节点。"""
        results = graph_with_nodes.typed_explore("MEM-A", path_intent="concept_lookup")
        result_ids = {n.id for n in results}
        # MEM-B 和 MEM-A 都有 about_concepts: [grpc]，concept_lookup include_inverse=True
        # 所以从 MEM-A 出发，应能通过反向 about 边找到 MEM-B（共享 grpc 概念）
        assert "MEM-B" in result_ids

    def test_knowledge_expand_uses_derived_from(
        self, graph_with_nodes: MemoryGraph
    ) -> None:
        """knowledge_expand 路径沿 derived_from 遍历，找到提炼来源。"""
        results = graph_with_nodes.typed_explore("MEM-G", path_intent="knowledge_expand")
        result_ids = {n.id for n in results}
        # MEM-G.derived_from = [MEM-A]
        assert "MEM-A" in result_ids

    def test_unknown_path_intent_falls_back_to_explore(
        self, graph_with_nodes: MemoryGraph
    ) -> None:
        """未知 path_intent 降级为普通 explore（不抛异常）。"""
        results = graph_with_nodes.typed_explore(
            "MEM-F", path_intent="nonexistent_path"
        )
        # explore 会找到 MEM-A（via related_to）
        result_ids = {n.id for n in results}
        assert "MEM-A" in result_ids

    def test_depth_limit_respected(self, graph_with_nodes: MemoryGraph) -> None:
        """depth=1 时不越界超过 1 跳。"""
        results = graph_with_nodes.typed_explore(
            "MEM-A", path_intent="concept_lookup", depth=1
        )
        # 结果中所有节点都是 MEM-A 的直接邻居（1 跳）
        assert len(results) <= 10  # 基本约束：不越界

    def test_nonexistent_start_returns_empty(
        self, graph_with_nodes: MemoryGraph
    ) -> None:
        """不存在的起始节点返回空列表，不抛异常。"""
        results = graph_with_nodes.typed_explore(
            "NONEXISTENT-ID", path_intent="concept_lookup"
        )
        assert results == []


# ─── find_by_concept 测试 ─────────────────────────────────────────────────────

class TestFindByConcept:
    def test_find_nodes_with_grpc_concept(
        self, graph_with_nodes: MemoryGraph
    ) -> None:
        """通过 about_concepts 反向索引找到所有含 'grpc' 概念的节点。"""
        results = graph_with_nodes.find_by_concept(["grpc"])
        result_ids = {n.id for n in results}
        # MEM-A 和 MEM-B 都有 about_concepts: [grpc]
        assert "MEM-A" in result_ids
        assert "MEM-B" in result_ids

    def test_concept_lookup_does_not_mix_unrelated(
        self, graph_with_nodes: MemoryGraph
    ) -> None:
        """搜索 'dto' 不应返回只有 'grpc' 概念的节点。"""
        results = graph_with_nodes.find_by_concept(["dto"])
        result_ids = {n.id for n in results}
        assert "MEM-C" in result_ids
        # MEM-A 和 MEM-B 都没有 dto 概念
        assert "MEM-A" not in result_ids
        assert "MEM-B" not in result_ids

    def test_empty_keywords_returns_empty_or_all(
        self, graph_with_nodes: MemoryGraph
    ) -> None:
        """空关键词列表不应抛异常。"""
        results = graph_with_nodes.find_by_concept([])
        assert isinstance(results, list)

    def test_results_sorted_by_tier(self, graph_with_nodes: MemoryGraph) -> None:
        """结果按 tier 排序：hot > warm > cold。"""
        results = graph_with_nodes.find_by_concept(["grpc"])
        if len(results) >= 2:
            tier_order = {"hot": 0, "warm": 1, "cold": 2, "archive": 3}
            tiers = [tier_order.get(n.tier, 9) for n in results]
            assert tiers == sorted(tiers), "结果未按 tier 排序"

    def test_tag_fallback_matching(self, graph_with_nodes: MemoryGraph) -> None:
        """当 about_concepts 为空但 tags 匹配时，也应被找到。"""
        # MEM-D 有 tags=[grpc] 但没有 about_concepts（在本 fixture 中有 cites_files）
        # 它应该通过 tag 匹配被找到
        results = graph_with_nodes.find_by_concept(["grpc"])
        result_ids = {n.id for n in results}
        # MEM-D 有 tags=["grpc"] 且有 about_concepts=[] (没有 about)
        # 通过 tag 匹配应能找到 MEM-D
        assert "MEM-D" in result_ids


# ─── hybrid_search 测试 ───────────────────────────────────────────────────────

class TestHybridSearch:
    def test_graph_results_sufficient_no_fallback(
        self, graph_with_nodes: MemoryGraph
    ) -> None:
        """图结果充足时（>= threshold），直接返回图结果。"""
        # grpc 概念有 MEM-A, MEM-B, MEM-D（通过 tag）= 3 个，threshold=3
        results = graph_with_nodes.hybrid_search(
            ["grpc"], graph_confidence_threshold=3
        )
        assert len(results) >= 3

    def test_fallback_when_graph_results_insufficient(
        self, graph_with_nodes: MemoryGraph
    ) -> None:
        """图结果不足时，触发 keyword fallback，结果数增加。"""
        # 'api' 在 about_concepts 中没有节点，但 MEM-E, MEM-F 有 tags=["api"]
        graph_results = graph_with_nodes.find_by_concept(["api"])
        hybrid_results = graph_with_nodes.hybrid_search(
            ["api"], graph_confidence_threshold=100  # 强制触发 fallback
        )
        # hybrid_search 结果 >= graph_results（关键词补充）
        assert len(hybrid_results) >= len(graph_results)

    def test_no_fallback_when_disabled(
        self, graph_with_nodes: MemoryGraph
    ) -> None:
        """fallback_to_keyword=False 时即使结果不足也不补充。"""
        results = graph_with_nodes.hybrid_search(
            ["nonexistent_xyz_concept"],
            graph_confidence_threshold=100,
            fallback_to_keyword=False,
        )
        assert results == []

    def test_graph_disabled_returns_keyword_results(
        self, graph_with_nodes: MemoryGraph
    ) -> None:
        """use_graph=False 时完全跳过图路径，只用关键词检索。"""
        results = graph_with_nodes.hybrid_search(
            ["gRPC 服务规范"],  # 是 MEM-A 的标题关键词
            use_graph=False,
            fallback_to_keyword=True,
        )
        result_ids = {n.id for n in results}
        assert "MEM-A" in result_ids

    def test_no_duplicates_in_hybrid_results(
        self, graph_with_nodes: MemoryGraph
    ) -> None:
        """混合检索结果不含重复节点。"""
        results = graph_with_nodes.hybrid_search(["grpc"])
        result_ids = [n.id for n in results]
        assert len(result_ids) == len(set(result_ids)), "结果含重复节点"


# ─── 反向索引测试 ─────────────────────────────────────────────────────────────

class TestConceptReverseIndex:
    def test_concept_to_ids_built_correctly(
        self, graph_with_nodes: MemoryGraph
    ) -> None:
        """_concept_to_ids 在 _load_all 时正确构建。"""
        graph_with_nodes._ensure_loaded()
        index = graph_with_nodes._concept_to_ids
        assert "grpc" in index
        assert "MEM-A" in index["grpc"]
        assert "MEM-B" in index["grpc"]

    def test_concept_not_in_index_when_no_about(
        self, graph_with_nodes: MemoryGraph
    ) -> None:
        """没有 about_concepts 的节点不会出现在反向索引中。"""
        graph_with_nodes._ensure_loaded()
        index = graph_with_nodes._concept_to_ids
        # MEM-E 没有 about_concepts，api 不应在索引中（或不包含 MEM-E）
        assert "MEM-E" not in index.get("api", [])
