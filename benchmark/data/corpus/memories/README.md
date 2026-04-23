# Benchmark Corpus — Memories

This directory contains sample memories used by the benchmark to evaluate retrieval quality.
These are **generic software engineering patterns**, not project-specific memories.

## Structure

```
memories/
├── L1_platform/        # Security, auth, configuration patterns
├── L2_infrastructure/  # DB, cache, messaging patterns
├── L3_domain/          # Domain modeling patterns
├── L4_application/     # Service, worker patterns
├── L5_interface/       # API, frontend, testing patterns
└── cross_cutting/      # Architecture decisions (ADRs)
```

## Adding New Memories

To add benchmark memories, create `.md` files following this schema:

```markdown
# Memory Title

**ID**: MEM-L-NNN
**Layer**: L2_infrastructure
**Tags**: [transaction, mysql, sqlmodel]
**Severity**: critical | warning | info

## Pattern

Describe the pattern or lesson learned.

## Example

```python
# correct usage
```

## Anti-pattern

```python
# wrong usage to avoid
```
```

Run `mms validate` to check schema compliance.
