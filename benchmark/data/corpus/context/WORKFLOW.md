# MDP 完整工作流参考手册

> 本文档从 AGENTS.md 迁移而来（EP-116），包含 EP 工作流详细说明、mms 完整命令参数、弱模型指南、CI 集成及熵控规则。
> 快速入口（日常使用）→ `AGENTS.md`

---

## 1. 完整 EP 工作流（6 步闭环）

### 步骤总览

```
① 意图合成    mms synthesize "<任务描述>" --template <类型>
② 生成 EP     Cursor 基于合成结果生成执行计划 → 用户确认
③ 前置检查    mms precheck --ep EP-NNN           ← 修改代码前
④ 修改代码    按 EP Unit 逐步实现 + 生成测试
⑤ 后校验      mms postcheck --ep EP-NNN          ← 修改代码后
⑥ 知识沉淀    mms distill --ep EP-NNN            ← postcheck PASS 后（判断是否需要）
```

### 详细命令

```bash
# ① 意图合成（三级漏斗：历史匹配 → 记忆检索 → 静态兜底）
python3 scripts/mms/cli.py synthesize "为对象类型新增批量导出 API" \
  --template ep-backend-api \
  --extra "需支持 CSV/JSON 两种格式，限制单次最多 10000 条"

# 首次使用或代码库有较大变动时，加 --refresh-maps 刷新文件路径快照
python3 scripts/mms/cli.py synthesize "修复用户登录 401" \
  --template ep-debug --refresh-maps

# 可用模板：ep-backend-api / ep-frontend / ep-ontology / ep-data-pipeline / ep-debug
# 自定义要求：--extra "..." 或 --interactive（多行交互输入）

# 三级检索漏斗（v2.2）：
#   第一级  Jaccard + 时间衰减历史匹配 → 命中时注入验证过的文件路径（减少幻觉）
#   第二级  MEMORY_INDEX.json 关键词匹配 → 注入相关约束和经验
#   第三级  task_quickmap.yaml 静态映射 → 毫秒级，永远不为空

# ② 将 synthesize 输出粘贴给 Cursor → 生成 EP 文件 → 用户审阅确认（Go）

# ③ 前置检查（代码修改前，建立基线）
python3 scripts/mms/cli.py precheck --ep EP-NNN
# 输出：arch_check 基线 + Scope 文件列表 + 影响范围分析
# BLOCKER 级问题时停止；PASS 后继续

# ④ 按 EP Unit 修改代码 + 生成测试（每 Unit 一个 git commit）

# ⑤ 后校验（代码修改后）
python3 scripts/mms/cli.py postcheck --ep EP-NNN
python3 scripts/mms/cli.py postcheck --ep EP-NNN --skip-tests  # 跳过测试
# 检查：pytest（EP 声明的测试）+ arch_check diff + doc_drift
# PASS 后自动提示 distill 命令

# ⑥ 知识沉淀（判断标准：发现新反模式/做了不显而易见的架构决策 → 必须 distill）
python3 scripts/mms/cli.py distill --ep EP-NNN
```

### 新对话起手式

```bash
cat docs/context/MASTER_INDEX.md    # 加载主索引
ls docs/execution_plans/ | tail -5  # 确认当前 EP
```

---

## 2. distill 判断框架（何时需要？）

```
EP 完成后，问自己：
│
├─ 发现了新的反模式或约束？
│   ✅ YES → 必须 distill（防止下个 Agent 踩同样的坑）
│
├─ 做了不显而易见的架构决策？
│   ✅ YES → 必须 distill（Decision Log → AD-XXX 记忆）
│
├─ 只是按已有模式实现了常规功能？
│   ❌ NO  → 可以跳过
│
└─ Bug 修复，根因已在记忆库中？
    ❌ NO  → 不需要 distill（fix 在代码里，git log 是权威）
```

---

## 3. 完整 mms 命令参考

