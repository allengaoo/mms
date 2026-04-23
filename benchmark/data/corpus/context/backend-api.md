# Backend API Manifest

> 适用：新增 Endpoint / Service / Model / Repository EP
> 补充加载：`@docs/architecture/e2e_traceability.md`（影响范围）
> **维护者**：@gaobin · 最后更新：EP-102

---

## 红线约束（此域最易出错）

1. **事务策略二选一**：Strategy A（`session.begin()` 在任何 `execute()` 前）或 Strategy B（autobegin + 末尾 `commit()`）。**禁止混用**，否则抛 `InvalidRequestError: A transaction is already begun`。
2. **Controller 零业务逻辑**：API endpoint 只做 DTO 解析 + Service 调用，业务逻辑必须下沉到 Service 层。
3. **返回标准信封**：`{"code": 200, "data": ..., "meta": ...}`，禁止返回裸列表或裸对象。
4. **N+1 防护**：List API 必须用 `selectinload()`，禁止循环查询。
5. **读操作必须缓存**：元数据读操作必须用 `@cached` 装饰器（`infrastructure/cache/redis_decorator.py`）。

---

## 核心代码骨架

### Service 层标准结构
```python
class MyControlService:
    @staticmethod
    async def create_item(ctx: SecurityContext, dto: CreateItemDTO) -> Item:
        log.info("create_item_start", user_id=ctx.user_id, tenant=ctx.tenant_id)
        async with async_session_factory() as session:
            async with session.begin():               # Strategy A
                item = Item(**dto.model_dump())
                item.tenant_id = ctx.tenant_id        # RLS
                session.add(item)
                await session.flush()
                await audit_service.log(ctx, "CREATE", item.id)
        return item
```

### API Controller 标准结构
```python
@router.post("/items", response_model=ResponseSchema[ItemDTO])
async def create_item(
    payload: ItemCreateDTO,
    ctx: SecurityContext = Depends(get_current_user),
):
    data = await MyControlService.create_item(ctx, payload)
    return ResponseSchema(data=data)
```

---

## 必读文件

| 文件 | 说明 | 优先级 |
|:---|:---|:---|
| `.cursor/rules/backend-gen.mdc` | 完整代码生成规范 | 必须 |
| `.cursor/rules/security-check.mdc` | 安全审查清单 | 必须 |
| `docs/architecture/e2e_traceability.md` | 影响范围检查 | 新增 API 时必须 |
| `docs/models/*.json` | 数据模型定义 | 涉及模型变更时 |
| `docs/specs/error_registry.md` | 错误码注册表 | 新增异常时 |

---

## 关键决策点

| 遇到 X | 选 A 而非 B | 理由 |
|:---|:---|:---|
| 先 SELECT 验证再 INSERT | Strategy A（begin-first） | 保证 SELECT 和 INSERT 在同一事务，防止幻读 |
| 简单单次写入（如更新 last_login） | Strategy B（autobegin + commit） | 代码更简洁，不需要嵌套 |
| 响应需要排除敏感字段 | `response_model_exclude` | 比手动 pop 更安全，不会遗漏 |
| 高频读操作（元数据） | `@cached` 装饰器 | Redis 缓存，减少 MySQL 压力 |

---

## Migration 触发规则（强制）

> 本节是 EP Plan **Runtime 声明节**中「DB 迁移」行的判断依据。

**触发条件**（满足任意一条即需执行迁移）：
- 新增了 SQLModel 类（新表）
- 修改了现有 SQLModel 字段（加字段、改类型、加索引、改约束）
- 手动编写了迁移脚本（`backend/alembic/versions/` 新增文件）

**执行步骤**：
1. `PYTHONPATH=. python -m alembic revision --autogenerate -m "ep{NNN}_{描述}"`
2. 人工审查生成文件（重点：DROP 是否有存在性判断，见 `backend-gen.mdc` §5.1）
3. 在 **mdp** 主库执行：`alembic upgrade head`
4. 在 **mdp_test** 测试库同步执行（防止集成测试失败）
5. 更新 `docs/context/SESSION_HANDOFF.md` 的 Alembic Head 列

**完整步骤参考**：`docs/architecture/runtime_migration_and_deploy_steps.md` §1

**EP Plan Runtime 声明模板**（在 EP plan 文件中填写）：
```
| 🗄️ DB 迁移（Alembic） | 是 | 新增 xxx 表 / 修改 yyy 字段 |
```
