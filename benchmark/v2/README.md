# 木兰 Benchmark v2 — 三层模块化评测框架

> 评测的目的不是给工具打分，而是**找到它的弱点**。  
> 每一个 FAILED case 都是一个未修复的 bug 或一条未覆盖的规则。

---

## 核心命题

木兰 Benchmark v2 所验证的核心命题是：

> **动态本体路由（Vectorless Ontology Routing）在代码生成质量、安全性、知识留存上，是否系统性地优于传统纯文本 BM25 检索？**

| 对比维度 | 传统方案（BM25 / ES / Milvus） | 木兰本体路由 |
|---|---|---|
| 检索粒度 | 文档级关键词匹配 | 概念图谱 + 语义哈希 + 架构层过滤 |
| 上下文质量 | 全量噪音（依赖向量相似度） | 精准注入（架构约束 + 记忆图谱） |
| 离线能力 | 依赖 ES/Milvus 服务 | **完全离线**（Layer 3 / Layer 2 D1/D4） |
| 可解释性 | 黑盒相似度分数 | 可溯源的 `about_concepts` + `cites_files` 链路 |
| 扩展方式 | 重新索引全量文档 | 向 `docs/memory/` 添加一个 Markdown 文件 |

> ⚠️ **已废弃**：v1 Benchmark 中的 "ES+Milvus 混合 RAG" 描述已完全移除。木兰不依赖任何向量数据库。

---

## 分层评估体系（L1 / L2 / L3）

```
┌─────────────────────────────────────────────────────────────────────┐
│  L1: SWE-bench 信用锚（Credibility Anchor）                          │
│  与工业标准基准对齐，证明"小模型+精准上下文 > 大模型+全量噪音"          │
│  核心指标：ΔPass@1（有/无记忆注入的代码通过率差值）                     │
│  运行条件：离线=格式验证；在线=需 LLM + Docker 沙盒                    │
├─────────────────────────────────────────────────────────────────────┤
│  L2: 记忆质量评测（Memory Quality）                                    │
│  验证"动态本体路由 → 代码生成质量提升"的核心价值主张                     │
│  核心指标：Info Density（信息密度）= ΔPass@1 / avg_injection_tokens   │
│  4 维度：D1 准确检索 / D2 注入提升 / D3 跨任务保留 / D4 漂移检测        │
│  运行条件：D1/D4 离线可运行；D2/D3 需 LLM API                          │
├─────────────────────────────────────────────────────────────────────┤
│  L3: 安全门控评测（Safety Gates）                                      │
│  验证"代码不上传，知识不泄露，架构不退化"的工程安全底线                  │
│  3 子系统：SanitizationGate / MigrationGate / ArchCheck              │
│  运行条件：完全离线，< 1 秒                                             │
└─────────────────────────────────────────────────────────────────────┘
```

### 分层指标速查表

| 层级 | 核心指标 | 目标值 | 是否需要 LLM |
|---|---|---|---|
| **L3 安全层** | SanitizeGate 检出率 | ≥ 90% | ❌ 完全离线 |
| **L3 安全层** | MigrationGate 阻断精度 | ≥ 85% | ❌ 完全离线 |
| **L3 安全层** | ArchCheck 覆盖率 | ≥ 75% | ❌ 完全离线 |
| **L2 记忆层** | Recall@5 (D1) | ≥ 0.60 | ❌ 离线可运行 |
| **L2 记忆层** | Info Density (D2) | > 0 | ✅ 需要 LLM |
| **L2 记忆层** | 漂移检出率 (D4) | ≥ 80% | ❌ 离线可运行 |
| **L1 执行层** | ΔPass@1 | > 0 | ✅ 需要 LLM + Docker |

### L2 核心指标说明：Info Density（信息密度）

```
Info Density = ΔPass@1 / avg_injection_tokens × 1000

其中：
  ΔPass@1          = Pass@1(有记忆注入) - Pass@1(无记忆注入)
  avg_injection_tokens = 平均注入的记忆 token 数

含义：每注入 1000 个记忆 token，代码通过率提升多少个百分点。

为何使用 Info Density 而非 Recall@K？
  - 传统 Recall@K 只验证"检索到了没有"，不验证"检索到的是否真正有用"
  - Info Density 直接度量记忆注入对下游任务的实际贡献
  - 对小模型（端侧 8B~32B）尤其关键：噪音注入会显著降低 Pass@1
```

