# 模版：ADAPTER 层 · REST API Endpoint（小模型优化版）
# 适用：新增 API 路由 / Response Model 定义 / 错误码注册
# Token 预算：≤3K

---

## [TASK] 任务描述
**目标**：{HTTP方法 + 路径 + 一句话说明用途}
**层级坐标**：Layer 5 (interface/api) × Dimension 8 (API 规范)
**涉及文件**：
- `backend/app/api/v1/endpoints/{domain}.py`
- `backend/app/api/schemas/{domain}.py`
- `docs/specs/error_registry.md`（如新增错误码）

---

## [MEMORY] 本次必须遵守的记忆（4条核心）

**响应格式（MEM-L-020）**：
- ✅ 统一信封：`{"code": 200, "data": ..., "meta": ...}`
- ✅ 必须定义 `response_model=ApiResponse[DTO]`
- ❌ 禁止：直接返回裸列表或裸字典
- 空结果用 `ApiResponse(code=200, data=[], meta=PageMeta(total=0, ...))`，不用 `None`

**分页策略（MEM-L-021）**：
- 预期记录 < 10万：可用 offset 分页
- 预期记录 > 10万 或无限增长（审计日志、对象数据）：必须用 cursor-based 分页
- cursor = base64({id, created_at})，通过 WHERE 条件而非 OFFSET 实现

**错误处理（MEM-L-022）**：
- ✅ Service 层只抛 `DomainException(code="E_MODULE_NNN")`，错误码必须在 `error_registry.md` 注册
- ❌ 禁止：`raise ValueError("...")` 或裸 `raise HTTPException(...)` 在 Service 层
- 错误码命名：`E_{ONT|PIPE|GOV|SYS|AUTH|QUOTA}_{001-999}`

**权限检查（全局红线）**：
- ✅ 每个 Endpoint 必须有 `@require_permission("domain:resource:action")`
- ✅ 权限格式：短前缀，如 `ont:object:view`（非 `ontology:object:view`）

---

## [STATE] 系统状态
- EP: {当前EP编号}
- 所需权限：`{domain}:{resource}:{action}`
- API 前缀：`/api/v1/{domain}/`

---

## [CONSTRAINTS] 本层必守红线（4条）
- ✅ URL kebab-case（如 `/sync-jobs/{id}/pause`）
- ✅ JSON 字段 snake_case（如 `job_id`，非 `jobId`）
- ✅ 错误码必须注册到 `docs/specs/error_registry.md`
- ❌ 禁止：Controller 层调用多个 Service（业务编排下沉到 Service）

---

## [EXAMPLE] 参考模式（来自 EP-103）
```python
# ✅ 标准 Endpoint 写法
@router.post(
    "/{job_id}/pause",
    response_model=ResponseSchema[SyncJobResponse],
    summary="暂停同步任务",
)
@require_permission("datalink:syncjob:edit")
async def pause_sync_job(
    job_id: UUID,
    ctx: SecurityContext = Depends(get_security_context),
) -> ResponseSchema[SyncJobResponse]:
    job = await datalink_service.pause_sync_job(ctx, job_id)
    return ResponseSchema(code=200, data=SyncJobResponse.model_validate(job))
```

---

## [OUTPUT] 输出格式
1. `api/v1/endpoints/{domain}.py` — 完整 Endpoint 函数
2. `api/schemas/{domain}.py` — Request/Response Pydantic 模型
3. 测试 `tests/unit/test_{domain}_endpoint.py` — mock Service 层
4. 新错误码（如有）：`E_{MODULE}_{NNN}: 描述`
