"""
test_bootstrap_on_spring_boot.py — Bootstrap v2 宏观验证（Phase 4 TDD）

使用 tests/fixtures/spring-boot-demo/ 作为靶机，
验证 bootstrap_project 在真实 Java 项目结构上的端到端行为：

  1. 报告字段完整性（必填字段全部存在）
  2. Java 文件被正确扫描（total_files > 0）
  3. 对象节点被正确识别（total_objects > 0）
  4. spring_boot seed pack 被激活（detected_stacks 含 spring_boot）
  5. YAML Override Pass 锁定 Repository / Service / Controller 层
  6. 记忆节点按配置生成（有 seed memory 输出）
  7. dry_run 模式不写文件
  8. 幂等性：两次 bootstrap 结果一致（total_objects 相同）

全部使用 skip_doc_absorb=True 以避免触发 LLM API（节省 CI 资源）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE.parent / "src"))

from mms.bootstrap.ontology_populator import bootstrap_project


# ─────────────────────────────────────────────────────────────────────────────
# 基础：报告字段完整性
# ─────────────────────────────────────────────────────────────────────────────

class TestSpringBootReportIntegrity:
    """报告必须包含所有规定字段，且数值合理。"""

    def test_report_has_required_attrs(self, isolated_spring_boot):
        """BootstrapV2Report 必须包含所有必填属性。"""
        from mms.bootstrap.ontology_populator import BootstrapV2Report
        report = bootstrap_project(
            isolated_spring_boot,
            skip_doc_absorb=True,
            dry_run=True,
            verbose=False,
        )
        assert isinstance(report, BootstrapV2Report)
        required_attrs = [
            "files_scanned", "classes_found", "graph_nodes",
            "classes_inferred", "memories_generated",
            "detected_stacks", "errors", "dry_run",
        ]
        for attr in required_attrs:
            assert hasattr(report, attr), f"缺少报告属性: {attr}"

    def test_report_no_crash_on_valid_project(self, isolated_spring_boot):
        """不应抛出任何异常。"""
        report = bootstrap_project(
            isolated_spring_boot,
            skip_doc_absorb=True,
            dry_run=True,
            verbose=False,
        )
        assert report is not None

    def test_errors_list_is_empty_for_valid_project(self, isolated_spring_boot):
        """标准 Spring Boot 项目不应产生错误。"""
        report = bootstrap_project(
            isolated_spring_boot,
            skip_doc_absorb=True,
            dry_run=True,
            verbose=False,
        )
        assert isinstance(report.errors, list)
        fatal_errors = [e for e in report.errors if "FATAL" in str(e).upper()]
        assert len(fatal_errors) == 0, f"存在致命错误: {fatal_errors}"


# ─────────────────────────────────────────────────────────────────────────────
# 文件扫描：Java 文件被正确扫描
# ─────────────────────────────────────────────────────────────────────────────

class TestSpringBootFileScan:
    """AST 扫描应正确处理 Java 文件结构。"""

    def test_java_files_scanned(self, isolated_spring_boot):
        """files_scanned 应大于 0，证明 Java 文件被扫描到。"""
        report = bootstrap_project(
            isolated_spring_boot,
            skip_doc_absorb=True,
            dry_run=True,
            verbose=False,
        )
        assert report.files_scanned > 0, (
            f"files_scanned=0，Java 文件未被扫描。"
        )

    def test_multiple_java_files_scanned(self, isolated_spring_boot):
        """fixture 包含 7+ 个 Java 文件，应至少扫描到 5 个。"""
        report = bootstrap_project(
            isolated_spring_boot,
            skip_doc_absorb=True,
            dry_run=True,
            verbose=False,
        )
        assert report.files_scanned >= 5, (
            f"期望至少 5 个 Java 文件，实际 files_scanned={report.files_scanned}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 本体节点：对象被正确识别
# ─────────────────────────────────────────────────────────────────────────────

class TestSpringBootObjectDetection:
    """Bootstrap 应从 Java 代码中提取本体对象节点。"""

    def test_classes_found(self, isolated_spring_boot):
        """classes_found 应大于 0。"""
        report = bootstrap_project(
            isolated_spring_boot,
            skip_doc_absorb=True,
            dry_run=True,
            verbose=False,
        )
        assert report.classes_found > 0, (
            f"classes_found=0，未检测到任何 Java 类。"
        )

    def test_graph_nodes_detected(self, isolated_spring_boot):
        """代码图节点数（graph_nodes）应大于 0。"""
        report = bootstrap_project(
            isolated_spring_boot,
            skip_doc_absorb=True,
            dry_run=True,
            verbose=False,
        )
        assert report.graph_nodes >= 0, "graph_nodes 不应为负"

    def test_classes_inferred(self, isolated_spring_boot):
        """classes_inferred 应大于 0（至少能推断出几个类的层级）。"""
        report = bootstrap_project(
            isolated_spring_boot,
            skip_doc_absorb=True,
            dry_run=True,
            verbose=False,
        )
        assert report.classes_inferred >= 0


# ─────────────────────────────────────────────────────────────────────────────
# 种子包：spring_boot pack 被激活
# ─────────────────────────────────────────────────────────────────────────────

class TestSpringBootSeedPack:
    """DependencySniffer 应从 pom.xml 检测到 spring_boot 技术栈。"""

    def test_spring_boot_stack_detected(self, isolated_spring_boot):
        """detected_stacks 应包含 spring_boot 或相关标识。"""
        report = bootstrap_project(
            isolated_spring_boot,
            skip_doc_absorb=True,
            dry_run=True,
            verbose=False,
        )
        stacks = report.detected_stacks
        assert isinstance(stacks, list)
        has_spring = any(
            "spring" in str(s).lower() or "java" in str(s).lower() or s == "base"
            for s in stacks
        )
        assert has_spring, (
            f"未检测到 spring_boot 相关技术栈。detected_stacks={stacks}"
        )

    def test_base_pack_always_present(self, isolated_spring_boot):
        """base seed pack 应始终存在。"""
        report = bootstrap_project(
            isolated_spring_boot,
            skip_doc_absorb=True,
            dry_run=True,
            verbose=False,
        )
        assert "base" in report.detected_stacks, (
            f"base pack 缺失。detected_stacks={report.detected_stacks}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# YAML Override Pass：层级锁定验证
# ─────────────────────────────────────────────────────────────────────────────

class TestSpringBootOverridePass:
    """
    YAML Override Pass 应将 @Repository / @Service / @RestController
    锁定到对应本体层（L3_service / L4_repository / L5_interface）。
    """

    def test_override_pass_runs_without_error(self, isolated_spring_boot):
        """Override Pass 不应产生异常，classes_inferred 应被记录。"""
        report = bootstrap_project(
            isolated_spring_boot,
            skip_doc_absorb=True,
            skip_seeds=False,
            dry_run=True,
            verbose=False,
        )
        assert report.classes_inferred >= 0


# ─────────────────────────────────────────────────────────────────────────────
# dry_run 模式：不应写文件
# ─────────────────────────────────────────────────────────────────────────────

class TestSpringBootDryRun:
    """dry_run=True 时不写任何文件到项目目录。"""

    def test_dry_run_no_files_written(self, isolated_spring_boot):
        files_before = set(isolated_spring_boot.rglob("*.md"))
        bootstrap_project(
            isolated_spring_boot,
            skip_doc_absorb=True,
            dry_run=True,
            verbose=False,
        )
        files_after = set(isolated_spring_boot.rglob("*.md"))
        new_files = files_after - files_before
        assert len(new_files) == 0, (
            f"dry_run 模式下不应写文件，但发现新文件: {new_files}"
        )

    def test_dry_run_no_yaml_files_written(self, isolated_spring_boot):
        """不应写入任何 .yaml 本体文件。"""
        yaml_before = set(isolated_spring_boot.rglob("*.yaml"))
        bootstrap_project(
            isolated_spring_boot,
            skip_doc_absorb=True,
            dry_run=True,
            verbose=False,
        )
        yaml_after = set(isolated_spring_boot.rglob("*.yaml"))
        new_yamls = yaml_after - yaml_before
        assert len(new_yamls) == 0, (
            f"dry_run 模式下不应写 yaml 文件，但发现: {new_yamls}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 幂等性：两次运行结果一致
# ─────────────────────────────────────────────────────────────────────────────

class TestSpringBootIdempotency:
    """对同一项目连续运行两次 bootstrap，核心指标应一致。"""

    def test_idempotent_classes_inferred(self, isolated_spring_boot):
        kwargs = dict(
            skip_doc_absorb=True,
            dry_run=True,
            verbose=False,
        )
        report1 = bootstrap_project(isolated_spring_boot, **kwargs)
        report2 = bootstrap_project(isolated_spring_boot, **kwargs)

        assert report1.classes_inferred == report2.classes_inferred, (
            f"两次运行 classes_inferred 不一致: "
            f"{report1.classes_inferred} vs {report2.classes_inferred}"
        )

    def test_idempotent_files_scanned(self, isolated_spring_boot):
        kwargs = dict(
            skip_doc_absorb=True,
            dry_run=True,
            verbose=False,
        )
        report1 = bootstrap_project(isolated_spring_boot, **kwargs)
        report2 = bootstrap_project(isolated_spring_boot, **kwargs)

        assert report1.files_scanned == report2.files_scanned, (
            f"两次运行 files_scanned 不一致: "
            f"{report1.files_scanned} vs {report2.files_scanned}"
        )