---

## 企业级靶机（Enterprise Fixtures）

木兰 v3.0 引入了来自真实 GitHub 万星项目的结构化 Benchmark 靶机，代表真实的工业复杂度。

| 项目 | Stars | 领域 | 技术栈 | Case 数 |
|---|---|---|---|---|
| `macrozheng/mall` | 80k+ | 电商订单服务 | Java Spring Boot + MyBatis | 4 |
| `halo-dev/halo` | 35k+ | 内容管理模块 | Java Spring Boot + JPA | 2 |

### 为何选择这两个项目？

- **真实复杂度**：两者均是生产级 Java 单体/微服务项目，包含完整的 Service/Repository/Controller 分层
- **可验证性**：代码结构明确，AIU 类型和目标文件可精确标注 ground truth
- **无外部依赖**：所有测试基于提取的 fixture 代码片段，无需 clone 完整仓库或访问网络

> 测试用例位于 `benchmark/v2/layer2_memory/tasks/enterprise_projects/`

---

## 设计原则

| 原则 | 实现方式 |
|---|---|
| **分层隔离** | 三层独立评测，每层可单独运行，互不依赖 |
| **YAML 驱动** | 新增测试 case 只需在 `fixtures/` 或 `tasks/` 添加 YAML，无需修改代码 |
| **离线优先** | Layer 3 完全离线（< 1s）；Layer 2 D1/D4 维度离线可运行 |
| **公平对比** | Layer 1 对接 SWE-bench 行业标准，保证结果可信 |
| **模块注册** | 新增评测层只需继承 `BaseEvaluator` 并在 `runner.py` 注册，3 步完成 |

---

## 快速开始

```bash
# 离线模式（推荐：无需 LLM API，< 1 秒）
mulan benchmark

# 或直接运行独立入口
python3 benchmark/run_benchmark_v2.py

# 详细输出（展示每条 case 的结果）
mulan benchmark --verbose

# 快速模式（Layer 2 + Layer 3，需 LLM API）
mulan benchmark --level fast --llm

# 全量模式（全部三层，需 LLM API）
mulan benchmark --level full --llm

# 生成 Markdown 报告
mulan benchmark --output markdown --output-path reports/bench_$(date +%Y%m%d).md
```

---

## Layer 3：安全门控评测（完全离线）

### 三个子系统

#### SanitizationGate — 敏感凭证检测

验证 `src/mms/core/sanitize.py` 能否正确拦截各类敏感凭证。

| 类别 | 覆盖场景（fixture 数） | 指标 |
|---|---|---|
| API Key | 12 条（含阴性样例 3 条） | 检出率 / 误报率 |
| JWT / 密码 / IP / 邮箱 / DSN | 14 条 | 检出率（critical 级） |
| 误报防护 | 6 条 | 假阳性率（目标 = 0%） |

**检测类别：**

- OpenAI / DashScope `sk-` 前缀 API Key
- AWS Access Key（`AKIA` 前缀）
- GitHub Personal Access Token（`ghp_` 前缀）
- JWT Bearer Token（三段 Base64 格式）
- 内网 IP（10.x / 192.168.x / 172.16-31.x）
- 含密码的数据库连接字符串
- 企业内部邮箱

#### MigrationGate — ORM 变更阻断

验证 `src/mms/workflow/migration_gate.py` 能否正确阻断"ORM 变更但无迁移脚本"的场景。

| 场景 | 预期行为 |
|---|---|
| 新增 Model 字段，无迁移脚本 | 阻断 |
| 删除 Model 字段，无迁移脚本 | 阻断 |
| 新增整张表（Model 类），无迁移脚本 | 阻断 |
| 字段重命名，无迁移脚本 | 阻断 |
| 有完整 `up() / down()` 迁移 | 通过 |
| 无 ORM 变更（纯 Service 修改） | 不触发 |

