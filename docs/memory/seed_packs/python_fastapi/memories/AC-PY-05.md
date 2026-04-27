---
id: AC-PY-05
layer: DOMAIN
tier: warm
type: lesson
language: python
pack: python_fastapi
about_concepts: [pydantic, validator, pure-function, side-effects]
cites_files: []
contradicts: []
created_at: "2026-04-27"
---

# Pydantic field_validator 必须是纯函数，禁止调用外部服务

## 教训（Lesson）

Pydantic 的 `@field_validator` 和 `@model_validator` 在模型实例化时同步执行，禁止在内部调用数据库、HTTP 服务或任何 I/O 操作。

```python
# ❌ 错误：validator 内部查询数据库
class UserCreate(BaseModel):
    username: str
    email: str

    @field_validator("email")
    @classmethod
    def email_must_be_unique(cls, v):
        db = SessionLocal()
        if db.query(User).filter(User.email == v).first():  # ❌ 数据库调用！
            raise ValueError("Email already registered")
        return v
```

```python
# ✅ 正确：validator 只做格式/逻辑校验（纯函数）
class UserCreate(BaseModel):
    username: str
    email: EmailStr          # 格式校验交给 Pydantic 内置类型

    @field_validator("username")
    @classmethod
    def username_alphanumeric(cls, v):
        if not v.isalnum():  # ✅ 纯逻辑，无副作用
            raise ValueError("Username must be alphanumeric")
        return v.lower()

# 唯一性校验放在 Service 层（可以调用 DB）
class UserService:
    def create_user(self, db: Session, user_in: UserCreate) -> User:
        if crud.get_user_by_email(db, email=user_in.email):
            raise HTTPException(status_code=400, detail="Email already registered")
        return crud.create_user(db, user_in)
```

## 原因（Why）

1. **测试困难**：在 validator 中调用 DB 使单元测试必须 mock 数据库，违反了 Schema 层的独立性
2. **序列化场景泄漏**：当 Pydantic 用于序列化（而非用户输入）时，多余的 DB 查询会造成性能损耗
3. **Pydantic v2 兼容性**：v2 中 validator 严格为同步，不支持 async，更不适合调用 I/O
