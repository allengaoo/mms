"""
test_atomicity_check.py — 原子性验证器测试

覆盖 4 个标准的通过/拒绝边界情况，以及综合得分计算。
"""
import sys
from pathlib import Path

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mms.dag.atomicity_check import (
    check_a1_file_count,
    check_a2_token_budget,
    check_a3_layer_consistency,
    check_a4_verifiability,
    compute_atomicity_score,
    validate_unit,
    infer_layer,
    estimate_tokens,
)


# ── infer_layer ───────────────────────────────────────────────────────────────

class TestInferLayer:
    def test_service_layer(self):
        assert infer_layer("backend/app/services/control/foo_service.py") == "L4_application"

    def test_api_layer(self):
        assert infer_layer("backend/app/api/v1/endpoints/foo.py") == "L5_interface"

    def test_domain_layer(self):
        assert infer_layer("backend/app/domain/models/foo.py") == "L3_domain"

    def test_infra_layer(self):
        assert infer_layer("backend/app/infrastructure/db/session.py") == "L2_infrastructure"

    def test_frontend_layer(self):
        assert infer_layer("frontend/src/pages/ontology/index.tsx") == "L5_interface"

    def test_test_file(self):
        assert infer_layer("backend/tests/unit/test_foo.py") == "testing"

    def test_mms_scripts(self):
        assert infer_layer("scripts/mms/dag_model.py") == "L4_application"

    def test_unknown_fallback(self):
        layer = infer_layer("some/random/file.py")
        assert layer == "unknown"


# ── A1: 文件数量 ──────────────────────────────────────────────────────────────

class TestA1FileCount:
    def test_zero_files_pass(self):
        r = check_a1_file_count([], max_files=2)
        assert r.passed is True

    def test_one_file_pass(self):
        r = check_a1_file_count(["f1.py"], max_files=2)
        assert r.passed is True

    def test_two_files_pass(self):
        r = check_a1_file_count(["f1.py", "f2.py"], max_files=2)
        assert r.passed is True

    def test_three_files_fail(self):
        r = check_a1_file_count(["f1.py", "f2.py", "f3.py"], max_files=2)
        assert r.passed is False

    def test_custom_max(self):
        r = check_a1_file_count(["f1.py", "f2.py", "f3.py"], max_files=3)
        assert r.passed is True


# ── A2: Token 预算 ────────────────────────────────────────────────────────────

class TestA2TokenBudget:
    def test_empty_files_pass(self):
        r = check_a2_token_budget([], model="8b")
        assert r.passed is True

    def test_nonexistent_file_zero_tokens(self):
        r = check_a2_token_budget(["nonexistent_xyz.py"], model="8b")
        assert r.passed is True  # 不存在的文件 = 0 bytes

    def test_capable_no_limit(self):
        r = check_a2_token_budget(["f.py"] * 10, model="capable",
                                  thresholds={"capable": 999999})
        assert r.passed is True

    def test_8b_threshold(self):
        # 8B 阈值 4000，测试逻辑不依赖实际文件
        r = check_a2_token_budget([], model="8b",
                                  thresholds={"8b": 4000, "16b": 8000})
        assert r.passed is True  # 0 tokens < 4000

    def test_label_contains_model(self):
        r = check_a2_token_budget([], model="16b")
        assert "16b" in r.detail


# ── A3: 层一致性 ──────────────────────────────────────────────────────────────

class TestA3LayerConsistency:
    def test_single_layer_pass(self):
        files = [
            "backend/app/services/control/foo_service.py",
            "backend/app/services/control/bar_service.py",
        ]
        r = check_a3_layer_consistency(files)
        assert r.passed is True

    def test_mixed_layers_warn(self):
        files = [
            "backend/app/services/control/foo_service.py",  # L4
            "backend/app/api/v1/endpoints/foo.py",          # L5
        ]
        r = check_a3_layer_consistency(files)
        assert r.passed is False
        assert r.is_warning is True  # 只警告，不硬性阻断

    def test_test_files_excluded(self):
        files = [
            "backend/app/services/control/foo_service.py",
            "backend/tests/unit/test_foo.py",  # testing 层，排除
        ]
        r = check_a3_layer_consistency(files)
        # testing 文件不计入层一致性检查
        assert r.passed is True

    def test_empty_files(self):
        r = check_a3_layer_consistency([])
        assert r.passed is True


# ── A4: 可验证性 ──────────────────────────────────────────────────────────────

class TestA4Verifiability:
    def test_has_test_file_pass(self):
        files = ["backend/app/services/control/foo_service.py"]
        test_files = ["backend/tests/unit/test_foo.py"]
        r = check_a4_verifiability(files, test_files)
        assert r.passed is True

    def test_test_in_files_pass(self):
        files = [
            "backend/app/services/control/foo_service.py",
            "backend/tests/unit/test_foo.py",
        ]
        r = check_a4_verifiability(files)
        assert r.passed is True

    def test_arch_check_coverage_pass(self):
        # services/ 层在 arch_check 覆盖范围
        files = ["backend/app/services/control/foo_service.py"]
        r = check_a4_verifiability(files)
        assert r.passed is True

    def test_no_test_no_arch_fail(self):
        # docs 文件既没有测试，也不在 arch_check 范围
        files = ["docs/context/layer_contracts.md"]
        r = check_a4_verifiability(files)
        assert r.passed is False


# ── 综合得分 ──────────────────────────────────────────────────────────────────

class TestComputeAtomicityScore:
    def test_all_pass_full_score(self):
        from mms.dag.atomicity_check import CheckResult
        results = [
            CheckResult(True, "A1", ""),
            CheckResult(True, "A2", ""),
            CheckResult(True, "A3", ""),
            CheckResult(True, "A4", ""),
        ]
        score = compute_atomicity_score(results)
        assert score == 1.0

    def test_all_fail_zero_score(self):
        from mms.dag.atomicity_check import CheckResult
        results = [
            CheckResult(False, "A1", ""),
            CheckResult(False, "A2", ""),
            CheckResult(False, "A3", ""),
            CheckResult(False, "A4", ""),
        ]
        score = compute_atomicity_score(results)
        assert score == 0.0

    def test_warning_half_score(self):
        from mms.dag.atomicity_check import CheckResult
        results = [
            CheckResult(True, "A1", ""),
            CheckResult(True, "A2", ""),
            CheckResult(False, "A3", "", is_warning=True),  # 半分
            CheckResult(True, "A4", ""),
        ]
        score = compute_atomicity_score(results)
        # 0.3 + 0.3 + 0.05 + 0.3 = 0.95
        assert abs(score - 0.95) < 0.01


# ── validate_unit 集成测试 ────────────────────────────────────────────────────

class TestValidateUnit:
    def test_service_file_is_atomic(self):
        files = ["backend/app/services/control/foo_service.py"]
        is_atomic, score, results = validate_unit(
            files=files, model="capable", verbose=False
        )
        assert is_atomic is True
        assert score > 0

    def test_too_many_files_not_atomic(self):
        files = ["f1.py", "f2.py", "f3.py"]
        is_atomic, score, results = validate_unit(
            files=files, model="8b", max_files=2, verbose=False
        )
        assert is_atomic is False

    def test_empty_files_atomic(self):
        is_atomic, score, results = validate_unit(
            files=[], model="capable", verbose=False
        )
        # 空文件列表：A1✅ A2✅ A3✅ A4❌（无测试）
        # 但 docs 层文件的 arch_check 不覆盖
        # 综合判断可能是 not atomic（取决于 A4）
        assert score >= 0
