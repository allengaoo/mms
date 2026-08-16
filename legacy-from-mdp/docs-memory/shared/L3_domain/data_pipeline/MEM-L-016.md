---
id: MEM-L-016
layer: L3_domain
module: data_pipeline
dimension: data_pipeline
type: lesson
tier: hot
tags: [ingestion-worker, job-execution-scope, try-except, job-status, data-pipeline, worker]
source_ep: EP-109
created_at: "2026-04-12"
last_accessed: "2026-04-12"
access_count: 7
related_memories: [MEM-L-004, MEM-L-005, MEM-L-015]
also_in: [L4-workers]
generalized: false
version: 1
related_to:
  - id: "AD-006"
    reason: "AD-006 是 JobExecutionScope 的架构决策，本记忆是其在数据管道场景的具体应用"
  - id: "MEM-L-001"
    reason: "Ingestion Worker 中数值字段（batch_size 等）易犯 or 默认值错误"
  - id: "AD-007"
    reason: "Ingestion Worker 向 Kafka 发送数据前必须通过 NullSafeNormalizer"
cites_files:
  - "backend/app/workers/base.py"
  - "backend/app/services/control/datalink_service.py"
impacts:
  - "BIZ-002"

---

# MEM-L-016 · IngestionWorker 必须用 JobExecutionScope，禁止散落 try/except 管理 Job 状态

## WHERE（在哪个模块/场景中）

`backend/app/workers/ingestion/` 下所有 Worker 实现，
以及继承 `BaseIngestionWorker` 的子类。

## WHAT（发生了什么）

当 Worker 使用散落的 `try/except` 管理 Job 状态时：

1. 异常路径漏更新 Job 状态 → UI 永久显示"运行中"（僵尸 Job）
2. `FAILED` 状态写入时机不一致 → 调度器误判为成功，触发后续依赖任务
3. 审计日志缺失（没有在 `except` 中调用 `AuditService`）
4. `tenant_id` 和 `trace_id` 丢失，无法排查多租户问题

## WHY（根本原因）

Job 生命周期管理（PENDING → RUNNING → SUCCESS/FAILED）是横切关注点，
应由框架统一处理，而非在业务代码中分散实现。
`JobExecutionScope`（`backend/app/workers/base.py`）正是为此设计的。

## HOW（解决方案）

```python
# ✅ 正确：使用 JobExecutionScope（EP-023 引入）
from app.workers.base import JobExecutionScope

class CompanyIngestionWorker(BaseIngestionWorker):
    async def run(self, job_id: str, connector_id: str) -> None:
        async with JobExecutionScope(
            job_id=job_id,
            worker_name="CompanyIngestionWorker",
            session_factory=self.session_factory,
        ) as scope:
            ctx = scope.ctx  # 已注入 tenant_id, trace_id, permissions

            # 仅写业务逻辑，JobExecutionScope 自动处理：
            # - Job 状态机（RUNNING → SUCCESS / FAILED）
            # - AuditService.log()
            # - 异常捕获与格式化错误信息
            async for batch in self._read_source(ctx, connector_id):
                await self._write_to_milvus(ctx, batch)

# ❌ 错误：手动管理 Job 状态（典型反模式）
async def run(self, job_id, connector_id):
    try:
        await self.job_service.update_status(job_id, "RUNNING")  # 漏写 tenant_id
        async for batch in self._read_source(connector_id):
            await self._write_to_milvus(batch)
        await self.job_service.update_status(job_id, "SUCCESS")
    except Exception as e:
        # 🚨 以下情况会漏执行：asyncio.CancelledError, SystemExit
        await self.job_service.update_status(job_id, "FAILED", str(e))
        raise
```

**JobExecutionScope 提供的能力**：

- 自动 RUNNING → SUCCESS / FAILED 状态转换
- 自动 `AuditService.log()` 写入审计
- 自动注入 `SecurityContext`（含 tenant_id, trace_id）
- 捕获 `BaseException`（含 `asyncio.CancelledError`）

## WHEN（触发条件）

- 新增任何 Ingestion Worker 实现
- 重构旧 Worker（去掉散落的 try/except）
- Code Review 检查 Worker 代码规范合规性

