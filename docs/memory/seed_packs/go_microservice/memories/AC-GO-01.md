---
id: AC-GO-01
layer: APP
tier: hot
type: arch_constraint
language: go
pack: go_microservice
about_concepts: [project-layout, internal, pkg, visibility, go]
cites_files: []
created_at: "2026-04-27"
---

# Go 项目可见性屏障：internal/ 与 pkg/ 的严格分工

## 约束（Constraint）

- `internal/`：核心业务逻辑、数据访问层、领域模型。**仅本模块可导入**（Go 编译器强制）
- `pkg/`：**只能存放无副作用的纯工具函数**（字符串处理、时间格式化、数学运算等）

```
project/
├── internal/
│   ├── biz/          # 业务逻辑层（Use Case）
│   ├── data/         # 数据访问层（Repository 实现）
│   ├── service/      # gRPC/HTTP Handler
│   └── conf/         # 配置结构体（不对外暴露）
├── pkg/
│   ├── timeutil/     # ✅ 纯工具：时间格式化、时区转换
│   └── mathutil/     # ✅ 纯工具：精度计算
│   # ❌ 禁止：pkg/db/，pkg/cache/（有副作用）
└── api/              # Protobuf 定义（公开接口）
```

```go
// ❌ 错误：pkg/ 中包含有副作用的代码
// pkg/db/client.go
package db

var DB *gorm.DB   // 全局状态！有副作用！不应在 pkg/ 中

// ✅ 正确：有状态的基础设施放在 internal/data/
// internal/data/db.go
package data

type Data struct {
    db *gorm.DB
}

func NewData(conf *conf.Data) (*Data, func(), error) {
    db, err := gorm.Open(mysql.Open(conf.Database.Source))
    cleanup := func() { db.Close() }
    return &Data{db: db}, cleanup, err
}
```

## 参考

- Go 文档：[Internal packages](https://pkg.go.dev/cmd/go#hdr-Internal_Directories)
- 参考实现：`go-kratos/kratos/examples/`
