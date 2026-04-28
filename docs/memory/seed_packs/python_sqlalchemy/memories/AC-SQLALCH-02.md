---
id: AC-SQLALCH-02
tier: hot
layer: L2
protection_bonus: 0.35
tags: [python, sqlalchemy, orm, query, select]
---
# AC-SQLALCH-02：使用 select() 替代 session.query()

## 约束
MUST 使用 `select(Model)` + `session.execute()` 进行查询；
`session.query()` 在 SQLAlchemy 2.x 中为 Legacy API，将在 3.0 移除。

## 反例（Anti-pattern）

```python
# ❌ 旧式 Query API（2.x 已废弃）
users = session.query(User).filter(User.name == "alice").all()
user = session.query(User).get(user_id)
count = session.query(User).count()
```

## 正例（Correct Pattern）

```python
# ✅ SQLAlchemy 2.x 风格
from sqlalchemy import select

# 查询列表
stmt = select(User).where(User.name == "alice")
users = session.execute(stmt).scalars().all()

# 按主键查询
user = session.get(User, user_id)

# 聚合
from sqlalchemy import func
count_stmt = select(func.count()).select_from(User)
count = session.execute(count_stmt).scalar_one()
```

## 原因
`select()` 支持完整的 SQL 表达式 API，与 Core 层统一，
且在异步（AsyncSession）中同样可用。`session.query()` 缺乏异步支持。
