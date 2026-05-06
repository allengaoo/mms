"""
Layer 2 记忆质量单元测试

覆盖：
  - 检索指标计算函数
  - 漂移检测（离线临时目录模拟）
  - 注入提升（离线跳过逻辑）
  - MemoryEvaluator 集成（加载 YAML 任务）
"""
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from benchmark.v2.schema import BenchmarkConfig, BenchmarkLayer, RunLevel, TaskStatus
from benchmark.v2.layer2_memory.metrics.retrieval import compute_retrieval_metrics, aggregate_retrieval_metrics, RetrievalResult
from benchmark.v2.layer2_memory.metrics.drift import DriftCase, evaluate_drift, aggregate_drift_metrics
from benchmark.v2.layer2_memory.metrics.injection_lift import mock_injection_lift_result, InjectionLiftCase
from benchmark.v2.layer2_memory.evaluator import MemoryEvaluator


# ─────────────────────────────────────────────────────────────────────────────
# 检索指标计算
# ─────────────────────────────────────────────────────────────────────────────

class TestRetrievalMetrics:
    def test_perfect_recall(self):
        retrieved = ["A", "B", "C"]
        relevant  = {"A", "B", "C"}
        m = compute_retrieval_metrics(retrieved, relevant, k=3)
        assert m["recall_at_k"] == 1.0
        assert m["precision_at_k"] == 1.0
        assert m["hit_at_1"] == 1.0

    def test_zero_recall(self):
        retrieved = ["X", "Y", "Z"]
        relevant  = {"A", "B"}
        m = compute_retrieval_metrics(retrieved, relevant, k=3)
        assert m["recall_at_k"] == 0.0
        assert m["hit_at_1"] == 0.0

    def test_partial_recall(self):
        retrieved = ["A", "X", "B", "Y"]
        relevant  = {"A", "B", "C"}
        m = compute_retrieval_metrics(retrieved, relevant, k=4)
        assert m["recall_at_k"] == pytest.approx(2 / 3, abs=0.01)

    def test_mrr_first_relevant_at_rank2(self):
        retrieved = ["X", "A", "Y"]
        relevant  = {"A"}
        m = compute_retrieval_metrics(retrieved, relevant, k=5)
        assert m["mrr"] == pytest.approx(0.5, abs=0.01)

    def test_hit_at_1_true(self):
        retrieved = ["A", "X"]
        relevant  = {"A"}
        m = compute_retrieval_metrics(retrieved, relevant, k=2)
        assert m["hit_at_1"] == 1.0

    def test_empty_retrieved(self):
        m = compute_retrieval_metrics([], {"A", "B"}, k=5)
        assert m["recall_at_k"] == 0.0
        assert m["mrr"] == 0.0

    def test_aggregate_metrics(self):
        results = [
            RetrievalResult("c1", recall_at_k=0.8, precision_at_k=0.8, mrr=0.9, hit_at_1=1.0, retrieved=[]),
            RetrievalResult("c2", recall_at_k=0.4, precision_at_k=0.4, mrr=0.5, hit_at_1=0.0, retrieved=[]),
        ]
        agg = aggregate_retrieval_metrics(results)
        assert agg["recall_at_k"] == pytest.approx(0.6, abs=0.01)


# ─────────────────────────────────────────────────────────────────────────────
# 漂移检测
# ─────────────────────────────────────────────────────────────────────────────

class TestDriftDetection:
    _MEM_TMPL = """\
---
id: MEM-DRIFT-001
layer: L3_domain
tier: warm
cites_files:
  - "{cited_file}"
---
# 测试记忆
函数签名为 get_by_id(user_id: str)。
"""

    def _make_case(self, orig, modified, should_drift, suffix=""):
        return DriftCase(
            case_id=f"test_{suffix}",
            description="test",
            memory_content=self._MEM_TMPL,
            cited_file_content=orig,
            modified_content=modified,
            should_drift=should_drift,
        )

    def test_signature_change_detected(self):
        pytest.importorskip("mms.memory.freshness_checker",
                            reason="freshness_checker 不可用，跳过")
        orig     = "async def get_by_id(user_id: str) -> UserDTO:\n    pass\n"
        modified = "async def get_by_id(user_id: uuid.UUID, tenant: str) -> UserDTO:\n    pass\n"
        case = self._make_case(orig, modified, should_drift=True, suffix="sig_change")
        result = evaluate_drift(case)
        assert result.passed, f"应检测到 drift，但未检测到: {result}"

    def test_comment_only_change_no_drift(self):
        pytest.importorskip("mms.memory.freshness_checker",
                            reason="freshness_checker 不可用，跳过")
        orig     = "async def get_by_id(user_id: str) -> UserDTO:\n    pass\n"
        modified = "# 查询用户\nasync def get_by_id(user_id: str) -> UserDTO:\n    \"\"\"查询用户\"\"\"\n    pass\n"
        case = self._make_case(orig, modified, should_drift=False, suffix="comment")
        result = evaluate_drift(case)
        assert result.passed, f"注释变化不应触发 drift，但触发了: {result}"

    def test_aggregate_drift_metrics_empty(self):
        metrics = aggregate_drift_metrics([])
        assert metrics == {}


# ─────────────────────────────────────────────────────────────────────────────
# 注入提升（离线跳过）
# ─────────────────────────────────────────────────────────────────────────────

class TestInjectionLift:
    def test_mock_returns_skipped(self):
        case = InjectionLiftCase(
            case_id="test_001",
            description="test",
            domain="generic_python",
            task_description="add rate limiting",
            required_imports=["fastapi"],
        )
        result = mock_injection_lift_result(case)
        assert result.skipped is True
        assert result.skip_reason != ""


# ─────────────────────────────────────────────────────────────────────────────
# MemoryEvaluator 集成
# ─────────────────────────────────────────────────────────────────────────────

class TestMemoryEvaluator:
    def setup_method(self):
        self.config = BenchmarkConfig(
            level=RunLevel.OFFLINE_ONLY,
            layers=[BenchmarkLayer.LAYER2_MEMORY],
            domains=["generic_python"],
            llm_available=False,
            dry_run=False,
        )

    def test_evaluator_runs_without_error(self):
        pytest.importorskip("yaml", reason="pyyaml 未安装")
        ev = MemoryEvaluator()
        result = ev.run(self.config)
        assert result.layer == BenchmarkLayer.LAYER2_MEMORY

    def test_score_in_range(self):
        pytest.importorskip("yaml", reason="pyyaml 未安装")
        ev = MemoryEvaluator()
        result = ev.run(self.config)
        assert 0.0 <= result.score <= 1.0

    def test_d1_tasks_loaded(self):
        """D1 任务文件应能被加载（即使全部 SKIPPED 因 relevant_ids 为空）"""
        pytest.importorskip("yaml", reason="pyyaml 未安装")
        ev = MemoryEvaluator()
        result = ev.run(self.config)
        d1_tasks = [t for t in result.task_results if t.task_id.startswith("d1_")]
        assert len(d1_tasks) > 0, "应加载到 D1 检索任务"

    def test_d4_tasks_loaded(self):
        """D4 任务文件应能被加载"""
        pytest.importorskip("yaml", reason="pyyaml 未安装")
        ev = MemoryEvaluator()
        result = ev.run(self.config)
        d4_tasks = [t for t in result.task_results if t.task_id.startswith("d4_")]
        assert len(d4_tasks) > 0, "应加载到 D4 漂移检测任务"

    def test_is_offline_capable(self):
        ev = MemoryEvaluator()
        assert ev.is_offline_capable is True
