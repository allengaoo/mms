"""
test_link_registry.py — Phase 1 测试

验证 LinkTypeRegistry 和 TraversalPathDef 的 YAML 驱动加载功能。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from mms.memory.link_registry import (
    LinkTypeDef,
    LinkTypeRegistry,
    TraversalPathDef,
    get_registry,
)


# ─── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_registry(tmp_path: Path) -> LinkTypeRegistry:
    """使用临时目录创建隔离的 Registry 实例。"""
    links_dir = tmp_path / "links"
    links_dir.mkdir()
    config_dir = tmp_path / "_config"
    config_dir.mkdir()

    # 创建两个 LinkType YAML
    (links_dir / "cites.yaml").write_text(
        """
id: link_cites
label: "引用代码文件"
source_type: MemoryNode
target_type: CodeFile
cardinality: M:N
inverse: cited_by
storage:
  field_name: cites_files
  field_type: list[string]
auto_population:
  trigger: action_distill
  method: regex_extract_file_paths
""",
        encoding="utf-8",
    )

    (links_dir / "about.yaml").write_text(
        """
id: link_about
label: "描述领域概念"
source_type: MemoryNode
target_type: DomainConcept
cardinality: M:N
inverse: cited_by_memories
storage:
  field_name: about_concepts
auto_population:
  trigger: action_distill
  method: keyword_match_from_layers_yaml
""",
        encoding="utf-8",
    )

    # 创建遍历路径配置
    traversal_file = config_dir / "traversal_paths.yaml"
    traversal_file.write_text(
        """
version: "1.0"

paths:
  concept_lookup:
    label: "查找某概念相关知识"
    edge_types: [about, related_to]
    max_depth: 2
    include_inverse: true
    min_results: 3

  code_change_impact:
    label: "代码变更时找受影响记忆"
    edge_types: [cites, impacts]
    max_depth: 1
    include_inverse: false
    min_results: 0

  knowledge_expand:
    label: "扩展相关知识"
    edge_types: [related_to, derived_from]
    max_depth: 2
    include_inverse: true
    min_results: 2
