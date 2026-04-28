---
id: AC-SQLALCH-01
tier: hot
layer: L2
protection_bonus: 0.35
tags: [python, sqlalchemy, orm, v2, mapping]
---
# AC-SQLALCH-01：使用 mapped_column() + Mapped[] 替代旧版 Column()

## 约束
SQLAlchemy 2.x 中 MUST 使用 `Mapped[T]` 类型注解 + `mapped_column()`；
旧版 `Column()` 用法在 2.x 中已标记为遗留，将在 3.0 移除。

## 反例（Anti-pattern）

```python
# ❌ SQLAlchemy 1.x 旧式写法（2.x 中已废弃）
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    email = Column(String(200), unique=True)
```

## 正例（Correct Pattern）

```python
# ✅ SQLAlchemy 2.x 声明式映射（推荐）
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(200), unique=True)
```

## 原因
`Mapped[T]` 使 IDE 能提供完整类型推断，`Optional[T]` 写法自动映射为 `nullable=True`。
SQLAlchemy 2.0+ 官方已将旧式 Column 标记为 Legacy API。
