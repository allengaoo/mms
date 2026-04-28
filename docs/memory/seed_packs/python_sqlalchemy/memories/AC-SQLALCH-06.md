---
id: AC-SQLALCH-06
tier: hot
layer: L2
protection_bonus: 0.35
tags: [python, sqlalchemy, async, asyncsession, fastapi]
---
# AC-SQLALCH-06：异步场景必须使用 AsyncSession + create_async_engine

## 约束
在 async def 函数中 MUST 使用 `AsyncSession`；
NEVER 在异步上下文中混用同步 `Session`（会阻塞事件循环导致服务假死）。

## 反例（Anti-pattern）

```python
# ❌ 在 async 中使用同步 Session（阻塞事件循环）
async def get_user(user_id: int):
    engine = create_engine("postgresql://...")  # 同步引擎！
    with Session(engine) as session:
        return session.get(User, user_id)  # IO 阻塞在事件循环线程
```

## 正例（Correct Pattern）

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

# ✅ 初始化（全局一次）
engine = create_async_engine(
    "postgresql+asyncpg://user:pass@localhost/db",
    pool_size=10,
    max_overflow=20,
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

# ✅ FastAPI 依赖注入
async def get_async_db():
    async with AsyncSessionLocal() as session:
        yield session

# ✅ 异步查询
async def get_user(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)

async def list_users(session: AsyncSession) -> list[User]:
    stmt = select(User).options(selectinload(User.posts))
    result = await session.execute(stmt)
    return result.scalars().all()
```

## 原因
同步 Session 的 IO 操作会在事件循环线程中阻塞，在并发负载下
导致服务响应延迟飙升。AsyncSession 将 IO 交给 asyncio，
让事件循环在等待期间处理其他请求。
