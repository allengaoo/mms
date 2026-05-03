# Transaction Management: Autobegin Conflict

**ID**: MEM-DB-001
**Layer**: L2_infrastructure
**Tags**: [transaction, sqlalchemy, sqlmodel, mysql]
**Severity**: critical

## Pattern

When using SQLAlchemy async sessions, calling `session.begin()` after `session.execute()` raises `InvalidRequestError` because `execute()` triggers autobegin implicitly.

## Correct Usage (Strategy A — Begin First)

```python
async with session.begin():
    result = await session.execute(select(Item).where(Item.id == item_id))
    item = result.scalar_one_or_none()
    session.add(new_item)
# commit happens automatically on context exit
```

## Correct Usage (Strategy B — Autobegin + Explicit Commit)

```python
result = await session.execute(select(Item).where(Item.id == item_id))
item = result.scalar_one_or_none()
session.add(new_item)
await session.commit()
```

## Anti-pattern

```python
# WRONG: execute() triggers autobegin, then begin() raises InvalidRequestError
result = await session.execute(select(Item))
async with session.begin():   # ← raises InvalidRequestError
    session.add(new_item)
```
