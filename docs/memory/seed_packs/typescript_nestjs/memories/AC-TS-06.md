---
id: AC-TS-06
layer: APP
tier: warm
type: lesson
language: typescript
pack: typescript_nestjs
about_concepts: [zustand, state-management, store-splitting, react]
cites_files: []
created_at: "2026-04-27"
---

# Zustand Store 必须按领域拆分，禁止超过 15 个字段的大 Store

## 教训（Lesson）

将所有状态集中在一个 Zustand Store 中（"God Store"）会导致任何状态变更都触发订阅了其他字段的组件重渲染，即使这些组件并不关心变更的字段。

```typescript
// ❌ God Store 反模式：30+ 字段混在一起
const useStore = create<AppState>((set) => ({
  // 用户状态
  user: null,
  token: null,
  isAuthenticated: false,
  // 订单状态
  orders: [],
  currentOrder: null,
  orderFilters: {},
  // UI 状态
  sidebarOpen: false,
  theme: 'light',
  notifications: [],
  // 购物车状态
  cartItems: [],
  cartTotal: 0,
  // ... 30 多个字段
}));
// 问题：修改 sidebarOpen 会导致所有订阅了 useStore 的组件重渲染！
```

```typescript
// ✅ 正确：按领域拆分 Store
// src/features/auth/store/useAuthStore.ts
const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: null,
  isAuthenticated: false,
  login: (token) => set({ token, isAuthenticated: true }),
  logout: () => set({ user: null, token: null, isAuthenticated: false }),
}));

// src/features/orders/store/useOrderStore.ts
const useOrderStore = create<OrderState>()(
  devtools(
    persist(
      (set) => ({
        orders: [],
        currentOrder: null,
        setOrders: (orders) => set({ orders }),
      }),
      { name: 'order-storage' }
    )
  )
);

// src/features/ui/store/useUIStore.ts
const useUIStore = create<UIState>((set) => ({
  sidebarOpen: false,
  theme: 'light' as Theme,
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
}));
```

## 参考

- Zustand 文档：[Slice Pattern](https://zustand.docs.pmnd.rs/guides/slices-pattern)
- bulletproof-react：stores/ 目录结构
