---
id: AC-REDIS-05
tier: warm
layer: CC
protection_bonus: 0.25
tags: [redis, async, aioredis, fastapi, asyncio]
---
# AC-REDIS-05：异步场景必须使用 redis.asyncio

## 约束
在 FastAPI / asyncio 服务中 MUST 使用 `redis.asyncio`（内置于 redis-py 4.2+）；
NEVER 在 `async def` 中调用同步 redis 客户端（阻塞事件循环）。

## 反例（Anti-pattern）

```python
# ❌ 同步客户端阻塞 asyncio 事件循环
import redis

async def get_cached_user(user_id: int):
    r = redis.Redis(host="localhost")  # 同步！
    data = r.get(f"user:{user_id}")   # IO 阻塞事件循环线程
    return json.loads(data) if data else None
```

## 正例（Correct Pattern）

```python
# ✅ redis.asyncio（redis-py 4.2+ 内置）
import redis.asyncio as aioredis
from fastapi import FastAPI, Depends

app = FastAPI()

# 全局连接池
redis_pool: aioredis.ConnectionPool | None = None

@app.on_event("startup")
async def startup():
    global redis_pool
    redis_pool = aioredis.ConnectionPool.from_url(
        settings.REDIS_URL,
        max_connections=20,
        decode_responses=True,
    )

@app.on_event("shutdown")
async def shutdown():
    if redis_pool:
        await redis_pool.disconnect()

async def get_redis() -> aioredis.Redis:
    return aioredis.Redis(connection_pool=redis_pool)

# ✅ 路由中使用
@app.get("/user/{user_id}")
async def get_user(user_id: int, r: aioredis.Redis = Depends(get_redis)):
    cached = await r.get(f"user:profile:{user_id}")
    if cached:
        return json.loads(cached)
    # ... 从数据库获取并缓存
    await r.set(f"user:profile:{user_id}", json.dumps(user), ex=3600)
    return user
```

## 原因
同步 IO 在异步事件循环线程中执行会占用唯一的 IO 线程，
导致所有并发请求在等待期间都被阻塞，表现为整个服务响应超时。
