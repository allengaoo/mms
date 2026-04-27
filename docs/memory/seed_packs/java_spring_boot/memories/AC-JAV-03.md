---
id: AC-JAV-03
layer: DOMAIN
tier: hot
type: arch_constraint
language: java
pack: java_spring_boot
about_concepts: [repository, mapper, mybatis, jpa, interface, spring-boot]
cites_files: []
contradicts: []
created_at: "2026-04-27"
---

# Repository/Mapper 必须是接口，禁止写实现类

## 约束（Constraint）

数据访问层（Repository/Mapper）必须定义为接口（extends `JpaRepository<T, ID>` 或 MyBatis 的 Mapper 接口），禁止手写实现类。

```java
// ❌ 错误：手写 Repository 实现类
@Repository
public class OrderRepositoryImpl implements OrderRepository {
    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Override
    public List<OmsOrder> findByUserId(Long userId) {
        return jdbcTemplate.query(
            "SELECT * FROM oms_order WHERE member_id = ?",
            new Object[]{userId},
            new OrderRowMapper()
        );
    }
}
```

```java
// ✅ 正确（JPA 风格）：接口即实现
public interface OmsOrderRepository extends JpaRepository<OmsOrder, Long> {
    List<OmsOrder> findByMemberId(Long memberId);

    @Query("SELECT o FROM OmsOrder o WHERE o.memberId = :memberId AND o.status = :status")
    Page<OmsOrder> findByMemberIdAndStatus(
        @Param("memberId") Long memberId,
        @Param("status") Integer status,
        Pageable pageable
    );
}

// ✅ 正确（MyBatis 风格）：@Mapper 接口 + XML/注解
@Mapper
public interface OmsOrderMapper extends BaseMapper<OmsOrder> {
    List<OmsOrderDetail> getDetail(@Param("id") Long id);
}
```

## 原因（Why）

1. **框架代理**：JPA/MyBatis 在运行时通过动态代理自动实现接口，手写实现类是对框架机制的对抗
2. **测试简便**：接口可以被 Mockito 直接 mock，实现类需要额外的 `@Spy` 配置
3. **维护成本**：手写 SQL 映射在字段变更时容易遗漏更新，框架生成的查询更安全
