# EP 类型模板：Bug 诊断 / 热修复 / 性能问题

> 适用场景：运行时错误、测试失败、性能瓶颈、API 异常、K8s 部署问题

---

## 必读文件（Cursor @mention 列表）

```
@docs/context/MASTER_INDEX.md
@docs/context/SESSION_HANDOFF.md
@docs/context/debug.md
@docs/hotfix/ISSUE-REGISTRY.md
```

---

## 关键约束摘要

1. **先诊断后修复**：遵循"Read Error → Analyze Root Cause → Fix Code → Retry"循环，最多 3 次
2. **禁止 print()**：调试日志必须用 `structlog`，不得留下 `print()` 语句
3. **禁止裸 except**：不得用 `except Exception: pass` 吞掉异常，必须 raise `DomainException`
4. **3-Strike 规则**：3 次自动修复失败后停止，向用户报告根因寻求指导
5. **回归测试**：修复后必须补充覆盖该 Bug 路径的测试用例，防止回归
6. **热修复记录**：修复完成后，在 `docs/hotfix/ISSUE-REGISTRY.md` 中追加记录

---

## EP 类型声明

**调试**

---

## 自定义要求

<!--
在此填写错误现象、错误日志、复现步骤等信息。
示例：
  错误现象：POST /api/v1/objects 返回 500，日志显示 "InvalidRequestError: A transaction is already begun"
  复现步骤：
    1. 调用 POST /api/v1/objects 创建对象
    2. 立即调用 PATCH /api/v1/objects/{id} 更新
  相关文件：backend/app/services/control/object_service.py:create_object()
  已尝试：检查了 session.begin() 调用顺序，未发现明显问题
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
