---
id: AC-ARCH-02
layer: PLATFORM
tier: hot
type: arch_constraint
language: all
pack: cross_cutting
about_concepts: [database-migration, ddl, business-logic, separation-of-concerns]
cites_files: []
created_at: "2026-04-27"
---

# 数据库迁移脚本中禁止包含业务逻辑

## 约束（Constraint）

数据库迁移脚本（Alembic/Flyway/Liquibase/golang-migrate）只能包含 DDL（CREATE/ALTER/DROP TABLE）和简单的 DML（数据填充）。**禁止在迁移脚本中包含业务计算逻辑、条件分支、外部服务调用。**

```sql
-- ❌ 错误：迁移脚本中包含业务逻辑
-- V2__migrate_order_status.sql
UPDATE orders
SET new_status = CASE
    WHEN payment_time IS NOT NULL AND shipping_time IS NULL THEN 'PAID'
    WHEN shipping_time IS NOT NULL AND receive_time IS NULL THEN 'SHIPPED'
    WHEN receive_time IS NOT NULL THEN 'COMPLETED'
    ELSE 'PENDING'
END;
-- 问题：业务状态逻辑写死在 SQL 中，未来状态机变更无法同步
```

```sql
-- ✅ 正确：迁移脚本只做结构变更
-- V2__add_new_status_column.sql
ALTER TABLE orders ADD COLUMN new_status VARCHAR(20) NOT NULL DEFAULT 'PENDING';
CREATE INDEX idx_orders_new_status ON orders(new_status);
```

```python
# 业务数据迁移通过独立的 Python/Go 脚本处理（可复用 Service 层逻辑）
# scripts/migrate_order_status.py
def migrate_order_status():
    for order in Order.query.all():
        order.new_status = order_service.compute_status(order)  # 复用 Service 逻辑
    db.session.commit()
```

## 原因（Why）

1. **可维护性**：业务逻辑写在 SQL 中无法被应用层的单元测试覆盖
2. **版本一致性**：迁移脚本是时间点快照，其中的业务逻辑无法随应用代码一起演进
3. **回滚安全**：纯 DDL 迁移的 `down()` 脚本是可靠的，含业务逻辑的迁移几乎无法安全回滚
