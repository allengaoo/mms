---
id: MEM-P-029
layer: L3
dimension: D4
type: pattern
tier: "cold"
tags: [testing, structure, integration]
source_ep: EP-126
created_at: "2026-04-19"
last_accessed: "2026-04-19"
access_count: 0
related_memories: []
also_in: []
generalized: false
version: 1
---

# MEM-P-029 · 多模块注册一致性测试模式

## WHERE（在哪个模块/场景中）
test_synthesizer_structure.py

## WHAT（发生了什么）
验证模板是否在 CLI、matcher、synthesizer 三处同步注册

## WHY（根本原因）
模板结构分散注册容易遗漏，需自动化验证确保一致性

## HOW（解决方案）
编写集成测试用例，验证模板名称、路径、标签在多个模块中的一致性

## WHEN（触发条件）
每次新增或修改模板时自动运行相关测试
