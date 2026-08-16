---
id: MEM-D-027
layer: L3
dimension: D4
type: decision
tier: "cold"
tags: [template, others, fallback]
source_ep: EP-126
created_at: "2026-04-19"
last_accessed: "2026-04-19"
access_count: 0
related_memories: []
also_in: []
generalized: false
version: 1
---

# MEM-D-027 · 新增 ep-others 兜底模板提升分类完备性

## WHERE（在哪个模块/场景中）
MMS templates / synthesizer

## WHAT（发生了什么）
为跨层任务和非典型场景提供统一兜底模板，避免强制归类

## WHY（根本原因）
当前 6 类模板无法覆盖文档整理、安全加固等任务，导致 EP 上下文质量下降

## HOW（解决方案）
创建 ep-others 模板并注册到 CLI 和 task_matcher，提供宽泛但结构化的引导

## WHEN（触发条件）
发现模板分类存在明显空白时
