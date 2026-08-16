---
id: MEM-L-014
layer: L3_domain
module: ontology
dimension: ontology
type: decision
tier: hot
description: "修改 SharedProperty 前必须查询所有引用方（ontology 和数据管道），级联影响范围广，必须先做影响分析"
tags: [shared_property, impact_analysis, cascade, change_request, ontology, governance]
source_ep: EP-109
created_at: "2026-04-12"
last_accessed: "2026-04-12"
access_count: 3
related_memories: [MEM-L-012, AD-002]
also_in: [CC-decisions]
generalized: true
version: 1
---

# MEM-L-014 · SharedProperty 变更级联影响所有引用方，必须先做影响分析再修改

## WHERE（在哪个模块/场景中）

`backend/app/domain/ontology/services/shared_property_service.py`
全域资产库中对 `SharedPropertyDef` 的修改操作（类型变更、删除、重命名）。

## WHAT（发生了什么）

直接修改 `SharedPropertyDef`（如将 `data_type` 从 `string` 改为 `number`）时：
1. 所有引用该属性的 `ObjectTypeDef` 的数据类型验证规则立即生效
2. 已有的对象数据可能因类型不匹配导致读取失败（`cast` 异常）
3. 前端 ProTable 组件的列渲染器无法处理类型变化（字符串→数字渲染不同）

## WHY（根本原因）

`SharedPropertyDef` 是跨对象类型共享的属性模板，修改一处即影响所有引用方。
平台设计文档（`docs/concepts/ontology.md`）明确要求：

> "全域资产库的修改必须触发影响分析，高风险修改必须走 CR（变更请求）审批流。"

但代码层面早期未强制执行此约束，导致直接修改可能绕过审批。

## HOW（解决方案）

```python
# ✅ 正确：修改前调用影响分析，高风险则创建 CR
class SharedPropertyService:
    async def update_property(
        self,
        ctx: SecurityContext,
        property_id: str,
        updates: SharedPropertyUpdate,
    ) -> Union[SharedPropertyDef, ChangeRequest]:

        # 1. 影响分析：找出所有引用此属性的 ObjectTypeDef
        impact = await self._analyze_impact(ctx, property_id, updates)

        # 2. 高风险变更（类型变更、删除）→ 创建 CR，走审批流
        if impact.risk_level == RiskLevel.HIGH:
            return await self.cr_service.create(
                ctx=ctx,
                change_type="shared_property_update",
                target_id=property_id,
                payload=updates.dict(),
                impact_summary=impact.summary,
            )

        # 3. 低风险变更（仅改 display_name）→ 直接执行
        return await self._apply_update(ctx, property_id, updates)

# ❌ 错误：直接 UPDATE，绕过影响分析
async def update_property(self, ctx, property_id, updates):
    await session.execute(
        update(SharedPropertyDef).where(...).values(**updates.dict())
    )
```

**影响分析维度**：
- 引用此属性的 ObjectTypeDef 数量
- 已有数据量（影响数据迁移成本）
- 是否涉及 `data_type` 变更（高风险）
- 是否有正在运行的 SyncJob 依赖此属性（高风险）

## WHEN（触发条件）

- 在全域资产库中修改任何 SharedPropertyDef
- 删除 SharedPropertyDef（最高风险，必须 CR）
- 修改 SharedPropertyDef 的 `required` 约束
