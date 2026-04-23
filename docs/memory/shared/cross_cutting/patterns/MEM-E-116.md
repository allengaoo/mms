---
id: MEM-E-116
layer: L1
dimension: ontology
type: error
tier: "cold"
tags: [ep-file, missing, cli, configuration, debugging]
source_ep: ep-116
created_at: "2026-04-17"
last_accessed: "2026-04-17"
access_count: 0
related_memories: []
also_in: []
generalized: false
version: 1
---

# MEM-E-116 · EP 文件未找到错误提示

## WHERE（在哪个模块/场景中）
CLI 启动流程

## WHAT（发生了什么）
执行 MDP 命令时因未指定 --ep-file 参数导致 ep-116 文件路径缺失，触发‘EP 文件未找到’硬错误

## WHY（根本原因）
MDP 工具在 EP 模式下强制要求显式提供 EP 文件路径，无默认值或 fallback 机制

## HOW（解决方案）
始终通过 --ep-file 显式传入有效 EP 文件路径；CI/CD 中增加路径存在性校验；CLI 添加 --ep-default 或 --ep-auto-resolve 选项（待实现）

## WHEN（触发条件）
调用 mdp run --ep ep-116 且未附加 --ep-file 参数时
