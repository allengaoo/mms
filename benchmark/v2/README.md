# 木兰 Benchmark v2 — 三层模块化评测框架

> 评测的目的不是给工具打分，而是**找到它的弱点**。  
> 每一个 FAILED case 都是一个未修复的 bug 或一条未覆盖的规则。

---

## 设计原则

| 原则       | 实现方式                                            |
| -------- | ----------------------------------------------- |
| **分层隔离** | 三层独立评测，每层可单独运行，互不依赖                             |
| **YAML 驱动** | 新增测试 case 只需在 `fixtures/` 或 `tasks/` 添加 YAML，无需修改代码 |
| **离线优先** | Layer 3 完全离线（< 1s）；Layer 2 D1/D4 维度离线可运行        |
| **公平对比** | Layer 1 对接 SWE-bench 行业标准，保证结果可信                |
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

## 三层架构

```
┌─────────────────────────────────────────────────────────────────────┐
│  Layer 1: SWE-bench 信用锚（Credibility Anchor）                     │
│  对接 princeton-nlp/SWE-bench，与工业标准对齐                         │
│  核心指标：Pass@1 / Resolve Rate vs. baseline                        │
│  运行条件：离线=格式验证；在线=需 LLM + Docker 沙盒                   │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 2: 记忆质量评测（Memory Quality）                              │
│  验证木兰"记忆 → 代码质量提升"的核心价值主张                            │
│  4 个子维度：D1 准确检索 / D2 注入提升 / D3 跨任务保留 / D4 漂移检测     │
│  运行条件：D1/D4 离线可运行；D2/D3 需 LLM API                         │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 3: 安全门控评测（Safety Gates）                                │
│  验证木兰"代码不上传，知识不泄露"的工程安全底线                          │
│  3 个子系统：SanitizationGate / MigrationGate / ArchCheck            │
│  运行条件：完全离线，< 1 秒                                            │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Layer 3：安全门控评测（完全离线）

### 三个子系统

#### SanitizationGate — 敏感凭证检测

验证 `src/mms/core/sanitize.py` 能否正确拦截各类敏感凭证。

| 类别          | 覆盖场景（fixture 数）  | 指标              |
| ----------- | ---------------- | --------------- |
| API Key     | 12 条（含阴性样例 3 条）  | 检出率 / 误报率       |
| JWT / 密码 / IP / 邮箱 / DSN | 14 条  | 检出率（critical 级） |
| 误报防护        | 6 条              | 假阳性率（目标 = 0%）   |

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

| 场景                    | 预期行为 |
| --------------------- | ---- |
| 新增 Model 字段，无迁移脚本     | 阻断   |
| 删除 Model 字段，无迁移脚本     | 阻断   |
| 新增整张表（Model 类），无迁移脚本  | 阻断   |
| 字段重命名，无迁移脚本           | 阻断   |
| 有完整 `up() / down()` 迁移 | 通过   |
| 无 ORM 变更（纯 Service 修改） | 不触发  |

#### ArchCheck — 架构约束扫描

验证架构规则检测覆盖率（AC-1~AC-6）。

| 规则   | 约束内容                                              | 阳性 case | 阴性 case |
| ---- | ------------------------------------------------- | ------- | ------- |
| AC-1 | 禁止在非基础设施层直接 import 消息队列客户端（aiokafka）              | 1       | 1       |
| AC-2 | Service 函数必须以 `RequestContext` 作为首参               | 1       | 1       |
| AC-3 | 写操作必须调用 `AuditService.log()`                      | 1       | 1       |
| AC-4 | API Endpoint 必须使用标准信封格式（`ResponseHelper`）         | 1       | 1       |
| AC-5 | 禁止在 Service 层使用 `session.begin()`（使用 autobegin 模式） | 1       | 1       |
| AC-6 | 禁止裸 `print()` 调用（必须使用 structlog）                  | 1       | 1       |

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
> - `san_ak_005`（AWS Secret Key）：正则模式未覆盖斜杠格式，需在 `sanitize.py` 补充
> - `arc_ac3_002`（审计调用检测）：多行代码跨行匹配问题，需改为 AST 级扫描
> - `arc_ac4_001`（信封格式检测）：装饰器与返回值之间有函数体，正则无法跨行匹配

---

## Layer 2：记忆质量评测

### 四个子维度

#### D1 准确检索（Accurate Retrieval）— 离线可运行

评测 `hybrid_search` / `find_by_concept` 能否从记忆图谱中检索到必要知识。

```python
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

