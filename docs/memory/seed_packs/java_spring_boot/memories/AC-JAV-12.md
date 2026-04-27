---
id: AC-JAV-12
layer: DOMAIN
tier: warm
type: anti_pattern
language: java
pack: java_spring_boot
about_concepts: [cache, cacheable, spring-aop, self-invocation, proxy]
cites_files: []
contradicts: []
created_at: "2026-04-27"
---

# @Cacheable 自调用无效：同类方法不能调用缓存方法

## 反模式（Anti-Pattern）

Spring 的 `@Cacheable`、`@CachePut`、`@CacheEvict` 基于 AOP 代理实现。**在同一个类内部，方法 A 调用方法 B，即使 B 标注了 `@Cacheable`，缓存也不会生效**（自调用绕过 AOP 代理）。

```java
// ❌ @Cacheable 失效：self-invocation
@Service
public class ProductServiceImpl implements ProductService {

    public List<PmsProduct> listByCategory(Long categoryId) {
        // 内部调用 getById，但 this.getById 走的是原始对象，不走代理
        return categoryIds.stream()
            .map(id -> this.getById(id))   // ❌ 绕过 AOP！缓存不生效
            .collect(Collectors.toList());
    }

    @Cacheable(value = "product", key = "#id")
    public PmsProduct getById(Long id) {
        return productMapper.selectByPrimaryKey(id);
    }
}
```

```java
// ✅ 方案 1：拆分到独立 Spring Bean（推荐）
@Service
public class ProductCacheService {
    @Cacheable(value = "product", key = "#id")
    public PmsProduct getById(Long id) {
        return productMapper.selectByPrimaryKey(id);
    }
}

@Service
@RequiredArgsConstructor
public class ProductServiceImpl implements ProductService {
    private final ProductCacheService productCacheService;   // 注入另一个 Bean

    public List<PmsProduct> listByCategory(Long categoryId) {
        return ids.stream()
            .map(id -> productCacheService.getById(id))    // ✅ 走代理
            .collect(Collectors.toList());
    }
}

// ✅ 方案 2：注入自身代理（不推荐，代码丑陋）
@Service
public class ProductServiceImpl implements ProductService {
    @Autowired
    @Lazy
    private ProductService self;   // 注入自身的 Spring 代理

    public List<PmsProduct> listByCategory(Long categoryId) {
        return ids.stream().map(id -> self.getById(id)).collect(toList());
    }
}
```

## 参考

- Spring 文档：[Understanding AOP Proxies](https://docs.spring.io/spring-framework/docs/current/reference/html/core.html#aop-understanding-aop-proxies)
