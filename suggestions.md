以下是对木兰（Mulan）系统底层架构、诊断机制、评测体系及组件的结构化深度解析。所有图表均采用高维抽象的 ASCII/文本层级图，方便直接嵌入你的技术白皮书或架构文档中。

最后部分针对你提出的“Oracle 风格诊断与 Trace 基础设施”给出了直接落地的工程重构方案。

---

### 图 1：木兰 EP 工作流全景业务流程图 (Business Process Flowchart)

该图展示了木兰系统从接收任务到完成知识回流的端到端（Top-to-Bottom）单次 Episode（EP）生命周期。

```text

========================================================================================

                      木兰 EP 业务工作流 (Top-to-Bottom Execution)

========================================================================================[Start] 用户自然语言输入: "修改 XXX 功能"

   │

   ▼

【Phase 0: 意图合成】 ──▶ src/mms/workflow/[synthesizer.py](http://synthesizer.py)

   │  └─ 漏斗分类 (RBO -> Ontology -> LLM)

   │  └─ 输出: [EP-NNN.md](http://EP-NNN.md) (Cursor 提示词任务书)

   ▼

【Phase 1: 前置检查】 ──▶ src/mms/workflow/[precheck.py](http://precheck.py)

   │  └─ 建立 Git Worktree 沙箱 (隔离主分支)

   │  └─ 扫描物理代码，生成 AST 快照 (ast_index.json)

   ▼

【Phase 2: 任务编排】 ──▶ src/mms/execution/unit_[generate.py](http://generate.py)

   │  └─ Qwen3-32B 读取 [EP-NNN.md](http://EP-NNN.md)

   │  └─ 输出: DAG (有向无环图) & AIU_Steps (原子工序列表)

   ▼

【Phase 3: 织造循环】 ──▶ src/mms/execution/unit_[runner.py](http://runner.py) 

   │  ┌───────────────────[ AIU 执行环 (Loop AIUs) ]────────────────────────┐

   │  │ 1. 上下文注入: graph_[resolver.py](http://resolver.py) (按 layer_affinity 召回 Ontology)    │

   │  │ 2. CBO 预算: aiu_cost_[estimator.py](http://estimator.py) (计算 Token 上限)                  │

   │  │ 3. 代码生成: qwen3-coder-next -> file_[applier.py](http://applier.py) (写入沙箱文件)       │

   │  │ 4. 内部评审(可选): internal_[reviewer.py](http://reviewer.py) (Qwen3-32B 拦截)              │

   │  │ 5. 失败回退: aiu_[feedback.py](http://feedback.py) (触发 3-Strike 扩预算/拆分子任务)          │

   │  └───────────────────────────────────────────────────────────────────┘

   ▼

【Phase 4: 质量门控】 ──▶ src/mms/workflow/[postcheck.py](http://postcheck.py)

   │  └─ AST 漂移检测 (ast_[diff.py](http://diff.py) 验证契约一致性)

   │  └─ 沙箱中运行 Pytest

   │  └─ 执行 2PC: 验证全绿则 Squash Merge 回主干，否则移除 Worktree

   ▼

【Phase 5: 知识回流】 ──▶ src/mms/memory/[distill.py](http://distill.py) & [dream.py](http://dream.py)

   │  └─ 脱敏屏障 (SanitizationGate) 剔除 Token / IP

   │  └─ 自动建边 (Auto-Link) 更新 L1-L5 记忆图谱

   │

[End] 任务结束，更新图谱健康度

```

---

### 图 2：诊断与追踪层级映射图 (Diagnostic & Trace Layered Diagram)

解答：“诊断时会产生什么数据？会调用哪些代码段？”

