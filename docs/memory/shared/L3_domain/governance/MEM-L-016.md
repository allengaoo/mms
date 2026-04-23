---
id: MEM-L-016
layer: L3
dimension: governance
type: decision
tier: cold
tags: [impact-analysis, risk-level, scenario, sync-job, links, actions]
source_ep: EP-113
created_at: "2026-04-14"
last_accessed: "2026-04-14"
access_count: 0
related_memories: []
also_in: []
generalized: false
version: 1
---

# MEM-L-016 · 影响分析API须扩展风险维度与依赖计数

## WHERE（在哪个模块/场景中）
backend / impact-analysis

## WHAT（发生了什么）
GET /api/v1/object-types/{id}/impact 增加 scenario_count、sync_job_count 和 risk_level 字段

## WHY（根本原因）
原 links+actions 无法量化变更风险等级，业务方无法快速判断修改影响范围与严重性

## HOW（解决方案）
基于依赖图谱实时聚合 Scenario/SyncJob 关联数；risk_level 按阈值规则（low/medium/high）动态计算并缓存

## WHEN（触发条件）
当影响分析结果需用于自动化审批流或变更风险预检时
