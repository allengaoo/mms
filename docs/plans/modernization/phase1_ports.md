# Phase 1 — 端口定义与内核解耦

> 分支：`feature/memory-ports`
> 预估：2–3 人周 · 前置依赖：无（可与 Phase 0 并行）
> 目标：所有记忆读写收敛到统一端口，为后端可替换做准备。**无论 Memoria 是否采用，此阶段都值得执行。**

---

## 实施状态（2026-07-14）

- [x] 已定义 `MemoryRecord`、`MemoryRepository`、`OntologyProjection`、`VersionStore` 与 `CodeParser` 端口；
- [x] 已实现 `MarkdownRepository`、后端工厂、原子写入、自动版本递增、归档与进程内记录缓存；
- [x] 已迁移 MemoryGraph、MemoryInjector、Memory Actions、Dream promote、Private promote、Bootstrap seed/结构性 GC、FreshnessChecker；
- [x] 已增加 front-matter 全库往返、Repository 契约、真实图谱对照和禁止绕过写入测试；
- [x] 4 个 fixture Bootstrap、Memory Engine、Dream、Freshness 与 Layer 2 扩展测试通过；
- [x] Phase 0 基线复测完成。AST、CodeGraph、推断与 Bootstrap 指标不变；图谱从 73 节点修正为 72 个有效节点（排除无 front-matter 的 `ontology_schema_readme.md`），`total_file_refs` 从 53 修正为 2（旧轻量解析器把 `cites_files: []` 错当作字符串引用）；
- [ ] `IncrementalIndexer` 写后钩子按原计划留到 Phase 2：当前索引仍是 v4 结构且存在双索引，先挂钩会把旧结构继续固化。

本地完整测试除两个已在 Phase 0.3 记录的 Tree-sitter sidecar capture API 兼容错误外均通过；该问题属于 Phase 3，不是本阶段引入。

---

## 任务 1.1 定义四个端口

### 工作内容

新建 `src/mms/ports/` 包，用 `typing.Protocol` 定义与后端无关的接口：

```python
# ports/repository.py
@dataclass
class MemoryRecord:
    """与存储无关的记忆记录。字段对齐 v5.0 front-matter 标准。"""
    id: str
    object_type: str          # Pattern | Decision | AntiPattern | BusinessFlow | ...
    layer: str                # v5.0 universal layer ID
    tier: str
    title: str
    body: str                 # Markdown 正文（不含 front-matter）
    tags: list[str]
    related_to: list[dict]
    cites_files: list[str]
    impacts: list[str]
    about_concepts: list[str]
    contradicts: list[str]
    derived_from: list[str]
    version: int
    access_count: int
    provenance: dict          # source_ep / module / generalized / dimension 等
    created_at: str
    updated_at: str

class MemoryRepository(Protocol):
    def get(self, memory_id: str) -> MemoryRecord | None: ...
    def put(self, record: MemoryRecord) -> MemoryRecord: ...   # 返回含新 version 的记录
    def delete(self, memory_id: str, *, archive: bool = True) -> bool: ...
    def list_ids(self, *, layer: str | None = None, tier: str | None = None,
                 object_type: str | None = None) -> list[str]: ...
    def query(self, q: "MemoryQuery") -> list[MemoryRecord]: ...
    def update_stats(self, memory_id: str, *, access_count: int | None = None,
                     tier: str | None = None) -> bool: ...
    def load_all(self) -> Iterable[MemoryRecord]: ...          # MemoryGraph 全量加载用
```

- `ports/version_store.py`：`VersionStore` Protocol —— `snapshot(label)` / `branch(name)` / `merge(src, dst)` / `rollback(ref)` / `history(memory_id)`。Phase 1 只定义接口，提供 `NullVersionStore`（全部抛 `NotImplementedError` 或 no-op）占位。
- `ports/projection.py`：`OntologyProjection` Protocol —— `to_record(front_matter, body)` / `from_record(record) -> (front_matter, body)`。把现有分散在 `graph_resolver._parse_frontmatter`、`dream._auto_link` 等处的 front-matter 解析/序列化逻辑收敛为唯一实现 `FrontMatterProjection`。
- `ports/code_parser.py`：直接 re-export 现有 `analysis/parsers/protocol.py` 的 `ASTParserProtocol`，不重复定义（Phase 3 使用）。

