"""Order application service — APP layer."""
from typing import Optional
from ..repositories.order_repository import OrderRepository
from ..models.order import Order
from ..schemas.order_schema import CreateOrderRequest, OrderResponse


class OrderService:
    """Orchestrates order creation and retrieval use cases."""

    def __init__(self, repository: OrderRepository) -> None:
        self._repo = repository

    async def create_order(self, request: CreateOrderRequest) -> OrderResponse:
        """Create order and persist it."""
        order = Order(
            customer_id=request.customer_id,
            items=request.items,
            total_amount=sum(i.price * i.quantity for i in request.items),
        )
        saved = await self._repo.save(order)
        return OrderResponse.from_domain(saved)

    async def get_order(self, order_id: str) -> Optional[OrderResponse]:
        """Retrieve order by ID."""
        order = await self._repo.find_by_id(order_id)
        return OrderResponse.from_domain(order) if order else None

    async def cancel_order(self, order_id: str) -> None:
        """Cancel an existing order."""
        order = await self._repo.find_by_id(order_id)
        if order:
            order.status = "cancelled"
            await self._repo.save(order)
