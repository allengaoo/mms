---
id: AC-PY-01
layer: ADAPTER
tier: hot
type: arch_constraint
language: python
pack: python_fastapi
about_concepts: [dependency-injection, database-session, fastapi, sqlalchemy]
cites_files: []
contradicts: []
created_at: "2026-04-27"
---

# FastAPI DB 会话必须通过 Depends(get_db) 注入

## 约束（Constraint）

在 FastAPI 的路由函数（API Route Layer）中，**绝对禁止**手动实例化数据库会话：

```python
# ❌ 错误：手动实例化（违反依赖注入原则）
@router.get("/users/{user_id}")
async def get_user(user_id: int):
    db = SessionLocal()          # 错误！
    try:
        return db.query(User).filter(User.id == user_id).first()
    finally:
        db.close()
```

**必须且只能**通过 `Depends(get_db)` 依赖注入获取数据库会话：

```python
# ✅ 正确：依赖注入
@router.get("/users/{user_id}")
async def get_user(user_id: int, db: Session = Depends(get_db)):
    return db.query(User).filter(User.id == user_id).first()
```

## 原因（Why）

1. **连接泄漏**：手动管理 `SessionLocal()` 在异常路径下容易忘记调用 `close()`，导致连接池耗尽
2. **测试困难**：手动创建的 Session 无法被测试框架 override，导致集成测试必须连真实 DB
3. **事务不一致**：多个手动 Session 之间无法共享事务，导致跨函数调用时数据不一致

## 参考

- FastAPI 官方文档：[SQL Databases](https://fastapi.tiangolo.com/tutorial/sql-databases/)
- 参考实现：`tiangolo/full-stack-fastapi-template/backend/app/api/deps.py`