### 涉及文件

| 文件 | 操作 |
|---|---|
| `src/mms/ports/__init__.py` | 新建 |
| `src/mms/ports/repository.py` | 新建：`MemoryRecord`、`MemoryQuery`、`MemoryRepository` |
| `src/mms/ports/version_store.py` | 新建：`VersionStore`、`NullVersionStore` |
| `src/mms/ports/projection.py` | 新建：`OntologyProjection`、`FrontMatterProjection` |
| `src/mms/ports/code_parser.py` | 新建（re-export） |
| `tests/test_ports_contract.py` | 新建：契约测试（见 1.4） |

### 达到的标准

- `MemoryRecord` 字段与 v5.0 front-matter 标准（见 `docs/memory/templates/`）一一对应，无信息丢失；
- `FrontMatterProjection` 对 `docs/memory/shared/` 下全部现有节点做 `to_record → from_record` 往返，输出与原文件语义等价（YAML 键序、引号风格允许不同，字段值必须一致）。

### 如何验证

- 新增往返测试：遍历 `docs/memory/shared/**/*.md`，断言 `from_record(to_record(x))` 解析后的 front-matter dict 与原始 dict 相等；
- `pytest tests/test_ports_contract.py -v` 全绿。

---

## 任务 1.2 实现 MarkdownRepository

### 工作内容

新建 `src/mms/adapters/markdown_repo.py`，将现有文件系统逻辑收敛为第一个 Repository 实现（过渡期默认后端）：

- `get`/`load_all`：复用 `graph_resolver.py` 的扫描规则（跳过 `_system`/`templates`/`archive`、`CONTRIBUTING.md`/`README.md`）；
- `put`：经 `FrontMatterProjection` 序列化，用 `core/writer.atomic_write` 落盘；**对已存在节点自动 `version += 1` 并刷新 `updated_at`**（修复"版本不自增"断层）；写后调用 `core/indexer.IncrementalIndexer` 同步索引（索引结构升级在 Phase 2，本阶段先保持现状调用）；
- `delete(archive=True)`：移动到 `archive/` 目录并调用 `indexer.remove_memory()`（对齐 Bootstrap 结构性 GC 的既有归档行为）；
- `update_stats`：委托 `indexer.update_stats()`；
- 文件路径规则（layer → 目录映射）从 `dream.py:_layer_to_dir()` 提取到 adapter 内，作为唯一实现。

### 涉及文件

| 文件 | 操作 |
|---|---|
| `src/mms/adapters/__init__.py` | 新建 |
| `src/mms/adapters/markdown_repo.py` | 新建 |
| `src/mms/core/writer.py` | 只读复用 |
| `src/mms/core/indexer.py` | 只读复用（Phase 2 再改造） |
| `tests/test_markdown_repo.py` | 新建 |

### 达到的标准

- 在临时目录中 `put` → `get` → `put`（修改）→ `get` → `delete` 全流程正确，第二次 `put` 后 `version == 2`；
- `load_all()` 对当前仓库 `docs/memory` 的加载结果与 `MemoryGraph._load_all()` 的节点集合完全一致（ID 集合相等、关键字段抽样相等）。

### 如何验证

- `pytest tests/test_markdown_repo.py -v`，其中包含一个对照测试：分别用 `MemoryGraph` 和 `MarkdownRepository.load_all()` 加载真实 `docs/memory`，断言节点 ID 集合相等。

---

## 任务 1.3 改造调用方（分 3 个小 PR）

### 工作内容

将 16 处直接落盘与各自为政的读取逻辑改为经 Repository。按耦合度分三批：

**PR-1a 写路径（核心）**

