---
id: MEM-SEED-DB-001
layer: L2_infrastructure
module: database
type: anti-pattern
tier: hot
tags: [sqlalchemy, transaction, autobegin, session, fastapi, seed]
source_ep: EP-130
created_at: 2026-04-18
version: 1
generalized: true
---

# MEM-SEED-DB-001: SQLAlchemy autobegin 陷阱（FastAPI + AsyncSession）

## 反模式

```python
# ❌ 错误：session.execute() 触发 autobegin 后再调 session.begin()
async def create_item(session: AsyncSession, data: dict):
    await session.execute(select(Item))  # 此处已触发 autobegin
    async with session.begin():          # ❌ InvalidRequestError: transaction already begun
        session.add(Item(**data))
```

## 正确做法

**策略 A（Begin-First）**：
```python
async def create_item(session: AsyncSession, data: dict):
    async with session.begin():          # 先 begin
        existing = await session.execute(select(Item))
        session.add(Item(**data))
```

**策略 B（Autobegin + Explicit Commit）**：
```python
async def create_item(session: AsyncSession, data: dict):
    existing = await session.execute(select(Item))   # autobegin
    session.add(Item(**data))
    await session.commit()                           # 显式 commit
```

## 根因

SQLAlchemy 2.x AsyncSession 使用"autobegin"模式：任何 execute/query 调用都会隐式开启事务。在此之后再调 `session.begin()` 会抛出 `InvalidRequestError`。
