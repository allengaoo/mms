---
id: SKL-SP-001
layer: CC
dimension: architecture
type: skill
object_type: Pattern
tier: warm
tags: [superpowers, sdd, subagent, unit-loop, backend]
source_ep: EP-000
created_at: "2026-07-19"
version: 1
about_concepts: [subagent-driven-development, task-brief, review-gate]
cites_files:
  - src/mms/execution/unit_runner.py
---

# SKL-SP-001: 子代理驱动开发（SDD）

## 技能（Skill）

源自 subagent-driven-development。
把计划拆成任务包：简报 → 实现子代理 → 只读评审子代理 → 合并/下一步。

## 步骤

1. 为任务准备 brief（目标、允许改的文件、验收命令、禁止事项）
2. 实现者只在范围内改动，保持小步可回滚
3. 评审者只读：对照计划，输出 Critical / Important / Minor
4. Critical 未清不得进入下一任务

## 与 MMS

对齐 Track A：`unit generate` → `unit run` → compare/review → apply。
小模型适合「窄 brief + 单文件行为」，正是 SDD 的优势区间。
