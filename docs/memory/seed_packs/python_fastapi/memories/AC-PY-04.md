---
id: AC-PY-04
layer: APP
tier: warm
type: lesson
language: python
pack: python_fastapi
about_concepts: [background-tasks, dependency-injection, fastapi, session-scope]
cites_files: []
contradicts: []
created_at: "2026-04-27"
---

# BackgroundTask 不能访问请求作用域的依赖

## 教训（Lesson）

FastAPI 的 `BackgroundTasks` 在请求响应返回后才执行，此时请求的作用域（包括通过 `Depends(get_db)` 创建的 DB Session）已经关闭。

```python
# ❌ 错误：BackgroundTask 使用请求作用域的 DB session
@router.post("/users/")
async def create_user(
    user_in: UserCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),          # 这个 session 在响应返回后就关闭了
):
    user = crud.create_user(db, user_in)
    background_tasks.add_task(send_welcome_email, db, user.email)  # ❌ db 已关闭！
    return user
```

## 正确做法

```python
# ✅ 正确：BackgroundTask 内部创建独立的 DB session
from app.db.session import SessionLocal

def send_welcome_email_task(user_email: str):
    db = SessionLocal()          # 独立 session，生命周期由 task 自己管理
    try:
        user = crud.get_user_by_email(db, email=user_email)
        email_service.send_welcome(user)
    finally:
        db.close()

@router.post("/users/")
async def create_user(user_in: UserCreate, background_tasks: BackgroundTasks):
    async with get_db_context() as db:
        user = crud.create_user(db, user_in)
    background_tasks.add_task(send_welcome_email_task, user.email)  # ✅ 只传递数据
    return user
```

## 参考

- FastAPI 文档：[Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)