#### ArchCheck — 架构约束扫描

验证架构规则检测覆盖率（AC-1~AC-6）。

| 规则 | 约束内容 | 阳性 case | 阴性 case |
|---|---|---|---|
| AC-1 | 禁止在非基础设施层直接 import 消息队列客户端（aiokafka） | 1 | 1 |
| AC-2 | Service 函数必须以 `RequestContext` 作为首参 | 1 | 1 |
| AC-3 | 写操作必须调用 `AuditService.log()` | 1 | 1 |
| AC-4 | API Endpoint 必须使用标准信封格式（`ResponseHelper`） | 1 | 1 |
| AC-5 | 禁止在 Service 层使用 `session.begin()`（使用 autobegin 模式） | 1 | 1 |
| AC-6 | 禁止裸 `print()` 调用（必须使用 structlog） | 1 | 1 |

### 综合得分计算

```
Layer 3 Score = SanitizeGate × 0.50 + MigrationGate × 0.30 + ArchCheck × 0.20
```

SanitizeGate 权重最高（0.50），因为敏感数据泄露是最严重的安全事件。

### 初次运行基线（2026-04-26）

```
Layer 3: 安全门控评测
  综合得分: 0.9474  （94.7%）
  任务总数: 46  通过: 43  失败: 3

  指标明细：
    sanitize.detection_rate:      0.9444  ← 1 条 AWS Secret 未检出（已记录为 bug）
    sanitize.false_positive_rate: 0.0000  ← 零误报 ✓
    sanitize.critical_misses:     1.0000  ← 1 条 critical 级别漏检
    migration.block_accuracy:     1.0000  ← 全部阻断场景正确 ✓
    arch.detection_rate:          0.8333  ← AC-3 / AC-4 正则待优化
```

> **3 个 FAILED case 的意义**：
>
> - `san_ak_005`（AWS Secret Key）：正则模式未覆盖斜杠格式，需在 `sanitize.py` 补充
> - `arc_ac3_002`（审计调用检测）：多行代码跨行匹配问题，需改为 AST 级扫描
> - `arc_ac4_001`（信封格式检测）：装饰器与返回值之间有函数体，正则无法跨行匹配

---

## Layer 2：记忆质量评测

### 四个子维度

#### D1 准确检索（Accurate Retrieval）— 离线可运行

评测 `hybrid_search` / `find_by_concept` 能否从记忆图谱中检索到必要知识。

```
指标：
  Recall@K    — 前 K 条结果中包含了多少"必要记忆"
  Precision@K — 前 K 条结果中有多少是真正相关的
  MRR         — 平均倒数排名（第一条相关结果的排名倒数均值）
  Hit@1       — 第一条就是相关记忆的比例

通过标准：Recall@5 ≥ 0.60
```

> D1 需要记忆库中存在 ground-truth 记忆节点。在空库状态下，D1 case 会被标记为 SKIPPED（等待填充 `relevant_ids`）。

#### D2 注入提升（Injection Lift）— 需要 LLM API

评测"有记忆注入 vs 无记忆注入"对代码生成质量的提升。

```
核心指标：
  ΔPass@1      = Pass@1(with_injection) - Pass@1(without_injection)
  Info Density = ΔPass@1 / avg_injection_tokens × 1000
                 （每注入 1000 token 带来的 Pass@1 提升）

无 LLM API 时：D2 全部 SKIPPED，其权重（0.35）转移给 D1（0.55）和 D4（0.45）
```

#### D3 跨任务保留（Cross-task Retention）— 待实现

评测任务 A 执行后沉淀的知识是否能帮助相关任务 B。当前版本为占位实现，不计入得分。

#### D4 漂移检测（Selective Forgetting）— 离线可运行

评测记忆新鲜度系统能否正确检测"代码被修改后，引用该代码的记忆应被标记为过时"。

```
评测方式（自包含，无需真实记忆库）：
  1. 构造初始代码内容 + 引用该代码的记忆文件
  2. 计算原始语义哈希
  3. 模拟代码变更（修改函数签名 / 仅添加注释 / 清空文件）
  4. 重新计算语义哈希，对比是否触发 drift

语义哈希：剔除注释和空行，只对核心签名行做 SHA256
  → 格式化工具（Black/gofmt）不会引起虚假漂移
  → 真实签名/类型变更会正确触发漂移
```

