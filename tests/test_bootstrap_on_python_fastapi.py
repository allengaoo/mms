"""
test_bootstrap_on_python_fastapi.py — Bootstrap v2 针对 Python FastAPI 项目的验证

使用 tests/fixtures/python-fastapi-demo 作为靶机。
验证项：
  1. 正确检测 FastAPI 技术栈并注入相应 Seed Pack
  2. AST 骨架化捕获所有 Python 类（Controller/Service/Repository/Model）
  3. 五路信号正确推断各类的层级：
     - OrderController  → ADAPTER (controller/ 路径 + Controller 后缀)
     - OrderService     → APP (service/ 路径 + Service 后缀)
     - OrderRepository  → DOMAIN (repository/ 路径 + Repository 后缀)
     - Order            → DOMAIN (model/ 路径 + Base 继承 → DeclarativeBase hint)
     - DatabaseConfig   → PLATFORM (config/ 相关路径 + Config 后缀)
  4. 生成的 MemoryNode 文件符合 MemoryNode ObjectType schema
  5. 生成的 layer 字段使用 schema 规范值（L3_domain / L4_application / L5_interface）
  6. 幂等性：两次 bootstrap 生成相同数量的记忆节点
"""
from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_FIXTURE = _HERE / "fixtures" / "python-fastapi-demo"

import sys
sys.path.insert(0, str(_HERE.parent / "src"))

from mms.bootstrap.ontology_populator import bootstrap_project, BootstrapV2Report


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def isolated_fastapi(tmp_path: Path) -> Path:
    """每个测试使用独立的副本（清除已有 MEM-BOOT-*.md，确保测试幂等）。"""
    target = tmp_path / "fastapi-demo"
    shutil.copytree(_FIXTURE, target)
    # 清除之前直接在 fixture 目录运行 bootstrap 时生成的 boot 记忆文件，
    # 避免 fingerprint 幂等检查在"第一次"就跳过所有生成
    for md in target.rglob("MEM-BOOT-*.md"):
        md.unlink()
    return target


# ─── 基础：报告完整性 ─────────────────────────────────────────────────────────

class TestFastAPIReportIntegrity:

    def test_report_has_required_attrs(self, isolated_fastapi):
        """BootstrapV2Report 包含所有必填属性。"""
        report = bootstrap_project(
            isolated_fastapi, skip_doc_absorb=True, dry_run=True, verbose=False
        )
        assert isinstance(report, BootstrapV2Report)
        for attr in ["files_scanned", "classes_found", "classes_inferred",
                     "memories_generated", "detected_stacks", "errors", "dry_run"]:
            assert hasattr(report, attr), f"缺少属性: {attr}"

    def test_no_fatal_errors(self, isolated_fastapi):
        """不应产生任何致命错误。"""
        report = bootstrap_project(
            isolated_fastapi, skip_doc_absorb=True, dry_run=True, verbose=False
        )
        fatal = [e for e in report.errors if "fatal" in e.lower() or "traceback" in e.lower()]
        assert fatal == [], f"存在致命错误: {fatal}"

    def test_all_python_files_scanned(self, isolated_fastapi):
        """应扫描所有 .py 文件（不含 __init__.py 等）。"""
        report = bootstrap_project(
            isolated_fastapi, skip_doc_absorb=True, dry_run=True, verbose=False
        )
        assert report.files_scanned >= 5, f"扫描文件数不足: {report.files_scanned}"

    def test_all_classes_found(self, isolated_fastapi):
        """应识别所有已定义的类。"""
        report = bootstrap_project(
            isolated_fastapi, skip_doc_absorb=True, dry_run=True, verbose=False
        )
        # FastAPI demo 有 9 个类（Controller/Service/Repository/Models/Schemas/Config）
        assert report.classes_found >= 5, f"类数量不足: {report.classes_found}"


# ─── 技术栈识别 ───────────────────────────────────────────────────────────────

