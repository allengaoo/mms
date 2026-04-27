---
id: AC-JAV-06
layer: PLATFORM
tier: hot
type: arch_constraint
language: java
pack: java_spring_boot
about_concepts: [sql-injection, mybatis, parameterized-query, security]
cites_files: []
contradicts: []
created_at: "2026-04-27"
---

# MyBatis 必须使用 #{} 参数绑定，禁止 ${} 直接插值

## 约束（Constraint）

在 MyBatis XML Mapper 和注解 SQL 中，**严禁使用 `${param}` 直接将用户输入插值到 SQL 字符串**。必须使用 `#{param}` 参数绑定（预编译 PreparedStatement）。

```xml
<!-- ❌ 错误：${} 直接插值 → SQL 注入漏洞 -->
<select id="searchOrders" resultType="OmsOrder">
    SELECT * FROM oms_order
    WHERE status = ${status}              <!-- SQL 注入！-->
    AND member_name LIKE '%${keyword}%'   <!-- SQL 注入！-->
    ORDER BY ${orderBy}                   <!-- SQL 注入！-->
</select>
```

```xml
<!-- ✅ 正确：#{} 参数绑定 -->
<select id="searchOrders" resultType="OmsOrder">
    SELECT * FROM oms_order
    WHERE status = #{status}
    AND member_name LIKE CONCAT('%', #{keyword}, '%')
    ORDER BY create_time DESC          <!-- 排序字段用白名单枚举替代 ${} -->
</select>
```

## ${} 合法用场景（仅限非用户输入）

```xml
<!-- ✅ 合法：表名/列名在代码中控制，非用户输入 -->
<select id="queryByTable" resultType="map">
    SELECT * FROM ${tableName}   <!-- tableName 必须是枚举白名单，非用户传入 -->
</select>
```

## 动态排序的安全写法

```java
// Service 层：用枚举白名单替代 ${orderBy}
public enum OrderSortField {
    CREATE_TIME("create_time"),
    AMOUNT("pay_amount");

    private final String column;
}

// Mapper XML：不再需要 ${orderBy}
// 在 Service 层对排序字段做枚举校验，再拼接到 SQL
```

## 参考

- MyBatis 文档：[String Substitution](https://mybatis.org/mybatis-3/sqlmap-xml.html#string-substitution)
- OWASP：[SQL Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html)