| 调用方 | 现状 | 改造 |
|---|---|---|
| `memory/memory_actions.py` — `create_memory_node()`、`apply_contradiction_resolution()` | 直接 `write_text` | 构造 `MemoryRecord` 后 `repo.put()` |
| `memory/dream.py` — `save_draft()`、`promote_draft()`、`_apply_auto_link_to_file()` | 直接读写文件 | draft 仍留私有目录；`promote_draft()` 的正式节点写入改走 `repo.put()`；`_get_next_mem_id()` 改为查询 repository |
| `memory/private.py` — `promote_note()` | 直接写共享区 | 改走 `repo.put()`（EP 私有笔记本身不动，仍是私有文件） |
| `bootstrap/ontology_populator.py` — MEM-BOOT 生成与结构性 GC | 直接写/归档文件 | 生成走 `repo.put()`，GC 走 `repo.delete(archive=True)` |

**PR-1b 读路径**

| 调用方 | 改造 |
|---|---|
| `memory/graph_resolver.py` — `MemoryGraph._load_all()` | 改为从 `repo.load_all()` 构建索引；`MemoryNode` 由 `MemoryRecord` 构造；保留 `memory_root` 参数以兼容测试 |
| `memory/injector.py` — `MemoryInjector` | 记忆正文读取改经 repository（索引文件问题在 Phase 2 处理） |
| `memory/task_matcher.py`、`memory/codemap.py`、`memory/funcmap.py`、`memory/template_lib.py` | 读经 repository；其中 codemap/funcmap 的产物（非记忆节点的系统文件）写入不动 |

**PR-1c 维护路径**

| 调用方 | 改造 |
|---|---|
| `memory/entropy_scan.py` | 孤立/幽灵扫描改为对比 `repo.list_ids()` 与索引；归档动作走 `repo.delete()` |
| `memory/graph_health.py`、`memory/freshness_checker.py` | 读经 repository |

Repository 实例通过模块级工厂 `mms.adapters.get_repository()` 获取（读取 `config.yaml` 的 `memory.backend`，本阶段只有 `markdown` 一个值），不引入全局单例状态。

### 达到的标准

- `src/mms/memory/` 与 `src/mms/bootstrap/` 中，除 `adapters/` 外不再有任何直接写 `docs/memory/shared/` 的代码；
- EP 私有目录（`private.py` 的 notes、`dream.py` 的 draft）、codemap/funcmap 系统产物明确豁免，在代码注释中标注原因；
- 全部现有测试通过，包括 4 个 fixture 的 bootstrap 集成测试与幂等测试。

### 如何验证

```bash
# 静态检查：无绕过写入（CI 中固化为一个测试）
rg -n "write_text|atomic_write" src/mms/memory src/mms/bootstrap | rg -v "adapters|# repo-exempt"
# 期望：仅剩标注豁免的行

pytest tests/ -x   # 现有测试全绿
python -m mms.cli bootstrap tests/fixtures/spring-boot-demo  # 端到端手工冒烟
```

新增 `tests/test_no_bypass_writes.py`：用 AST/文本扫描断言豁免清单之外无直接落盘调用。

---

## 任务 1.4 端口契约测试

### 工作内容

编写与实现无关的契约测试套件 `tests/test_ports_contract.py`，以 pytest 参数化形式对"任何 `MemoryRepository` 实现"断言行为：put 幂等性、version 自增、delete 归档语义、list 过滤、stats 更新。Phase 1 只挂 `MarkdownRepository`，Phase 4 的 `MemoriaRepository` 直接复用同一套契约。

### 达到的标准

- 契约测试覆盖 Repository 全部方法；
- 测试通过 fixture 注入实现，不 import 具体 adapter 类到断言逻辑中。

### 如何验证

`pytest tests/test_ports_contract.py -v` 全绿；人工确认 Phase 4 挂新实现只需新增一个 fixture 参数。

---

## Phase 1 整体验收

- [x] 端口、适配器及三类调用路径已完成；
- [x] `tests/test_no_bypass_writes.py` 已加入测试集；
- [x] 基线复测完成，Bootstrap 结果零差异；图谱差异已确认是旧解析器误计数修复；
- [x] 回退方案确认：本阶段纯重构，回退 = revert 本阶段变更。
