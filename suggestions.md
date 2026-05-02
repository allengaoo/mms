

以下是将木兰系统重构为“弹性伸缩工具链”以及强化“Bootstrap v2”的具体工程实施方案。我将通过架构图、流程图以及核心数据结构的定义，为你提供可直接转化为代码级的落地指导。

---

### 第一部分：将木兰重构为“弹性伸缩工具链（Elastic Toolchain）”

**工程目标**：将木兰现有的单轨控制流（Pipeline）升级为双轨分发流。核心是将底层的知识图谱（Layer 2）和安全验证（Layer 4）包装成标准化工具（Tools/MCP），让大模型可以自主调用，而小模型继续留在原有流水线中。

#### 1. 弹性架构总览图 (Elastic Architecture Diagram)

```text

┌─────────────────────────────────────────────────────────────────────────────┐

│                          EP Runner (任务入口)                                │

│                   src/mms/workflow/ep_[runner.py](http://runner.py)                             │

└─────────────────────────────────┬───────────────────────────────────────────┘

                                  ▼

                     【Capability Router (能力探针)】

                      读取 mms_config.yaml 中定义的模型级别

                                  │

          ┌───────────────────────┴────────────────────────┐

     [Level < 8: 小模型/离线][Level >= 8: 大模型/云端]

          │                                                │

          ▼                                                ▼

【Track A: Micro-Pipeline (微观流水线)】    【Track B: Autonomous Agent (自治智能体)】

 模块: dag/task_[decomposer.py](http://decomposer.py)              模块: execution/autonomous_[runner.py](http://runner.py)

 特征: 强制拆分 43 种微观 AIU                特征: 封装为 1 个 Macro-AIU (全量意图)

 控制: UnitRunner 串行控制, 3-Strike       控制: ReAct/Plan-Solve 自循环

 上下文: 系统主动检索并强行拼接 (Inject)     上下文: 大模型按需主动调用 Tools 检索

          │                                                │

          └───────────────────────┬────────────────────────┘

                                  ▼

┌─────────────────────────────────────────────────────────────────────────────┐

│               Tool Abstraction Layer (MCP 工具抽象层)                       │

│                   src/mms/agent_tools/[registry.py](http://registry.py)                           │

│                                                                             │

│ [Tool 1] tool_query_ontology(keyword)  → 映射至 memory/graph_[resolver.py](http://resolver.py)    │

│ [Tool 2] tool_get_ast(file_path)       → 映射至 analysis/ast_[skeleton.py](http://skeleton.py)    │

│ [Tool 3] tool_dry_run_diff(diff)       → 映射至 execution/[sandbox.py](http://sandbox.py) +      │

│                                           analysis/arch_[check.py](http://check.py)            │

│ [Tool 4] tool_run_pytest(test_path)    → 映射至 workflow/[postcheck.py](http://postcheck.py)       │

└─────────────────────────────────────────────────────────────────────────────┘

```

#### 2. 实施细节：模型分流与配置

在 `docs/memory/_system/config.yaml` 中新增能力定义，并在 `ep_runner.py` 中实现拦截。

*   **配置设计**：

    ```yaml

    runner:

      execution_mode: "auto"  # auto | pipeline | autonomous

      capability_levels:

        "qwen3-32b": 5        # Level < 8 走 Track A (Pipeline)

        "qwen3-coder-plus": 5

        "claude-3.5-opus": 9  # Level >= 8 走 Track B (Autonomous)

        "gpt-4o": 9

    ```

#### 3. 实施细节：Tool Abstraction (MCP 工具层)

这是大模型向下穿透获取企业架构知识的关键。在 `src/mms/agent_tools/` 中，必须以严谨的 JSON Schema 定义工具入参，以防大模型调用报错。

*   **核心工具 1：图谱语义探针 `tool_query_ontology`**

    *   **描述给大模型 (System Prompt)**：“当你需要了解当前项目的架构规范、API 契约、领域模型约束时，调用此工具。传入关键词。”

    *   **内部执行**：直接调用现有的 `graph_resolver.hybrid_search(keyword)`。

    *   **返回格式**：将找回的 `MemoryNode` 列表转化为精简的 Markdown 字符串返回给大模型。

*   **核心工具 2：AST 物理探针 `tool_get_ast`**

    *   **描述给大模型**：“在你修改某个文件前，调用此工具获取该文件的完整类、函数签名及 imports 列表，避免盲目猜测变量名。”

    *   **内部执行**：查询 `ast_index.json`，返回对应 `file_path` 的骨架（Skeleton）。

*   **核心工具 3：沙箱验证器 `tool_dry_run_diff`**

    *   **描述给大模型**：“在你认为代码编写完成后，提交标准的 Diff 格式到此工具。系统将在隔离沙箱中进行架构红线扫描和语法验证。”

    *   **内部执行**：在 `.mulan-shadow-workspaces` 中应用 Diff，调用 `arch_check.py`，返回全绿（Success）或具体的报错堆栈（Traceback）。

#### 4. 实施细节：Autonomous Runner 执行循环

新建 `src/mms/execution/autonomous_runner.py`。这是一个标准的 `while` 循环，将控制权（Control Flow）交还给大模型。

*   **循环逻辑**：

    1.  **System Prompt 初始化**：告知模型你现在是一个资深架构师，你的目标是完成 Macro-AIU（宏观任务），你有 4 个工具可用。

    2.  **Action 阶段**：模型输出希望调用的 Tool（如 `tool_query_ontology`）及参数。

    3.  **Observation 阶段**：木兰系统在本地执行该 Tool，将结果追加到 Message 历史中，再次请求大模型。

    4.  **Verification 阶段**：大模型生成代码 Diff 并调用 `tool_dry_run_diff`。如果返回 Error，大模型会自动阅读 Error 并发起下一轮修改。

    5.  **Exit 阶段**：大模型调用 `tool_finish(status="success")`，木兰结束沙箱，执行最终合并。

