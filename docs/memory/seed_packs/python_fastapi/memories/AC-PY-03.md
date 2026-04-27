---
id: AC-PY-03
layer: DOMAIN
tier: hot
type: anti_pattern
language: python
pack: python_fastapi
about_concepts: [n-plus-1, sqlalchemy, orm, lazy-loading, performance]
cites_files: []
contradicts: []
created_at: "2026-04-27"
---

# SQLAlchemy N+1 陷阱：关联对象必须用 selectinload/joinedload

## 反模式（Anti-Pattern）

SQLAlchemy 的默认懒加载（Lazy Loading）在循环中访问关联对象时会产生 N+1 查询问题。

```python
# ❌ N+1 反模式：每次访问 user.items 触发一次额外 SELECT
users = db.query(User).all()          # 1 次 SELECT
for user in users:
    print(user.items)                 # N 次 SELECT（每个 user 一次）
# 共 1 + N 次查询！
```

## 正确做法

```python
# ✅ selectinload：两次 SELECT，适合 1:N 关系（items 数量多）
from sqlalchemy.orm import selectinload

users = db.query(User).options(selectinload(User.items)).all()

# ✅ joinedload：一次 JOIN，适合 N:1 关系（如 item.owner）
from sqlalchemy.orm import joinedload

items = db.query(Item).options(joinedload(Item.owner)).all()

# ✅ SQLAlchemy 2.x 风格（推荐）
from sqlalchemy import select
from sqlalchemy.orm import selectinload

stmt = select(User).options(selectinload(User.items))
users = db.execute(stmt).scalars().all()
```

## 检测方法

使用 `sqlalchemy-utils` 的 `count_queries` 或 `SQLALCHEMY_ECHO=True` 环境变量在开发期检测 N+1。

## 参考

- SQLAlchemy 文档：[Relationship Loading Techniques](https://docs.sqlalchemy.org/en/20/orm/queryguide/relationships.html)
- 性能对比：selectinload vs joinedload vs subqueryload 在不同数据量下的表现