```python
指标：
  lift_pass_at_1   = Pass@1(with_injection) - Pass@1(without_injection)
  token_roi        = lift_pass_at_1 / avg_injection_tokens * 1000
                     （每千个注入 token 带来的 Pass@1 提升）

无 LLM API 时：D2 全部 SKIPPED，其权重（0.35）转移给 D1（0.55）和 D4（0.45）
```

#### D3 跨任务保留（Cross-task Retention）— 待实现

评测任务 A 执行后沉淀的知识是否能帮助相关任务 B。当前版本为占位实现，不计入得分。

#### D4 漂移检测（Selective Forgetting）— 离线可运行

评测记忆新鲜度系统能否正确检测"代码被修改后，引用该代码的记忆应被标记为过时"。

```python
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

| 场景                       | 预期结果  |
| ------------------------ | ----- |
| 函数参数类型 + 数量变更            | 触发漂移  |
| 仅添加注释和空行（gofmt / Black）   | 不触发漂移 |
| 文件内容清空（模拟删除）             | 触发漂移  |

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

### 离线模式（当前实现）

在无 LLM API 的环境下，Layer 1 执行：
- 任务格式完整性验证（6 个必填字段）
- `expected_aiu_type` 是否在 28 种内置类型中
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
    # TODO: 计算 Pass@1 和 Resolve Rate
    pass
```

在线模式的完整流程：
1. 读取 SWE-bench 任务（本地 YAML 或 princeton-nlp/SWE-bench HuggingFace 数据集）
2. 为每个任务调用 `mulan ep run` 生成 patch
3. 在 Docker 沙盒中执行 `fail_tests`，验证 `pass_tests` 是否全部通过
4. 与 baseline（直接 LLM，无记忆注入）对比，计算 ΔPass@1

### 内置样本任务

| ID                 | 仓库             | 难度   | AIU 类型    |
| ------------------ | -------------- | ---- | --------- |
| `swe_django_001`   | django/django  | 中    | BUG_FIX   |
| `swe_django_002`   | django/django  | 易    | BUG_FIX   |
| `swe_fastapi_001`  | tiangolo/fastapi | 中  | BUG_FIX   |
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

### 新增 Migration 测试场景

在 `layer3_safety/fixtures/migration/` 下创建或编辑 YAML 文件：

```yaml
schema_version: "1.0"
gate: "MigrationGate"

cases:
  - id: mig_new_001
    category: constraint_add_no_migration
    description: "新增唯一约束，无迁移脚本 → 应阻断"
    orm_diff: |
      +    __table_args__ = (UniqueConstraint("user_id", "tenant_id"),)
    migration_files: []
    should_block: true
    severity: critical
```

### 新增 ArchCheck 规则 case

在 `layer3_safety/fixtures/arch/violations.yaml` 添加 case：

```yaml
  - id: arc_ac7_001
    rule_id: "AC-7"           # 与 arch_check.py 中的新规则 ID 一致
    description: "新规则：禁止 Service 层直接读取环境变量"
    code: |
      import os
      async def get_db_url():
          return os.environ.get("DATABASE_URL")
    expected_violations: 1
    should_flag: true
```

同时在 `ArchCheckSubEvaluator._RULES` 中添加对应正则。

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
      - "MEM-L-045"    # 填写真实记忆 ID
      - "AD-012"
    domain_concepts: ["transaction", "spring-boot", "rollback"]
    k: 5
