---
id: MEM-E-028
layer: L3
dimension: D4
type: error
tier: "cold"
tags: [tagging, intent-map, semantic-mismatch]
source_ep: EP-126
created_at: "2026-04-19"
last_accessed: "2026-04-19"
access_count: 0
related_memories: []
also_in: []
generalized: false
version: 1
---

# MEM-E-028 · 模板标签与 intent_map 层标签语义不一致风险

## WHERE（在哪个模块/场景中）
task_matcher.py / intent_map.yaml

## WHAT（发生了什么）
若 _TEMPLATE_TAGS 与 intent_map 的 L1-L5/CC 标签不一致，将影响历史任务相似度计算

## WHY（根本原因）
标签系统是 MMS 内部匹配机制的核心，不一致会导致上下文检索错误

## HOW（解决方案）
确保每个新模板的标签严格符合 intent_map 的层级定义

## WHEN（触发条件）
添加或修改模板时必须进行标签一致性校验
