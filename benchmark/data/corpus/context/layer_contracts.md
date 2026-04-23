# Layer Boundary Contracts

## L5 — Interface Layer (API Endpoints)

**Typical path**: `app/api/v1/endpoints/*.py`

**Must have**:
- Route decorator with `response_model`
- Permission guard decorator
- `SecurityContext` from dependency injection
- Return via `ResponseHelper` (no raw dicts/lists)

**Must NOT have**:
- Business logic (SQL queries, calculations)
- Direct infrastructure imports (`pymilvus`, `aiokafka`, `elasticsearch`)

---

## L4 — Application Layer (Services)

**Typical path**: `app/services/*.py`

**Must have**:
- `ctx: SecurityContext` as first argument
- `AuditService.log()` on all WRITE operations
- Explicit transaction management (Strategy A or B)

**Must NOT have**:
- Direct HTTP calls to external services (use adapters)
- Raw SQL strings (use ORM)

---

## L3 — Domain Layer (Models & Business Rules)

**Typical path**: `app/domain/*.py`

**Must have**:
- Pure business rule validation (no I/O)
- Domain exceptions with error codes

---

## L2 — Infrastructure Layer (DB, Cache, Queue)

**Typical path**: `app/infrastructure/*.py`

**Rules**:
- Transaction Strategy A: `async with session.begin(): ...`
- Transaction Strategy B: `await session.execute(...)` + explicit `await session.commit()`
- **NEVER** call `session.begin()` after `session.execute()` (triggers autobegin conflict)
- Cache read-heavy queries with `@cached` decorator

---

## L1 — Platform Layer (Security, Config)

**Typical path**: `app/core/*.py`

**Rules**:
- All secrets via environment variables or `SystemConfig`
- No hardcoded values (timeouts, limits, switches)
