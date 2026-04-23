---
id: MEM-L-012
layer: L3_domain
module: ontology
dimension: ontology
type: lesson
tier: hot
description: "ObjectTypeDef 必须设 primary_key 和 unique_key；缺少这两个字段时 Milvus 检索退化为全量扫描"
tags: [objecttypedef, primary_key, unique_key, index, performance, ontology]
source_ep: EP-109
created_at: "2026-04-12"
last_accessed: "2026-04-12"
access_count: 5
related_memories: [MEM-L-013, AD-003]
also_in: [L2-D7]
generalized: true
related_to:
  - id: "MEM-L-013"
    reason: "ObjectTypeDef 定义主键后，Action 回写时需要用主键定位 sys_object_instances"
  - id: "AD-002"
    reason: "对象查询时必须联合 primary_key + tenant_id 双重过滤"
  - id: "BIZ-001"
    reason: "全域对象类型创建流程中主键/唯一键设计是关键决策点"
cites_files:
  - "backend/app/models/ontology.py"
  - "backend/app/services/control/ontology_service.py"
impacts:
  - "MEM-L-013"
  - "BIZ-001"
version: 1
---

# MEM-L-012 · ObjectTypeDef 必须设置 primary_key + unique_key，否则对象检索退化为全表扫描

## WHERE（在哪个模块/场景中）

`backend/app/domain/ontology/models/object_type_def.py`
以及所有通过 `ObjectTypeService.create_object_type()` 创建对象类型的场景。

## WHAT（发生了什么）

当 `ObjectTypeDef` 缺少 `primary_key` 或 `unique_key` 定义时：
- Object360 页面加载 P99 延迟从 200ms 上升到 3000ms+
- `ObjectQueryService.find_by_id()` 退化为 `SELECT * WHERE tenant_id = ?`（全表扫描）
- Milvus 向量检索结果无法与 MySQL 对象记录做关联（JOIN 无主键）

## WHY（根本原因）

`BaseRepository.get_by_id()` 依赖 `primary_key` 字段名来构造 `WHERE {pk} = ?` 查询。
未设置时回退到 `WHERE id = ?`，但 `id` 在部分对象类型中是复合业务 ID，不是数据库主键，
导致全表扫描。

`unique_key` 缺失会使 Milvus 无法建立 primary_field，向量检索返回空结果。

## HOW（解决方案）

```python
# ✅ 正确：创建 ObjectTypeDef 时必须显式设置
object_type = ObjectTypeDef(
    name="Company",
    primary_key="company_id",          # 数据库主键字段名
    unique_key="unified_social_code",  # 业务唯一标识（用于 Milvus primary_field）
    display_name="企业",
    ...
)

# ❌ 错误：依赖框架推断（不可靠）
object_type = ObjectTypeDef(name="Company", ...)
```

**检查清单**（每次新建对象类型时）：
1. `primary_key` → 数据库物理主键字段名
2. `unique_key` → 业务唯一标识（通常是证件号、编码等）
3. 确认对应 MySQL 表有 `INDEX(unique_key)`
4. 确认 Milvus Collection 的 `primary_field` = `unique_key`

## WHEN（触发条件）

- 新增 ObjectTypeDef 时未配置索引字段
- 从旧系统迁移对象类型，未检查字段映射
- 单元测试用 Mock 对象时省略了这两个字段导致集成测试漏检
