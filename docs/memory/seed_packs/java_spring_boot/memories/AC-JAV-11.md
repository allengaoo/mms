---
id: AC-JAV-11
layer: PLATFORM
tier: warm
type: lesson
language: java
pack: java_spring_boot
about_concepts: [mysql, enum, ddl, schema-migration, backward-compatibility]
cites_files: []
contradicts: []
created_at: "2026-04-27"
---

# MySQL ENUM 类型新增值必须分两次部署

## 教训（Lesson）

MySQL ENUM 字段新增枚举值时，如果先更新应用代码（向 DB 写入新枚举值），会导致旧版本应用在读取时报 `com.mysql.cj.exceptions.DataTruncation` 异常（旧版不认识新枚举值）。

## 两阶段部署流程

```sql
-- ❌ 错误：一次性迁移，旧版应用报错
-- 步骤 1：先部署新 SQL（新增枚举值）
ALTER TABLE oms_order MODIFY COLUMN status ENUM('0','1','2','3','4') NOT NULL;
-- 步骤 2：部署新代码（写入状态 '4'）
-- → 新旧版本同时运行期间，旧版读到 '4' 会崩溃！
```

```sql
-- ✅ 正确：先迁移 DB，再部署代码
-- 步骤 1：先执行 SQL 迁移（此时旧版应用不会写入 '4'，安全）
ALTER TABLE oms_order MODIFY COLUMN status ENUM('0','1','2','3','4') NOT NULL;

-- 步骤 2：确认 SQL 执行完毕后，再部署新版代码
-- → 新版代码才会写入状态 '4'
```

## 推荐替代方案：用 TINYINT 替代 ENUM

```sql
-- 避免 ENUM 类型的维护复杂性，用 TINYINT + 应用层枚举映射
ALTER TABLE oms_order ADD COLUMN new_status TINYINT NOT NULL DEFAULT 0 COMMENT '0:待付款 1:待发货 2:已发货 3:已完成 4:已关闭';
```

这样新增状态值只需更新应用层枚举，无需 DDL 变更。

## 参考

- MySQL 文档：[ENUM 类型](https://dev.mysql.com/doc/refman/8.0/en/enum.html)
