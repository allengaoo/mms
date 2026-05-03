# DAG 层 (Directed Acyclic Graph)

## 1. 架构定位

DAG 层是木兰 (Mulan) 任务工程层 (Layer 1) 的核心数据结构模块。它负责将高层级的执行计划 (EP) 转化为机器可读的、带有依赖关系的原子任务图 (DAG)。
在木兰系统中，大模型不直接处理模糊的宏观需求，而是由 DAG 层将其拆解为一系列确定性的 **AIU (Atomic Intent Unit, 原子意图单元)**，从而实现“大任务拆小，小任务确定化”。

## 2. 核心概念

- **DagState**: 整个 EP 对应的执行状态机，包含多个 `DagUnit` 以及全局状态（如 `pending`, `in_progress`, `done`）。它负责维护任务的拓扑顺序和断点续跑状态。
- **DagUnit**: DAG 图中的单个节点。它描述了一个具体的执行动作，包含涉及的文件 (`files`)、依赖的前置节点 (`depends_on`)、执行顺序 (`order`) 以及绑定的模型提示 (`model_hint`)。
- **AIU (Atomic Intent Unit)**: 编码动作的原子抽象。木兰预定义了 9 族 43 种 AIU 类型（如 `SCHEMA_ADD_FIELD`, `ENDPOINT_ADD`），每种 AIU 都有严格的输入输出 Schema 和验证规则。
- **Task Decomposer**: 负责将自然语言的 EP 描述解析并转化为结构化的 DAG 节点。

## 3. 核心文件与方法签名

### `src/mms/dag/`

#### 1. `dag_model.py` (DAG 状态模型)
定义了 DAG 的数据结构和状态流转逻辑。

- `class DagUnit:`
  - 属性: `id`, `title`, `files`, `depends_on`, `status` 等。
  - `def is_executable(self, done_ids: List[str]) -> bool`: 判断当前节点是否满足执行条件（所有依赖项均已完成）。
- `class DagState:`
  - 属性: `ep_id`, `units`, `overall_status` 等。
  - `def done_ids(self) -> List[str]`: 获取所有已完成的 Unit ID。
  - `def mark_done(self, unit_id: str, commit_hash: Optional[str] = None) -> None`: 标记节点为完成，并更新全局状态。
  - `def to_dict(self) -> dict` / `def from_dict(cls, data: dict) -> "DagState"`: 状态的序列化与反序列化。
- `def make_dag_state(ep_id: str, units_data: List[dict], orchestrator_model: str) -> DagState`: 工厂方法，用于初始化全新的 DAG 状态。

#### 2. `task_decomposer.py` (任务拆解器)
将 EP Markdown 转化为 DAG 结构。

- `class TaskDecomposer:`
  - `def decompose(self, ep_doc: EpDocument) -> DagState`: 核心方法，解析 EP 并生成 DAG。

#### 3. `aiu_types.py` & `aiu_registry.py` (原子意图单元定义)
定义了系统中所有合法的 AIU 类型及其 Schema。

- `class AIUType(str, Enum):`: 枚举所有支持的 AIU 类型。
- `class AIURegistry:`: 注册表，用于获取特定 AIU 类型的验证规则和 Schema。

#### 4. `atomicity_check.py` (原子性校验)
验证生成的 Unit 是否符合原子性要求（如修改文件数量是否超标，逻辑是否过于复杂）。

## 4. 状态流转机制

每个 `DagUnit` 具有以下状态流转：
- `pending`: 初始状态，等待依赖项完成。
- `in_progress`: 正在执行中。
- `done`: 执行成功，且通过了所有的独立验证（如 AST 检查、单元测试）。
- `skipped`: 被用户或系统显式跳过。
- `failed`: 执行失败，且耗尽了重试次数（3-Strike）。

`DagState` 会根据所有 `DagUnit` 的状态自动计算 `overall_status`，从而驱动 `ep_runner` 的断点续跑和幂等执行。