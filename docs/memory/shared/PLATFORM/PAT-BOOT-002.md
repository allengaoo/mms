---
id: PAT-BOOT-002
type: pattern
layer: L1_platform
dimension: architecture
source_ep: EP-000
tier: warm
tags: [config, configuration, cross-cutting, infrastructure, mms]
cites_files:
  - src/mms/utils/mms_config.py
about_concepts: [config, infrastructure]
impacts: []
derived_from: []
ast_pointer:
  file_path: src/mms/utils/mms_config.py
  class_name: MmsConfig
  fingerprint: 
  drift: false
provenance:
  trigger_type: bootstrap_v2
  generated_at: 2026-05-02
  layer_confidence: 0.70
version: 1
created_at: 2026-05-02
---
# MmsConfig — 平台配置，定义横切基础设施（安全/配置/Bean 注册等）

> **自动生成**：由 `mulan bootstrap` v2 扫描代码库生成，基于五路信号融合（置信度 70%）。
> 请在积累实际使用经验后，用 `mulan distill` 或 `mulan private` 完善此记忆。

## 代码位置

- 文件：`src/mms/utils/mms_config.py`
- 继承：—
- 注解：—

## 公开方法

  - `__init__(self, config_path: Path = _CONFIG_PATH) -> None`
  - `runner_timeout_llm(self) -> int`
  - `runner_timeout_arch_check(self) -> int`
  - `runner_timeout_test(self) -> int`
  - `runner_timeout_postcheck_test(self) -> int`
  - _...共 20 个方法_

## 架构职责

此类属于 **PLATFORM** 层的 **Config** 类型。平台配置，定义横切基础设施（安全/配置/Bean 注册等）。

- 修改此类时，请同步更新相关 MemoryNode 的 `cites_files` 和 `about_concepts`。
- 如此类发生接口契约变更，请运行 `mulan ast-diff` 检测影响范围。
