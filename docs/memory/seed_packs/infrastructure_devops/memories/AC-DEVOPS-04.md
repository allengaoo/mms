---
id: AC-DEVOPS-04
tier: hot
layer: CC
protection_bonus: 0.35
tags: [kubernetes, health-check, liveness, readiness, probe]
---
# AC-DEVOPS-04：Kubernetes Pod 必须配置存活探针和就绪探针

## 约束
每个提供 HTTP 服务的 container MUST 配置 `livenessProbe` 和 `readinessProbe`；
NEVER 部署无探针的服务（K8s 无法感知应用层崩溃，流量会继续路由到不健康实例）。

## 反例（Anti-pattern）

```yaml
# ❌ 无探针：Pod 内进程崩溃后 K8s 仍路由流量（直到 TCP 超时）
containers:
  - name: api-server
    image: myapp:1.0.0
    ports:
      - containerPort: 8080
    # 缺少 livenessProbe 和 readinessProbe
```

## 正例（Correct Pattern）

```yaml
containers:
  - name: api-server
    image: myapp:1.0.0
    ports:
      - containerPort: 8080

    # ✅ 就绪探针：确保 Pod 启动完成才接收流量
    readinessProbe:
      httpGet:
        path: /health/ready    # 应用定义的就绪检查端点
        port: 8080
      initialDelaySeconds: 10  # 等待应用启动
      periodSeconds: 5
      failureThreshold: 3

    # ✅ 存活探针：检测应用死锁/崩溃，触发自动重启
    livenessProbe:
      httpGet:
        path: /health/live     # 轻量级存活检查（不含依赖检查）
        port: 8080
      initialDelaySeconds: 30  # 留足启动时间（避免误杀）
      periodSeconds: 10
      failureThreshold: 3

    # ✅ 启动探针：处理慢启动应用（如 JVM 预热）
    startupProbe:
      httpGet:
        path: /health/live
        port: 8080
      failureThreshold: 30     # 允许 5 分钟启动时间
      periodSeconds: 10
```

## 原因
`readinessProbe` 控制流量路由：Pod 未就绪时 Service 不转发；
`livenessProbe` 控制重启策略：探针失败时 kubelet 自动重启 Pod。
两者协同可实现零宕机滚动发布和自愈能力。
