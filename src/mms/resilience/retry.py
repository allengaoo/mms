"""
指数退避重试装饰器（Python 3.9，纯 stdlib，零第三方依赖）

配置（来自 config.yaml::resilience.retry）：
  max_attempts:    3       最大尝试次数（含首次）
  wait_min:        1.0s    首次等待时间
  wait_max:        10.0s   最大等待时间上限
  wait_multiplier: 2.0     等待时间倍数（指数退避）

退避序列示例（max=3, min=1, multiplier=2）：
  第1次失败 → 等待 1s → 第2次尝试
  第2次失败 → 等待 2s → 第3次尝试（最后一次）
  第3次失败 → 抛出 RetryExhaustedError

使用场景：LLM HTTP 调用、文件 I/O、索引更新
"""
import functools
import time
from typing import Callable, Optional, Tuple, Type, TypeVar

F = TypeVar("F", bound=Callable)


class RetryExhaustedError(Exception):
    """重试次数耗尽，操作最终失败"""

    def __init__(self, attempts: int, last_exception: Exception) -> None:
        self.attempts = attempts
        self.last_exception = last_exception
        super().__init__(
            f"操作失败（已重试 {attempts} 次）: {last_exception}"
        )


def with_retry(
    max_attempts: int = 3,
    wait_min: float = 1.0,
    wait_max: float = 10.0,
    wait_multiplier: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable[[int, Exception], None]] = None,
) -> Callable[[F], F]:
    """
    指数退避重试装饰器。

    Args:
        max_attempts:    最大尝试次数（含首次，最小值 1）
        wait_min:        首次等待时间（秒）
        wait_max:        最大等待时间上限（秒）
        wait_multiplier: 退避倍数
        exceptions:      需要触发重试的异常类型元组
        on_retry:        每次重试前的回调（参数: attempt序号, 上次异常）

    Returns:
        被装饰的函数，失败超限后抛出 RetryExhaustedError

    Example:
        @with_retry(max_attempts=3, exceptions=(ProviderUnavailableError,))
        def call_llm(prompt: str) -> str:
            return provider.complete(prompt)
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc: Optional[Exception] = None
            wait = wait_min

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        break
                    if on_retry is not None:
                        on_retry(attempt, exc)
                    time.sleep(min(wait, wait_max))
                    wait *= wait_multiplier

            raise RetryExhaustedError(max_attempts, last_exc)

        return wrapper  # type: ignore[return-value]
    return decorator
