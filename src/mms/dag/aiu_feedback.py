"""
aiu_feedback.py — AIU 执行反馈统计系统

类比数据库 Query Feedback（Cardinality Feedback）机制：
  执行完成后收集真实代价 → 与估算代价对比 → 更新统计 → 下次同类 AIU 受益

改进点（v2.0）：
  1. 移除 fcntl 强依赖（跨平台崩溃风险）→ 改用 threading.Lock + 可选 filelock
  2. 内存态缓存（In-memory Cache）：启动时一次性加载磁盘，之后 query() 不再触发 I/O
  3. 滑动窗口衰减（Decay Window）：每种 AIU 只保留最近 N 条记录，旧记录自动淘汰
  4. 新增 record_unit_feedback() / get_max_feedback_level() 替代 unit_runner 中的直接文件读写

核心功能：
  1. record()               — 记录单次 AIU 执行结果
  2. query()                — 查询某类 AIU 的历史统计（从内存读取）
  3. suggest()              — 给出执行建议（token budget / model hint）
  4. summary()              — 打印 AIU 执行统计摘要
  5. record_unit_feedback() — 记录 Unit 级 Feedback（三级回退）
  6. get_max_feedback_level() — 查询 Unit 已达到的最高 Feedback 级别

数据存储：
  docs/memory/_system/feedback_stats.jsonl
  每行一条 JSON 记录（append-only WAL）

EP-129 v2.0 | 2026-05-04
"""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict, deque
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

# ── 跨平台文件锁 ──────────────────────────────────────────────────────────────
# 优先使用 filelock（跨进程安全），降级为 threading.Lock（单进程内安全）
try:
    from filelock import FileLock as _FileLock  # type: ignore[import]
    _HAS_FILELOCK = True
except ImportError:
    _HAS_FILELOCK = False
    _logger.debug(
        "filelock 未安装，使用 threading.Lock 作为写入锁。"
        "多进程并发写入可能产生竞争，建议安装：pip install filelock"
    )

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
    # 每种 AIU 类型保留最近 N 条执行记录；超过则丢弃最旧记录，实现衰减
    _DECAY_WINDOW: int = int(getattr(_cfg, "feedback_decay_window", 50))
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
    _DECAY_WINDOW = 50  # 仅保留最近 50 条，自然淘汰历史包袱（幽灵记忆问题）


# ── 数据结构 ─────────────────────────────────────────────────────────────────

class AIUStats:
    """
    单种 AIU 类型的聚合统计（基于滑动窗口）。

    只统计最近 _DECAY_WINDOW 条执行记录，自动淘汰旧记录。
    避免旧版本积累的大量失败记录永久拖垮当前估算（幽灵记忆问题）。
    """

    def __init__(self, aiu_type: str, records: List[dict]) -> None:
        self.aiu_type = aiu_type
        self._records = records  # 已经过 deque 截断的最近记录

    @property
    def total_runs(self) -> int:
        return len(self._records)

    @property
    def successes(self) -> int:
        return sum(1 for r in self._records if r.get("success", False))

    @property
    def success_rate(self) -> float:
        if not self._records:
            return _DEFAULT_SUCCESS_RATE
        return round(self.successes / self.total_runs, 3)

    @property
    def avg_attempts(self) -> float:
        if not self._records:
            return 1.0
        return round(sum(r.get("attempts", 1) for r in self._records) / self.total_runs, 2)

    @property
    def avg_actual_tokens(self) -> int:
        if not self._records:
            return 0
        return sum(r.get("actual_tokens", 0) for r in self._records) // self.total_runs

    @property
    def token_estimation_error(self) -> float:
        """Token 预估偏差率（> 0 表示低估，< 0 表示高估）。"""
        total_estimated = sum(r.get("estimated_tokens", 0) for r in self._records)
        total_actual = sum(r.get("actual_tokens", 0) for r in self._records)
        if total_estimated == 0:
            return 0.0
        return round((total_actual - total_estimated) / total_estimated, 3)

    @property
    def avg_latency_ms(self) -> int:
        if not self._records:
            return 0
        return sum(r.get("latency_ms", 0) for r in self._records) // self.total_runs

    def to_dict(self) -> dict:
        return {
            "aiu_type": self.aiu_type,
            "total_runs": self.total_runs,
            "success_rate": self.success_rate,
            "avg_attempts": self.avg_attempts,
            "avg_actual_tokens": self.avg_actual_tokens,
            "token_estimation_error": self.token_estimation_error,
            "avg_latency_ms": self.avg_latency_ms,
        }


