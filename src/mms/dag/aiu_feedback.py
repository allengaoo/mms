"""
aiu_feedback.py — AIU 执行反馈统计系统

类比数据库 Query Feedback（Cardinality Feedback）机制：
  执行完成后收集真实代价 → 与估算代价对比 → 更新统计 → 下次同类 AIU 受益

核心功能：
  1. record()  — 记录单次 AIU 执行结果（成功/失败/token 消耗/延迟）
  2. query()   — 查询某类 AIU 的历史统计（成功率/平均 token/平均重试）
  3. suggest() — 基于历史统计给出执行建议（token budget / model hint）
  4. summary() — 打印 AIU 执行统计摘要报告

数据存储：
  docs/memory/_system/feedback_stats.jsonl
  每行一条 JSON 记录（append-only，类比 Write-Ahead Log）

数据格式（每行）：
  {
    "ts": ISO 8601 时间戳,
    "ep_id": "EP-129",
    "unit_id": "U1",
    "aiu_id": "aiu_1",
    "aiu_type": "SCHEMA_ADD_FIELD",
    "success": true,
    "attempts": 1,
    "actual_tokens": 2800,
    "estimated_tokens": 2500,
    "latency_ms": 3200,
    "feedback_level": 0,
    "error_pattern": null,
    "type": "aiu_execution"
  }

EP-129 | 2026-04-22
"""

from __future__ import annotations

import fcntl
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

_logger = logging.getLogger(__name__)

_HERE = Path(__file__).resolve().parent
try:
    from mms.utils._paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE.parent.parent
_FEEDBACK_PATH = _ROOT / "docs" / "memory" / "_system" / "feedback_stats.jsonl"

# ── 可配置常量（优先从 mms_config 读取）──────────────────────────────────────

try:
    import sys as _sys
    _sys.path.insert(0, str(_HERE))
    from mms.utils.mms_config import cfg as _cfg  # type: ignore[import]
    _SUGGEST_MIN_SAMPLES: int = int(getattr(_cfg, "feedback_suggest_min_samples", 3))
    _SUGGEST_CONFIDENCE_DENOMINATOR: int = int(getattr(_cfg, "feedback_confidence_denominator", 10))
    _TOKEN_LOW_ESTIMATE_THRESHOLD: float = float(getattr(_cfg, "feedback_low_estimate_threshold", 0.2))
    _TOKEN_HIGH_ESTIMATE_THRESHOLD: float = float(getattr(_cfg, "feedback_high_estimate_threshold", 0.3))
    _TOKEN_MIN: int = int(getattr(_cfg, "cost_estimator_token_min", 1500))
    _TOKEN_MAX: int = int(getattr(_cfg, "cost_estimator_token_max", 16000))
    _FAST_MODEL_MAX_TOKENS: int = int(getattr(_cfg, "fast_model_max_tokens", 4000))
    _DEFAULT_SUCCESS_RATE: float = float(getattr(_cfg, "cost_estimator_default_success_rate", 0.8))
    _WARN_SUCCESS_RATE_THRESHOLD: float = float(getattr(_cfg, "feedback_warn_success_threshold", 0.5))
except (ImportError, AttributeError):
    _SUGGEST_MIN_SAMPLES = 3
    _SUGGEST_CONFIDENCE_DENOMINATOR = 10
    _TOKEN_LOW_ESTIMATE_THRESHOLD = 0.2
    _TOKEN_HIGH_ESTIMATE_THRESHOLD = 0.3
    _TOKEN_MIN = 1500
    _TOKEN_MAX = 16000
    _FAST_MODEL_MAX_TOKENS = 4000
    _DEFAULT_SUCCESS_RATE = 0.8
    _WARN_SUCCESS_RATE_THRESHOLD = 0.5


# ── 数据结构 ─────────────────────────────────────────────────────────────────

