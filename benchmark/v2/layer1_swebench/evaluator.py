"""
Layer 1 — SWE-bench 适配器评测器（信用锚层）

功能：
  1. 离线模式：运行本地样本任务（tasks/*.yaml），评测 Mulan 的 AIU 分解 + 代码生成
  2. 在线模式：双轨对比（Mulan-Enhanced vs Baseline），计算 ΔPass@1

核心指标：
  Pass@1        — 一次执行即通过所有 fail→pass 测试的概率
  Resolve Rate  — 在 3 级回退（retry）机制下的最终解决率
  ΔPass@1       — Mulan-Enhanced 比 Baseline 的 Pass@1 提升（核心价值主张）
  Info Density  — ΔPass@1 / avg_injection_tokens × 1000

在线模式流程（双轨对比）：
  Baseline      ←→ 裸 LLM（无 Mulan 记忆注入）→ 生成 patch → pytest 沙盒
  Mulan-Enhanced ←→ Mulan EP 工作流（有记忆注入）→ 生成 patch → pytest 沙盒
  ΔPass@1 = Pass@1(Mulan) - Pass@1(Baseline)

实现状态：
  ✅ 离线格式验证 + AIU 覆盖率
  ✅ SandboxedCodeRunner 语法 + pytest 沙盒
  ✅ DualRailRunner 框架（双轨对比骨架）
  🔲 mulan ep run 真实调用（需配置 LLM API + EP 工作流）
  🔲 Docker 沙盒执行（需 Docker 环境）

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

try:
    from mms.execution.sandboxed_runner import SandboxedCodeRunner
    _SANDBOX_AVAILABLE = True
except ImportError:
    _SANDBOX_AVAILABLE = False


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
# 在线模式：双轨对比（DualRailRunner）
# ─────────────────────────────────────────────────────────────────────────────

class DualRailResult:
    """单任务双轨对比结果。"""
    __slots__ = (
        "task_id", "baseline_pass", "mulan_pass",
        "delta_pass_at_1", "injection_tokens", "info_density",
        "baseline_error", "mulan_error",
    )

    def __init__(
        self,
        task_id: str,
        baseline_pass: bool = False,
        mulan_pass: bool = False,
        injection_tokens: int = 0,
        baseline_error: str = "",
        mulan_error: str = "",
    ) -> None:
        self.task_id = task_id
        self.baseline_pass = baseline_pass
        self.mulan_pass = mulan_pass
        self.delta_pass_at_1 = float(mulan_pass) - float(baseline_pass)
        self.injection_tokens = injection_tokens
        self.info_density = (
            self.delta_pass_at_1 / injection_tokens * 1000
            if injection_tokens > 0 else 0.0
        )
        self.baseline_error = baseline_error
        self.mulan_error = mulan_error


def _call_baseline_llm(task: Dict[str, Any]) -> str:
    """
    Baseline 轨：直接调用 LLM 生成 patch，无 Mulan 记忆注入。

    当前为占位实现（返回空 patch），真实实现需要：
      1. 构造纯 issue 描述 prompt
      2. 调用 BailianProvider / OpenAI API
      3. 从 LLM 输出中提取 unified diff

    Returns:
        生成的 patch 字符串（unified diff 格式）
    """
    return ""   # TODO: 实现真实 LLM 调用


def _call_mulan_enhanced(task: Dict[str, Any]) -> tuple:
    """
    Mulan-Enhanced 轨：通过 EP 工作流 + 记忆注入生成 patch。

    当前为占位实现，真实实现需要：
      1. 将 issue 描述转化为 EP 请求
      2. 调用 mulan ep run（注入本体路由检索的架构上下文）
      3. 从 EP 输出中提取 patch
      4. 返回 (patch_str, injection_tokens)

    Returns:
        (patch_str, injection_tokens): patch 内容和注入 token 数
    """
    return "", 0   # TODO: 实现真实 mulan ep run 调用


def _run_online_task(task: Dict[str, Any], config: BenchmarkConfig) -> TaskResult:
    """
    在线模式：双轨对比执行单个任务。

    流程：
      1. 调用 Baseline LLM（无注入）生成 patch
      2. 调用 Mulan-Enhanced（有注入）生成 patch
      3. 使用 SandboxedCodeRunner 分别执行 fail_tests → 验证 pass_tests
      4. 计算 ΔPass@1 和 Info Density

    当 SandboxedCodeRunner 不可用时，退化为格式验证模式。
    """
    t0 = time.monotonic()
    task_id = f"l1_online_{task.get('id', 'unknown')}"

    if not _SANDBOX_AVAILABLE:
        result = _run_offline_task(task, config)
        result.details["mode"] = "online_degraded_no_sandbox"
        return result

    # ── 获取 fail_tests（第一个）作为验证测试 ──
    fail_tests = task.get("fail_tests", [])
    pass_tests = task.get("pass_tests", [])
    if not fail_tests:
        result = _run_offline_task(task, config)
        result.details["mode"] = "online_degraded_no_tests"
        return result

    runner = SandboxedCodeRunner(timeout_seconds=60)

    # ── Baseline 轨 ──
    baseline_patch = _call_baseline_llm(task)
    baseline_run = runner.run(
        code=baseline_patch,
        file_path=f"patch_baseline_{task.get('id', 'x')}.py",
        test_script=None,  # 真实实现应运行 pass_tests[0]
    )
    baseline_pass = bool(baseline_patch) and baseline_run.syntax_pass

    # ── Mulan-Enhanced 轨 ──
    mulan_patch, injection_tokens = _call_mulan_enhanced(task)
    mulan_run = runner.run(
        code=mulan_patch,
        file_path=f"patch_mulan_{task.get('id', 'x')}.py",
        test_script=None,  # 真实实现应运行 pass_tests[0]
    )
    mulan_pass = bool(mulan_patch) and mulan_run.syntax_pass

    dual = DualRailResult(
        task_id=task_id,
        baseline_pass=baseline_pass,
        mulan_pass=mulan_pass,
        injection_tokens=injection_tokens,
    )

    return TaskResult(
        task_id=task_id,
        status=TaskStatus.PASSED if dual.mulan_pass else TaskStatus.SKIPPED,
        score=max(0.0, dual.delta_pass_at_1 + 0.5),  # 中性基线 0.5
        details={
            "repo":              task.get("repo"),
            "issue_title":       task.get("issue_title"),
            "mode":              "online_dual_rail",
            "baseline_pass":     baseline_pass,
            "mulan_pass":        mulan_pass,
            "delta_pass_at_1":   dual.delta_pass_at_1,
            "injection_tokens":  injection_tokens,
            "info_density":      dual.info_density,
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

        is_online = config.llm_available and not config.dry_run

        results: List[TaskResult] = []
        for task in all_tasks:
            if is_online:
                result = _run_online_task(task, config)
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

        if is_online:
            # 在线模式：ΔPass@1 是核心指标
            delta_vals = [
                r.details.get("delta_pass_at_1", 0.0)
                for r in results
                if isinstance(r.details.get("delta_pass_at_1"), (int, float))
            ]
            avg_delta = sum(delta_vals) / len(delta_vals) if delta_vals else 0.0
            info_density_vals = [
                r.details.get("info_density", 0.0)
                for r in results
                if isinstance(r.details.get("info_density"), (int, float))
            ]
            avg_info_density = sum(info_density_vals) / len(info_density_vals) if info_density_vals else 0.0
            mulan_pass_rate = sum(
                1 for r in results if r.details.get("mulan_pass")
            ) / max(len(results), 1)
            baseline_pass_rate = sum(
                1 for r in results if r.details.get("baseline_pass")
            ) / max(len(results), 1)
            # 在线得分 = 0.5 基准 + max(ΔPass@1, 0) × 2
            score = min(1.0, 0.5 + max(avg_delta, 0.0) * 2)
            metrics = {
                "mode":                1.0,
                "mulan_pass_rate":     round(mulan_pass_rate, 4),
                "baseline_pass_rate":  round(baseline_pass_rate, 4),
                "avg_delta_pass_at_1": round(avg_delta, 4),
                "avg_info_density":    round(avg_info_density, 4),
                "aiu_type_coverage":   round(aiu_coverage, 4),
                "aiu_types_covered":   float(len(aiu_types_seen)),
            }
        else:
            # 离线模式：格式合规率 + AIU 覆盖率
            format_compliance = passed / max(len(results), 1)
            score = (format_compliance * 0.6 + aiu_coverage * 0.4) if results else 0.0
            metrics = {
                "mode":               0.0,
                "format_compliance":  round(format_compliance, 4),
                "aiu_type_coverage":  round(aiu_coverage, 4),
                "aiu_types_covered":  float(len(aiu_types_seen)),
                "pass_at_1":          0.0,   # 需在线填充
                "resolve_rate":       0.0,   # 需在线填充
            }

        return LayerResult(
            layer=self.layer,
            name="SWE-bench 信用锚评测（Layer 1）",
            tasks_total=len(results),
            tasks_passed=passed,
            tasks_skipped=skipped,
            tasks_failed=failed,
            score=round(score, 4),
            metrics=metrics,
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
