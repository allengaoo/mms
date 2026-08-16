# EP 类型模板：后端 API / Service

> 适用场景：新增 REST Endpoint、Service 方法、Repository、Model、Alembic 迁移

---

## 必读文件（Cursor @mention 列表）

```
@docs/context/MASTER_INDEX.md
@docs/context/SESSION_HANDOFF.md
@docs/context/backend-api.md
@docs/architecture/e2e_traceability.md
```

---

## 关键约束摘要

1. **SecurityContext 首参**：所有 Service 公开方法首参必须是 `ctx: SecurityContext`
2. **RLS 隔离**：所有 DB 查询必须 `WHERE tenant_id = ctx.tenant_id`
3. **AuditService**：每个 WRITE 方法必须调用 `AuditService.log(ctx, ...)`
4. **API 信封格式**：返回 `{"code": 200, "data": ..., "meta": ...}`，禁止裸列表
5. **事务策略**：选且仅选一种（Strategy A: begin-first / Strategy B: autobegin + explicit commit）
6. **缓存**：读密集操作必须使用 `@cached` 装饰器

---

## EP 类型声明

**后端 API**

---

## 自定义要求

<!-- 
在此填写您的特殊需求、约束或背景信息。
示例：
  - 本接口需要支持分页（page / page_size 参数）
  - 不允许修改现有的 ObjectTypeDef 模型字段
  - 需要同时发送 Kafka 事件通知下游
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

> ⚠️ **此节为必填项**，mms precheck 解析此表格以建立基线。
> 节名必须为 `## Scope`，格式如下：

| Unit | 操作描述 | 涉及文件 |
|------|---------|---------|
| U1   | 新增 SQLModel 数据模型 | `backend/app/models/<name>.py` |
| U2   | 实现 Service 层逻辑 | `backend/app/services/control/<name>_service.py` |
| U3   | 实现 API Endpoint | `backend/app/api/v1/endpoints/<name>.py` |
| U4   | Alembic 迁移 | `backend/alembic/versions/<hash>_<desc>.py` |
| U5   | 单元测试 | `backend/tests/unit/services/test_<name>_service.py` |

---

## Testing Plan

> ⚠️ **此节为必填项**，mms precheck 解析此列表以建立测试基线。
> 节名必须为 `## Testing Plan`，格式如下：

- `backend/tests/unit/services/control/test_<name>_service.py` — Service 层单元测试（RLS + AuditService + 事务策略）
- `backend/tests/unit/api/test_<name>_endpoint.py` — Endpoint 单元测试（请求/响应格式 + 权限拦截）
