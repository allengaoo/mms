# 模版：DOMAIN 层 · 本体（Ontology）操作（小模型优化版）
# 适用：ObjectType / LinkType / Action / Function / Scenario 相关修改
# Token 预算：≤4K

---

## [TASK] 任务描述
**目标**：{本体操作说明（一句话）}
**层级坐标**：Layer 3 (domain/ontology) × OntoForge 专属领域
**涉及文件**：
- `backend/app/services/control/ontology_srv.py`
- `backend/app/models/ontology.py`（或相关模型）
- `frontend/src/pages/ontology/`（如有前端变更）

---

## [MEMORY] 本次必须遵守的记忆（2条核心）

**本体 V3 架构约束**：
- ObjectTypeDef → ObjectTypeVer（版本化）→ PropertyDef（属性定义）
- 修改 ObjectTypeDef 必须创建新 ObjectTypeVer（不可原地修改已发布版本）
- Scenario Overlay 读取优先级：先查 `sys_object_edits`（场景覆盖层），再查 Base

**SecurityContext + scenario_id**：
- 所有本体数据读取方法必须接受 `scenario_id: Optional[str] = None`
- 当 `scenario_id` 不为 None 时，优先从覆盖层读取

---

## [STATE] 系统状态
- EP: {当前EP编号} | 后端镜像: {version}
- 涉及 Alembic 迁移：是 / 否
- 是否涉及 Kafka 事件（本体变更通知）：是 / 否

---

## [CONSTRAINTS] 本层必守红线（5条）
- ✅ Service 首参：`ctx: SecurityContext`
- ✅ 读写隔离：读 → `services/query/`，写 → `services/control/`
- ✅ 本体变更必须通过 `services/dispatch/` 发 Kafka 事件（触发索引更新）
- ✅ 支持 `scenario_id` 参数（仿真引擎兼容性）
- ❌ 禁止：直接在本体写操作中调用 Milvus/ES

---

## [EXAMPLE] 参考模式（来自 EP-083）
```python
async def create_object_type(
    ctx: SecurityContext,
    dto: ObjectTypeCreateDTO,
    scenario_id: Optional[str] = None,
) -> ObjectTypeDef:
    async with async_session_factory() as session:
        async with session.begin():
            obj_type = ObjectTypeDef(
                tenant_id=ctx.tenant_id,    # RLS
                **dto.model_dump(),
            )
            session.add(obj_type)
            await session.flush()
            await audit_service.log(ctx, "CREATE_OBJECT_TYPE", str(obj_type.id))
            # 通知索引 Worker
            await dispatch_service.emit("ONTOLOGY_CHANGED", {"id": str(obj_type.id)})
    return obj_type
```

---

## [OUTPUT] 输出格式
1. `services/control/ontology_srv.py` 中的完整函数
2. `api/v1/endpoints/ontology.py` — Endpoint（含权限）
3. `api/schemas/ontology.py` — DTO 定义
4. 测试（单元 + 集成，含 scenario_id 场景）
