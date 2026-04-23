---
id: MEM-L-009
layer: L1_platform
module: observability
dimension: D3_observability
type: lesson
tier: hot
description: "Python 容器未设 PYTHONUNBUFFERED=1 时日志缓冲，kubectl logs 看不到输出；必须在 Dockerfile 或 env 中设置"
tags: [k8s, docker, python, logs, PYTHONUNBUFFERED, stdout, buffering]
source_ep: EP-100
created_at: "2026-03-06"
version: 1
last_accessed: "2026-04-11"
access_count: 6
related_memories: [MEM-L-008]
also_in: []
generalized: true
---

# MEM-L-009 · kubectl logs 日志不可见的根因是 PYTHONUNBUFFERED 未设置

## WHERE（发生层/模块）
Layer 1 平台横切层 → 可观测性 → K8s 容器 Python 日志输出

## WHAT（问题类型）
Dimension 3: 可观测性 — 日志输出不可见（排查困难）

## WHY（根因与影响）
**触发条件**：K8s 容器未设置 `PYTHONUNBUFFERED=1`
**症状**：`kubectl logs mdp-backend-xxx` 输出为空，触发任务后完全无日志
**根因**：Python stdout 默认块缓冲模式（buffer size 8KB），日志在内存中积累不立即写出

## HOW（修复）
```dockerfile
# ✅ Dockerfile 中添加（一次配置，永久生效）
ENV PYTHONUNBUFFERED=1
```

```yaml
# ✅ 或 K8s Deployment env 中添加
env:
  - name: PYTHONUNBUFFERED
    value: "1"
```

## WHEN（应用条件）
- ✅ 所有 Python 服务的 Dockerfile
- ✅ K8s Deployment YAML（如果 Dockerfile 未设置）
- ✅ 每次创建新后端镜像时检查此项

## 禁止项
- ❌ 在没有 `PYTHONUNBUFFERED=1` 的情况下交付 K8s Python 容器
