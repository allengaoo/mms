---
id: AC-DEVOPS-05
tier: warm
layer: CC
protection_bonus: 0.30
tags: [docker, multi-stage, build, image-size, security]
---
# AC-DEVOPS-05：生产镜像必须使用多阶段构建

## 约束
生产 Docker 镜像 MUST 使用多阶段构建（multi-stage build）；
NEVER 将构建工具（gcc、make、pip install dev-deps、git）包含在最终镜像中。

## 反例（Anti-pattern）

```dockerfile
# ❌ 单阶段构建：构建工具留在最终镜像（镜像 >1GB，攻击面大）
FROM python:3.12
RUN apt-get update && apt-get install -y gcc git make
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt  # 包含 dev 依赖
COPY . .
RUN python setup.py build_ext --inplace  # 编译扩展
CMD ["gunicorn", "app:app"]
# 最终镜像包含 gcc、git、所有构建产物 → 安全风险 + 体积过大
```

## 正例（Correct Pattern）

```dockerfile
# ✅ 多阶段构建：只有运行时产物进入最终镜像

# === 阶段 1：构建 ===
FROM python:3.12-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends gcc
WORKDIR /build
COPY requirements.txt requirements-prod.txt ./
RUN pip install --user --no-cache-dir -r requirements-prod.txt
COPY . .
RUN python setup.py build_ext --inplace

# === 阶段 2：运行时（最终镜像）===
FROM python:3.12-slim AS runtime
# 非 root 用户
RUN groupadd -r app && useradd -r -g app app
WORKDIR /app

# 只从 builder 阶段复制必要产物
COPY --from=builder /root/.local /home/app/.local
COPY --from=builder /build/myapp ./myapp
COPY --from=builder /build/*.so ./

USER app
ENV PATH="/home/app/.local/bin:$PATH"
EXPOSE 8080
CMD ["gunicorn", "--workers=4", "--bind=0.0.0.0:8080", "myapp.wsgi:app"]
```

## 原因
多阶段构建可将最终镜像体积从 >1GB 压缩至 ~150MB，
移除 gcc/git 等工具消除潜在的提权攻击面。
镜像推拉速度提升 3-5x，冷启动时间缩短 30%+。
