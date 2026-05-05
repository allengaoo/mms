---
id: AD-SEED-002
layer: CC
module: architecture
type: decision
tier: hot
tags: [api, contract, response-format, error-handling, cold-start, seed]
source_ep: EP-130
created_at: 2026-04-18
version: 1
generalized: true
---

# AD-SEED-002: API 接口契约规范（通用）

## 决策

所有 HTTP API 响应必须使用统一的信封格式，禁止裸列表或裸对象响应。

## 标准格式

```json
{
  "code": 200,
  "data": { ... },
  "meta": { "total": 100, "page": 1 }
}
```

## 错误格式

```json
{
  "code": 40001,
  "message": "资源不存在",
  "trace_id": "xxx"
}
```

## 违反后果

客户端无法统一处理错误，前端拦截器无法工作，监控系统无法正确识别错误率。
