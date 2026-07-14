# Phase 2 — 内部断层修复

> 分支：`feature/index-unification`
> 预估：1–2 人周 · 前置依赖：Phase 1（Repository 已就位）
> 目标：修复双索引、索引结构过时、GC 未闭环、全量扫描四个既有断层。**即使不上 Memoria，本阶段也直接改善系统一致性与性能。**

---

## 实施状态（2026-07-14）

- [x] `MEMORY_INDEX.json` 已升级为 Schema v5.0：Universal Layer 一级节点、ObjectType 二级节点；
- [x] 新增幂等迁移脚本 `scripts/migrate_index_v5.py`，真实仓库当前索引 5 个 active shared 节点；
- [x] Injector 与 Postcheck 已切到唯一索引，`src/` 对 `_system/memory_index.json` 的读取引用为 0；
- [x] MarkdownRepository 已接通 put/delete/update_stats 写后索引钩子，新增与更新均为 upsert，支持层级迁移；
- [x] LFU 生命周期已形成 `rank → downgrade/archive → index sync → edge decay` 闭环，并增加 `--apply-gc` 显式执行开关；
- [x] Dream/Private promote 后可立即被 Injector 检索；
- [x] MarkdownRepository 已实现跨实例解析缓存和基于 mtime/size 的单文件增量失效；
- [x] 全量回归（排除 Phase 3 已知 Tree-sitter sidecar 测试）通过；
- [x] 固定检索集从 Phase 0 的 0/20 恢复为 20/20 有结果；
- [x] 图谱实测首次加载 70.324ms、二次加载 12.158ms，二次不再解析 Markdown。二次耗时为首次的 17.3%，未达到原定 <10% 的微基准阈值；剩余成本来自 72 个文件的变更签名扫描与图反向索引重建，不以牺牲外部文件变更可见性换取数字达标。

---

## 任务 2.1 统一索引为单一事实源

### 工作内容

当前存在两套索引且服务不同消费者：

- `docs/memory/MEMORY_INDEX.json` — 被 `core/reader.py`、`core/indexer.py`、`memory/entropy_scan.py`、`utils/verify.py` 使用；
- `docs/memory/_system/memory_index.json` — 被 `memory/injector.py:183`（记忆注入主路径！）和 `workflow/postcheck.py:595` 使用。

改造方案：

1. 确定 `MEMORY_INDEX.json` 为唯一索引（它有增量更新器与校验工具链）；
2. **升级索引树结构到 v5.0**：`core/indexer.py` 的 `_find_node()` 目前按 v4 的 `layer_id-dim_id`（如 `L2-D6`）定位，改为按 v5.0 universal layer ID（`ADAPTER`/`APP`/`DOMAIN`/`PLATFORM`/`CC`/`CC_testing`/`CC_governance`/`BIZ`/`Ops`）组织一级节点，二级按 ObjectType 分组；同步升级索引条目 schema（补 `object_type`、`layer` 字段）；
3. 写迁移脚本 `scripts/migrate_index_v5.py`：从 `docs/memory/shared/` 全量重建新结构索引（幂等，可重复执行）；
4. 改造 `MemoryInjector`：`_index_file` 指向 `MEMORY_INDEX.json`，`_classify_task()` 的 `_KEYWORD_LAYER_MAP` 从 v4 节点 ID（`L1`/`L5-D8`）迁移到 v5.0 层 ID；
5. `_system/memory_index.json` 标记废弃：迁移脚本运行后将其替换为指向新索引的说明文件，`workflow/postcheck.py` 改读新索引。

### 涉及文件

| 文件 | 操作 |
|---|---|
| `src/mms/core/indexer.py` | 修改：新树结构定位逻辑 + 条目 schema |
| `src/mms/core/reader.py` | 修改：适配新结构（`_INDEX_FILE` 不变） |
| `src/mms/memory/injector.py` | 修改：索引路径 + `_KEYWORD_LAYER_MAP` v5 化 |
| `src/mms/workflow/postcheck.py` | 修改：改读 `MEMORY_INDEX.json` |
| `src/mms/utils/verify.py` | 修改：一致性校验适配新结构 |
| `src/mms/memory/entropy_scan.py` | 修改：`_collect_index_entries()` 适配新结构 |
| `scripts/migrate_index_v5.py` | 新建：幂等重建脚本 |
| `docs/memory/MEMORY_INDEX.json` | 数据迁移（脚本产出） |
| `tests/test_index_v5.py` | 新建 |

### 达到的标准

- 全仓库（`src/`）对 `_system/memory_index.json` 的读取引用为 0；
- 迁移脚本幂等：连续执行两次，索引文件字节级一致；
- 索引条目数 == `docs/memory/shared/` 下有效记忆节点数（不含 archive/templates）；
- `MemoryInjector.inject()` 对 Phase 0 固定查询集的召回不低于基线（索引换轨不能让注入变差）。

### 如何验证

```bash
python scripts/migrate_index_v5.py && python scripts/migrate_index_v5.py  # 幂等
python -m mms.utils.verify --index                                        # 索引一致性
rg -l "_system/memory_index" src/                                         # 期望无输出
pytest tests/test_index_v5.py tests/ -x
python scripts/benchmark_baseline.py --compare-retrieval benchmarks/baseline.json
```