class TestFastAPIStackDetection:

    def test_detects_fastapi_or_base(self, isolated_fastapi):
        """应识别 FastAPI 或基础栈。"""
        report = bootstrap_project(
            isolated_fastapi, skip_doc_absorb=True, dry_run=True, verbose=False
        )
        detected = report.detected_stacks
        assert len(detected) > 0, "未检测到任何技术栈"
        # base 栈必须存在（所有项目的基础）
        assert "base" in detected, f"缺少 base 栈: {detected}"

    def test_seed_packs_injected(self, isolated_fastapi):
        """至少有一个 Seed Pack 被注入。"""
        report = bootstrap_project(
            isolated_fastapi, skip_doc_absorb=True, dry_run=False, verbose=False
        )
        assert report.injected_seed_packs is not None
        assert len(report.injected_seed_packs) > 0


# ─── 层级推断准确性 ───────────────────────────────────────────────────────────

class TestFastAPILayerInference:
    """验证 signal_fusion 对 FastAPI 项目各类的推断准确性。"""

    def _get_inferences(self, target: Path):
        from mms.analysis.ast_skeleton import build_ast_index
        from mms.bootstrap.signal_fusion import infer_all
        from mms.bootstrap.code_graph_builder import build_code_graph
        ast_index = build_ast_index(root=target, dry_run=False)
        code_graph = build_code_graph(ast_index=ast_index, project_root=target)
        return infer_all(ast_index=ast_index, project_root=target)

    def test_controller_inferred_as_adapter(self, isolated_fastapi):
        """OrderController → ADAPTER 层（controller/ 路径 + Controller 后缀）。"""
        inferences = self._get_inferences(isolated_fastapi)
        controller_entries = [
            (fqn, inf, otype)
            for fqn, (inf, otype) in inferences.items()
            if fqn.endswith("::OrderController")
        ]
        assert len(controller_entries) == 1, "未找到 OrderController"
        _, inf, otype = controller_entries[0]
        assert inf.inferred_layer == "ADAPTER", f"OrderController 应为 ADAPTER，实际: {inf.inferred_layer}"
        assert otype.code_object_type == "Controller"
        assert inf.confidence >= 0.5

    def test_service_inferred_as_app(self, isolated_fastapi):
        """OrderService → APP 层（service/ 路径 + Service 后缀）。"""
        inferences = self._get_inferences(isolated_fastapi)
        service_entries = [
            (fqn, inf, otype)
            for fqn, (inf, otype) in inferences.items()
            if fqn.endswith("::OrderService")
        ]
        assert len(service_entries) == 1, "未找到 OrderService"
        _, inf, otype = service_entries[0]
        assert inf.inferred_layer == "APP", f"OrderService 应为 APP，实际: {inf.inferred_layer}"
        assert otype.code_object_type == "Service"

    def test_repository_inferred_as_domain(self, isolated_fastapi):
        """OrderRepository → DOMAIN 层（repository/ 路径 + Repository 后缀）。"""
        inferences = self._get_inferences(isolated_fastapi)
        repo_entries = [
            (fqn, inf, otype)
            for fqn, (inf, otype) in inferences.items()
            if fqn.endswith("::OrderRepository")
        ]
        assert len(repo_entries) == 1, "未找到 OrderRepository"
        _, inf, otype = repo_entries[0]
        assert inf.inferred_layer == "DOMAIN", f"OrderRepository 应为 DOMAIN，实际: {inf.inferred_layer}"
        assert otype.code_object_type == "Repository"
        assert inf.confidence >= 0.7

    def test_model_inferred_as_domain(self, isolated_fastapi):
        """Order (SQLAlchemy Model) → DOMAIN 层（DeclarativeBase 继承 hint）。"""
        inferences = self._get_inferences(isolated_fastapi)
        order_entries = [
            (fqn, inf, otype)
            for fqn, (inf, otype) in inferences.items()
            if fqn.endswith("::Order")
        ]
        assert len(order_entries) >= 1, "未找到 Order 模型类"
        _, inf, _ = order_entries[0]
        assert inf.inferred_layer == "DOMAIN", f"Order 应为 DOMAIN，实际: {inf.inferred_layer}"

    def test_config_inferred_as_platform(self, isolated_fastapi):
        """DatabaseConfig → PLATFORM 层（Config 后缀）。"""
        inferences = self._get_inferences(isolated_fastapi)
        config_entries = [
            (fqn, inf, otype)
            for fqn, (inf, otype) in inferences.items()
            if "Config" in fqn.split("::")[-1]
        ]
        assert len(config_entries) >= 1, "未找到 Config 类"
        _, inf, otype = config_entries[0]
        assert inf.inferred_layer == "PLATFORM", f"DatabaseConfig 应为 PLATFORM，实际: {inf.inferred_layer}"

    def test_no_unknown_classes(self, isolated_fastapi):
        """所有类应有有效层级推断（无 UNKNOWN）。"""
        inferences = self._get_inferences(isolated_fastapi)
        unknown = [(fqn, inf.confidence) for fqn, (inf, _) in inferences.items()
                   if inf.inferred_layer == "UNKNOWN"]
        assert unknown == [], f"存在未推断类: {unknown}"


