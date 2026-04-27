---
id: AC-PY-10
layer: ADAPTER
tier: hot
type: lesson
language: python
pack: python_fastapi
about_concepts: [async, httpx, event-loop, blocking-io, fastapi]
cites_files: []
contradicts: []
created_at: "2026-04-27"
---

# async 路由函数内禁止调用同步阻塞 IO

## 教训（Lesson）

在 `async def` 路由函数内调用 `requests.get()` 等同步阻塞 I/O，会**完全阻塞 asyncio 事件循环**，导致其他并发请求全部挂起，在高并发场景下引发灾难性性能下降。

```python
import requests

# ❌ 严重错误：阻塞事件循环
@router.get("/weather")
async def get_weather(city: str):
    response = requests.get(f"https://api.weather.com/{city}")  # 阻塞！
    return response.json()
```

## 正确做法

```python
import httpx

# ✅ 正确：使用 httpx.AsyncClient（async 原生）
@router.get("/weather")
async def get_weather(city: str):
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"https://api.weather.com/{city}")
        response.raise_for_status()
        return response.json()

# ✅ 更好：使用共享的 Client（避免重复建立连接）
# 在 lifespan 事件中初始化
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient(timeout=30.0)
    yield
    await app.state.http_client.aclose()
```

## 如果必须调用同步库

```python
import asyncio
from functools import partial

# ✅ 将同步调用放入线程池执行，不阻塞事件循环
@router.get("/sync-task")
async def call_sync_lib(param: str):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, sync_library_call, param)
    return result
```

## 参考

- httpx 文档：https://www.python-httpx.org/async/
- FastAPI 文档：[Concurrency and async / await](https://fastapi.tiangolo.com/async/)
