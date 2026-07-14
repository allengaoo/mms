# MMS 现代化改造 — 执行计划总览

> 版本：v1.0 · 制定日期：2026-07-14

> 执行结果：Phase 1–3 已完成并通过全量回归。Memoria `main` 与稳定版 `v0.4.0 + MatrixOne 3.0.17` 均无法原生往返自定义 metadata（0/20）；稳定版虽已通过 snapshot/rollback/branch/merge，但本体兼容决策门仍为 No-Go，因此按既定降级路径停止 Phase 4–5。
> 决策依据：Canvas《MMS 现代化改造评估》（mms-modernization-options）
> 技术栈决策：Memoria（版本化持久层）+ 动态本体（语义层，保留）+ Tree-sitter（代码事实提取）；**不引入 AgentScope**

---

## 1. 总体策略

采用「原仓库渐进改造」路线（Canvas 方案 A）：

1. 先在当前仓库建立四个端口（`MemoryRepository` / `VersionStore` / `OntologyProjection` / `CodeParser`），让所有读写走统一入口；
2. 修复既有内部断层（双索引、版本不自增、GC 未闭环）——这一步无论 Memoria 是否最终采用都直接受益；
3. 将 Tree-sitter 从 sidecar 提升为 Bootstrap 主路径解析器；
4. 通过双写 + 影子读验证 Memoria，验证通过才切换默认后端。

核心原则：**每一步都可独立回退，每一步完成后现有测试必须全绿。**

## 2. 阶段索引

| 阶段 | 计划文件 | 分支 | 预估 | 前置依赖 |
|---|---|---|---|---|
| Phase 0 技术验证与基线 | [phase0_validation.md](phase0_validation.md) | `spike/memoria-poc`（不合主干） | 1–2 人周 | 无（本机 OrbStack 提供 Docker） |
| Phase 1 端口定义与内核解耦 | [phase1_ports.md](phase1_ports.md) | `feature/memory-ports` | 2–3 人周 | 无（可与 Phase 0 并行） |
| Phase 2 内部断层修复 | [phase2_internal_fixes.md](phase2_internal_fixes.md) | `feature/index-unification` | 1–2 人周 | Phase 1 |
| Phase 3 Tree-sitter 接入主路径 | [phase3_treesitter.md](phase3_treesitter.md) | `feature/treesitter-mainline` | 2–4 人周 | Phase 0.3 决策门 |
| Phase 4 Memoria 双写迁移 | [phase4_memoria_dualwrite.md](phase4_memoria_dualwrite.md) | `feature/memoria-dualwrite` | 3–5 人周 | Phase 0.2 决策门 + Phase 1 + Phase 2 |
| Phase 5 切换与清理 | [phase5_cutover.md](phase5_cutover.md) | `feature/memoria-cutover` | 2–3 人周 | Phase 4 验收指标达标 |

## 3. 决策门（Phase 0 产出）

Phase 0 结束后必须对以下五个维度给出书面结论，决定后续阶段范围：

| 验证维度 | 继续的证据 | 暂停/缩小范围的证据 | 影响的阶段 |
|---|---|---|---|
| 版本与审计 | 真实场景需要隔离实验、差异审查、合并、精确回滚 | Git 对 Markdown 的历史与回滚已满足需求 | Phase 4/5 |
| 检索与性能 | Memoria 在基线数据集上提高召回或降低延迟 | 网络/序列化开销抵消收益 | Phase 4/5 |
| 本体兼容 | ObjectType/LinkType/provenance 可无损往返并随分支正确合并 | 需大量旁路表或无法保证关系一致性 | Phase 4/5 |
| 端侧运维 | OrbStack 下 MatrixOne 资源、备份、恢复成本可接受 | 无法稳定运行或必须依赖云服务 | Phase 4/5 |
| Tree-sitter 精度 | 四语言 fixture 的类归属/签名/注解/imports 明显优于正则 | 收益只出现在少数样本，且引入 fingerprint 漂移噪音 | Phase 3 |

**降级路径**：Memoria 验证失败 → 只执行 Phase 1–3（端口 + 断层修复 + Tree-sitter 仍有独立价值）；Tree-sitter 验证不达标 → Phase 3 缩小为仅 Java/Go 或取消。

## 4. 全局风险清单

| 风险 | 等级 | 缓解措施 | 归属阶段 |
|---|---|---|---|
| Fingerprint 漂移导致 MEM-BOOT 记忆被误 GC | 高 | 签名归一化 + 双解析器 fingerprint 一致性测试 + 一次性迁移脚本 | Phase 3 |
| LinkType 边在 Memoria 中无法无损表示 | 高 | Phase 0.2 提前验证，失败则终止 Phase 4 | Phase 0/4 |
| 双写不一致造成静默数据分裂 | 中 | 每日对账脚本 + 影子读差异日志 + 副写失败重试队列 | Phase 4 |
| Memoria 公开接口演进（项目较新） | 中 | 客户端侧字段校验 + 依赖版本锁定 | Phase 4 |
| 大范围改造调用方引入回归 | 中 | 每个阶段结束现有测试全绿才可合并；Phase 1 分多个小 PR | Phase 1 |

## 5. 分支与合并纪律

- 每个阶段一个 feature 分支，一个（或多个小）PR，CI 全绿方可合并主干（`main`）。
- `spike/memoria-poc` 是实验分支，产出报告后即废弃，不合主干。
- Phase 4 起引入配置开关 `memory.backend`（`markdown` | `dual` | `memoria`），任何时刻可通过配置一键回退。

## 6. 关键代码事实（计划编写时核实，2026-07-14）

以下事实是各阶段计划的依据，动手前如发现代码已变化需先更新计划：

- **双索引断层**：`MemoryInjector` 实际读取 `docs/memory/_system/memory_index.json`（`src/mms/memory/injector.py:183`），而 `core/reader.py`、`core/indexer.py`、`memory/entropy_scan.py`、`utils/verify.py` 全部使用 `docs/memory/MEMORY_INDEX.json`。注入引擎与 GC/校验体系用的是两套索引。
- **Tree-sitter 未接主路径**：`AstSkeletonBuilder.build()`（`src/mms/analysis/ast_skeleton.py:725`）直接调用内部正则函数 `_parse_typescript`(:380) / `_parse_java`(:445) / `_parse_go`(:542)；`parsers/factory.get_parser()` 仅支持 java/go 且没有主流程调用方。
- **写入入口分散**：`src/mms/memory/` 下 9 个文件共 16 处直接 `write_text` / `atomic_write` 落盘（`dream.py`、`private.py` 各 3 处，`memory_actions.py` 2 处等）。
- **版本不自增**：`MemoryNode.version` 从 front-matter 读取（`graph_resolver.py:314`），但无任何写路径对其递增。
- **索引树仍是 v4 结构**：`core/indexer.py` 的 `_find_node()` 以 `L2-D6` 形式的 `layer_id-dim_id` 定位节点，与 v5.0 通用层 ID（`ADAPTER`/`APP`/`DOMAIN`/...）不匹配。
- **CLI 入口**：`pyproject.toml` → `mulan = "mms.cli:main"`。
- **Tree-sitter 配置**：`docs/memory/_system/config.yaml` → `analysis.use_tree_sitter: false`、`tree_sitter_languages: [java, go]`；extras 定义在 `pyproject.toml` 的 `tree_sitter` 分组。
- **测试基材**：`tests/fixtures/` 有 4 个语言 fixture（`spring-boot-demo`、`go-gin-demo`、`python-fastapi-demo`、`typescript-nestjs-demo`）。
