---
id: AC-JAV-09
layer: PLATFORM
tier: warm
type: pattern
language: java
pack: java_spring_boot
about_concepts: [actuator, security, health-check, spring-boot, production]
cites_files: []
contradicts: []
created_at: "2026-04-27"
---

# Spring Boot Actuator 生产环境必须屏蔽敏感信息

## 模式（Pattern）

Spring Boot Actuator 的 `/actuator/health`、`/actuator/env`、`/actuator/beans` 等端点在生产环境会暴露内部配置（数据库 URL、内存信息、Bean 列表）。必须在生产环境正确配置。

```yaml
# ❌ 危险：默认配置在生产环境暴露全量信息
management:
  endpoints:
    web:
      exposure:
        include: "*"           # 暴露所有端点！
  endpoint:
    health:
      show-details: always     # 暴露 DB 连接信息、磁盘空间等！
```

```yaml
# ✅ 正确：生产环境配置
management:
  endpoints:
    web:
      exposure:
        include: "health,info,metrics"   # 只暴露必要端点
      base-path: "/internal"             # 修改基础路径（配合网关 IP 白名单）
  endpoint:
    health:
      show-details: never                # 不暴露详细健康信息
      show-components: never
    info:
      enabled: true
  server:
    port: 8081                           # 管理端口与业务端口分离
```

## 推荐架构：管理端口隔离

```yaml
# Kubernetes 场景：业务端口 8080 对外，管理端口 8081 仅集群内访问
server:
  port: 8080

management:
  server:
    port: 8081    # K8s Service 不暴露此端口，只有 liveness/readiness probe 访问
```

## 参考

- Spring Boot 文档：[Actuator Security](https://docs.spring.io/spring-boot/docs/current/reference/html/actuator.html#actuator.endpoints.security)
