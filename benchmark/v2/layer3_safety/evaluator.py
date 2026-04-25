"""
Layer 3 — 安全门控评测器（完全离线可运行）

评测三个子系统：
  1. SanitizationGate  — 敏感凭证检测率 / 误报率
  2. MigrationGate     — ORM 变更 ↔ 迁移脚本对齐阻断率
  3. ArchCheck         — 架构违规检测覆盖率（AC-1 ~ AC-6）

扩展方式：
  - 新增 Sanitize 规则：在 fixtures/sanitize/*.yaml 添加 case，无需改代码
  - 新增 Migration 场景：在 fixtures/migration/*.yaml 添加 case
  - 新增 Arch 规则：在 fixtures/arch/*.yaml 添加 case，并在 arch_check.py 中实现规则
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 添加项目根到 sys.path
_HERE = Path(__file__).resolve().parent
_BENCH_ROOT = _HERE.parent.parent.parent
if str(_BENCH_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_BENCH_ROOT / "src"))

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
# SanitizationGate 子评测器
# ─────────────────────────────────────────────────────────────────────────────

class SanitizeSubEvaluator:
    """
    测试 SanitizationGate 的检出率和误报率。

    检出率（Detection Rate）  = 应检出且检出 / 应检出总数
    误报率（False Positive Rate） = 不应检出但检出 / 不应检出总数
    """

    # 与 src/mms/core/sanitize.py 保持一致的模式集合
    _PATTERNS: List[Tuple[str, re.Pattern]] = [
        ("API_KEY",    re.compile(r"sk-(?!your-key|example|placeholder)[a-zA-Z0-9\-_]{16,}")),
        ("API_KEY",    re.compile(r"AKIA[0-9A-Z]{16}")),                          # AWS Access Key
        ("API_KEY",    re.compile(r"ghp_[a-zA-Z0-9]{36}")),                        # GitHub PAT
        ("JWT",        re.compile(r"eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}")),
        ("INTERNAL_IP",re.compile(r"(?<!\d)(10\.\d{1,3}\.\d{1,3}\.\d{1,3})(?!\d)")),
        ("INTERNAL_IP",re.compile(r"(?<!\d)(192\.168\.\d{1,3}\.\d{1,3})(?!\d)")),
        ("INTERNAL_IP",re.compile(r"(?<!\d)(172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?!\d)")),
        ("PASSWORD",   re.compile(r"(?i)(password|passwd|pwd)\s*=\s*['\"]?(?!your-|example|placeholder)[^\s'\"]{8,}")),
        ("EMAIL",      re.compile(r"[a-zA-Z0-9._%+\-]+@(?!example\.com|yourdomain\.com)[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")),
        ("CONN_STR",   re.compile(r"(?i)(postgresql|mysql|redis)://[^:]+:[^@]{4,}@(?!localhost)[^\s/\"']+")),
    ]

    _REDACTED_PATTERN = re.compile(r"\[REDACTED_[A-Z_]+\]")

    def detect(self, text: str) -> List[str]:
        """返回检测到的标签列表（可能重复）"""
        # 跳过已脱敏内容
        if self._REDACTED_PATTERN.search(text):
            clean = self._REDACTED_PATTERN.sub("", text).strip()
            if not clean:
                return []
        detected = []
        for label, pattern in self._PATTERNS:
            if pattern.search(text):
                detected.append(label)
        return detected

    def run(self, fixture_dir: Path, config: BenchmarkConfig) -> List[TaskResult]:
        results: List[TaskResult] = []
        cases = self._load_fixtures(fixture_dir)
        if config.max_tasks:
            cases = cases[:config.max_tasks]

        for case in cases:
            t0 = time.monotonic()
            task_id = f"san_{case.get('id', 'unknown')}"
            try:
                detected = self.detect(case["input"])
                is_detected = len(detected) > 0
                should_detect = case.get("should_detect", True)

                if should_detect:
                    passed = is_detected
                    score  = 1.0 if passed else 0.0
                else:
                    # 阴性样例：检测到 = 误报（失败）
                    passed = not is_detected
                    score  = 1.0 if passed else 0.0

                results.append(TaskResult(
                    task_id=task_id,
                    status=TaskStatus.PASSED if passed else TaskStatus.FAILED,
                    score=score,
                    details={
                        "should_detect": should_detect,
                        "detected":      is_detected,
                        "labels":        detected,
                        "category":      case.get("category"),
                        "severity":      case.get("severity"),
                    },
                    duration_seconds=time.monotonic() - t0,
                ))
            except Exception as exc:
                results.append(TaskResult(
                    task_id=task_id,
                    status=TaskStatus.ERROR,
                    score=0.0,
                    error_message=str(exc),
                    duration_seconds=time.monotonic() - t0,
                ))
        return results

    def _load_fixtures(self, fixture_dir: Path) -> List[Dict[str, Any]]:
        cases: List[Dict[str, Any]] = []
        for yaml_file in sorted(fixture_dir.glob("*.yaml")):
            if _YAML_AVAILABLE:
                with open(yaml_file, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                cases.extend(data.get("cases", []))
        return cases


# ─────────────────────────────────────────────────────────────────────────────
# MigrationGate 子评测器
# ─────────────────────────────────────────────────────────────────────────────

class MigrationSubEvaluator:
    """
    测试 MigrationGate 的阻断精度。

    判定逻辑（镜像 migration_gate.py 的规则）：
      - orm_diff 包含 + 行（新增/修改）且 migration_files 为空 → 应阻断
      - orm_diff 为空 → 不触发
    """

    # 触发 migration gate 的 ORM diff 关键词
    _ORM_CHANGE_PATTERNS = [
        re.compile(r"^\+\s*(class\s+\w+.*SQLModel|SQLModel.*table=True)", re.MULTILINE),
        re.compile(r"^\+\s*\w+\s*:\s*\w+.*=\s*Field\(", re.MULTILINE),
        re.compile(r"^\+\s*__table_args__", re.MULTILINE),
        re.compile(r"^\-\s*\w+\s*:\s*\w+.*=\s*Field\(", re.MULTILINE),  # 删除字段
    ]

    def _has_orm_change(self, orm_diff: str) -> bool:
        if not orm_diff or not orm_diff.strip():
            return False
        return any(p.search(orm_diff) for p in self._ORM_CHANGE_PATTERNS)

    def _has_migration(self, migration_files: List[Dict]) -> bool:
        if not migration_files:
            return False
        for mf in migration_files:
            content = mf.get("content", "")
            if "def upgrade" in content and "def downgrade" in content:
                return True
        return False

    def run(self, fixture_dir: Path, config: BenchmarkConfig) -> List[TaskResult]:
        results: List[TaskResult] = []
        cases = self._load_fixtures(fixture_dir)
        if config.max_tasks:
            cases = cases[:config.max_tasks]

        for case in cases:
            t0 = time.monotonic()
            task_id = f"mig_{case.get('id', 'unknown')}"
            try:
                orm_diff    = case.get("orm_diff", "")
                mig_files   = case.get("migration_files", [])
                should_block = case.get("should_block", False)

                has_change = self._has_orm_change(orm_diff)
                has_mig    = self._has_migration(mig_files)
                would_block = has_change and not has_mig

                passed = (would_block == should_block)
                results.append(TaskResult(
                    task_id=task_id,
                    status=TaskStatus.PASSED if passed else TaskStatus.FAILED,
                    score=1.0 if passed else 0.0,
                    details={
                        "should_block":  should_block,
                        "would_block":   would_block,
                        "has_orm_change": has_change,
                        "has_migration":  has_mig,
                        "severity":       case.get("severity"),
                    },
                    duration_seconds=time.monotonic() - t0,
                ))
            except Exception as exc:
                results.append(TaskResult(
                    task_id=task_id,
                    status=TaskStatus.ERROR,
                    score=0.0,
                    error_message=str(exc),
                    duration_seconds=time.monotonic() - t0,
                ))
        return results

    def _load_fixtures(self, fixture_dir: Path) -> List[Dict[str, Any]]:
        cases: List[Dict[str, Any]] = []
        for yaml_file in sorted(fixture_dir.glob("*.yaml")):
            if _YAML_AVAILABLE:
                with open(yaml_file, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                cases.extend(data.get("cases", []))
        return cases


# ─────────────────────────────────────────────────────────────────────────────
# ArchCheck 子评测器
# ─────────────────────────────────────────────────────────────────────────────

class ArchCheckSubEvaluator:
    """
    测试架构约束扫描器（arch_check.py）的检出精度。
    使用内置轻量版规则（镜像 AC-1~AC-6），不依赖外部 arch_check.py。
    """

    _RULES: Dict[str, re.Pattern] = {
        "AC-1": re.compile(r"(?m)^(?!.*#.*)\s*(import aiokafka|from aiokafka)"),
        "AC-2": re.compile(r"(?m)^async def \w+\s*\(\s*(?!ctx\s*:|.*RequestContext|.*SecurityContext)\w"),
        "AC-3": re.compile(r"(?m)async def \w+.*\basession\b|(?=.*session\.add|.*session\.commit)(?!.*audit_service\.log)"),
        "AC-4": re.compile(r"@router\.\w+.*\ndef \w+.*:\n.*return \{"),
        "AC-5": re.compile(r"async with session\.begin\(\)"),
        "AC-6": re.compile(r"(?m)^\s*print\s*\("),
    }

    def _detect_violations(self, code: str, rule_id: str) -> int:
        pattern = self._RULES.get(rule_id)
        if not pattern:
            return 0
        return len(pattern.findall(code))

    def run(self, fixture_dir: Path, config: BenchmarkConfig) -> List[TaskResult]:
        results: List[TaskResult] = []
        cases = self._load_fixtures(fixture_dir)
        if config.max_tasks:
            cases = cases[:config.max_tasks]

        for case in cases:
            t0 = time.monotonic()
            task_id = f"arc_{case.get('id', 'unknown')}"
            try:
                code         = case.get("code", "")
                rule_id      = case.get("rule_id", "")
                expected_v   = case.get("expected_violations", 0)
                should_flag  = case.get("should_flag", expected_v > 0)

                actual_v = self._detect_violations(code, rule_id)
                is_flagged = actual_v > 0

                passed = (is_flagged == should_flag)
                results.append(TaskResult(
                    task_id=task_id,
                    status=TaskStatus.PASSED if passed else TaskStatus.FAILED,
                    score=1.0 if passed else 0.0,
                    details={
                        "rule_id":             rule_id,
                        "should_flag":         should_flag,
                        "is_flagged":          is_flagged,
                        "expected_violations": expected_v,
                        "actual_violations":   actual_v,
                    },
                    duration_seconds=time.monotonic() - t0,
                ))
            except Exception as exc:
                results.append(TaskResult(
                    task_id=task_id,
                    status=TaskStatus.ERROR,
                    score=0.0,
                    error_message=str(exc),
                    duration_seconds=time.monotonic() - t0,
                ))
        return results

    def _load_fixtures(self, fixture_dir: Path) -> List[Dict[str, Any]]:
        cases: List[Dict[str, Any]] = []
        for yaml_file in sorted(fixture_dir.glob("*.yaml")):
            if _YAML_AVAILABLE:
                with open(yaml_file, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                cases.extend(data.get("cases", []))
        return cases


# ─────────────────────────────────────────────────────────────────────────────
# Layer 3 主评测器
# ─────────────────────────────────────────────────────────────────────────────

class SafetyEvaluator(BaseEvaluator):
    """
    Layer 3 安全门控综合评测器。

    得分计算：
      - SanitizeGate 权重 0.5（最高优先级，直接影响数据安全）
      - MigrationGate 权重 0.3
      - ArchCheck 权重 0.2
    """

    _WEIGHTS = {"sanitize": 0.5, "migration": 0.3, "arch": 0.2}

    @property
    def layer(self) -> BenchmarkLayer:
        return BenchmarkLayer.LAYER3_SAFETY

    @property
    def is_offline_capable(self) -> bool:
        return True  # 完全离线，无需 LLM API

    def run(self, config: BenchmarkConfig) -> LayerResult:
        t0 = time.monotonic()

        if not _YAML_AVAILABLE:
            return self._make_skipped_result(
                "pyyaml 未安装，无法读取 fixture 文件。请运行: pip install pyyaml"
            )

        fixture_base = Path(__file__).parent / "fixtures"
        sanitize_evaluator  = SanitizeSubEvaluator()
        migration_evaluator = MigrationSubEvaluator()
        arch_evaluator      = ArchCheckSubEvaluator()

        san_results  = sanitize_evaluator.run(fixture_base / "sanitize",  config)
        mig_results  = migration_evaluator.run(fixture_base / "migration", config)
        arch_results = arch_evaluator.run(fixture_base / "arch",           config)

        all_results = san_results + mig_results + arch_results

        # 分类统计
        def _rate(results: List[TaskResult]) -> float:
            if not results:
                return 0.0
            return sum(1 for r in results if r.passed) / len(results)

        san_rate  = _rate(san_results)
        mig_rate  = _rate(mig_results)
        arch_rate = _rate(arch_results)

        # 区分检出率和误报率
        san_positive   = [r for r in san_results if r.details.get("should_detect") is True]
        san_negative   = [r for r in san_results if r.details.get("should_detect") is False]
        detection_rate = _rate(san_positive)
        fp_rate        = 1.0 - _rate(san_negative)  # 误报率 = 1 - 阴性通过率

        # 严重违规漏检数（severity=critical 且 should_detect=True 但未检出）
        critical_misses = sum(
            1 for r in san_results
            if r.details.get("severity") == "critical"
            and r.details.get("should_detect") is True
            and not r.passed
        )

        weighted_score = (
            self._WEIGHTS["sanitize"]  * san_rate +
            self._WEIGHTS["migration"] * mig_rate +
            self._WEIGHTS["arch"]      * arch_rate
        )

        passed = sum(1 for r in all_results if r.passed)
        skipped = sum(1 for r in all_results if r.status == TaskStatus.SKIPPED)
        failed = len(all_results) - passed - skipped

        return LayerResult(
            layer=self.layer,
            name="安全门控评测（Layer 3）",
            tasks_total=len(all_results),
            tasks_passed=passed,
            tasks_skipped=skipped,
            tasks_failed=failed,
            score=weighted_score,
            metrics={
                # SanitizationGate
                "sanitize.detection_rate":     round(detection_rate, 4),
                "sanitize.false_positive_rate":round(fp_rate, 4),
                "sanitize.critical_misses":    float(critical_misses),
                "sanitize.pass_rate":          round(san_rate, 4),
                # MigrationGate
                "migration.block_accuracy":    round(mig_rate, 4),
                # ArchCheck
                "arch.detection_rate":         round(arch_rate, 4),
                # 综合
                "overall.weighted_score":      round(weighted_score, 4),
            },
            task_results=all_results,
            duration_seconds=time.monotonic() - t0,
        )