# ── 主类 ─────────────────────────────────────────────────────────────────────

class AIUFeedbackStore:
    """
    AIU 执行反馈存储与查询引擎（v2.0 内存缓存版）。

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

        # 内存缓存：aiu_type → deque(maxlen=_DECAY_WINDOW) of raw record dicts
        self._cache: Dict[str, deque] = defaultdict(lambda: deque(maxlen=_DECAY_WINDOW))
        self._cache_loaded = False
        self._lock = threading.Lock()  # 保护内存缓存的读写

        # 跨进程文件锁（写磁盘时使用）
        if _HAS_FILELOCK:
            self._file_lock: Optional[object] = _FileLock(str(self._path) + ".lock")
        else:
            self._file_lock = None

    # ── 缓存管理 ─────────────────────────────────────────────────────────────

    def _ensure_cache(self) -> None:
        """懒加载：首次访问时从磁盘一次性加载 aiu_execution 记录到内存。"""
        if self._cache_loaded:
            return
        with self._lock:
            if self._cache_loaded:
                return
            if not self._path.exists():
                self._cache_loaded = True
                return
            try:
                for line in self._path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if record.get("type") != "aiu_execution":
                        continue
                    aiu_type = record.get("aiu_type", "UNKNOWN")
                    self._cache[aiu_type].append(record)
            except OSError as exc:
                _logger.warning("AIUFeedbackStore 加载缓存失败: %s", exc)
            finally:
                self._cache_loaded = True

    def _write_line(self, line: str) -> None:
        """线程安全 + 跨进程安全地追加一行到磁盘。"""
        try:
            if self._file_lock is not None:
                with self._file_lock:  # type: ignore[attr-defined]
                    with self._path.open("a", encoding="utf-8") as f:
                        f.write(line)
            else:
                with self._lock:
                    with self._path.open("a", encoding="utf-8") as f:
                        f.write(line)
        except OSError as exc:
            _logger.warning("AIUFeedbackStore 写入磁盘失败: %s", exc)

    # ── 核心 API ──────────────────────────────────────────────────────────────

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
        同步更新内存缓存（O(1)）+ 追加写磁盘（类比 WAL）。
        """
        self._ensure_cache()

        entry = {
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

        with self._lock:
            self._cache[aiu_type].append(entry)

        self._write_line(json.dumps(entry, ensure_ascii=False) + "\n")

    def query(self, aiu_type: Optional[str] = None) -> Dict[str, AIUStats]:
        """
        查询历史统计（从内存缓存读取，不触发磁盘 I/O）。
        aiu_type=None 时返回所有类型的统计。
        """
        self._ensure_cache()

        with self._lock:
            if aiu_type is not None:
                if aiu_type not in self._cache or not self._cache[aiu_type]:
                    return {}
                records = list(self._cache[aiu_type])
                return {aiu_type: AIUStats(aiu_type, records)}

            return {
                t: AIUStats(t, list(deq))
                for t, deq in self._cache.items()
                if deq
            }

    def suggest(
        self,
        aiu_type: str,
        estimated_tokens: int,
    ) -> Dict:
        """
        基于历史统计给出执行建议。
        类比 DB 优化器根据 Cardinality 选择最优执行计划。
        """
        stats_map = self.query(aiu_type)
        stats = stats_map.get(aiu_type)

        if stats is None or stats.total_runs < _SUGGEST_MIN_SAMPLES:
            return {
                "recommended_tokens": estimated_tokens,
                "recommended_model": "fast" if estimated_tokens <= _FAST_MODEL_MAX_TOKENS else "capable",
                "confidence": 0.5,
                "historical_success_rate": _DEFAULT_SUCCESS_RATE,
                "warning": None,
            }

        token_error = stats.token_estimation_error
        if token_error > _TOKEN_LOW_ESTIMATE_THRESHOLD:
            recommended = int(estimated_tokens * (1 + token_error))
        elif token_error < -_TOKEN_HIGH_ESTIMATE_THRESHOLD:
            recommended = int(estimated_tokens * (1 + token_error * 0.5))
        else:
            recommended = estimated_tokens

        recommended = max(_TOKEN_MIN, min(recommended, _TOKEN_MAX))
        model = "fast" if recommended <= _FAST_MODEL_MAX_TOKENS else "capable"
        confidence = min(stats.total_runs / _SUGGEST_CONFIDENCE_DENOMINATOR, 1.0)

        warning = None
        if stats.success_rate < _WARN_SUCCESS_RATE_THRESHOLD:
            warning = (
                f"警告：{aiu_type} 历史成功率仅 {stats.success_rate:.0%}"
                f"（近 {stats.total_runs} 次），建议改用 capable 模型并人工核查"
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
        """生成 AIU 执行统计摘要（类比 EXPLAIN ANALYZE 输出）。"""
        stats_map = self.query()
        if not stats_map:
            return "暂无 AIU 执行统计数据。"

        lines = [
            "=" * 70,
            f"AIU 执行统计摘要（共 {len(stats_map)} 种类型，Top {top_n}，近 {_DECAY_WINDOW} 条/类型）",
            "=" * 70,
            f"{'AIU 类型':<30} {'成功率':>7} {'均重试':>7} {'均Token':>8} {'偏差率':>7} {'样本':>6}",
            "-" * 70,
        ]

        sorted_stats = sorted(stats_map.values(), key=lambda s: -s.total_runs)
        for s in sorted_stats[:top_n]:
            sign = "+" if s.token_estimation_error >= 0 else ""
            lines.append(
                f"{s.aiu_type:<30} "
                f"{s.success_rate:>6.0%} "
                f"{s.avg_attempts:>7.1f} "
                f"{s.avg_actual_tokens:>8d} "
                f"{sign}{s.token_estimation_error:>6.0%} "
                f"{s.total_runs:>6d}"
            )

        total_runs = sum(s.total_runs for s in stats_map.values())
        total_success = sum(s.successes for s in stats_map.values())
        overall = total_success / max(total_runs, 1)
        lines.append("-" * 70)
        lines.append(f"整体成功率: {overall:.1%} | 总执行次数: {total_runs}")
        lines.append("=" * 70)
        return "\n".join(lines)

    # ── Unit 级 Feedback（三级回退记录）────────────────────────────────────────

    def record_unit_feedback(
        self,
        ep_id: str,
        unit_id: str,
        level: int,
        success: bool,
        error_preview: str = "",
    ) -> None:
        """
        记录 Unit 级别的 Feedback 回退事件（type=aiu_feedback）。
        不进入 aiu_execution 缓存，直接写磁盘。
        """
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "ep_id": ep_id,
            "unit_id": unit_id,
            "level": level,
            "success": success,
            "error_preview": error_preview[:200],
            "type": "aiu_feedback",
        }
        self._write_line(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_max_feedback_level(self, ep_id: str, unit_id: str) -> int:
        """
        查询某 ep_id + unit_id 已达到的最高 Feedback 级别。
        从磁盘扫描 aiu_feedback 记录（这类记录量少，不值得单独缓存）。
        """
        if not self._path.exists():
            return 0
        max_level = 0
        try:
            for line in self._path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    record.get("type") == "aiu_feedback"
                    and record.get("ep_id") == ep_id
                    and record.get("unit_id") == unit_id
                ):
                    max_level = max(max_level, int(record.get("level", 0)))
        except OSError:
            pass
        return max_level


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
        store = AIUFeedbackStore()
        store.record("EP-129", "U1", "aiu_1", "SCHEMA_ADD_FIELD", True, attempts=1,
                     actual_tokens=2800, estimated_tokens=2500, latency_ms=3100)
        store.record("EP-129", "U1", "aiu_2", "ROUTE_ADD_ENDPOINT", True, attempts=2,
                     actual_tokens=3600, estimated_tokens=3500, latency_ms=5200)
        store.record("EP-129", "U2", "aiu_1", "SCHEMA_ADD_FIELD", False, attempts=3,
                     actual_tokens=2900, estimated_tokens=2500, latency_ms=9000,
                     error_pattern="MISSING_FIELD")
        print(store.summary())
        print("\n建议查询（SCHEMA_ADD_FIELD）:")
        print(store.suggest("SCHEMA_ADD_FIELD", 2500))
    else:
        print("用法：python aiu_feedback.py [summary | demo]")
