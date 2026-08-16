# Codemap — 项目目录快照

> **自动生成** · 2026-04-12 14:36 UTC · 勿手动编辑
> 使用 `python3 scripts/mms/codemap.py` 刷新

---

## 后端应用层 (`backend/app`)

```
backend/app/
├── api/
│   ├── schemas/
│   │   ├── action.py
│   │   ├── chat.py
│   │   ├── config.py
│   │   ├── datalink.py
│   │   ├── diagnosis.py
│   │   ├── file.py
│   │   ├── function.py
│   │   ├── governance.py
│   │   ├── graph.py
│   │   ├── link.py
│   │   ├── mapping.py
│   │   ├── notification.py
│   │   ├── object_instance.py
│   │   ├── ontology.py
│   │   ├── processing.py
│   │   ├── role.py
│   │   ├── scenario.py
│   │   ├── search.py
│   │   └── user.py
│   ├── v1/
│   │   ├── endpoints/
│   │   └── __init__.py
│   └── __init__.py
├── core/
│   ├── utils/
│   │   ├── __init__.py
│   │   └── urn.py
│   ├── __init__.py
│   ├── auth.py
│   ├── config.py
│   ├── context.py
│   ├── db.py
│   ├── encryption.py
│   ├── exceptions.py
│   ├── logger.py
│   ├── rbac.py
│   ├── resilience.py
│   ├── response.py
│   ├── security.py
│   └── telemetry.py
├── domain/
│   ├── dto/
│   │   ├── __init__.py
│   │   └── action.py
│   └── ports/
│       ├── __init__.py
│       └── graph_port.py
├── infrastructure/
│   ├── cache/
│   │   ├── __init__.py
│   │   ├── redis_client.py
│   │   ├── redis_decorator.py
│   │   └── search_cache.py
│   ├── connector/
│   │   ├── __init__.py
│   │   ├── api_adapter.py
│   │   ├── connector_registry.py
│   │   ├── factory.py
│   │   ├── mysql_adapter.py
│   │   ├── normalizer.py
│   │   ├── postgres_adapter.py
│   │   ├── resolve_host.py
│   │   ├── s3_adapter.py
│   │   └── source_adapter.py
│   ├── consensus/
│   │   ├── __init__.py
│   │   └── leader_election.py
│   ├── db/
│   │   └── __init__.py
│   ├── graph/
│   │   ├── __init__.py
│   │   └── mysql_graph_adapter.py
│   ├── lake/
│   │   ├── README.md
│   │   ├── __init__.py
│   │   ├── iceberg_ops.py
│   │   ├── pyiceberg_adapter.py
│   │   ├── schema_registry.py
│   │   └── spark_factory.py
│   ├── llm/
│   │   ├── __init__.py
│   │   └── client.py
│   ├── model/
│   │   ├── __init__.py
│   │   └── embedding.py
│   ├── mq/
│   │   ├── __init__.py
│   │   └── kafka_producer.py
│   ├── realtime/
│   │   ├── __init__.py
│   │   └── broadcaster.py
│   ├── repositories/
│   │   ├── __init__.py
│   │   └── lineage_repository.py
│   ├── search/
│   │   ├── __init__.py
│   │   └── es_adapter.py
│   ├── security/
│   │   ├── __init__.py
│   │   └── virus_scanner.py
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── minio_adapter.py
│   │   └── thumbnail_service.py
│   ├── vector/
│   │   ├── __init__.py
│   │   └── milvus_adapter.py
│   ├── writeback/
│   │   ├── __init__.py
│   │   └── source_db_writeback.py
│   └── __init__.py
├── models/
│   ├── __init__.py
│   ├── action.py
│   ├── audit.py
│   ├── datalink.py
│   ├── file.py
│   ├── function.py
│   ├── governance.py
│   ├── lineage.py
│   ├── link.py
│   ├── notification.py
│   ├── ontology.py
│   ├── simulation.py
│   └── system.py
├── services/
│   ├── control/
│   │   ├── __init__.py
│   │   ├── action_executor_service.py
│   │   ├── action_service.py
│   │   ├── audit_service.py
│   │   ├── auth_service.py
│   │   ├── config_service.py
│   │   ├── datalink_service.py
│   │   ├── debezium_service.py
│   │   ├── file_service.py
│   │   ├── function_registry.py
│   │   ├── function_service.py
│   │   ├── lineage_service.py
│   │   ├── link_service.py
│   │   ├── mapping_service.py
│   │   ├── notification_service.py
│   │   ├── ontology_service.py
│   │   ├── ontology_srv.py
│   │   ├── role_service.py
│   │   ├── scenario_service.py
│   │   ├── shared_property_service.py
│   │   ├── transaction_srv.py
│   │   ├── usage_service.py
│   │   └── user_service.py
│   ├── dispatch/
│   │   ├── __init__.py
│   │   └── job_dispatcher.py
│   ├── query/
│   │   ├── __init__.py
│   │   ├── action_query_service.py
│   │   ├── audit_query_service.py
│   │   ├── chat_service.py
│   │   ├── graph_service.py
│   │   ├── lineage_query_service.py
│   │   ├── mapping_catalog_service.py
│   │   ├── object_instance_query_service.py
│   │   ├── ontology_query_service.py
│   │   ├── overlay_engine.py
│   │   ├── quota_enforcer.py
│   │   ├── ranker.py
│   │   ├── schema_retriever.py
│   │   ├── search_service.py
│   │   ├── search_srv.py
│   │   └── ui_injector.py
│   └── __init__.py
├── utils/
│   ├── __init__.py
│   └── retry.py
├── workers/
│   ├── spark/
│   │   ├── __init__.py
│   │   ├── schema_diff.py
│   │   ├── schema_evolution.py
│   │   └── stream_ingestion.py
│   ├── __init__.py
│   ├── base.py
│   ├── compaction.py
│   ├── indexing.py
│   ├── ingestion.py
│   ├── lake_writer.py
│   ├── metadata_sync.py
│   ├── orphan_cleanup.py
│   ├── scenario_merge_worker.py
│   ├── scheduler_daemon.py
│   └── scheduler_engine.py
├── initial_data.py
└── main.py
```

