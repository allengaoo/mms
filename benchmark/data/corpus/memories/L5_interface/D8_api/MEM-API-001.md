# API Response Envelope Format

**ID**: MEM-API-001
**Layer**: L5_interface
**Tags**: [api, response, envelope, fastapi]
**Severity**: critical

## Pattern

All API responses must use a consistent envelope format. Never return raw lists or unstructured dicts.

## Correct Usage

```python
# Always wrap in envelope
return ResponseHelper.ok(
    data=items,
    meta={"total": total, "page": page, "page_size": page_size}
)

# Response shape:
# {"code": 200, "data": [...], "meta": {"total": 42, ...}}
```

## Anti-pattern

```python
# WRONG: raw list response
return items

# WRONG: unstructured dict
return {"items": items, "count": len(items)}
```

## Why

- Consistent error handling on the client side
- Enables generic pagination / meta handling
- Easier API versioning
