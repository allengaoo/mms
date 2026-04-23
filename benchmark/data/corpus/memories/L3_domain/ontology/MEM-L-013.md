---
id: MEM-L-013
layer: L3_domain
module: ontology
dimension: ontology
type: lesson
tier: hot
description: "Action 回写结果写入 sys_object_edits overlay 表（按 scenario_id 隔离）；禁止直接修改 sys_objects 原始数据"
tags: [action, writeback, sys_object_edits, overlay, scenario, ontology]
source_ep: EP-109
created_at: "2026-04-12"
last_accessed: "2026-04-12"
access_count: 6
related_memories: [MEM-L-012, AD-005]
also_in: [L4-D2]
generalized: false
related_to:
  - id: "MEM-L-012"
    reason: "回写时通过 ObjectTypeDef 的 primary_key 定位目标对象实例"
  - id: "AD-003"
    reason: "Action 回写是控制面→数据面的边界操作（live 路径）"
  - id: "AD-005"
    reason: "回写操作是写操作，必须遵守事务策略 A 或 B"
cites_files:
  - "backend/app/services/control/ontology_service.py"
  - "backend/app/models/ontology.py"
impacts:
  - "BIZ-001"
version: 1
---

# MEM-L-013 · Action 回写使用 sys_object_edits overlay 机制，不直接修改原始数据

## WHERE（在哪个模块/场景中）

`backend/app/domain/ontology/services/action_service.py`
`ActionDef` 的 `execute()` 方法，以及所有对对象属性的写回操作。

## WHAT（发生了什么）

如果 Action 直接修改对象原始数据表（如 `UPDATE company SET revenue = ?`），会导致：
1. **场景隔离破坏**：仿真场景（Scenario）中的修改污染生产数据
2. **审计链断裂**：无法追溯"谁在什么场景下做了什么修改"
3. **回滚困难**：场景关闭后无法恢复到原始状态

## WHY（根本原因）

平台采用"全局资产 + 场景化应用"双层设计。Action 的回写必须经过
**Overlay 层**（`sys_object_edits` 表），而不是直接操作原始数据源。

Overlay 读取优先级：
```
有 scenario_id → 读 sys_object_edits（Redis 优先，MySQL 兜底）→ 覆盖原始字段
无 scenario_id（live 模式）→ 直接操作原始数据
```

## HOW（解决方案）

```python
# ✅ 正确：通过 ActionService 调用，框架自动路由到 Overlay 层
class MyAction(ActionDef):
    async def execute(
        self,
        ctx: SecurityContext,
        object_id: str,
        payload: dict,
        scenario_id: Optional[str] = None,  # 必须接收此参数
    ) -> ActionResult:
        # 不要直接 UPDATE，调用 overlay writer
        await self.object_edit_service.apply_edit(
            ctx=ctx,
            object_id=object_id,
            field_updates=payload,
            scenario_id=scenario_id,  # None = live 模式，直接写原始数据
            source="action",
            action_def_id=self.id,
        )
        return ActionResult(status="ok")

# ❌ 错误：直接操作原始数据
async def execute(self, ctx, object_id, payload, ...):
    await session.execute(
        update(CompanyTable)
        .where(CompanyTable.id == object_id)
        .values(**payload)  # 🚨 绕过 Overlay，破坏场景隔离
    )
```

**Overlay 写入规则**：
- `scenario_id` 非 None → 写入 `sys_object_edits`（Redis + MySQL 双写）
- `scenario_id` 为 None（live）→ 直接写原始表，同时写审计日志

## WHEN（触发条件）

- 实现新的 `ActionDef` 子类
- 对对象属性做批量更新（如数据清洗 Action）
- 在仿真场景中测试回写逻辑
