# EP 类型模板：本体层操作

> 适用场景：ObjectTypeDef / LinkTypeDef / ActionDef / FunctionDef / OntologyScenario / SharedProperty

---

## 必读文件（Cursor @mention 列表）

```
@docs/context/MASTER_INDEX.md
@docs/context/SESSION_HANDOFF.md
@docs/context/ontology.md
@docs/architecture/e2e_traceability.md
@docs/models/ontology.json
```

---

## 关键约束摘要

1. **双层架构**：全局资产库（Global Registry）是 Source of Truth，场景（Scenario）提供别名和覆盖
2. **软删除**：全域资产删除必须走回收站机制（`is_deleted=True`），不允许物理删除
3. **影响分析**：修改全局对象前，必须分析关联的 Scenario、SyncJob、Action 的影响范围
4. **版本管理**：ObjectTypeDef 修改需创建新版本记录（`ObjectTypeVer`），保持历史可追溯
5. **Scenario 隔离**：读取 Object Data 时，有 `scenario_id` 时必须优先查 `sys_object_edits`
6. **属性安全传播**：`sensitive` 属性在 Response 中必须排除（`ResponsePruner` / `response_model_exclude`）

---

## EP 类型声明

**本体**

---

## 自定义要求

<!--
在此填写您的特殊需求、约束或背景信息。
示例：
  - 此次修改涉及已有对象类型的属性新增（需评估向下兼容性）
  - 新建的 ActionDef 需要支持审批流（需集成 CR 机制）
  - 需要同时更新 Milvus 向量索引
-->



---

## Surprises & Discoveries
<!-- 实施过程中的意外发现（完成后填写）
格式：
- 现象：...
  证据：...（命令输出 / 错误信息片段）
-->

---

## Decision Log
<!-- 每个关键决策（完成后填写）
格式：
- Decision: [做了什么决定]
  Rationale: [为什么；有哪些备选方案被排除]
  Date: YYYY-MM-DD
-->

---

## Outcomes & Retrospective
<!-- EP 完成后填写
- 达成了什么（与 Purpose 对照）
- 偏差（未完成的 Unit 或范围变更）
- 给下一个 Agent 的教训
-->

---

## DAG Sketch（跨层变更时填写，单层可省略）
<!-- 描述 Unit 间依赖关系，供小模型执行时参考执行顺序
示例：
U1(model) → U2(service) → U3(endpoint) → U4(frontend)
             ↘ U5(test, 与 U2 同时)
注：同层 Unit 可并行；跨层 Unit 必须串行（见 layer_contracts.md §DAG 层依赖规则）
-->

---

## Scope

> ⚠️ **此节为必填项**，mms precheck 解析此表格以建立基线。节名必须为 `## Scope`。

| Unit | 操作描述 | 涉及文件 |
|------|---------|---------|
| U1   | （填写第一个原子操作） | `路径/文件.py` |
| U2   | （填写第二个原子操作） | `路径/文件.py` |

---

## Testing Plan

> ⚠️ **此节为必填项**，mms precheck 解析此列表以建立测试基线。节名必须为 `## Testing Plan`。

- `tests/unit/.../test_xxx.py` — 说明验证内容
