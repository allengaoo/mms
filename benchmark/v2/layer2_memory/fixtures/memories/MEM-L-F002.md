---
id: MEM-L-F002
title: Spring @Transactional 传播机制：REQUIRES_NEW 会导致外层事务中断
type: anti-pattern
layer: ADAPTER
dimension: D9
tags: [spring, transaction, propagation, requires-new, java]
about_concepts: [transaction, spring-framework, database-consistency]
access_count: 8
last_accessed: "2026-04-15"
tier: warm
drift_suspected: false
version: 1
---

## WHERE（适用场景）
在 Spring Boot 项目中，Service 方法标注 `@Transactional`，内部调用另一个标注 `@Transactional(propagation = REQUIRES_NEW)` 的方法时。

## HOW（核心实现）
1. `REQUIRES_NEW` 会挂起当前事务，开启一个全新独立事务。若内层事务提交但外层事务回滚，数据不一致。
2. 正确用法：只在需要"无论外层是否回滚，内层操作都必须提交"的场景（如审计日志写入）使用 REQUIRES_NEW。
3. 检测方法：在 arch_check 中扫描 `REQUIRES_NEW` 用法，要求添加注释说明为什么需要独立事务。

## WHEN（触发条件）
- 当审计日志、消息发送等副作用操作使用 `REQUIRES_NEW` 时，需要特别关注外层事务失败的补偿逻辑。
