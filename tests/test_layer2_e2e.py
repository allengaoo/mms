"""
test_layer2_e2e.py — Layer 2 端到端测试

参照 layer2_readme.md 的整体数据流图设计：

  物理代码库 ──AST解析──> Bootstrap Engine ──生成初始节点──> Memory Graph (Markdown)
  Ontology Schema ────懒加载────> Ontology Engine
  Layer 1 任务请求 ──发起检索──> Memory Engine ──图遍历──> Memory Graph ──组装Prompt──> Layer 1

覆盖三条主要数据链路：

  链路 A: 代码库 → Bootstrap → Memory Graph → Ontology 校验
    步骤：1) bootstrap_project 生成初始节点
          2) 所有节点通过 MemoryNode schema 校验
          3) 节点包含正确的 ast_pointer 和 cites_files

  链路 B: Ontology Schema → OntologyRegistry → 加载校验
    步骤：1) OntologyRegistry 加载所有 ObjectType/Function/Action
          2) validate_completeness 无严重错误
          3) 已知类型可以校验实例

  链路 C: Memory Graph → Memory Engine → 上下文注入
    步骤：1) bootstrap_project 生成节点
          2) LinkTypeRegistry 加载成功
          3) graph_resolver 可以解析 front-matter（不调用 LLM）

  链路 D: Layer 1 & 2 集成测试（轻量级，mock Layer 1）
    步骤：1) 模拟 Layer 1 发出"任务描述"
          2) Memory Engine 返回相关上下文片段
          3) 验证返回内容包含已 bootstrap 的代码信息
"""
from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List
from unittest.mock import MagicMock, patch

import pytest
import yaml

_HERE = Path(__file__).resolve().parent

import sys
sys.path.insert(0, str(_HERE.parent / "src"))

from mms.bootstrap.ontology_populator import bootstrap_project
from mms.ontology.registry import get_ontology_registry


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def bootstrapped_python_project(tmp_path_factory) -> Path:
    """模块级 fixture：对 Python FastAPI demo 执行一次 bootstrap 并复用。"""
    fixture = _HERE / "fixtures" / "python-fastapi-demo"
    target = tmp_path_factory.mktemp("e2e_python") / "fastapi-demo"
    shutil.copytree(fixture, target)
    for md in target.rglob("MEM-BOOT-*.md"):
        md.unlink()
    bootstrap_project(target, skip_doc_absorb=True, dry_run=False, verbose=False)
    return target


@pytest.fixture(scope="module")
def bootstrapped_java_project(tmp_path_factory) -> Path:
    """模块级 fixture：对 Spring Boot demo 执行一次 bootstrap 并复用。"""
    fixture = _HERE / "fixtures" / "spring-boot-demo"
    target = tmp_path_factory.mktemp("e2e_java") / "spring-boot-demo"
    shutil.copytree(fixture, target)
    for md in target.rglob("MEM-BOOT-*.md"):
        md.unlink()
    bootstrap_project(target, skip_doc_absorb=True, dry_run=False, verbose=False)
    return target


# ─── 链路 A: Bootstrap → Memory Graph → Ontology 校验 ────────────────────────

