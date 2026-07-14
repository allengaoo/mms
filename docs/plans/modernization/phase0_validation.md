# Phase 0 — 技术验证与基线

> 分支：`spike/memoria-poc`（实验分支，不合主干）
> 预估：1–2 人周 · 前置依赖：无 · Docker 环境：本机 OrbStack
> 产出性质：**决策门报告**，决定 Phase 3 / Phase 4-5 是否执行及范围

## 当前进度（2026-07-14）

- [x] 0.1 基线采集脚本、20 条固定查询集和首份基线已生成；
- [x] 基线连续运行两次，确定性字段零差异；
- [x] OrbStack 已启动，Docker 29.4.0 可用；
- [x] 0.2 第一轮 Memoria main 组合测试完成：metadata 0/20、snapshot API 500；
- [x] 0.2b 稳定组合 `Memoria v0.4.0 + MatrixOne 3.0.17` 已复测：版本 API 恢复，但 metadata 仍为 0/20，最终 No-Go；
- [x] 0.3 Tree-sitter 决策门完成：captures 兼容错误已消除，三语言提取测试、双模式 fingerprint 一致性和性能基准均通过，Phase 3 已实施。

---

## 任务 0.1 建立基线数据

### 工作内容

编写基线采集脚本，对现状做量化快照，作为后续所有阶段"不回退"判断的锚点：

1. 对 4 个 fixture（`tests/fixtures/{spring-boot-demo,go-gin-demo,python-fastapi-demo,typescript-nestjs-demo}`）各跑一次完整 Bootstrap，记录：
   - 解析出的文件数、类数、方法数、注解数、imports 数（按语言分组）；
   - 层级分布（每个 universal layer 的节点数）、`UNKNOWN` 比例、conflict 数（来自 `schema_evolution` 报告）；
   - 端到端耗时（AST 构建、信号融合、记忆生成分段计时）。
2. 对 `docs/memory/` 现有节点执行一组固定检索查询（≥ 20 条，覆盖各 layer 和 ObjectType），记录 `MemoryInjector.inject()` 的命中 ID 列表与耗时。
3. 记录 `MemoryGraph` 全量加载耗时与节点数。

### 涉及文件

| 文件 | 操作 |
|---|---|
| `scripts/benchmark_baseline.py` | 新建：采集脚本，输出 JSON |
| `benchmarks/baseline.json` | 新建：基线数据（提交入库） |
| `benchmarks/retrieval_queries.yaml` | 新建：固定检索查询集（提交入库） |
| `src/mms/bootstrap/ontology_populator.py` | 只读（复用 `BootstrapV2Report`） |
| `src/mms/memory/injector.py` | 只读 |

### 达到的标准

- 基线 JSON 包含上述全部指标，且脚本可重复执行（同一 commit 下两次运行结果一致，耗时类指标允许 ±20% 波动）。
- 检索查询集覆盖全部 9 个 universal layer 中至少 6 个、4 个记忆 ObjectType 全部覆盖。

### 如何验证

```bash
python scripts/benchmark_baseline.py --out benchmarks/baseline.json
python scripts/benchmark_baseline.py --out /tmp/baseline2.json
python scripts/benchmark_baseline.py --diff benchmarks/baseline.json /tmp/baseline2.json  # 非耗时指标 0 差异
```

---

## 任务 0.2 Memoria PoC

### 工作内容

在 OrbStack 中部署 Memoria + MatrixOne，验证 Canvas 决策门中"本体兼容 / 版本与审计 / 检索与性能 / 端侧运维"四个维度：

1. **部署**：编写 `spike/memoria_poc/docker-compose.yml`，锁定 Memoria 与 MatrixOne 镜像版本；记录冷启动时间、内存/磁盘占用。
2. **元数据往返**：取 20 个真实记忆节点（覆盖 4 个 ObjectType、含 `related_to`/`cites_files`/`about_concepts`/`contradicts`/`derived_from`/provenance 全字段），写入 Memoria 再读回，逐字段比对。重点验证嵌套结构（`related_to` 是对象列表）是否无损。
3. **LinkType 表示方案**：分别试验两种方案并评估——(a) 边作为节点 metadata 数组；(b) 边作为独立 memory 记录（旁路表）。评估标准：反向查询（"谁引用了我"）的可行性与成本。
4. **版本语义**：执行 snapshot → 修改 5 个节点 → branch → 两分支各改不同节点 → merge → rollback 全流程，检查每一步后 metadata 与关系是否完整。
5. **检索对比**：将 `docs/memory` 全量节点导入，跑 0.1 的固定查询集，与 `MemoryInjector` 基线对比召回与延迟。
6. **备份恢复**：导出 MatrixOne 数据卷 → 销毁容器 → 恢复 → 校验节点数与抽样内容一致。

