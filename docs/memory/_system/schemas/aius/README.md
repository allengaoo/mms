# AIU 合约 Schema 目录

本目录存放所有 AIU（原子意图单元）的 YAML 合约定义，实现 Schema-Driven AIU（开闭原则）。

## 设计原则

- **开放扩展**：新增 AIU 类型只需添加 YAML 文件，无需修改 Python 代码
- **双轨并行**：YAML 定义优先，Python Enum 作为兜底（保证向后兼容）
- **合约完备**：每个 AIU 定义必须包含 `input_schema` 和 `validation_rules`

## 文件组织

```
aius/
├── README.md               # 本文件
├── family_A_schema.yaml    # 族 A：结构定义类（6 种）
├── family_B_control.yaml   # 族 B：逻辑流控制类（5 种）
├── family_C_data.yaml      # 族 C：数据读写类（5 种）
├── family_D_interface.yaml # 族 D：接口与路由类（5 种）
├── family_E_infra.yaml     # 族 E：事件与基础设施类（4 种）
├── family_F_quality.yaml   # 族 F：质量保障类（3 种）
├── family_G_distributed.yaml  # 族 G：分布式协调类（4 种，v3.0 新增）
├── family_H_governance.yaml   # 族 H：治理与合规类（4 种，v3.0 新增）
├── family_I_observability.yaml # 族 I：可观测性类（3 种，v3.0 新增）
└── custom/                 # 用户自定义扩展（不纳入内置管理）
    └── k8s_example.yaml    # 示例：K8S 专用 AIU
```

## 合约 Schema 格式

```yaml
id: AIU_TYPE_ID           # 必填，全大写蛇形命名
family: A_schema          # 所属族
layer_affinity: [ADAPTER, DOMAIN]  # 架构层亲和性
exec_order: 1             # 执行顺序
base_cost: 1800           # 基础 Token 成本
description: "..."        # 人类可读描述

input_schema:             # 必填：DAG 编排时 LLM 须遵守的输入参数 Schema
  field_name:
    type: string
    description: "..."
    required: true
    enum: [value1, value2]  # 可选：枚举约束

validation_rules:         # 必填：代码审查时的 AST 验证规则
  ast_target: "ClassDef"  # 目标 AST 节点类型
  required_patterns: []   # 生成代码中必须包含的模式
  forbidden_patterns: []  # 生成代码中禁止出现的模式
```

## 加载方式

由 `src/mms/dag/aiu_registry.py` 的 `AIURegistry` 在启动时读取。
YAML 定义的 AIU 自动标记 `is_builtin: false`。
