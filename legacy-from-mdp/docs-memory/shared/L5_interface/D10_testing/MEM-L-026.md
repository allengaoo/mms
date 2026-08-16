---
id: MEM-L-026
layer: L5_interface
module: testing
dimension: D10
type: lesson
tier: hot
description: "后端测试数据用 Polyfactory 工厂生成；断言用 dirty-equals 做模糊匹配；禁止在测试中手写大量 fixture"
tags: [testing, polyfactory, dirty-equals, pytest, mock, backend, test-data]
source_ep: EP-110
created_at: "2026-04-12"
last_accessed: "2026-04-12"
access_count: 3
related_memories: [MEM-L-027, MEM-L-001]
also_in: []
generalized: true
version: 1
---

# MEM-L-026 · 后端测试用 Polyfactory 生成测试数据，`dirty-equals` 做模糊断言

## WHERE（在哪个模块/场景中）

`backend/tests/` 下所有单元测试和集成测试。
`backend/tests/factories/` — Polyfactory 工厂类存放位置。

## WHAT（发生了什么）

手写 Mock dict 作为测试数据时：
1. 字段变更（如新增必填字段）时，所有手写 Mock 需要逐个更新（维护成本高）
2. 测试数据不满足 Pydantic 约束（如 `email` 格式、`uuid` 格式），导致假阴性
3. 精确断言（`assert result.name == "exact_string"`）在字段顺序、时间戳等可变字段上频繁失败

## WHY（根本原因）

手写 Mock 是静态的，无法感知 Schema 变化。`Polyfactory` 基于 Pydantic 模型自动生成合法的测试数据，
Schema 变更后工厂类自动适应，无需手动同步。

`dirty-equals` 提供语义化的模糊断言（如"任意 UUID"、"任意非空字符串"），
避免精确值断言在动态字段（时间戳、自动生成 ID）上的脆弱性。

## HOW（解决方案）

```python
# ✅ 正确：Polyfactory 工厂类 + dirty-equals 断言

# backend/tests/factories/ontology.py
from polyfactory.factories.pydantic_factory import ModelFactory
from app.domain.ontology.schemas import ObjectTypeCreate, ObjectTypeOut

class ObjectTypeCreateFactory(ModelFactory):
    __model__ = ObjectTypeCreate
    # 可以覆盖特定字段
    name = "TestObjectType"  # 固定值（便于查找）
    # 未覆盖的字段由 Polyfactory 自动生成合法值

class ObjectTypeOutFactory(ModelFactory):
    __model__ = ObjectTypeOut

# backend/tests/unit/test_object_type_service.py
from dirty_equals import IsUUID, IsDatetime, IsStr, HasLen
from tests.factories.ontology import ObjectTypeCreateFactory, ObjectTypeOutFactory

async def test_create_object_type(mock_repo, mock_audit):
    body = ObjectTypeCreateFactory.build()  # 生成合法的 ObjectTypeCreate 实例

    result = await object_type_service.create(ctx=mock_ctx, body=body)

    # ✅ 模糊断言：不关心具体值，只关心类型和结构
    assert result == {
        "id":          IsUUID(),           # 任意合法 UUID
        "name":        body.name,           # 这个我们关心
        "created_at":  IsDatetime(),        # 任意合法时间戳
        "tenant_id":   mock_ctx.tenant_id, # 这个必须精确匹配
        "properties":  HasLen(0),           # 新创建时属性为空
    }

# ❌ 错误：手写 Mock dict（脆弱）
async def test_create_object_type():
    body = {
        "name": "Company",
        "display_name": "企业",
        # 🚨 忘记写新增的必填字段 primary_key → 测试不合法
    }
    result = await service.create(ctx=mock_ctx, body=body)
    assert result["id"] == "some-fixed-uuid"  # 🚨 时间戳每次不同，精确断言会失败
```

**Testcontainers 集成测试**（需要真实 MySQL）：
```python
# backend/tests/integration/conftest.py
from testcontainers.mysql import MySqlContainer

@pytest.fixture(scope="session")
def mysql_container():
    with MySqlContainer("mysql:8.0") as mysql:
        yield mysql  # 测试完自动销毁

# 集成测试用工厂类 + 真实 DB
async def test_create_and_fetch(async_session, mysql_container):
    body = ObjectTypeCreateFactory.build()
    created = await service.create(ctx=mock_ctx, body=body)
    fetched = await service.get(ctx=mock_ctx, id=created.id)
    assert fetched.name == body.name
```

**覆盖率要求**：Service 层 ≥ 85%，Repository 层集成测试覆盖所有 CRUD 操作。

## WHEN（触发条件）

- 新增 Service 方法时（同步编写测试）
- 测试数据维护成本过高时（超过 50 行手写 Mock）
- 精确断言在 CI 中偶发性失败时（时间戳、UUID 等动态字段）
