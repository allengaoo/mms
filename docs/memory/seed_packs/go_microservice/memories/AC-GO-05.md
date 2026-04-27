---
id: AC-GO-05
layer: PLATFORM
tier: hot
type: lesson
language: go
pack: go_microservice
about_concepts: [goroutine, errgroup, context-cancellation, goroutine-leak, go-concurrency]
cites_files: []
created_at: "2026-04-27"
---

# goroutine 必须监听 ctx.Done()，使用 errgroup 替代裸 goroutine+WaitGroup

## 教训（Lesson）

裸 goroutine + `sync.WaitGroup` 的组合无法传播取消信号，一旦某个 goroutine 失败，其他 goroutine 会继续运行直到完成，造成资源浪费和 goroutine 泄漏。

```go
// ❌ 危险：裸 goroutine 无法取消，一个失败其他不知道
var wg sync.WaitGroup
var firstErr error

for _, task := range tasks {
    wg.Add(1)
    go func(t Task) {
        defer wg.Done()
        if err := processTask(t); err != nil {
            firstErr = err   // data race！多个 goroutine 并发写
        }
    }(task)
}
wg.Wait()
```

```go
// ✅ 正确：errgroup 自动传播取消和错误
import "golang.org/x/sync/errgroup"

func processTasks(ctx context.Context, tasks []Task) error {
    g, gctx := errgroup.WithContext(ctx)

    for _, task := range tasks {
        task := task   // 捕获循环变量（Go 1.21 之前必须）
        g.Go(func() error {
            return processTask(gctx, task)   // gctx 在任一 goroutine 出错时自动取消
        })
    }

    return g.Wait()   // 等待所有完成，返回第一个错误
}

// processTask 监听取消信号
func processTask(ctx context.Context, task Task) error {
    select {
    case <-ctx.Done():
        return ctx.Err()   // 感知到取消，提前退出
    default:
    }
    // ... 执行任务
}
```

## 并发限制（Semaphore 模式）

```go
// 限制最大并发数（防止资源耗尽）
g, gctx := errgroup.WithContext(ctx)
sem := make(chan struct{}, 10)   // 最多 10 个并发

for _, task := range tasks {
    task := task
    sem <- struct{}{}            // 获取令牌
    g.Go(func() error {
        defer func() { <-sem }() // 释放令牌
        return processTask(gctx, task)
    })
}
```

## 参考

- errgroup 文档：https://pkg.go.dev/golang.org/x/sync/errgroup
- Go Blog：[Concurrency Patterns: Context](https://go.dev/blog/context)
