---
id: MEM-L-F004
title: Go 并发：goroutine 泄漏检测需在 context.Done() 中显式退出
type: lesson
layer: DOMAIN
dimension: D4
tags: [go, goroutine, context, leak, concurrency]
about_concepts: [concurrency, go-runtime, context-cancellation, resource-management]
access_count: 5
last_accessed: "2026-03-15"
tier: cold
drift_suspected: false
version: 1
---

## WHERE（适用场景）
在 Go 微服务中使用 goroutine 处理后台任务、长轮询或流式数据时。

## HOW（核心实现）
1. 所有 goroutine 必须监听 `ctx.Done()`，在 context 取消时主动退出。
2. 使用 `errgroup.WithContext` 而非裸 goroutine + WaitGroup，自动传播取消信号。
3. 借助 `goleak` 在测试中检测 goroutine 泄漏（`defer goleak.VerifyNone(t)`）。

## WHEN（触发条件）
- 当新增 `go func()` 语法时，代码审查必须检查是否有 `ctx.Done()` 退出路径。
