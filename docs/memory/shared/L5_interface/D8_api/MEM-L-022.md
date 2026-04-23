---
id: MEM-L-022
layer: L5_interface
module: api
dimension: D8
type: lesson
tier: hot
description: "raise DomainException(code='E_MODULE_ID')；错误码必须在 docs/specs/error_registry.md 中预先注册"
tags: [error, domain-exception, error-registry, error-code, exception-handling, api]
source_ep: EP-110
created_at: "2026-04-12"
last_accessed: "2026-04-12"
access_count: 6
related_memories: [MEM-L-020, MEM-L-009]
also_in: [L1-D3]
generalized: true
related_to:
  - id: "MEM-L-020"
    reason: "DomainException 最终通过 Envelope 信封格式返回给客户端"
  - id: "AD-002"
    reason: "403 DomainException 通常是 tenant_id 不匹配或权限缺失触发的"
cites_files:
  - "backend/app/core/exceptions.py"
  - "backend/app/core/response.py"
impacts:
  - "MEM-L-020"
version: 1
---

# MEM-L-022 · `DomainException(code="E_MODULE_ID")` 必须映射 error_registry.md，禁止裸 raise

## WHERE（在哪个模块/场景中）

`backend/app/domain/` 下所有 Service 方法，以及 API 路由的异常处理。
`backend/app/core/exceptions.py`（DomainException 定义）。

## WHAT（发生了什么）

裸 raise（`raise ValueError("xxx")`）或非标准异常码导致：
1. 前端收到 HTTP 500（即使是业务逻辑错误，如重复创建），用户体验差
2. 监控告警无法按错误类型分类（所有业务错误都变成 500）
3. 国际化支持缺失（硬编码中文错误消息无法 i18n）
4. 错误无法被 `GlobalExceptionHandler` 正确转换为标准 Envelope 格式

## WHY（根本原因）

平台有统一的异常处理架构：
```
Service 抛出 DomainException(code="E_ONT_001")
         ↓
GlobalExceptionHandler.handle()
         ↓
查询 error_registry.md 获取 HTTP 状态码和消息模板
         ↓
返回 ApiResponse(code=4xx/5xx, message="...")
```

裸 raise 绕过了这个链路，导致 500 和无法追踪的错误。

## HOW（解决方案）

```python
# ✅ 正确：使用 DomainException + 标准错误码
from app.core.exceptions import DomainException

class ObjectTypeService:
    async def create(self, ctx: SecurityContext, body: ObjectTypeCreate):
        # 检查重复
        existing = await self.repo.find_by_name(ctx, body.name)
        if existing:
            raise DomainException(
                code="E_ONT_001",         # 必须在 error_registry.md 中注册
                detail={"name": body.name},  # 可选：用于消息模板插值
            )
        ...

# error_registry.md 中对应条目：
# | E_ONT_001 | 409 | 对象类型 '{name}' 已存在 | ObjectTypeDef 名称重复 |

# ❌ 错误：裸 raise，绕过标准异常处理
async def create(self, ctx, body):
    if existing:
        raise ValueError(f"对象类型 {body.name} 已存在")  # 🚨 500 + 无法分类

# ❌ 错误：HTTPException（只能在 Controller 层用，不能在 Service 层用）
async def create(self, ctx, body):
    if existing:
        raise HTTPException(status_code=409, detail="已存在")  # 🚨 Service 层不应依赖 HTTP 概念
```

**错误码命名规范**：
```
E_{MODULE}_{SEQ}
  MODULE: ONT(本体) | PIPE(数据管道) | GOV(治理) | SYS(系统) | AUTH(认证) | QUOTA(配额)
  SEQ:    3位数字，001 起

示例：
  E_ONT_001  对象类型重复
  E_ONT_002  属性类型不合法
  E_PIPE_001 Connector 连接失败
  E_AUTH_001 Token 过期
  E_QUOTA_001 配额超限
```

**新增错误码流程**：
1. 在 `docs/specs/error_registry.md` 添加条目（含 HTTP 状态码、消息模板）
2. 在代码中使用 `DomainException(code="E_XXX_NNN")`
3. `GlobalExceptionHandler` 自动转换，无需修改处理器

## WHEN（触发条件）

- Service 层需要返回业务错误（重复、不合法、权限不足等）
- Code Review 发现 `raise ValueError/KeyError/Exception` 在业务代码中
- 前端反馈"所有错误都是 500，无法区分"
