---
id: AC-TS-05
layer: APP
tier: warm
type: arch_constraint
language: typescript
pack: typescript_nestjs
about_concepts: [react, feature-sliced-design, component-organization, architecture]
cites_files: []
created_at: "2026-04-27"
---

# React 组件必须在 features/ 目录，pages/ 仅负责路由组合

## 约束（Constraint）

- `pages/`：只包含路由级别的组合组件，**禁止放业务组件、禁止直接 fetch**
- `features/xxx/`：业务功能模块，包含该功能的组件、Hook、API、状态

```
src/
├── pages/
│   ├── Dashboard.tsx      ← ✅ 只组合 features/ 中的组件
│   ├── UserDetail.tsx     ← ✅ 只组合 features/ 中的组件
│   └── Orders.tsx
│
├── features/
│   ├── dashboard/
│   │   ├── components/    ← ✅ Dashboard 专用组件
│   │   ├── api/           ← ✅ Dashboard 的数据请求
│   │   └── index.ts       ← ✅ 公开 API（只导出允许跨功能使用的内容）
│   ├── users/
│   │   ├── components/
│   │   │   ├── UserCard.tsx
│   │   │   └── UserForm.tsx
│   │   ├── api/
│   │   │   └── useUser.ts
│   │   └── index.ts
│   └── orders/
└── shared/
    ├── components/        ← ✅ 通用 UI（Button、Modal 等）
    └── utils/             ← ✅ 纯工具函数
```

```tsx
// ✅ pages/ 的正确写法
// src/pages/UserDetail.tsx
import { UserProfile, UserOrders } from '@/features/users';
import { OrderHistory } from '@/features/orders';

export function UserDetailPage() {
  const { userId } = useParams();
  return (
    <Layout>
      <UserProfile userId={userId} />    {/* features/ 中的组件 */}
      <UserOrders userId={userId} />
      <OrderHistory userId={userId} />
    </Layout>
  );
}
```

## 为何不直接在 pages/ 中写业务组件？

`pages/` 与路由 1:1 对应，业务需求变化时路由结构频繁调整。将业务组件放在 `features/` 中可以在路由重组时**零成本迁移**（组件不受影响）。

## 参考

- bulletproof-react：https://github.com/alan2207/bulletproof-react/tree/master/src
