---
id: AC-GO-03
layer: CC
tier: hot
type: arch_constraint
language: go
pack: go_microservice
about_concepts: [context, cancellation, timeout, io-operations, go-convention]
cites_files: []
created_at: "2026-04-27"
---

# 所有执行 I/O 的函数第一个参数必须是 context.Context

## 约束（Constraint）

所有执行 I/O 操作（数据库、HTTP、RPC、文件读写、消息队列）的函数，第一个参数必须是 `context.Context`。禁止在函数内部使用 `context.Background()` 或 `context.TODO()` 硬编码上下文。

```go
// ❌ 错误：无 context，无法取消和超时
func (r *userRepo) FindById(id int64) (*User, error) {
    var user User
    err := r.db.First(&user, id).Error   // 无法取消！
    return &user, err
}

// ❌ 错误：内部创建 context，破坏调用链
func (s *userService) GetUser(id int64) (*biz.User, error) {
    ctx := context.Background()   // 绕过调用方的超时控制！
    return s.repo.FindById(ctx, id)
}
```

```go
// ✅ 正确：context 作为第一个参数传递
func (r *userRepo) FindById(ctx context.Context, id int64) (*User, error) {
    var user User
    err := r.db.WithContext(ctx).First(&user, id).Error   // 支持取消
    if err != nil {
        return nil, fmt.Errorf("userRepo.FindById id=%d: %w", id, err)
    }
    return &user, nil
}

func (s *userService) GetUser(ctx context.Context, id int64) (*biz.User, error) {
    return s.repo.FindById(ctx, id)   // context 透传
}
```

## 为什么禁止内部创建 context.Background()？

```go
// 场景：HTTP Handler 设置了 5s 超时
ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
defer cancel()
user, err := userService.GetUser(ctx, userId)

// 如果 GetUser 内部创建了 context.Background()，
// 5s 超时将对 DB 查询完全无效，导致 goroutine 泄漏
```

## 参考

- Go 官方文档：[context package](https://pkg.go.dev/context)
- Effective Go：[Contexts and goroutines](https://go.dev/blog/context)
