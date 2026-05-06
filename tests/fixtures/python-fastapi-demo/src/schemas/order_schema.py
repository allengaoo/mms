"""Order request/response schemas (Pydantic DTOs) — DOMAIN layer."""
from pydantic import BaseModel
from typing import List


class OrderItem(BaseModel):
    product_id: str
    quantity: int
    price: float


class CreateOrderRequest(BaseModel):
    customer_id: str
    items: List[OrderItem]


class OrderResponse(BaseModel):
    id: str
    customer_id: str
    total_amount: float
    status: str

    @classmethod
    def from_domain(cls, order) -> "OrderResponse":
        return cls(
            id=order.id,
            customer_id=order.customer_id,
            total_amount=order.total_amount,
            status=order.status,
        )