```bash
# ── EP 工作流命令 ─────────────────────────────────────────────
mms synthesize "<任务>" --template <类型>   # 意图合成
mms synthesize --list-templates             # 列出所有模板
mms precheck --ep EP-NNN                   # 前置检查
mms postcheck --ep EP-NNN                  # 后校验（含 dream 建议）
mms postcheck --ep EP-NNN --skip-tests     # 跳过测试
mms distill --ep EP-NNN                    # 手动知识蒸馏

# ── autoDream（EP-118）：学习闭环自动化 ──────────────────────
mms dream --ep EP-NNN                      # 从 EP + git 自动萃取知识草稿
mms dream --since 7d                       # 按时间范围萃取（不限 EP）
mms dream --list                           # 列出所有待审核草稿
mms dream --promote                        # 交互式审核 → 提升为正式 MEM-*.md
mms dream --dry-run --ep EP-NNN           # 预览 LLM prompt，不调用 LLM

# ── 代码模板库（EP-118）：小模型脚手架 ──────────────────────
mms template list                          # 列出所有可用模板（4 个内置）
mms template info service-method           # 查看模板变量说明
mms template use service-method \          # 渲染模板并写入文件
  --var entity=ObjectType \
  --var method_name=create_object_type \
  --var action=create \
  --var resource=object_type \
  --output backend/app/services/control/object_type_service.py
mms template use api-endpoint --dry-run    # 预览渲染结果

# ── DAG 编排（EP-117）：手动模式 ──────────────────────────────
mms unit generate --ep EP-NNN             # 生成 DAG（LLM 编排）
mms unit status --ep EP-NNN              # 查看 DAG 进度
mms unit next --ep EP-NNN               # 获取下一个可执行 Unit + 上下文
mms unit done --ep EP-NNN --unit U1      # 标记完成（验证 + commit）
mms unit context --ep EP-NNN --unit U2   # 生成 Unit 上下文（给小模型）
mms unit reset --ep EP-NNN --unit U1     # 回退 Unit 状态为 pending
mms unit skip --ep EP-NNN --unit U1      # 跳过指定 Unit

# ── LLM 自动执行（EP-119）：沙箱 + 3-Strike 重试 ──────────────
mms unit run --ep EP-NNN --unit U1                # 自动执行单个 Unit
mms unit run --ep EP-NNN --unit U1 --dry-run      # 仅预览代码变更（不写文件）
mms unit run --ep EP-NNN --unit U1 --confirm      # 写入前显示摘要等待确认
mms unit run --ep EP-NNN --unit U1 --model 16b    # 指定执行模型
mms unit run-next --ep EP-NNN                     # 执行当前批次所有可执行 Unit
mms unit run-next --ep EP-NNN --max-failures 2    # 允许最多 2 个 Unit 失败后继续
mms unit run-all --ep EP-NNN                      # 顺序执行全部 pending Unit（⚠️ 谨慎）

# ── 记忆管理 ──────────────────────────────────────────────────
mms inject "<任务>"                         # 注入记忆上下文（旧式，仍可用）
mms status                                  # 系统状态（模型/记忆统计）
mms validate                                # Schema 校验
mms private init EP-NNN "描述"             # 新建 EP 私有工作区

# ── 知识图谱 ──────────────────────────────────────────────────
mms graph stats                             # 图谱节点/边统计
mms graph explore AD-002 --depth 2         # 从某节点出发 BFS 遍历
mms graph file "frontend/src/config/navigation.ts"  # 反查引用该文件的节点
mms graph impacts AD-002                   # 影响分析

# ── 路径快照刷新（大重构后或新 EP 前执行）─────────────────────
python3 scripts/mms/codemap.py             # 刷新目录树
python3 scripts/mms/funcmap.py             # 刷新函数签名索引

# ── 架构检查 ──────────────────────────────────────────────────
python3 scripts/mms/arch_check.py          # 全量扫描（含修复指令）
python3 scripts/mms/arch_check.py --ci    # CI 模式（exit 2 on error）
python3 scripts/mms/doc_drift.py          # 文档漂移检测
python3 scripts/mms/entropy_scan.py --threshold warn  # 熵扫描

# ── 模型统计 ──────────────────────────────────────────────────
mms usage --since 7                        # 最近 7 天模型调用统计
```

---

## 4. 记忆格式速查

