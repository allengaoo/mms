---
id: PAT-SP-004
layer: CC_governance
dimension: governance
type: pattern
object_type: Pattern
tier: hot
tags: [superpowers, verification, postcheck, completion-gate, ci]
source_ep: EP-000
created_at: "2026-07-19"
version: 1
about_concepts: [verification-before-completion, evidence-based-done]
cites_files:
  - src/mms/workflow/postcheck.py
---

# PAT-SP-004: 完成前验证（Verification Before Completion）

## 模式（Pattern）

源自 verification-before-completion。
在宣称「做完了 / 修好了 / 可合并」之前，必须运行**真实验证命令**并阅读输出。

## 铁律

- 不允许「应该能过」代替实际运行
- 不允许只跑子集却声称全绿（除非明确声明范围）
- 失败输出必须被阅读并处理，而不是忽略

## 与 MMS Layer4

直接映射 `postcheck`：pytest + arch_check + MigrationGate。
Unit/EP 完成状态仅在验证证据存在后标记。

## 前后端建议命令集

- 后端：相关 pytest 路径、类型检查、arch_check
- 前端：单测 / 组件测 / 关键 e2e 子集
- 契约变更：前后端契约测试同时绿

映射约束：`SP-GATE-002`。