**D4 覆盖场景：**

| 场景 | 预期结果 |
|---|---|
| 函数参数类型 + 数量变更 | 触发漂移 |
| 仅添加注释和空行（gofmt / Black） | 不触发漂移 |
| 文件内容清空（模拟删除） | 触发漂移 |

### 综合得分计算

```
有 LLM API 时：
  Score = D1 × 0.35 + D2 × 0.35 + D4 × 0.30

无 LLM API 时（D2 全部 SKIPPED）：
  Score = D1 × 0.55 + D4 × 0.45
```

---

## Layer 1：SWE-bench 信用锚

### 定位

将木兰的代码生成能力与工业标准基准对齐，确保评测结果可被外部验证和比较。

### 核心价值主张验证

```
实验设计（双轨对比）：
  Baseline（无注入）：直接提供 Issue 描述，让 Coder 生成 patch
  Mulan-Enhanced（有注入）：注入木兰基于本体路由检索到的架构上下文

核心输出：
  ΔPass@1 = Pass@1(Mulan-Enhanced) - Pass@1(Baseline)
  目标：ΔPass@1 > 0，证明"端侧小模型+精准上下文 > 大模型+全量噪音"
```

### 离线模式（当前实现）

在无 LLM API 的环境下，Layer 1 执行：

- 任务格式完整性验证（6 个必填字段）
- `expected_aiu_type` 是否在 43 种内置类型中
- AIU 类型覆盖率统计

```
离线得分 = 格式合规率 × 0.6 + AIU 类型覆盖率 × 0.4
```

### 在线模式（待实现，接口已预留）

```python
# layer1_swebench/evaluator.py 中的扩展点：
if config.llm_available and not config.dry_run:
    # TODO: 调用 mulan ep run 生成 patch
    # TODO: 在 Docker 沙盒中运行 fail_tests → pass_tests
    # TODO: 计算 ΔPass@1 和 Resolve Rate vs Baseline
    pass
```

在线模式的完整流程：

1. 读取 SWE-bench 任务（本地 YAML 或 princeton-nlp/SWE-bench HuggingFace 数据集）
2. 为每个任务调用 `mulan ep run` 生成 patch（Mulan-Enhanced 组）
3. 同任务使用裸 LLM（无记忆注入）生成 patch（Baseline 组）
4. 在 Docker 沙盒中执行 `fail_tests`，验证 `pass_tests` 是否全部通过
5. 计算 ΔPass@1 和 Info Density

### 内置样本任务

| ID | 仓库 | 难度 | AIU 类型 |
|---|---|---|---|
| `swe_django_001` | django/django | 中 | BUG_FIX |
| `swe_django_002` | django/django | 易 | BUG_FIX |
| `swe_fastapi_001` | tiangolo/fastapi | 中 | BUG_FIX |
| `swe_sqlalchemy_001` | sqlalchemy/sqlalchemy | 难 | BUG_FIX |

---

## 扩展指南

### 新增 Sanitize 检测 case

在 `layer3_safety/fixtures/sanitize/` 下创建或编辑 YAML 文件：

```yaml
schema_version: "1.0"
gate: "SanitizationGate"

cases:
  - id: san_new_001
    category: api_key          # api_key / jwt / internal_ip / password / email / connection_string
    description: "Anthropic Claude API Key（新格式）"
    input: "ANTHROPIC_KEY=sk-ant-newformat-abcdefghij"
    should_detect: true        # true = 应检出；false = 不应检出（阴性样例）
    severity: critical         # critical / high / medium
```

**无需修改任何 Python 代码**，评测器自动加载新文件。

### 新增 ArchCheck 规则 case

在 `layer3_safety/fixtures/arch/violations.yaml` 添加 case（同时在 `ArchCheckSubEvaluator._RULES` 添加对应正则）：