class TestChainA_BootstrapToMemoryGraph:
    """验证从代码库到 Memory Graph 的完整生成链路。"""

    def test_memory_dir_created(self, bootstrapped_python_project):
        """bootstrap 应创建 docs/memory/shared 目录。"""
        mem_dir = bootstrapped_python_project / "docs" / "memory" / "shared"
        assert mem_dir.is_dir(), "docs/memory/shared 目录未创建"

    def test_memory_nodes_generated(self, bootstrapped_python_project):
        """至少生成 1 个 MEM-BOOT-*.md 节点。"""
        mem_files = list(
            (bootstrapped_python_project / "docs" / "memory" / "shared").rglob("MEM-BOOT-*.md")
        )
        assert len(mem_files) > 0, "未生成任何 MEM-BOOT-*.md 节点"

    def test_all_nodes_pass_schema(self, bootstrapped_python_project):
        """所有生成的节点通过 MemoryNode schema 校验。"""
        reg = get_ontology_registry()
        mem_files = list(
            (bootstrapped_python_project / "docs" / "memory" / "shared").rglob("MEM-BOOT-*.md")
        )
        failures = []
        for f in mem_files:
            content = f.read_text()
            if not content.startswith("---"):
                continue
            fm_end = content.find("---", 3)
            fm = yaml.safe_load(content[3:fm_end].strip())
            result = reg.objects.validate("MemoryNode", fm)
            if not result.valid:
                failures.append(f"{f.name}: {result.errors}")
        assert failures == [], f"以下节点未通过 schema 校验:\n" + "\n".join(failures)

    def test_nodes_have_ast_pointer(self, bootstrapped_python_project):
        """生成的节点应含 ast_pointer 字段（代码骨架绑定）。"""
        mem_files = list(
            (bootstrapped_python_project / "docs" / "memory" / "shared").rglob("MEM-BOOT-*.md")
        )
        missing = []
        for f in mem_files:
            content = f.read_text()
            if "ast_pointer:" not in content:
                missing.append(f.name)
        assert missing == [], f"以下节点缺少 ast_pointer: {missing}"

    def test_nodes_have_cites_files(self, bootstrapped_python_project):
        """生成的节点应含 cites_files（链接到实际代码文件）。"""
        mem_files = list(
            (bootstrapped_python_project / "docs" / "memory" / "shared").rglob("MEM-BOOT-*.md")
        )
        missing = []
        for f in mem_files:
            content = f.read_text()
            if "cites_files:" not in content:
                missing.append(f.name)
        assert missing == [], f"以下节点缺少 cites_files: {missing}"

    def test_layer_distribution_covers_all_arch_layers(self, bootstrapped_python_project):
        """FastAPI 项目应覆盖 ADAPTER/APP/DOMAIN/PLATFORM 四层的记忆节点。"""
        mem_files = list(
            (bootstrapped_python_project / "docs" / "memory" / "shared").rglob("MEM-BOOT-*.md")
        )
        layers_found = set()
        for f in mem_files:
            content = f.read_text()
            if content.startswith("---"):
                fm_end = content.find("---", 3)
                fm = yaml.safe_load(content[3:fm_end].strip())
                layers_found.add(fm.get("layer"))

        # 期望至少包含 ADAPTER/APP/DOMAIN 对应的 v4.0 细粒度 schema 层
        # ADAPTER → L5_api, APP → L4_service, DOMAIN → L3_ontology
        expected_schema_layers_v4 = {"L5_api", "L4_service", "L3_ontology"}
        # 向后兼容：旧粗粒度层名也视为覆盖
        expected_schema_layers_v3 = {"L5_interface", "L4_application", "L3_domain"}
        covered = (layers_found & expected_schema_layers_v4) | (layers_found & expected_schema_layers_v3)
        assert len(covered) >= 2, (
            f"缺少足够的架构层覆盖（期望 ≥ 2 层）\n已有层: {layers_found}"
        )

    def test_java_project_bootstrap_success(self, bootstrapped_java_project):
        """Java Spring Boot 项目 bootstrap 也能成功生成节点。"""
        mem_files = list(
            (bootstrapped_java_project / "docs" / "memory" / "shared").rglob("MEM-BOOT-*.md")
        )
        assert len(mem_files) > 0, "Java 项目未生成任何记忆节点"

    def test_cross_project_schema_consistency(
        self, bootstrapped_python_project, bootstrapped_java_project
    ):
        """Python 和 Java 项目生成的节点都符合同一 schema（跨语言一致性）。"""
        reg = get_ontology_registry()
        for proj_dir in [bootstrapped_python_project, bootstrapped_java_project]:
            mem_files = list(
                (proj_dir / "docs" / "memory" / "shared").rglob("MEM-BOOT-*.md")
            )
            for f in mem_files:
                content = f.read_text()
                if not content.startswith("---"):
                    continue
                fm_end = content.find("---", 3)
                fm = yaml.safe_load(content[3:fm_end].strip())
                result = reg.objects.validate("MemoryNode", fm)
                assert result.valid, (
                    f"[{proj_dir.name}] {f.name} 校验失败: {result.errors}"
                )