```text

========================================================================================

                      诊断级别与代码调用栈映射 (Oracle 10046 风格)

========================================================================================

【Level 1: Basic】(基础状态流转)

 ├── 产生数据：步骤耗时 (Latency)、成功/失败标志、DAG 状态机变迁、AIU_Step 启停事件。

 ├── 核心定位：宏观感知系统"卡在哪一步"。

 └── 追踪源码段：

     ├── src/mms/dag/dag_[model.py](http://model.py)       (状态更新钩子)

     ├── src/mms/execution/unit_[cmd.py](http://cmd.py)  (状态机控制器)

     └── src/mms/workflow/ep_[runner.py](http://runner.py)  (Phase 级别切换)

【Level 4: LLM】(模型调用与成本)

 ├── 产生数据：LLM 模型名称、Prompt Tokens、Completion Tokens、API 请求头、重试计数。

 ├── 核心定位：排查 Token 预算溢出、模型幻觉触发频率、并发限流 (Rate Limit)。

 └── 追踪源码段：

     ├── src/mms/providers/[bailian.py](http://bailian.py)   (API 请求底层)

     ├── src/mms/utils/model_[tracker.py](http://tracker.py) (用量统计器)

     └── src/mms/resilience/[retry.py](http://retry.py)    (退避重试拦截器)

【Level 8: FileOps】(物理层与沙箱操作)

 ├── 产生数据：AST 提取耗时、真实写入的沙箱文件路径、写入行数、DB 迁移拦截日志。

 ├── 核心定位：排查"为什么代码没写进去"、沙箱合并失败原因、Git 锁冲突。

 └── 追踪源码段：

     ├── src/mms/execution/[sandbox.py](http://sandbox.py)   (Git Worktree 操作)

     ├── src/mms/execution/file_[applier.py](http://applier.py) (Diff 应用器)

     └── src/mms/core/[writer.py](http://writer.py)         (落盘操作)

【Level 12: Full】(全量语义日志)

 ├── 产生数据：完整的 Prompt 拼接原文、LLM 吐出的原始 JSON/Markdown 文本、SanitizationGate 脱敏详情。

 ├── 核心定位：排查小模型不遵循指令 (Instruction Following) 的语义级 Bug、格式解析崩溃。

 └── 追踪源码段：

     ├── src/mms/memory/[injector.py](http://injector.py)     (上下文拼接组装)

     ├── src/mms/dag/task_[decomposer.py](http://decomposer.py) (输出解析层)

     └── src/mms/core/[sanitize.py](http://sanitize.py)       (正则脱敏引擎)

```

---

### 图 3：Benchmark 测试架构图 (Benchmark Architectural Perspective)

解答：“未来如何修改 Benchmark 代码以及 Debug 时从何处切入？”

```text

========================================================================================

                      Benchmark v2 架构图与 Debug 切入点

========================================================================================

[Entry Point] ──▶ benchmark/run_benchmark_[v2.py](http://v2.py) (入口脚本)

   │

   ▼

[Registry & Dispatcher] ──▶ benchmark/v2/[runner.py](http://runner.py)

   │  └─ 核心逻辑：读取 fixtures/*.yaml，分配至对应层级的 Evaluator

   │  └─ Debug 切入点：如需限制并发或增加超时，在此修改 asyncio / ThreadPool

   │

   ├─▶ 【Layer 1: SWE-Bench 执行锚】 ──▶ benchmark/v2/layer1_swebench/

   │      ├── [evaluator.py](http://evaluator.py) (调度 Git Worktree，触发 `pytest`)

   │      └── tasks/       (存放如 Python 真实项目的 Issue 描述)

   │      └─ 关注指标：Pass@1 (代码通过率), Resolve Rate

   │      └─ Debug 切入点：沙箱隔离失败或测试框架找不到时，断点打在此处。

   │

   ├─▶ 【Layer 2: 记忆检索质量】 ──▶ benchmark/v2/layer2_memory/

   │      ├── [evaluator.py](http://evaluator.py) (调用 hybrid_search，统计 Token)

   │      ├── tasks/funnel_retrieval.yaml (漏斗有效性测试)

   │      └── tasks/mall_order_cases.yaml (企业靶机结构)

   │      └─ 关注指标：Info Density (有效信息密度), Recall@5

   │      └─ Debug 切入点：如果木兰"找不到对应的记忆"，断点打在 `hybrid_search()` 调用处。

   │

   └─▶ 【Layer 3: 安全门控拦截】 ──▶ benchmark/v2/layer3_safety/

          ├── [evaluator.py](http://evaluator.py) (纯离线，输入脏数据测试拦截率)

          └── fixtures/    (存放带假 Token/IP 的文本，非法迁移脚本)

          └─ 关注指标：凭证检出率, 架构规则覆盖率

          └─ Debug 切入点：测试脱敏正则是否误杀，断点打在 `sanitize.py` 内部。

```

---

### 图 4：系统组件详图 (System Component Diagrams)

#### 4.1 全局五层组件图 (Overall System)

```text

┌─────────────────────────────────────────────────────────────┐

│ 1. Task Eng (工作流与任务)   synthesizer | ep_runner | ep_wizard│

├─────────────────────────────────────────────────────────────┤

│ 2. Knowledge (记忆与知识)    hybrid_search | ontology | dream   │

├─────────────────────────────────────────────────────────────┤

│ 3. Code Gen (执行与代码)     unit_generate | unit_runner      │

├─────────────────────────────────────────────────────────────┤

│ 4. Safety (门控与沙箱)       sandbox | arch_check | sanitize  │

├─────────────────────────────────────────────────────────────┤

│ 5. Foundation (基础设施)     providers(llm) | trace | audit   │

└─────────────────────────────────────────────────────────────┘

```

#### 4.2 意图识别、DAG 与 AIU 的内部组件图 (Intent, DAG, AIU)

