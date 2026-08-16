# EP 类型模板：前端页面 / 组件

> 适用场景：新增 React 页面、ProTable 列表、表单、Zustand Store、路由、权限控制

---

## 必读文件（Cursor @mention 列表）

```
@docs/context/MASTER_INDEX.md
@docs/context/SESSION_HANDOFF.md
@docs/context/frontend.md
@docs/architecture/frontend_page_map.md
@docs/ui/style_guide.md
```

---

## 关键约束摘要

1. **UI 库**：管理页面必须使用 Ant Design 5 ProComponents，禁止在非 Chat2App 模块使用 Amis JSON
2. **颜色规范**：顶部导航使用 Deep Blue（`#2B55D5`），侧边栏使用 Light Gray（`#F7F8FA`）
3. **权限控制**：页面入口使用 `PermissionGate`，敏感操作用 `require_permission`
4. **HTTP 调用**：所有 API 调用必须封装在 `src/services/*.ts`，禁止在组件中直接调用 Axios
5. **状态管理**：跨组件状态使用 Zustand Store，本地状态用 `useState`
6. **类型安全**：禁止使用 `any`，所有 Props 和 API 响应必须有 TypeScript 类型定义

---

## EP 类型声明

**前端**

---

## 自定义要求

<!--
在此填写您的特殊需求、约束或背景信息。
示例：
  - 此页面需要支持虚拟化列表（数据量 >10000 行）
  - 需要集成现有的 ObjectTypeStore
  - 页面需要 WebSocket 实时更新
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
