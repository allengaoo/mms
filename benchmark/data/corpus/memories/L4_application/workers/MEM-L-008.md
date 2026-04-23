---
id: MEM-L-008
layer: L4_application
module: workers
dimension: D3_observability
type: lesson
tier: hot
description: "Compose 和 K8s 并存时，K8s Service 和 Compose port-forward 路由到不同实例；只保留一套调试入口"
tags: [docker, k8s, deployment, image-version, routing, compose, double-stack]
source_ep: EP-100
created_at: "2026-03-06"
version: 1
last_accessed: "2026-04-11"
access_count: 9
related_memories: [MEM-L-004, MEM-L-005, MEM-L-009]
also_in: [L1_platform/D3_observability]
generalized: true
---

# MEM-L-008 · 双栈运行陷阱：Docker Compose + K8s 共存时流量路由不透明

## WHERE（发生层/模块）
Layer 4 应用层 → 部署/运维域 → Docker Compose + K8s 双栈

## WHAT（问题类型）
Dimension 3: 可观测性 — 流量路由不透明导致修复无效

## WHY（根因与影响）
**触发条件**：同时运行 Docker Compose 栈（旧版本）和 K8s 栈（新版本）
**症状**：EP 代码修复完成并部署到 K8s，但问题依然存在；`localhost:8000` 流量走的是 Compose 旧版本
**根因**：Docker Compose 绑定 `0.0.0.0:8000`，优先于 K8s port-forward

## HOW（检测与规范）
```bash
# 检测当前 8000 端口实际由谁监听
lsof -nP -i TCP:8000
docker ps | grep "8000->8000"
docker inspect <container_id> | grep Image    # 确认镜像版本

# 修复：每次重建镜像后同步更新 Compose 容器
docker compose -f deploy/docker-compose.app.yml up -d --force-recreate
```

**EP 执行计划规范**：镜像重建步骤必须同时包含：
1. `docker build` 新镜像
2. `docker compose up -d` 更新 Compose 容器
3. OR 明确说明「本次仅更新 K8s，不影响 Compose 栈」

## WHEN（应用条件）
- ✅ 每次 EP 验收时执行双栈检测命令
- ✅ Runtime 声明节明确标注哪个栈受影响