```text

[用户输入任务]

      │

      ▼

【Intent Classifier 意图漏斗】

  ├── Level 1: RBO (正则/AST特征极速匹配)

  ├── Level 2: Ontology Match (匹配 layers.yaml 实体)

  └── Level 3: LLM 分类 (Qwen3-32B 兜底识别)

      │

      ▼

【Task Decomposer & DAG Generator】

  ├── 读取 aiu_[registry.py](http://registry.py) (获取 43 种 AIU 的 Schema)

  ├── 识别依赖关系 -> 组装 DagState (有向无环图)

  └── 吐出任务队列：[A族_Schema] ->[C族_Data] -> [D族_Interface]

      │

      ▼

【AIU Cost Estimator (CBO)】

  └── 为当前出列的 AIU_Step 估算 Token Budget。

      │

      ▼

【Unit Runner 执行环】

  └── 在沙箱中完成：LLM 翻译 -> File Apply -> 门控检查 -> aiu_feedback 回退

```

#### 4.3 记忆层内部组件图 (Memory Layer)

```text

【Layer 0: 物理数据】 (ast_index.json / Git History)

      ▲

      │ (AST 同步 / Cites 边)

      ▼

【Layer 1: Ontology 引擎】 (ObjectType / LinkType YAML定义)

      ▲

      │ (Typed Explore)

      ▼

【Layer 2: 核心图检索算法】 (graph_[resolver.py](http://resolver.py))

  ├── 1. find_by_concept()[零LLM, 基于关键词定位节点]

  ├── 2. concept_lookup()    [向外探索 about/related_to 边]

  └── 3. *keyword*fallback() [BM25 全文降级]

      │

      ▼

【Context Builder】 ([injector.py](http://injector.py))

  └── 剪裁/压缩图谱片段，保证 Token < 4k，注入给 Coder 模型

```

---

第五部分：  
基于 Oracle 数据库极其成熟的 ADR（Automatic Diagnostic Repository，自动诊断库）架构哲学，为木兰（Mulan）系统重构 Trace 与诊断基础设施，是解决“AI 智能体黑盒化”与“并发任务难以调试”的关键战役。

在企业级软件工程中，系统崩溃时的“案发现场”往往稍纵即逝。大模型 API 的超时、返回 JSON 格式的断裂、沙箱挂载的失败，如果仅靠控制台标准输出`stdout`），在并发或后台执行时将根本无法追溯。

以下是基于 Oracle 诊断哲学，为木兰系统设计的详细工程实施方案与底层架构落地细节。

---

### 一、 物理目录抽象：MDR (Mulan Diagnostic Repository)

借鉴 Oracle 的 `DIAGNOSTIC_DEST` 参数，在木兰的工作区中建立集中的诊断层，物理隔离业务代码与诊断数据。

在 `docs/memory/private/` 目录下创建 `mdr/` 目录：

```text

docs/memory/private/mdr/

├── alert/

│   └── alert_mulan.log                # 全局告警日志（系统生命体征）

├── trace/

│   ├── mulan_ep_1024_1117.trc         # 单个 EP 的全生命周期追踪（类比 10046 trace）

│   └── mulan_ep_1025_1120.trc

└── incident/

    ├── inc_20260427_1117_JSON_ERR/    # 致命崩溃的独立案发现场

    │   ├── call_stack.dmp             # 堆栈快照与内存变量

    │   └── prompt_context.txt         # 触发崩溃的毒性 Prompt 副本

    └── inc_20260427_1125_OOM/

```

---

### 二、 核心组件实施细节与源码映射

#### 1. 宏观监控基建：全局告警日志 `alert_mulan.log`)

**定位**：系统的“心电图”。只记录重大系统级事件与级联故障，**绝对不记录**某行代码生成了什么。

**实施细节**：

- 在 `src/mms/observability/logger.py` 中初始化一个专属的全局 Logger，绑定到 `alert/alert_mulan.log`，采用 Append-Only（仅追加）与按天轮转（Log Rotation）模式。
- **记录的触发点（Triggers）**：
  - **Startup/Shutdown**：木兰引擎启动、加载配置文件完毕、索引构建完成。
  - **Resilience Events**`circuit_breaker.py`（熔断器）被触发（例如 Bailian API 连续超时 3 次，熔断器打开）。
  - **Resource Limits**：检测到磁盘空间不足、Git Worktree 创建失败。
- **工程价值**：当木兰作为企业后台守护进程（Daemon）批量处理上百个 PR 时，运维人员只需 `tail -f alert_mulan.log` 即可确认系统存活状态。一旦出现 `[FATAL] Circuit Breaker OPEN for qwen3-coder-next`，立刻知道是外部算力掉线。

#### 2. 会话级追踪基建：Oracle 10046 风格 Trace `.trc`)

**定位**：针对单个 EP（Execution Plan）的显微镜。类比 Oracle 中通过 `ALTER SESSION SET EVENTS '10046 trace name context forever, level 12'` 开启的 SQL 追踪。

