"""
Layer 1 SWE-bench 适配器单元测试
"""
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from benchmark.v2.schema import BenchmarkConfig, BenchmarkLayer, RunLevel
from benchmark.v2.layer1_swebench.evaluator import (
    SWEBenchEvaluator,
    _validate_task,
    _SUPPORTED_AIU_TYPES,
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
