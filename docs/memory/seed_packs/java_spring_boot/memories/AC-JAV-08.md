---
id: AC-JAV-08
layer: DOMAIN
tier: warm
type: lesson
language: java
pack: java_spring_boot
about_concepts: [transaction, propagation, requires-new, nested-transaction, spring]
cites_files: []
contradicts: []
created_at: "2026-04-27"
---

# @Transactional(propagation=REQUIRES_NEW) 会挂起外层事务，谨慎使用

## 教训（Lesson）

`REQUIRES_NEW` 传播行为会挂起当前事务，开启新的独立事务。这意味着**新事务提交后，即使外层事务回滚，新事务的数据变更已经持久化**，导致数据不一致。

```java
// ❌ 危险误用：以为 REQUIRES_NEW 能"隔离"异常
@Service
public class OrderServiceImpl {

    @Transactional
    public void createOrderWithAudit(OrderParam param) {
        // 1. 创建订单
        OmsOrder order = createOrder(param);

        // 2. 记录审计日志（以为 REQUIRES_NEW 能独立提交，不受主事务影响）
        auditService.log(order.getId(), "ORDER_CREATED");

        // 3. 后续操作抛出异常 → 主事务回滚，但审计日志已提交！
        stockService.deduct(param.getSkuIds());   // 抛出 StockInsufficientException
    }
}

@Service
public class AuditServiceImpl {
    @Transactional(propagation = Propagation.REQUIRES_NEW)   // 独立事务，立即提交
    public void log(Long orderId, String action) {
        auditLogMapper.insert(new AuditLog(orderId, action));
    }
}
```

## 正确使用场景

`REQUIRES_NEW` 只适合**必须独立提交的场景**（如审计日志、操作流水），且调用方已接受"即使主事务回滚，此记录仍保留"的语义：

```java
// ✅ 合法场景：失败记录必须保存（即使订单创建失败，也要记录失败原因）
@Transactional(propagation = Propagation.REQUIRES_NEW)
public void logFailure(Long taskId, String reason) {
    failureLogMapper.insert(new FailureLog(taskId, reason, LocalDateTime.now()));
}
```

## 推荐替代方案

对于需要事务隔离的审计日志，推荐使用 **Outbox 模式**：将日志消息写入同一事务的 `outbox` 表，由异步进程读取并投递。

## 参考

- Spring 文档：[Transaction Propagation](https://docs.spring.io/spring-framework/docs/current/reference/html/data-access.html#tx-propagation)