```

### 新增 D4 漂移检测场景

在 `layer2_memory/tasks/<domain>/` 下创建 `*_drift.yaml`：

```yaml
schema_version: "1.0"
domain: "go_gin"
category: "drift"

cases:
  - id: go_drift_001
    description: "Go Gin handler 返回类型变更"
    memory_content: |
      ---
      id: MEM-DRIFT-001
      cites_files:
        - "{cited_file}"
      ---
      # 用户 API 规范
      GET /users/:id 返回 UserResponse 结构体。
    cited_file_content: |
      func GetUser(c *gin.Context) {
          c.JSON(200, UserResponse{})
      }
    modified_content: |
      func GetUser(c *gin.Context) (UserResponse, error) {
          return UserResponse{}, nil
      }
    should_drift: true
```

### 新增评测层（4 步完成）

```python
# 步骤 1: 创建目录 benchmark/v2/layer4_<name>/

# 步骤 2: 实现 Evaluator
# benchmark/v2/layer4_<name>/evaluator.py
from benchmark.v2.schema import BaseEvaluator, BenchmarkLayer, BenchmarkConfig, LayerResult

class MyEvaluator(BaseEvaluator):

    @property
    def layer(self) -> BenchmarkLayer:
        return BenchmarkLayer.LAYER4_NEW  # 先在 schema.py 的 BenchmarkLayer 枚举中添加

    @property
    def is_offline_capable(self) -> bool:
        return True  # 如果可以离线运行

    def run(self, config: BenchmarkConfig) -> LayerResult:
        # 实现评测逻辑
        ...

# 步骤 3: 在 schema.py 中扩展枚举
class BenchmarkLayer(Enum):
    LAYER1_SWEBENCH = 1
    LAYER2_MEMORY   = 2
    LAYER3_SAFETY   = 3
    LAYER4_NEW      = 4  # 新增

# 步骤 4: 在 runner.py 中注册
from benchmark.v2.layer4_new.evaluator import MyEvaluator

_EVALUATOR_REGISTRY = {
    ...
    BenchmarkLayer.LAYER4_NEW: MyEvaluator,  # 注册
}
_LEVEL_LAYERS[RunLevel.FULL].append(BenchmarkLayer.LAYER4_NEW)
```

---

## 文件结构

```
benchmark/v2/
├── README.md                        # 本文件
├── __init__.py                      # 公共 API 导出
├── schema.py                        # 共享数据结构
│   ├── BenchmarkLayer（层级枚举）
│   ├── RunLevel（运行级别：offline/fast/full）
│   ├── TaskResult（单任务结果）
│   ├── LayerResult（单层汇总）
│   ├── BenchmarkResult（整体结果）
│   ├── BenchmarkConfig（运行配置）
│   └── BaseEvaluator（评测器基类）
│
├── runner.py                        # 主调度器
│   ├── _EVALUATOR_REGISTRY          # 评测器注册表（扩展入口）
│   ├── _LEVEL_LAYERS                # 各级别默认层配置
│   ├── run_benchmark()              # 核心执行函数
│   ├── report()                     # 报告输出路由
│   └── main()                      # CLI 入口
│
├── config.yaml                      # 默认阈值配置
│
├── layer1_swebench/                 # SWE-bench 信用锚层
│   ├── __init__.py
│   ├── evaluator.py                 # SWEBenchEvaluator
│   └── tasks/
│       └── sample_django_001.yaml   # 内置样本任务（4 个）
│
├── layer2_memory/                   # 记忆质量评测层
│   ├── __init__.py
│   ├── evaluator.py                 # MemoryEvaluator（4 个子维度）
│   ├── metrics/
│   │   ├── __init__.py
│   │   ├── retrieval.py             # D1 准确检索（Recall@K / MRR / Hit@1）
│   │   ├── injection_lift.py        # D2 注入提升（ΔPass@1 / Token ROI）
│   │   ├── retention.py             # D3 跨任务保留（占位，待实现）
│   │   └── drift.py                 # D4 漂移检测（语义哈希对比）
│   └── tasks/
│       └── generic_python/
│           ├── gp_retrieval.yaml    # D1 检索 case（5 个）
│           └── gp_drift.yaml        # D4 漂移 case（3 个）
│
├── layer3_safety/                   # 安全门控评测层（完全离线）
│   ├── __init__.py
│   ├── evaluator.py                 # SafetyEvaluator（3 个子评测器）
│   │   ├── SanitizeSubEvaluator     # 凭证检测
│   │   ├── MigrationSubEvaluator    # ORM 变更拦截
│   │   └── ArchCheckSubEvaluator    # 架构规则扫描
│   └── fixtures/
│       ├── sanitize/
│       │   ├── api_keys.yaml        # 12 个 API Key case
│       │   └── secrets.yaml         # 14 个 JWT/IP/密码/邮箱 case
│       ├── migration/
│       │   └── orm_migration.yaml   # 8 个 ORM 变更 case
│       └── arch/
│           └── violations.yaml      # 12 个架构违规 case（AC-1~AC-6 各 2 个）
│
└── reporters/                       # 报告输出
    ├── __init__.py
    ├── console.py                   # 彩色终端输出
    └── markdown.py                  # GitHub 可渲染 Markdown 报告
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
  --output-path PATH             报告保存路径（json/markdown 格式时有效）
  --max-tasks N                  每层最多运行任务数（调试用）
  -v, --verbose                  详细输出（展示每条 case 的结果）
