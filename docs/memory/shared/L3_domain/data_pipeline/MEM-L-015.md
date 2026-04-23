---
id: MEM-L-015
layer: L3_domain
module: data_pipeline
dimension: data_pipeline
type: lesson
tier: warm
tags: [connector, connection-test, timeout, api-thread, blocking, data-pipeline]
source_ep: EP-109
created_at: "2026-04-12"
last_accessed: "2026-04-12"
access_count: 2
related_memories: [MEM-L-016, MEM-L-001]
also_in: [L2-D4]
generalized: true
version: 1
---

# MEM-L-015 · Connector 连接测试必须在独立超时内完成，禁止阻塞 API 线程

## WHERE（在哪个模块/场景中）

`backend/app/domain/data_pipeline/services/connector_service.py`
`POST /api/v1/connectors/{id}/test` 接口的实现。

## WHAT（发生了什么）

当 Connector 的目标数据源（MySQL / S3 / Kafka）响应慢或不可达时，
`test_connection()` 方法会阻塞 Uvicorn 工作线程长达 30-60 秒，
导致整个 API 服务的并发处理能力下降（Uvicorn 默认 4 个 worker）。

## WHY（根本原因）

`asyncio` 的 `async def` 函数中使用了同步阻塞 I/O（如 `pymysql.connect()`），
或者 HTTP 超时未设置上限，导致协程挂起时间过长。

## HOW（解决方案）

```python
# ✅ 正确：使用 asyncio.wait_for 强制超时 + 后台任务执行
class ConnectorService:
    async def test_connection(
        self, ctx: SecurityContext, connector_id: str
    ) -> TestResult:
        connector = await self._get(ctx, connector_id)

        try:
            # 强制 10 秒超时，防止阻塞 API 线程
            result = await asyncio.wait_for(
                self._do_test(connector),
                timeout=10.0,
            )
            return TestResult(status="ok", latency_ms=result.latency_ms)

        except asyncio.TimeoutError:
            return TestResult(
                status="timeout",
                message="连接测试超时（>10s），请检查网络或目标数据源状态",
            )

    async def _do_test(self, connector: Connector) -> _TestRaw:
        # 同步驱动包裹在 run_in_executor 中
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._sync_test,   # 同步测试函数
            connector,
        )

# ❌ 错误：直接 await 同步阻塞操作（无超时）
async def test_connection(self, ctx, connector_id):
    conn = pymysql.connect(...)  # 🚨 同步阻塞，无超时上限
    ...
```

**连接测试超时建议**：
- 数据库（MySQL/PG）：10s
- 对象存储（S3/OSS）：15s
- Kafka：20s（需要等待 metadata fetch）
- HTTP API：5s

## WHEN（触发条件）

- 新增 Connector 后执行连接测试
- 定期健康检查（`scheduler` 每 5 分钟触发）
- 数据源网络不稳定（跨 VPC、跨云）
