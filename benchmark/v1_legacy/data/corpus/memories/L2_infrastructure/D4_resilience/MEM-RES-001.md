# Python `or` Operator with Numeric Defaults

**ID**: MEM-RES-001
**Layer**: L2_infrastructure
**Tags**: [python, defaults, numeric, falsy]
**Severity**: warning

## Pattern

Using `or` for numeric default values is incorrect because `0` is falsy in Python.

## Correct Usage

```python
# Always use explicit None check for numeric fields
def process(count: int = None):
    actual_count = count if count is not None else 10
```

## Anti-pattern

```python
# WRONG: 0 or 10 returns 10, silently ignoring the intended value 0
def process(count: int = None):
    actual_count = count or 10   # ← if count=0, returns 10 (bug!)
```
