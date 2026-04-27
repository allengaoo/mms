---
id: AC-PY-06
layer: CC
tier: hot
type: arch_constraint
language: python
pack: python_fastapi
about_concepts: [logging, structlog, observability, structured-logging]
cites_files: []
contradicts: []
created_at: "2026-04-27"
---

# 结构化日志必须用 structlog，禁止裸 print() 和 logging.error()

## 约束（Constraint）

所有生产代码（非测试、非脚本）必须使用 `structlog` 进行结构化日志输出。

```python
# ❌ 禁止：裸 print
print(f"User {user_id} created")

# ❌ 禁止：标准库 logging 的格式化字符串
import logging
logging.error(f"Failed to process order {order_id}: {e}")

# ✅ 正确：structlog 结构化日志
import structlog
logger = structlog.get_logger(__name__)

logger.info("user_created", user_id=user_id, email=user.email)
logger.error("order_processing_failed", order_id=order_id, error=str(e), exc_info=True)
```

## 原因（Why）

1. **可检索性**：结构化日志（JSON 格式）可以被 ELK/Loki/DataDog 按字段过滤，`print` 输出只能全文搜索
2. **上下文追踪**：structlog 支持 `bind_contextvars(request_id=...)` 自动注入请求级别的追踪 ID
3. **性能**：structlog 的懒渲染（lazy rendering）避免了在 DEBUG 级别关闭时仍然进行字符串格式化

## 配置示例

```python
# app/core/logging.py
import structlog

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)
```

## 参考

- structlog 文档：https://www.structlog.org/en/stable/
- 参考实现：`tiangolo/full-stack-fastapi-template/backend/app/core/config.py`
