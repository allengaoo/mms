---
id: AC-PY-08
layer: ADAPTER
tier: warm
type: anti_pattern
language: python
pack: python_fastapi
about_concepts: [middleware, fastapi, exception-handling, json-response]
cites_files: []
contradicts: []
created_at: "2026-04-27"
---

# FastAPI 中间件不能抛出未捕获异常，必须统一返回 JSONResponse

## 反模式（Anti-Pattern）

FastAPI 中间件（Middleware）如果抛出未捕获的异常，会导致客户端收到 500 内部服务器错误，且错误格式与正常业务错误不一致（破坏 API 信封格式）。

```python
# ❌ 错误：中间件内部异常未捕获
@app.middleware("http")
async def add_request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID")
    if not request_id:
        raise ValueError("Missing X-Request-ID")  # ❌ 未捕获，返回 500 HTML
    response = await call_next(request)
    return response
```

```python
# ✅ 正确：中间件内部统一返回 JSONResponse
from fastapi.responses import JSONResponse

@app.middleware("http")
async def add_request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID")
    if not request_id:
        return JSONResponse(                       # ✅ 统一 JSON 格式
            status_code=400,
            content={"code": 40001, "message": "Missing X-Request-ID", "data": None},
        )
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response
```

## 原因（Why）

FastAPI 的 `@app.exception_handler` 无法捕获 Middleware 内部抛出的异常（Starlette 的中间件层在异常处理器之外）。中间件必须自行保证不向外泄漏未捕获异常。
