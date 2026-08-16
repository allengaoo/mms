---
id: MEM-L-021
layer: L5_interface
module: api
dimension: D8
type: lesson
tier: hot
description: "offset 分页在百万级数据下性能退化严重；超过 10K 条记录的列表 API 必须改用 cursor-based 分页"
tags: [pagination, cursor-based, offset, performance, large-dataset, api]
source_ep: EP-110
created_at: "2026-04-12"
last_accessed: "2026-04-12"
access_count: 3
related_memories: [MEM-L-020, MEM-DB-002]
also_in: [L2-D7]
generalized: true
version: 1
---

# MEM-L-021 · 大数据量列表 API 必须用 cursor-based 分页，offset 分页在百万级退化

## WHERE（在哪个模块/场景中）

`backend/app/api/v1/` 下所有列表查询接口，尤其是：
- 对象数据列表（Object360 列表视图，可能百万条以上）
- 审计日志列表（无上限增长）
- 数据目录列表（Connector 同步后记录数量大）

## WHAT（发生了什么）

使用 `LIMIT {page_size} OFFSET {(page-1)*page_size}` 时，在第 1000 页（10 万条记录后）
MySQL 需要扫描并跳过 99000 条记录才能返回第 100 条，查询时间从 5ms 退化到 3000ms+。
即使加了索引，`OFFSET` 大值仍需要物理扫描。

## WHY（根本原因）

MySQL 的 `OFFSET` 实现是扫描跳过，不是随机访问。在对象数据表（可能有数百万条）中，
第 N 页的开销是 O(N × page_size)，随页码线性增长。

## HOW（解决方案）

```python
# ✅ Cursor-based 分页（适合大数据量，性能稳定 O(1)）
@router.get("/objects", response_model=ApiResponse[List[ObjectOut]])
async def list_objects(
    ctx: SecurityContext = Depends(get_ctx),
    page_size: int = Query(20, ge=1, le=100),
    cursor: Optional[str] = Query(None),  # base64 编码的 {id, created_at}
):
    items, next_cursor = await object_service.list_cursor(
        ctx, page_size=page_size, cursor=cursor
    )
    return ApiResponse(
        code=200,
        data=items,
        meta={"next_cursor": next_cursor, "has_more": next_cursor is not None},
    )

# Service 层实现（MySQL）
async def list_cursor(self, ctx, page_size, cursor):
    stmt = (
        select(ObjectModel)
        .where(ObjectModel.tenant_id == ctx.tenant_id)
        .order_by(ObjectModel.created_at.desc(), ObjectModel.id.desc())
        .limit(page_size + 1)  # 多取 1 条判断 has_more
    )
    if cursor:
        pivot_id, pivot_ts = self._decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                ObjectModel.created_at < pivot_ts,
                and_(ObjectModel.created_at == pivot_ts,
                     ObjectModel.id < pivot_id)
            )
        )
    rows = (await session.execute(stmt)).scalars().all()
    has_more = len(rows) > page_size
    items = rows[:page_size]
    next_cursor = self._encode_cursor(items[-1]) if has_more else None
    return items, next_cursor

# ⚠️  offset 分页可接受的场景：记录数 < 10 万，且用户不会翻到后几百页
# ✅  管理后台小表（如对象类型列表，通常 < 1000 条）可用 offset
@router.get("/object-types")
async def list_object_types(page: int = 1, page_size: int = 20):
    # 对象类型数量少，offset 可接受
    ...
```

**选型决策树**：
```
预期记录数 < 10万 且 页码 < 100？  → offset 可用
预期记录数 > 10万 或 无限增长？    → cursor-based 必须用
用户需要跳转到特定页？             → offset（搜索结果场景）
用户是下拉加载 / 无限滚动？        → cursor-based
```

## WHEN（触发条件）

- 新增对象数据、审计日志、事件流等无限增长表的列表 API
- 查询 EXPLAIN 显示 `Using filesort` + `rows_examined` 过大
- 前端无限滚动/加载更多场景
