---
id: MEM-L-007
layer: L2_infrastructure
module: storage
dimension: D6_bigdata
type: lesson
tier: hot
description: "Iceberg 写入后必须显式调用 table.commit()；元数据和数据文件分离，不 commit 则数据对查询不可见"
tags: [iceberg, pyiceberg, commit, transaction, minio, s3]
source_ep: EP-096
created_at: "2026-02-20"
version: 1
last_accessed: "2026-04-11"
access_count: 7
related_memories: [MEM-L-010]
also_in: []
generalized: true
---

# MEM-L-007 · Iceberg 写入需要显式 commit

## WHERE（发生层/模块）
Layer 2 基础设施层 → Storage 模块 → PyIceberg 写入适配器

## WHAT（问题类型）
Dimension 6: 大数据与事件驱动 — Iceberg 写入后数据不可见

## WHY（根因与影响）
**触发条件**：PyIceberg 写入数据后未调用 commit
**症状**：数据已写入 S3/MinIO 但查询返回空（元数据未更新）
**根因**：PyIceberg 写入是事务性的；数据文件（Parquet）和元数据文件（manifest）是分离的；未 commit 则元数据不指向新数据文件

## HOW（正确写法）
```python
# ✅ 显式 commit
table = catalog.load_table("tenant.logistics_carriers")
with table.transaction() as txn:
    txn.append(pa_table)                    # 写数据文件
    # 事务上下文退出时自动 commit_transaction()

# 或显式调用
txn = table.transaction()
txn.append(pa_table)
txn.commit_transaction()                    # 必须显式 commit！

# ❌ 错误：直接 append 后不 commit
table.append(pa_table)                      # 某些版本不自动提交元数据
```

## WHEN（应用条件）
- ✅ 所有 LakeWriter Worker 中的 Iceberg 写入
- ✅ 任何直接操作 PyIceberg Table 的代码
