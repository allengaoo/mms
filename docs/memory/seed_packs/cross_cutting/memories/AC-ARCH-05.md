---
id: AC-ARCH-05
layer: PLATFORM
tier: hot
type: pattern
language: all
pack: cross_cutting
about_concepts: [timeout, retry, circuit-breaker, resilience, external-service]
cites_files: []
created_at: "2026-04-27"
---

# 所有外部服务调用必须配置超时和重试策略

## 模式（Pattern）

所有涉及外部服务（HTTP/gRPC/数据库/消息队列）的调用必须配置：
1. **超时（Timeout）**：防止调用方 goroutine/线程阻塞
2. **重试（Retry）**：对幂等的只读操作，网络抖动时自动重试
3. **熔断（Circuit Breaker）**：防止下游故障蔓延（可选，生产级系统推荐）

## 各语言实现

### Python (httpx + tenacity)

```python
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    reraise=True,
)
async def call_payment_service(order_id: str) -> dict:
    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
        response = await client.post(
            f"{PAYMENT_SERVICE_URL}/payments",
            json={"order_id": order_id},
        )
        response.raise_for_status()
        return response.json()
```

### Java (Resilience4j)

```java
@Bean
public Customizer<Resilience4JCircuitBreakerFactory> defaultCustomizer() {
    return factory -> factory.configureDefault(id -> new Resilience4JConfigBuilder(id)
        .timeLimiterConfig(TimeLimiterConfig.custom()
            .timeoutDuration(Duration.ofSeconds(5))
            .build())
        .circuitBreakerConfig(CircuitBreakerConfig.custom()
            .slidingWindowSize(10)
            .failureRateThreshold(50)
            .waitDurationInOpenState(Duration.ofSeconds(30))
            .build())
        .build());
}
```

### Go

```go
// 使用 hashicorp/go-retryablehttp
client := retryablehttp.NewClient()
client.HTTPClient.Timeout = 10 * time.Second
client.RetryMax = 3
client.RetryWaitMin = 1 * time.Second
client.RetryWaitMax = 5 * time.Second
client.CheckRetry = retryablehttp.DefaultRetryPolicy   // 只重试幂等请求
```

## 重要原则

1. **写操作不重试**（非幂等）：POST 创建资源的请求失败时，重试可能导致重复创建
2. **使用指数退避**：避免大量请求同时重试造成下游雪崩（Thundering Herd Problem）
3. **设置合理超时层次**：连接超时（2s）< 读取超时（5s）< 总超时（10s）

## 参考

- Resilience4j：https://resilience4j.readme.io/docs
- tenacity：https://tenacity.readthedocs.io/
