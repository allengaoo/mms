---

# 木兰（Mulan）系统高阶架构重构与落地实施指南

## 实施模块一：重构多语言 AST 解析器（引入工业级语法树）

**目标**：彻底消除纯 Python 正则解析在复杂企业级代码（如泛型、闭包、复杂嵌套）中的脆弱性，保证 `ast_pointer` 的绝对精准。

**约束**：保持“零强制常驻运行时”原则，不启动类似 LSP 的后台服务。

### 落地步骤：

*   **Step 1.1: 引入静态 Tree-sitter 绑定**

    *   **操作**：在 `pyproject.toml` 的可选依赖中引入官方的 `tree-sitter` Python 轮子（预编译二进制，无需用户本地配置 C 编译器）。例如`tree-sitter`, `tree-sitter-python`, `tree-sitter-java`, `tree-sitter-go`。

*   **Step 1.2: 抽象解析器接口 (Adapter Pattern)**

    *   **操作**：在 `src/mms/analysis/` 下创建子包 `parsers/`，定义 `ASTParserProtocol` 基础接口，包含 `extract_classes()`, `extract_methods()`, `get_imports()`。

    *   保留旧的正则解析器作为 `RegexFallbackParser`，新建 `TreeSitterParser` 作为主力实现。

*   **Step 1.3: 编写 S-Expression (SCM) 查询规则**

    *   **操作**：Tree-sitter 的核心是 `.scm` 查询文件。你需要为 Java/Go/Python 编写专门的 S 表达式来精准提取结构。

    *   *示例（提取 Python 类和方法的 SCM 查询）*：

      ```scheme

      (class_definition name: (identifier) @[class.name](http://class.name))

      (function_definition name: (identifier) @[function.name](http://function.name))

      ```

*   **Step 1.4: 升级 `ast_skeleton.py` 中的语义哈希算法**

    *   **操作**：将提取到的 `AST Node` 转化为标准化字符串（如去除所有空白符、注释、Docstring），然后再进行 SHA-256 哈希计算。这将彻底根除由代码格式化工具（如 Black/gofmt）引发的虚假漂移（False Drift）。

---

## 实施模块二：记忆图谱的边衰减与剪枝机制（防止毛线球效应）

**目标**：控制动态本体图的熵增，确保 `hybrid_search` 和 `typed_explore` 在长期运行中保持高信噪比和极低的 Token 消耗。

### 落地步骤：

*   **Step 2.1: 升级 LinkType 的 YAML 定义（增加元数据）**

    *   **操作**：修改 `docs/memory/ontology/links/cites.yaml` 和 `about.yaml`，在结构中增加 `weight`（边权重，默认 1.0）和 `last_accessed_ep`（最后访问任务 ID）字段。

*   **Step 2.2: 在 `graph_resolver.py` 中实现检索强化（Reinforcement）**

    *   **操作**：当 `hybrid_search` 取出一条记忆并注入 Prompt，且该任务在 `postcheck.py` 阶段成功通过验证时，木兰自动将该记忆涉及的图谱边权重（Weight）增加 0.2（设定上限为 2.0）。这叫**隐式正反馈**。

*   **Step 2.3: 在 `mulan gc` 中实现 LFU 遗忘算法 (Forgetting Algorithm)**

    *   **操作**：修改 `src/mms/memory/entropy_scan.py` 模块。每次运行 `mulan gc` 时，执行全局边遍历。

    *   **算法逻辑**：如果一条边在最近的 20 个 EP 任务中都没有被成功使用过（通过对比当前 EP ID 与 `last_accessed_ep`），对其权重执行衰减`weight = weight * 0.8`。

*   **Step 2.4: 触发自动剪枝（Pruning）**

    *   **操作**：当某条自动生成的 `cites` 边或 `about` 边权重降至 0.2 以下时，物理删除该图关系。由于图是纯文本，直接操作 YAML/Markdown Front-matter 中的数组即可。

---

## 实施模块三：Benchmark 逆向合成扩容（提升评测公信力）

**目标**：在不耗费大量人工的前提下，将 Benchmark 的样本量从 30 个提升至 300+ 个，证明木兰在复杂工业场景下的泛化能力。

### 落地步骤：

*   **Step 3.1: 开发数据合成流水线 (Synthetic Data Pipeline)**

    *   **操作**：新建脚本 `scripts/benchmark_generator.py`。

*   **Step 3.2: 圈定高质量企业级开源库靶机**

    *   **操作**：将经典的 Java Spring Boot 仓库（如 `macrozheng/mall`）或 Go 微服务仓库克隆到本地。

*   **Step 3.3: 利用 Qwen3-32B 实施逆向工程 (Reverse Generation)**

    *   **操作**：筛选目标仓库最近半年的 `fix:` 或 `feat:` 前缀的 Git Commits。

    *   **LLM Prompt 设计**：

      将 Commit 的前后 Diff 代码输入给本地 Qwen3-32B，提示语设定为：

      *"你是一个高级架构师。请阅读以下代码变更 Diff。提取开发者修改这段代码时的业务意图。然后，用一句用户的自然语言口吻，反向生成一个指令（例如：‘帮我给用户服务加上 Redis 缓存拦截’）。同时，记录该 Diff 中被修改的文件路径作为 Ground Truth。"*.

*   **Step 3.4: 自动化装配测试集**

    *   **操作**：将生成的 300+ 用例，连同对应的 Ground Truth 文件，自动写入 `benchmark/v2/layer2_memory/tasks/synthetic_tasks.yaml` 中，作为常态化 CI 评测集。

---

## 实施模块四：闭环“执行成功率（Pass@1）”测试体系

**目标**：打通从“检索准确度”到“代码生成通过率”的最后一公里，用最强硬的工业标准（代码跑通了才算赢）为木兰正名。

### 落地步骤：

*   **Step 4.1: 在 Benchmark v2 中引入沙箱隔离机制**

    *   **操作**：利用你现有的 `src/mms/execution/sandbox.py`，确保 Benchmark 的每一个 Task 都在独立的 Git Worktree 中执行，互不污染。

*   **Step 4.2: 升级 `schema.py` 评估指标**

    *   **操作**：在 Benchmark 的输出指标中，除了目前的 `RecallInfo Density`，新增两个核心布尔值：

        *   `syntax_pass`（代码无语法级崩溃）

        *   `pytest_pass`（即 Pass@1：代码生成后，运行沙箱内的测试集`exit_code == 0`）

*   **Step 4.3: 实现 SWE-Bench 风格的全自动裁判**

    *   **操作**：修改 `benchmark/run_benchmark_v2.py` 的执行图。对于指定的评测用例（Task），直接触发完整的 `mulan ep run --auto-confirm`。

    *   **对比实验设计**：

        *   跑两遍同样的 Task。第一遍：关闭 `injector.py`（即不注入任何木兰记忆图谱上下文），记录 Pass@1 得分；第二遍：开启木兰上下文注入，记录 Pass@1 得分。

        *   **最终报告**将直观展示：*“木兰系统通过 1500 Tokens 的高密度 Ontology 上下文注入，将 Qwen3-Coder-Next 的 Pass@1 成功率从 18% 提升到了 55%”*。这是任何技术文章或开源社区中最具杀伤力的数据。