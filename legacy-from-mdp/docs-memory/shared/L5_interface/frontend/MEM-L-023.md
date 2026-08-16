---
id: MEM-L-023
layer: L5_interface
module: frontend
dimension: frontend
type: decision
tier: hot
description: "管理页面必须是 TypeScript React 组件（Ant Design 5）；Amis JSON 只允许用于 Chat2App 模块"
tags: [frontend, react, amis, procomponents, management-page, chat2app, rendering]
source_ep: EP-110
created_at: "2026-04-12"
last_accessed: "2026-04-12"
access_count: 7
related_memories: [MEM-L-024, MEM-L-025, AD-008]
also_in: []
generalized: false
related_to:
  - id: "MEM-L-025"
    reason: "Management 页面选 React 组件后，需配套使用 PermissionGate 进行权限控制"
  - id: "MEM-L-020"
    reason: "React 组件调用 API 时，前端需解包信封格式（unwrap data 字段）"
cites_files:
  - "frontend/src/layouts/MainLayout.tsx"
  - "frontend/src/pages/"
  - "frontend/src/config/navigation.ts"
impacts:
  - "MEM-L-025"
version: 1
---

# MEM-L-023 · 管理页面用 React + ProComponents，Amis 只用于 Chat2App 模块

## WHERE（在哪个模块/场景中）

`frontend/src/pages/` 下所有页面组件的技术选型决策。
`docs/architecture/frontend_page_map.md`（路由→渲染技术映射表）。

## WHAT（发生了什么）

混用 Amis JSON 配置和 React 组件导致：
1. 管理页面用 Amis 配置后，TypeScript 类型检查完全失效（Amis 是 any 类型 JSON）
2. 复杂交互（如本体画布 Canvas、拖拽排序）在 Amis 中无法实现，后期难以重构
3. 前端 Zustand Store 与 Amis 状态管理冲突（两套状态系统）
4. 单元测试无法覆盖 Amis JSON 配置（testing-library 无法渲染纯 JSON Schema）
5. Amis 的 Header 与平台 Deep Blue 导航栏样式冲突（出现双层 Header）

## WHY（根本原因）

平台的技术分工：
- **React + ProComponents**：管理类页面（CRUD、配置、监控）— 严格 TypeScript，可测试
- **Baidu Amis**：Chat2App 模块的动态低代码渲染 — 运行时 JSON，面向业务用户配置

两者定位不同，混用会导致维护成本激增。

## HOW（解决方案）

```typescript
// ✅ 正确：管理页面用 React + ProComponents
// frontend/src/pages/ontology/ObjectTypeListPage.tsx

import { ProTable, ProColumns } from '@ant-design/pro-components';
import { useObjectTypeStore } from '@/stores/ontology/objectTypeStore';
import { PermissionGate } from '@/components/PermissionGate';

const ObjectTypeListPage: React.FC = () => {
  const { list, fetchList, loading } = useObjectTypeStore();

  const columns: ProColumns<ObjectType>[] = [
    { title: '名称', dataIndex: 'name' },
    { title: '显示名', dataIndex: 'displayName' },
    {
      title: '操作',
      render: (_, record) => (
        <PermissionGate permission="ont:object:edit">
          <EditButton onClick={() => handleEdit(record.id)} />
        </PermissionGate>
      ),
    },
  ];

  return <ProTable columns={columns} dataSource={list} loading={loading} />;
};

// ❌ 错误：管理页面用 Amis JSON 配置
// frontend/src/pages/ontology/object-type-list.amis.json
{
  "type": "page",
  "body": { "type": "crud", "api": "/api/v1/object-types" }
  // 🚨 无 TypeScript、无权限控制、无法单元测试
}
```

**判断依据**（每次新建页面时）：

| 场景 | 使用技术 |
|:---|:---|
| CRUD 管理页（用户、角色、配置） | React + ProComponents |
| 数据可视化（图表、大盘） | React + Ant Design Charts |
| 本体画布（拖拽、连线） | React + 自定义 Canvas |
| Chat2App 动态应用渲染 | Baidu Amis |
| 需要 TypeScript 类型安全的页面 | React（任何情况） |

**必须同步更新**：新增页面后，在 `docs/architecture/frontend_page_map.md` 添加条目，注明渲染技术。

## WHEN（触发条件）

- 讨论新页面技术选型时
- 发现有人在管理页面引入 Amis 依赖时
- Amis 双 Header 问题（在非 Chat2App 页面使用 Amis 的症状）
