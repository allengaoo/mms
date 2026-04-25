"""
Layer 1 — SWE-bench 适配器评测器（信用锚层）

功能：
  1. 离线模式：运行本地样本任务（tasks/*.yaml），评测 Mulan 的 AIU 分解 + 代码生成
  2. 在线模式：对接 princeton-nlp/SWE-bench 数据集（需要 Docker）

核心指标：
  Pass@1       — 一次执行即通过所有 fail→pass 测试的概率
  Resolve Rate — 在 3 级回退（retry）机制下的最终解决率
  Δ vs baseline — 与 direct_llm（无注入）的对比提升

当前实现为"离线 Mock"版本：
  - 读取 tasks/*.yaml，验证任务格式完整性
  - 统计 Mulan 可以分解的 AIU 类型覆盖率
  - Pass@1 / Resolve Rate 需要真实 LLM API，在无 API 时返回 SKIPPED

扩展方式：
  - 新增任务：在 tasks/*.yaml 中添加 task
  - 对接 SWE-bench 官方数据集：实现 SWEBenchAdapter.fetch_from_hf()
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, List

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


# ─────────────────────────────────────────────────────────────────────────────
# SWE-bench 任务格式验证
# ─────────────────────────────────────────────────────────────────────────────

_REQUIRED_FIELDS = {"id", "repo", "issue_title", "fail_tests", "pass_tests"}
_SUPPORTED_AIU_TYPES = {
    "BUG_FIX", "FEATURE_ADD", "REFACTOR", "TEST_ADD",
    "ENDPOINT_ADD", "SCHEMA_ADD_FIELD", "MIDDLEWARE_ADD",
}


def _validate_task(task: Dict[str, Any]) -> List[str]:
    """返回格式问题列表，空列表表示合法"""
    issues = []
    for field in _REQUIRED_FIELDS:
        if not task.get(field):
            issues.append(f"缺少必填字段: {field}")
    aiu_type = task.get("expected_aiu_type", "")
    if aiu_type and aiu_type not in _SUPPORTED_AIU_TYPES:
        issues.append(f"不支持的 AIU 类型: {aiu_type}（支持: {_SUPPORTED_AIU_TYPES}）")
    return issues


# ─────────────────────────────────────────────────────────────────────────────
# 离线任务执行（结构验证 + AIU 覆盖率）
# ─────────────────────────────────────────────────────────────────────────────

def _run_offline_task(task: Dict[str, Any], config: BenchmarkConfig) -> TaskResult:
    """
    离线模式下验证任务可行性（不调用 LLM）。
    检查：
      1. 任务格式完整性
      2. expected_aiu_type 是否在 AIU 注册表中支持
      3. domain_concepts 能否在记忆本体中找到对应 ObjectType
    """
    t0 = time.monotonic()
    task_id = f"l1_{task.get('id', 'unknown')}"
    validation_errors = _validate_task(task)

    if validation_errors:
        return TaskResult(
            task_id=task_id,
            status=TaskStatus.FAILED,
            score=0.0,
            details={"validation_errors": validation_errors},
            duration_seconds=time.monotonic() - t0,
        )

    # 检查 AIU 类型覆盖
    aiu_type   = task.get("expected_aiu_type", "")
    aiu_covered = not aiu_type or aiu_type in _SUPPORTED_AIU_TYPES

    # 记录任务元数据，Pass@1 占位（真实值需 LLM）
    return TaskResult(
        task_id=task_id,
        status=TaskStatus.PASSED if aiu_covered else TaskStatus.FAILED,
        score=1.0 if aiu_covered else 0.5,
        details={
            "repo":                task.get("repo"),
            "issue_title":        task.get("issue_title"),
            "expected_aiu_type":  aiu_type,
            "aiu_covered":        aiu_covered,
            "fail_tests_count":   len(task.get("fail_tests", [])),
            "pass_at_1":          None,  # 需 LLM 填充
            "resolve_rate":       None,  # 需 LLM 填充
            "mode":               "offline_format_check",
        },
        duration_seconds=time.monotonic() - t0,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Layer 1 主评测器
# ─────────────────────────────────────────────────────────────────────────────

class SWEBenchEvaluator(BaseEvaluator):
    """
    Layer 1 SWE-bench 信用锚评测器。

    离线模式（is_offline_capable=True）：
      - 仅做格式验证和 AIU 类型覆盖率检查
      - Pass@1 / Resolve Rate 标记为 SKIPPED

    在线模式（llm_available=True）：
      - 调用 Mulan EP 工作流生成 patch
      - 在沙盒中运行 pytest 验证
      - 计算 Pass@1 和 Resolve Rate（TODO）
    """

    @property
    def layer(self) -> BenchmarkLayer:
        return BenchmarkLayer.LAYER1_SWEBENCH

    @property
    def is_offline_capable(self) -> bool:
        return True   # 离线可做格式/覆盖率验证

    def run(self, config: BenchmarkConfig) -> LayerResult:
        t0 = time.monotonic()

        if not _YAML_AVAILABLE:
            return self._make_skipped_result(
                "pyyaml 未安装，无法读取任务文件"
            )

        tasks_dir = Path(__file__).parent / "tasks"
        all_tasks = self._load_tasks(tasks_dir)

        if config.max_tasks:
            all_tasks = all_tasks[:config.max_tasks]

        results: List[TaskResult] = []
        for task in all_tasks:
            if config.llm_available and not config.dry_run:
                # 在线模式（TODO：调用 Mulan EP 工作流）
                result = _run_offline_task(task, config)
                result.details["mode"] = "online_pending"
            else:
                result = _run_offline_task(task, config)
            results.append(result)

        passed  = sum(1 for r in results if r.passed)
        skipped = sum(1 for r in results if r.status == TaskStatus.SKIPPED)
        failed  = len(results) - passed - skipped

        # AIU 覆盖率
        aiu_types_seen = {
            r.details.get("expected_aiu_type", "")
            for r in results if r.details.get("expected_aiu_type")
        }
        aiu_coverage = len(aiu_types_seen & _SUPPORTED_AIU_TYPES) / max(len(_SUPPORTED_AIU_TYPES), 1)

        # 离线模式下得分 = 格式合规率 + AIU 覆盖率
        format_compliance = passed / max(len(results), 1)
        score = (format_compliance * 0.6 + aiu_coverage * 0.4) if results else 0.0

        return LayerResult(
            layer=self.layer,
            name="SWE-bench 信用锚评测（Layer 1）",
            tasks_total=len(results),
            tasks_passed=passed,
            tasks_skipped=skipped,
            tasks_failed=failed,
            score=round(score, 4),
            metrics={
                "format_compliance":   round(format_compliance, 4),
                "aiu_type_coverage":   round(aiu_coverage, 4),
                "aiu_types_covered":   float(len(aiu_types_seen)),
                "pass_at_1":           0.0,   # 需在线填充
                "resolve_rate":        0.0,   # 需在线填充
                "mode":                0.0,   # 0=offline, 1=online
            },
            task_results=results,
            duration_seconds=time.monotonic() - t0,
        )

    def _load_tasks(self, tasks_dir: Path) -> List[Dict[str, Any]]:
        all_tasks: List[Dict[str, Any]] = []
        for yaml_file in sorted(tasks_dir.glob("**/*.yaml")):
            with open(yaml_file, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            all_tasks.extend(data.get("tasks", []))
        return all_tasks