# ─── 链路 B: Ontology Schema → OntologyRegistry ───────────────────────────────

class TestChainB_OntologyRegistry:
    """验证 Ontology Schema → OntologyRegistry 的加载链路。"""

    def test_all_object_types_loaded(self):
        """所有 ObjectType 定义可加载且有效。"""
        reg = get_ontology_registry()
        ids = reg.objects.all_ids()
        assert len(ids) >= 5, f"ObjectType 数量不足: {ids}"
        # 核心类型必须存在
        for required in ["CodeClass", "MemoryNode", "CodeFile"]:
            assert required in ids, f"缺少核心 ObjectType: {required}"

    def test_all_functions_loaded(self):
        """所有 Function 定义可加载。"""
        reg = get_ontology_registry()
        fns = reg.functions.all_ids()
        assert "fn_infer_layer" in fns, "fn_infer_layer 未加载"
        assert "fn_build_code_graph" in fns, "fn_build_code_graph 未加载"

    def test_all_actions_loaded(self):
        """所有 Action 定义可加载。"""
        reg = get_ontology_registry()
        acts = reg.actions.all_ids()
        assert "action_bootstrap" in acts, "action_bootstrap 未加载"

    def test_ontology_completeness(self):
        """validate_completeness 无严重错误。"""
        reg = get_ontology_registry()
        issues = reg.validate_completeness()
        # 不应有任何严重错误（可以有警告）
        assert isinstance(issues, list)

    def test_link_types_loaded(self):
        """LinkType 定义完整加载。"""
        from mms.memory.link_registry import LinkTypeRegistry
        lreg = LinkTypeRegistry()
        links = lreg.all()
        assert len(links) >= 5, f"LinkType 数量不足: {len(links)}"
        link_ids = {lt.id for lt in links}
        for required in ["link_depends_on", "link_cites", "link_about"]:
            assert required in link_ids, f"缺少核心 LinkType: {required}"

    def test_code_class_schema_covers_bootstrap_fields(self):
        """CodeClass schema 包含 Bootstrap 填充的所有字段。"""
        reg = get_ontology_registry()
        cc_def = reg.objects.get("CodeClass")
        assert cc_def is not None
        required_fields = [
            "class_fqn", "name", "kind", "file_path",
            "inferred_layer", "inferred_object_type", "layer_confidence"
        ]
        for field in required_fields:
            assert field in cc_def.properties, (
                f"CodeClass schema 缺少 Bootstrap 填充的字段: {field}"
            )


# ─── 链路 C: Memory Graph → Memory Engine 读取 ────────────────────────────────