## 前端源码 (`frontend/src`)

```
frontend/src/
├── components/
│   ├── AmisRenderer/
│   │   └── index.tsx
│   ├── ErrorBoundary/
│   │   ├── __tests__/
│   │   └── index.tsx
│   ├── CommonIcon.tsx
│   ├── ObjectDetailDrawer.tsx
│   └── PermissionGate.tsx
├── config/
│   ├── navigation.ts
│   ├── queryClient.ts
│   └── theme.ts
├── constants/
│   └── propertyConstraints.ts
├── hooks/
├── layouts/
│   ├── __tests__/
│   │   └── MainLayout.test.tsx
│   ├── components/
│   │   ├── __tests__/
│   │   ├── NotificationBell.tsx
│   │   └── SimulationBanner.tsx
│   └── MainLayout.tsx
├── pages/
│   ├── Dashboard/
│   │   ├── __tests__/
│   │   └── index.tsx
│   ├── Debug/
│   │   └── CrashTest.tsx
│   ├── auth/
│   │   ├── __tests__/
│   │   └── Login.tsx
│   ├── datalink/
│   │   ├── ConnectorList/
│   │   ├── Mappings/
│   │   ├── SyncJobDetail/
│   │   └── SyncJobList/
│   ├── explorer/
│   │   ├── Chat/
│   │   ├── Graph/
│   │   ├── Object360/
│   │   ├── Scenarios/
│   │   └── Search/
│   ├── ontology/
│   │   ├── Library/
│   │   ├── LinkList/
│   │   ├── LogicList/
│   │   ├── ObjectList/
│   │   └── PropertyList/
│   ├── ops/
│   │   ├── AuditLog/
│   │   ├── Config/
│   │   ├── Developer/
│   │   ├── Diagnosis/
│   │   ├── Monitor/
│   │   ├── NotificationList/
│   │   ├── Roles/
│   │   └── UserList/
│   ├── processing/
│   │   ├── Health/
│   │   └── Lineage/
│   ├── profile/
│   │   └── Profile.tsx
│   ├── ComingSoon.tsx
│   └── NotFound.tsx
├── providers/
│   └── AppProvider.tsx
├── routes/
│   ├── __tests__/
│   │   └── guards.test.tsx
│   ├── guards.tsx
│   └── index.tsx
├── services/
│   ├── __tests__/
│   │   ├── audit.test.ts
│   │   ├── auth.test.ts
│   │   ├── chat.test.ts
│   │   ├── datalink.test.ts
│   │   ├── graph.test.ts
│   │   ├── link.test.ts
│   │   ├── monitor.test.ts
│   │   ├── ontology.test.ts
│   │   ├── role.test.ts
│   │   ├── search.test.ts
│   │   └── user.test.ts
│   ├── action.ts
│   ├── audit.ts
│   ├── auth.ts
│   ├── chat.ts
│   ├── config.ts
│   ├── datalink.ts
│   ├── diagnosis.ts
│   ├── graph.ts
│   ├── library.ts
│   ├── lineage.ts
│   ├── link.ts
│   ├── logic.ts
│   ├── mapping.ts
│   ├── monitor.ts
│   ├── notification.ts
│   ├── object360.ts
│   ├── ontology.ts
│   ├── processing.ts
│   ├── property.ts
│   ├── role.ts
│   ├── search.ts
│   ├── simulation.ts
│   └── user.ts
├── store/
│   ├── __tests__/
│   │   ├── notificationStore.test.ts
│   │   ├── simulationStore.test.ts
│   │   └── userStore.test.ts
│   ├── notificationStore.ts
│   ├── simulationStore.ts
│   └── userStore.ts
├── styles/
│   └── global.css
├── test/
│   ├── fixtures/
│   │   └── scenarios/
│   ├── mocks/
│   │   ├── data.ts
│   │   ├── handlers.ts
│   │   ├── monaco.ts
│   │   └── server.ts
│   ├── setup.ts
│   └── utils.tsx
├── types/
│   ├── action.ts
│   ├── chat.ts
│   ├── datalink.ts
│   ├── governance.ts
│   ├── graph.ts
│   ├── lineage.ts
│   ├── link.ts
│   ├── logic.ts
│   ├── notification.ts
│   ├── object360.ts
│   ├── ontology.ts
│   ├── processing.ts
│   ├── property.ts
│   ├── search.ts
│   └── simulation.ts
├── utils/
│   ├── __tests__/
│   │   ├── graphTransformer.test.ts
│   │   ├── logger.test.ts
│   │   └── request.test.ts
│   ├── graphTransformer.ts
│   ├── logger.ts
│   ├── mapper.ts
│   └── request.ts
├── App.tsx
├── main.tsx
└── vite-env.d.ts
```

