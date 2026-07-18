---
id: PAT-SP-003
layer: PLATFORM
dimension: observability
type: pattern
object_type: Pattern
tier: hot
tags: [superpowers, debugging, root-cause, tracing, backend]
source_ep: EP-000
created_at: "2026-07-19"
version: 1
about_concepts: [root-cause-tracing, no-symptom-fix, instrumentation]
cites_files:
  - src/mms/trace/tracer.py
---

# PAT-SP-003: Root-Cause-First 调试

## 模式（Pattern）

源自 systematic-debugging。铁律：

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

症状补丁视为失败。未完成根因调查前不得提出修复方案。

## 四阶段（摘要）

1. **根因调查**：读完整错误/堆栈；稳定复现；查近期变更；多组件边界埋点
2. **模式分析**：一个失败 vs 一类失败；找最深层共同原因
3. **最小修复**：在源头修，并加防御层（见 PAT-SP-002）
4. **防回归**：用失败测试锁定根因，再修到绿

## 后端落地

- 跨 API→Service→DB 故障：先在边界打日志证明断点，再改代码
- 对接 MMS `trace`：Unit 失败时记录组件进出数据

## 检测方式

流程门禁 `SP-GATE-003`；紧急压力下更要系统化，而非更随意。
