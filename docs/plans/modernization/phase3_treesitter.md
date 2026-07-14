# Phase 3 — Tree-sitter 接入主路径

> 分支：`feature/treesitter-mainline`
> 预估：2–4 人周 · 前置依赖：Phase 0.3 决策门通过（精度提升成立、fingerprint 漂移可归因）
> 目标：Tree-sitter 从 sidecar 提升为 Bootstrap 默认解析器（Java/Go/TypeScript），Python 继续走标准库 ast。

---

## 实施状态（2026-07-14）

- [x] AstSkeletonBuilder 已统一通过 parser factory 分发 Java、Go、TypeScript/TSX；Python 保持标准库 `ast`；
- [x] RegexFallbackParser 已覆盖三种非 Python 语言，显式关闭 Tree-sitter 时与改造前实现逐字段一致；
- [x] TreeSitterParser 已改为直接遍历 CST，消除了 Query capture API 版本差异和 Java 方法错误归属；
- [x] Java 已覆盖嵌套类、继承/实现、参数化注解、方法签名与 imports；
- [x] Go 已覆盖 receiver、struct embedding、interface、顶层函数与 imports；
- [x] TypeScript/TSX 已覆盖 interface/enum、NestJS decorators、方法与 imports；
- [x] 新增 parser-independent source fingerprint；三个非 Python fixture 在 Regex/Tree-sitter 两模式下文件集合和 fingerprint 100% 一致；
- [x] 新增幂等迁移脚本 `scripts/migrate_fingerprints.py`；真实仓库 dry-run 当前需迁移 0 个 MEM-BOOT 节点；
- [x] 默认启用 Tree-sitter，依赖缺失时 factory 自动回退；CI 安装三语言 grammar 并执行双模式一致性测试；
- [x] 全量回归通过；三 fixture 20 轮基准：Regex 208.31ms，Tree-sitter 222.99ms，增幅 7.0%；
- [x] 提取质量的可验证改善：Spring 注解 0 → 14；NestJS class/method decorators 0 → 34；Go imports 13 → 28。TS 方法数 56 → 27 是修复旧正则将方法重复归属到多个类的假阳性，不作为能力回退。

---

## 任务 3.1 AstSkeletonBuilder 改走解析器工厂

### 工作内容

`AstSkeletonBuilder`（`src/mms/analysis/ast_skeleton.py:717`）目前对 java/go/typescript 直接调用内部正则函数 `_parse_java`(:445) / `_parse_go`(:542) / `_parse_typescript`(:380)，完全绕过了 `parsers/factory.py`。改造：

1. `build()` 内的语言分发改为 `get_parser(lang).extract_skeleton(source, rel_path)`；Python 分支保持直连标准库 ast 不变；
2. 三个正则函数迁移到 `parsers/regex_parser.py` 内（成为 `RegexFallbackParser` 的实现体），`ast_skeleton.py` 中删除，避免双份维护；
3. `factory.get_parser()` 解除 `lang not in ("java", "go")` 的限制，加入 `typescript`；
4. 降级链保持：`use_tree_sitter=false` 或依赖缺失 → `RegexFallbackParser`，行为与改造前完全一致。

### 涉及文件

| 文件 | 操作 |
|---|---|
| `src/mms/analysis/ast_skeleton.py` | 修改：`build()` 分发；删除 `_parse_java/_parse_go/_parse_typescript` 及其正则常量 |
| `src/mms/analysis/parsers/regex_parser.py` | 修改：吸收三个正则解析函数 |
| `src/mms/analysis/parsers/factory.py` | 修改：支持 typescript |
| `src/mms/analysis/parsers/protocol.py` | 只读（接口不变） |
| `tests/test_parser_dispatch.py` | 新建：分发与降级测试 |

### 达到的标准

- `use_tree_sitter=false` 时，4 个 fixture 的 `build_ast_index()` 输出与改造前**逐字段一致**（含 fingerprint）——纯重构不改行为；
- `ast_skeleton.py` 中不再有 java/go/ts 的正则解析代码。

### 如何验证

- 改造前在主干跑一次 `build_ast_index()` 并序列化输出为 golden 文件；改造后 `use_tree_sitter=false` 对比 golden 文件零差异（此测试进入 `tests/test_parser_dispatch.py`）；
- `pytest tests/ -x` 全绿。

---

## 任务 3.2 TreeSitterParser 能力补齐

### 工作内容

按 Phase 0.3 报告中的缺口清单补齐提取能力（现有实现见 `parsers/tree_sitter_parser.py`，仅有 Java/Go 的类名与方法名查询）：

1. **Java**：方法完整签名（参数类型 + 返回类型）、类级/方法级注解含参数形式（`@Transactional(readOnly=true)`）、嵌套类（限定名 `Outer.Inner`）、`extends`/`implements` 链、imports 过滤规则与正则版对齐；
2. **Go**：函数/方法签名（含 receiver 类型）、struct 内嵌（embedding）、interface 方法集、imports；
3. **TypeScript**：新增 `tree-sitter-typescript` 支持——class/interface/enum、decorator（NestJS 的 `@Controller`/`@Injectable` 是层级推断关键信号）、方法签名、import 语句；
4. 所有输出统一填充现有 `FileSkeleton`/`ClassSkeleton`/`MethodSkeleton` dataclass，不改数据结构。

### 涉及文件