## MMS 记忆系统脚本 (`scripts/mms`)

```
scripts/mms/
├── core/
│   ├── __init__.py
│   ├── indexer.py
│   ├── reader.py
│   └── writer.py
├── observability/
│   ├── __init__.py
│   ├── audit.py
│   └── tracer.py
├── providers/
│   ├── __init__.py
│   ├── base.py
│   ├── claude.py
│   ├── factory.py
│   └── ollama.py
├── resilience/
│   ├── __init__.py
│   ├── checkpoint.py
│   ├── circuit_breaker.py
│   └── retry.py
├── __init__.py
├── arch_check.py
├── ci_hook.py
├── cli.py
├── codemap.py
├── doc_drift.py
├── entropy_scan.py
├── injector.py
├── private.py
├── router.py
├── validate.py
└── verify.py
```

## 共享记忆库 (`docs/memory/shared`)

```
docs/memory/shared/
├── L1_platform/
│   ├── D1_security/
│   ├── D3_observability/
│   │   └── MEM-L-009.md
│   └── config/
├── L2_infrastructure/
│   ├── D4_resilience/
│   │   ├── MEM-L-001.md
│   │   └── MEM-L-003.md
│   ├── D5_distributed/
│   ├── D6_messaging/
│   │   ├── MEM-L-002.md
│   │   ├── MEM-L-006.md
│   │   ├── MEM-L-010.md
│   │   └── MEM-L-011.md
│   ├── D7_cache/
│   ├── D9_database/
│   │   └── MEM-DB-002.md
│   └── storage/
│       └── MEM-L-007.md
├── L3_domain/
│   ├── data_pipeline/
│   │   ├── MEM-L-015.md
│   │   ├── MEM-L-016.md
│   │   └── MEM-L-017.md
│   ├── governance/
│   │   ├── MEM-L-018.md
│   │   └── MEM-L-019.md
│   ├── ontology/
│   │   ├── MEM-L-012.md
│   │   ├── MEM-L-013.md
│   │   └── MEM-L-014.md
│   └── simulation/
├── L4_application/
│   ├── D2_architecture/
│   └── workers/
│       ├── MEM-L-004.md
│       ├── MEM-L-005.md
│       └── MEM-L-008.md
├── L5_interface/
│   ├── D10_testing/
│   │   ├── MEM-L-026.md
│   │   └── MEM-L-027.md
│   ├── D8_api/
│   │   ├── MEM-L-020.md
│   │   ├── MEM-L-021.md
│   │   └── MEM-L-022.md
│   ├── D8_api_standards/
│   └── frontend/
│       ├── MEM-L-023.md
│       ├── MEM-L-024.md
│       └── MEM-L-025.md
├── cross_cutting/
│   ├── decisions/
│   │   ├── AD-001.md
│   │   ├── AD-002.md
│   │   ├── AD-003.md
│   │   ├── AD-004.md
│   │   ├── AD-005.md
│   │   ├── AD-006.md
│   │   ├── AD-007.md
│   │   └── AD-008.md
│   └── patterns/
└── evolution/
    └── skills/
```

## 架构文档 (`docs/architecture`)

```
docs/architecture/
├── ARCHITECTURE_CHANGELOG.md
├── e2e_traceability.md
├── frontend_architecture.md
├── frontend_page_map.md
├── k8s_service_dependencies.md
├── master_architecture.md
├── metadata_er_diagram.md
├── runtime_migration_and_deploy_steps.md
└── tech_stack.md
```

---

## 最近修改文件（最近 5 个）

- `scripts/mms/cli.py` — 2026-04-12 14:35
- `scripts/mms/codemap.py` — 2026-04-12 14:35
- `scripts/mms/entropy_scan.py` — 2026-04-12 14:33
- `scripts/mms/doc_drift.py` — 2026-04-12 14:32
- `scripts/mms/arch_check.py` — 2026-04-12 14:31

---

_本文件由 `scripts/mms/codemap.py` 自动生成，请勿手动编辑。刷新命令：`python3 scripts/mms/cli.py codemap`_
