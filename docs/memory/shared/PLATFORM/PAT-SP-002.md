---
id: PAT-SP-002
layer: PLATFORM
dimension: security
type: pattern
object_type: Pattern
tier: hot
tags: [superpowers, defense-in-depth, validation, security, backend, api]
source_ep: EP-000
created_at: "2026-07-19"
version: 1
about_concepts: [defense-in-depth, input-validation, environment-guard]
cites_files: []
related_to:
  - id: PAT-SP-003
    reason: "根因修复后用多层校验使缺陷不可能再现"
---

# PAT-SP-002: Defense-in-Depth 校验

## 模式（Pattern）

源自 systematic-debugging/defense-in-depth。
单点校验可被旁路；应在数据经过的**每一层**校验，使缺陷结构上不可能。

## 四层

1. **Entry**：API/CLI 边界拒绝明显非法输入
2. **Business**：领域/业务逻辑确认数据对本操作有意义
3. **Environment**：测试/CI 中拒绝危险副作用（如在非 temp 目录 git init）
4. **Debug**：关键操作记录上下文，便于取证

## 后端落地

- Handler 校验请求形状；Service 校验业务不变量；Worker 校验作用域
- 修复「非法路径/空目录」类 bug 时，至少加固 Entry + Business 两层

## 前端落地

- 表单/客户端校验不能替代服务端校验
- 对危险本地操作（写磁盘、开子进程）加环境守卫

## 与 MMS Layer4

扩展 `arch_check` / postcheck：非法数据修复 PR 必须展示多层校验。
映射约束：`SP-SEC-001`。
