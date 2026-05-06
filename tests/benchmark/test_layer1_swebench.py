"""
Layer 1 SWE-bench 适配器单元测试
"""
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from unittest.mock import patch
from benchmark.v2.schema import BenchmarkConfig, BenchmarkLayer, RunLevel
from benchmark.v2.layer1_swebench.evaluator import (
    SWEBenchEvaluator,
    _validate_task,
    _SUPPORTED_AIU_TYPES,
    DualRailResult,
    _call_baseline_llm,
    _call_mulan_enhanced,
)


class TestTaskValidation:
    def test_valid_task_no_errors(self):
        task = {
            "id": "swe_test_001",
            "repo": "django/django",
            "issue_title": "Test issue",
            "fail_tests": ["tests/test_foo.py::test_bar"],
            "pass_tests": ["tests/test_foo.py::test_bar"],
        }
        errors = _validate_task(task)
        assert errors == []

    def test_missing_required_fields(self):
        task = {"id": "swe_test_002"}
        errors = _validate_task(task)
        assert any("repo" in e for e in errors)
        assert any("fail_tests" in e for e in errors)

    def test_unsupported_aiu_type_flagged(self):
        task = {
            "id": "swe_test_003",
            "repo": "test/test",
            "issue_title": "test",
            "fail_tests": ["test.py::test"],
            "pass_tests": ["test.py::test"],
            "expected_aiu_type": "UNKNOWN_TYPE_XYZ",
        }
        errors = _validate_task(task)
        assert any("UNKNOWN_TYPE_XYZ" in e for e in errors)

    def test_supported_aiu_type_ok(self):
        for aiu_type in _SUPPORTED_AIU_TYPES:
            task = {
                "id": "swe_test",
                "repo": "test/test",
                "issue_title": "test",
                "fail_tests": ["t.py::t"],
                "pass_tests": ["t.py::t"],
                "expected_aiu_type": aiu_type,
            }
            assert _validate_task(task) == [], f"AIU type {aiu_type} 不应报错"


class TestSWEBenchEvaluator:
    def setup_method(self):
        self.config = BenchmarkConfig(
            level=RunLevel.OFFLINE_ONLY,
            layers=[BenchmarkLayer.LAYER1_SWEBENCH],
            llm_available=False,
            dry_run=False,
        )

    def test_evaluator_runs_without_error(self):
        pytest.importorskip("yaml", reason="pyyaml 未安装")
        ev = SWEBenchEvaluator()
        result = ev.run(self.config)
        assert result.layer == BenchmarkLayer.LAYER1_SWEBENCH

    def test_sample_tasks_loaded(self):
        pytest.importorskip("yaml", reason="pyyaml 未安装")
        ev = SWEBenchEvaluator()
        result = ev.run(self.config)
        assert result.tasks_total >= 3, "应至少加载 3 个样本任务"

    def test_score_in_range(self):
        pytest.importorskip("yaml", reason="pyyaml 未安装")
        ev = SWEBenchEvaluator()
        result = ev.run(self.config)
        assert 0.0 <= result.score <= 1.0

    def test_format_compliance_metric_present(self):
        pytest.importorskip("yaml", reason="pyyaml 未安装")
        ev = SWEBenchEvaluator()
        result = ev.run(self.config)
        assert "format_compliance" in result.metrics
        assert "aiu_type_coverage" in result.metrics

    def test_is_offline_capable(self):
        ev = SWEBenchEvaluator()
        assert ev.is_offline_capable is True

    def test_java_mall_tasks_loaded(self):
        """新增的 mall 订单 Java 任务应被自动加载。"""
        pytest.importorskip("yaml", reason="pyyaml 未安装")
        ev = SWEBenchEvaluator()
        result = ev.run(self.config)
        assert result.tasks_total >= 5, "加上 mall 任务后应至少 5 个"


class TestDualRailRunner:
    """在线模式双轨对比（DualRailResult + mock）。"""

    _TASK = {
        "id": "test_dual_001",
        "repo": "test/test",
        "issue_title": "测试双轨",
        "fail_tests": ["tests/test_foo.py::test_bar"],
        "pass_tests": ["tests/test_foo.py::test_bar"],
        "expected_aiu_type": "BUG_FIX",
    }

    def test_dual_rail_result_delta_calculation(self):
        """ΔPass@1 = mulan_pass - baseline_pass。"""
        dual = DualRailResult("t1", baseline_pass=False, mulan_pass=True)
        assert dual.delta_pass_at_1 == 1.0

    def test_dual_rail_result_no_improvement(self):
        dual = DualRailResult("t2", baseline_pass=True, mulan_pass=True)
        assert dual.delta_pass_at_1 == 0.0

    def test_dual_rail_result_regression(self):
        """Mulan 比 Baseline 差时 ΔPass@1 为负。"""
        dual = DualRailResult("t3", baseline_pass=True, mulan_pass=False)
        assert dual.delta_pass_at_1 == -1.0

    def test_info_density_zero_when_no_injection(self):
        """injection_tokens=0 时 info_density 应为 0（不除零）。"""
        dual = DualRailResult("t4", mulan_pass=True, injection_tokens=0)
        assert dual.info_density == 0.0

    def test_info_density_positive_when_improvement(self):
        """有注入 token 且 ΔPass@1 > 0 时 info_density > 0。"""
        dual = DualRailResult(
            "t5",
            baseline_pass=False,
            mulan_pass=True,
            injection_tokens=500,
        )
        assert dual.info_density > 0.0

    def test_online_mode_evaluator_with_mock(self):
        """在线模式下，mock LLM 调用，evaluator 不崩溃，返回在线 mode 指标。"""
        pytest.importorskip("yaml", reason="pyyaml 未安装")
        config = BenchmarkConfig(
            level=RunLevel.FAST,
            layers=[BenchmarkLayer.LAYER1_SWEBENCH],
            llm_available=True,   # 触发在线模式
            dry_run=False,
        )
        with patch(
            "benchmark.v2.layer1_swebench.evaluator._call_baseline_llm",
            return_value="",
        ), patch(
            "benchmark.v2.layer1_swebench.evaluator._call_mulan_enhanced",
            return_value=("", 0),
        ):
            ev = SWEBenchEvaluator()
            result = ev.run(config)

        assert result.layer == BenchmarkLayer.LAYER1_SWEBENCH
        assert 0.0 <= result.score <= 1.0
        assert "mode" in result.metrics
        assert result.metrics.get("mode") == 1.0  # 在线模式标识
        assert "avg_delta_pass_at_1" in result.metrics

    def test_baseline_placeholder_returns_empty(self):
        """占位实现返回空 patch。"""
        patch_str = _call_baseline_llm({"id": "x", "issue_title": "test"})
        assert isinstance(patch_str, str)

    def test_mulan_placeholder_returns_tuple(self):
        """占位实现返回 (str, int) 元组。"""
        patch_str, tokens = _call_mulan_enhanced({"id": "x"})
        assert isinstance(patch_str, str)
        assert isinstance(tokens, int)
