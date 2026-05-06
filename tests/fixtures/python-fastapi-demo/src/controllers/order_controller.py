"""Order HTTP controller — ADAPTER layer."""
from fastapi import APIRouter, Depends, HTTPException
from ..services.order_service import OrderService
from ..schemas.order_schema import CreateOrderRequest, OrderResponse

router = APIRouter(prefix="/orders", tags=["orders"])


class OrderController:
    """REST adapter for order management endpoints."""

    def __init__(self, service: OrderService) -> None:
        self._service = service

    @router.post("/", response_model=OrderResponse)
    async def create_order(self, request: CreateOrderRequest) -> OrderResponse:
        """Create a new order."""
        return await self._service.create_order(request)

    @router.get("/{order_id}", response_model=OrderResponse)
    async def get_order(self, order_id: str) -> OrderResponse:
        """Retrieve an order by ID."""
        order = await self._service.get_order(order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        return order

    @router.delete("/{order_id}", status_code=204)
    async def delete_order(self, order_id: str) -> None:
        """Cancel an order."""
        await self._service.cancel_order(order_id)