---

### 第二部分：针对 v5.0 Bootstrap v2 的强化建议

**工程目标**：解决纯正则推断在老旧/奇葩项目中的误判问题；实现从项目现存文档（如 `CONTRIBUTING.md`）到木兰动态本体（Ontology）的自动吸收，达成“零阻力接管”。

#### 1. 强化 Bootstrap v2 流程图 (Enhanced Bootstrap Flowchart)

```text

[Start mms bootstrap]

       │

       ▼

【Step 1: 静态嗅探 (Sniffer)】(dep_[sniffer.py](http://sniffer.py))

   ├─ 检测包管理器 (pom.xml, go.mod) → 决定 Seed Pack

   └─ ▶ [新增] 检测项目中是否存在 `.cursorrules`, `CONTRIBUTING.md`, `docs/arch.md`

          │

          └─▶ 触发异步进程: Rule Absorber (后台静默将这些文档蒸馏为本体和约束，不阻塞主流程)

       │

       ▼

【Step 2: AST 骨架化】(ast_[skeleton.py](http://skeleton.py))

   └─ 提取物理代码结构 → ast_index.json

       │

       ▼

【Step 3: 框架强制覆盖 (Framework Override Pass)】▶ [核心重构点]

   ├─ 读取 `seed_packs/<name>/match_conditions.yaml`

   ├─ AST 选择器精确命中 (如: 继承自 `django.db.models.Model`)

   └─ 命中则直接锁定 Layer 和 ObjectType，并标记 Confidence = 1.0 (短路后续推断)

       │

       ▼

【Step 4: 五路信号推断 (Signal Fusion)】(signal_[fusion.py](http://fusion.py))

   └─ 对 Step 3 未命中的类，继续使用 路径/命名/注解/依赖 融合加权推断

       │

       ▼

【Step 5: 初始记忆生成与合并】

   ├─ 融合推断产生的基线记忆 (MEM-BOOT-*.md)

   └─ ▶ [新增] 合并 Step 1 中后台 Rule Absorber 刚刚蒸馏完毕的企业特有规范记忆

       │

[End] 彻底接管项目，初始化完成

```

#### 2. 实施细节：框架强制覆盖机制 (Framework Override Pass)

绝不能将特定的框架规则硬编码在 `signal_fusion.py` 的 Python 代码中。必须采用 **Data as Code (数据即代码)**，通过 YAML 驱动。

*   **数据结构设计**：在每个种子包（如 `seed_packs/python_django/`）下创建 `match_conditions.yaml`。

    ```yaml

    # docs/memory/seed_packs/python_django/match_conditions.yaml

    overrides:

      - rule_id: DJANGO_MODEL_IS_ENTITY

        # AST 选择器：只要类的基类包含 models.Model

        ast_selector: "ClassDef[bases*='models.Model']"

        # 短路赋值

        force_layer: "DOMAIN"

        force_object_type: "Entity"

        confidence: 1.0

      - rule_id: DJANGO_VIEW_IS_ADAPTER

        ast_selector: "ClassDef[bases*='APIView']"

        force_layer: "ADAPTER"

        force_object_type: "Controller"

        confidence: 1.0

    ```

*   **执行引擎修改**：在 `signal_fusion.py` 中，执行逻辑改为：

    1. 遍历当前项目的所有的 `ClassSkeleton`。

    2. 第一遍筛选：针对加载的 `match_conditions.yaml` 执行 AST Selector 匹配。如果命中，直接为其赋予 `inferred_layer` 和 `code_object_type`，置信度 1.0。

    3. 第二遍筛选：对于置信度 < 1.0 的类，再运行原有的“五路信号加权逻辑”。这保证了框架核心组件 100% 被正确归类。

#### 3. 实施细节：Rule Absorber 的无缝前置集成

目前 `seed_absorber.py` 需要开发者手动运行 URL 吸收。对于新接手的企业项目，应做到完全自动化。

*   **执行逻辑设计**：

    1.  在 `ontology_populator.py` (Bootstrap 入口) 执行时，扫描项目根目录及 `docs/`, `.github/` 下的特征文件。特征列表包括`CONTRIBUTING.md`, `.cursorrules`, `ARCHITECTURE.md`, `CODING_GUIDELINES.md`。

    2.  一旦发现此类文件，调用现有的 `seed_absorber.absorb(file_path)`。

    3.  **核心提示词（System Prompt）调优**：告诉 qwen3-32b：“你正在扫描当前项目遗留的自然语言开发文档。请提取其中的强约束规约，抛弃所有关于环境搭建、Git 操作的噪音，仅输出纯粹的架构层规约（AC 规则）和业务领域概念，格式化为 MMS 本体 YAML。”

    4.  生成的自定义种子文件直接写入 `docs/memory/shared/CC/`（作为高优先级的跨切面约束）和 `docs/memory/ontology/` 中。

**工程价值总结**：

通过以上改造，当你用木兰执行 `mulan bootstrap` 时，系统不仅能在 5 秒内精准看透 Django/Spring Boot 等框架的底层物理结构，还能自动“读懂”前任工程师留下的文本规范，并将其转化为大模型在编写代码时无法逾越的数字高墙。这才是真正的“零阻力接管”。