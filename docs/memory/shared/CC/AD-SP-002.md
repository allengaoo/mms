---
id: AD-SP-002
layer: CC
dimension: architecture
type: decision
object_type: Decision
tier: hot
tags: [superpowers, writing-plans, task-decomposition, tdd, sdlc]
source_ep: EP-000
created_at: "2026-07-19"
version: 1
about_concepts: [spec-plan-implement-review, bite-sized-tasks, yagni]
cites_files: []
related_to:
  - id: AD-SP-001
    reason: "设计批准后才能写计划"
  - id: SKL-SP-001
    reason: "计划由 SDD 逐任务执行"
---

# AD-SP-002: Spec → Plan → Implement → Review

## 决策

源自 writing-plans / executing-plans / subagent-driven-development：
多步任务必须先有可勾选实现计划；每个任务是**可独立测试、可独立评审**的交付物。

## 约束条款

1. 计划前先锁定文件职责与边界（谁创建/修改什么）
2. 一起变更的文件放在一起；按职责拆分，而非机械按技术层堆砌
3. 步骤粒度：写失败测试 → 确认失败 → 最小实现 → 确认通过 → 提交
4. DRY / YAGNI / TDD；禁止把无关重构塞进当前目标
5. 子系统可独立交付时拆成多个计划，而非巨型计划

## 对前后端的含义

- 后端 Unit ≈ 「一个可测行为 + 对应测试」
- 前端 Unit ≈ 「一个组件/交互契约 + 行为测试」
- 对接 MMS：`unit generate` 原子化阈值与本决策对齐

## 检测方式

计划文档含 checkbox 任务；每个任务有独立验证命令。