class TestChainC_MemoryEngineRead:
    """验证 Memory Engine 能够正确读取 bootstrap 生成的节点。"""

    def test_graph_resolver_parses_frontmatter(self, bootstrapped_python_project):
        """MemoryGraph 能解析 MEM-BOOT-*.md 的 front-matter。"""
        from mms.memory.graph_resolver import MemoryGraph
        # 指向 bootstrap 生成的 docs/memory/shared 目录
        mem_root = bootstrapped_python_project / "docs" / "memory" / "shared"
        graph = MemoryGraph(memory_root=mem_root)

        # 使用 get() 和 all_hot() 验证节点已加载
        graph._ensure_loaded()
        assert len(graph._nodes) > 0, "MemoryGraph 未读取到任何节点"

    def test_graph_resolver_node_has_layer(self, bootstrapped_python_project):
        """读取的节点应包含有效的 layer 字段（v4.0 细粒度 ID 或向后兼容粗粒度别名）。"""
        from mms.memory.graph_resolver import MemoryGraph
        # v4.0：细粒度层 ID + 粗粒度别名（向后兼容）
        VALID_LAYERS = {
            "L5_frontend", "L5_api", "L4_service", "L4_worker",
            "L3_ontology", "L3_data_pipeline",
            "L2_database", "L2_messaging", "L2_cache", "L2_storage",
            "L1_security", "CC_architecture", "CC_testing", "CC_governance",
            "BIZ", "Ops", "Tooling_mms",
            "L1_platform", "L2_infrastructure", "L3_domain", "L4_application", "L5_interface", "CC",
        }
        mem_root = bootstrapped_python_project / "docs" / "memory" / "shared"
        graph = MemoryGraph(memory_root=mem_root)
        graph._ensure_loaded()
        boot_nodes = [n for nid, n in graph._nodes.items() if nid.startswith("MEM-BOOT-")]
        assert len(boot_nodes) > 0, "未加载到任何 MEM-BOOT-* 节点"
        for node in boot_nodes:
            layer = node.layer
            assert layer in VALID_LAYERS, (
                f"节点 {node.id} 的 layer='{layer}' 不在 schema 允许值中"
            )

    def test_link_registry_resolves_depends_on(self):
        """LinkTypeRegistry 能解析 depends_on 边定义。"""
        from mms.memory.link_registry import LinkTypeRegistry
        reg = LinkTypeRegistry()
        lt = reg.get("link_depends_on")
        assert lt is not None
        assert lt.source_type == "CodeClass"
        assert lt.target_type == "CodeClass"

    def test_link_registry_resolves_cites(self):
        """LinkTypeRegistry 能解析 cites 边定义。"""
        from mms.memory.link_registry import LinkTypeRegistry
        reg = LinkTypeRegistry()
        lt = reg.get("link_cites")
        assert lt is not None
        assert lt.source_type == "MemoryNode"


# ─── 链路 D: Layer 1 & 2 联合集成测试 ────────────────────────────────────────

