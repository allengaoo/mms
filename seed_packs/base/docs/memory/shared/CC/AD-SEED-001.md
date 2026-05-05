---
id: AD-SEED-001
layer: CC
module: architecture
type: decision
tier: hot
tags: [architecture, layering, separation-of-concerns, cold-start, seed]
source_ep: EP-130
created_at: 2026-04-18
version: 1
generalized: true
cites_files: []
related_to:
  - id: AD-SEED-002
    reason: "分层架构约束依赖接口契约约束"
---

# AD-SEED-001: 分层架构边界约束（通用）

## 决策

所有企业级软件必须遵守严格的分层边界，禁止跨层直接依赖。

## 约束条款

1. **表示层**不包含业务逻辑（仅做请求/响应转换）
2. **应用服务层**编排业务流程，不直接操作数据库
3. **领域层**封装核心业务规则，不依赖任何框架
4. **基础设施层**实现技术细节（DB、MQ、Cache），通过接口向上暴露

## 违反后果

跨层直接依赖导致：修改一个地方需要改动多处，测试困难，架构腐化。

## 检测方式

代码中出现 `import` 跨层路径时触发告警（见 `arch_check.py`）。
