---
id: AC-JAV-02
layer: ADAPTER
tier: hot
type: arch_constraint
language: java
pack: java_spring_boot
about_concepts: [exception-handling, rest-controller-advice, business-exception, spring-boot]
cites_files: []
contradicts: []
created_at: "2026-04-27"
---

# Controller 禁止 try-catch 业务异常，统一由 @RestControllerAdvice 处理

## 约束（Constraint）

禁止在 Controller 层书写 `try-catch` 块捕捉业务异常。必须直接抛出自定义的 `BusinessException`，由标注了 `@RestControllerAdvice` 的全局异常处理器统一接管。

```java
// ❌ 错误：Controller 内 try-catch
@PostMapping("/order/create")
public CommonResult createOrder(@RequestBody OrderParam orderParam) {
    try {
        OmsOrder order = orderService.createOrder(orderParam);
        return CommonResult.success(order);
    } catch (IllegalArgumentException e) {
        return CommonResult.failed(e.getMessage());    // 错误！格式不统一
    } catch (StockInsufficientException e) {
        return CommonResult.failed(400, "库存不足");   // 错误！业务码散落各处
    }
}
```

```java
// ✅ 正确：Service 层抛出异常，Controller 不捕获
@PostMapping("/order/create")
public CommonResult<OmsOrderDetail> createOrder(@RequestBody OrderParam orderParam) {
    OmsOrderDetail order = orderService.createOrder(orderParam);    // 直接调用
    return CommonResult.success(order);
}

// 全局异常处理器
@RestControllerAdvice
public class GlobalExceptionHandler {
    @ExceptionHandler(BusinessException.class)
    public CommonResult<Void> handleBusinessException(BusinessException e) {
        return CommonResult.failed(e.getCode(), e.getMessage());
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public CommonResult<Void> handleValidationException(MethodArgumentNotValidException e) {
        String message = e.getBindingResult().getFieldErrors().stream()
            .map(FieldError::getDefaultMessage)
            .collect(Collectors.joining(", "));
        return CommonResult.failed(ResultCode.VALIDATE_FAILED, message);
    }
}
```

## 原因（Why）

1. **响应格式统一**：全局处理器确保所有错误响应都使用相同的 JSON 信封格式 `{"code":..., "message":..., "data":null}`
2. **错误码集中管理**：业务错误码集中定义在枚举中（如 `ResultCode`），而非散落在各 Controller
3. **日志统一**：异常日志可在全局处理器中统一记录，包含请求路径、用户 ID 等上下文信息

## 参考

- 参考实现：`macrozheng/mall/mall-common/src/main/java/com/macro/mall/common/exception/`
