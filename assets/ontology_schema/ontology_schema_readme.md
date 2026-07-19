# MMS Ontology 定义 (assets/ontology_schema)

## 1. 模块定位

`assets/ontology_schema` 是 MMS 系统的**本体声明式 Schema 库**（唯一运行时来源）。
它以 YAML 格式存储 ObjectType / LinkType / Function / Action / Rule，由 `src/mms/ontology/registry.py` 懒加载。

> 历史镜像 `docs/memory/ontology/` 已移除；请勿再向该路径添加定义。

## 2. 目录结构

```text
assets/ontology_schema/
├── memory_schema.yaml          记忆节点 front-matter 规范（兼容 v4/v5）
├── objects/                    ObjectType（含 _memory_base.yaml）
├── links/                      LinkType（9 种）
├── functions/                  Function（9 种）
├── actions/                    Action（5 种）
├── rules/                      Rule（Bootstrap / 质量 / 增量后置）
└── _config/
    ├── universal_layers.yaml
    ├── inference_rules.yaml
    ├── traversal_paths.yaml
    └── ontology_design_principles.yaml
```

## 3. 与运行时的关系

| 资产 | 引擎 |
| --- | --- |
| `assets/ontology_schema/` | `src/mms/ontology/registry.py` + `memory/link_registry.py` |

新增或修改 Schema 只改 `assets/ontology_schema/`；CI 的 `test_ontology_principles.py` 会校验设计原则合规性。