class AIUStats:
    """单种 AIU 类型的聚合统计（类比 DB Cardinality Statistics）。"""

    def __init__(self, aiu_type: str) -> None:
        self.aiu_type = aiu_type
        self.total_runs: int = 0
        self.successes: int = 0
        self.total_attempts: int = 0
        self.total_actual_tokens: int = 0
        self.total_estimated_tokens: int = 0
        self.total_latency_ms: int = 0
        self.feedback_level_counts: Dict[int, int] = defaultdict(int)
        self.error_pattern_counts: Dict[str, int] = defaultdict(int)

    @property
    def success_rate(self) -> float:
        if self.total_runs == 0:
            return 0.8  # 乐观默认
        return round(self.successes / self.total_runs, 3)

    @property
    def avg_attempts(self) -> float:
        if self.total_runs == 0:
            return 1.0
        return round(self.total_attempts / self.total_runs, 2)

    @property
    def avg_actual_tokens(self) -> int:
        if self.total_runs == 0:
            return 0
        return self.total_actual_tokens // self.total_runs

    @property
    def token_estimation_error(self) -> float:
        """
        Token 预估偏差率（类比 DB Cardinality Estimation Error）。
        > 0 表示实际消耗 > 估算（低估），< 0 表示高估。
        """
        if self.total_estimated_tokens == 0:
            return 0.0
        return round(
            (self.total_actual_tokens - self.total_estimated_tokens)
            / self.total_estimated_tokens,
            3
        )

    @property
    def avg_latency_ms(self) -> int:
        if self.total_runs == 0:
            return 0
        return self.total_latency_ms // self.total_runs

    def to_dict(self) -> dict:
        return {
            "aiu_type": self.aiu_type,
            "total_runs": self.total_runs,
            "success_rate": self.success_rate,
            "avg_attempts": self.avg_attempts,
            "avg_actual_tokens": self.avg_actual_tokens,
            "token_estimation_error": self.token_estimation_error,
            "avg_latency_ms": self.avg_latency_ms,
            "feedback_level_counts": dict(self.feedback_level_counts),
            "top_error_patterns": dict(
                sorted(self.error_pattern_counts.items(), key=lambda x: -x[1])[:3]
            ),
        }


# ── 主类 ─────────────────────────────────────────────────────────────────────

