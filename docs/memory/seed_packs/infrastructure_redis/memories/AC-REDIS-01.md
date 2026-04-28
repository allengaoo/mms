---
id: AC-REDIS-01
tier: hot
layer: CC
protection_bonus: 0.35
tags: [redis, cache, ttl, expiry, memory]
---
# AC-REDIS-01：所有缓存写入必须设置 TTL

## 约束
Redis 中 MUST 为每个 SET 操作指定过期时间（`ex`/`px`/`exat`）；
NEVER 写入无 TTL 的 key（否则 Redis 内存将无限增长，最终导致 OOM）。

## 反例（Anti-pattern）

```python
# ❌ 无 TTL：Redis 内存泄漏
r.set("user:profile:123", json.dumps(user_data))
r.set("session:abc123", token)
r.hset("cart:456", mapping=cart_items)  # Hash 同样需要 EXPIRE
```

## 正例（Correct Pattern）

```python
import redis
import json

r = redis.Redis(connection_pool=pool)

# ✅ 使用 ex 参数（秒）
r.set("user:profile:123", json.dumps(user_data), ex=3600)   # 1小时

# ✅ 使用 px 参数（毫秒）
r.set("rate_limit:ip:1.2.3.4", "1", px=60_000)              # 60秒

# ✅ Hash 类型：先设值再 EXPIRE
pipe = r.pipeline()
pipe.hset("cart:456", mapping=cart_items)
pipe.expire("cart:456", 86400)  # 24小时
pipe.execute()

# ✅ 常量化 TTL（集中管理，避免魔法数字）
CACHE_TTL = {
    "user_profile": 3600,
    "session": 1800,
    "rate_limit": 60,
}
r.set(f"user:profile:{user_id}", data, ex=CACHE_TTL["user_profile"])
```

## 原因
Redis 默认为内存存储，无 TTL 的 key 永不过期。生产环境中，
即使内存充裕，旧数据的累积也会导致缓存命中率下降和运维困难。
