"""
熔断器（Circuit Breaker）状态机

状态转换：
  CLOSED ──(连续 N 次失败)──▶ OPEN ──(60s 后)──▶ HALF_OPEN
     ▲                                                 │
     └──────────────(成功)────────────────────────────┘
                       │(失败)
                       ▼
                     OPEN（重置计时器）

状态持久化到 _system/circuit_state.json，跨进程生效。
这意味着：LLM Provider 不可用后，下一次脚本启动也不会重试直到恢复时间到达。

配置（来自 config.yaml::resilience.circuit_breaker）：
  failure_threshold:        3   连续失败 N 次后开路
  recovery_timeout_seconds: 60  开路后等待 N 秒进入半开状态
"""
import datetime
import json
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

R = TypeVar("R")

try:
    from mms.utils._paths import DOCS_MEMORY as _MEMORY_ROOT  # type: ignore[import]
except ImportError:
    _MEMORY_ROOT = Path(__file__).resolve().parent.parent / "docs" / "memory"

_DEFAULT_STATE_FILE = _MEMORY_ROOT / "_system" / "circuit_state.json"

_STATE_CLOSED = "CLOSED"
_STATE_OPEN = "OPEN"
_STATE_HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(Exception):
    """熔断器处于开路状态，调用被拒绝"""

    def __init__(self, model_name: str, retry_after_seconds: float) -> None:
        self.model_name = model_name
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"熔断器已开路（{model_name}），"
            f"请等待 {retry_after_seconds:.0f}s 后自动进入半开状态。\n"
            f"GC 和规则类操作不受影响，可继续运行。"
        )


class CircuitBreaker:
    """
    跨进程持久化熔断器。

    Example:
        cb = CircuitBreaker(model_name="deepseek-r1:8b")

        def call_with_cb():
            return cb.call(provider.complete, prompt)

        try:
            result = call_with_cb()
        except CircuitOpenError as e:
            print(f"熔断器开路，跳过 LLM 调用: {e}")
            # 降级处理：使用 tag_overlap 替代 embedding 相似度检测
    """

    def __init__(
        self,
        model_name: str = "bailian",
        failure_threshold: int = 3,
        recovery_timeout: int = 60,
        state_file: Optional[Path] = None,
    ) -> None:
        self.model_name = model_name
        self._threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._state_file = state_file or _DEFAULT_STATE_FILE
        self._state_file.parent.mkdir(parents=True, exist_ok=True)

    def _load_state(self) -> dict:
        if not self._state_file.exists():
            return self._initial_state()
        try:
            all_states = json.loads(self._state_file.read_text(encoding="utf-8"))
            return all_states.get(self.model_name, self._initial_state())
        except (json.JSONDecodeError, OSError):
            return self._initial_state()

    def _save_state(self, state: dict) -> None:
        try:
            all_states = json.loads(self._state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, FileNotFoundError):
            all_states = {}

        all_states[self.model_name] = state
        tmp = self._state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(all_states, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.rename(self._state_file)

    @staticmethod
    def _initial_state() -> dict:
        return {
            "status": _STATE_CLOSED,
            "failure_count": 0,
            "last_failure_at": None,
            "last_success_at": None,
        }

    @staticmethod
    def _now_ts() -> float:
        return datetime.datetime.utcnow().timestamp()

    def call(self, func: Callable[..., R], *args: Any, **kwargs: Any) -> R:
        """
        通过熔断器保护地调用函数。

        Raises:
            CircuitOpenError: 熔断器处于 OPEN 状态时
            原始异常:         CLOSED / HALF_OPEN 状态下调用失败时
        """
        state = self._load_state()
        now = self._now_ts()

        if state["status"] == _STATE_OPEN:
            elapsed = now - (state.get("last_failure_at") or now)
            remaining = self._recovery_timeout - elapsed
            if remaining > 0:
                raise CircuitOpenError(self.model_name, remaining)
            state["status"] = _STATE_HALF_OPEN
            self._save_state(state)

        try:
            result = func(*args, **kwargs)
            state["status"] = _STATE_CLOSED
            state["failure_count"] = 0
            state["last_success_at"] = now
            self._save_state(state)
            return result

        except Exception:
            state["failure_count"] = state.get("failure_count", 0) + 1
            state["last_failure_at"] = now
            if state["failure_count"] >= self._threshold:
                state["status"] = _STATE_OPEN
            self._save_state(state)
            raise

    def reset(self) -> None:
        """手动重置熔断器到 CLOSED 状态（维护操作）"""
        self._save_state(self._initial_state())

    @property
    def is_open(self) -> bool:
        state = self._load_state()
        if state["status"] != _STATE_OPEN:
            return False
        elapsed = self._now_ts() - (state.get("last_failure_at") or 0)
        return elapsed < self._recovery_timeout