class AIUFeedbackStore:
    """
    AIU 执行反馈存储与查询引擎。

    使用方式：
      store = AIUFeedbackStore()
      store.record(ep_id="EP-129", unit_id="U1", aiu_id="aiu_1",
                   aiu_type="SCHEMA_ADD_FIELD", success=True,
                   attempts=1, actual_tokens=2800, estimated_tokens=2500,
                   latency_ms=3200)
      stats = store.query("SCHEMA_ADD_FIELD")
      suggestion = store.suggest("SCHEMA_ADD_FIELD", estimated_tokens=2500)
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path or _FEEDBACK_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        ep_id: str,
        unit_id: str,
        aiu_id: str,
        aiu_type: str,
        success: bool,
        attempts: int = 1,
        actual_tokens: int = 0,
        estimated_tokens: int = 0,
        latency_ms: int = 0,
        feedback_level: int = 0,
        error_pattern: Optional[str] = None,
    ) -> None:
        """
        记录一次 AIU 执行结果。
        类比 DB 执行完成后收集真实 Cardinality 并写入 Statistics 字典。
        """
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "ep_id": ep_id,
            "unit_id": unit_id,
            "aiu_id": aiu_id,
            "aiu_type": aiu_type,
            "success": success,
            "attempts": attempts,
            "actual_tokens": actual_tokens,
            "estimated_tokens": estimated_tokens,
            "latency_ms": latency_ms,
            "feedback_level": feedback_level,
            "error_pattern": error_pattern,
            "type": "aiu_execution",
        }
        # 使用文件锁保证多进程并发写安全（fcntl 仅在 Unix 可用）
        try:
            with self._path.open("a", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except OSError as exc:
            _logger.warning("AIUFeedbackStore.record 写入失败: %s", exc)

    def query(self, aiu_type: Optional[str] = None) -> Dict[str, AIUStats]:
        """
        查询历史统计。
        aiu_type=None 时返回所有类型的统计。
        """
        all_stats: Dict[str, AIUStats] = {}

        if not self._path.exists():
            return all_stats

        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            if record.get("type") != "aiu_execution":
                continue

            t = record.get("aiu_type", "UNKNOWN")
            if aiu_type and t != aiu_type:
                continue

            if t not in all_stats:
                all_stats[t] = AIUStats(t)

            stats = all_stats[t]
            stats.total_runs += 1
            if record.get("success", False):
                stats.successes += 1
            stats.total_attempts += int(record.get("attempts", 1))
            stats.total_actual_tokens += int(record.get("actual_tokens", 0))
            stats.total_estimated_tokens += int(record.get("estimated_tokens", 0))
            stats.total_latency_ms += int(record.get("latency_ms", 0))
            level = int(record.get("feedback_level", 0))
            stats.feedback_level_counts[level] += 1
            err = record.get("error_pattern")
            if err:
                stats.error_pattern_counts[str(err)] += 1

        return all_stats

    def suggest(
        self,
        aiu_type: str,
        estimated_tokens: int,
    ) -> Dict:
        """
        基于历史统计给出执行建议。
        类比 DB 优化器根据 Cardinality 选择最优执行计划。

        返回：
          {
            "recommended_tokens": int,  # 建议 token 预算
            "recommended_model": str,   # 建议模型
            "confidence": float,        # 建议置信度（基于历史样本数）
            "historical_success_rate": float,
            "warning": str | None,      # 若低成功率，给出警告
          }
        """
        stats_map = self.query(aiu_type)
        stats = stats_map.get(aiu_type)

        if stats is None or stats.total_runs < _SUGGEST_MIN_SAMPLES:
            # 历史数据不足，使用估算值
            return {
                "recommended_tokens": estimated_tokens,
                "recommended_model": "fast" if estimated_tokens <= _FAST_MODEL_MAX_TOKENS else "capable",
                "confidence": 0.5,
                "historical_success_rate": _DEFAULT_SUCCESS_RATE,
                "warning": None,
            }

        # 基于历史实际 token 消耗调整
        token_error = stats.token_estimation_error
        if token_error > _TOKEN_LOW_ESTIMATE_THRESHOLD:
            # 低估超过阈值：建议扩充预算
            recommended = int(estimated_tokens * (1 + token_error))
        elif token_error < -_TOKEN_HIGH_ESTIMATE_THRESHOLD:
            # 高估超过阈值：建议缩减（节省 token）
            recommended = int(estimated_tokens * (1 + token_error * 0.5))
        else:
            recommended = estimated_tokens

        # 限制范围（与 cost_estimator 共用 cfg 配置）
        recommended = max(_TOKEN_MIN, min(recommended, _TOKEN_MAX))

        # 模型选择
        model = "fast" if recommended <= _FAST_MODEL_MAX_TOKENS else "capable"

        # 置信度：样本越多越可信
        confidence = min(stats.total_runs / _SUGGEST_CONFIDENCE_DENOMINATOR, 1.0)

        warning = None
        if stats.success_rate < _WARN_SUCCESS_RATE_THRESHOLD:
            warning = (
                f"警告：{aiu_type} 的历史成功率仅 {stats.success_rate:.0%}，"
                f"建议升级为 capable 模型并手动检查"
            )
            model = "capable"

        return {
            "recommended_tokens": recommended,
            "recommended_model": model,
            "confidence": round(confidence, 2),
            "historical_success_rate": stats.success_rate,
            "warning": warning,
        }

    def summary(self, top_n: int = 10) -> str:
        """
        生成 AIU 执行统计摘要报告。
        类比 DB EXPLAIN ANALYZE 的统计输出。
        """
        stats_map = self.query()
        if not stats_map:
            return "暂无 AIU 执行统计数据。"

        lines = [
            "=" * 70,
            f"AIU 执行统计摘要（共 {len(stats_map)} 种类型，Top {top_n} 频率）",
            "=" * 70,
            f"{'AIU 类型':<30} {'成功率':>7} {'均重试':>7} {'均Token':>8} {'偏差率':>7} {'样本':>6}",
            "-" * 70,
        ]

        sorted_stats = sorted(stats_map.values(), key=lambda s: -s.total_runs)
        for stats in sorted_stats[:top_n]:
            error_sign = "+" if stats.token_estimation_error >= 0 else ""
            lines.append(
                f"{stats.aiu_type:<30} "
                f"{stats.success_rate:>6.0%} "
                f"{stats.avg_attempts:>7.1f} "
                f"{stats.avg_actual_tokens:>8d} "
                f"{error_sign}{stats.token_estimation_error:>6.0%} "
                f"{stats.total_runs:>6d}"
            )

        # 整体统计
        total_runs = sum(s.total_runs for s in stats_map.values())
        total_success = sum(s.successes for s in stats_map.values())
        overall_rate = total_success / max(total_runs, 1)
        lines.append("-" * 70)
        lines.append(f"整体成功率: {overall_rate:.1%} | 总执行次数: {total_runs}")

        # Feedback 级别分布
        level_dist: Dict[int, int] = defaultdict(int)
        for s in stats_map.values():
            for level, count in s.feedback_level_counts.items():
                level_dist[level] += count
        if level_dist:
            lines.append(
                "Feedback 级别分布: "
                + " | ".join(f"L{k}={v}" for k, v in sorted(level_dist.items()))
            )

        lines.append("=" * 70)
        return "\n".join(lines)


# ── 模块级便捷函数 ────────────────────────────────────────────────────────────

_default_store: Optional[AIUFeedbackStore] = None


def get_feedback_store() -> AIUFeedbackStore:
    """获取全局单例 AIUFeedbackStore。"""
    global _default_store
    if _default_store is None:
        _default_store = AIUFeedbackStore()
    return _default_store


def record_aiu_execution(
    ep_id: str,
    unit_id: str,
    aiu_id: str,
    aiu_type: str,
    success: bool,
    **kwargs,
) -> None:
    """便捷函数：记录 AIU 执行结果。"""
    get_feedback_store().record(
        ep_id=ep_id, unit_id=unit_id, aiu_id=aiu_id,
        aiu_type=aiu_type, success=success, **kwargs,
    )


def query_aiu_suggestion(aiu_type: str, estimated_tokens: int) -> Dict:
    """便捷函数：查询 AIU 执行建议。"""
    return get_feedback_store().suggest(aiu_type, estimated_tokens)


def print_feedback_summary() -> None:
    """便捷函数：打印统计摘要。"""
    print(get_feedback_store().summary())


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "summary":
        print_feedback_summary()
    elif len(sys.argv) > 1 and sys.argv[1] == "demo":
        # 写入一些示例数据
        store = AIUFeedbackStore()
        store.record("EP-129", "U1", "aiu_1", "SCHEMA_ADD_FIELD", True, attempts=1,
                     actual_tokens=2800, estimated_tokens=2500, latency_ms=3100)
        store.record("EP-129", "U1", "aiu_2", "ROUTE_ADD_ENDPOINT", True, attempts=2,
                     actual_tokens=3600, estimated_tokens=3500, latency_ms=5200, feedback_level=1)
        store.record("EP-129", "U2", "aiu_1", "SCHEMA_ADD_FIELD", False, attempts=3,
                     actual_tokens=2900, estimated_tokens=2500, latency_ms=9000,
                     feedback_level=2, error_pattern="MISSING_FIELD")
        print(store.summary())
        print("\n建议查询（SCHEMA_ADD_FIELD）:")
        print(store.suggest("SCHEMA_ADD_FIELD", 2500))
    else:
        print("用法：python aiu_feedback.py [summary | demo]")
