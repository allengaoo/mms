---
id: AC-JAV-10
layer: DOMAIN
tier: warm
type: lesson
language: java
pack: java_spring_boot
about_concepts: [mybatis, batch-insert, foreach, performance, sql-length]
cites_files: []
contradicts: []
created_at: "2026-04-27"
---

# MyBatis <foreach> 批量插入超过 1000 条必须分批

## 教训（Lesson）

MyBatis `<foreach>` 批量插入在 list 超过 1000 条时，生成的 SQL 语句会超过 MySQL 的 `max_allowed_packet` 限制（默认 4MB），导致 `Packet for query is too large` 异常。

```java
// ❌ 危险：不分批，超过 1000 条时崩溃
public void batchInsertOrderItems(List<OmsOrderItem> items) {
    orderItemMapper.batchInsert(items);   // items 可能有几千条！
}
```

```java
// ✅ 正确：分批插入，每批 500 条（留有安全余量）
private static final int BATCH_SIZE = 500;

public void batchInsertOrderItems(List<OmsOrderItem> items) {
    if (items == null || items.isEmpty()) return;

    // Guava Lists.partition 或手动分批
    for (int i = 0; i < items.size(); i += BATCH_SIZE) {
        List<OmsOrderItem> batch = items.subList(i, Math.min(i + BATCH_SIZE, items.size()));
        orderItemMapper.batchInsert(batch);
    }
}
```

## 更优方案：MyBatis ExecutorType.BATCH

```java
// 使用 BatchExecutor 避免 N+1 次网络往返，同时不受 SQL 长度限制
@Transactional
public void batchInsertWithExecutor(List<OmsOrderItem> items) {
    try (SqlSession session = sqlSessionFactory.openSession(ExecutorType.BATCH)) {
        OmsOrderItemMapper mapper = session.getMapper(OmsOrderItemMapper.class);
        items.forEach(mapper::insert);
        session.commit();
    }
}
```

## 参考

- MySQL 文档：[max_allowed_packet](https://dev.mysql.com/doc/refman/8.0/en/server-system-variables.html#sysvar_max_allowed_packet)
- MyBatis 文档：[Batch Executor](https://mybatis.org/mybatis-3/java-api.html#sqlsessions)
