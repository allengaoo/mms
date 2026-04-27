---
id: AC-JAV-04
layer: DOMAIN
tier: warm
type: anti_pattern
language: java
pack: java_spring_boot
about_concepts: [dependency-injection, constructor-injection, autowired, lombok, spring-boot]
cites_files: []
contradicts: []
created_at: "2026-04-27"
---

# 禁止 @Autowired 字段注入，必须使用构造函数注入

## 反模式（Anti-Pattern）

`@Autowired` 字段注入（Field Injection）在 Spring 生态中应被彻底废弃，必须改用构造函数注入。

```java
// ❌ 字段注入反模式
@Service
public class OrderServiceImpl implements OrderService {
    @Autowired
    private OmsOrderMapper orderMapper;     // 无法 mock，测试困难

    @Autowired
    private UmsMemberService memberService; // 隐藏的循环依赖无法在编译期发现
}
```

```java
// ✅ 正确：构造函数注入（配合 Lombok @RequiredArgsConstructor）
@Service
@RequiredArgsConstructor                         // Lombok 自动生成构造函数
public class OrderServiceImpl implements OrderService {
    private final OmsOrderMapper orderMapper;    // final + 构造注入
    private final UmsMemberService memberService;
}
```

## 原因（Why）

1. **不可变性（Immutability）**：`final` 字段在对象构造完成后不可被修改，防止运行时意外替换
2. **测试友好**：构造函数注入的依赖可以在测试中通过 `new MyService(mockA, mockB)` 直接构造，无需 Spring 容器
3. **循环依赖早期发现**：循环依赖在应用启动时会立即报错（而非运行时 NPE），便于提前发现架构问题
4. **IntelliJ IDEA 告警**：IDE 会对字段注入提示 "Field injection is not recommended"，遵循工具建议

## 参考

- Spring 官方博客：[Why field injection is evil](https://odrotbohm.de/2013/11/why-field-injection-is-evil/)
