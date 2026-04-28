---
id: AC-SQLALCH-04
tier: warm
layer: L2
protection_bonus: 0.25
tags: [python, sqlalchemy, relationship, back_populates, backref]
---
# AC-SQLALCH-04：使用 back_populates 替代 backref

## 约束
关联关系 MUST 使用显式 `back_populates`；
NEVER 使用已废弃的 `backref` 字符串（类型不安全，IDE 无法推断）。

## 反例（Anti-pattern）

```python
# ❌ 使用 backref 字符串（无类型安全）
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    posts = relationship("Post", backref="author")  # 隐式创建反向属性

class Post(Base):
    __tablename__ = "posts"
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    # author 属性由 backref 隐式创建，类型检查器不知道
```

## 正例（Correct Pattern）

```python
# ✅ 显式 back_populates（类型安全）
from __future__ import annotations
from typing import TYPE_CHECKING

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    posts: Mapped[list[Post]] = relationship(back_populates="author")

class Post(Base):
    __tablename__ = "posts"
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    author: Mapped[User] = relationship(back_populates="posts")
```

## 原因
`back_populates` 在双方都显式声明，类型检查器（mypy/pyright）
可完整推断关联属性的类型，避免运行时 AttributeError。