```yaml
  - id: arc_ac7_001
    rule_id: "AC-7"
    description: "新规则：禁止 Service 层直接读取环境变量"
    code: |
      import os
      async def get_db_url():
          return os.environ.get("DATABASE_URL")
    expected_violations: 1
    should_flag: true
```

### 新增记忆质量检索 case

在 `layer2_memory/tasks/<domain>/` 下创建 YAML 文件：

```yaml
schema_version: "1.0"
domain: "spring_boot"
category: "retrieval"

cases:
  - id: sb_ret_001
    description: "Spring Boot @Transactional 相关记忆检索"
    query: "Spring Boot transaction propagation rollback"
    relevant_ids:
      - "MEM-L-045"
      - "AD-012"
    domain_concepts: ["transaction", "spring-boot", "rollback"]
    k: 5
```

### 新增企业级靶机项目

1. 在 `layer2_memory/tasks/enterprise_projects/<project_name>/` 创建目录
2. 添加 `README.md`（项目背景说明）
3. 添加 `*_cases.yaml`（测试用例，含 fixture 代码片段）
4. 评测器自动扫描并加载

### 新增评测层（4 步完成）

```python
# 步骤 1: 创建目录 benchmark/v2/layer4_<name>/

# 步骤 2: 实现 Evaluator
from benchmark.v2.schema import BaseEvaluator, BenchmarkLayer, BenchmarkConfig, LayerResult

class MyEvaluator(BaseEvaluator):
    @property
    def layer(self) -> BenchmarkLayer:
        return BenchmarkLayer.LAYER4_NEW

    @property
    def is_offline_capable(self) -> bool:
        return True

    def run(self, config: BenchmarkConfig) -> LayerResult:
        ...

# 步骤 3: 在 schema.py 中扩展枚举
class BenchmarkLayer(Enum):
    LAYER4_NEW = 4  # 新增

# 步骤 4: 在 runner.py 中注册
_EVALUATOR_REGISTRY[BenchmarkLayer.LAYER4_NEW] = MyEvaluator
_LEVEL_LAYERS[RunLevel.FULL].append(BenchmarkLayer.LAYER4_NEW)
```

---

## 文件结构

```
benchmark/v2/
├── README.md                        # 本文件
├── __init__.py                      # 公共 API 导出
├── schema.py                        # 共享数据结构
├── runner.py                        # 主调度器
├── config.yaml                      # 默认阈值配置
│
├── layer1_swebench/                 # L1: SWE-bench 信用锚层
│   ├── evaluator.py
│   └── tasks/
│       └── sample_django_001.yaml   # 内置样本任务（4 个）
│
├── layer2_memory/                   # L2: 记忆质量评测层
│   ├── evaluator.py
│   ├── metrics/
│   │   ├── retrieval.py             # D1 准确检索（Recall@K / MRR / Hit@1）
│   │   ├── injection_lift.py        # D2 注入提升（ΔPass@1 / Info Density）
│   │   ├── retention.py             # D3 跨任务保留（占位）
│   │   ├── drift.py                 # D4 漂移检测（语义哈希对比）
│   │   └── funnel.py                # 三层漏斗检索评测
│   ├── fixtures/memories/           # 漏斗测试 ground-truth 记忆节点
│   └── tasks/
│       ├── generic_python/          # Python 通用检索 / 漂移 case
│       ├── funnel_test/             # 三层检索漏斗验证 case（9 个）
│       └── enterprise_projects/
│           ├── mall_order/          # macrozheng/mall 订单服务（4 case）
│           └── halo_content/        # halo-dev/halo 内容管理（2 case）
│
├── layer3_safety/                   # L3: 安全门控评测层（完全离线）
│   ├── evaluator.py
│   └── fixtures/
│       ├── sanitize/                # 凭证检测（26 个 case）
│       ├── migration/               # ORM 变更拦截（8 个 case）
│       └── arch/                    # 架构规则（12 个 case，AC-1~AC-6）
│
└── reporters/                       # 报告输出
    ├── console.py                   # 彩色终端
    └── markdown.py                  # GitHub 可渲染 Markdown
```

---

## CLI 参数参考

