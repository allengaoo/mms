---
id: MEM-L-004
layer: L4_application
module: workers
dimension: D4_resilience
type: lesson
tier: hot
description: "Docker COPY 路径相对于 build context 目录（-f 参数指定），而非 Dockerfile 所在目录"
tags: [docker, dockerfile, build-context, copy, requirements, path]
source_ep: EP-098
created_at: "2026-02-24"
version: 1
last_accessed: "2026-04-11"
access_count: 4
related_memories: [MEM-L-005, MEM-L-008]
also_in: []
generalized: true
---

# MEM-L-004 · Docker 镜像构建的上下文陷阱

## WHERE（发生层/模块）
Layer 4 应用层 → 部署/运维域 → Docker build context

## WHAT（问题类型）
Dimension 4: 弹性与事务 — 部署陷阱（非事务，归类于弹性）

## WHY（根因与影响）
**触发条件**：在项目根目录执行 `docker build -f backend/Dockerfile .`
**症状**：`COPY requirements.txt .` 报错找不到文件
**根因**：`COPY` 中的路径相对于 build context（`.`），不是 Dockerfile 所在目录

## HOW（正确方式）
```bash
# ✅ 在 Dockerfile 所在目录执行（context = backend/）
cd backend && docker build .

# ✅ 如必须从根目录执行，需调整 COPY 路径
docker build -f backend/Dockerfile --build-context backend=./backend .

# ❌ 错误：从根目录执行，Dockerfile 中 COPY requirements.txt
cd /project_root
docker build -f backend/Dockerfile .   # requirements.txt 找不到
```

## WHEN（应用条件）
- ✅ 每次构建后端镜像时，在 `backend/` 目录内执行 `docker build .`
- ✅ Makefile / CI 中硬编码正确的 cwd
