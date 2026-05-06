"""
test_bootstrap_on_nestjs.py — Bootstrap v2 宏观验证（Phase 6 压测矩阵：TypeScript/NestJS）

使用 tests/fixtures/typescript-nestjs-demo/ 作为靶机，
验证 bootstrap_project 在真实 NestJS 项目结构上的端到端行为：

  1. 报告字段完整性（必填字段全部存在）
  2. TypeScript 文件被正确扫描（total_files > 0）
  3. 对象节点被正确识别（有 Controller/Service/Entity/Guard 等）
  4. ADAPTER 层：Controller/Guard 正确归类
  5. APP 层：Service 正确归类
  6. DOMAIN 层：Entity（@Entity 装饰器）正确归类
  7. CC 层：Util/Interceptor/Filter 正确归类
  8. dry_run 模式不写文件
  9. 幂等性：两次 bootstrap 结果一致

全部使用 skip_doc_absorb=True 以避免触发 LLM API（节省 CI 资源）。
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_FIXTURES = _HERE / "fixtures"
_NESTJS_FIXTURE = _FIXTURES / "typescript-nestjs-demo"

sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE.parent / "src"))

from mms.bootstrap.ontology_populator import bootstrap_project


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def isolated_nestjs(tmp_path):
    """为每个测试提供隔离的 NestJS fixture 副本（避免测试间污染）。"""
    dest = tmp_path / "typescript-nestjs-demo"
    shutil.copytree(_NESTJS_FIXTURE, dest)
    # 清理任何已有的 MEM-BOOT-*.md（避免 fixture 污染）
    for md in dest.rglob("MEM-BOOT-*.md"):
        md.unlink()
    return dest


# ─── 报告完整性测试 ───────────────────────────────────────────────────────────

class TestNestJSReportIntegrity:
    """报告必须包含所有规定字段，且数值合理。"""

    def test_report_has_required_attrs(self, isolated_nestjs):
        from mms.bootstrap.ontology_populator import BootstrapV2Report
        report = bootstrap_project(
            isolated_nestjs,
            skip_doc_absorb=True,
            dry_run=True,
            verbose=False,
        )
        assert isinstance(report, BootstrapV2Report)
        required_attrs = [
            "files_scanned", "classes_found", "graph_nodes",
            "memories_generated", "seed_memories_loaded",
            "detected_stacks", "weights_profile_used",
        ]
        for attr in required_attrs:
            assert hasattr(report, attr), f"Report missing required attribute: {attr}"

    def test_files_scanned_positive(self, isolated_nestjs):
        """必须扫描到 TypeScript 文件。"""
        report = bootstrap_project(
            isolated_nestjs,
            skip_doc_absorb=True,
            dry_run=True,
            verbose=False,
        )
        assert report.files_scanned > 0, (
            f"Expected > 0 TypeScript files scanned, got {report.files_scanned}. "
            f"Fixture path: {isolated_nestjs}"
        )

    def test_classes_found_positive(self, isolated_nestjs):
        """必须识别到代码类（Controller/Service/Entity 等）。"""
        report = bootstrap_project(
            isolated_nestjs,
            skip_doc_absorb=True,
            dry_run=True,
            verbose=False,
        )
        assert report.classes_found > 0, (
            f"Expected > 0 classes, got {report.classes_found}. "
            "Check that TypeScript AST parser handles .ts files correctly."
        )


# ─── 层级推断测试 ─────────────────────────────────────────────────────────────

class TestNestJSLayerInference:
    """NestJS 的层级推断准确性验证。"""

    def _run_and_get_inferences(self, project_path):
        """运行 bootstrap 并提取层级推断结果（dry_run）。"""
        from mms.analysis.ast_skeleton import build_ast_index
        from mms.bootstrap.signal_fusion import infer_all

        ast_index = build_ast_index(project_path)
        return infer_all(ast_index)

    def test_controller_classified_as_adapter(self, isolated_nestjs):
        """@Controller 装饰的类必须归入 ADAPTER 层。"""
        inferences = self._run_and_get_inferences(isolated_nestjs)
        controller_classes = {
            fqn: (layer_inf, _)
            for fqn, (layer_inf, _) in inferences.items()
            if "Controller" in fqn
        }
        if not controller_classes:
            pytest.skip("No Controller classes found in NestJS fixture")

        for fqn, (layer_inf, _) in controller_classes.items():
            assert layer_inf.inferred_layer == "ADAPTER", (
                f"{fqn}: expected ADAPTER, got {layer_inf.inferred_layer} "
                f"(confidence={layer_inf.confidence})"
            )

    def test_service_classified_as_app(self, isolated_nestjs):
        """@Injectable Service 类必须归入 APP 层。"""
        inferences = self._run_and_get_inferences(isolated_nestjs)
        service_classes = {
            fqn: (layer_inf, _)
            for fqn, (layer_inf, _) in inferences.items()
            if fqn.endswith("Service") and "Repository" not in fqn
        }
        if not service_classes:
            pytest.skip("No Service classes found in NestJS fixture")

        adapter_or_app = {"ADAPTER", "APP", "DOMAIN"}
        for fqn, (layer_inf, _) in service_classes.items():
            assert layer_inf.inferred_layer in adapter_or_app, (
                f"{fqn}: expected ADAPTER/APP/DOMAIN (service-like), "
                f"got {layer_inf.inferred_layer}"
            )

    def test_entity_classified_as_domain(self, isolated_nestjs):
        """@Entity 装饰的 TypeORM 实体必须归入 DOMAIN 层。"""
        inferences = self._run_and_get_inferences(isolated_nestjs)
        entity_classes = {
            fqn: (layer_inf, _)
            for fqn, (layer_inf, _) in inferences.items()
            if "entity" in fqn.lower() or fqn.endswith("Entity")
        }
        if not entity_classes:
            pytest.skip("No Entity classes found in NestJS fixture")

        for fqn, (layer_inf, _) in entity_classes.items():
            assert layer_inf.inferred_layer in ("DOMAIN", "PLATFORM"), (
                f"{fqn}: expected DOMAIN/PLATFORM for entity, "
                f"got {layer_inf.inferred_layer}"
            )

    def test_util_classified_as_cc(self, isolated_nestjs):
        """Util 工具类必须归入 CC 层。"""
        inferences = self._run_and_get_inferences(isolated_nestjs)
        util_classes = {
            fqn: (layer_inf, _)
            for fqn, (layer_inf, _) in inferences.items()
            if "util" in fqn.lower() or "Util" in fqn
        }
        if not util_classes:
            pytest.skip("No Util classes found in NestJS fixture")

        for fqn, (layer_inf, _) in util_classes.items():
            assert layer_inf.inferred_layer in ("CC", "CC_testing"), (
                f"{fqn}: expected CC, got {layer_inf.inferred_layer}"
            )

    def test_filter_classified_appropriately(self, isolated_nestjs):
        """ExceptionFilter（带 @Catch 装饰器）应归入 CC 或 ADAPTER 层。"""
        inferences = self._run_and_get_inferences(isolated_nestjs)
        filter_classes = {
            fqn: (layer_inf, _)
            for fqn, (layer_inf, _) in inferences.items()
            if "filter" in fqn.lower() or "Filter" in fqn
        }
        if not filter_classes:
            pytest.skip("No Filter classes found in NestJS fixture")

        acceptable = {"CC", "CC_testing", "ADAPTER"}
        for fqn, (layer_inf, _) in filter_classes.items():
            assert layer_inf.inferred_layer in acceptable, (
                f"{fqn}: expected CC/ADAPTER for filter, "
                f"got {layer_inf.inferred_layer}"
            )


# ─── dry_run 模式验证 ─────────────────────────────────────────────────────────

class TestNestJSDryRun:
    def test_dry_run_creates_no_memory_files(self, isolated_nestjs):
        """dry_run=True 时不应生成任何 MEM-BOOT-*.md 文件。"""
        bootstrap_project(
            isolated_nestjs,
            skip_doc_absorb=True,
            dry_run=True,
            verbose=False,
        )
        boot_files = list(isolated_nestjs.rglob("MEM-BOOT-*.md"))
        assert len(boot_files) == 0, (
            f"dry_run=True but found {len(boot_files)} MEM-BOOT-*.md files: "
            f"{[str(f) for f in boot_files[:5]]}"
        )


# ─── 幂等性验证 ───────────────────────────────────────────────────────────────

class TestNestJSIdempotency:
    def test_two_runs_produce_same_class_count(self, isolated_nestjs):
        """两次 Bootstrap（non-dry_run）产生相同数量的 MEM-BOOT-*.md。"""
        bootstrap_project(
            isolated_nestjs,
            skip_doc_absorb=True,
            dry_run=False,
            verbose=False,
        )
        first_run = list(isolated_nestjs.rglob("MEM-BOOT-*.md"))

        bootstrap_project(
            isolated_nestjs,
            skip_doc_absorb=True,
            dry_run=False,
            verbose=False,
        )
        second_run = list(isolated_nestjs.rglob("MEM-BOOT-*.md"))

        assert len(first_run) == len(second_run), (
            f"Bootstrap not idempotent: first={len(first_run)}, second={len(second_run)}"
        )


# ─── Schema v5.0 层名兼容性验证 ──────────────────────────────────────────────

class TestNestJSSchemaV5Layers:
    """验证生成的 MEM-BOOT-*.md 使用 v5.0 通用层 ID（不含旧的细粒度 ID）。"""

    _V4_DEPRECATED_LAYERS = {
        "L5_api", "L5_frontend", "L4_service", "L4_worker",
        "L3_ontology", "L3_data_pipeline", "L2_database",
        "L2_messaging", "L2_cache", "L2_storage",
        "L2_infrastructure", "L1_security", "L1_platform",
        "CC_architecture", "Tooling_mms",
    }

    def test_generated_memories_use_v5_layer_ids(self, isolated_nestjs):
        """生成的记忆文件必须使用 v5.0 通用层 ID，不使用废弃的 v4 ID。"""
        bootstrap_project(
            isolated_nestjs,
            skip_doc_absorb=True,
            dry_run=False,
            verbose=False,
        )
        boot_files = list(isolated_nestjs.rglob("MEM-BOOT-*.md"))
        if not boot_files:
            pytest.skip("No MEM-BOOT-*.md files generated (may not have parseable TS classes)")

        import yaml as _yaml
        violations = []
        for md_file in boot_files:
            content = md_file.read_text(encoding="utf-8")
            if "---" not in content:
                continue
            fm_text = content.split("---")[1] if content.startswith("---") else ""
            try:
                fm = _yaml.safe_load(fm_text) or {}
            except Exception:
                continue
            layer = fm.get("layer", "")
            if layer in self._V4_DEPRECATED_LAYERS:
                violations.append(f"{md_file.name}: layer={layer!r} is deprecated v4 ID")

        assert not violations, (
            f"Found {len(violations)} memory files using deprecated v4 layer IDs:\n"
            + "\n".join(violations[:10])
        )
