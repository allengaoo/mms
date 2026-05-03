"""
参考实现：ObjectTypeDef.metadata_json 字段
任务 ID：CG-013
层：L3_model (Domain Model)

评分重点：
  - 必须使用 sa_column=Column(JSON)（MySQL JSON 列）
  - 不能使用 JSON() / JsonType（错误用法）
  - 允许为 NULL，默认 {} 
"""
from typing import Optional, Dict, Any

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


class ObjectTypeDef(SQLModel, table=True):
    """示例：在现有 ObjectTypeDef 中新增 metadata_json 字段"""

    __tablename__ = "meta_object_defs"

    # ... 其他已有字段省略 ...

    metadata_json: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description="扩展元数据（标签、注释等，JSON 格式）",
    )
