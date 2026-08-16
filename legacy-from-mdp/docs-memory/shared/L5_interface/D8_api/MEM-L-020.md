---
id: MEM-L-020
layer: L5_interface
module: api
dimension: D8
type: lesson
tier: hot
description: "API 返回必须是 {code, data, meta} 信封格式；return [] 或 return {} 裸响应违反 AC-4 红线"
tags: [api, envelope, response, code, data, meta, raw-list]
source_ep: EP-110
created_at: "2026-04-12"
last_accessed: "2026-04-12"
access_count: 8
related_memories: [MEM-L-022, AD-008]
also_in: []
generalized: true
version: 1
related_to:
  - id: "MEM-L-022"
    reason: "错误响应也必须遵守信封格式，DomainException 输出到信封的 error 字段"
  - id: "AD-002"
    reason: "信封格式中需正确传递 tenant 上下文，不能泄露其他 tenant 数据"
cites_files:
  - "backend/app/core/response.py"
  - "backend/app/api/v1/endpoints/ontology.py"
  - "backend/app/api/v1/endpoints/auth.py"
impacts:
  - "MEM-L-023"
  - "BIZ-001"
---

# MEM-L-020 · API 响应必须用 Envelope `{code, data, meta}`，禁止裸列表

## WHERE（在哪个模块/场景中）

所有 `backend/app/api/v1/` 下的路由处理函数（Controller 层）。
包括列表查询、单体查询、写操作、批量操作的所有响应。

## WHAT（发生了什么）

返回裸列表（`return [item1, item2, ...]`）导致：
1. 前端无法判断请求是否成功（HTTP 200 但业务失败无法区分）
2. 分页信息无处放置（`total`、`page`、`has_more` 丢失）
3. API 版本升级时无法在不破坏前端的情况下添加元数据
4. 监控告警系统无法按业务错误码过滤（只有 HTTP 状态码）

## WHY（根本原因）

平台采用统一 API Envelope 规范，前端 Axios 拦截器和监控系统均基于
`{ code, data, meta }` 结构解析响应。裸列表会导致拦截器抛出解析异常。

## HOW（解决方案）

```python
# ✅ 正确：使用 Envelope 格式
from app.api.schemas.response import ApiResponse, PageMeta

@router.get("/object-types", response_model=ApiResponse[List[ObjectTypeOut]])
async def list_object_types(
    ctx: SecurityContext = Depends(get_ctx),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    items, total = await object_type_service.list(ctx, page, page_size)
    return ApiResponse(
        code=200,
        data=items,
        meta=PageMeta(total=total, page=page, page_size=page_size),
    )

# ✅ 单体查询
@router.get("/{object_type_id}", response_model=ApiResponse[ObjectTypeOut])
async def get_object_type(object_type_id: str, ctx=Depends(get_ctx)):
    item = await object_type_service.get(ctx, object_type_id)
    return ApiResponse(code=200, data=item)

# ✅ 写操作（创建/更新）
@router.post("/", response_model=ApiResponse[ObjectTypeOut], status_code=201)
async def create_object_type(body: ObjectTypeCreate, ctx=Depends(get_ctx)):
    item = await object_type_service.create(ctx, body)
    return ApiResponse(code=201, data=item)

# ❌ 错误：裸列表
@router.get("/object-types")
async def list_object_types(ctx=Depends(get_ctx)):
    return await object_type_service.list(ctx)  # 🚨 裸列表
```

**ApiResponse 结构定义**（`app/api/schemas/response.py`）：
```python
class ApiResponse(BaseModel, Generic[T]):
    code: int = 200
    data: T
    meta: Optional[PageMeta] = None
    message: Optional[str] = None
```

**特殊情况**：
- 异步任务（重建索引等）：返回 `ApiResponse(code=202, data={"task_id": "..."})`
- 空结果：返回 `ApiResponse(code=200, data=[], meta=PageMeta(total=0, ...))`
- 禁止用 `None` 作为 `data`，改用空列表或空 dict

## WHEN（触发条件）

- 新增任何 API 路由
- Code Review 检查 Response Model 合规性
- 前端报 "Cannot read properties of undefined" 时（通常是 data 为 None）