### 涉及文件

| 文件 | 操作 |
|---|---|
| `spike/memoria_poc/docker-compose.yml` | 新建 |
| `spike/memoria_poc/test_roundtrip.py` | 新建：元数据往返 + LinkType 方案试验 |
| `spike/memoria_poc/test_versioning.py` | 新建：snapshot/branch/merge/rollback 流程 |
| `spike/memoria_poc/test_retrieval.py` | 新建：检索对比（读取 `benchmarks/retrieval_queries.yaml`） |
| `spike/memoria_poc/REPORT.md` | 新建：决策门报告 |

### 达到的标准（Go 条件，全部满足才进入 Phase 4）

- [ ] 20 个节点全字段无损往返（含嵌套结构），或差异可通过 `OntologyProjection` 层确定性修复；
- [ ] LinkType 两方案至少一个支持正/反向查询，且单节点边查询 < 100ms；
- [ ] snapshot/branch/merge/rollback 全流程后节点内容、metadata、边关系零丢失；
- [ ] 固定查询集召回不低于 `MemoryInjector` 基线，P95 延迟 < 500ms；
- [ ] OrbStack 下常驻内存 < 2GB，备份恢复流程 < 10 分钟且数据完整。

### 如何验证

- 三个 test 脚本以 pytest 形式编写，`pytest spike/memoria_poc/ -v` 全绿即满足前四条；
- 资源与备份指标人工执行并记录在 `REPORT.md`；
- `REPORT.md` 末尾给出每个决策门维度的 Go/No-Go 结论及证据链接。

---

## 任务 0.3 Tree-sitter 金标对比

### 工作内容

1. **建金标**：人工核对 4 个 fixture 的全部源文件，为每个文件标注：类/接口/结构体清单、方法签名、类级与方法级注解（含带参形式如 `@Transactional(readOnly=true)`）、imports、嵌套类型。存为 YAML。
2. **补 TypeScript 语言包**：临时安装 `tree-sitter-typescript`，在 spike 内为 TS 写与 Java/Go 同构的查询（正式接入在 Phase 3）。
3. **双解析器对比**：对每个 fixture 文件分别用现有正则路径（`ast_skeleton.py` 的 `_parse_java`/`_parse_go`/`_parse_typescript`）和 Tree-sitter 路径提取 `FileSkeleton`，与金标计算精确率/召回率（按类、方法、注解、imports 四个维度分别统计）。
4. **fingerprint 漂移评估**：统计两种解析器对同一文件产出的 fingerprint 不一致的文件比例，分析原因（签名格式差异 vs 提取内容差异），作为 Phase 3 风险量化输入。

### 涉及文件

| 文件 | 操作 |
|---|---|
| `spike/treesitter_eval/golden/{java,go,typescript}.yaml` | 新建：金标标注 |
| `spike/treesitter_eval/compare.py` | 新建：双解析器对比脚本 |
| `spike/treesitter_eval/REPORT.md` | 新建：精度对比 + fingerprint 漂移报告 |
| `src/mms/analysis/parsers/tree_sitter_parser.py` | 只读（评估现有 Java/Go 查询覆盖度，缺口记入报告） |

### 达到的标准（Go 条件）

- [ ] Tree-sitter 在 Java/Go/TS 三种语言上，类归属与方法签名的 F1 均 ≥ 正则解析，且至少一个维度（注解、嵌套类、imports 之一）提升 ≥ 10 个百分点；
- [ ] fingerprint 漂移原因全部可归因（签名归一化可消除的格式差异 vs 真实提取差异），并给出 Phase 3 的归一化规则草案。

### 如何验证

```bash
pip install tree-sitter tree-sitter-java tree-sitter-go tree-sitter-typescript
python spike/treesitter_eval/compare.py --out spike/treesitter_eval/REPORT.md
```

报告中包含每语言 × 每维度的 P/R/F1 表格和漂移文件清单。

---

## Phase 0 整体验收

- [ ] `benchmarks/baseline.json` 与查询集已提交主干（基线部分走独立小 PR，可合主干）；
- [x] `spike/memoria_poc/REPORT.md` 已完成两轮实测并给出最终 No-Go；Tree-sitter 证据固化在 Phase 3 测试与阶段报告中；
- [x] 阶段范围已收敛：Phase 1–3 完成，Phase 4–5 因 Memoria 本体兼容决策门失败而停止。
