# RBAC / Security Manifest

> 适用：权限控制 / ACL / 多租户隔离 / 审计日志 EP
> 补充加载：`@.cursor/rules/security-check.mdc`
> **维护者**：@gaobin · 最后更新：EP-102

---

## 红线约束（零容忍）

1. **RLS 强制过滤**：所有 DB 查询必须含 `WHERE tenant_id = ctx.tenant_id`；禁止跨租户直查。
2. **SecurityContext 首参**：Service 公开方法首参必须是 `ctx: SecurityContext`，不能用默认值绕过。
3. **敏感字段加密**：`docs/models` 中标注 `"sensitive": true` 的字段（password/secret/token）写入前必须调 `EncryptionService`，响应时必须脱敏。
4. **Audit 写操作必覆盖**：所有 CREATE / UPDATE / DELETE 操作必须调 `audit_service.log(ctx, action, target_id)`。
5. **CORS 生产限制**：禁止 `allow_origins=["*"]`，必须在 settings 中配置明确域名列表。

---

## 核心代码骨架

### 权限守卫标准模式
```python
from app.core.security import require_permission

@router.delete("/objects/{object_id}")
@require_permission("object:delete")
async def delete_object(
    object_id: UUID,
    ctx: SecurityContext = Depends(get_current_user),
):
    await object_service.delete(ctx, object_id)
    return ResponseSchema(data={"deleted": True})
```

### 多租户隔离查询
```python
# 正确：强制 tenant_id 过滤
statement = (
    select(ObjectInstance)
    .where(ObjectInstance.tenant_id == ctx.tenant_id)
    .where(ObjectInstance.id == object_id)
)

# 错误：IDOR 漏洞
statement = select(ObjectInstance).where(ObjectInstance.id == object_id)
```

---

## 必读文件

| 文件 | 说明 | 优先级 |
|:---|:---|:---|
| `docs/architecture/e2e_traceability.md §5 IAM` | 本域代码文件全层索引（API/Service/Model/Tests） | 变更前必须 |
| `.cursor/rules/security-check.mdc` | 安全审查 5 维度清单 | 必须 |
| `docs/specs/iam_spec.md` | IAM 规约（Role/Permission 定义） | 必须 |
| `.cursor/rules/rbac-patterns.mdc` | RBAC 代码模式 | 必须 |
| `docs/models/iam.json` | IAM 数据模型 | 涉及权限模型时 |

---

## 关键决策点

| 遇到 X | 选 A 而非 B | 理由 |
|:---|:---|:---|
| 对象级权限 vs 页面级权限 | ACL（对象级）+ 角色（页面级）组合 | 满足细粒度治理要求 |
| 敏感数据响应 | `response_model_exclude` + `ResponsePruner` | 比手动 del 更可靠，覆盖嵌套字段 |
| 变更全局资产 | 必须走 CR 审批流 | 治理规范，防止意外破坏全局依赖 |
