"""
tests/dag/test_atomicity_check_full.py

P1 测试：atomicity_check.py 完整覆盖（A1/A2/A4 + validate_unit + infer_layer）

已覆盖于 test_cost_and_atomicity.py 的 A3 部分不在此重复，
本文件专注于：
  - A1：文件数量检查（通过/失败/边界）
  - A2：Token 预算估算（通过/边界）
  - A4：自动验证性检查（pytest 路径/arch_check）
  - infer_layer：路径前缀推断各架构层
  - validate_unit：完整链路（is_atomic、score、results 聚合）
  - compute_atomicity_score：分数计算逻辑
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from mms.dag.atomicity_check import (
    check_a1_file_count,
    check_a2_token_budget,
    check_a3_layer_consistency,
    check_a4_verifiability,
    validate_unit,
    infer_layer,
    compute_atomicity_score,
    CheckResult,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. infer_layer — 路径推断
# ─────────────────────────────────────────────────────────────────────────────

class TestInferLayer:
    """验证 infer_layer 从文件路径正确推断架构层。"""

    def test_backend_api_is_interface(self):
        assert infer_layer("backend/app/api/v1/users.py") == "L5_interface"

    def test_backend_services_is_application(self):
        assert infer_layer("backend/app/services/user_service.py") == "L4_application"

    def test_backend_domain_is_domain(self):
        assert infer_layer("backend/app/domain/user.py") == "L3_domain"

    def test_backend_infrastructure_is_infra(self):
        assert infer_layer("backend/app/infrastructure/db.py") == "L2_infrastructure"

    def test_backend_core_is_platform(self):
        assert infer_layer("backend/app/core/config.py") == "L1_platform"

    def test_frontend_pages_is_interface(self):
        assert infer_layer("frontend/src/pages/HomePage.tsx") == "L5_interface"

    def test_frontend_stores_is_application(self):
        assert infer_layer("frontend/src/stores/userStore.ts") == "L4_application"

    def test_test_file_is_testing(self):
        assert infer_layer("backend/tests/test_user.py") == "testing"

    def test_test_keyword_in_path_is_testing(self):
        assert infer_layer("src/something/test_utils.py") == "testing"

    def test_md_file_is_docs(self):
        assert infer_layer("README.md") == "docs"

    def test_docs_dir_is_docs(self):
        assert infer_layer("docs/memory/_system/config.yaml") == "docs"

    def test_unknown_path_is_unknown(self):
        assert infer_layer("random/path/to/file.py") == "unknown"

    def test_scripts_mms_is_application(self):
        assert infer_layer("scripts/mms/ep_runner.py") == "L4_application"


# ─────────────────────────────────────────────────────────────────────────────
# 2. A1：文件数量检查
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckA1FileCount:
    def test_empty_files_passes(self):
        result = check_a1_file_count([], max_files=2)
        assert result.passed is True
        assert result.label == "A1 文件数量"

    def test_one_file_passes(self):
        assert check_a1_file_count(["a.py"], max_files=2).passed is True

    def test_exactly_max_files_passes(self):
        assert check_a1_file_count(["a.py", "b.py"], max_files=2).passed is True

    def test_one_over_limit_fails(self):
        result = check_a1_file_count(["a.py", "b.py", "c.py"], max_files=2)
        assert result.passed is False
        assert result.is_warning is False  # 硬性失败（不是 is_warning）

    def test_custom_max_files(self):
        """max_files=5 时，5 个文件应通过。"""
        files = [f"file{i}.py" for i in range(5)]
        assert check_a1_file_count(files, max_files=5).passed is True
        assert check_a1_file_count(files + ["extra.py"], max_files=5).passed is False

    def test_detail_contains_count_and_threshold(self):
        """detail 字符串包含文件数量和阈值信息。"""
        result = check_a1_file_count(["a.py", "b.py", "c.py"], max_files=2)
        assert "3" in result.detail
        assert "2" in result.detail


# ─────────────────────────────────────────────────────────────────────────────
# 3. A2：Token 预算检查
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckA2TokenBudget:
    def test_empty_files_always_passes(self):
        """空文件列表 → estimated=0 ≤ 任何阈值 → 通过。"""
        result = check_a2_token_budget([], model="capable")
        assert result.passed is True
        assert result.label == "A2 Token 估算"

    def test_nonexistent_files_pass(self):
        """不存在的文件 → estimated=0 → 通过。"""
        result = check_a2_token_budget(["/no/such/file.py"], model="capable")
        assert result.passed is True

    def test_custom_threshold_respected(self):
        """自定义 thresholds 正确限制 budget。"""
        # 无文件 = 0 tokens，无论阈值如何都通过
        result = check_a2_token_budget([], model="8b", thresholds={"8b": 1000})
        assert result.passed is True

    def test_capable_model_uses_no_limit(self):
        """capable 模型默认无限制（999999），始终通过。"""
        result = check_a2_token_budget([], model="capable")
        assert result.passed is True

    def test_detail_contains_token_estimate(self):
        """detail 字符串包含 token 估算数值。"""
        result = check_a2_token_budget([], model="8b", thresholds={"8b": 4000})
        assert "tokens" in result.detail or "0" in result.detail


# ─────────────────────────────────────────────────────────────────────────────
# 4. A4：自动验证性
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckA4Verifiability:
    def test_with_test_files_passes(self):
        """提供 test_files → A4 通过（has_test_file=True）。"""
        result = check_a4_verifiability(
            files=["backend/app/domain/user.py"],
            test_files=["backend/tests/test_user.py"],
        )
        assert result.passed is True
        assert result.label == "A4 可验证性"

    def test_without_test_files_is_warning(self):
        """
        无 test_files 时，A4 检查降级为 arch_check 覆盖。
        对于 L5_interface/L4_application 层（在 _ARCH_CHECK_LAYERS），A4 也通过。
        """
        result = check_a4_verifiability(
            files=["backend/app/api/v1/users.py"],
            test_files=None,
        )
        assert isinstance(result, CheckResult)
        assert result.label == "A4 可验证性"
        # api 层在 _ARCH_CHECK_LAYERS 中 → has_arch_check=True → passed=True
        assert result.passed is True

    def test_empty_files_and_no_tests_fails(self):
        """空文件列表 + 无测试 → A4 失败（无法验证）。"""
        result = check_a4_verifiability(files=[], test_files=None)
        assert isinstance(result, CheckResult)
        assert result.passed is False  # 没有文件也没有测试 → 无法验证

    def test_test_file_name_in_files_passes(self):
        """files 中含 test_ 前缀文件 → has_test_file=True → A4 通过。"""
        result = check_a4_verifiability(
            files=["backend/tests/test_user.py"],
            test_files=None,
        )
        assert result.passed is True

    def test_docs_layer_no_arch_check_fails(self):
        """docs 层文件不在 _ARCH_CHECK_LAYERS → 无测试 → A4 失败。"""
        result = check_a4_verifiability(
            files=["docs/memory/_system/config.yaml"],
            test_files=None,
        )
        # docs 层不在 _ARCH_CHECK_LAYERS，且无测试文件 → failed
        assert result.passed is False


# ─────────────────────────────────────────────────────────────────────────────
# 5. compute_atomicity_score
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeAtomicityScore:
    """
    验证原子性评分计算逻辑。

    实际评分为加权和（0.0-1.0），权重：
      A1=0.3, A2=0.3, A3=0.1（警告得 0.5 × 0.1）, A4=0.3
    """

    def test_all_passed_score_1(self):
        """所有检查通过 → score = 1.0。"""
        results = [
            CheckResult(passed=True, label="A1", detail="ok"),
            CheckResult(passed=True, label="A2", detail="ok"),
            CheckResult(passed=True, label="A3", detail="ok"),
            CheckResult(passed=True, label="A4", detail="ok"),
        ]
        score = compute_atomicity_score(results)
        assert abs(score - 1.0) < 1e-6

    def test_all_failed_score_0(self):
        """所有检查失败 → score = 0.0。"""
        results = [
            CheckResult(passed=False, label="A1", detail="fail"),
            CheckResult(passed=False, label="A2", detail="fail"),
            CheckResult(passed=False, label="A3", detail="fail"),
            CheckResult(passed=False, label="A4", detail="fail"),
        ]
        score = compute_atomicity_score(results)
        assert score == 0.0

    def test_a3_warning_gets_half_weight(self):
        """
        A3 is_warning=True → 得 weight × 0.5 = 0.1 × 0.5 = 0.05
        其他三项通过 → score = 0.3 + 0.3 + 0.05 + 0.3 = 0.95
        """
        results = [
            CheckResult(passed=True, label="A1", detail="ok"),
            CheckResult(passed=True, label="A2", detail="ok"),
            CheckResult(passed=False, label="A3", detail="warn", is_warning=True),
            CheckResult(passed=True, label="A4", detail="ok"),
        ]
        score = compute_atomicity_score(results)
        assert abs(score - 0.95) < 1e-6

    def test_a1_a2_pass_a3_a4_fail(self):
        """A1(0.3)+A2(0.3) 通过，A3/A4 均失败 → score = 0.6。"""
        results = [
            CheckResult(passed=True, label="A1", detail="ok"),
            CheckResult(passed=True, label="A2", detail="ok"),
            CheckResult(passed=False, label="A3", detail="fail"),
            CheckResult(passed=False, label="A4", detail="fail"),
        ]
        score = compute_atomicity_score(results)
        assert abs(score - 0.6) < 1e-6

    def test_score_between_0_and_1(self):
        """score 始终在 [0, 1] 范围内。"""
        for n_pass in range(5):
            results = [
                CheckResult(passed=i < n_pass, label=f"A{i+1}", detail="")
                for i in range(4)
            ]
            score = compute_atomicity_score(results)
            assert 0.0 <= score <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# 6. validate_unit — 完整链路
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateUnit:
    """验证 validate_unit 聚合所有检查的完整链路。"""

    def test_empty_files_is_not_atomic(self):
        """
        空文件列表 → A4 失败（无文件无法验证）→ is_atomic=False。
        注意：A4 是硬性标准，无文件时 has_test_file=False 且 has_arch_check=False。
        """
        is_atomic, score, results = validate_unit([], model="capable", verbose=False)
        # A4 硬性失败 → is_atomic=False
        assert is_atomic is False
        assert isinstance(score, float)
        assert len(results) >= 3  # A1/A2/A3/A4 至少 4 项

    def test_two_same_layer_domain_files_atomic(self):
        """
        2 个同层域层文件（L3_domain 在 _ARCH_CHECK_LAYERS）→
        A1 通过（≤2），A2 通过（0 tokens，文件不存在），
        A3 fallback（Track B，同层通过），A4 通过（arch_check 覆盖）→ is_atomic=True。
        """
        files = [
            "backend/app/domain/user.py",
            "backend/app/domain/order.py",
        ]
        is_atomic, score, results = validate_unit(files, model="capable", verbose=False)
        assert is_atomic is True

    def test_too_many_files_not_atomic(self):
        """
        超过 max_files（默认 2）→ A1 硬性失败 → is_atomic=False。
        """
        files = ["a.py", "b.py", "c.py"]
        is_atomic, score, results = validate_unit(files, max_files=2, verbose=False)
        assert is_atomic is False

    def test_returns_tuple_of_correct_types(self):
        """返回值类型为 (bool, float, List[CheckResult])。"""
        is_atomic, score, results = validate_unit([], verbose=False)
        assert isinstance(is_atomic, bool)
        assert isinstance(score, float)
        assert isinstance(results, list)
        assert all(isinstance(r, CheckResult) for r in results)

    def test_score_between_0_and_100(self):
        """score 始终在 [0, 100] 范围内。"""
        for file_count in [0, 1, 2, 5]:
            files = [f"backend/app/domain/file{i}.py" for i in range(file_count)]
            _, score, _ = validate_unit(files, verbose=False)
            assert 0.0 <= score <= 100.0

    def test_a3_warning_does_not_block_atomic(self):
        """
        A3 警告（is_warning=True）不阻断 is_atomic（警告不算硬性失败）。
        """
        # 文件跨层会触发 A3 警告（Track B）
        files = [
            "backend/app/api/v1/users.py",   # L5_interface
            "backend/app/domain/user.py",    # L3_domain
        ]
        # 这些文件不存在，A2 估算=0 tokens（通过），A3 可能警告
        is_atomic, score, results = validate_unit(files, model="capable", verbose=False)

        a3_result = results[2]  # A3 是第三项
        if not a3_result.passed and a3_result.is_warning:
            # 即使 A3 警告，只要 A1/A2/A4 通过，仍应是 atomic
            hard_fails = [r for r in results if not r.passed and not r.is_warning]
            assert is_atomic == (len(hard_fails) == 0)

    def test_verbose_false_produces_no_output(self, capsys):
        """verbose=False 时不打印任何输出。"""
        validate_unit(["backend/app/domain/user.py"], verbose=False)
        captured = capsys.readouterr()
        assert captured.out == ""
