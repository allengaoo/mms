---
id: MEM-SEED-SEC-001
layer: L1_platform
module: security
type: decision
tier: hot
tags: [security, multi-tenant, rls, row-level-security, fastapi, seed]
source_ep: EP-130
created_at: 2026-04-18
version: 1
generalized: true
---

# MEM-SEED-SEC-001: 多租户行级安全（RLS）基线

## 决策

所有数据库查询必须包含 `tenant_id` 过滤，防止跨租户数据泄露。

## 强制规则

1. Service 公开方法首参必须是 `ctx: SecurityContext`（含 `tenant_id`）
2. Repository 层所有查询必须追加 `WHERE tenant_id = ctx.tenant_id`
3. API Endpoint 禁止直接接收 `tenant_id` 作为请求参数（必须从 JWT 提取）

## 代码模板

```python
class ItemRepository:
    async def find_by_id(self, ctx: SecurityContext, item_id: str) -> Optional[Item]:
        stmt = select(Item).where(
            Item.id == item_id,
            Item.tenant_id == ctx.tenant_id,  # ← 必须！
        )
        return (await session.execute(stmt)).scalar_one_or_none()
```

## 违反后果

跨租户数据泄露，严重的安全事故，可能导致法律责任。
