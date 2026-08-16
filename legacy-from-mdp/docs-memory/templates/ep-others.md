# EP 类型模板：通用兜底（跨层重构 / 安全加固 / 性能优化 / 测试补全 / 文档整理）

> 适用场景：无法归入其他 6 类模板的任务，包括但不限于：
> - 跨层模块重构 / 文件迁移 / 包拆分
> - 安全加固（Rate Limit、输入校验、敏感字段脱敏）
> - 性能优化（缓存、查询优化、批量处理）
> - 测试覆盖补全（新增单元测试 / 集成测试 / E2E 测试）
> - 纯文档整理（`e2e_traceability.md`、`frontend_page_map.md` 同步）
> - MMS 系统自身优化（harness、config、模板、CLI）

---

## 必读文件（Cursor @mention 列表）

```
@docs/context/MASTER_INDEX.md
@docs/context/SESSION_HANDOFF.md
@docs/architecture/e2e_traceability.md
```

---

## 关键约束摘要

1. **变更范围最小化**：`ep-others` 类任务往往跨越多层，务必在 Scope 表格中明确每个 Unit 的架构层，避免一个 Unit 同时修改 L2 + L5
2. **不引入新业务依赖**：重构/优化类 EP 不应新增功能，只改结构；若需新功能，拆分为独立 EP
3. **测试补全类**：新增测试文件须覆盖被测目标的核心路径，coverage 不得低于原有水平
4. **文档整理类**：更新 `e2e_traceability.md` / `frontend_page_map.md` 后，需运行 `mms validate` 确认 schema 合规
5. **安全加固类**：修改认证/权限相关逻辑必须同步更新 `docs/specs/error_registry.md` 中的错误码

---

## EP 类型声明

**通用 / 其他**

---

## 自定义要求

<!--
在此填写任务背景、目标、约束条件。
示例（重构）：
  目标：将 auth_service.py 拆分为 token_service.py + session_service.py
  约束：接口签名不变，现有测试全部通过，不新增业务功能

示例（测试补全）：
  目标：为 action_service 和 function_service 补充单元测试
  约束：coverage 提升至 85% 以上，mock 所有外部依赖

示例（安全加固）：
  目标：为所有 POST 接口添加请求频率限制（10 req/min/user）
  约束：不影响现有业务功能，Rate Limit 超限返回 E_RATE_LIMIT 错误码
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

## Scope

> ⚠️ **此节为必填项**，mms precheck 解析此表格以建立基线。节名必须为 `## Scope`。
> `ep-others` 类 EP 须在「操作描述」列中注明所属架构层（如 `[L4]`、`[L5]`、`[测试层]`）。

| Unit | 操作描述 | 涉及文件 |
|------|---------|---------|
| U1   | [L4] 示例：重构目标模块，拆分职责 | `backend/app/services/control/example_service.py` |
| U2   | [测试层] 示例：补充单元测试 | `backend/tests/unit/services/test_example_service.py` |
| U3   | [文档] 示例：同步更新架构追踪文档 | `docs/architecture/e2e_traceability.md` |

---

## Testing Plan

> ⚠️ **此节为必填项**，mms precheck 解析此列表。
> 填写本次 EP 新增或修改的测试文件路径，每行一个，格式：`` `路径` — 说明 ``

- `backend/tests/unit/services/test_example_service.py` — 验证重构后接口行为不变
- `backend/tests/integration/test_example_e2e.py` — 端到端回归测试（如适用）
