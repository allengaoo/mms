# Phase 4 — Memoria 双写迁移

> 分支：`feature/memoria-dualwrite`
> 预估：3–5 人周 · 前置依赖：Phase 0.2 决策门 **Go** + Phase 1（端口）+ Phase 2（索引统一）
> 目标：Memoria 作为第二后端接入双写与影子读，用生产流量验证其可靠性，**全程 Markdown 仍是主后端，任何时刻可一键退回。**

> **状态：停止（2026-07-14）。** 稳定版复测虽通过版本控制流程，但任意本体 metadata 仍为 0/20，LinkType 无原生精确查询能力，未满足本阶段的 Phase 0.2 Go 前置条件。本文件保留为未来能力变化后的候选计划，本轮不实施。

---

## 任务 4.1 MemoriaRepository 适配器

### 工作内容

1. 新建 `src/mms/adapters/memoria_repo.py`，实现 Phase 1 定义的 `MemoryRepository` 端口，内部封装 Memoria REST 客户端：
   - 连接配置从 `config.yaml` 读取（`memory.memoria.base_url` / `api_key` / `project_id` / `timeout`）；
   - **客户端侧字段校验**（应对 Memoria 已知的输入验证薄弱）：写入前校验 `MemoryRecord` 必填字段、layer 枚举、ObjectType 枚举，非法输入在客户端拒绝并给出明确错误；
   - 重试策略：网络错误指数退避重试 3 次，仍失败抛 `MemoriaUnavailableError`；
   - 依赖锁定：Memoria 客户端/镜像版本写死在 `pyproject.toml` 与 compose 文件，升级必须走独立 PR。
2. 按 Phase 0.2 报告选定的 LinkType 表示方案实现边的读写（metadata 数组或旁路记录，以 PoC 结论为准，在本文件动工前补充决定）。

### 涉及文件

| 文件 | 操作 |
|---|---|
| `src/mms/adapters/memoria_repo.py` | 新建 |
| `src/mms/adapters/memoria_client.py` | 新建：REST 封装 + 校验 + 重试 |
| `docs/memory/_system/config.yaml` | 修改：`memory.memoria.*` 配置段 |
| `src/mms/utils/mms_config.py` | 修改：新配置属性 |
| `pyproject.toml` | 修改：可选依赖分组 `memoria`（HTTP 客户端等） |
| `deploy/memoria/docker-compose.yml` | 新建（从 spike 转正，锁版本） |
| `tests/test_memoria_repo.py` | 新建：单测（mock HTTP） |
| `tests/integration/test_memoria_live.py` | 新建：live 集成测试（需本机 OrbStack，CI 中按 label 触发） |

### 达到的标准

- `MemoriaRepository` 通过 Phase 1 的**同一套契约测试**（`tests/test_ports_contract.py` 新增一个 fixture 参数即可挂载，无需改断言）；
- 非法输入（错误 layer、缺 ID、超长字段）100% 在客户端被拒绝，不落入 Memoria；
- Memoria 不可用时抛出明确异常，不静默吞错。

### 如何验证

```bash
pytest tests/test_memoria_repo.py tests/test_ports_contract.py -v          # mock 层
docker compose -f deploy/memoria/docker-compose.yml up -d
pytest tests/integration/test_memoria_live.py -v                            # live 层
```

---

## 任务 4.2 OntologyProjection 的 Memoria 实现

### 工作内容

新建 `MemoriaProjection`：`MemoryRecord` ↔ Memoria 记录的映射，front-matter 全字段（`object_type`、`layer`、`tier`、`related_to`、`cites_files`、`about_concepts`、`contradicts`、`derived_from`、provenance、version）进 metadata；正文进 content。序列化规则以 Phase 0.2 往返测试固化的格式为准。**动态本体（ObjectType/LinkType schema 校验、类型化遍历）仍在木兰侧，Memoria 只见序列化后的 metadata——不允许 schema 概念泄漏进 adapter 之外的代码。**

### 涉及文件

| 文件 | 操作 |
|---|---|
| `src/mms/adapters/memoria_projection.py` | 新建 |
| `tests/test_memoria_projection.py` | 新建：全字段往返测试 |

### 达到的标准

- 对 `docs/memory/shared/` 全部真实节点：`from_record(to_record(x)) == x`（逐字段相等）；
- `src/mms/memory/`、`src/mms/ontology/` 中无任何 import Memoria 相关模块（边界检查）。

### 如何验证

- `pytest tests/test_memoria_projection.py -v`（参数化遍历全部真实节点）；
- `rg -l "memoria" src/mms/memory src/mms/ontology`（期望无输出）。

---

## 任务 4.3 CompositeRepository 双写

### 工作内容

1. 新建 `src/mms/adapters/composite_repo.py`：
   - 写路径：主写 Markdown（同步、失败即报错）→ 副写 Memoria（失败不阻塞主流程，写入重试队列 `docs/memory/_system/memoria_retry_queue.jsonl`）；
   - 读路径：默认读 Markdown（主后端）；
   - `flush_retry_queue()`：重放队列，供 CLI 和定时任务调用。
