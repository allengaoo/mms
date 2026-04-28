---
id: AC-SQLALCH-05
tier: hot
layer: L2
protection_bonus: 0.35
tags: [python, sqlalchemy, n+1, eager-loading, performance, selectinload]
---
# AC-SQLALCH-05：用 selectinload/joinedload 避免 N+1 查询

## 约束
MUST 在查询关联对象时显式指定加载策略；
NEVER 依赖懒加载（lazy="select"）在循环中访问关联属性，
否则每次访问都会触发一条额外 SQL（N+1 问题）。

## 反例（Anti-pattern）

```python
# ❌ 懒加载触发 N+1：查询 100 个 User 会产生 100+1 条 SQL
users = session.execute(select(User)).scalars().all()
for user in users:
    print(user.posts)  # 每次访问都触发 SELECT * FROM posts WHERE author_id=?
```

## 正例（Correct Pattern）

```python
from sqlalchemy.orm import selectinload, joinedload

# ✅ selectinload：对一对多推荐（批量 IN 查询，2 条 SQL）
stmt = select(User).options(selectinload(User.posts))
users = session.execute(stmt).scalars().all()
for user in users:
    print(user.posts)  # 无额外 SQL

# ✅ joinedload：对多对一/一对一推荐（JOIN 查询，1 条 SQL）
stmt = select(Post).options(joinedload(Post.author))
posts = session.execute(stmt).scalars().all()

# ✅ 嵌套加载（深层关联）
stmt = select(User).options(
    selectinload(User.posts).selectinload(Post.comments)
)
```

## 原因
N+1 是 ORM 最常见的性能问题。生产环境中，1000 条记录循环
会触发 1001 次数据库往返，在高并发下会压垮数据库连接池。
