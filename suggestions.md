

### 一、 Git Worktree 沙箱隔离的落地细节与优先级

**工程定位与优先级：P0（最高级阻断项）**。在没有物理隔离的情况下，让 AI 直接操作主干代码是工程灾难。必须在木兰的核心调度层强制推行。

**详细实施方案**：

1. **工作区生命周期管理**：

   * 在 `ep_runner.py` 启动阶段，拦截原有就地修改逻辑。

   * 执行 `git worktree add -b mulan-ep-<ID> .mulan-shadow/EP-<ID>`。将生成的目录加入主仓库的 `.gitignore`。

   * 修改 `_paths.py` 的上下文路径解析，将当前执行的 `root_dir` 动态重定向到这个 Shadow Worktree。

2. **AIU 执行与门控（The Execution Loop）**：

   * 所有的 `qwen3-coder-next` 生成`file_applier` 写入、以及 `pytest` 和 `arch_check`，完全在该 Worktree 下独立运行。

   * **Crash Consistency（崩溃一致性）保障**：如果 API 超时、进程被 Kill，主代码库不受任何污染，开发者只需清理 `.mulan-shadow` 目录。

3. **两阶段提交（2PC）合并**：

   * 当 `postcheck` 返回全绿时，触发 Commit 阶段。

   * 切换回主干目录`git checkout main && git merge --squash mulan-ep-<ID>`。

   * 清理沙箱`git worktree remove --force .mulan-shadow/EP-<ID>`。

---

### 二、 图谱维护（矛盾检测自动化）的优化方案

**事实依据**：随着系统演进，基于本体的图谱必定产生逻辑互斥的节点。手工维护 `contradicts` 边在知识量突破 1000 个节点时将彻底失效。

**详细实施方案**：

1. **触发时机（Trigger Point）**：

   * 挂载在 `dream.py` 和 `distill.py` 生成新的 `Pattern` 或 `ADR`（架构决策）写入存储前。

2. **爆炸半径控制（Blast Radius）**：

   * 不要全图比对。新节点生成后，仅提取与其具有相同 `layer_affinity`（如同属 `DOMAIN` 层）且 `tier` 为 `hot/warm` 的现有图谱节点（控制在 10-20 个内）。

3. **对抗性 LLM 审查（Adversarial Review）**：

   * 调用 `qwen3-32b`，注入特定的系统提示词：

     *“你是架构仲裁者。对比【新规则 A】与【旧规则集 B】。若发现互斥（如 A 要求使用 gRPC，B 要求使用 REST），请输出包含冲突节点 ID 的 JSON 数组及理由。”*

4. **自动化图谱重构（Graph Mutation）**：

   * 一旦检测到冲突，木兰底层 API 自动在新旧节点间建立 `contradicts` 边。

   * 触发图谱降级逻辑：将引发冲突的旧节点 `tier` 强制降为 `archive`，切断其所有的 `about` 和 `cites` 入边，使其在未来的 `hybrid_search` 中被永久忽略。

---

### 三、 Benchmark 的优化方向与 README 重构

#### 1. Benchmark 优化方向

* **引入执行结果（Pass@1）闭环**：检索的终极目的是代码通过率。在 Benchmark 中必须加入端到端的执行对比。

  * **实验组设计**：提取 SWE-bench Lite 中 20 个 Python 任务。第一组（Baseline）仅提供 Issue 描述让 Coder 生成代码；第二组（Mulan-Enhanced）注入木兰基于本体检索到的项目架构上下文。

  * **核心输出**：不仅输出 `Recall@5`，必须输出 `ΔPass@1`（即木兰上下文让通过率提升了多少百分点）。这是证明“端侧小模型+极简高质量上下文 > 云端大模型+全量噪音上下文”的唯一数学武器。

#### 2. Benchmark README 更新指南

原 README 仍保留着废弃的“ES+Milvus 混合 RAG”描述，必须彻底改写以反映系统最新状态。

**重构框架建议**：

* **核心命题修正**：明确声明评测的核心是 **“动态本体路由（Vectorless Ontology）” vs “传统纯文本 BM25”**。彻底删除对 ES/Milvus 的依赖说明。

* **数据集声明**：重点突出 v3.0 引入的企业级靶机。说明 `mall_order_cases` 和 `halo_content_cases` 是从真实 GitHub 万星项目中提取的结构，代表真实的工业复杂度。

* **分层评估体系（L1/L2/L3）可视化**：在文档中用表格明确定义：

  * **L3 安全层（完全离线）**：评估木兰是否能拦截代码中的硬编码 Token 和危险 DB 迁移。

  * **L2 记忆层（离线+LLM）**：展示 `Info Density` 公式，说明为何它比传统的 Recall 更适合评估小模型。

  * **L1 执行层**：展示 SWE-bench 的抽样执行通过率（Pass@1）。

---

### 四、 构建高可扩展的 AIU（原子意图单元）体系

目前的 43 种 AIU 仍可能存在盲区。硬编码在 Python 代码中的 AIU 体系违反了开闭原则（OCP）。