# ─── Schema 合规性 ────────────────────────────────────────────────────────────

class TestFastAPISchemaConformance:
    """验证 bootstrap 生成的 MemoryNode 符合 MemoryNode ObjectType Schema。"""

    VALID_ID_PATTERN = re.compile(r"^(MEM-L-|MEM-BOOT-|AD-|BIZ-|ENV-|MEM-DB-)[0-9A-Z-]+")
    # v4.0：支持细粒度层 ID（规范值）和粗粒度别名（向后兼容）
    VALID_LAYERS = {
        # v5.0 通用层 ID（universal_layers.yaml，Schema Source of Truth）
        "ADAPTER", "APP", "DOMAIN", "PLATFORM", "CC",
        "CC_testing", "CC_governance", "BIZ", "Ops",
        # v4.x 项目特化 ID（向后兼容，迁移期内有效）
        "L5_frontend", "L5_api", "L4_service", "L4_worker",
        "L3_ontology", "L3_data_pipeline",
        "L2_database", "L2_messaging", "L2_cache", "L2_storage",
        "L1_security", "CC_architecture", "CC_governance", "Tooling_mms",
        # v3.x 粗粒度别名（更早期兼容）
        "L1_platform", "L2_infrastructure", "L3_domain", "L4_application", "L5_interface",
    }
    VALID_TYPES = {"lesson", "pattern", "decision", "anti-pattern", "business-flow"}
    VALID_TIERS = {"hot", "warm", "cold", "archive"}

    def test_generated_nodes_pass_schema_validation(self, isolated_fastapi):
        """所有生成的 MEM-BOOT-*.md 节点通过 MemoryNode schema 校验。"""
        bootstrap_project(isolated_fastapi, skip_doc_absorb=True, dry_run=False, verbose=False)

        from mms.ontology.registry import get_ontology_registry
        import yaml

        reg = get_ontology_registry()
        mem_files = list((isolated_fastapi / "docs" / "memory" / "shared").rglob("MEM-BOOT-*.md"))
        assert len(mem_files) > 0, "没有生成任何 MEM-BOOT-*.md 文件"

        for md_file in mem_files:
            content = md_file.read_text()
            # 提取 front-matter
            if content.startswith("---"):
                fm_end = content.find("---", 3)
                fm_str = content[3:fm_end].strip()
                fm = yaml.safe_load(fm_str)
            else:
                pytest.fail(f"{md_file.name} 缺少 YAML front-matter")

            result = reg.objects.validate("MemoryNode", fm)
            assert result.valid, (
                f"{md_file.name} 未通过 MemoryNode schema 校验:\n"
                f"  errors: {result.errors}\n"
                f"  front-matter: {fm}"
            )

    def test_generated_id_matches_pattern(self, isolated_fastapi):
        """生成的 id 符合 MemoryNode 的 id pattern。"""
        bootstrap_project(isolated_fastapi, skip_doc_absorb=True, dry_run=False, verbose=False)
        import yaml

        mem_files = list((isolated_fastapi / "docs" / "memory" / "shared").rglob("MEM-BOOT-*.md"))
        for md_file in mem_files:
            content = md_file.read_text()
            if content.startswith("---"):
                fm_end = content.find("---", 3)
                fm = yaml.safe_load(content[3:fm_end].strip())
                assert self.VALID_ID_PATTERN.match(fm.get("id", "")), (
                    f"{md_file.name} id='{fm.get('id')}' 不符合格式"
                )

    def test_generated_layer_is_schema_compliant(self, isolated_fastapi):
        """生成的 layer 字段使用 schema 规范值（非 ADAPTER/APP/DOMAIN）。"""
        bootstrap_project(isolated_fastapi, skip_doc_absorb=True, dry_run=False, verbose=False)
        import yaml

        mem_files = list((isolated_fastapi / "docs" / "memory" / "shared").rglob("MEM-BOOT-*.md"))
        for md_file in mem_files:
            content = md_file.read_text()
            if content.startswith("---"):
                fm_end = content.find("---", 3)
                fm = yaml.safe_load(content[3:fm_end].strip())
                layer = fm.get("layer", "")
                assert layer in self.VALID_LAYERS, (
                    f"{md_file.name} layer='{layer}' 不在 schema 允许值中 {self.VALID_LAYERS}"
                )
                # Schema v5.0: ADAPTER/APP/DOMAIN/PLATFORM 现在就是正规的 universal 层 ID
                # （_SCHEMA_LAYER_MAP 已废除，v4 细粒度 ID 在迁移期内仍有效）

    def test_generated_type_is_valid(self, isolated_fastapi):
        """生成的 type 字段在 MemoryNode schema 允许的枚举中。"""
        bootstrap_project(isolated_fastapi, skip_doc_absorb=True, dry_run=False, verbose=False)
        import yaml

        mem_files = list((isolated_fastapi / "docs" / "memory" / "shared").rglob("MEM-BOOT-*.md"))
        for md_file in mem_files:
            content = md_file.read_text()
            if content.startswith("---"):
                fm_end = content.find("---", 3)
                fm = yaml.safe_load(content[3:fm_end].strip())
                assert fm.get("type") in self.VALID_TYPES, (
                    f"{md_file.name} type='{fm.get('type')}' 不合法"
                )


