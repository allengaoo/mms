---
id: MEM-L-025
layer: L5_interface
module: frontend
dimension: frontend
type: lesson
tier: hot
description: "PermissionGate 控制按钮/字段级权限；只做页面路由守卫不够，敏感操作必须在 UI 层细粒度隐藏/禁用"
tags: [rbac, permission-gate, frontend, button-level, field-level, permission, component]
source_ep: EP-110
created_at: "2026-04-12"
last_accessed: "2026-04-12"
access_count: 5
related_memories: [MEM-L-023, AD-002]
also_in: [L1-D1]
generalized: false
related_to:
  - id: "MEM-L-023"
    reason: "PermissionGate 只用在 React 管理页面中，Amis 模块不适用"
  - id: "AD-002"
    reason: "前端 PermissionGate 是 RLS 在界面层的镜像，控制可见性而非数据安全"
cites_files:
  - "frontend/src/components/auth/"
  - "backend/app/core/rbac.py"
impacts: []
version: 1
---

# MEM-L-025 · `PermissionGate` 细粒度控制按钮/字段权限，禁止只做页面级路由守卫

## WHERE（在哪个模块/场景中）

`frontend/src/components/PermissionGate.tsx`，以及所有带操作按钮的管理页面。

## WHAT（发生了什么）

只在路由层做权限检查（`<RequireAuth permission="ont:object:view">`）时：
1. 普通成员进入对象类型列表页后，仍能看到"删除"、"编辑"按钮（只是点击后 403）
2. 误操作风险上升（用户以为自己有权限）
3. API 层遭受大量无效请求（前端未拦截 → 后端 403 → 日志噪音）
4. 表单中的敏感字段（如 `tenant_id`、加密字段）对无权限用户可见

## WHY（根本原因）

路由级权限守卫只解决"能否进入页面"，无法控制"页面内哪些操作/字段可见"。
平台 RBAC 设计明确要求细粒度到**操作（Action）**级别：
`ont:object:view`（查看）≠ `ont:object:edit`（编辑）≠ `ont:object:delete`（删除）

## HOW（解决方案）

```typescript
// ✅ 正确：PermissionGate 控制按钮和字段可见性
import { PermissionGate } from '@/components/PermissionGate';

const ObjectTypeListPage = () => {
  return (
    <ProTable
      columns={[
        { title: '名称', dataIndex: 'name' },
        {
          title: '操作',
          render: (_, record) => (
            <Space>
              {/* 查看按钮：所有有 view 权限的人可见 */}
              <PermissionGate permission="ont:object:view">
                <Button onClick={() => handleView(record.id)}>查看</Button>
              </PermissionGate>

              {/* 编辑按钮：需要 edit 权限 */}
              <PermissionGate permission="ont:object:edit">
                <Button type="primary" onClick={() => handleEdit(record.id)}>
                  编辑
                </Button>
              </PermissionGate>

              {/* 删除按钮：需要 delete 权限，且有确认弹窗 */}
              <PermissionGate permission="ont:object:delete">
                <Popconfirm onConfirm={() => handleDelete(record.id)}>
                  <Button danger>删除</Button>
                </Popconfirm>
              </PermissionGate>
            </Space>
          ),
        },
      ]}
    />
  );
};

// ✅ 表单字段权限控制（敏感字段）
const ObjectTypeForm = () => (
  <Form>
    <Form.Item name="name" label="名称">
      <Input />
    </Form.Item>
    {/* 高级配置只对管理员可见 */}
    <PermissionGate permission="ont:object:admin">
      <Form.Item name="primary_key" label="主键字段（高级）">
        <Input />
      </Form.Item>
    </PermissionGate>
  </Form>
);

// ❌ 错误：只在路由层控制，页面内无细粒度权限
// routes.tsx
<Route
  path="/ontology/object-types"
  element={<RequireAuth perm="ont:object:view"><ObjectTypeListPage /></RequireAuth>}
/>
// 所有进入此页面的用户都能看到删除按钮 🚨
```

**PermissionGate 实现原理**：
```typescript
// frontend/src/components/PermissionGate.tsx
export const PermissionGate: React.FC<{
  permission: string;
  fallback?: React.ReactNode;
  children: React.ReactNode;
}> = ({ permission, fallback = null, children }) => {
  const { permissions } = useAuthStore();  // 从 authStore 读取当前用户权限列表
  return permissions.includes(permission) ? <>{children}</> : <>{fallback}</>;
};
```

**权限 Key 格式**（来自 `rbac.py::PERMISSION_REGISTRY`）：
```
{domain}:{resource}:{action}
  domain:   ont | pipe | gov | sys
  resource: object | link | action | connector | job | quota | cr
  action:   view | edit | delete | admin | execute
```

## WHEN（触发条件）

- 新增任何带操作按钮的管理页面
- Code Review 发现操作按钮无 PermissionGate 包裹
- 用户反馈"看到了不该看到的按钮"
