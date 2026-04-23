---
id: MEM-L-005
layer: L4_application
module: workers
dimension: D4_resilience
type: lesson
tier: hot
description: "kubectl set-image 容器名不等于 Deployment 名；必须先 kubectl describe deploy 查 spec.containers[].name"
tags: [kubectl, set-image, container-name, k8s, deployment]
source_ep: EP-098
created_at: "2026-02-24"
version: 1
last_accessed: "2026-04-11"
access_count: 5
related_memories: [MEM-L-004, MEM-L-009]
also_in: []
generalized: true
---

# MEM-L-005 · kubectl set-image 必须查容器名

## WHERE（发生层/模块）
Layer 4 应用层 → 部署/运维域 → K8s Deployment 镜像更新

## WHAT（问题类型）
Dimension 4: 弹性与事务 — K8s 部署陷阱

## WHY（根因与影响）
**触发条件**：`kubectl set image deployment/mdp-backend mdp-backend=...`
**症状**：`unable to find container named "mdp-backend"`（实际容器名是 `api`）
**根因**：K8s Deployment 的容器名由 `spec.template.spec.containers[].name` 决定，与 Deployment 名字无关

## HOW（正确流程）
```bash
# ✅ 先查容器名
kubectl get deployment mdp-backend -n mdp \
  -o jsonpath='{.spec.template.spec.containers[*].name}'
# 输出: api

# ✅ 再用正确容器名更新镜像
kubectl set image deployment/mdp-backend api=mdp-backend:ep107 -n mdp
```

## WHEN（应用条件）
- ✅ 每次执行 `kubectl set image` 前必须先查容器名
- ✅ 在 EP 执行计划的 Runtime 声明节记录容器名

## 禁止项
- ❌ 假设容器名 = Deployment 名（几乎总是错的）
