# MMS Knowledge Index — Master Router

> Load this file at the start of each new task to orient the AI agent.
> Follow with the relevant domain manifest based on task type.

---

## Task Type → Manifest

| Task Type | Manifest File |
|-----------|---------------|
| Backend API | `backend-api.md` |
| Frontend Page | `frontend.md` |
| Data Pipeline | `data-pipeline.md` |
| Debugging | `debug.md` |
| DevOps / Deploy | `devops.md` |
| Full-stack Feature | `fullstack.md` |

## Architecture Layers (L1–L5)

| Layer | Responsibility | Typical Files |
|-------|---------------|---------------|
| L1 Platform | Security, Auth, Config | `core/security.py`, `core/config.py` |
| L2 Infrastructure | DB, Cache, Queue | `infrastructure/db.py`, `infrastructure/redis.py` |
| L3 Domain | Business Logic | `domain/models.py`, `domain/services.py` |
| L4 Application | Service Orchestration | `app/services/*.py` |
| L5 Interface | API, UI, Tests | `api/endpoints/*.py`, `tests/` |

## Key Constraints (Always Apply)

1. Service public methods must accept `ctx: SecurityContext` as first argument
2. All DB queries must filter by `tenant_id` (Row-Level Security)
3. All WRITE operations must call `AuditService.log()`
4. API responses must use envelope format: `{"code": 200, "data": ..., "meta": ...}`
5. No direct import of infrastructure libraries in service layer
