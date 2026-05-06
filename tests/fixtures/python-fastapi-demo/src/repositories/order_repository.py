"""Order repository — DOMAIN layer (data access abstraction)."""
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..models.order import Order


class OrderRepository:
    """SQLAlchemy-backed repository for Order entities."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, order: Order) -> Order:
        """Persist an order (insert or update)."""
        self._session.add(order)
        await self._session.commit()
        await self._session.refresh(order)
        return order

    async def find_by_id(self, order_id: str) -> Optional[Order]:
        """Find order by primary key."""
        result = await self._session.execute(
            select(Order).where(Order.id == order_id)
        )
        return result.scalar_one_or_none()

    async def find_by_customer(self, customer_id: str) -> List[Order]:
        """Find all orders for a customer."""
        result = await self._session.execute(
            select(Order).where(Order.customer_id == customer_id)
        )
        return list(result.scalars().all())

    async def delete(self, order_id: str) -> bool:
        """Delete an order by ID. Returns True if deleted."""
        order = await self.find_by_id(order_id)
        if order:
            await self._session.delete(order)
            await self._session.commit()
            return True
        return False