---

## 任务 2.2 索引写后钩子（消灭写入-索引不一致）

### 工作内容

将 `IncrementalIndexer` 挂为 `MarkdownRepository` 的写后钩子：

- `put()` 成功后自动 `indexer.add_memory()`（新节点）或条目字段刷新（已有节点）；
- `delete()` 成功后自动 `indexer.remove_memory()`；
- `update_stats()` 直接委托 `indexer.update_stats()`；
- 移除各调用方（`dream.promote_draft`、`entropy_scan` 等）中手工调用 indexer 的散落代码——写入与索引从此不可能脱节。

### 涉及文件

| 文件 | 操作 |
|---|---|
| `src/mms/adapters/markdown_repo.py` | 修改：写后钩子 |
| `src/mms/memory/dream.py`、`src/mms/memory/entropy_scan.py` | 修改：删除手工 indexer 调用 |
| `tests/test_markdown_repo.py` | 扩展：写后索引一致性断言 |

### 达到的标准

- 任意 `put`/`delete` 序列执行后，索引条目集合与磁盘文件集合严格一致（无孤立、无幽灵）；
- `src/mms/` 中除 adapter 外无直接 import `IncrementalIndexer` 的业务代码。

### 如何验证

- `tests/test_markdown_repo.py` 新增随机操作序列测试：随机执行 50 次 put/delete/update_stats 后运行 `verify --index` 逻辑，断言零差异；
- `rg -l "IncrementalIndexer" src/mms | rg -v "core/indexer|adapters"` 无输出。

---

## 任务 2.3 GC / LFU / promote 闭环

### 工作内容

1. `entropy_scan.py` 的 LFU 计算（`compute_eviction_score`、`rank_eviction_candidates`）结果通过 `repo.update_stats()` 批量落盘（内部走 `indexer.batch_update_stats()`，一次磁盘写）；
2. 淘汰执行动作统一为 `repo.delete(archive=True)`，与 Bootstrap 结构性 GC 共用同一条归档路径；
3. `private.promote_note()` 与 `dream.promote_draft()` 晋升后，索引即时可见（依赖 2.2 的写后钩子，此处补集成测试）；
4. 边衰减（`decay_edges`）的权重文件读写保持现状（`_system` 系统文件，非记忆节点），但入口统一到 `entropy_scan.main()` 的固定阶段，确保每次 GC 运行都会执行。

### 涉及文件

| 文件 | 操作 |
|---|---|
| `src/mms/memory/entropy_scan.py` | 修改：落盘走 repository；`main()` 阶段编排 |
| `src/mms/memory/private.py`、`src/mms/memory/dream.py` | 只读（验证 promote 路径） |
| `tests/test_gc_loop.py` | 新建：GC 闭环集成测试 |

### 达到的标准

- GC 全流程（扫描 → 评分 → 降级/归档 → 索引同步）单命令触发，中间无需人工修复索引；
- promote 后立即执行 `MemoryInjector.inject()` 能检索到新晋升节点。

### 如何验证

- `tests/test_gc_loop.py`：在临时记忆库中构造 hot-但-零访问节点 → 跑 entropy_scan → 断言 tier 降级已同时反映在文件 front-matter 与索引中；构造已删除源码类的 MEM-BOOT 节点 → 跑 bootstrap → 断言归档 + 索引移除；
- promote 集成测试：`init_ep → add_note → promote_note → inject`，断言命中。

---

## 任务 2.4 MemoryGraph 缓存与增量加载

### 工作内容

`MemoryGraph` 每次实例化都 `rglob` 全量扫描并解析所有 Markdown（`graph_resolver.py:240`）。改造：

1. 首次加载后将解析结果缓存（进程内，以 `memory_root` 为 key）；
2. 失效策略：对比索引文件 mtime + 各条目 `file` 的 mtime，仅重新解析变化的文件；
3. 保持 `MemoryGraph` 公共 API 不变（`_nodes`、反向索引、in-degree 计算逻辑不动）。

### 涉及文件

| 文件 | 操作 |
|---|---|
| `src/mms/memory/graph_resolver.py` | 修改：缓存 + 增量失效 |
| `tests/test_graph_cache.py` | 新建 |

### 达到的标准

- 第二次实例化 `MemoryGraph`（无文件变化）加载耗时 < 首次的 10%；
- 修改单个节点文件后，重新加载能反映变化且只重解析该文件；
- 现有依赖 `MemoryGraph` 的测试全部不改动即通过。

### 如何验证

- `tests/test_graph_cache.py`：计时断言 + 篡改单文件后的可见性断言；
- `pytest tests/ -x` 全绿。

---

## Phase 2 整体验收

- [x] `python -m mms.utils.verify --index` 在真实仓库上零告警；
- [x] 基线复测：固定查询 20/20 有结果；图谱二次加载不再重复解析 Markdown；
- [x] 4 个 fixture Bootstrap 与幂等测试全绿；
- [x] 回退方案：恢复旧索引消费者并用 Git 恢复 `MEMORY_INDEX.json`。
