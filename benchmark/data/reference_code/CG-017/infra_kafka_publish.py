"""
参考实现：KafkaEventPublisher.publish_with_retry
任务 ID：CG-017
层：L2_infra (Infrastructure)

评分重点：
  - 禁止直接 import aiokafka（通过 infrastructure 适配器）
  - 必须调用 normalize_record（防止 date/Decimal/UUID 序列化失败）
  - 使用 tenacity 指数退避重试（最大 3 次）
  - structlog 记录含 trace_id、partition、offset
"""
import asyncio
from typing import Any, Dict, Optional

import structlog
from tenacity import (
    AsyncRetrying,
    RetryError,
    stop_after_attempt,
    wait_exponential,
)

from app.infrastructure.messaging.kafka_client import KafkaClient  # 通过适配器访问
from app.infrastructure.messaging.normalizer import normalize_record

log = structlog.get_logger(__name__)

_MAX_RETRIES = 3
_WAIT_MIN_SECONDS = 0.5
_WAIT_MAX_SECONDS = 8.0


class KafkaEventPublisher:
    """Kafka 事件发布器（通过 infrastructure 适配器，禁止直接 import aiokafka）"""

    def __init__(self, client: KafkaClient) -> None:
        self._client = client

    async def publish_with_retry(
        self,
        topic: str,
        record: Dict[str, Any],
        key: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> None:
        """
        带指数退避重试的 Kafka 消息发布。

        发送前必须调用 normalize_record 归一化：
          - date → ISO string
          - Decimal → float
          - UUID → str
          - datetime → ISO string

        Args:
            topic:    Kafka Topic 名称
            record:   消息体（发送前自动归一化）
            key:      消息 key（可选，用于分区路由）
            trace_id: 追踪 ID（记录到日志）

        Raises:
            RuntimeError: 超出最大重试次数后抛出
        """
        normalized = normalize_record(record)  # 必须调用，防止静默序列化失败

        logger = log.bind(topic=topic, trace_id=trace_id or "")

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(_MAX_RETRIES),
                wait=wait_exponential(
                    multiplier=1,
                    min=_WAIT_MIN_SECONDS,
                    max=_WAIT_MAX_SECONDS,
                ),
                reraise=False,
            ):
                with attempt:
                    result = await self._client.send(
                        topic=topic,
                        value=normalized,
                        key=key,
                    )
                    logger.info(
                        "kafka.publish.success",
                        partition=result.partition,
                        offset=result.offset,
                        attempt=attempt.retry_state.attempt_number,
                    )
        except RetryError as exc:
            logger.error(
                "kafka.publish.failed",
                max_retries=_MAX_RETRIES,
                error=str(exc),
            )
            raise RuntimeError(
                f"Kafka 发布失败（topic={topic}，已重试 {_MAX_RETRIES} 次）"
            ) from exc
