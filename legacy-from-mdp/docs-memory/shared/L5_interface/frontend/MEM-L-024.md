---
id: MEM-L-024
layer: L5_interface
module: frontend
dimension: frontend
type: lesson
tier: hot
description: "Zustand Store 必须按业务域划分（ontologyStore/datalinkStore 等）；禁止 God Store；跨域数据用 selector"
tags: [zustand, store, god-store, domain-split, selector, frontend, state-management]
source_ep: EP-110
created_at: "2026-04-12"
last_accessed: "2026-04-12"
access_count: 3
related_memories: [MEM-L-023, MEM-L-025]
also_in: []
generalized: true
version: 1
---

# MEM-L-024 · Zustand Store 必须按业务域划分，禁止 God Store，跨域用 selector

## WHERE（在哪个模块/场景中）

`frontend/src/stores/` 目录结构设计，以及所有组件的状态管理实现。

## WHAT（发生了什么）

将所有状态放入单一 `useAppStore` (God Store) 时：
1. 任意子状态变化触发所有订阅组件重渲染（性能问题）
2. Store 文件超过 1000 行，难以维护和测试
3. 多人协同时频繁产生 Git merge 冲突（所有状态都在一个文件）
4. `useAppStore.getState()` 的快照测试包含无关状态，测试脆弱

## WHY（根本原因）

Zustand 的 selector 机制虽能优化渲染，但 God Store 在架构层面仍存在：
- 单文件职责过重（违反单一职责）
- 跨团队编辑同一文件产生冲突
- 测试隔离困难（需要 Mock 整个大 Store）

## HOW（解决方案）

```typescript
// ✅ 正确：按业务域划分 Store

// frontend/src/stores/ontology/objectTypeStore.ts
interface ObjectTypeState {
  list: ObjectType[];
  loading: boolean;
  fetchList: (params?: ListParams) => Promise<void>;
  create: (body: ObjectTypeCreate) => Promise<ObjectType>;
}

export const useObjectTypeStore = create<ObjectTypeState>((set, get) => ({
  list: [],
  loading: false,
  fetchList: async (params) => {
    set({ loading: true });
    const { data } = await objectTypeApi.list(params);
    set({ list: data, loading: false });
  },
  create: async (body) => {
    const { data } = await objectTypeApi.create(body);
    set((state) => ({ list: [data, ...state.list] }));
    return data;
  },
}));

// frontend/src/stores/governance/changeRequestStore.ts
export const useChangeRequestStore = create<ChangeRequestState>(...)

// frontend/src/stores/auth/authStore.ts
export const useAuthStore = create<AuthState>(...)

// ❌ 错误：God Store
// frontend/src/stores/appStore.ts (3000 行)
export const useAppStore = create((set) => ({
  objectTypes: [],           // 🚨 本体状态
  changeRequests: [],        // 🚨 治理状态
  currentUser: null,         // 🚨 认证状态
  connectors: [],            // 🚨 数据管道状态
  // ... 100+ 个字段全混在一起
}))
```

**跨域状态共享**（使用 selector，不引入新依赖）：
```typescript
// ✅ 跨域读取：在组件中组合多个 Store
const MyComponent = () => {
  const { currentUser } = useAuthStore();              // 认证 Store
  const { objectTypes } = useObjectTypeStore();         // 本体 Store
  const { quota } = useQuotaStore(s => s.quota);       // 治理 Store（selector）
  ...
};
```

**Store 目录规范**：
```
frontend/src/stores/
  ontology/
    objectTypeStore.ts    ← 对象类型状态
    linkTypeStore.ts      ← 链接类型状态
  data_pipeline/
    connectorStore.ts     ← 连接器状态
  governance/
    changeRequestStore.ts ← 变更请求状态
  auth/
    authStore.ts          ← 认证/用户状态
```

**必须同步**：新建 Store 后，在 `docs/architecture/frontend_page_map.md` 的 Store 总览区域添加条目。

## WHEN（触发条件）

- 新增页面需要状态管理时
- Store 文件超过 300 行时（拆分信号）
- 组件 re-render 过频繁时（先检查是否订阅了不必要的 Store 字段）
