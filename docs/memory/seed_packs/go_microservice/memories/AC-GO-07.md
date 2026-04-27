---
id: AC-GO-07
layer: ADAPTER
tier: warm
type: pattern
language: go
pack: go_microservice
about_concepts: [http-handler, timeout, context, goroutine-leak, go]
cites_files: []
created_at: "2026-04-27"
---

# HTTP Handler 必须通过 context.WithTimeout 设置超时

## 模式（Pattern）

```go
// ❌ 无超时：下游服务不响应时，goroutine 永远阻塞
func (h *OrderHandler) CreateOrder(w http.ResponseWriter, r *http.Request) {
    order, err := h.service.CreateOrder(r.Context(), parseParam(r))
    // 若 CreateOrder 调用了超时的 RPC，此 goroutine 永远不退出
}
```

```go
// ✅ 正确：为业务操作设置独立超时（不依赖客户端连接超时）
const orderCreateTimeout = 10 * time.Second

func (h *OrderHandler) CreateOrder(w http.ResponseWriter, r *http.Request) {
    ctx, cancel := context.WithTimeout(r.Context(), orderCreateTimeout)
    defer cancel()   // 必须 defer cancel，防止 context 泄漏

    order, err := h.service.CreateOrder(ctx, parseParam(r))
    if err != nil {
        if errors.Is(err, context.DeadlineExceeded) {
            http.Error(w, "request timeout", http.StatusGatewayTimeout)
            return
        }
        http.Error(w, err.Error(), http.StatusInternalServerError)
        return
    }
    json.NewEncoder(w).Encode(order)
}
```

## 超时层次建议

```
客户端超时（如 30s）
  └── HTTP 服务器读写超时（如 25s，server.ReadTimeout/WriteTimeout）
        └── 业务 Handler 超时（如 10s，context.WithTimeout）
              └── 下游 RPC/DB 超时（如 5s，gRPC Deadline / GORM WithContext）
```

每层超时应比下层小，形成超时保护层次。

## 参考

- Go Blog：[Timeouts and Cancellation](https://go.dev/blog/context)
- net/http 文档：[Server.ReadTimeout](https://pkg.go.dev/net/http#Server)