2. `get_repository()` 工厂支持 `memory.backend: dual`；
3. 全量初始迁移脚本 `scripts/migrate_to_memoria.py`：把现有全部节点导入 Memoria（幂等，按 ID upsert），作为双写起点。

### 涉及文件

| 文件 | 操作 |
|---|---|
| `src/mms/adapters/composite_repo.py` | 新建 |
| `src/mms/adapters/__init__.py` | 修改：工厂支持 `dual` |
| `scripts/migrate_to_memoria.py` | 新建 |
| `src/mms/cli.py` | 修改：`mulan memory retry-queue` 子命令 |
| `tests/test_composite_repo.py` | 新建：含副写故障注入测试 |

### 达到的标准

- Memoria 完全宕机时，所有写操作照常成功（主后端不受影响），失败副写全部进入队列；恢复后 `flush_retry_queue()` 清空队列且数据一致；
- 迁移脚本幂等：连续执行两次，Memoria 侧节点数与内容不变。

### 如何验证

- `tests/test_composite_repo.py`：mock Memoria 抛错，断言主写成功 + 队列条目正确；恢复后 flush 断言一致；
- live 演练：`docker compose stop memoria` → 执行一次 bootstrap → `start` → flush → 对账零差异。

---

## 任务 4.4 对账与影子读

### 工作内容

1. **对账脚本** `scripts/reconcile_memoria.py`：遍历两后端全部节点，比对 ID 集合与逐字段内容，差异输出到 `docs/memory/_system/reconcile_report.jsonl`；支持 `--fix`（以 Markdown 为准修复 Memoria）；
2. **影子读**：`CompositeRepository` 增加 `shadow_read: true` 配置——`query()` 同时打两个后端，以 Markdown 结果返回调用方，异步比对两侧结果差异（ID 集合、排序）记入 `docs/memory/_system/shadow_read_diff.jsonl`；
3. **检索质量对比**：Phase 0 固定查询集在 Memoria 检索路径下重跑，与基线对比召回与延迟。

### 涉及文件

| 文件 | 操作 |
|---|---|
| `scripts/reconcile_memoria.py` | 新建 |
| `src/mms/adapters/composite_repo.py` | 修改：影子读 |
| `docs/memory/_system/config.yaml` | 修改：`shadow_read` 开关 |
| `tests/test_reconcile.py` | 新建 |

### 达到的标准（Phase 5 的准入指标）

- 日常使用（真实 bootstrap + dream + promote + GC 流程各若干次）下，连续 **14 天**对账零差异；
- 影子读一致率 > 99%（差异日志中不一致条目 / 总查询数）；
- Memoria 检索召回 ≥ Markdown 基线，P95 延迟 < 500ms。

### 如何验证

```bash
python scripts/reconcile_memoria.py            # 退出码 0 = 零差异
jq -s 'length' docs/memory/_system/shadow_read_diff.jsonl   # 统计差异条目
python scripts/benchmark_baseline.py --compare-retrieval --backend memoria
```

---

## 任务 4.5 VersionStore 实现与 CLI

### 工作内容

1. 新建 `src/mms/adapters/memoria_version_store.py`：用 Memoria 的 snapshot/branch/merge/rollback 实现 Phase 1 的 `VersionStore` 端口；
2. CLI 子命令：`mulan memory snapshot <label>` / `branch <name>` / `merge <src>` / `rollback <ref>` / `history <memory_id>`；
3. rollback 与 Markdown 主后端的一致性策略：双写期 rollback 仅作用于 Memoria 侧做演练验证，**不反向覆盖 Markdown**（正式启用在 Phase 5 切主之后）；CLI 输出明确提示。

### 涉及文件

| 文件 | 操作 |
|---|---|
| `src/mms/adapters/memoria_version_store.py` | 新建 |
| `src/mms/cli.py` | 修改：memory 子命令组 |
| `tests/integration/test_version_store_live.py` | 新建 |

### 达到的标准

- snapshot → 修改 → rollback 后，Memoria 侧节点内容、metadata、边关系与快照点完全一致；
- branch/merge 演练（对齐 Phase 0.2 的流程）在真实数据规模下通过。

### 如何验证

- `pytest tests/integration/test_version_store_live.py -v`（需本机 Memoria 运行）；
- 演练记录（含数据规模、耗时）附在 PR 描述。

---

## Phase 4 整体验收

- [ ] 契约测试三实现（Markdown / Memoria / Composite）全绿；
- [ ] 14 天对账零差异 + 影子读一致率 > 99% + 检索指标达标（数据留档 `docs/plans/modernization/phase4_metrics.md`）；
- [ ] 故障演练通过：Memoria 宕机不影响主流程，恢复后队列自愈；
- [ ] 回退方案：`memory.backend: markdown` 一键回退，Memoria 数据保留不删。
