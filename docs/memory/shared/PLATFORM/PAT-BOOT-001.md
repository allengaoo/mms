---
id: PAT-BOOT-001
type: pattern
layer: L1_platform
dimension: architecture
source_ep: EP-000
tier: warm
tags: [config, configuration, cross-cutting, infrastructure, trace]
cites_files:
  - src/mms/trace/tracer.py
about_concepts: [config, infrastructure, trace]
impacts: []
derived_from: []
ast_pointer:
  file_path: src/mms/trace/tracer.py
  class_name: TraceConfig
  fingerprint: 
  drift: false
provenance:
  trigger_type: bootstrap_v2
  generated_at: 2026-05-02
  layer_confidence: 0.70
version: 1
created_at: 2026-05-02
---
# TraceConfig — 平台配置，定义横切基础设施（安全/配置/Bean 注册等）

> **自动生成**：由 `mulan bootstrap` v2 扫描代码库生成，基于五路信号融合（置信度 70%）。
> 请在积累实际使用经验后，用 `mulan distill` 或 `mulan private` 完善此记忆。

## 代码位置

- 文件：`src/mms/trace/tracer.py`
- 继承：—
- 注解：—

## 公开方法

  - `__init__(self, ep_id: str, enabled: bool = False, level: int = _DEFAULT_LEVEL, trace_id: Optional[str] = None, started_at: Optional[str] = None, stopped_at: Optional[str] = None, event_count: int = 0, max_events: int = _DEFAULT_MAX_EVENTS, preview_chars: int = _DEFAULT_PREVIEW_CHARS) -> None`
  - `save(self) -> None`
  - `load(cls, ep_id: str) -> Optional['TraceConfig']`
  - `load_or_default(cls, ep_id: str) -> 'TraceConfig'`

## 架构职责

此类属于 **PLATFORM** 层的 **Config** 类型。平台配置，定义横切基础设施（安全/配置/Bean 注册等）。

- 修改此类时，请同步更新相关 MemoryNode 的 `cites_files` 和 `about_concepts`。
- 如此类发生接口契约变更，请运行 `mulan ast-diff` 检测影响范围。
