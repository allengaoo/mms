---
id: AC-JAV-05
layer: DOMAIN
tier: warm
type: lesson
language: java
pack: java_spring_boot
about_concepts: [transaction, read-only, performance, jpa, spring-data]
cites_files: []
contradicts: []
created_at: "2026-04-27"
---

# 只读 Service 方法必须标注 @Transactional(readOnly=true)

## 教训（Lesson）

所有只进行数据读取（无写入操作）的 Service 方法，必须标注 `@Transactional(readOnly = true)`，以提升数据库读性能并防止脏数据写入。

```java
// ❌ 未标注 readOnly 的查询方法
@Service
public class OmsOrderServiceImpl implements OmsOrderService {
    public List<OmsOrder> listOrders(Long memberId) {   // 未标注事务！
        return orderMapper.selectByMemberId(memberId);
    }
}
```

```java
// ✅ 正确：类级别标注 readOnly=true，写操作方法覆盖为 readOnly=false
@Service
@Transactional(readOnly = true)                 // 类级别默认只读
public class OmsOrderServiceImpl implements OmsOrderService {

    public List<OmsOrder> listOrders(Long memberId) {
        return orderMapper.selectByMemberId(memberId);   // 继承只读事务
    }

    @Transactional(readOnly = false)            // 写操作显式覆盖
    public Long createOrder(OrderParam param) {
        // ...
    }
}
```

## 性能收益

| 数据库 | readOnly=true 的效果 |
|---|---|
| MySQL/InnoDB | 禁止 undo log 生成，减少 MVCC 开销；可被路由到只读从库 |
| PostgreSQL | 跳过 WAL 同步，降低 I/O 压力 |
| Hibernate/JPA | 禁用 Dirty Checking（脏检查），减少 Session flush 开销 |

## 参考

- Spring 文档：[@Transactional readOnly](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/transaction/annotation/Transactional.html#readOnly--)
