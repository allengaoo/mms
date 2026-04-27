---
id: AC-GO-04
layer: DOMAIN
tier: warm
type: anti_pattern
language: go
pack: go_microservice
about_concepts: [global-state, dependency-injection, wire, testability, go]
cites_files: []
created_at: "2026-04-27"
---

# 禁止全局可变状态，必须通过构造函数依赖注入

## 反模式（Anti-Pattern）

```go
// ❌ 全局可变状态反模式
var (
    GlobalDB    *gorm.DB        // 全局 DB 连接
    GlobalRedis *redis.Client   // 全局 Redis 连接
    GlobalCache = make(map[string]interface{})  // 全局缓存
)

func init() {
    GlobalDB, _ = gorm.Open(mysql.Open(os.Getenv("DATABASE_URL")))
    GlobalRedis = redis.NewClient(&redis.Options{Addr: "localhost:6379"})
}

// 使用全局变量
func GetUser(id int64) (*User, error) {
    return GlobalDB.First(&User{}, id).Error  // 无法测试！
}
```

## 正确做法：构造函数依赖注入（配合 Wire）

```go
// ✅ 正确：通过结构体持有依赖
type UserRepo struct {
    db    *gorm.DB
    cache *redis.Client
}

func NewUserRepo(db *gorm.DB, cache *redis.Client) *UserRepo {
    return &UserRepo{db: db, cache: cache}
}

func (r *UserRepo) FindById(ctx context.Context, id int64) (*User, error) {
    // 通过 r.db 使用，可以在测试中传入 mock
    var user User
    return &user, r.db.WithContext(ctx).First(&user, id).Error
}

// Wire 依赖注入（自动生成 wire_gen.go）
// wire.go
func InitApp(conf *conf.Bootstrap) (*App, func(), error) {
    wire.Build(
        NewDB,
        NewRedis,
        NewUserRepo,
        NewUserService,
        NewServer,
        NewApp,
    )
    return nil, nil, nil
}
```

## 测试友好

```go
// 测试中只需传入 mock 或测试专用 DB
func TestUserRepo_FindById(t *testing.T) {
    db := setupTestDB(t)           // 测试专用 DB，不依赖全局状态
    repo := NewUserRepo(db, nil)
    user, err := repo.FindById(context.Background(), 1)
    assert.NoError(t, err)
}
```

## 参考

- Google Wire：https://github.com/google/wire
- Uber Go Style Guide：[Avoid Global State](https://github.com/uber-go/guide/blob/master/style.md#avoid-global-state)
