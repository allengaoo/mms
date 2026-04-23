"""
参考实现：bulk_create_objects (ontology_service.py)
任务 ID：CG-007
层：L4_service (Service 层)

评分重点：
  - ctx: RequestContext 首参（AC-2）
  - 审计日志：audit_service.log()（AC-3）
  - Strategy B 事务：autobegin + explicit commit
  - 禁止 session.begin() 在 execute() 之后
  - 禁止 fetchall()
"""
from typing import List

from sqlalchemy import select

from app.core.context import RequestContext
from app.core.db import async_session_factory
from app.core.exceptions import DomainException, E_ONT_001
from app.core.logger import get_logger
from app.models.ontology import ObjectTypeDef, ObjectTypeVer, VersionStatus
from app.api.schemas.ontology import ObjectCreateDTO, ObjectReadDTO
from app.services.control.audit_service import audit_service

log = get_logger("app.services.control.ontology_service")

MAX_BULK_CREATE = 50


async def bulk_create_objects(
    ctx: RequestContext,
    dtos: List[ObjectCreateDTO],
) -> List[ObjectReadDTO]:
    """
    批量创建 ObjectTypeDef，单事务原子提交。

    - 重复 api_name（同一 tenant）跳过，返回已存在的
    - 超过 MAX_BULK_CREATE 条拒绝（防止超大事务）
    - 每个对象独立记录审计日志

    Args:
        ctx: 安全上下文
        dtos: 创建 DTO 列表

    Returns:
        成功创建的 ObjectReadDTO 列表
    """
    if not dtos:
        return []

    if len(dtos) > MAX_BULK_CREATE:
        raise DomainException(
            code="E_ONT_BULK_LIMIT",
            message=f"批量创建最多 {MAX_BULK_CREATE} 个，当前：{len(dtos)}",
        )

    results: List[ObjectReadDTO] = []
    api_names = [d.api_name for d in dtos]

    async with async_session_factory() as session:
        # Strategy B：autobegin（session.execute 触发）+ explicit commit
        existing = (
            await session.execute(
                select(ObjectTypeDef).where(
                    ObjectTypeDef.tenant_id == ctx.tenant_id,
                    ObjectTypeDef.api_name.in_(api_names),
                )
            )
        ).scalars().all()

        existing_names = {obj.api_name for obj in existing}

        for dto in dtos:
            if dto.api_name in existing_names:
                log.info(
                    "bulk_create_objects.skip_duplicate",
                    tenant_id=ctx.tenant_id,
                    api_name=dto.api_name,
                )
                continue

            obj = ObjectTypeDef(
                api_name=dto.api_name,
                display_name=dto.display_name,
                description=dto.description or "",
                tenant_id=ctx.tenant_id,
                created_by=ctx.user_id,
                status=VersionStatus.DRAFT,
            )
            session.add(obj)

        # 先 flush 获取 ORM id（不提交事务）
        await session.flush()

        # 审计每个新建对象
        for dto in dtos:
            if dto.api_name not in existing_names:
                await audit_service.log(
                    ctx=ctx,
                    action="bulk_create_objects",
                    resource_type="ObjectTypeDef",
                    resource_id=dto.api_name,
                    detail={"display_name": dto.display_name},
                )

        # 显式提交（Strategy B）
        await session.commit()

        # 重新查询返回完整 DTO
        created = (
            await session.execute(
                select(ObjectTypeDef).where(
                    ObjectTypeDef.tenant_id == ctx.tenant_id,
                    ObjectTypeDef.api_name.in_(
                        [d.api_name for d in dtos if d.api_name not in existing_names]
                    ),
                )
            )
        ).scalars().all()

        results = [ObjectReadDTO.model_validate(obj) for obj in created]

    log.info(
        "bulk_create_objects.done",
        tenant_id=ctx.tenant_id,
        created=len(results),
        skipped=len(existing_names),
        trace_id=ctx.trace_id,
    )
    return results
