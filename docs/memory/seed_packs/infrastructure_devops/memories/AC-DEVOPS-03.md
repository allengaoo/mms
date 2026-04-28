---
id: AC-DEVOPS-03
tier: hot
layer: CC
protection_bonus: 0.35
tags: [kubernetes, resources, limits, requests, qos]
---
# AC-DEVOPS-03：Kubernetes Pod 必须配置 resources.requests 和 limits

## 约束
每个 container MUST 配置 `resources.requests` 和 `resources.limits`；
NEVER 部署无资源限制的 Pod（会导致节点资源争抢、OOM Kill 级联故障）。

## 反例（Anti-pattern）

```yaml
# ❌ 无资源限制：无限制消耗节点资源
containers:
  - name: api-server
    image: myapp:1.0.0
    ports:
      - containerPort: 8080
    # 缺少 resources 配置
```

## 正例（Correct Pattern）

```yaml
# ✅ 配置 requests 和 limits（建议 limits = 2x requests）
containers:
  - name: api-server
    image: myapp:1.0.0
    ports:
      - containerPort: 8080
    resources:
      requests:
        cpu: "100m"        # 0.1 核（调度依据）
        memory: "256Mi"    # 调度依据
      limits:
        cpu: "500m"        # 最大 0.5 核（超过被 throttle）
        memory: "512Mi"    # 超过触发 OOM Kill

# ✅ 通过 LimitRange 设置命名空间默认值（兜底）
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
  namespace: production
spec:
  limits:
    - type: Container
      default:
        cpu: "200m"
        memory: "256Mi"
      defaultRequest:
        cpu: "100m"
        memory: "128Mi"
```

## 原因
无资源限制的 Pod 在节点内存压力下会被随机 OOM Kill，且可能
影响同节点其他 Pod。K8s 调度器依赖 requests 做节点选择，
无 requests 的 Pod 会被调度到已过载的节点，引发级联故障。
