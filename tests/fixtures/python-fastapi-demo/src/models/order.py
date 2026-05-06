"""Order domain entity — DOMAIN layer."""
from sqlalchemy import Column, String, Float, JSON
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Order(Base):
    """Core domain entity representing a customer order."""

    __tablename__ = "orders"

    id = Column(String, primary_key=True)
    customer_id = Column(String, nullable=False)
    items = Column(JSON, nullable=False, default=list)
    total_amount = Column(Float, nullable=False)
    status = Column(String, nullable=False, default="pending")
