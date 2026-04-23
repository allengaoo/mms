# Ontology Manifest

> 适用：ObjectType / LinkType / Action / Function / 本体画布 EP
> 补充加载：`@.cursor/skills/ontology/SKILL.md`
> **维护者**：@gaobin · 最后更新：EP-102

---

## 红线约束（本体层特有）

1. **控制面 / 数据面分离**：`services/control`（MySQL）管理本体定义（ObjectTypeDef, LinkTypeDef）；写 Milvus/ES 必须通过 `services/dispatch` 发 Kafka 事件，**禁止在 control 层直接调向量库**。
2. **Simulation Overlay**：读取 Object 实例数据的 Service 方法必须接受 `scenario_id` 参数；当 `scenario_id` 非 None 时，优先读 `sys_object_edits`（Redis/MySQL overlay），再 fallback 到 live 数据。
3. **Action 回写幂等**：Action 执行必须生成幂等 `execution_id`；重试时检查 `action_executions` 表，存在则直接返回历史结果。
4. **Function 缓存隔离**：计算属性（Function）缓存 key 必须含 `scenario_id`，防止 live 数据与模拟数据污染。
5. **全局修改须走 CR**：修改全域资产库（Global Registry）中的对象/链接定义，必须触发变更请求（Change Request）审批流。

---

## 核心代码骨架

### ObjectTypeDef Service 标准读取（含 Simulation）
```python
async def get_object_data(
    ctx: SecurityContext,
    object_id: UUID,
    scenario_id: Optional[str] = None,  # None = live
) -> ObjectData:
    if scenario_id:
        overlay = await redis.get(f"scenario:{scenario_id}:obj:{object_id}")
        if overlay:
            return ObjectData.model_validate_json(overlay)
    # fallback to live
    return await object_repo.get(ctx, object_id)
```

### Action 写回骨架
```python
async def execute_action(ctx: SecurityContext, dto: ActionExecuteDTO) -> ActionResult:
    existing = await action_exec_repo.get_by_idempotency(dto.execution_id)
    if existing:
        return existing.result
    result = await action_adapter.run(ctx, dto)
    await action_exec_repo.save(ctx, dto.execution_id, result)
    await kafka.emit("ACTION_EXECUTED", {"id": str(dto.execution_id)})
    return result
```

---

## 必读文件

| 文件 | 说明 | 优先级 |
|:---|:---|:---|
| `.cursor/skills/ontology/SKILL.md` | 本体层核心概念（Object/Link/Action/Function） | 必须 |
| `docs/specs/ontology_spec.md` | 本体业务规约 | 必须 |
| `docs/models/object_type.json` | ObjectTypeDef 数据模型 | 涉及模型时 |
| `docs/models/link_type.json` | LinkTypeDef 数据模型 | 涉及链接时 |
| `docs/architecture/e2e_traceability.md` | 本体→数据流影响范围 | 必须 |

---

## 关键决策点

| 遇到 X | 选 A 而非 B | 理由 |
|:---|:---|:---|
| 写向量索引 | Kafka 事件 → Index Worker | 保持控制面/数据面分离 |
| 读 Object 实例（有 scenario） | Overlay 优先 + fallback | Simulation 核心机制 |
| Action 重试 | 先查幂等表 | 防止重复执行副作用 |
| 全局对象定义变更 | 触发 CR 审批流 | 治理规范，防止意外破坏依赖 |
