---
id: MEM-DB-002
layer: L2_infrastructure
module: database
dimension: D9_database
type: lesson
tier: hot
description: "session.execute() 触发 autobegin 后再调 session.begin() 报 InvalidRequestError；事务策略 A/B 选一种不混用"
tags: [sqlalchemy, transaction, autobegin, session, asyncsession, begin]
source_ep: EP-087
created_at: "2026-01-15"
version: 1
last_accessed: "2026-04-11"
access_count: 28
related_memories: [AD-005]
also_in: [L4_application/D2_architecture]
generalized: true
related_to:
  - id: "AD-005"
    reason: "AD-005 是本记忆的架构规范出处，本记忆是违反 AD-005 的具体失败案例"
  - id: "AD-002"
    reason: "事务边界内必须同时有 tenant_id 过滤，两者共同保证数据安全"
cites_files:
  - "backend/app/core/db.py"
  - "backend/app/services/control/auth_service.py"
  - "backend/app/services/control/ontology_service.py"
impacts:
  - "AD-005"
---

# MEM-DB-002 · autobegin 后禁止再调 session.begin()

## WHERE（发生层/模块）
Layer 2 基础设施层 → Database 模块 → SQLAlchemy AsyncSession

## WHAT（问题类型）
Dimension 9: 数据库与迁移 — 事务管理崩溃级陷阱

## WHY（根因与影响）
**触发条件**：在 `session.execute()` 之后调用 `session.begin()`
**症状**：`InvalidRequestError: A transaction is already begun`（生产 500 错误）
**根因**：`AsyncSession` 默认 `autobegin=True`，任何 `execute()` 隐式开启事务；之后显式 `session.begin()` 冲突

## HOW（两种合法策略，二选一）
```python
# ✅ Strategy A：begin-first（读写混合 + 需要原子性）
async with session.begin():
    result = await session.execute(select(Model).where(...))
    session.add(new_obj)
    # 自动 commit on exit，自动 rollback on exception

# ✅ Strategy B：autobegin + explicit commit（简单写入）
obj = await session.get(Model, id)   # autobegin 触发
obj.field = new_value
await session.commit()               # 显式 commit

# ❌ 禁止：execute 之后再调 begin
result = await session.execute(...)  # autobegin 已触发
async with session.begin():          # InvalidRequestError!
    ...
```

## WHEN（应用条件）
- ✅ 所有 `services/control/` 下的写操作
- ✅ Strategy A 优先（更安全，自动 rollback）
- ✅ Strategy B 用于简单的单表写入

## 禁止项
- ❌ 任何 `execute()` 之后调用 `session.begin()`
- ❌ 混用两种策略（在同一函数中）
