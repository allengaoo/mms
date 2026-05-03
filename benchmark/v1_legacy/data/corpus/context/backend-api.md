# Backend API Development Guide

## REST API Design Principles

- Use kebab-case for URL paths: `/api/v1/user-profiles`
- Use snake_case for JSON fields: `{"user_name": "...", "created_at": "..."}`
- Always define `response_model` on FastAPI routes
- Guard routes with `@require_permission("domain:resource:action")`

## Standard Endpoint Pattern

```python
@router.get("/items/{item_id}", response_model=BaseResponse[ItemResponse])
@require_permission("items:read")
async def get_item(
    item_id: int,
    ctx: SecurityContext = Depends(get_current_user),
    service: ItemService = Depends(get_item_service),
) -> BaseResponse[ItemResponse]:
    result = await service.get_by_id(ctx, item_id)
    return ResponseHelper.ok(data=result)
```

## Service Layer Pattern

```python
class ItemService:
    async def get_by_id(self, ctx: SecurityContext, item_id: int) -> ItemResponse:
        # Always pass ctx for tenant isolation
        item = await self.repo.find_by_id(ctx.tenant_id, item_id)
        if not item:
            raise DomainException(code="E_ITEM_NOT_FOUND")
        await AuditService.log(ctx, action="item.read", resource_id=item_id)
        return ItemResponse.from_orm(item)
```

## Error Codes Convention

- `E_NOT_FOUND` — Resource does not exist
- `E_PERMISSION_DENIED` — Insufficient permissions
- `E_VALIDATION` — Input validation failed
- `E_CONFLICT` — Duplicate resource or state conflict
