---
id: MEM-L-017
layer: L3_domain
module: data_pipeline
dimension: data_pipeline
type: lesson
tier: warm
tags: [data-catalog, column-mapping, auto-mode, schema-drift, sync-strategy, data-pipeline]
source_ep: EP-109
created_at: "2026-04-12"
last_accessed: "2026-04-12"
access_count: 2
related_memories: [MEM-L-015, MEM-L-016]
also_in: []
generalized: true
version: 1
---

# MEM-L-017 · DataCatalog 列映射支持三种策略，auto 模式列名变更会静默断开映射

## WHERE（在哪个模块/场景中）

`backend/app/domain/data_pipeline/services/data_catalog_service.py`
`DataCatalog` 的 `sync_schema()` 和 `apply_mapping()` 方法。

## WHAT（发生了什么）

使用 `auto` 映射策略时，源数据库发生 Schema 变更（如列名从 `company_name` 改为 `corp_name`），
DataCatalog 会**静默断开**该列的映射关系，不抛出异常，不发告警。
后续的 SyncJob 仍然成功运行，但该列数据全部丢失（写入 `null`）。

## WHY（根本原因）

三种映射策略的行为差异：

| 策略 | 列名变更时行为 | 新增列时行为 | 适用场景 |
|:---|:---|:---|:---|
| `auto` | **静默断开映射** | 自动建立映射 | 数据探索（不推荐生产）|
| `manual` | 报错，阻止同步 | 忽略，不映射 | 生产环境稳定字段 |
| `hybrid` | 报错，发告警 | 自动建立映射 | **推荐：生产环境** |

`auto` 模式设计用于快速探索，不适合生产环境中对数据完整性有要求的场景。

## HOW（解决方案）

```python
# ✅ 正确：生产环境使用 hybrid 策略 + 开启 drift_alert
catalog = DataCatalog(
    connector_id=connector_id,
    mapping_strategy=MappingStrategy.HYBRID,  # 列名变更 → 报错+告警
    drift_alert=True,                          # Schema 漂移时发 DingTalk 告警
    drift_action=DriftAction.BLOCK,            # 漂移时阻止 SyncJob 运行
)

# auto 模式只用于数据探索阶段（Connector 初始化时）
catalog_explore = DataCatalog(
    connector_id=connector_id,
    mapping_strategy=MappingStrategy.AUTO,    # 仅探索用
    # 📌 探索完成后必须切换为 manual 或 hybrid
)

# ❌ 错误：生产环境用 auto 模式，Schema 变更时静默丢数据
catalog_prod = DataCatalog(
    connector_id=connector_id,
    mapping_strategy=MappingStrategy.AUTO,  # 🚨 列名变更会静默断开映射
)
```

**告警配置**（`SystemConfig`）：
```python
CATALOG_DRIFT_ALERT_WEBHOOK = "https://oapi.dingtalk.com/robot/send?..."
CATALOG_DRIFT_BLOCK_THRESHOLD = 1  # 任意列漂移即阻止同步
```

## WHEN（触发条件）

- 新建 DataCatalog 配置（**生产环境必须选 hybrid**）
- 源数据库做 DDL 变更（列改名/删列）前，检查 DataCatalog 漂移策略
- SyncJob 运行后发现某字段全为 null（可能是静默断开的表现）
