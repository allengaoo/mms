---
id: AC-SQLALCH-03
tier: hot
layer: L2
protection_bonus: 0.30
tags: [python, sqlalchemy, session, context-manager, transaction]
---
# AC-SQLALCH-03：Session 必须通过 context manager 使用

## 约束
MUST 使用 `with Session(engine) as session` 或 `with session_factory() as session`；
NEVER 在 finally 块中手动调用 `session.close()`；Session 应在 context manager 退出时自动关闭。

## 反例（Anti-pattern）

```python
# ❌ 手动管理 Session 生命周期（容易泄漏连接）
session = Session(engine)
try:
    user = session.get(User, user_id)
    session.commit()
except Exception:
    session.rollback()
finally:
    session.close()  # 手动关闭，但异常路径可能被跳过
```

## 正例（Correct Pattern）

```python
# ✅ context manager 自动管理事务和连接
with Session(engine) as session:
    with session.begin():
        user = session.get(User, user_id)
        user.name = "new_name"
    # 事务自动提交，Session 自动关闭

# ✅ 或使用 sessionmaker
SessionLocal = sessionmaker(bind=engine)

def get_db():
    with SessionLocal() as session:
        yield session  # FastAPI dependency injection 模式
```

## 原因
context manager 确保即使发生异常，连接也会被归还连接池，
防止连接泄漏。手动 `session.close()` 在异常路径中常被漏掉。
