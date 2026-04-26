---
id: MEM-L-F003
title: Redis 缓存 TTL 策略：多租户场景必须加 tenant_id 前缀防止数据泄漏
type: lesson
layer: PLATFORM
dimension: D7
tags: [redis, cache, multi-tenant, ttl, security]
about_concepts: [cache, redis, tenant-isolation, performance]
access_count: 15
last_accessed: "2026-04-22"
tier: hot
drift_suspected: false
version: 1
---

## WHERE（适用场景）
在多租户 SaaS 系统中使用 Redis 缓存任何与租户相关的业务数据时。

## HOW（核心实现）
1. 缓存 key 格式：`{tenant_id}:{entity_type}:{entity_id}` — 严禁省略 tenant_id 前缀。
2. TTL 设置原则：热数据 5 分钟，温数据 30 分钟，冷数据不缓存（降低数据过期风险）。
3. 缓存失效时使用 SCAN + DEL（禁止 KEYS *，防止生产 Redis 卡顿）。

## WHEN（触发条件）
- 任何新增 Redis 写入操作时，需要 code review 检查是否有 tenant_id 前缀。
- 租户切换/切出时必须清理对应 tenant_id 的所有缓存。