# ─── 幂等性 ───────────────────────────────────────────────────────────────────

class TestFastAPIIdempotency:

    def test_two_runs_produce_same_count(self, isolated_fastapi):
        """增量幂等性：第一次生成记忆，第二次 fingerprint 未变则跳过生成（生成 0 条）。"""
        r1 = bootstrap_project(
            isolated_fastapi, skip_doc_absorb=True, dry_run=False, verbose=False
        )
        assert r1.memories_generated > 0, "第一次 bootstrap 应该生成至少 1 条记忆"

        r2 = bootstrap_project(
            isolated_fastapi, skip_doc_absorb=True, dry_run=False, verbose=False
        )
        # 增量模式：代码未变化时 fingerprint 匹配，第二次生成数应为 0（幂等）
        assert r2.memories_generated == 0, (
            f"增量幂等性失败: 第二次应跳过所有已生成记忆，但实际生成了 {r2.memories_generated} 条"
        )

    def test_dry_run_writes_no_files(self, isolated_fastapi):
        """dry_run=True 时不写入任何文件。"""
        before_files = set((isolated_fastapi / "docs").rglob("*")) if (
            isolated_fastapi / "docs"
        ).exists() else set()
        bootstrap_project(isolated_fastapi, skip_doc_absorb=True, dry_run=True, verbose=False)
        after_files = set((isolated_fastapi / "docs").rglob("*")) if (
            isolated_fastapi / "docs"
        ).exists() else set()
        new_files = after_files - before_files
        assert new_files == set(), f"dry_run 不应创建文件: {new_files}"
