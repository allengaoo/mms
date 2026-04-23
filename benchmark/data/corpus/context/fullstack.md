# Fullstack Manifest

> 适用：跨越后端 + 前端 + 数据层的复合 EP
> 使用方式：本文件作为总索引，同时加载所涉及各域的 Manifest
> **维护者**：@gaobin · 最后更新：EP-102

---

## 红线约束（全栈串联时特有）

1. **影响范围必查**：全栈 EP 开始前**必须**读 `e2e_traceability.md`，识别所有受影响层（API / Service / Model / Worker / Frontend / Store）。
2. **文档同步双更新**：新增 API + 新增页面时，`e2e_traceability.md` 和 `frontend_page_map.md` 都需要更新。
3. **后端先行**：全栈 EP 执行顺序：Model → Service → API → Frontend；禁止在后端未完成前 mock 前端数据（避免接口漂移）。
4. **响应格式对齐**：后端 `ResponseSchema` 的 `data` 结构必须与前端 `service.ts` 的类型定义严格对齐；字段名不一致是全栈 bug 最常见来源。
5. **测试分层覆盖**：后端写 pytest 单元测试 + 前端写 Vitest + MSW mock；全链路功能测试通过浏览器验收。

---

## 全栈 EP 执行顺序模板

```
Phase A: 后端
  Unit A1: Model 定义（SQLModel + Alembic migration）
  Unit A2: Service 层（Control + Query）
  Unit A3: API endpoint（Controller + ResponseModel）

Phase B: 前端
  Unit B1: API service 封装（src/services/xxx.ts + 类型定义）
  Unit B2: Zustand Store（如需全局状态）
  Unit B3: 页面 / 组件（ProTable + ModalForm）

Phase C: 文档同步
  Unit C1: e2e_traceability.md + frontend_page_map.md
```

---

## 必读文件

| 文件 | 说明 | 优先级 |
|:---|:---|:---|
| `docs/architecture/e2e_traceability.md` | 端到端影响范围映射 | 必须 |
| `docs/architecture/frontend_page_map.md` | 前端页面→API 对应关系 | 必须 |
| `docs/context/backend-api.md` | 后端规范摘要 | 必须 |
| `docs/context/frontend.md` | 前端规范摘要 | 必须 |
| `docs/context/data-pipeline.md` | 若涉及数据管道 | 按需 |
| `docs/context/ontology.md` | 若涉及本体 | 按需 |

---

## 关键决策点

| 遇到 X | 选 A 而非 B | 理由 |
|:---|:---|:---|
| 后端 API 未完成时前端需要数据 | MSW mock handler | 避免接口漂移；完成后删除 mock |
| 全栈功能验收 | 浏览器关键路径操作 | 比单元测试更能发现集成问题 |
| 后端字段名 vs 前端显示名 | 后端 snake_case，前端 camelCase（自动转换） | axios 配置了 camelizeKeys，保持一致 |
| 新增 Zustand Store | 同步更新 `frontend_page_map.md` Store 总览 | 强制要求，见 `global-constraints.mdc` §16 |
