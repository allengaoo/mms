---
id: AC-PY-09
layer: DOMAIN
tier: warm
type: pattern
language: python
pack: python_fastapi
about_concepts: [multi-tenancy, row-level-security, sqlalchemy, query-filter]
cites_files: []
contradicts: []
created_at: "2026-04-27"
---

# 多租户 RLS：所有查询必须注入 tenant_id 过滤条件

## 模式（Pattern）

在多租户（Multi-Tenant）系统中，每个 SQLAlchemy 查询必须强制注入 `tenant_id` 过滤条件，防止租户数据越界访问。

## 推荐实现：自定义 Session 事件

```python
# app/db/tenant_session.py
from sqlalchemy import event
from sqlalchemy.orm import Session

def apply_tenant_filter(session: Session, tenant_id: str):
    """为 session 内所有查询自动注入 tenant_id 过滤"""
    @event.listens_for(session, "do_orm_execute")
    def add_tenant_filter(execute_state):
        if (
            execute_state.is_select
            and not execute_state.execution_options.get("skip_tenant_filter", False)
        ):
            execute_state.statement = execute_state.statement.filter_by(
                tenant_id=tenant_id
            )

# app/api/deps.py
def get_tenant_db(
    request: Request,
    db: Session = Depends(get_db),
) -> Session:
    tenant_id = request.state.tenant_id   # 从 JWT/Header 提取
    apply_tenant_filter(db, tenant_id)
    return db
```

## 逃生舱（Escape Hatch）

对于管理员级别的跨租户查询，使用 `execution_options(skip_tenant_filter=True)`：

```python
# 仅限 admin 路由
result = db.execute(
    select(User),
    execution_options={"skip_tenant_filter": True}
)
```

## 原因（Why）

硬编码每个 CRUD 函数的 `filter(Model.tenant_id == tenant_id)` 极易遗漏，造成数据泄露。将 RLS 下沉到 Session 层可保证无论哪个开发者写 CRUD 都不会绕过租户隔离。
