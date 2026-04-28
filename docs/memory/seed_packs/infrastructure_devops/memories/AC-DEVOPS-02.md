---
id: AC-DEVOPS-02
tier: hot
layer: CC
protection_bonus: 0.35
tags: [docker, image, versioning, reproducibility, pinning]
---
# AC-DEVOPS-02：基础镜像必须固定版本，禁止使用 :latest

## 约束
Dockerfile 中 MUST 固定基础镜像的 digest 或具体版本标签；
NEVER 使用 `:latest` 标签（不可重现构建，上游更新可能引入 breaking changes）。

## 反例（Anti-pattern）

```dockerfile
# ❌ :latest 不可重现，上游更新可能静默破坏构建
FROM python:latest
FROM node:latest
FROM ubuntu:latest
FROM redis:latest
```

## 正例（Correct Pattern）

```dockerfile
# ✅ 固定具体版本
FROM python:3.12.3-slim-bookworm

# ✅ 或固定 digest（最严格，可完全重现）
FROM python:3.12.3-slim-bookworm@sha256:abc123def456...

# ✅ docker-compose 同样需要固定版本
# docker-compose.yml
services:
  redis:
    image: redis:7.2.4-alpine   # ✅ 具体版本
  postgres:
    image: postgres:16.2        # ✅ 具体版本
  # ❌ image: redis:latest
```

## 原因
`:latest` 标签在每次 `docker pull` 时可能拉取不同的镜像内容。
上游镜像的小版本更新可能引入 Python 运行时变化、系统库安全补丁
（有时会破坏 ABI 兼容性），导致"在我机器上能跑"的问题。
固定版本确保 CI/CD 环境和生产环境使用完全相同的镜像层。
