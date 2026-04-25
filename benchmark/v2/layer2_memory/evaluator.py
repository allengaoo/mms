"""
Layer 2 — 记忆质量评测器

四个子维度（参考 MemoryAgentBench 框架）：
  D1 准确检索（Accurate Retrieval）    — 离线可运行（需要记忆文件存在）
  D2 注入提升（Injection Lift）         — 需要 LLM API
  D3 跨任务保留（Cross-task Retention） — 需要 LLM API（暂为占位实现）
  D4 漂移检测（Selective Forgetting）   — 离线可运行

综合得分 = D1×0.35 + D2×0.35 + D4×0.30
（D3 在实验性阶段不计入综合得分，单独展示）

扩展方式：
  - 新增检索任务：在 tasks/<domain>/xxx_retrieval.yaml 中添加 case
  - 新增漂移场景：在 tasks/<domain>/xxx_drift.yaml 中添加 case
  - 新增 D2 注入任务：在 tasks/<domain>/xxx_injection.yaml 中添加 case
  - 新增 domain：创建 tasks/<new_domain>/ 目录，评测器自动加载
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent.parent
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

from benchmark.v2.schema import (
    BaseEvaluator,
    BenchmarkConfig,
    BenchmarkLayer,
    LayerResult,
    TaskResult,
    TaskStatus,
)
from benchmark.v2.layer2_memory.metrics.retrieval import (
    RetrievalCase,
    evaluate_retrieval,
    aggregate_retrieval_metrics,
)
from benchmark.v2.layer2_memory.metrics.injection_lift import (
    InjectionLiftCase,
    mock_injection_lift_result,
    compute_lift,
)
from benchmark.v2.layer2_memory.metrics.drift import (
    DriftCase,
    evaluate_drift,
    aggregate_drift_metrics,
)


# ─────────────────────────────────────────────────────────────────────────────
# 任务文件加载
# ─────────────────────────────────────────────────────────────────────────────

def _load_yaml_cases(directory: Path, category_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """从目录下所有 YAML 文件加载 case 列表"""
    cases: List[Dict[str, Any]] = []
    if not directory.exists():
        return cases
    for yaml_file in sorted(directory.glob("**/*.yaml")):
        if not _YAML_AVAILABLE:
            break
        with open(yaml_file, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        file_category = data.get("category", "")
        if category_filter and file_category != category_filter:
            continue
        cases.extend(data.get("cases", []))
    return cases


# ─────────────────────────────────────────────────────────────────────────────
# D1 检索子评测
# ─────────────────────────────────────────────────────────────────────────────

def _run_retrieval_dimension(
    task_dir: Path,
    memory_root: Path,
    config: BenchmarkConfig,
) -> List[TaskResult]:
    raw_cases = _load_yaml_cases(task_dir, "retrieval")
    if config.max_tasks:
        raw_cases = raw_cases[:config.max_tasks]

    results: List[TaskResult] = []
    for raw in raw_cases:
        t0 = time.monotonic()
        task_id = f"d1_{raw.get('id', 'unknown')}"
        relevant_ids = set(raw.get("relevant_ids", []))

        # 若 ground-truth 为空，跳过（需先建记忆库）
        if not relevant_ids:
            results.append(TaskResult(
                task_id=task_id,
                status=TaskStatus.SKIPPED,
                score=0.0,
                details={"reason": "relevant_ids 为空，请先填充记忆库"},
                duration_seconds=time.monotonic() - t0,
            ))
            continue

        case = RetrievalCase(
            case_id=task_id,
            query=raw.get("query", ""),
            relevant_ids=relevant_ids,
            k=raw.get("k", 5),
        )
        ret_result = evaluate_retrieval(case, memory_root)

        status  = TaskStatus.PASSED if ret_result.recall_at_k >= 0.6 else TaskStatus.FAILED
        results.append(TaskResult(
            task_id=task_id,
            status=status,
            score=ret_result.recall_at_k,
            details={
                "recall_at_k":    ret_result.recall_at_k,
                "precision_at_k": ret_result.precision_at_k,
                "mrr":            ret_result.mrr,
                "hit_at_1":       ret_result.hit_at_1,
                "retrieved":      ret_result.retrieved,
                "error":          ret_result.error,
            },
            duration_seconds=time.monotonic() - t0,
        ))
    return results


# ─────────────────────────────────────────────────────────────────────────────
# D2 注入提升子评测
# ─────────────────────────────────────────────────────────────────────────────

def _run_injection_dimension(
    task_dir: Path,
    config: BenchmarkConfig,
) -> List[TaskResult]:
    raw_cases = _load_yaml_cases(task_dir, "injection_lift")
    if config.max_tasks:
        raw_cases = raw_cases[:config.max_tasks]

    results: List[TaskResult] = []
    for raw in raw_cases:
        t0 = time.monotonic()
        task_id = f"d2_{raw.get('id', 'unknown')}"

        case = InjectionLiftCase(
            case_id=task_id,
            description=raw.get("description", ""),
            domain=raw.get("domain", ""),
            task_description=raw.get("task_description", ""),
            required_imports=raw.get("required_imports", []),
            forbidden_patterns=raw.get("forbidden_patterns", []),
        )

        if not config.llm_available or config.dry_run:
            lift_result = mock_injection_lift_result(case)
            results.append(TaskResult(
                task_id=task_id,
                status=TaskStatus.SKIPPED,
                score=0.0,
                details={"reason": lift_result.skip_reason},
                duration_seconds=time.monotonic() - t0,
            ))
        else:
            # 真实 LLM 评测（留作扩展点）
            results.append(TaskResult(
                task_id=task_id,
                status=TaskStatus.SKIPPED,
                score=0.0,
                details={"reason": "LLM 注入提升评测待实现（参见 injection_lift.py）"},
                duration_seconds=time.monotonic() - t0,
            ))
    return results


# ─────────────────────────────────────────────────────────────────────────────
# D4 漂移检测子评测
# ─────────────────────────────────────────────────────────────────────────────

def _run_drift_dimension(
    task_dir: Path,
    config: BenchmarkConfig,
) -> List[TaskResult]:
    raw_cases = _load_yaml_cases(task_dir, "drift")
    if config.max_tasks:
        raw_cases = raw_cases[:config.max_tasks]

    results: List[TaskResult] = []
    for raw in raw_cases:
        t0 = time.monotonic()
        task_id = f"d4_{raw.get('id', 'unknown')}"

        case = DriftCase(
            case_id=task_id,
            description=raw.get("description", ""),
            memory_content=raw.get("memory_content", ""),
            cited_file_content=raw.get("cited_file_content", ""),
            modified_content=raw.get("modified_content", ""),
            should_drift=raw.get("should_drift", True),
        )

        drift_result = evaluate_drift(case)
        status = TaskStatus.PASSED if drift_result.passed else TaskStatus.FAILED

        results.append(TaskResult(
            task_id=task_id,
            status=status,
            score=1.0 if drift_result.passed else 0.0,
            details={
                "should_drift":   case.should_drift,
                "detected_drift": drift_result.detected_drift,
                "latency_ms":     drift_result.latency_ms,
                "error":          drift_result.error,
            },
            duration_seconds=time.monotonic() - t0,
        ))
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Layer 2 主评测器
# ─────────────────────────────────────────────────────────────────────────────

class MemoryEvaluator(BaseEvaluator):
    """
    Layer 2 记忆质量综合评测器。

    扩展维度（D3 跨任务保留）在未来版本实现，当前返回 SKIPPED。
    """

    _WEIGHTS = {"d1": 0.35, "d2": 0.35, "d4": 0.30}

    @property
    def layer(self) -> BenchmarkLayer:
        return BenchmarkLayer.LAYER2_MEMORY

    @property
    def is_offline_capable(self) -> bool:
        return True   # D1 和 D4 离线可运行；D2 在无 LLM 时跳过

    def run(self, config: BenchmarkConfig) -> LayerResult:
        t0 = time.monotonic()

        if not _YAML_AVAILABLE:
            return self._make_skipped_result(
                "pyyaml 未安装，无法读取任务文件。请运行: pip install pyyaml"
            )

        tasks_root  = Path(__file__).parent / "tasks"
        # 确定记忆库路径（优先使用 config.repo_root）
        repo_root   = Path(config.repo_root) if config.repo_root else _ROOT
        memory_root = repo_root / "docs" / "memory"

        all_d1: List[TaskResult] = []
        all_d2: List[TaskResult] = []
        all_d4: List[TaskResult] = []

        # 遍历所有请求的 domain
        for domain in config.domains:
            domain_dir = tasks_root / domain
            if not domain_dir.exists():
                continue
            all_d1.extend(_run_retrieval_dimension(domain_dir, memory_root, config))
            all_d2.extend(_run_injection_dimension(domain_dir, config))
            all_d4.extend(_run_drift_dimension(domain_dir, config))

        all_results = all_d1 + all_d2 + all_d4

        def _pass_rate(results: List[TaskResult]) -> float:
            non_skip = [r for r in results if r.status != TaskStatus.SKIPPED]
            if not non_skip:
                return 0.0
            return sum(1 for r in non_skip if r.passed) / len(non_skip)

        d1_rate = _pass_rate(all_d1)
        d2_rate = _pass_rate(all_d2)
        d4_rate = _pass_rate(all_d4)

        # D2 全部跳过时，将其权重分给 D1 和 D4
        d2_skipped = all(r.status == TaskStatus.SKIPPED for r in all_d2) if all_d2 else True
        if d2_skipped:
            score = d1_rate * 0.55 + d4_rate * 0.45
        else:
            score = (
                self._WEIGHTS["d1"] * d1_rate +
                self._WEIGHTS["d2"] * d2_rate +
                self._WEIGHTS["d4"] * d4_rate
            )

        # 聚合分维度指标
        metrics: Dict[str, float] = {
            "d1.recall_pass_rate":     round(d1_rate, 4),
            "d2.injection_pass_rate":  round(d2_rate, 4),
            "d4.drift_detection_rate": round(d4_rate, 4),
            "overall.score":           round(score, 4),
            "tasks.d1_total": float(len(all_d1)),
            "tasks.d2_total": float(len(all_d2)),
            "tasks.d4_total": float(len(all_d4)),
        }

        passed  = sum(1 for r in all_results if r.passed)
        skipped = sum(1 for r in all_results if r.status == TaskStatus.SKIPPED)
        failed  = len(all_results) - passed - skipped

        return LayerResult(
            layer=self.layer,
            name="记忆质量评测（Layer 2）",
            tasks_total=len(all_results),
            tasks_passed=passed,
            tasks_skipped=skipped,
            tasks_failed=failed,
            score=score,
            metrics=metrics,
            task_results=all_results,
            duration_seconds=time.monotonic() - t0,
        )
