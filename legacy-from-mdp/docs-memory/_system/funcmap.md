# Funcmap — 函数签名索引

> **自动生成** · 2026-04-12 14:41 UTC · 勿手动编辑
> 仅包含有 docstring/JSDoc 注释的公开函数
> 使用 `python3 scripts/mms/funcmap.py` 刷新

---

## 后端函数索引

### 后端 Service 层 (`backend/app/services`)

| 函数 | 文件 | 行号 | 说明 |
|:--|:--|:--|:--|
| `async def execute_action(ctx: RequestContext, action_id: str, object_id: str, ob` | `action_executor_service.py:119` | 119 | Execute an action by ID: validate -> permissions -> run func |
| `async def create_action(ctx: RequestContext, dto: ActionCreateDTO) -> ActionRead` | `action_service.py:25` | 25 | Register a new action definition. |
| `async def get_action(ctx: RequestContext, action_id: str) -> ActionReadDTO` | `action_service.py:200` | 200 | Get a single action definition by ID (RLS: tenant_id). |
| `async def list_actions(ctx: RequestContext) -> List[ActionReadDTO]` | `action_service.py:236` | 236 | List action definitions for the current tenant with optional |
| `async def log(ctx: Optional[SecurityContext]) -> None` | `audit_service.py:43` | 43 | Persist an audit record. |
| `async def authenticate_user(email: str, password: str) -> User` | `auth_service.py:25` | 25 | Authenticate user by email and password. |
| `async def create_token_pair(user: User) -> dict` | `auth_service.py:215` | 215 | Create access + refresh token pair for authenticated user. |
| `async def refresh_access_token(refresh_token: str) -> dict` | `auth_service.py:288` | 288 | Validate a refresh token and issue a new access token pair. |
| `async def list_config(ctx: RequestContext) -> List[dict]` | `config_service.py:115` | 115 | List all config entries (key, value, description, is_hot_rel |
| `async def set_config(ctx: RequestContext, key: str, value: Any, description: Opt` | `config_service.py:146` | 146 | Upsert one config entry. Whitelist + validation + audit (EP- |
| `async def create_connector(ctx: RequestContext, dto: ConnectorCreateDTO) -> Conn` | `datalink_service.py:103` | 103 | Create a Connector with encrypted secrets. |
| `async def get_connector_secrets(ctx: RequestContext, connector_id: str) -> dict` | `datalink_service.py:276` | 276 | Get decrypted secrets for a connector (internal method for W |
| `async def get_sync_job(ctx: RequestContext, job_id: str) -> SyncJobReadDTO` | `datalink_service.py:407` | 407 | Get a SyncJob by ID with RLS enforcement (EP-013). |
| `async def list_sync_job_runs(ctx: RequestContext, job_id: str, limit: int) -> di` | `datalink_service.py:485` | 485 | List run history for a sync job (EP-080, EP-082). |
| `async def get_last_watermark_for_job(ctx: RequestContext, job_id: str) -> Option` | `datalink_service.py:574` | 574 | Get the last successful watermark for a sync job (EP-082 INC |
| `async def get_connector_by_id(ctx: RequestContext, connector_id: str) -> Connect` | `datalink_service.py:607` | 607 | Get a Connector by ID with RLS enforcement (EP-013). |
| `async def test_connection(ctx: RequestContext, dto: ConnectorTestConnectionDTO) ` | `datalink_service.py:676` | 676 | Test connector connectivity without persisting (EP-077). |
| `async def update_connector(ctx: RequestContext, connector_id: str, dto: Connecto` | `datalink_service.py:734` | 734 | Update a Connector (EP-077). RLS by tenant_id; only non-None |
| `async def test_connector(ctx: RequestContext, connector_id: str) -> ConnectorRea` | `datalink_service.py:829` | 829 | Test connector connectivity and update last_tested_at, statu |
| `async def update_sync_job_status(ctx: RequestContext, job_id: str, status: str, ` | `datalink_service.py:901` | 901 | Update SyncJob run status and timestamp; persist run to meta |
| `async def register_mysql_connector(ctx: SecurityContext) -> Dict[str, Any]` | `debezium_service.py:207` | 207 | Register a Debezium MySQL source connector. |
| `async def register_postgres_connector(ctx: SecurityContext) -> Dict[str, Any]` | `debezium_service.py:279` | 279 | Register a Debezium PostgreSQL source connector. |
| `async def list_connectors(ctx: SecurityContext) -> List[str]` | `debezium_service.py:343` | 343 | Return list of all connector names registered in Kafka Conne |
| `async def get_connector(ctx: SecurityContext) -> Dict[str, Any]` | `debezium_service.py:360` | 360 | Return connector config + metadata from Kafka Connect. |
| `async def get_connector_status(ctx: SecurityContext) -> Dict[str, Any]` | `debezium_service.py:385` | 385 | Return connector + task status. |
| `async def delete_connector(ctx: SecurityContext) -> None` | `debezium_service.py:430` | 430 | Delete a Kafka Connect connector (stops CDC capture from the |
| `def build_connector_name(ctx: SecurityContext, connector_id: str, db_type: str) ` | `debezium_service.py:471` | 471 | Return the deterministic Kafka Connect connector name for a  |
| `async def init_upload(self, ctx: RequestContext, original_name: str, content_typ` | `file_service.py:86` | 86 | Initialize a file upload. |
| `async def confirm_upload(self, ctx: RequestContext, file_id: str) -> Dict[str, A` | `file_service.py:183` | 183 | Confirm a file upload and run post-processing. |
| `async def get_download_url(self, ctx: RequestContext, file_id: str) -> Dict[str,` | `file_service.py:331` | 331 | Generate a presigned GET URL for file download. |
| `async def get_file_metadata(self, ctx: RequestContext, file_id: str) -> Dict[str` | `file_service.py:368` | 368 | Get file metadata (RLS-filtered). |
| `async def list_files(self, ctx: RequestContext, category: Optional[FileCategory]` | `file_service.py:383` | 383 | List files for the tenant (RLS). |
| `async def delete_file(self, ctx: RequestContext, file_id: str) -> Dict[str, Any]` | `file_service.py:418` | 418 | Soft-delete a file: mark as DELETED in DB, delete from MinIO |
| `async def cleanup_orphans(self, max_age_hours: Optional[int]) -> Dict[str, Any]` | `file_service.py:464` | 464 | Clean up orphaned files (PENDING status older than TTL). |
| `def register_mvp_functions() -> None` | `function_registry.py:285` | 285 | Register MVP functions by common api_name patterns. Call at  |
| `def execute(self, api_name: str, params: Dict[str, Any]) -> Dict[str, Any]` | `function_registry.py:57` | 57 | Run the function registered under api_name with the given pa |
| `async def create_function(ctx: RequestContext, dto: FunctionCreateDTO) -> Functi` | `function_service.py:23` | 23 | Register a new function definition. |
| `async def list_functions(ctx: RequestContext) -> List[FunctionReadDTO]` | `function_service.py:171` | 171 | List function definitions for the current tenant with option |
| `async def register_asset(self, ctx: RequestContext, urn: str, node_type: NodeTyp` | `lineage_service.py:104` | 104 | Register a new data asset in the lineage graph. |
| `async def connect_assets(self, ctx: RequestContext, source_urn: str, target_urn:` | `lineage_service.py:202` | 202 | Connect two assets and trigger security propagation. |
| `async def register_run(self, ctx: RequestContext, job_id: str, target_node_urn: ` | `lineage_service.py:431` | 431 | Register an execution run for provenance tracking. |
| `async def create_link(ctx: RequestContext, dto: LinkCreateDTO) -> LinkReadDTO` | `link_service.py:28` | 28 | Create a LinkTypeDef with initial version atomically. |
| `async def update_link(ctx: RequestContext, link_id: str, dto: LinkUpdateDTO) -> ` | `link_service.py:253` | 253 | Update link type display_name and/or link_properties. RLS by |
| `async def delete_link(ctx: RequestContext, link_id: str) -> None` | `link_service.py:339` | 339 | Delete a link type definition and its versions. |
| `async def bind_mapping(ctx: RequestContext, object_property_id: str, connector_i` | `mapping_service.py:21` | 21 | Bind a physical table/column to an ObjectProperty (EP-050). |
| `async def send_notification(self, ctx: RequestContext, user_id: str, title: str,` | `notification_service.py:64` | 64 | Create and broadcast a notification. |
| `async def mark_read(self, ctx: RequestContext, notification_id: str) -> Dict[str` | `notification_service.py:142` | 142 | Mark a single notification as read (RLS: tenant + user). |
| `async def mark_all_read(self, ctx: RequestContext) -> Dict[str, Any]` | `notification_service.py:175` | 175 | Mark all notifications as read for the current user (RLS). |
| `async def list_notifications(self, ctx: RequestContext, unread_only: bool, categ` | `notification_service.py:207` | 207 | List notifications for the current user (RLS: tenant + user) |
| `async def get_unread_count(self, ctx: RequestContext) -> int` | `notification_service.py:242` | 242 | Get unread notification count for the current user (RLS). |

### 后端 API 路由 (`backend/app/api/v1`)

| 函数 | 文件 | 行号 | 说明 |
|:--|:--|:--|:--|
| `async def register_action_endpoint(dto: ActionCreateDTO, current_user: CurrentUs` | `actions.py:34` | 34 | Register a new action definition. |
| `async def list_actions_endpoint(target_object_id: Optional[str], current_user: C` | `actions.py:78` | 78 | List action definitions for the current tenant (admin / mana |
| `async def list_actions_menu_endpoint(target_object_id: Optional[str], current_us` | `actions.py:114` | 114 | List lightweight action menu items for the current tenant (E |
| `async def get_action_endpoint(action_id: str, current_user: CurrentUser)` | `actions.py:162` | 162 | Get a single action definition by ID (EP-056). |
| `async def execute_action_endpoint(action_id: str, body: ExecuteActionRequest, cu` | `actions.py:191` | 191 | Execute an action by ID (EP-043-B). |
| `async def get_audit_logs(user: CurrentUser, session: AsyncSession, page: int, pa` | `audit.py:24` | 24 | List audit logs with filters. |
| `async def login(form_data: OAuth2PasswordRequestForm) -> dict` | `auth.py:50` | 50 | Login endpoint (OAuth2 form-data): exchange email/password f |
| `async def token(body: TokenRequestDTO) -> dict` | `auth.py:76` | 76 | Login endpoint (JSON): exchange email/password for access to |
| `async def refresh(body: RefreshRequestDTO) -> dict` | `auth.py:104` | 104 | Refresh endpoint: exchange a valid refresh token for a new t |
| `async def chat_to_app(request: ChatRequest, current_user: CurrentUser, ctx: Requ` | `chat.py:29` | 29 | Chat2App 主接口（架构调整版）. |
| `async def chat_health_check()` | `chat.py:132` | 132 | Chat Service 健康检查. |
| `async def get_config(current_user: CurrentUser)` | `config.py:20` | 20 | List all system config entries (Feature Flags, settings). |
| `async def put_config(body: ConfigItemPut, current_user: CurrentUser)` | `config.py:39` | 39 | Upsert one config entry by key. Requires sys:config:manage p |
| `async def create_connector_endpoint(dto: ConnectorCreateDTO, current_user: Curre` | `datalink.py:65` | 65 | Create a new connector with encrypted secrets. |
| `async def list_connectors_endpoint(current_user: CurrentUser)` | `datalink.py:110` | 110 | List connectors for the current tenant. |
| `async def test_connection_endpoint(dto: ConnectorTestConnectionDTO, current_user` | `datalink.py:184` | 184 | Test connector connectivity without persisting (EP-077). |
| `async def get_connector_endpoint(connector_id: str, current_user: CurrentUser)` | `datalink.py:210` | 210 | Get a connector by ID (EP-076). Secrets are masked. For view |
| `async def update_connector_endpoint(connector_id: str, dto: ConnectorUpdateDTO, ` | `datalink.py:233` | 233 | Update a connector (EP-077). Name, config, secrets optional; |
| `async def delete_connector_endpoint(connector_id: str, current_user: CurrentUser` | `datalink.py:256` | 256 | Delete a connector and its associated sync jobs. |
| `async def test_connector_endpoint(connector_id: str, current_user: CurrentUser)` | `datalink.py:294` | 294 | Test connector connectivity (EP-076). Updates last_tested_at |
| `async def create_sync_job_endpoint(dto: SyncJobCreateDTO, current_user: CurrentU` | `datalink.py:322` | 322 | Create a new sync job associated with a connector. |
| `async def list_sync_jobs_endpoint(current_user: CurrentUser)` | `datalink.py:368` | 368 | List sync jobs for the current tenant. |
| `async def list_sync_job_runs_endpoint(job_id: str, current_user: CurrentUser)` | `datalink.py:419` | 419 | List run history for a sync job (EP-080). |
| `async def get_diagnosis(current_user: CurrentUser)` | `diagnosis.py:175` | 175 | Aggregate system diagnosis (DB + Redis) for ops dashboard (E |
| `async def init_upload(body: InitUploadRequest, user: CurrentUser, session: Async` | `files.py:78` | 78 | Initialize a file upload. Returns a presigned PUT URL for cl |
| `async def confirm_upload(body: ConfirmUploadRequest, user: CurrentUser, session:` | `files.py:105` | 105 | Confirm a file upload. Verifies the file in MinIO, runs viru |
| `async def get_file_metadata(file_id: str, user: CurrentUser, session: AsyncSessi` | `files.py:127` | 127 | Get file metadata by ID (RLS: tenant-scoped). |
| `async def get_download_url(file_id: str, user: CurrentUser, session: AsyncSessio` | `files.py:144` | 144 | Get a presigned download URL for the file (RLS: tenant-scope |
| `async def list_files(user: CurrentUser, session: AsyncSession, category: Optiona` | `files.py:161` | 161 | List files for the current tenant (RLS-filtered). |
| `async def delete_file(file_id: str, user: CurrentUser, session: AsyncSession)` | `files.py:190` | 190 | Soft-delete a file (RLS: tenant-scoped). Deletes from MinIO  |
| `async def trigger_orphan_cleanup(user: CurrentUser, session: AsyncSession, max_a` | `files.py:207` | 207 | Trigger orphan file cleanup (admin operation). |
| `async def register_function_endpoint(dto: FunctionCreateDTO, current_user: Curre` | `functions.py:26` | 26 | Register a new function definition. |
| `async def list_functions_endpoint(is_pure: Optional[bool], current_user: Current` | `functions.py:70` | 70 | List function definitions for the current tenant. |
| `async def get_function_code(function_id: str, current_user: CurrentUser, ctx: Re` | `functions.py:104` | 104 | Get the inline code body of a function (Plan 7.4). |
| `async def update_function_code(function_id: str, payload: dict, current_user: Cu` | `functions.py:133` | 133 | Update the inline code body of a function. EP-083. |
| `async def create_quota(body: CreateQuotaRequest, user: CurrentUser, session: Asy` | `governance.py:55` | 55 | Create a new quota rule for the current tenant. |
| `async def list_quotas(user: CurrentUser, session: AsyncSession, metric_type: Opt` | `governance.py:99` | 99 | List all quota rules for the current tenant (RLS-filtered). |
| `async def update_quota(quota_id: UUID, body: UpdateQuotaRequest, user: CurrentUs` | `governance.py:136` | 136 | Update an existing quota rule. RLS: only the owning tenant c |
| `async def check_usage(metric_type: str, user: CurrentUser, session: AsyncSession` | `governance.py:194` | 194 | Check current usage vs configured quota for a specific metri |
| `async def governance_health()` | `governance.py:241` | 241 | Health check for the governance service. |
| `async def get_usage_stats(user: CurrentUser, session: AsyncSession)` | `governance.py:270` | 270 | Aggregated stats for Monitor dashboard: storage, API calls,  |
| `async def expand_graph(request: GraphExpandRequest, current_user: CurrentUser, c` | `graph.py:29` | 29 | 图谱展开接口. |
| `async def graph_health_check()` | `graph.py:131` | 131 | Graph Service 健康检查. |
| `async def list_workspaces(include_archived: bool, workspace_type: Optional[str],` | `library.py:23` | 23 | List library workspaces for the current tenant (EP-053). |
| `async def register_asset(request: RegisterAssetRequest, current_user: CurrentUse` | `lineage.py:177` | 177 | Register a new data asset in the lineage graph. |
| `async def connect_assets(request: ConnectAssetsRequest, current_user: CurrentUse` | `lineage.py:217` | 217 | Connect two data assets and trigger security marking propaga |
| `async def get_staleness_summary(current_user: CurrentUser, session: AsyncSession` | `lineage.py:262` | 262 | Return list of stale nodes (table/object-level) for Lineage  |
| `async def get_lineage_by_object_type(object_type: str, current_user: CurrentUser` | `lineage.py:290` | 290 | Return upstream catalog lineage for the given object type: t |
| `async def get_lineage_graph(urn: str, direction: Literal['UPSTREAM', 'DOWNSTREAM` | `lineage.py:315` | 315 | Get lineage graph for a given data asset. |
| `async def register_run(request: RegisterRunRequest, current_user: CurrentUser, s` | `lineage.py:363` | 363 | Register an execution run for provenance tracking. |

### 后端 Worker (`backend/app/workers`)

| 函数 | 文件 | 行号 | 说明 |
|:--|:--|:--|:--|
| `def set_metric(self, key: str, value: Any) -> None` | `base.py:201` | 201 | Store an arbitrary metric to be included in result / lineage |
| `async def process_batch(messages: list, text_field: str, embedding_provider: Emb` | `indexing.py:64` | 64 | Process a single batch of Kafka messages: embed + dual-write |
| `async def run_indexing_worker(kafka_bootstrap_servers: Optional[str], kafka_topi` | `indexing.py:299` | 299 | Indexing Worker Main Loop. |
| `async def ingestion_task(job_id: str, tenant_id: str, user_id: str, trace_id: Op` | `ingestion.py:99` | 99 | Main ingestion task: Source → Avro → Kafka. |
| `async def lake_writer_task(job_id: str, tenant_id: str, topic: str, table_name: ` | `lake_writer.py:216` | 216 | Consume Kafka topic and write records to Iceberg table on Mi |
| `async def orphan_cleanup_task(max_age_hours: int \| None) -> dict` | `orphan_cleanup.py:32` | 32 | Execute orphan file cleanup. |
| `def main() -> None` | `orphan_cleanup.py:78` | 78 | Run orphan cleanup as a standalone script. |
| `async def run_scenario_merge_job(job_id: str, scenario_id: str, tenant_id: str, ` | `scenario_merge_worker.py:18` | 18 | Execute scenario merge within JobExecutionScope. |
| `async def run_scheduler_daemon() -> None` | `scheduler_daemon.py:214` | 214 | Entry point for the scheduler daemon. |
| `async def start(self) -> None` | `scheduler_daemon.py:55` | 55 | Initialize resources and enter the main loop. |
| `def is_running(self) -> bool` | `scheduler_engine.py:64` | 64 | Whether the scheduler is actively running (not paused or sto |
| `def start(self) -> None` | `scheduler_engine.py:68` | 68 | Start the APScheduler (idempotent). |
| `def pause(self) -> None` | `scheduler_engine.py:80` | 80 | Pause the scheduler (follower mode). |
| `def shutdown(self) -> None` | `scheduler_engine.py:87` | 87 | Gracefully shut down the scheduler. |
| `async def sync_jobs_from_db(self) -> int` | `scheduler_engine.py:102` | 102 | Query meta_sync_jobs for schedulable jobs and sync into APSc |
| `def get_scheduled_jobs(self) -> list` | `scheduler_engine.py:264` | 264 | Return list of currently scheduled jobs (for monitoring). |
| `def get_active_task_count(self) -> int` | `scheduler_engine.py:277` | 277 | Return number of currently running dispatch tasks. |
| `def to_sql(self, table_name: str) -> str` | `schema_diff.py:65` | 65 | Generate ALTER TABLE SQL for this change. |
| `def is_safe(self) -> bool` | `schema_diff.py:81` | 81 | Check if this change is safe to auto-apply. |
| `def to_sql(self, table_name: str) -> str` | `schema_diff.py:110` | 110 | Generate ADD COLUMNS SQL. |
| `def is_safe(self) -> bool` | `schema_diff.py:117` | 117 | Adding columns is always safe. |
| `def to_sql(self, table_name: str) -> str` | `schema_diff.py:149` | 149 | Generate ALTER COLUMN TYPE SQL. |
| `def is_safe(self) -> bool` | `schema_diff.py:155` | 155 | Check if type promotion is in safe list. |
| `def to_sql(self, table_name: str) -> str` | `schema_diff.py:186` | 186 | Generate DROP NOT NULL SQL. |
| `def is_safe(self) -> bool` | `schema_diff.py:193` | 193 | Relaxing constraints is always safe. |
| `def to_sql(self, table_name: str) -> str` | `schema_diff.py:222` | 222 | Cannot generate SQL for incompatible change. |
| `def is_safe(self) -> bool` | `schema_diff.py:226` | 226 | Always unsafe. |
| `def evolve_table(self, table_name: str, incoming_schema: StructType, schema_poli` | `schema_evolution.py:87` | 87 | Evolve Iceberg table schema based on incoming data and polic |
| `def run_stream_job(job_id: str, kafka_bootstrap_servers: str, kafka_topic: str, ` | `stream_ingestion.py:38` | 38 | Run Spark Structured Streaming job to ingest data from Kafka |
| `def run_stream_job_with_evolution(job_id: str, kafka_bootstrap_servers: str, kaf` | `stream_ingestion.py:228` | 228 | Run Spark Structured Streaming job with Schema Evolution sup |
| `def create_batch_processor(target_table: str, schema_policy: str, job_id: str, p` | `stream_ingestion.py:559` | 559 | Factory function to create batch processor with closure. |
| `def process_batch(batch_df: DataFrame, batch_id: int)` | `stream_ingestion.py:594` | 594 | Process each micro-batch with schema evolution (V2 Optimized |

### 基础设施适配器 (`backend/app/infrastructure`)

| 函数 | 文件 | 行号 | 说明 |
|:--|:--|:--|:--|
| `async def get_redis() -> Redis` | `redis_client.py:15` | 15 | Get async Redis client (singleton pool). |
| `async def close_redis() -> None` | `redis_client.py:31` | 31 | Close Redis connection pool (call on shutdown). |
| `def cached(ttl: int, prefix: str, skip_ctx_arg: bool) -> Callable` | `redis_decorator.py:68` | 68 | Decorator: cache async function result in Redis. |
| `async def get(self, tenant_id: str, request: SearchRequest) -> Optional[SearchRe` | `search_cache.py:124` | 124 | Get cached search result. |
| `async def set(self, tenant_id: str, request: SearchRequest, response: SearchResp` | `search_cache.py:187` | 187 | Cache search result. |
| `async def invalidate(self, tenant_id: str, request: SearchRequest) -> bool` | `search_cache.py:239` | 239 | Invalidate (delete) cached result. |
| `async def clear_tenant(self, tenant_id: str) -> int` | `search_cache.py:278` | 278 | Clear all cached results for a tenant. |
| `async def connect(self) -> None` | `api_adapter.py:109` | 109 | Initialize httpx async client. |
| `async def disconnect(self) -> None` | `api_adapter.py:141` | 141 | Close the httpx client and release resources. |
| `async def read_stream(self, endpoint: str, batch_size: int) -> AsyncGenerator[Li` | `api_adapter.py:148` | 148 | Stream data from a REST API with pagination. |
| `async def test_connection(self) -> bool` | `api_adapter.py:272` | 272 | Test API connectivity by sending a request to the base URL. |
| `def get_capability(connector_type: ConnectorType) -> ConnectorCapability` | `connector_registry.py:159` | 159 | Return the ConnectorCapability for the given ConnectorType. |
| `def create_adapter_from_registry(connector_type: ConnectorType, config: dict, se` | `connector_registry.py:177` | 177 | Instantiate a SourceAdapter for the given connector type usi |
| `def get_supported_sync_modes(connector_type: ConnectorType) -> List[SyncMode]` | `connector_registry.py:205` | 205 | Return the list of SyncMode values supported by the given co |
| `def is_sync_mode_supported(connector_type: ConnectorType, sync_mode: SyncMode) -` | `connector_registry.py:210` | 210 | Return True if the connector type supports the given sync mo |
| `def create_source_adapter(connector_type: ConnectorType, config: dict, secrets: ` | `factory.py:16` | 16 | Create a SourceAdapter for the given connector type (EP-076, |
| `async def connect(self) -> None` | `mysql_adapter.py:94` | 94 | Establish async connection to MySQL. |
| `async def disconnect(self) -> None` | `mysql_adapter.py:122` | 122 | Close the MySQL connection and release resources. |
| `async def read_stream(self, table: str, batch_size: int) -> AsyncGenerator[List[` | `mysql_adapter.py:129` | 129 | Stream rows from a MySQL table in batches using server-side  |
| `async def read_stream_incremental(self, table: str, watermark_column: str, last_` | `mysql_adapter.py:175` | 175 | Stream rows where watermark_column > last_watermark (EP-082  |
| `async def test_connection(self) -> bool` | `mysql_adapter.py:216` | 216 | Test MySQL connectivity by executing SELECT 1. |
| `async def list_tables(self) -> List[str]` | `mysql_adapter.py:235` | 235 | List table names in the current database (EP-050: data catal |
| `async def list_columns(self, table: str) -> List[Dict[str, str]]` | `mysql_adapter.py:253` | 253 | List columns for a table (EP-050: data catalog). |
| `async def fetch_row_by_primary_key(self, table: str, pk_columns: List[str], pk_v` | `mysql_adapter.py:277` | 277 | Fetch a single row by primary key (EP-079 M2-2 ON_DEMAND). |
| `def register_type_handler(python_type: Type, handler: Callable[[Any], Any]) -> N` | `normalizer.py:109` | 109 | Register a converter for a Python type. |
| `def register_type_handlers(mapping: Dict[Type, Callable[[Any], Any]]) -> None` | `normalizer.py:128` | 128 | Bulk-register a dict of {python_type: handler} pairs. |
| `def set_default_normalizer(normalizer: NullSafeNormalizer) -> None` | `normalizer.py:290` | 290 | Replace the module-level singleton normalizer. |
| `def normalize_value(value: Any) -> Any` | `normalizer.py:300` | 300 | Module-level shortcut: normalize a single value using the de |
| `def normalize_record(record: dict) -> dict` | `normalizer.py:305` | 305 | Module-level shortcut: normalize all values in a row dict. |
| `def normalize_value(self, value: Any, field_name: str) -> Any` | `normalizer.py:207` | 207 | Convert a single value to a JSON/Avro-serializable primitive |
| `def normalize_record(self, record: dict) -> dict` | `normalizer.py:278` | 278 | Normalize all values in a row dict, passing field names for  |
| `async def connect(self) -> None` | `postgres_adapter.py:87` | 87 | Establish async connection to PostgreSQL. |
| `async def disconnect(self) -> None` | `postgres_adapter.py:115` | 115 | Close the PostgreSQL connection and release resources. |
| `async def read_stream(self, table: str, batch_size: int) -> AsyncGenerator[List[` | `postgres_adapter.py:122` | 122 | Stream rows from a PostgreSQL table in batches using server- |
| `async def read_stream_incremental(self, table: str, watermark_column: str, last_` | `postgres_adapter.py:177` | 177 | Stream rows where watermark_column > last_watermark (EP-082  |
| `async def list_tables(self) -> List[str]` | `postgres_adapter.py:221` | 221 | List table names in the configured schema (EP-050, EP-080: d |
| `async def list_columns(self, table: str) -> List[Dict[str, str]]` | `postgres_adapter.py:238` | 238 | List columns for a table (EP-050, EP-080: data catalog). |
| `async def test_connection(self) -> bool` | `postgres_adapter.py:267` | 267 | Test PostgreSQL connectivity by executing SELECT 1. |
| `def resolve_connection_config(config: Dict[str, Any]) -> Dict[str, Any]` | `resolve_host.py:18` | 18 | Return a shallow copy of config with host possibly replaced  |
| `async def connect(self) -> None` | `s3_adapter.py:106` | 106 | Initialize aiobotocore S3 client. |
| `async def disconnect(self) -> None` | `s3_adapter.py:134` | 134 | Close the S3 client and release resources. |
| `async def read_stream(self, file_path: str, batch_size: int) -> AsyncGenerator[L` | `s3_adapter.py:142` | 142 | Stream data from an S3 file in batches. |
| `async def test_connection(self) -> bool` | `s3_adapter.py:307` | 307 | Test S3 connectivity by checking bucket access. |
| `async def list_tables(self) -> List[str]` | `s3_adapter.py:325` | 325 | List available "tables" in S3 — i.e., object keys (files) di |
| `async def read_stream_incremental(self, table: str, watermark_column: str, last_` | `s3_adapter.py:361` | 361 | Stream records from S3 files modified after last_watermark ( |
| `async def connect(self) -> None` | `source_adapter.py:58` | 58 | Establish connection to the external data source. |
| `async def disconnect(self) -> None` | `source_adapter.py:63` | 63 | Close the connection and release resources. |
| `async def read_stream(self, table: str, batch_size: int) -> AsyncGenerator[List[` | `source_adapter.py:68` | 68 | Stream data from the source in batches. |
| `async def read_stream_incremental(self, table: str, watermark_column: str, last_` | `source_adapter.py:89` | 89 | Stream rows where watermark_column > last_watermark (EP-082  |
| `async def test_connection(self) -> bool` | `source_adapter.py:115` | 115 | Test connectivity to the external data source. |

---

_本文件由 `scripts/mms/funcmap.py` 自动生成。刷新命令：`python3 scripts/mms/cli.py funcmap`_
