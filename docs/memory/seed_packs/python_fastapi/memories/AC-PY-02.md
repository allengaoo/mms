---
id: AC-PY-02
layer: ADAPTER
tier: hot
type: arch_constraint
language: python
pack: python_fastapi
about_concepts: [response-model, pydantic, fastapi, api-contract]
cites_files: []
contradicts: []
created_at: "2026-04-27"
---

# 路由 response_model 必须绑定 Pydantic Schema，禁止返回裸字典

## 约束（Constraint）

FastAPI 路由的 `response_model` 必须绑定继承自 `pydantic.BaseModel` 的 Schema 类。禁止在 `return` 语句中直接构造并返回 Python 字典。

```python
# ❌ 错误：返回裸字典
@router.get("/users/{user_id}")
async def get_user(user_id: int, db: Session = Depends(get_db)):
    user = crud.get_user(db, user_id=user_id)
    return {"id": user.id, "email": user.email}   # 错误！
```

```python
# ✅ 正确：绑定 response_model
class UserPublic(BaseModel):
    id: int
    email: str
    model_config = ConfigDict(from_attributes=True)

@router.get("/users/{user_id}", response_model=UserPublic)
async def get_user(user_id: int, db: Session = Depends(get_db)):
    return crud.get_user(db, user_id=user_id)
```

## 原因（Why）

1. **字段过滤**：`response_model` 自动过滤 Schema 中未声明的字段（如密码 hash），防止敏感数据泄露
2. **文档生成**：OpenAPI 文档中的响应 Schema 只有绑定 `response_model` 才能正确渲染
3. **类型校验**：Pydantic 在序列化时会进行类型转换和校验，裸字典完全绕过此保护

## 参考

- Pydantic v2 文档：[Response Model](https://fastapi.tiangolo.com/tutorial/response-model/)
- 参考实现：`tiangolo/full-stack-fastapi-template/backend/app/api/routes/users.py`
