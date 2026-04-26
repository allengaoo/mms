# 模版：ADAPTER 层 · 数据库写操作（小模型优化版）
# 适用：新增 Service 写方法 / Repository 操作 / Alembic 迁移
# Token 预算：≤3.5K（含模版本身约 800 token）

---

## [TASK] 任务描述
**目标**：{一句话，包含：做什么 + 涉及哪个 Model/Service}
**层级坐标**：Layer 2 (infrastructure/database) × Dimension 9 (数据库与迁移)
**涉及文件**：
- `backend/app/models/{model}.py`
- `backend/app/services/control/{service}.py`
- `backend/app/infrastructure/repositories/{repo}.py`（如有）

---

## [MEMORY] 本次必须遵守的记忆（2条核心）

**MEM-DB-002**：autobegin 后禁止再调 session.begin()
- 规则：`session.execute()` 触发 autobegin 后，禁止再调 `session.begin()`
- ✅ 正确：`async with session.begin(): await session.execute(...)`
- ❌ 错误：`await session.execute(...)` 然后 `async with session.begin():`

**AD-005**：事务策略二选一
- Strategy A（优先）：`async with session.begin():` 包裹全部读写
- Strategy B：简单写入时，在末尾 `await session.commit()`
- ❌ 禁止：同一函数中混用两种策略

---

## [STATE] 系统状态（从 SESSION_HANDOFF 复制当前值）
- EP: {当前EP编号} | 后端镜像: {version} | DB Head: {alembic_head}
- 是否需要 Alembic 迁移: 是 / 否

---

## [CONSTRAINTS] 本层必守红线（5条）
- ✅ Service 公开方法首参必须是 `ctx: SecurityContext`
- ✅ 所有查询必须含 `.where(Model.tenant_id == ctx.tenant_id)`
- ✅ 所有 WRITE 必须调用 `await audit_service.log(ctx, action=..., target_id=...)`
- ✅ JSON 字段必须用 `sa_column=Column(JSON)` 而非 `field: dict`
- ❌ 禁止：Controller 层写业务逻辑；禁止裸 `except Exception:` 吞异常

---

## [EXAMPLE] 参考模式（来自 EP-087）
```python
# ✅ Strategy A 完整示例
async def update_sync_job(
    ctx: SecurityContext,
    job_id: UUID,
    dto: SyncJobUpdateDTO,
) -> SyncJob:
    async with async_session_factory() as session:
        async with session.begin():                        # Strategy A
            job = await session.get(SyncJob, job_id)
            if not job or job.tenant_id != ctx.tenant_id: # RLS
                raise DomainException(code="E_DATALINK_001")
            for field, value in dto.model_dump(exclude_unset=True).items():
                setattr(job, field, value)
            await audit_service.log(ctx, "UPDATE_SYNC_JOB", str(job_id))
    return job
```

---

## [OUTPUT] 输出格式（严格按顺序，无需额外说明）
1. `backend/app/services/control/{service}.py` — 完整函数代码
2. `backend/app/api/v1/endpoints/{endpoint}.py` — Endpoint（如涉及）
3. 对应测试 `tests/unit/test_{service}.py` — AAA 格式（Arrange/Act/Assert）
4. 是否需要 Alembic 迁移（是：提供迁移脚本骨架；否：直接说明）