```

---

## 评测层权重与阈值

权重和阈值在 `config.yaml` 中配置，无需修改代码：

```yaml
layer3:
  weights:
    sanitize:  0.50    # SanitizationGate 权重最高（安全底线）
    migration: 0.30
    arch:      0.20
  sanitize_critical_min_detection_rate: 0.90   # critical 检出率警戒线
  migration_min_block_accuracy: 0.85           # 阻断精度警戒线
  arch_min_detection_rate: 0.75                # 规则覆盖率警戒线

layer2:
  weights:
    d1_retrieval: 0.35
    d2_injection: 0.35    # 无 LLM 时权重转移
    d4_drift:     0.30
  retrieval_min_recall_at_5: 0.60
  drift_min_detection_rate:  0.80

layer1:
  min_format_compliance: 1.00    # 格式合规性 100%
  min_aiu_coverage: 0.50         # AIU 类型覆盖率 50%
  target_pass_at_1: 0.30         # 在线目标（参考值）
  target_resolve_rate: 0.45
```

---

## 与 v1 Benchmark 的关系

| 维度     | v1 Benchmark                | v2 Benchmark                     |
| ------ | --------------------------- | -------------------------------- |
| 定位     | 验证记忆检索 vs keyword 的优劣       | 全面评测木兰工具链的三大核心价值               |
| 依赖     | 需要向量数据库（可选）+ LLM API       | Layer 3 完全离线；Layer 2 D1/D4 离线   |
| 扩展性    | 固定指标，需修改代码添加场景              | YAML 驱动，添加 case 无需改代码            |
| 行业对齐   | 内部 MDP 任务集                  | SWE-bench Verified（Layer 1 信用锚）  |
| 测试覆盖   | ~20 个任务                     | 46 个 L3 + 8 个 L2 + 4 个 L1 = 58+  |

v1 Benchmark 代码保留在 `benchmark/src/` 目录，向后兼容。

---

## 测试

Benchmark v2 本身也有完整的单元测试：

```bash
# 仅运行 Benchmark 测试（63 个用例）
pytest tests/benchmark/ -v

# 覆盖内容：
# - test_schema.py         Schema 数据结构
# - test_layer3_safety.py  SanitizeGate / MigrationGate / ArchCheck
# - test_layer2_memory.py  检索指标计算 / 漂移检测 / 注入提升（离线）
# - test_layer1_swebench.py 任务格式验证 / AIU 类型覆盖
```
