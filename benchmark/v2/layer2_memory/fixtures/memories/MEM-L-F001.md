---
id: MEM-L-F001
title: 跨服务调用必须通过 Repository 接口隔离，禁止直接引用 Session
type: lesson
layer: DOMAIN
dimension: D9
tags: [transaction, database, repository-pattern, isolation]
about_concepts: [transaction, database-access, session-management, repository]
access_count: 12
last_accessed: "2026-04-20"
tier: hot
drift_suspected: false
version: 1
---

## WHERE（适用场景）
在 Service 层或 Application Handler 层需要访问数据库时，尤其是多服务共享数据库的情况。

## HOW（核心实现）
1. 所有数据库操作必须封装在 Repository 接口后，Service 层只调用 Repository 方法，不直接操作 Session/Connection。
2. 事务边界必须在 Service 层（或 Application Handler）声明，而非在 Repository 内部。
3. Repository 接口定义在 DOMAIN 层，实现类在 ADAPTER 层（防止领域逻辑依赖具体 ORM）。

## WHEN（触发条件）
- 当 Service 方法直接 `import sqlalchemy.orm.Session` 时立即触发此规则检查。
- 当多个 Service 共享同一个 Repository 查询时，需检查 N+1 风险。
