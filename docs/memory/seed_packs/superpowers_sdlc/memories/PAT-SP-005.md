---
id: PAT-SP-005
layer: CC_testing
dimension: testing
type: anti-pattern
object_type: AntiPattern
tier: hot
tags: [superpowers, testing-anti-pattern, mock, frontend, backend]
source_ep: EP-000
created_at: "2026-07-19"
version: 1
about_concepts: [test-real-behavior, no-mock-assertions, no-test-only-prod-api]
cites_files: []
---

# PAT-SP-005: 禁止测 Mock / 禁止生产类塞测试方法

## 反模式（Anti-Pattern）

源自 testing-anti-patterns。核心原则：测试代码做什么，而不是 mock 做什么。

## Iron Laws

1. NEVER 断言 mock 占位符存在（如 `getByTestId('sidebar-mock')`）
2. NEVER 在生产类添加仅测试使用的方法（如危险的 `destroy()`）
3. NEVER 在不理解依赖的情况下盲目 mock

## 正确做法

- 前端：测真实角色/文本/交互；必须隔离时也断言宿主行为，不断言 mock
- 后端：清理逻辑放 `test-utils/`，不污染生产 API
- 闸门：断言前自问「我在测真实行为还是 mock 存在性？」

映射约束：`SP-TEST-001`。
