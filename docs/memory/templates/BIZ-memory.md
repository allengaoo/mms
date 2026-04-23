---
id: BIZ-XXX                        # 唯一 ID，格式 BIZ-NNN
layer: BIZ                         # 固定为 BIZ（业务逻辑维度）
module: ontology                   # 业务子模块（ontology/pipeline/governance/platform）
dimension: D0                      # D0 = 业务语义维度（跨 D1~D10）
type: business-flow                # business-flow | actor-model | constraint | edge-case
tier: hot                          # hot | warm | cold
tags: [object-type, crud, tenant]  # 业务相关标签
source_ep: EP-XXX
created_at: "YYYY-MM-DD"
last_accessed: "YYYY-MM-DD"
access_count: 0
related_memories: []               # 相关 MEM-L-xxx / AD-xxx 记忆 ID
version: 1
---

# BIZ-XXX · 业务名称（简洁说明 WHAT）

## 业务场景（Business Context）
<!-- 描述：这是哪个业务领域？哪类用户？解决什么业务问题？ -->

## 核心流程（Core Flow）
<!-- 端到端业务流程，包含关键步骤和系统交互：
1. 用户/Actor 执行 ...
2. 系统验证 ...
3. 触发事件 ...
4. 返回结果 ...
-->

## 参与者（Actors & Roles）
<!-- 参与本业务流程的角色和系统：
- **角色1**：描述职责
- **角色2**：描述职责
- **外部系统**：交互方式
-->

## 业务规则（Constraints & Rules）
<!-- 必须遵守的业务规则、验证逻辑、限制条件 -->
- 规则1：...
- 规则2：...

## 数据流（Data Flow）
<!-- 关键数据如何在系统中流动，涉及哪些核心实体 -->

## 边界情况（Edge Cases）
<!-- 容易出错或需要特殊处理的场景 -->
- 边界1：...

## 代码入口（Code Anchors）
<!-- 相关代码的关键入口点，方便 AI 快速定位 -->
- Service: `backend/app/services/control/XXX_service.py`
- API: `backend/app/api/v1/XXX.py`
- Frontend: `frontend/src/pages/XXX.tsx`
- Store: `frontend/src/stores/useXXXStore.ts`

## 相关记忆（Related Memories）
<!-- 关联的技术实现记忆 -->
- [MEM-L-XXX] ...
- [AD-XXX] ...
