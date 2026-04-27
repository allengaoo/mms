---
id: AC-GO-06
layer: PLATFORM
tier: hot
type: arch_constraint
language: go
pack: go_microservice
about_concepts: [sql-injection, parameterized-query, gorm, database-sql, security]
cites_files: []
created_at: "2026-04-27"
---

# SQL 查询禁止 fmt.Sprintf 拼接，必须使用参数化查询

## 约束（Constraint）

```go
// ❌ SQL 注入漏洞：fmt.Sprintf 拼接用户输入
func (r *userRepo) FindByName(ctx context.Context, name string) ([]*User, error) {
    sql := fmt.Sprintf("SELECT * FROM users WHERE name = '%s'", name)
    // 攻击者传入：' OR '1'='1
    // 生成 SQL：SELECT * FROM users WHERE name = '' OR '1'='1'
    return r.db.WithContext(ctx).Raw(sql).Scan(&users).Error
}
```

```go
// ✅ 正确：GORM 参数化查询（自动转义）
func (r *userRepo) FindByName(ctx context.Context, name string) ([]*User, error) {
    var users []*User
    err := r.db.WithContext(ctx).
        Where("name = ?", name).   // ? 占位符，GORM 自动参数化
        Find(&users).Error
    if err != nil {
        return nil, fmt.Errorf("userRepo.FindByName: %w", err)
    }
    return users, nil
}

// ✅ 原生 SQL 时使用参数
func (r *orderRepo) SearchOrders(ctx context.Context, keyword string) ([]*Order, error) {
    var orders []*Order
    err := r.db.WithContext(ctx).
        Raw("SELECT * FROM orders WHERE description LIKE ?", "%"+keyword+"%").
        Scan(&orders).Error
    return orders, err
}
```

## GORM Raw 的安全用法

```go
// ✅ Raw + 命名参数（推荐复杂查询）
r.db.WithContext(ctx).Raw(
    "SELECT * FROM orders WHERE status = @status AND amount > @amount",
    map[string]interface{}{"status": 1, "amount": 100.0},
).Scan(&orders)
```

## 参考

- GORM 文档：[Raw SQL & SQL Builder](https://gorm.io/docs/sql_builder.html)
- OWASP：[SQL Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html)
