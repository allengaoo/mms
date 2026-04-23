---
id: MEM-L-015
layer: L3
dimension: ontology
type: lesson
tier: cold
tags: [api, object-type, version-history, rest, backend, read-only]
source_ep: EP-113
created_at: "2026-04-14"
last_accessed: "2026-04-14"
access_count: 0
related_memories: []
also_in: []
generalized: false
version: 1
---

# MEM-L-015 · ObjectType版本历史应通过独立API暴露

## WHERE（在哪个模块/场景中）
backend / object-types

## WHAT（发生了什么）
ObjectTypeVer 表已存在但未提供查询接口，需新增 GET /api/v1/object-types/{id}/versions

## WHY（根本原因）
前端与治理工具需追溯模型演进，现有 schema-only 方式无法满足审计与回滚分析需求

## HOW（解决方案）
复用现有 ObjectTypeVer 实体，添加分页版只读端点，兼容 ETag 和 If-None-Match 缓存头

## WHEN（触发条件）
当本体对象需支持合规审计、影响溯源或版本对比时
