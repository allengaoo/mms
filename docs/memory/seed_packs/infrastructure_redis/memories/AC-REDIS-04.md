---
id: AC-REDIS-04
tier: hot
layer: CC
protection_bonus: 0.40
tags: [redis, keys, scan, performance, production]
---
# AC-REDIS-04：禁止在生产环境使用 KEYS * 命令

## 约束
NEVER 在生产代码中使用 `KEYS *` 或 `KEYS pattern`（单线程阻塞命令）；
MUST 使用 `SCAN` 迭代器遍历 key（非阻塞，游标分批）。

## 反例（Anti-pattern）

```python
# ❌ KEYS * 会阻塞 Redis 事件循环（百万 key 时阻塞 >1s）
all_keys = r.keys("*")
user_keys = r.keys("user:*")
r.delete(*r.keys("session:*"))  # 极其危险！
```

## 正例（Correct Pattern）

```python
# ✅ SCAN 分批迭代（非阻塞）
def delete_by_pattern(r: redis.Redis, pattern: str, batch_size: int = 100) -> int:
    """安全删除匹配 pattern 的所有 key。"""
    deleted = 0
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor, match=pattern, count=batch_size)
        if keys:
            r.delete(*keys)
            deleted += len(keys)
        if cursor == 0:
            break
    return deleted

# ✅ 使用 scan_iter（更 Pythonic）
def count_by_pattern(r: redis.Redis, pattern: str) -> int:
    return sum(1 for _ in r.scan_iter(pattern, count=100))

# ✅ 用法
delete_by_pattern(r, "auth:session:*")   # 清除所有 session
count_by_pattern(r, "cart:*")            # 统计购物车数量
```

## 原因
Redis 是单线程执行命令的。`KEYS *` 在包含 100 万 key 的实例上
可能阻塞 >1 秒，期间所有其他命令无法执行，导致服务超时告警。
这是生产环境中 Redis 慢查询的首要来源。
