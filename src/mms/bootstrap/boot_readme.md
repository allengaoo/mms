# MMS Bootstrap 模块 (src/mms/bootstrap)

## 1. 模块定位

`src/mms/bootstrap` 是 MMS 系统的**冷启动与初始化引擎 (Cold Start & Initialization Engine)**。它负责在一个全新的或现有的代码仓库中，自动推断架构、提取代码特征，并生成初始的记忆图谱（Memory Graph）。

## 2. 核心代码文件与核心方法

### `signal_fusion.py`

架构推断的大脑，负责融合多路信号。

- `**fn_infer_layer(file_path)`**: 根据文件路径、命名约定等推断其所属的架构层级（如 `L3_domain`, `L4_application`）。
- `**fn_detect_code_object_type(ast_node, layer)`**: 结合 AST 节点特征和所属层级，推断具体的 ObjectType（如 `DatabaseTable`, `APIEndpoint`）。

### `code_graph_builder.py`

负责底层代码结构的静态分析。

- `**fn_build_code_graph(project_root)`**: 扫描整个代码库，解析 AST，提取类、函数定义及其相互调用/依赖关系，构建 `CodeGraph`。

### `memory_seed_generator.py`

负责将代码结构转化为记忆节点。

- `**GeneratedMemory` (DataClass)**: 承载生成的记忆节点数据。
- `**generate_seeds(code_graph, layer_inferences)`**: 遍历代码图谱，为核心 CodeClass 生成初始的 `MEM-BOOT-*.md` 记忆文件，自动填充 `layer`, `cites_files` 等 Front-matter。

### `ontology_populator.py`

顶层编排脚本，整合上述流程。

- `**bootstrap_project(project_root)`**: 暴露给 CLI 的主入口，顺序调用 Graph Builder -> Signal Fusion -> Seed Generator，并生成 `BootstrapV2Report`。

## 3. 业务流程图

### 3.1 Bootstrap v2 执行流程 (Mermaid)

```mermaid
graph TD
    A[CLI: mms bootstrap] --> B(ontology_populator.bootstrap_project)
    
    subgraph 1. 图谱构建阶段
        B --> C[code_graph_builder.fn_build_code_graph]
        C --> D{AST 解析与依赖提取}
        D --> E[生成 CodeGraph]
    end
    
    subgraph 2. 信号融合阶段
        E --> F[signal_fusion.fn_infer_layer]
        F --> G[signal_fusion.fn_detect_code_object_type]
        G --> H[生成 Layer & Type 映射]
    end
    
    subgraph 3. 记忆生成阶段
        H --> I[memory_seed_generator.generate_seeds]
        I --> J{填充 Markdown Front-matter}
        J --> K[写入 docs/memory/shared/MEM-BOOT-*.md]
    end
    
    subgraph 4. 种子包注入 (可选)
        B --> L[嗅探项目依赖]
        L --> M{匹配 seed_packs/match_conditions.yaml}
        M -- 匹配成功 --> N[拷贝预制 Markdown 记忆]
    end
    
    K --> O[生成 BootstrapV2Report]
    N --> O
    O --> P[结束]
```