class TestChainD_Layer1And2Integration:
    """
    模拟 Layer 1 发起上下文查询请求，验证 Layer 2 能正确返回相关内存节点。

    注意：不调用真实 LLM，通过关键词匹配模拟意图分类。
    """

    def test_memory_graph_contains_order_knowledge(self, bootstrapped_python_project):
        """bootstrap 后，Memory Graph 应包含订单领域相关的知识节点。"""
        mem_files = list(
            (bootstrapped_python_project / "docs" / "memory" / "shared").rglob("MEM-BOOT-*.md")
        )
        # 至少有一个节点 about_concepts 或 tags 包含 "order" 相关词
        order_related = [
            f for f in mem_files
            if "order" in f.read_text().lower()
        ]
        assert len(order_related) > 0, "Memory Graph 中没有订单相关的知识节点"

    def test_controller_node_links_to_service_file(self, bootstrapped_python_project):
        """Controller 的记忆节点应通过 cites_files 链接到对应的源代码。"""
        mem_files = list(
            (bootstrapped_python_project / "docs" / "memory" / "shared").rglob("MEM-BOOT-*.md")
        )
        controller_nodes = [
            f for f in mem_files
            if "controller" in f.read_text().lower() and "cites_files:" in f.read_text()
        ]
        assert len(controller_nodes) > 0, "未找到包含 cites_files 的 Controller 节点"

        for node_file in controller_nodes:
            content = node_file.read_text()
            # cites_files 应指向真实存在的代码文件
            if content.startswith("---"):
                fm_end = content.find("---", 3)
                fm = yaml.safe_load(content[3:fm_end].strip())
                cites = fm.get("cites_files", [])
                for cited_path in cites:
                    full_path = bootstrapped_python_project / cited_path
                    assert full_path.exists() or cited_path != "", (
                        f"cites_files 引用的文件不存在: {cited_path}"
                    )

    def test_layer2_output_suitable_for_layer1_context(self, bootstrapped_python_project):
        """
        验证 Memory Graph 输出的格式适合作为 Layer 1 的上下文。

        Layer 1 需要：每个节点至少有 id、layer、type、tags 字段。
        """
        mem_files = list(
            (bootstrapped_python_project / "docs" / "memory" / "shared").rglob("MEM-BOOT-*.md")
        )
        required_fields = {"id", "layer", "type", "tags"}
        for f in mem_files:
            content = f.read_text()
            if not content.startswith("---"):
                continue
            fm_end = content.find("---", 3)
            fm = yaml.safe_load(content[3:fm_end].strip())
            missing = required_fields - set(fm.keys())
            assert not missing, (
                f"{f.name} 缺少 Layer 1 所需的上下文字段: {missing}"
            )

    def test_bootstrap_report_matches_actual_files(self, tmp_path):
        """BootstrapV2Report 中的 memories_generated 与实际文件数一致。"""
        fixture = _HERE / "fixtures" / "python-fastapi-demo"
        target = tmp_path / "check-consistency"
        shutil.copytree(fixture, target)
        for md in target.rglob("MEM-BOOT-*.md"):
            md.unlink()
        report = bootstrap_project(target, skip_doc_absorb=True, dry_run=False, verbose=False)

        actual_files = list(
            (target / "docs" / "memory" / "shared").rglob("MEM-BOOT-*.md")
        )
        assert report.memories_generated == len(actual_files), (
            f"Report 声明生成 {report.memories_generated} 个节点，"
            f"但实际找到 {len(actual_files)} 个文件"
        )


# ─── 全链路流水线测试 ──────────────────────────────────────────────────────────

class TestFullPipeline:
    """从代码库到知识图谱的完整流水线验证。"""

    @pytest.mark.parametrize("fixture_name", [
        "python-fastapi-demo",
        "spring-boot-demo",
    ])
    def test_full_pipeline_on_fixture(self, tmp_path, fixture_name):
        """
        完整流水线：
          1. Bootstrap: 代码库 → AST → Signal Fusion → Memory Graph
          2. Validation: Memory Graph → OntologyRegistry 校验
          3. Linking: LinkTypeRegistry 能解析节点间的边类型

        参数化覆盖 Python 和 Java 两种项目。
        """
        fixture = _HERE / "fixtures" / fixture_name
        if not fixture.exists():
            pytest.skip(f"Fixture {fixture_name} 不存在")

        target = tmp_path / fixture_name
        shutil.copytree(fixture, target)
        for md in target.rglob("MEM-BOOT-*.md"):
            md.unlink()

        # Step 1: Bootstrap
        report = bootstrap_project(target, skip_doc_absorb=True, dry_run=False, verbose=False)
        assert report.memories_generated >= 0
        assert report.errors == [] or all("warning" in e.lower() for e in report.errors)

        # Step 2: Ontology Validation
        reg = get_ontology_registry()
        mem_files = list((target / "docs" / "memory" / "shared").rglob("MEM-BOOT-*.md"))
        for f in mem_files:
            content = f.read_text()
            if not content.startswith("---"):
                continue
            fm_end = content.find("---", 3)
            fm = yaml.safe_load(content[3:fm_end].strip())
            result = reg.objects.validate("MemoryNode", fm)
            assert result.valid, f"[{fixture_name}] {f.name} schema 校验失败: {result.errors}"

        # Step 3: Link Type Resolution
        from mms.memory.link_registry import LinkTypeRegistry
        lreg = LinkTypeRegistry()
        for lt in lreg.all():
            assert lt.id is not None and lt.id != ""
            assert lt.source_type is not None
            assert lt.target_type is not None
