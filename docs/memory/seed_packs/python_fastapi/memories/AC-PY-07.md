---
id: AC-PY-07
layer: PLATFORM
tier: warm
type: lesson
language: python
pack: python_fastapi
about_concepts: [alembic, database-migration, backward-compatibility, ddl]
cites_files: []
contradicts: []
created_at: "2026-04-27"
---

# Alembic 迁移必须向前兼容，DROP/RENAME 需分两阶段执行

## 教训（Lesson）

数据库迁移必须是向前兼容的（additive-only）。直接执行 `DROP COLUMN` 或 `RENAME COLUMN` 会导致正在运行的旧版本应用崩溃（零停机部署的必要条件）。

## 两阶段迁移模式

### 场景 1：重命名列（old_name → new_name）

```python
# ❌ 错误：一次性 RENAME，旧版 app 崩溃
def upgrade():
    op.alter_column("users", "username", new_column_name="user_name")

# ✅ 正确：分两次迁移

# 迁移 1（部署新版之前）：新增列，双写
def upgrade():
    op.add_column("users", sa.Column("user_name", sa.String(50)))
    op.execute("UPDATE users SET user_name = username WHERE user_name IS NULL")

# 迁移 2（确认旧版已无流量之后）：删除旧列
def upgrade():
    op.drop_column("users", "username")
```

### 场景 2：删除列

```python
# ✅ 正确：先让应用停止读写该列（代码版本 N+1），再迁移（代码版本 N+2）
# 迁移 N+2：
def upgrade():
    op.drop_column("users", "deprecated_field")
```

## 自动检测

在 CI 中添加 `alembic check` 确保所有 ORM 模型变更都有对应迁移：

```bash
# 检查是否有未生成迁移的模型变更
alembic check
```

## 参考

- 参考文章：[Zero-downtime migrations with Alembic](https://planetscale.com/blog/backward-compatible-migrations)
- Alembic 文档：[Operations Reference](https://alembic.sqlalchemy.org/en/latest/ops.html)
