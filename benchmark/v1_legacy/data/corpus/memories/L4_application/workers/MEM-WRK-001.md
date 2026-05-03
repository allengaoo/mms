# Worker Job Execution Scope

**ID**: MEM-WRK-001
**Layer**: L4_application
**Tags**: [worker, job, execution, lifecycle]
**Severity**: critical

## Pattern

All workers must use `JobExecutionScope` for context hydration, status lifecycle management, and error handling. Do not scatter try/except blocks to manage job state.

## Correct Usage

```python
class MyWorker(BaseWorker):
    async def execute(self, job_id: str, payload: dict) -> None:
        async with JobExecutionScope(job_id, self.job_repo) as scope:
            ctx = scope.build_context(payload)
            # Business logic here
            result = await self.service.process(ctx, payload["data"])
            scope.set_result(result)
        # Status automatically set to DONE or FAILED by scope
```

## Anti-pattern

```python
# WRONG: manual status management scattered in try/except
async def execute(self, job_id: str, payload: dict) -> None:
    try:
        await self.job_repo.set_status(job_id, "running")
        result = await self.service.process(payload)
        await self.job_repo.set_status(job_id, "done")
    except Exception as e:
        await self.job_repo.set_status(job_id, "failed")
        raise
```
