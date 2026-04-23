"""
参考实现：GET /objects/{object_id}/topology
任务 ID：CG-001
层：L5_api (FastAPI Endpoint)

评分重点：
  - 路由装饰器必须有 response_model
  - 权限守卫 require_permission("ont:object:view")
  - SecurityContext 通过 Depends 注入，不得硬编码
  - 使用 ResponseHelper.ok() 包装，不得裸返回列表/字典
"""
from typing import List

from fastapi import APIRouter, Depends, Query

from app.core.auth import get_current_user, CurrentUser
from app.core.context import RequestContext, get_context
from app.core.response import ResponseSchema, success_response
from app.core.rbac import require_permission
from app.api.schemas.ontology import TopologyDTO, TopologyNodeDTO, TopologyEdgeDTO
from app.services.query.ontology_query_service import get_object_topology as _get_topology

router = APIRouter(prefix="/objects", tags=["ontology"])


@router.get(
    "/{object_id}/topology",
    response_model=ResponseSchema[TopologyDTO],
    summary="获取对象拓扑结构",
)
@require_permission("ont:object:view")
async def get_object_topology(
    object_id: str,
    depth: int = Query(default=3, ge=1, le=10, description="拓扑展开深度"),
    ctx: RequestContext = Depends(get_context),
    current_user: CurrentUser = Depends(get_current_user),
) -> ResponseSchema[TopologyDTO]:
    """
    返回指定对象的上游依赖和下游引用拓扑结构。

    Args:
        object_id: ObjectTypeDef 的 API 名称或 UUID
        depth: 拓扑展开深度，默认 3 层
        ctx: 安全上下文（含 tenant_id, user_id, trace_id）
        current_user: 当前登录用户（JWT 解析）

    Returns:
        ResponseSchema[TopologyDTO]: 含节点和边的拓扑图
    """
    topology = await _get_topology(ctx, object_id=object_id, depth=depth)
    return success_response(data=topology)
