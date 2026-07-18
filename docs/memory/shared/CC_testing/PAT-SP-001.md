---
id: PAT-SP-001
layer: CC_testing
dimension: testing
type: pattern
object_type: Pattern
tier: hot
tags: [superpowers, tdd, red-green-refactor, backend, frontend, testing]
source_ep: EP-000
created_at: "2026-07-19"
version: 1
about_concepts: [tdd, failing-test-first, red-green-refactor]
cites_files: []
---

# PAT-SP-001: TDD Red-Green-Refactor

## 模式（Pattern）

源自 test-driven-development。铁律：

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

若已写了生产代码却没有先写失败测试——删除生产代码，从测试重来。

## 循环

1. **RED**：写一个最小失败测试，描述真实行为（清晰命名，一事一测）
2. **Verify RED**：必须亲眼看到正确失败原因
3. **GREEN**：写最小代码使测试通过
4. **Verify GREEN**：全绿
5. **REFACTOR**：保持绿灯下清理

## 后端示例意图

- 先测 service/API 契约（状态码、错误码、副作用）
- 再实现 handler；禁止「先实现再补测」

## 前端示例意图

- 先测用户可见行为（role/text），再实现组件
- 禁止先写完整 UI 再「补」测试

## 与 MMS

`postcheck` 的 pytest 门禁应优先保证「行为测试存在且通过」，而非覆盖率虚高。