```yaml
---
id: MEM-L-XXX          # 唯一 ID（L1~L5: MEM-L-xxx; CC: AD-xxx; BIZ: BIZ-xxx）
layer: L5_interface    # 所属层
module: api            # 子模块
dimension: D8          # 工程维度（D1安全..D10测试）
type: lesson           # lesson | pattern | anti-pattern | decision
tier: hot              # hot | warm | cold
description: "30-60字语义摘要，供 LLM 判断相关性"   # EP-116 新增
tags: [api, envelope]
source_ep: EP-110
created_at: "2026-04-12"
last_accessed: "2026-04-12"
access_count: 8
---
# MEM-L-XXX · 标题（一句话说明 WHAT）
## WHERE（适用场景）
## HOW（核心实现）
## WHEN（触发条件 / 危险信号）
```

---

## 5. 弱模型使用指南（8B / 16B 本地模型）

使用 `deepseek-r1:8b`（推理）或 `deepseek-coder-v2:16b`（代码生成）时：

1. **先运行** `mms inject "<任务>"` 获取压缩上下文（约 800-1200 tokens）
2. **使用模板**：`docs/memory/templates/` 下有各类任务的 Prompt 模板
3. **单任务原则**：每次对话只做一个 Unit，完成后再开新对话
4. **验证循环**：生成代码后立即运行 `arch_check.py` 检查架构约束
5. **原子化标准**：适合小模型的 Unit 应满足：
  - 单文件变更（最多 + 对应测试文件）
  - 上下文 ≤ 4000 tokens（8B）/ ≤ 8000 tokens（16B）
  - 不需要跨层理解
  - 正确性可被 `arch_check` / `pytest` 自动验证

**任务快捷索引**（模板 → 必读文件）：


| 任务类型     | 必读文件                                                             |
| -------- | ---------------------------------------------------------------- |
| 新增后端 API | `backend-gen.mdc`, `aop-integration.mdc`, `layer_contracts.md`   |
| 新增前端页面   | `frontend-gen.mdc`, `frontend_page_map.md`, `layer_contracts.md` |
| 修复 Bug   | `troubleshooting.mdc`, `ISSUE-REGISTRY.md`                       |
| 数据管道     | `data-pipeline-patterns.mdc`, `connector_sync.md`                |
| 本体模块     | `ontology-patterns.mdc`                                          |
| 权限/RBAC  | `rbac-patterns.mdc`, `rbac.py`                                   |


---

## 6. 熵控管理

### 文档同步规则


| 代码变更             | 必须同步的文档                                              | 同步方式                     |
| ---------------- | ---------------------------------------------------- | ------------------------ |
| 新增 API Endpoint  | `docs/architecture/e2e_traceability.md`              | 手动 → `mms verify --docs` |
| 新增前端页面/路由        | `docs/architecture/frontend_page_map.md`             | 手动 → `mms verify --docs` |
| 新增 Zustand Store | `frontend_page_map.md` Store 总览                      | 手动 → `mms verify --docs` |
| 新增记忆文件           | `docs/memory/MEMORY_INDEX.json` + `MEMORY.md`        | `mms indexer update`     |
| EP 完成            | `docs/context/EP_REGISTRY.md` + `SESSION_HANDOFF.md` | EP 结束仪式                  |


### 熵扫描阈值


| 指标      | 警告阈值      | 说明                |
| ------- | --------- | ----------------- |
| 孤立记忆    | > 5 条     | 在索引中不存在的 .md 文件   |
| 过期热记忆   | > 30 天未访问 | 可降级为 warm         |
| 文档漂移    | 任意字段不一致   | `doc_drift.py` 检测 |
| 重复记忆相似度 | > 0.8     | 合并候选              |


---

## 7. CI 集成说明

```yaml
# .github/workflows/mms-harness.yml
jobs:
  mms-harness:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Schema validation
        run: python3 scripts/mms/validate.py
      - name: Architecture constraints
        run: python3 scripts/mms/arch_check.py --ci
      - name: Doc drift detection
        run: python3 scripts/mms/doc_drift.py --ci
      - name: Entropy scan
        run: python3 scripts/mms/entropy_scan.py --threshold warn
```

---

*从 AGENTS.md 迁移 · EP-116 · 2026-04-16*