**可扩展架构方案（Schema-Driven AIU）**：

1. **纯 YAML 驱动（Data as Code）**：

    *彻底废弃 Python 中的 Enum 硬编码。所有 AIU 定义迁移至* `docs/memory/_system/schemas/aius/.yaml`。

2. **定义 AIU 标准契约（Contract Schema）**：

   每个 AIU 文件必须包含以下字段，以确保其可执行、可验证：

   ```yaml

   id: ROUTE_ADD_ENDPOINT

   family: D_Interface

   layer_affinity: ADAPTER

   # 核心：必须明确输入参数的 JSON Schema，供 DAG 编排模型（qwen3-32b）生成时严格遵守

   input_schema:

     method: {type: string, enum: [GET, POST, PUT, DELETE]}

     path: {type: string}

     auth_required: {type: boolean}

   # 核心：验证规则的 AST 选择器

   validation_rules:

     ast_target: "FunctionDef"

     required_decorators:["@router."]

   ```

3. **动态注册表（Dynamic Registry）**：

   * 木兰启动时，读取所有 YAML 文件，动态生成内部可调用的 AIU 策略类。

   * 当用户需要为特定的微服务系统增加一种独有操作（如 `K8S_ADD_SIDECAR`）时，只需放入一个 YAML 文件，木兰的 `task_decomposer` 在下一次规划 DAG 时会自动读取并使用其 `input_schema`。

---

### 五、 从 GitHub 顶级开源仓库提取的“种子基因（Seed Genes）”

为了让木兰的 `seed_packs` 具有真实的工业实战价值，以下是从四种语言的 GitHub SOTA（State-of-the-Art）仓库中提取的核心架构红线（AC）与代码模式，可直接转化为木兰的 Ontology 约束。

#### 1. Python (参考标的: `tiangolo/full-stack-fastapi-template`)

*   **架构范式**：FastAPI + SQLAlchemy + Pydantic v2。

*   **种子基因（AC 约束）**：

    *   **AC-PY-01 (DB 会话隔离)**：在 API Route 层，绝对禁止手动实例化 `SessionLocal()`。必须且只能通过 `Depends(get_db)` 依赖注入获取数据库会话。

    *   **AC-PY-02 (响应契约)**：路由的 `response_model` 必须绑定继承自 `pydantic.BaseModel` 的类。禁止在返回语句中直接构造并返回 Python 字典`return {"user": ...}`）。

#### 2. Java (参考标的: `macrozheng/mall` & `spring-projects/spring-petclinic`)

*   **架构范式**：Spring Boot 单体/微服务 + MyBatis/JPA + MapStruct。

*   **种子基因（AC 约束）**：

    *   **AC-JAV-01 (严格充血/贫血边界)**`@Entity` 标注的数据库模型类绝对不允许跨越 `Service` 层边界返回给 `Controller`。所有流出 `Service` 的对象必须通过 MapStruct 转化为 `XxxDTO` 或 `XxxVO`。

    *   **AC-JAV-02 (全局异常收敛)**：禁止在 Controller 层书写 `try-catch` 块捕捉业务异常。必须直接抛出自定义的 `BusinessException`，由标注了 `@RestControllerAdvice` 的全局异常处理器统一接管并封装为标准 JSON 信封格式`{"code":..., "message":..., "data":...}`）。

#### 3. Go (参考标的: `golang-standards/project-layout` & `go-kratos/kratos`)

*   **架构范式**：领域驱动目录结构 + GORM + 错误冒泡机制。

*   **种子基因（AC 约束）**：

    *   **AC-GO-01 (可见性屏障)**：核心业务逻辑和数据访问层代码必须存放于 `internal/` 目录下`pkg/` 目录只能存放无副作用的纯工具函数。

    *   **AC-GO-02 (错误包裹栈)**：在非最外层的函数调用中，当捕获到 `err != nil` 时，严禁直接返回原 `err`。必须使用 `fmt.Errorf("do action failed: %w", err)` 进行错误栈包裹（Error Wrapping），保留完整的堆栈上下文。

#### 4. TypeScript (参考标的: `nestjs/nest` & `alan2207/bulletproof-react`)

*   **架构范式**：NestJS (后端) / React Feature-Sliced Design (前端)。

*   **种子基因（AC 约束）**：

    *   **AC-TS-01 (NestJS 守卫越权防范)**：任何负责处理写操作`@Post`, `@Put`, `@Delete`）的控制器方法，在 AST 层面必须检测到绑定了 `@UseGuards(JwtAuthGuard)` 或类似的权限校验装饰器，禁止存在无鉴权的裸露写接口。

    *   **AC-TS-02 (React 状态下放)**：对于前端组件，严禁在顶层页面组件（Page Component）中书写直接的 `fetch` 或 `axios` 调用。所有网络请求必须封装在特征目录`features/xxx/api/`）下的自定义 Hook（如 `useQuery` 或 SWR）中。