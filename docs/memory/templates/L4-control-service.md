# 模版：APP 层 · Control Service（写操作）（小模型优化版）
# 适用：新增 Service 方法 / CRUD 写操作 / 业务逻辑编排
# Token 预算：≤4K

---

## [TASK] 任务描述
**目标**：{一句话，包含：做什么 + 业务约束条件 + 涉及哪个 Domain}
**层级坐标**：Layer 4 (application/control) × Dimension 2 (架构边界) + Dimension 1 (安全)
**涉及文件**：
- `backend/app/services/control/{domain}_service.py`
- `backend/app/api/v1/endpoints/{domain}.py`
- `backend/app/api/schemas/{domain}.py`（DTO）

---

## [MEMORY] 本次必须遵守的记忆（3条核心）

**AD-003**：控制面/数据面严格分离
- ✅ Control Service 只操作 MySQL（SQLModel + AsyncSession）
- ❌ 禁止：在 Control Service 中直接 import pymilvus / elasticsearch / aiokafka
- 写向量库/ES 必须通过 `services/dispatch/` 发 Kafka 事件

**AD-002**：所有 DB 查询必须含 tenant_id 过滤（RLS）
- ❌ 遗漏 tenant_id 过滤 = IDOR 安全漏洞（红线）

**MEM-DB-002**：事务策略 A/B 二选一
- Strategy A（优先）：`async with session.begin():` 包裹读写
- ❌ 禁止：`execute()` 之后再调 `session.begin()`

---

## [STATE] 系统状态
- EP: {当前EP编号} | 后端镜像: {version} | DB Head: {alembic_head}
- 权限要求：{所需 RBAC 权限，如 `ont:object:edit`}

---

## [CONSTRAINTS] 本层必守红线（6条）
- ✅ Service 公开方法首参：`ctx: SecurityContext`
- ✅ 所有写操作调用：`await audit_service.log(ctx, action=..., target_id=...)`
- ✅ 业务错误使用：`raise DomainException(code="E_{MODULE}_{NNN}")`
- ✅ API 响应使用信封格式：`{"code": 200, "data": ..., "meta": ...}`
- ✅ 禁止 `print()`，使用 `structlog.get_logger().info(...)`
- ❌ 禁止：Controller 层写业务逻辑（必须下沉到 Service）

---

## [EXAMPLE] 参考模式（来自 EP-103）
```python
# ✅ 标准 Control Service 写方法
async def pause_sync_job(
    ctx: SecurityContext,
    job_id: UUID,
) -> SyncJob:
    logger = structlog.get_logger()
    logger.info("pause_sync_job", tenant=ctx.tenant_id, job_id=str(job_id))

    async with async_session_factory() as session:
        async with session.begin():                        # Strategy A
            job = await session.get(SyncJob, job_id)
            if not job or job.tenant_id != ctx.tenant_id: # RLS
                raise DomainException(code="E_DATALINK_001", msg="Job not found")
            if job.status == SyncJobStatus.RUNNING:
                raise DomainException(code="E_DATALINK_009", msg="Cannot pause running job")
            job.is_paused = True
            await audit_service.log(ctx, "PAUSE_SYNC_JOB", str(job_id))
    return job
```

---

## [OUTPUT] 输出格式
1. `services/control/{domain}_service.py` — 完整函数
2. `api/v1/endpoints/{domain}.py` — Endpoint（含 require_permission 装饰器）
3. `api/schemas/{domain}.py` — Request/Response DTO（Pydantic v2）
4. `tests/unit/test_{domain}_service.py` — 单元测试（AAA + Mock DB）
