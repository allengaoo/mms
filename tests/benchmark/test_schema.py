"""
Benchmark v2 Schema 基础结构单元测试
"""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from benchmark.v2.schema import (
    BenchmarkConfig,
    BenchmarkLayer,
    BenchmarkResult,
    LayerResult,
    RunLevel,
    TaskResult,
    TaskStatus,
)


class TestTaskResult:
    def test_passed_property(self):
        tr = TaskResult(task_id="t1", status=TaskStatus.PASSED, score=1.0)
        assert tr.passed is True

    def test_failed_not_passed(self):
        tr = TaskResult(task_id="t2", status=TaskStatus.FAILED, score=0.0)
        assert tr.passed is False

    def test_skipped_not_passed(self):
        tr = TaskResult(task_id="t3", status=TaskStatus.SKIPPED, score=0.0)
        assert tr.passed is False


class TestLayerResult:
    def _make(self, passed, total, skipped=0):
        return LayerResult(
            layer=BenchmarkLayer.LAYER3_SAFETY,
            name="test",
            tasks_total=total,
            tasks_passed=passed,
            tasks_skipped=skipped,
            tasks_failed=total - passed - skipped,
            score=passed / max(total, 1),
        )

    def test_pass_rate_calculation(self):
        lr = self._make(8, 10)
        assert lr.pass_rate == 0.8

    def test_zero_total_pass_rate(self):
        lr = self._make(0, 0)
        assert lr.pass_rate == 0.0

    def test_skip_rate_calculation(self):
        lr = self._make(passed=5, total=10, skipped=3)
        assert lr.skip_rate == 0.3


class TestBenchmarkResult:
    def test_overall_score_average(self):
        result = BenchmarkResult()
        result.layer_results[3] = LayerResult(
            layer=BenchmarkLayer.LAYER3_SAFETY,
            name="L3", tasks_total=10, tasks_passed=8,
            tasks_skipped=0, tasks_failed=2, score=0.8,
        )
        result.layer_results[2] = LayerResult(
            layer=BenchmarkLayer.LAYER2_MEMORY,
            name="L2", tasks_total=5, tasks_passed=4,
            tasks_skipped=0, tasks_failed=1, score=0.6,
        )
        assert result.overall_score == 0.7

    def test_empty_result_score_zero(self):
        result = BenchmarkResult()
        assert result.overall_score == 0.0

    def test_get_layer(self):
        result = BenchmarkResult()
        lr = LayerResult(
            layer=BenchmarkLayer.LAYER3_SAFETY,
            name="L3", tasks_total=1, tasks_passed=1,
            tasks_skipped=0, tasks_failed=0, score=1.0,
        )
        result.layer_results[3] = lr
        assert result.get_layer(BenchmarkLayer.LAYER3_SAFETY) is lr
        assert result.get_layer(BenchmarkLayer.LAYER2_MEMORY) is None


class TestBenchmarkConfig:
    def test_default_config(self):
        config = BenchmarkConfig()
        assert config.level == RunLevel.OFFLINE_ONLY
        assert config.dry_run is False
        assert config.llm_available is False

    def test_offline_only_layer_list(self):
        config = BenchmarkConfig(level=RunLevel.OFFLINE_ONLY)
        assert BenchmarkLayer.LAYER3_SAFETY in config.layers
