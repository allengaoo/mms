# MMS — Memory Management System

> **AI Agent 驱动的结构化工程知识管理系统**
>
> 跨会话积累经验教训、在每次任务前注入相关上下文、扫描架构约束、控制文档熵 ——
> 全部基于纯文本，无需向量数据库，无强制第三方运行时依赖。

[![CI](https://github.com/allengaoo/mms/actions/workflows/ci.yml/badge.svg)](https://github.com/allengaoo/mms/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 为什么需要 MMS？

现代 AI 编码 Agent（Cursor、Copilot 等）天生无状态——每次会话结束后一切归零。
MMS 充当**持久化结构化记忆层**，解决以下问题：

| 问题 | MMS 解决方案 |
|------|-------------|
| AI 反复犯相同错误 | 带严重程度标签的结构化记忆 |
| AI 幻想架构规则 | `arch_check.py` 机械化约束扫描器（6 条红线 AC-1~AC-6）|
| 无关上下文浪费 Token | 三级检索漏斗（每次任务 < 4k tokens）|
| 新项目冷启动无历史 | `mms bootstrap` —— AST 骨架 + 种子包，< 1 秒 |
| 文档与代码逐渐偏离 | AST Diff + 本体自动同步（`postcheck`）|

---

## 快速开始

### 1. 安装

```bash
# 克隆项目
git clone https://github.com/allengaoo/mms.git
cd mms

# 核心依赖（大多数功能无需 LLM）
pip install pyyaml structlog

# 可选：百炼（阿里云）LLM 支持
pip install openai dashscope

# 可选：Benchmark（需要 Elasticsearch + Milvus）
pip install pymilvus elasticsearch numpy
```

### 2. 冷启动新项目

```bash
# 在你的项目根目录执行（自动扫描 AST、检测技术栈、注入种子知识）
MMS_PROJECT_ROOT=$(pwd) python3 /path/to/mms/cli.py bootstrap
```

### 3. 配置 LLM Provider

```bash
cp .env.example .env.memory
# 编辑 .env.memory 填入 API Key
```

### 4. 开始任务工作流

```bash
# 意图合成 → 生成执行计划草稿
mms synthesize "新增用户头像上传接口" --template ep-backend-api

# 编码前：建立基线 + 分析影响范围
mms precheck --ep EP-001

# 编码后：质量验收 + 知识蒸馏
mms postcheck --ep EP-001
mms distill --ep EP-001
```

---

## 核心工作流（7 步闭环）

```
① mms synthesize "<任务>" --template <类型>    # 意图合成（三级漏斗）
② 确认 EP（用户审阅执行计划）                   # 规划
③ mms precheck --ep EP-NNN                    # 前置检查（建立基线）
④ mms unit generate --ep EP-NNN              # 生成 DAG（可选，适合复杂 EP）
⑤ 按 EP Unit 修改代码 + 生成测试               # 执行
⑥ mms postcheck --ep EP-NNN                  # 后校验（pytest + arch_check + 文档偏移）
⑦ mms distill --ep EP-NNN                    # 知识蒸馏（沉淀到 shared 记忆）
```

或者使用全自动管道（LLM 驱动）：

```bash
mms ep run --ep EP-NNN                        # 全自动执行（3-Strike 重试 + 沙箱回滚）
mms ep run --ep EP-NNN --dry-run              # 预览代码变更（不写文件）
mms ep run --ep EP-NNN --confirm              # 写入前逐步确认
```

---

## 项目结构

```
mms/
├── cli.py                  # 统一 CLI 入口（mms <command>）
│
├── 意图与规划
│   ├── synthesizer.py      # EP 合成：任务 → 执行计划草稿
│   ├── intent_classifier.py # 三级意图漏斗（RBO + LLM 降级）
│   ├── task_decomposer.py  # AIU 原子分解（28 种意图类型）
│   ├── unit_generate.py    # DAG 生成（capable model 编排）
│   └── ep_parser.py        # 解析 EP Markdown → DagState
│
├── 执行与验证
│   ├── unit_runner.py      # AIU 执行（3-Strike 重试 + 反馈回滚）
│   ├── unit_compare.py     # LLM 代码评审（Qwen3-32B 评估器）
│   ├── unit_context.py     # Unit 上下文生成（token 受限）
│   ├── unit_cmd.py         # Unit 命令执行（子进程 + 超时）
│   ├── ep_runner.py        # 自动化 EP 管道（mms ep run）
│   └── ep_wizard.py        # 交互式 EP 向导
│
├── 记忆与检索
│   ├── injector.py         # 记忆注入（检索 + 压缩 → Cursor 提示词前缀）
│   ├── precheck.py         # 前置检查门控（arch_check 基线 + 影响分析）
│   ├── postcheck.py        # 后校验质量门（10 维度 + 文档偏移检测）
│   ├── dream.py            # autoDream：自动从 EP 萃取知识草稿
│   ├── entropy_scan.py     # 检测孤立/过期记忆
│   └── model_tracker.py    # LLM 调用次数与成本追踪
│
├── 代码分析
│   ├── arch_check.py       # 架构约束扫描（6 条红线 AC-1~AC-6）
│   ├── arch_resolver.py    # 层到文件路径解析器
│   ├── ast_skeleton.py     # AST 解析：提取类/函数签名
│   ├── ast_diff.py         # AST Diff：检测合约变更
│   ├── ontology_syncer.py  # 从 AST 变更同步本体 YAML
│   ├── repo_map.py         # 上下文排序文件图（PageRank 启发）
│   ├── graph_resolver.py   # 导入依赖图分析
│   ├── dep_sniffer.py      # 从依赖文件检测技术栈
│   ├── codemap.py          # 生成项目目录快照
│   ├── funcmap.py          # 生成函数级签名索引
│   └── doc_drift.py        # 文档偏移检测
│
├── 工具与基础设施
│   ├── dag_model.py        # DagUnit / DagState 数据模型
│   ├── aiu_types.py        # 28 种原子意图类型（6 个家族）
│   ├── aiu_cost_estimator.py # CBO 风格的 AIU 成本估算
│   ├── aiu_feedback.py     # 三级回滚反馈（类 DB Query Feedback）
│   ├── atomicity_check.py  # 检查 Unit 是否足够原子化
│   ├── sandbox.py          # Git 沙箱（安全文件操作）
│   ├── file_applier.py     # 解析并应用 LLM BEGIN/END-CHANGES 块
│   ├── template_lib.py     # EP 代码模板库（小模型脚手架）
│   ├── task_matcher.py     # 任务到模板的匹配器
│   ├── router.py           # 任务 → Provider 路由
│   ├── mms_config.py       # 集中配置加载器（config.yaml）
│   ├── fix_gen.py          # 自动生成架构修复建议
│   ├── ci_hook.py          # CI 集成钩子
│   ├── validate.py         # 记忆文件 Schema 校验
│   ├── verify.py           # 系统完整性检查
│   └── private.py          # EP 粒度私有记忆隔离
│
├── providers/              # LLM Provider 适配器
│   ├── factory.py          # 任务 → Provider 路由（MMS_TASK_MODEL_OVERRIDE）
│   ├── bailian.py          # 阿里云百炼（Qwen3-32B、Qwen3-Coder-Next）
│   ├── gemini.py           # Google Gemini（降级备用）
│   ├── claude.py           # Anthropic Claude（降级备用）
│   └── ollama.py           # Ollama 离线（deepseek-r1:8b、deepseek-coder-v2:16b）
│
├── trace/                  # 执行追踪（类 tkprof）
│   ├── tracer.py           # EPTracer：记录 LLM 调用、文件操作、事件
│   ├── collector.py        # 追踪数据采集
│   ├── reporter.py         # 追踪报告生成
│   └── event.py            # 追踪事件类型与级别
│
├── resilience/             # 可靠性原语
│   ├── retry.py            # 指数退避重试装饰器
│   ├── circuit_breaker.py  # LLM/API 调用熔断器
│   └── checkpoint.py       # 长时任务断点保存/恢复
│
├── core/                   # 核心 I/O 工具
│   ├── reader.py           # 文件读取（编码自检）
│   ├── writer.py           # 安全文件写入（原子操作 + 备份）
│   └── indexer.py          # 记忆索引构建器
│
├── seed_packs/             # 冷启动种子知识包
│   ├── base/               # 通用架构模式（安全、事务）
│   ├── fastapi_sqlmodel/   # FastAPI + SQLModel 模式
│   ├── react_zustand/      # React + Zustand 模式
│   └── palantir_arch/      # Palantir 风格本体模式
│
├── benchmark/              # 检索质量与代码生成质量评测
│   ├── run_benchmark.py    # 主 Benchmark 入口
│   ├── run_codegen.py      # 代码生成质量 Benchmark（EP-132）
│   ├── run_indexer.py      # Benchmark 索引构建
│   ├── data/
│   │   ├── queries.yaml         # 检索评测查询集
│   │   ├── queries_codegen.yaml # 代码生成任务集（20 条 MDP 后端任务）
│   │   └── corpus/              # 评测语料（通用软件工程模式）
│   └── src/
│       ├── evaluators/          # 4 级代码生成评估器
│       ├── metrics/             # 精度、效率、AIU 质量指标
│       ├── reporters/           # Markdown + JSON 报告
│       └── retrievers/          # PageIndex / HybridRAG / Ontology 检索器
│
├── docs/memory/            # 知识库（由 mms 命令填充）
│   ├── _system/            # 系统文件（config.yaml、codemap、task_quickmap）
│   ├── shared/             # 积累记忆（L1–L5 + cross_cutting）
│   ├── ontology/           # 动态本体定义（对象、链接、动作、函数）
│   └── templates/          # 按任务类型分类的 EP 模板
│
└── tests/                  # 测试套件（563+ 个用例）
```

---

## 核心概念

### 记忆层（L1–L5）

MMS 按软件架构的 5 个层次组织记忆：

| 层 | 关注点 | 示例 |
|----|--------|------|
| **L1** 平台层 | 安全、认证、配置 | 多租户、RBAC |
| **L2** 基础设施层 | 数据库、缓存、消息 | 事务模式、Kafka 消费者 |
| **L3** 领域层 | 业务逻辑 | 领域模型、实体规则 |
| **L4** 应用层 | Service、Worker | 作业执行、CQRS |
| **L5** 接口层 | API、前端、测试 | 响应格式、组件模式 |
| **CC** 横切关注点 | 架构决策 | ADR、全局约束 |

### 原子意图单元（AIU）

任务被分解为 6 个家族、28 种原子类型：

| 家族 | AIU 类型 |
|------|---------|
| **Schema** | `FIELD_ADD`, `FIELD_MODIFY`, `FIELD_REMOVE`, `TYPE_ADD`, `TYPE_MODIFY`, `INDEX_ADD` |
| **Endpoint** | `ENDPOINT_ADD`, `ENDPOINT_MODIFY`, `ENDPOINT_REMOVE`, `PERMISSION_ADD` |
| **Service** | `SERVICE_METHOD_ADD`, `SERVICE_METHOD_MODIFY`, `SERVICE_REFACTOR`, `CACHE_ADD` |
| **Infrastructure** | `QUERY_ADD`, `QUERY_MODIFY`, `MIGRATION_ADD`, `INFRA_ADAPTER_ADD` |
| **Test** | `UNIT_TEST_ADD`, `INTEGRATION_TEST_ADD`, `FIXTURE_ADD`, `MOCK_ADD` |
| **Orchestration** | `CONFIG_ADD`, `FEATURE_FLAG_ADD`, `EVENT_EMIT`, `DAG_RESTRUCTURE`, `VALIDATION_ADD`, `ERROR_CODE_ADD` |

### 三级意图漏斗

```
用户任务输入
     │
     ▼
[L1] 规则引擎分类（RBO）       ← 零 LLM 成本，~0ms
     │ 置信度 < 阈值
     ▼
[L2] 关键词 + 本体匹配         ← 本地查找，~5ms
     │ 置信度 < 阈值
     ▼
[L3] LLM 意图分类              ← 百炼降级，~500ms
     │
     ▼
AIU 分解 → DAG → 执行
```

### 查询反馈（三级回滚）

当 AIU 超出成本预算时（类比数据库 Query Feedback）：

```
Level 1: 扩展 Token 预算（1.5× 倍数）
Level 2: 插入前置 AIU（补充缺失上下文）
Level 3: 拆分 AIU 为更小单元
```

---

## CLI 命令参考

### EP 工作流

```bash
mms synthesize "<任务>" --template ep-backend-api   # 意图合成，生成 EP 草稿
mms precheck --ep EP-NNN                           # 前置检查（arch_check 基线）
mms postcheck --ep EP-NNN                          # 后校验（pytest + 文档偏移）
mms distill --ep EP-NNN                            # 知识蒸馏
mms distill --ep EP-NNN --dry-run                  # 预览蒸馏结果（不写入）
```

### Unit（DAG 任务单元）

```bash
mms unit generate --ep EP-NNN                      # 生成 DAG 执行计划
mms unit status --ep EP-NNN                        # 查看 DAG 进度
mms unit next --ep EP-NNN                          # 获取下一个可执行 Unit
mms unit context --ep EP-NNN --unit U1             # 生成 Unit 上下文
mms unit done --ep EP-NNN --unit U1                # 标记 Unit 完成
mms unit run --ep EP-NNN --unit U1                 # LLM 自动执行（3-Strike）
mms unit run-next --ep EP-NNN                      # 执行当前批次所有 Unit
mms unit run-all --ep EP-NNN                       # 执行全部 Unit（⚠️ 谨慎）
mms unit compare --ep EP-NNN --unit U1             # 语义代码评审（Qwen3-32B）
mms unit reset --ep EP-NNN --unit U1               # 回退 Unit 为 pending
```

### EP 自动化管道

```bash
mms ep run --ep EP-NNN                             # 全自动 EP 执行管道
mms ep run --ep EP-NNN --dry-run                   # 预览，不写文件
mms ep run --ep EP-NNN --confirm                   # 写入前逐步确认
mms ep start --ep EP-NNN                           # 启动/续跑 EP 向导
mms ep status --ep EP-NNN                          # 查看 EP 向导进度
```

### 记忆管理

```bash
mms inject "<任务描述>"                             # 记忆注入（生成提示词前缀）
mms search kafka replication k8s                   # 关键词检索记忆
mms list --tier hot                                # 列出热门记忆
mms list --layer L2_infrastructure                 # 按层过滤
mms distill --ep EP-NNN                            # 知识蒸馏
mms dream --ep EP-NNN                              # autoDream：自动萃取知识草稿
mms dream --list                                   # 列出草稿
mms dream --promote                                # 审核并提升为正式记忆
```

### 代码分析

```bash
mms arch-check                                     # 架构约束扫描（6 条红线）
mms ast-diff --before HEAD~1 --after HEAD          # AST 合约变更检测
mms graph stats                                    # 记忆图谱统计
mms graph explore MEM-L2-025                       # 从节点出发 BFS 遍历
mms graph impacts MEM-L2-025                       # 查询同步检查节点
mms codemap                                        # 生成目录快照
mms funcmap                                        # 生成函数签名索引
```

### 追踪与诊断

```bash
mms trace enable --ep EP-NNN                       # 开启诊断追踪
mms trace show --ep EP-NNN                         # 查看追踪报告（类 tkprof）
mms trace summary --ep EP-NNN                      # 一行摘要
mms trace list                                     # 列出所有有追踪记录的 EP
mms trace clean --ep EP-NNN                        # 清除追踪数据
```

### 系统管理

```bash
mms status                                         # 系统状态总览
mms bootstrap                                      # 冷启动：AST 扫描 + 种子注入
mms verify                                         # 系统健康检查
mms validate                                       # 记忆 Schema 校验
mms gc                                             # 垃圾回收（LFU tier 重计算）
mms usage                                          # LLM 调用统计与成本报告
mms reset-circuit                                  # 重置熔断器
mms hook install                                   # 安装 git pre-commit hook
```

### 模板库

```bash
mms template list                                  # 列出所有代码模板
mms template info service-method                   # 查看模板变量说明
mms template use service-method \
  --var entity=User --var method_name=create        # 渲染模板输出代码
```

### 私有记忆

```bash
mms private init EP-NNN                            # 初始化 EP 私有工作区
mms private note EP-NNN "发现一个事务陷阱"          # 添加临时笔记
mms private list                                   # 列出所有工作区
mms private promote EP-NNN note.md L2 MEM-L2-new   # 升级为 shared 记忆
mms private close EP-NNN                           # 关闭工作区
```

---

## LLM Provider 配置

MMS 将不同任务路由到不同模型：

| 任务 | 默认 Provider | 模型 |
|------|--------------|------|
| 代码生成 | `bailian_coder` | `qwen3-coder-next` |
| 推理 / DAG 编排 | `bailian_plus` | `qwen3-32b` |
| 代码评审 | `bailian_plus` | `qwen3-32b` |
| 离线降级 | `ollama_coder` | 通过 `OLLAMA_CODER_MODEL` 配置 |

运行时按任务覆盖：

```bash
MMS_TASK_MODEL_OVERRIDE="dag_orchestration:gemini,code_review:gemini" \
  mms unit run --ep EP-001 --unit U1
```

`.env.memory` 关键配置项：

```bash
DASHSCOPE_API_KEY=sk-...           # 阿里云百炼 API Key
BAILIAN_CODER_MODEL=qwen3-coder-next
BAILIAN_REASONING_MODEL=qwen3-32b
OLLAMA_CODER_MODEL=deepseek-coder-v2:16b
OLLAMA_R1_MODEL=deepseek-r1:8b
MMS_PROJECT_ROOT=/path/to/your/project  # 指定项目根目录（CI/Docker 使用）
```

---

## 冷启动

在零记忆的全新项目上快速建立 MMS：

```bash
# 完整冷启动：AST 扫描 + 技术栈检测 + 种子包注入（< 1 秒，零 LLM 调用）
mms bootstrap --project-root /path/to/your/project
```

冷启动后自动完成：

1. **AST 骨架扫描** → `docs/memory/_system/codemap.md`
2. **依赖嗅探** → 检测 FastAPI、SQLModel、React 等技术栈
3. **种子包注入** → 将匹配的模式复制到 `docs/memory/shared/`
4. **本体初始化** → `docs/memory/ontology/`

可用种子包：

| 种子包 | 触发条件 | 注入内容 |
|--------|---------|---------|
| `base` | 任何项目 | 通用模式（安全、事务、API 格式）|
| `fastapi_sqlmodel` | requirements 含 `fastapi`, `sqlmodel` | 后端 API 模式 |
| `react_zustand` | package.json 含 `react`, `zustand` | 前端组件模式 |
| `palantir_arch` | 含本体/元数据关键词 | 领域建模模式 |

---

## Benchmark

跨三个系统评估检索质量：

```bash
# 运行完整 Benchmark（HybridRAG 需 ES + Milvus）
python3 benchmark/run_benchmark.py --systems pageindex hybrid_rag ontology

# 代码生成质量 Benchmark（需要百炼 API）
python3 benchmark/run_codegen.py --systems pageindex ontology --full-eval

# Dry run（无 LLM 调用，仅测试结构）
python3 benchmark/run_codegen.py --dry-run
```

### 评测指标

| 指标 | 公式 | 衡量什么 |
|------|------|---------|
| Layer Accuracy | `hits / queries` | L1–L5 层识别正确率 |
| Recall@5 | `relevant in top-5 / total relevant` | 相关记忆覆盖率 |
| MRR | `Σ(1/rank_i) / N` | 平均倒数排名 |
| Path Validity | `valid_paths / total_paths` | 可操作文件引用率 |
| Context Tokens | `mean(token_count)` | 成本效率 |
| Info Density | `Recall@5 / (tokens / 1000)` | 每 token 质量 |
| AIU Precision | `correct_AIUs / predicted_AIUs` | 分解准确率 |
| Codegen Score | `0.1×语法 + 0.3×合约 + 0.3×架构 + 0.3×测试` | 4 级代码质量 |
| Cost Efficiency | `codegen_score / (total_tokens / 1000)` | 质量/成本比 |

---

## 测试

```bash
# 运行全部测试（无需 LLM API）
pytest tests/ -v

# 按标记过滤
pytest tests/ -m "not slow and not integration"

# 生成覆盖率报告
pytest tests/ --cov=. --cov-report=html
```

测试结果：**563+ 通过**，1 跳过，2 预期失败（xfail）

---

## 配置参考

所有配置位于 `docs/memory/_system/config.yaml`（由 `mms bootstrap` 创建）。

关键配置项：

```yaml
runner:
  timeout_llm: 180               # LLM 调用超时（秒）
  max_retries: 3                 # 3-Strike 重试次数
  token_budget:
    fast: 2000                   # 快速模型 Token 预算
    capable: 4000                # 精确模型 Token 预算
  max_tokens:
    code_generation: 4096
    code_review: 4096
    dag_orchestration: 8192

intent:
  confidence_threshold: 0.85    # 低于此值 → LLM 降级
  grey_zone_low: 0.60

dag:
  annotate_threshold_high: 0.85
  report_threshold: 0.75

compare:
  diff_truncate_chars: 3000      # Diff 摘要截断字符数
  code_truncate_chars: 4000      # 代码内容截断字符数

benchmark:
  max_context_chars: 12000       # 约 3000 tokens
  codegen_max_tokens: 2048
  result_preview_chars: 3000
```

---

## 架构约束扫描（AC-1~AC-6）

`mms arch-check` 检查以下 6 条红线：

| 规则 | 约束 | 检测方式 |
|------|------|---------|
| AC-1 | `pymilvus/aiokafka/elasticsearch` 禁止在 `services/` 直接 import | `--layer` |
| AC-2 | Service 公开方法首参必须是 `ctx: SecurityContext` | `--ctx` |
| AC-3 | 所有 DB WRITE 必须调用 `AuditService.log()` | `--audit` |
| AC-4 | API 返回必须用 `{"code":..,"data":..,"meta":..}` 信封格式 | `--envelope` |
| AC-5 | 前端管理页面必须是 React 组件（非 Amis JSON）| `--frontend` |
| AC-6 | Worker 必须使用 `JobExecutionScope` | `--worker` |

---

## 贡献指南

1. Fork 此仓库
2. 创建特性分支：`git checkout -b feature/my-feature`
3. 运行测试：`pytest tests/`
4. 运行架构检查：`python3 arch_check.py --ci`
5. 提交 Pull Request

---

## License

MIT License — 详见 [LICENSE](LICENSE)。
