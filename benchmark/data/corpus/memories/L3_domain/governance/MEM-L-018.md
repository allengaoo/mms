---
id: MEM-L-018
layer: L3_domain
module: governance
dimension: governance
type: lesson
tier: hot
description: "TenantQuota Redis 计数必须用 INCR/DECR 原子操作；GET+SET 存在竞态条件，并发下计数会超额"
tags: [tenant-quota, redis, atomic-incr, race-condition, get-set, governance]
source_ep: EP-109
created_at: "2026-04-12"
last_accessed: "2026-04-12"
access_count: 5
related_memories: [MEM-L-007, AD-002]
also_in: [L2-D7]
generalized: true
version: 1
related_to:
  - id: "AD-002"
    reason: "配额检查必须在 tenant_id 范围内，RLS 基线约束同时适用于配额操作"
cites_files:
  - "backend/app/infrastructure/cache/"
impacts: []
---

# MEM-L-018 · TenantQuota Redis 计数必须用原子 INCR，禁止 GET+SET（竞态条件）

## WHERE（在哪个模块/场景中）

`backend/app/domain/governance/services/quota_service.py`
所有涉及租户配额消耗的场景：对象数量、存储用量、API 调用次数、SyncJob 并发数。

## WHAT（发生了什么）

使用 `GET + SET` 模式更新 Redis 配额计数时，高并发场景下会出现竞态条件：

```
线程 A: GET quota = 99
线程 B: GET quota = 99
线程 A: SET quota = 100  (99+1)
线程 B: SET quota = 100  (99+1)  ← 丢失一次计数，实际用了 101
```

结果：租户超出配额后系统未能正确拦截，造成资源泄漏。

## WHY（根本原因）

Redis `GET + SET` 是两步非原子操作，在高并发（如批量导入 10000 条对象）时，
多个协程同时读取旧值并各自加一写回，导致计数被覆盖。

`INCR` / `INCRBY` 是 Redis 原子命令，保证在任何并发情况下计数正确。

## HOW（解决方案）

```python
# ✅ 正确：使用原子 INCR 命令
class QuotaService:
    async def consume(
        self,
        ctx: SecurityContext,
        resource: QuotaResource,
        amount: int = 1,
    ) -> QuotaResult:
        key = f"quota:{ctx.tenant_id}:{resource.value}"
        limit_key = f"quota_limit:{ctx.tenant_id}:{resource.value}"

        # 原子操作：先 INCR，再检查是否超限
        async with self.redis.pipeline(transaction=True) as pipe:
            await pipe.incrby(key, amount)
            await pipe.get(limit_key)
            new_count, limit = await pipe.execute()

        if limit and int(new_count) > int(limit):
            # 超限：回滚计数
            await self.redis.decrby(key, amount)
            raise QuotaExceededError(
                tenant_id=ctx.tenant_id,
                resource=resource,
                current=int(new_count) - amount,
                limit=int(limit),
            )

        return QuotaResult(current=int(new_count), limit=int(limit) if limit else None)

# ❌ 错误：GET + SET（竞态条件）
async def consume(self, ctx, resource, amount=1):
    key = f"quota:{ctx.tenant_id}:{resource.value}"
    current = int(await self.redis.get(key) or 0)  # 🚨 非原子读
    new_count = current + amount
    await self.redis.set(key, new_count)           # 🚨 非原子写，高并发下覆盖
```

**配额 Key 设计规范**：
- 当前值：`quota:{tenant_id}:{resource}`（INCR 维护）
- 上限值：`quota_limit:{tenant_id}:{resource}`（管理员设置，较少变化）
- 过期策略：当前值 TTL=86400（每天重置），上限值无 TTL

## WHEN（触发条件）

- 任何需要追踪租户资源消耗的场景
- 批量导入（高并发写入）时配额检查
- 实现新的 `QuotaResource` 枚举值
