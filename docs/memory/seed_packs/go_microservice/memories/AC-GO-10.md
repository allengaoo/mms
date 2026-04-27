---
id: AC-GO-10
layer: CC
tier: warm
type: lesson
language: go
pack: go_microservice
about_concepts: [goroutine-leak, testing, goleak, test-cleanup, go]
cites_files: []
created_at: "2026-04-27"
---

# 涉及 goroutine 的测试必须用 goleak 检测泄漏

## 教训（Lesson）

Go 测试中启动了 goroutine 但未等待其结束，会导致 goroutine 在测试结束后继续运行（goroutine leak），累积后会污染其他测试或使进程崩溃。

```go
// ❌ 测试中 goroutine 泄漏（常见于 channel/HTTP server 测试）
func TestWorker_Process(t *testing.T) {
    w := NewWorker(make(chan Task, 10))
    go w.Start()   // goroutine 启动了，测试结束后还在运行！
    // 向 channel 发送任务、验证结果...
    // 但没有调用 w.Stop()，goroutine 泄漏！
}
```

```go
// ✅ 正确：使用 goleak 检测 + t.Cleanup 确保清理
import "go.uber.org/goleak"

func TestWorker_Process(t *testing.T) {
    defer goleak.VerifyNone(t)   // 测试结束时验证无 goroutine 泄漏

    ctx, cancel := context.WithCancel(context.Background())
    t.Cleanup(cancel)            // 测试结束时取消 context，goroutine 自动退出

    w := NewWorker(ctx, make(chan Task, 10))
    go w.Start()

    // 发送任务
    w.Tasks <- Task{ID: 1}
    // 验证结果...
    // t.Cleanup(cancel) 会在测试结束时调用 cancel()，
    // goroutine 监听 ctx.Done() 后退出，goleak 检测通过
}
```

## CI 集成

```go
// 在 TestMain 中全局开启（推荐）
func TestMain(m *testing.M) {
    goleak.VerifyTestMain(m)   // 所有测试完成后验证无泄漏
}
```

## 参考

- goleak：https://github.com/uber-go/goleak
- Go 官方博客：[Goroutine Leaks - The Forgotten Sender](https://ardanlabs.com/blog/2018/11/goroutine-leaks-the-forgotten-sender.html)
