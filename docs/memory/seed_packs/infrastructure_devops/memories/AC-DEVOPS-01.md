---
id: AC-DEVOPS-01
tier: hot
layer: CC
protection_bonus: 0.40
tags: [docker, security, non-root, container, hardening]
---
# AC-DEVOPS-01：Dockerfile 必须以非 root 用户运行

## 约束
容器进程 MUST 以非 root 用户执行；
NEVER 在生产 Dockerfile 中省略 `USER` 指令（默认 root 运行，容器逃逸风险极高）。

## 反例（Anti-pattern）

```dockerfile
# ❌ 默认以 root 运行（安全风险）
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "main.py"]
# 缺少 USER 指令 → root 运行
```

## 正例（Correct Pattern）

```dockerfile
# ✅ 非 root 用户运行
FROM python:3.12-slim

# 创建非特权用户和组
RUN groupadd -r appgroup && useradd -r -g appgroup -d /app -s /bin/false appuser

WORKDIR /app

# 先以 root 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appgroup . .

# 切换到非 root 用户
USER appuser

EXPOSE 8080
CMD ["python", "main.py"]
```

## 原因
容器以 root 运行时，如果发生容器逃逸漏洞，攻击者将以 root
权限访问宿主机文件系统。非 root 用户可将攻击面缩小 80%+。
CIS Docker Benchmark 将此列为必须项（Level 1）。
