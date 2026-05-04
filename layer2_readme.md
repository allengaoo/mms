# Layer 2: 知识本体层 (Knowledge Ontology Layer)

## 1. 架构定位

Layer 2 是 MMS 系统的“大脑皮层”，负责将散落的代码、文档和架构约束转化为机器可读、可计算的**有向知识图谱 (Knowledge Graph)**。它为 Layer 1 (任务工程层) 提供精准的上下文注入，并为其他分析和应用层提供决策依据。

## 2. 组件架构与职责分布

Layer 2 采用“引擎 (Engine) - 资产 (Assets) - 实例数据 (Instance Data)”分离的三层架构设计。

### 2.1 组件架构图 (Mermaid)

```mermaid
graph TD
    subgraph Engine [引擎层 (src/mms/)]
        M[Memory Engine<br/>图谱操作/上下文注入]
        O[Ontology Engine<br/>Schema 解析/校验]
        B[Bootstrap Engine<br/>冷启动/架构推断]
    end

    subgraph Assets [资产与配置层]
        OS[Ontology Schema<br/>assets/ontology_schema/]
        SP[Seed Packs<br/>src/mms/bootstrap/seed_packs/]
    end

    subgraph Data [实例数据层]
        MD[Memory Nodes<br/>docs/memory/shared/*.md]
    end

    %% 依赖关系
    M -->|读取/写入| MD
    M -->|查询规则| O
    O -->|解析 YAML| OS
    B -->|注入先验知识| SP
    B -->|生成初始节点| MD
```

### 2.2 核心组件职责

- **Memory Engine (`src/mms/memory/`)**: 运行时操作核心。负责解析 Markdown 为图结构，在 EP 执行前进行上下文注入，以及后台的知识萃取与腐化检测。
- **Ontology Engine (`src/mms/ontology/`)**: Schema 的运行时代理。负责读取 YAML 格式的本体定义，提供内存注册表供 Memory 引擎校验。
- **Bootstrap Engine (`src/mms/bootstrap/`)**: 项目初始化引擎。通过 AST 分析自动推断架构层级，并结合 Seed Packs 生成初始记忆。
- **Ontology Schema (`assets/ontology_schema/`)**: 声明式的“世界观”定义（YAML），定义了系统支持的节点类型和边类型。
- **Seed Packs (`src/mms/bootstrap/seed_packs/`)**: 按技术栈划分的预制 Markdown 记忆文件，提供初始的“先验知识”。

## 3. 核心业务流程与数据流

### 3.1 Layer 2 整体数据流图 (Mermaid)

```mermaid
flowchart LR
    Code[物理代码库] -->|1. AST 解析 & 信号融合| Boot(Bootstrap Engine)
    SP[(Seed Packs)] -->|2. 匹配注入| Boot
    Boot -->|3. 生成初始节点| Graph[(Memory Graph<br/>Markdown Files)]
    
    YAML[(Ontology Schema)] -->|4. 懒加载| Onto(Ontology Engine)
    
    Task[Layer 1 任务请求] -->|5. 发起检索| Mem(Memory Engine)
    Mem <-->|6. 校验与路由| Onto
    Mem <-->|7. 图遍历与混合检索| Graph
    Mem -->|8. 组装 Prompt| Task
    
    Log[EP 执行日志] -->|9. 异步萃取| Dream(Dream Engine)
    Dream -->|10. 沉淀新知识| Graph
```

## 4. 目录结构设计原则 (Design Principles)

经过近期的架构重构，Layer 2 实现了严格的**高内聚与物理隔离**，当前的目录结构如下：

```text
src/mms/
├── memory/                 # 引擎：图谱操作与上下文注入
├── ontology/               # 引擎：Schema 解析与内存注册表
├── bootstrap/              # 引擎：冷启动与架构推断
│   └── seed_packs/         # 资产：作为 Bootstrap 的专属数据源，收敛在引擎内部

assets/                     # 资产：系统级静态资产
└── ontology_schema/        # 资产：全局本体 Schema 定义 (原 docs/memory/ontology)

docs/memory/                # 数据：明确边界，仅存放当前项目生成的实例数据
├── shared/                 # 数据：实际记忆节点 (*.md)
└── private/                # 数据：草稿与私有数据
```

**设计收益**：
1. **语义清晰**：将系统级的 Schema 配置 (`assets/ontology_schema`) 与项目级的实例数据 (`docs/memory`) 彻底分离，避免了原先混用在 `docs/` 目录下的语义歧义。
2. **高内聚**：将 `seed_packs` 移入 `src/mms/bootstrap/`，遵循了“谁使用谁管理”的原则，收敛了项目根目录，降低了开发者的认知负担。
