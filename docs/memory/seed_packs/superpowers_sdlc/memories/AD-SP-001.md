---
id: AD-SP-001
layer: CC
dimension: architecture
type: decision
object_type: Decision
tier: hot
tags: [superpowers, brainstorming, design-gate, frontend, backend, sdlc]
source_ep: EP-000
created_at: "2026-07-19"
version: 1
about_concepts: [design-before-code, hard-gate, interface-boundary]
cites_files: []
related_to:
  - id: AD-SP-002
    reason: "设计批准后进入 Spec→Plan 流水线"
---

# AD-SP-001: 先设计后实现（Hard Gate）

## 决策

源自 [obra/superpowers · brainstorming](https://github.[REDACTED_SECRET])：
在获得用户批准的设计之前，**禁止**调用任何实现技能、写业务代码或脚手架。

## 约束条款

1. 任何功能/行为变更先探索项目上下文，再一次只问一个澄清问题
2. 提出 2–3 个方案并给出推荐与权衡
3. 分段呈现设计（架构、组件、数据流、错误处理、测试），逐段确认
4. 单元须满足：单一职责、清晰接口、可独立理解与测试
5. 「太简单不需要设计」是反模式——简单项目更易因未检验假设浪费返工

## 对前后端的含义

- **后端**：先定 API 契约、领域边界、失败路径，再写 handler/service
- **前端**：先定组件边界与数据流，再写页面/store
- **小模型**：优先生成边界清晰的小文件，避免巨型模块

## 检测方式

流程门禁：`synthesize` / `unit generate` 前应存在已批准规格或等价设计记录。
映射约束：`SP-GATE-001`。
