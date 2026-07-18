---
id: PAT-SP-006
layer: CC_testing
dimension: testing
type: pattern
object_type: Pattern
tier: warm
tags: [superpowers, async, flaky-tests, frontend, backend, waiting]
source_ep: EP-000
created_at: "2026-07-19"
version: 1
about_concepts: [condition-based-waiting, flaky-test-prevention]
cites_files: []
---

# PAT-SP-006: 条件等待替代 sleep

## 模式（Pattern）

源自 condition-based-waiting。
对异步结果使用 `waitFor(condition)`，禁止用盲目 `sleep`/`setTimeout` 赌时序。

## 适用

- 前端：等待 DOM/状态就绪
- 后端：等待事件、队列、最终一致读
- CI 并行下易 flaky 的集成测试

## 例外

仅当测试的就是定时行为（debounce/throttle）时允许固定等待，且必须注释 WHY。

## 实现要点

- 轮询间隔约 10ms；必须有超时与清晰错误信息
- 循环内取新鲜状态，勿缓存陈旧快照