| 文件 | 操作 |
|---|---|
| `src/mms/analysis/parsers/tree_sitter_parser.py` | 修改：补查询与提取逻辑，新增 TS 分支 |
| `pyproject.toml` | 修改：`tree_sitter` extras 加入 `tree-sitter-typescript`，锁定三个语言包版本 |
| `docs/memory/_system/config.yaml` | 修改：`tree_sitter_languages: [java, go, typescript]` |
| `src/mms/utils/mms_config.py` | 修改：`analysis_tree_sitter_languages` 默认值同步 |
| `tests/test_tree_sitter_extraction.py` | 新建：每语言 × 每维度的提取用例 |

### 达到的标准

- 对 Phase 0.3 金标（`spike/treesitter_eval/golden/*.yaml`）：类归属与方法签名 F1 ≥ 正则版，注解维度 F1 提升 ≥ 10 个百分点（决策门数值，若 0.3 实测更高则以实测为准写入本文件）；
- 空文件、语法错误文件、超大文件（>1MB）不抛异常，降级返回空 skeleton 并记 warning。

### 如何验证

```bash
pip install -e ".[tree_sitter]"
pytest tests/test_tree_sitter_extraction.py -v
python spike/treesitter_eval/compare.py --parser tree_sitter --golden spike/treesitter_eval/golden/
```

---

## 任务 3.3 Fingerprint 漂移控制（本阶段最高风险项）

### 工作内容

fingerprint 是增量 Bootstrap 与结构性 GC 的比对依据（`ontology_populator.py:394` 起扫描已有 MEM-BOOT 的 fingerprint 映射）。解析器切换若改变签名文本格式，会导致全部 fingerprint 变化 → 增量模式失效 → 旧 MEM-BOOT 被误判为孤立节点归档。措施：

1. **签名归一化层**：在 `FileSkeleton` 生成 fingerprint 之前引入 `normalize_signature()`（统一空白、参数名剥离只留类型、泛型格式统一），两种解析器共用，规则来自 Phase 0.3 的漂移归因报告；
2. **一致性测试**：对 4 个 fixture 的每个文件断言 `fingerprint(regex) == fingerprint(tree_sitter)`；对无法归一化消除的真实提取差异（Tree-sitter 提取得更全），列入白名单文件并触发 3.4 的一次性迁移；
3. **一次性迁移脚本** `scripts/migrate_fingerprints.py`：对白名单差异，用新解析器重算所有 MEM-BOOT 节点的 fingerprint 并原位更新 front-matter（不触发 GC、不改 ID、幂等）。

### 涉及文件

| 文件 | 操作 |
|---|---|
| `src/mms/analysis/ast_skeleton.py` | 修改：`normalize_signature()` + fingerprint 计算改造 |
| `scripts/migrate_fingerprints.py` | 新建 |
| `tests/test_fingerprint_stability.py` | 新建 |

### 达到的标准

- 归一化后，4 个 fixture 中 fingerprint 不一致的文件占比 < 5%，且全部在白名单内有归因说明；
- 迁移脚本执行后立刻跑增量 bootstrap：`memories_generated == 0` 且结构性 GC 归档数 == 0（零漂移证明）。

### 如何验证

```bash
pytest tests/test_fingerprint_stability.py -v
python scripts/migrate_fingerprints.py --dry-run   # 输出将变更的节点清单
python scripts/migrate_fingerprints.py
python -m mms.cli bootstrap tests/fixtures/spring-boot-demo  # 断言 0 新增 0 归档
```

---

## 任务 3.4 默认启用与 CI 接入

### 工作内容

1. `config.yaml` 默认 `use_tree_sitter: true`（依赖缺失时 factory 已有自动降级 + warning，行为安全）；
2. CI（`.github/workflows/ci.yml`）安装 `.[tree_sitter]`，并将 4 fixture 集成测试在 **tree-sitter 与 regex 两种模式下各跑一遍**（矩阵或双 step），防止降级路径腐化；
3. `boot_readme.md` 与 `layer2_readme.md` 的解析器章节更新。

### 涉及文件

| 文件 | 操作 |
|---|---|
| `docs/memory/_system/config.yaml` | 修改：默认值 |
| `.github/workflows/ci.yml` | 修改：依赖安装 + 双模式测试 |
| `src/mms/bootstrap/boot_readme.md`、`layer2_readme.md` | 修改：文档同步 |

### 达到的标准

- CI 双模式全绿；
- tree-sitter 模式下 4 个 fixture 的层级分布相对基线不回退（`UNKNOWN` 比例不升高，conflict 数不增加），NestJS fixture 因 decorator 信号增强预期改善。

### 如何验证

- CI 运行记录；
- `python scripts/benchmark_baseline.py --compare-bootstrap benchmarks/baseline.json`：输出层级分布对比表，人工确认改善项并将数值写入 PR 描述。

---

## Phase 3 整体验收

- [x] 4 个 fixture Bootstrap 全绿；三种非 Python fixture 双模式 fingerprint 100% 一致；
- [x] 真实仓库 `migrate_fingerprints.py --dry-run` 输出 0 个待迁移节点；
- [x] Tree-sitter 相对 Regex 端到端解析耗时增幅 7.0%，低于 50% 门槛；
- [x] 回退方案：`use_tree_sitter: false` 一键回退，fingerprint 保持不变。
