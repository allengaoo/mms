# MDP 层边界契约（Layer Boundary Contracts）

> **用途**：
> 1. 生成 EP DAG 时，编排 Agent（qwen3-32b）依据本文件判断每个 Unit 属于哪一层、需要遵守什么规格
> 2. 小模型执行 Unit 时，作为"约束注入"的上下文（替代阅读完整架构文档）
> 3. arch_check.py 错误消息中引用本文件作为修复参考
>
> **维护**：新增/修改 Service 模板、Endpoint 模式时同步更新本文件。
> **更新**：EP-116 · 2026-04-16

---

## L5 — 接口层（API Endpoints）

**典型文件路径**：`backend/app/api/v1/endpoints/*.py`

**边界入口**：FastAPI Router + Pydantic Request/Response Schema

**必须出现**：
```python
# 1. 路由装饰器 + response_model（禁止省略）
@router.get("/path", response_model=BaseResponse[ListData[T]])

# 2. 权限守卫（在路由函数签名上方）
@require_permission("domain:resource:action")

# 3. SecurityContext 从依赖注入获取（禁止硬编码）
async def list_objects(
    ctx: SecurityContext = Depends(get_current_user),
    ...
)

# 4. 统一返回 ResponseHelper（禁止裸字典）
return ResponseHelper.ok(data=result, meta={"total": total})
```

**禁止出现**：
- 业务逻辑（SELECT/INSERT/UPDATE 查询）→ 下沉到 Service 层
- `return []` 裸列表 / `return {"key": "val"}` 裸字典（AC-4 红线）
- `import pymilvus` / `import aiokafka` / `import elasticsearch`（AC-1 红线）
- `session` 对象直接在 endpoint 中操作

**典型函数签名**：
```python
async def list_{resource}(
    ctx: SecurityContext = Depends(get_current_user),
    filter_params: {Resource}FilterParams = Depends(),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> BaseResponse[ListData[{Resource}Response]]:
```

---

## L4 — 应用服务层（Control Services）

**典型文件路径**：`backend/app/services/control/*_service.py`

**边界入口**：`async def method(ctx: SecurityContext, ...) -> DomainObject`

**必须出现**：
```python
# 1. 首参必须是 SecurityContext（AC-2 红线）
async def create_{resource}(ctx: SecurityContext, data: CreateRequest) -> DomainObject:

# 2. 所有 DB 查询必须有 tenant_id 过滤（AC-1 + RLS 规则）
stmt = select(Model).where(
    Model.tenant_id == ctx.tenant_id,
    Model.id == resource_id,
)

# 3. WRITE 方法必须调 AuditService.log（AC-3 红线）
await AuditService.log(ctx, action="create_{resource}", resource_id=obj.id)

# 4. 事务策略选 A 或 B，不混用（AC-11 红线）
# Strategy A（推荐写法）：
async with session.begin():
    session.add(obj)
    await AuditService.log(...)
# Strategy B（autobegin）：
await session.execute(stmt)
await session.commit()  # 显式 commit，禁止在 execute 后再 begin()
```

**禁止出现**：
- `import pymilvus` / `import aiokafka` / `import elasticsearch`（只走 infrastructure/ 适配器）
- `session.begin()` 在 `session.execute()` 之后（AC-11 红线）
- `print()` 语句（用 `structlog`）

**典型函数签名**：
```python
async def get_{resource}(ctx: SecurityContext, resource_id: str) -> {Resource}:
async def create_{resource}(ctx: SecurityContext, data: Create{Resource}Request) -> {Resource}:
async def update_{resource}(ctx: SecurityContext, resource_id: str, data: Update{Resource}Request) -> {Resource}:
async def delete_{resource}(ctx: SecurityContext, resource_id: str) -> None:
async def list_{resource}s(ctx: SecurityContext, filter: FilterParams) -> Tuple[List[{Resource}], int]:
```

---

## L2 — 基础设施层（Infrastructure Adapters）

**典型文件路径**：`backend/app/infrastructure/{db,cache,mq,lake,consensus}/*.py`

**边界**：端口接口实现，封装具体技术细节，对 Service 层暴露抽象接口

**必须出现**：
```python
# 1. 异常包装为 DomainException（禁止裸 Exception 泄漏到 Service 层）
try:
    await session.execute(stmt)
except SQLAlchemyError as e:
    raise DomainException(code="E_DB_001", detail=str(e)) from e

# 2. 重试包装（外部调用：DB/Kafka/Redis/S3）
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10))
async def _execute_with_retry(...):

# 3. 流式处理（读 S3/文件/DB Cursor）
async def read_records() -> AsyncIterator[dict]:
    async for row in cursor:  # yield，禁止 fetchall()
        yield row
```

**禁止出现**：
- 业务规则判断（"此字段不能为空"→ 属于 Service 层）
- 直接暴露 pymilvus/aiokafka 原生对象给 Service 层

---

## L3 — 领域层（Domain / Ontology Objects）

**典型文件路径**：`backend/app/domain/**/*.py`、`backend/app/services/control/ontology_service.py`

**边界**：纯业务逻辑，包含领域实体、值对象、领域事件

**必须出现**：
```python
# SQLModel 定义，JSON 字段用 sa_column=Column(JSON)
class ObjectTypeDef(SQLModel, table=True):
    __tablename__ = "meta_object_defs"  # 表名：snake_case 复数
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    tenant_id: str = Field(index=True)
    properties: dict = Field(default_factory=dict, sa_column=Column(JSON))
```

**禁止出现**：
- 直接调用 HTTP 客户端或消息队列
- `import aiokafka` / `import pymilvus`（通过 `services/dispatch` 发事件）

---

## 前端层（Frontend React Components）

**典型文件路径**：`frontend/src/pages/*/index.tsx`

**边界**：React 18 + TypeScript 组件，Ant Design 5 ProComponents

**必须出现**：
```typescript
// 1. 数据获取通过 services/ 封装（禁止直接 axios）
import { listObjects } from '@/services/ontology'

// 2. 权限检查通过 PermissionGate 组件
<PermissionGate permission="ont:object:view">
  <ObjectList />
</PermissionGate>

// 3. 类型严格（禁止 any，除非有 // eslint-disable 注释说明原因）
const columns: ProColumns<ObjectTypeRow>[] = [...]

// 4. 页面级 Store（Zustand）管理复杂状态
const { objects, fetchObjects } = useOntologyStore()
```

**禁止出现**：
- `axios.get(...)` 直接在组件中调用（通过 `src/services/*.ts` 封装）
- Amis JSON 配置（非 Chat2App 模块）
- 魔法字符串颜色值（通过 ConfigProvider 主题注入）

---

## DAG 层依赖规则（Unit 排序参考）

跨层变更时，Unit 执行顺序必须遵循以下依赖链：

```
数据模型（L3 SQLModel） → 服务方法（L4 Service） → API Endpoint（L5） → 前端页面
                                    ↓
                          测试文件（与业务文件同 Unit）
                                    ↓
                          文档更新（e2e_traceability / frontend_page_map）
```

**并行规则**：同一层的多个 Unit 可并行（例如：同时修改两个不相关的 Service 方法），不同层的 Unit 必须串行（下层完成后才能做上层）。

---

*EP-116 · 2026-04-16*
