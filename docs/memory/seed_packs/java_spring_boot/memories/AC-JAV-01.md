---
id: AC-JAV-01
layer: DOMAIN
tier: hot
type: arch_constraint
language: java
pack: java_spring_boot
about_concepts: [entity, dto, vo, mapstruct, layered-architecture, spring-boot]
cites_files: []
contradicts: []
created_at: "2026-04-27"
---

# @Entity 对象严禁跨越 Service 层，必须转换为 DTO/VO

## 约束（Constraint）

`@Entity` 标注的数据库模型类**绝对不允许**跨越 `Service` 层边界返回给 `Controller`。所有流出 `Service` 的对象必须通过 MapStruct 转化为 `XxxDTO`（传输对象）或 `XxxVO`（视图对象）。

```java
// ❌ 错误：直接返回 Entity
@RestController
@RequestMapping("/api/orders")
public class OrderController {
    @GetMapping("/{id}")
    public OmsOrder getOrder(@PathVariable Long id) {    // 返回 @Entity！
        return orderService.getById(id);
    }
}

// ❌ 错误：Service 返回 @Entity 集合
public List<UmsAdmin> listAdmins() {
    return adminMapper.selectAll();   // UmsAdmin 包含 password 字段！
}
```

```java
// ✅ 正确：通过 MapStruct 转换
@Mapper(componentModel = "spring")
public interface OrderConverter {
    OrderDetailVO toDetailVO(OmsOrder order);
    List<OrderListVO> toListVO(List<OmsOrder> orders);
}

@Service
public class OrderServiceImpl implements OrderService {
    @Override
    public OrderDetailVO getOrderDetail(Long id) {
        OmsOrder order = orderMapper.selectByPrimaryKey(id);
        return orderConverter.toDetailVO(order);    // ✅ 转换后返回
    }
}
```

## 原因（Why）

1. **敏感字段泄露**：`@Entity` 通常包含 `password`、`salt` 等字段，直接序列化到 JSON 会泄露敏感信息
2. **循环引用**：JPA Entity 之间的双向关联（`@OneToMany` + `@ManyToOne`）在 JSON 序列化时会导致无限递归
3. **API 契约不稳定**：数据库 Schema 变更会直接破坏 API 结构，DTO 层提供了稳定的契约屏障

## 参考

- 参考实现：`macrozheng/mall/mall-mbg/src/main/java/com/macro/mall/model/` (Entity) vs `mall-admin/src/main/java/com/macro/mall/dto/` (DTO)
- MapStruct 文档：https://mapstruct.org/documentation/stable/reference/html/
