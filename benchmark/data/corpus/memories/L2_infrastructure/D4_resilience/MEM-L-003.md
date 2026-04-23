---
id: MEM-L-003
layer: L2_infrastructure
module: messaging
dimension: D4_resilience
type: lesson
tier: hot
description: "用 hasattr + callable 探针处理 numpy/asyncpg 等第三方类型；避免硬依赖 import 导致 ImportError"
tags: [python, duck-typing, third-party, numpy, asyncpg, import, coupling]
source_ep: EP-098
created_at: "2026-02-24"
version: 1
last_accessed: "2026-04-11"
access_count: 5
related_memories: [MEM-L-002]
also_in: []
generalized: true
---

# MEM-L-003 · Duck-typing 处理第三方库类型优于显式 import

## WHERE（发生层/模块）
Layer 2 基础设施层 → 归一化适配器层（normalizer.py）

## WHAT（问题类型）
Dimension 4: 弹性与事务 — 依赖耦合设计模式

## WHY（重要性）
**场景**：需要处理 `numpy.scalar`（`.item()`）和 `asyncpg.pgproto.UUID`（`.isoformat()`），但不想增加对 numpy/asyncpg 的硬依赖
**问题**：直接 `import numpy` 在不安装 numpy 的环境中会 ImportError

## HOW（正确模式）
```python
# ✅ Duck-typing 探针（零依赖）
def normalize_value(value):
    # 处理 numpy scalar（有 .item() 方法）
    item_method = getattr(value, 'item', None)
    if callable(item_method):
        return item_method()

    # 处理 datetime/date/UUID（有 .isoformat() 方法）
    iso_method = getattr(value, 'isoformat', None)
    if callable(iso_method):
        return iso_method()

    return value

# ❌ 错误：直接 import（增加耦合）
import numpy as np
if isinstance(value, np.generic):   # 要求安装 numpy
    return value.item()
```

## WHEN（应用条件）
- ✅ 需要处理来自不同数据源的"外来"类型时
- ✅ 通用工具库/适配器（不应锁定特定依赖版本）
