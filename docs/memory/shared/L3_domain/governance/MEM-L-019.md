---
id: MEM-L-019
layer: L3_domain
module: governance
dimension: governance
type: decision
tier: warm
tags: [change-request, cr, approval-flow, mysql, redis, state-machine, governance]
source_ep: EP-109
created_at: "2026-04-12"
last_accessed: "2026-04-12"
access_count: 2
related_memories: [MEM-L-018, MEM-L-014, AD-004]
also_in: [L4-D2]
generalized: true
version: 1
---

# MEM-L-019 · CR 审批流状态必须持久化到 MySQL，Redis 只用于加速读取

## WHERE（在哪个模块/场景中）

`backend/app/domain/governance/services/change_request_service.py`
变更请求（CR）的状态流转：DRAFT → PENDING → APPROVED / REJECTED → APPLIED。

## WHAT（发生了什么）

早期版本将 CR 状态存储在 Redis Hash 中（仅 Redis）：
1. Redis 重启后，所有待审批 CR 的状态丢失
2. 审批人 A 批准的同时审批人 B 也批准（Redis 无事务保障），导致重复执行变更
3. 审计报告无法查询历史 CR（Redis 无持久化查询能力）
4. CR 附带的变更 payload（JSON）可能超过 Redis 默认 value 大小限制（512MB 理论上限，但实际 key-value 过大影响内存）

## WHY（根本原因）

审批流是**高价值、低频**的业务操作，需要：
- **持久性**：服务重启不丢失状态（Redis 默认非持久化）
- **事务性**：状态流转必须是原子操作（MySQL 事务 vs Redis 管道）
- **可查询性**：支持历史审计查询（MySQL 全文检索 vs Redis 仅键值查询）
- **一致性**：多个审批人同时操作时必须加行锁（MySQL `SELECT FOR UPDATE`）

## HOW（解决方案）

```python
# ✅ 正确：MySQL 持久化 + Redis 加速读取
class ChangeRequestService:

    # 写操作：MySQL 事务
    async def approve(
        self,
        ctx: SecurityContext,
        cr_id: str,
    ) -> ChangeRequest:
        async with self.session.begin():
            # 行锁防止并发审批冲突
            cr = await self.session.execute(
                select(ChangeRequestModel)
                .where(ChangeRequestModel.id == cr_id)
                .with_for_update()   # SELECT FOR UPDATE
            )
            cr = cr.scalar_one()

            if cr.status != CRStatus.PENDING:
                raise InvalidStateError(f"CR 当前状态为 {cr.status}，不可审批")

            cr.status = CRStatus.APPROVED
            cr.approved_by = ctx.user_id
            cr.approved_at = datetime.utcnow()

            await self.audit_service.log(ctx, "cr_approve", target=cr_id)

        # 更新 Redis 缓存（异步，失败不影响主流程）
        await self._update_cache(cr)
        return cr

    # 读操作：Redis 优先，MySQL 兜底
    async def get_cr(self, ctx: SecurityContext, cr_id: str) -> ChangeRequest:
        cached = await self.redis.hgetall(f"cr:{cr_id}")
        if cached:
            return ChangeRequest(**cached)
        # Cache miss → MySQL 查询并回填缓存
        cr = await self._load_from_db(ctx, cr_id)
        await self._update_cache(cr)
        return cr

# ❌ 错误：仅 Redis 存储 CR 状态
async def approve(self, cr_id):
    await self.redis.hset(f"cr:{cr_id}", "status", "APPROVED")  # 🚨 Redis 重启丢失
```

**状态流转规则**（MySQL 行级锁保障）：
```
DRAFT → PENDING（提交审批）
PENDING → APPROVED（审批人同意）  — 需要 SELECT FOR UPDATE
PENDING → REJECTED（审批人拒绝）  — 需要 SELECT FOR UPDATE
APPROVED → APPLIED（系统执行变更）
APPLIED → [终态]（不可再流转）
```

## WHEN（触发条件）

- 实现新的 CR 类型（如 `shared_property_update`、`object_type_delete`）
- 审批流出现并发冲突（同一 CR 被批准两次）
- Redis 重启后 CR 状态对 UI 不可见
