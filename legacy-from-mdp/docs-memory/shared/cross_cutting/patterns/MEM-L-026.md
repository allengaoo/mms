---
id: MEM-L-026
layer: L3
dimension: D4
type: lesson
tier: "cold"
tags: [template, registration, devops]
source_ep: EP-126
created_at: "2026-04-19"
last_accessed: "2026-04-19"
access_count: 0
related_memories: []
also_in: []
generalized: false
version: 1
---

# MEM-L-026 · ep-devops 模板漏注册问题修复

## WHERE（在哪个模块/场景中）
MMS CLI / task_matcher / synthesizer

## WHAT（发生了什么）
EP-123 新增了 ep-devops 模板文件，但未同步更新 CLI choices 和 task_matcher 的标签映射

## WHY（根本原因）
模板注册不完整导致用户无法通过 CLI 使用该模板，影响上下文生成质量

## HOW（解决方案）
在 cli.py、task_matcher.py 和 synthesizer.py 中补充 ep-devops 注册，并更新 help 文本

## WHEN（触发条件）
新增 EP 模板后需检查所有注册点
