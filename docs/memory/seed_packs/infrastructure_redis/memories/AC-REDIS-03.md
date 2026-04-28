---
id: AC-REDIS-03
tier: warm
layer: CC
protection_bonus: 0.25
tags: [redis, naming-convention, key-design, namespace]
---
# AC-REDIS-03：Redis Key 必须遵循命名规范

## 约束
Key MUST 遵循 `{service}:{entity}:{id}` 层级命名；
NEVER 使用裸字符串、uuid 直接作为 key（无法按 pattern 扫描、运维困难）。

## 反例（Anti-pattern）

```python
# ❌ 裸 key，无命名空间
r.set("abc123", user_data)
r.set(user_id, token)          # 数字 key
r.set("profile", user_profile) # 无实体标识

# ❌ 不一致的分隔符
r.set("user.profile.123", data)  # 点号
r.set("user_profile_123", data)  # 下划线
```

## 正例（Correct Pattern）

```python
# ✅ 标准命名：{service}:{entity}:{id}
SERVICE = "auth"

def user_profile_key(user_id: int) -> str:
    return f"{SERVICE}:user:profile:{user_id}"

def session_key(token: str) -> str:
    return f"{SERVICE}:session:{token}"

def rate_limit_key(ip: str, endpoint: str) -> str:
    return f"ratelimit:{endpoint}:{ip}"

# ✅ 使用
r.set(user_profile_key(123), json.dumps(data), ex=3600)
r.get(session_key(token))

# ✅ 按 pattern 扫描（运维友好）
for key in r.scan_iter(f"{SERVICE}:user:profile:*"):
    print(key)
```

## 原因
结构化 key 允许通过 `SCAN pattern` 批量操作同类 key（如批量清除
某用户所有缓存），避免生产事故。同时明确了 key 的归属服务，
多团队共用 Redis 时不会冲突。