```bash
mulan benchmark [OPTIONS]

选项：
  --level {offline,fast,full}    运行级别（默认: offline）
                                 offline = 仅 Layer 3，无需 LLM API，< 1s
                                 fast    = Layer 2 + Layer 3，需 LLM API
                                 full    = 全部三层，需 LLM API + Docker
  --layer {1,2,3}                仅运行指定单层（覆盖 --level）
  --domain DOMAIN [DOMAIN...]    评测 domain（默认: generic_python）
  --llm                          声明 LLM API 可用（开启在线评测维度）
  --dry-run                      仅打印将要执行的任务，不实际运行
  --output {console,json,markdown}  报告格式（默认: console）
  --output-path PATH             报告保存路径
  --max-tasks N                  每层最多运行任务数（调试用）
  -v, --verbose                  详细输出（展示每条 case 的结果）
```

---

## 评测层权重与阈值

权重和阈值在 `config.yaml` 中配置，无需修改代码：

```yaml
layer3:
  weights:
    sanitize:  0.50
    migration: 0.30
    arch:      0.20
  sanitize_critical_min_detection_rate: 0.90
  migration_min_block_accuracy: 0.85
  arch_min_detection_rate: 0.75

layer2:
  weights:
    d1_retrieval: 0.35
    d2_injection: 0.35
    d4_drift:     0.30
  retrieval_min_recall_at_5: 0.60
  drift_min_detection_rate:  0.80

layer1:
  min_format_compliance: 1.00
  min_aiu_coverage: 0.50
  target_delta_pass_at_1: 0.10   # ΔPass@1 目标：Mulan-Enhanced 比 Baseline 至少提升 10pp
  target_resolve_rate: 0.45
```

---

## 与 v1 Benchmark 的关系

| 维度 | v1 Benchmark | v2 Benchmark |
|---|---|---|
| 定位 | 验证记忆检索 vs keyword 的优劣 | 全面评测木兰工具链的三大核心价值 |
| 检索方案 | 向量数据库（ES/Milvus 可选）+ LLM | **本体路由**（无向量库）+ 语义哈希 |
| 依赖 | 需 ES/Milvus + LLM API | Layer 3 完全离线；Layer 2 D1/D4 离线 |
| 扩展性 | 固定指标，需修改代码添加场景 | YAML 驱动，添加 case 无需改代码 |
| 行业对齐 | 内部 MDP 任务集 | SWE-bench Verified（Layer 1 信用锚）|
| 测试覆盖 | ~20 个任务 | 58+ 个（可通过 synthetic pipeline 扩充至 300+）|
| 企业靶机 | 无 | mall (80k⭐) + halo (35k⭐) 真实工业用例 |

v1 Benchmark 代码保留在 `benchmark/src/` 目录，向后兼容。

---

## 合成数据生成

```bash
# 从当前仓库的 commit 生成合成测试 case（dry-run 预览）
python3 scripts/benchmark_generator.py --repo . --max 20 --dry-run

# 真实生成（写入 benchmark/v2/layer2_memory/tasks/synthetic/）
python3 scripts/benchmark_generator.py --repo /path/to/target-repo --max 50

# 启用 LLM 自动生成意图描述（需配置百炼 API）
python3 scripts/benchmark_generator.py --repo . --max 20 --llm
```

生成的 case 默认标记 `reviewed: false`，不参与主评测。审核后改为 `reviewed: true` 即可。

> **防过拟合设计**：合成数据单独存放在 `tasks/synthetic/`，通过 `--include-synthetic`
> 标志才会参与评测，并在报告中与 human case 分开呈现。

---

## 测试

Benchmark v2 本身也有完整的单元测试：

```bash
# 仅运行 Benchmark 测试
pytest tests/benchmark/ -v

# 覆盖内容：
# - test_schema.py              Schema 数据结构
# - test_layer3_safety.py       SanitizeGate / MigrationGate / ArchCheck
# - test_layer2_memory.py       检索指标计算 / 漂移检测 / 注入提升（离线）
# - test_layer1_swebench.py     任务格式验证 / AIU 类型覆盖
# - test_phase4_pass_at_1.py    SandboxedCodeRunner / dual-rail 降级
```