**实施细节**：

- **ContextVars 绑定 (关键)**：为了支持未来多 Agent 并发，不能使用全局 Logger。必须使用 Python 原生的 `contextvars` 绑定当前的 `ep_id`。
- 在 `ep_runner.py` 启动时：
  ```python

  import contextvars

  from structlog.contextvars import bind_contextvars



  ep_id_var = contextvars.ContextVar("ep_id")

  ep_id_var.set("EP-1024")

  bind_contextvars(ep_id="EP-1024")

  # 初始化专属的文件 Handler 指向 trace/mulan_ep_1024.trc

  ```
- **动态级别注入 (Dynamic Trace Levels)**：
系统在接收任务时，可通过 `mulan trace enable EP-1024 --level 12` 动态调整该文件的颗粒度：
  - *Level 4 (LLM)*：拦截所有 `src/mms/providers/` 的出站 HTTP 请求和响应耗时。
  - *Level 8 (FileOps)*：拦截 `src/mms/execution/sandbox.py` 的所有 `open()` 和 `write()`。
  - *Level 12 (Full)*：拦截 `src/mms/memory/injector.py`，完整写入拼接了 4k Token 的 Prompt 原文。

#### 3. 致命崩溃现场基建：Incident Dump `.dmp`)

**定位**：系统的“黑匣子”。当木兰因为大模型幻觉、非预期 JSON 断裂或底层异常崩溃时，系统不再只是在终端抛出一堆难以追踪的 Traceback 然后死掉。

**实施细节**：

- **全局异常接管 `sys.excepthook`)**：
在木兰的 CLI 入口 `src/mms/cli.py`)，重写系统异常捕获钩子：
  ```python

  import sys

  import traceback

  from datetime import datetime



  def mulan_crash_handler(exc_type, exc_value, exc_traceback):

      # 1. 抑制普通的 KeyboardInterrupt

      if issubclass(exc_type, KeyboardInterrupt):

          sys.__excepthook__(exc_type, exc_value, exc_traceback)

          return

          

      # 2. 生成 Incident ID

      incident_id = f"inc_{[datetime.now](http://datetime.now)().strftime('%Y%m%d_%H%M%S')}_{exc_type.__name__}"

      dump_dir = Path(f"docs/memory/private/mdr/incident/{incident_id}")

      dump_dir.mkdir(parents=True, exist_ok=True)

      

      # 3. 写入 Call Stack Dump

      with open(dump_dir / "call_stack.dmp", "w") as f:

          f.write(f"FATAL ERROR: {exc_type.__name__}: {exc_value}\n")

          f.write("="*50 + "\n[TRACEBACK]\n")

          traceback.print_tb(exc_traceback, file=f)

          

          # 4. 提取崩溃栈帧中的局部变量（Locals）

          f.write("\n" + "="*50 + "\n[LOCAL VARIABLES OF CRASH FRAME]\n")

          tb = exc_traceback

          while tb.tb_next:

              tb = tb.tb_next # 追溯到最深处的报错栈帧

          for key, value in tb.tb_frame.f_locals.items():

              f.write(f"{key} = {repr(value)}\n")

      

      # 5. 通知用户

      print(f"\n[CRITICAL] Mulan encountered a fatal error.")

      print(f"Incident details dumped to: {dump_dir}")

      

  sys.excepthook = mulan_crash_handler

  ```
- **现场物证留存 (The Poisonous Prompt)**：
如果崩溃是由大模型返回的错误 JSON 引发的（如 `json.decoder.JSONDecodeError`），钩子会读取当前 `contextvars` 中的最后一次 Prompt 和最后一次 Response，将其原封不动地写入 `prompt_context.txt`。这使得开发者可以直接复制这个文件去复现大模型的幻觉行为，无需重新跑整个繁重的 EP。

---

### 三、 辅助诊断命令行：Mulan Diag (类比 Oracle ADRCI)

为了让这套基础设施真正在日常开发和 Debug 中发挥作用，增加对应的 CLI 工具。

在 `src/mms/cli.py` 中增加子命令：

1. *`mulan diag status`**：
  读取 `alert_mulan.log` 尾部，报告当前系统是否有未处理的 FATAL 报错。
2. *`mulan diag pack <incident_id>`**：
  (类比 Oracle 的 `adrci> ips pack incident`)。
    当用户或开源贡献者遇到报错时，执行该命令，木兰会自动将 `call_stack.dmpprompt_context.txt`、相关的 `mulan_ep_xxx.trc` 以及当时的 `ast_index.json` 打包成一个 `.zip` 文件。用户只需将此 ZIP 附在 GitHub Issue 中，核心开发者即可获取 100% 完美的上下文进行 Debug，极大提升开源项目的维护效率。