""",
        encoding="utf-8",
    )

    return LinkTypeRegistry(links_dir=links_dir, traversal_file=traversal_file)


# ─── 加载测试 ─────────────────────────────────────────────────────────────────

class TestLinkRegistryLoad:
    def test_load_known_link_types(self, tmp_registry: LinkTypeRegistry) -> None:
        """加载 links/*.yaml 无错误，且能检索到已知 LinkType。"""
        link = tmp_registry.get("link_cites")
        assert link is not None
        assert link.id == "link_cites"
        assert link.label == "引用代码文件"
        assert link.source_type == "MemoryNode"
        assert link.target_type == "CodeFile"
        assert link.cardinality == "M:N"
        assert link.inverse == "cited_by"

    def test_storage_field_as_alias(self, tmp_registry: LinkTypeRegistry) -> None:
        """storage_field 名（如 cites_files）也可作为查询 key。"""
        link = tmp_registry.get("cites_files")
        assert link is not None
        assert link.id == "link_cites"

    def test_all_returns_unique_link_defs(self, tmp_registry: LinkTypeRegistry) -> None:
        """all() 返回不重复的 LinkType 列表。"""
        links = tmp_registry.all()
        ids = [l.id for l in links]
        assert "link_cites" in ids
        assert "link_about" in ids
        assert len(ids) == len(set(ids)), "all() 不应返回重复条目"

    def test_unknown_link_id_returns_none(self, tmp_registry: LinkTypeRegistry) -> None:
        """未知 link_id 返回 None，不抛异常。"""
        result = tmp_registry.get("nonexistent_link")
        assert result is None

    def test_auto_populate_detection(self, tmp_registry: LinkTypeRegistry) -> None:
        """auto_population.trigger 存在时，auto_populate 为 True。"""
        link = tmp_registry.get("link_cites")
        assert link is not None
        assert link.auto_populate is True

    def test_storage_field_parsed(self, tmp_registry: LinkTypeRegistry) -> None:
        """storage.field_name 被正确解析为 storage_field 属性。"""
        link = tmp_registry.get("link_about")
        assert link is not None
        assert link.storage_field == "about_concepts"


# ─── 遍历路径测试 ─────────────────────────────────────────────────────────────

class TestTraversalPaths:
    def test_traversal_path_concept_lookup(self, tmp_registry: LinkTypeRegistry) -> None:
        """concept_lookup 路径包含正确的边类型序列。"""
        edges = tmp_registry.traversal_path("concept_lookup")
        assert edges == ["about", "related_to"]

    def test_traversal_path_code_change_impact(self, tmp_registry: LinkTypeRegistry) -> None:
        """code_change_impact 路径只包含 cites 和 impacts。"""
        edges = tmp_registry.traversal_path("code_change_impact")
        assert edges == ["cites", "impacts"]

    def test_unknown_intent_returns_empty(self, tmp_registry: LinkTypeRegistry) -> None:
        """未知 intent 返回空列表，不抛异常。"""
        edges = tmp_registry.traversal_path("nonexistent_intent")
        assert edges == []

    def test_traversal_path_def_max_depth(self, tmp_registry: LinkTypeRegistry) -> None:
        """TraversalPathDef 正确解析 max_depth 和 include_inverse。"""
        path = tmp_registry.traversal_path_def("concept_lookup")
        assert path is not None
        assert path.max_depth == 2
        assert path.include_inverse is True
        assert path.min_results == 3

    def test_traversal_path_def_no_inverse(self, tmp_registry: LinkTypeRegistry) -> None:
        """code_change_impact 不包含反向边。"""
        path = tmp_registry.traversal_path_def("code_change_impact")
        assert path is not None
        assert path.include_inverse is False
        assert path.min_results == 0

    def test_all_path_ids(self, tmp_registry: LinkTypeRegistry) -> None:
        """all_path_ids() 返回所有已注册的路径 ID。"""
        ids = tmp_registry.all_path_ids()
        assert "concept_lookup" in ids
        assert "code_change_impact" in ids
        assert "knowledge_expand" in ids


# ─── 扩展性验证 ───────────────────────────────────────────────────────────────

class TestExtensibility:
    def test_new_yaml_file_auto_loaded(self, tmp_registry: LinkTypeRegistry) -> None:
        """新增 YAML 文件后，重新加载时自动被识别（扩展性验证）。"""
        # 在 links 目录新增一个 impacts.yaml
        impacts_yaml = tmp_registry._links_dir / "impacts.yaml"
        impacts_yaml.write_text(
            """
id: link_impacts
label: "影响关系"
source_type: MemoryNode
target_type: MemoryNode
cardinality: M:N
inverse: impacted_by
storage:
  field_name: impacts
""",
            encoding="utf-8",
        )

        # 重新创建 Registry（模拟重启加载）
        new_registry = LinkTypeRegistry(
            links_dir=tmp_registry._links_dir,
            traversal_file=tmp_registry._traversal_file,
        )
        link = new_registry.get("link_impacts")
        assert link is not None
        assert link.id == "link_impacts"

    def test_new_traversal_path_auto_loaded(self, tmp_registry: LinkTypeRegistry) -> None:
        """在 traversal_paths.yaml 新增路径后，新实例自动加载。"""
        # 读取现有内容并追加新路径
        existing = tmp_registry._traversal_file.read_text()
        existing += """
  contradiction_check:
    label: "矛盾检测"
    edge_types: [contradicts]
    max_depth: 1
    include_inverse: true
    min_results: 0
"""
        tmp_registry._traversal_file.write_text(existing)

        new_registry = LinkTypeRegistry(
            links_dir=tmp_registry._links_dir,
            traversal_file=tmp_registry._traversal_file,
        )
        edges = new_registry.traversal_path("contradiction_check")
        assert edges == ["contradicts"]


# ─── 生产环境目录加载测试 ─────────────────────────────────────────────────────

class TestProductionRegistry:
    def test_default_registry_loads_without_error(self) -> None:
        """默认 Registry 加载项目 links/ 目录无异常。"""
        registry = get_registry()
        # 可能没有磁盘文件时，all() 返回空列表（不抛异常）
        links = registry.all()
        assert isinstance(links, list)

    def test_production_links_dir_has_link_defs(self) -> None:
        """生产环境 links/ 目录包含预期的 5 个 LinkType 定义。"""
        registry = LinkTypeRegistry()
        links = registry.all()
        ids = {l.id for l in links}
        for expected_id in ["link_cites", "link_about", "link_impacts",
                            "link_contradicts", "link_derived_from"]:
            assert expected_id in ids, f"缺少 LinkType: {expected_id}"

    def test_production_traversal_paths_loaded(self) -> None:
        """生产环境 traversal_paths.yaml 包含核心路径。"""
        registry = LinkTypeRegistry()
        path_ids = registry.all_path_ids()
        for expected in ["concept_lookup", "code_change_impact", "knowledge_expand"]:
            assert expected in path_ids, f"缺少遍历路径: {expected}"
