---
id: AC-REDIS-02
tier: hot
layer: CC
protection_bonus: 0.35
tags: [redis, connection-pool, performance, resource-management]
---
# AC-REDIS-02：必须使用连接池，禁止每次请求新建连接

## 约束
MUST 在应用启动时初始化 `ConnectionPool`，并复用；
NEVER 在请求处理函数中直接 `Redis(host=...)` 创建新连接（每次都会建立 TCP 握手）。

## 反例（Anti-pattern）

```python
# ❌ 每次请求都创建新连接（TCP 握手开销极大）
def get_user_cache(user_id: int):
    r = redis.Redis(host="localhost", port=6379, db=0)  # 每次新建！
    return r.get(f"user:{user_id}")

# ❌ 函数内 StrictRedis 实例化
def set_session(token: str, data: dict):
    r = redis.StrictRedis(host=REDIS_HOST, decode_responses=True)
    r.set(f"session:{token}", json.dumps(data), ex=1800)
```

## 正例（Correct Pattern）

```python
import redis
from functools import lru_cache

# ✅ 模块级连接池（应用启动时初始化一次）
pool = redis.ConnectionPool(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    db=0,
    max_connections=50,
    decode_responses=True,
)
r = redis.Redis(connection_pool=pool)

# ✅ FastAPI / 依赖注入模式
@lru_cache()
def get_redis_pool() -> redis.ConnectionPool:
    return redis.ConnectionPool.from_url(
        settings.REDIS_URL,
        max_connections=50,
        decode_responses=True,
    )

def get_redis() -> redis.Redis:
    return redis.Redis(connection_pool=get_redis_pool())
```

## 原因
TCP 连接建立（握手+认证）开销约 1-2ms，在 1000 QPS 下会
额外消耗 1-2s CPU 时间。连接池允许复用已有连接，P99 延迟
可降低 50%+。
