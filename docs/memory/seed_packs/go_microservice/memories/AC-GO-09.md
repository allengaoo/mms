---
id: AC-GO-09
layer: DOMAIN
tier: warm
type: pattern
language: go
pack: go_microservice
about_concepts: [interface, dependency-inversion, consumer-defines-interface, go]
cites_files: []
created_at: "2026-04-27"
---

# Go 接口应定义在调用方（Consumer）所在的包

## 模式（Pattern）

Go 使用隐式接口实现（implicit interface satisfaction）。接口应定义在**使用它的包**（调用方/Consumer），而非实现它的包（提供方/Provider）。

```go
// ❌ Java 风格：接口在 Provider 包中（违反 Go 惯用法）
// internal/data/user_repository.go（Provider 包）
type UserRepository interface {    // ❌ 接口定义在实现方
    FindById(ctx context.Context, id int64) (*User, error)
}
type userRepositoryImpl struct { db *gorm.DB }
func (r *userRepositoryImpl) FindById(...) (*User, error) { ... }
```

```go
// ✅ Go 惯用法：接口在 Consumer 包中（biz 层定义，data 层实现）
// internal/biz/user.go（Consumer 包，定义接口）
type UserRepo interface {                   // ✅ 接口在调用方
    FindById(ctx context.Context, id int64) (*User, error)
    Save(ctx context.Context, u *User) error
}

type UserUsecase struct {
    repo UserRepo   // 依赖接口，不依赖实现
}

// internal/data/user.go（Provider 包，实现接口）
type userRepo struct { data *Data }
// 只要方法签名匹配，自动满足 biz.UserRepo 接口（无需 implements 关键字）
func (r *userRepo) FindById(ctx context.Context, id int64) (*User, error) { ... }
func (r *userRepo) Save(ctx context.Context, u *User) error { ... }
```

## 好处

1. **依赖方向正确**：`biz` 层不依赖 `data` 层（只依赖自己定义的接口），符合 DDD 的依赖倒置原则
2. **最小接口原则**：Consumer 只定义自己需要的方法（而非 Provider 提供的所有方法），减少不必要的耦合
3. **测试友好**：可以轻松 mock `biz.UserRepo` 接口，无需引入 `data` 包

## 参考

- Go Wiki：[CodeReviewComments: Interfaces](https://github.com/golang/go/wiki/CodeReviewComments#interfaces)
- Rob Pike：["The bigger the interface, the weaker the abstraction"](https://go-proverbs.github.io/)
