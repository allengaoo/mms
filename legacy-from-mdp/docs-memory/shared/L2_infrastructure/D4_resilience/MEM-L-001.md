---

id: MEM-L-001
layer: L2_infrastructure
module: D4_resilience
dimension: D4_resilience
type: lesson
tier: hot
description: "Python or 运算符对 0/False/'' 短路；数值型字段默认值必须用 if x is None 判断，而非 x or default"
tags: [python, or, default-value, numeric, none-check, bug]
source_ep: EP-098
created_at: "2026-02-24"
version: 1
last_accessed: "2026-04-11"
access_count: 18
related_memories: [MEM-L-002]
also_in: [L4_application/workers]
generalized: true
related_to:

- id: "MEM-L-002"
reason: "Avro 序列化中 Decimal/int 字段误用 or 默认值是同类根因"
- id: "AD-005"
reason: "事务代码中数值型字段（如 retry_count）常见同样错误"
cites_files:
- "backend/app/workers/"
impacts:
- "MEM-L-016"

---

# MEM-L-001 · Python `or` 不能用于数值型默认值

## WHERE（发生层/模块）

Layer 2 / Layer 4 — 任何 Python 数值字段默认值赋值处

## WHAT（问题类型）

Dimension 4: 弹性与事务 — 静默数据错误（Python 语言陷阱）

## WHY（根因与影响）

**触发条件**：`rows_affected = job.rows_affected or 0`
**症状**：当 `job.rows_affected = 0`（合法值）时，`0 or 5 = 5`（旧值覆盖新值），导致 `rows_affected` 显示不正确
**根因**：Python `or` 是布尔短路，不是 None 检查。`0` 是 falsy，会被 `or` 跳过

## HOW（正确写法）

```python
# ✅ 正确：明确 None 检查
rows_affected = job.rows_affected if job.rows_affected is not None else 0

# ✅ Python 3.8+ walrus / 简洁写法
rows_affected = 0 if job.rows_affected is None else job.rows_affected

# ❌ 错误：or 短路
rows_affected = job.rows_affected or 0    # 当值为 0 时静默错误
count = data.get('count') or 10           # 当 count=0 时错误
```

## WHEN（应用条件）

- ✅ 所有数值型字段（int/float/Decimal）的默认值赋值
- ✅ 所有列表/字典字段的默认值赋值（空列表 `[]` 也是 falsy）
- ✅ DB 查询结果字段（可能为 0 的计数器）

## 禁止项

- ❌ 对数值类型使用 `x or default`
- ❌ 对列表类型使用 `x or []`（空列表也是 falsy）

