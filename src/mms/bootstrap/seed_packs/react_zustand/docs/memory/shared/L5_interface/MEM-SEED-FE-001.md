---
id: MEM-SEED-FE-001
layer: L5_interface
module: frontend
type: pattern
tier: hot
tags: [react, zustand, axios, state-management, api-call, seed]
source_ep: EP-130
created_at: 2026-04-18
version: 1
generalized: true
---

# MEM-SEED-FE-001: React + Zustand 数据获取模式

## 模式

前端 API 调用必须封装在 `src/services/*.ts` 中，Store 只调用 service 函数，组件只调用 Store action。

```
组件 → Store Action → service.ts → Axios 实例 → 后端 API
```

## 禁止直接在组件中调用 Axios

```typescript
// ❌ 错误：组件中直接调用 axios
const MyComponent = () => {
  const [data, setData] = useState([]);
  useEffect(() => {
    axios.get("/api/v1/items").then(res => setData(res.data)); // ❌
  }, []);
};

// ✅ 正确：通过 service → store
const useItemStore = create<ItemState>((set) => ({
  items: [],
  fetchItems: async () => {
    const res = await itemService.list();  // service 封装
    set({ items: res.data });
  },
}));
```

## 错误处理规范

Axios 拦截器统一处理 401（跳转登录）和 403（无权限提示），组件不需要单独处理这两种错误。
