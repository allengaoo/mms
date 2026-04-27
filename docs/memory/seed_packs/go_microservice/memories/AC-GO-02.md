---
id: AC-GO-02
layer: CC
tier: hot
type: arch_constraint
language: go
pack: go_microservice
about_concepts: [error-wrapping, fmt-errorf, error-stack, go-errors]
cites_files: []
created_at: "2026-04-27"
---

# 错误必须用 fmt.Errorf("%w") 包裹，禁止裸返回原 err

## 约束（Constraint）

在非最外层的函数调用中，当捕获到 `err != nil` 时，严禁直接返回原始 `err`。必须使用 `fmt.Errorf("context: %w", err)` 进行错误包裹，保留完整的调用栈上下文。

```go
// ❌ 错误：裸返回，丢失上下文
func (r *orderRepo) CreateOrder(ctx context.Context, o *biz.Order) error {
    result := r.db.WithContext(ctx).Create(o)
    if result.Error != nil {
        return result.Error   // 调用方只看到 "duplicate key"，不知道是哪个函数
    }
    return nil
}

// ❌ 错误：自定义错误但丢弃原始 err
func getUser(id int64) (*User, error) {
    u, err := db.Find(id)
    if err != nil {
        return nil, errors.New("user not found")  // 原始 err 被丢弃！
    }
    return u, nil
}
```

```go
// ✅ 正确：包裹错误，保留完整上下文
func (r *orderRepo) CreateOrder(ctx context.Context, o *biz.Order) error {
    result := r.db.WithContext(ctx).Create(o)
    if result.Error != nil {
        return fmt.Errorf("orderRepo.CreateOrder: %w", result.Error)
    }
    return nil
}

// 调用链：CreateOrder → PlaceOrder → HTTP Handler
// 最终错误消息：
// "handler.PlaceOrder: service.PlaceOrder: orderRepo.CreateOrder: duplicate key value"
```

## 错误判断

```go
// errors.Is 和 errors.As 对 %w 包裹的错误有效
if errors.Is(err, gorm.ErrRecordNotFound) {
    return nil, status.Error(codes.NotFound, "record not found")
}

var dbErr *mysql.MySQLError
if errors.As(err, &dbErr) && dbErr.Number == 1062 {
    return nil, status.Error(codes.AlreadyExists, "duplicate entry")
}
```

## 参考

- Go Blog：[Working with Errors in Go 1.13](https://go.dev/blog/go1.13-errors)
- Uber Go Style Guide：[Error Wrapping](https://github.com/uber-go/guide/blob/master/style.md#error-wrapping)
