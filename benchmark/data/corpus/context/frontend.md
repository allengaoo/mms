# Frontend Manifest

> 适用：新增页面 / 组件 / 路由 / Zustand Store EP
> 补充加载：`@docs/architecture/frontend_page_map.md`
> **维护者**：@gaobin · 最后更新：EP-102

---

## 红线约束（此域最易出错）

1. **ProComponents 强制**：列表页用 `ProTable`，表单用 `ModalForm` / `DrawerForm`；禁止用原始 `Table` / `Form`。
2. **禁止 `any` 类型**：TypeScript 严格模式，用具体类型或 `unknown`，禁止 `any`。
3. **API 调用封装**：所有 Axios 调用必须在 `src/services/*.ts` 中；禁止在组件里直接调用 `axios`。
4. **状态模式**：全局状态用 Zustand；服务端数据用 TanStack Query；禁止 `useEffect` + `setState` 获取数据。
5. **颜色不硬编码**：颜色必须通过 `ConfigProvider` token 或 CSS Variables；Header 背景 `#2B55D5`（Deep Blue），Sidebar 背景 `#F7F8FA`（Light Gray）。

---

## 核心代码骨架

### ProTable 标准结构
```tsx
import { ProTable } from '@ant-design/pro-components';

const MyListPage: React.FC = () => {
  return (
    <ProTable<MyRecord>
      request={async (params) => {
        const res = await myService.list(params);
        return { data: res.data.items, success: true, total: res.data.total };
      }}
      columns={columns}
      rowKey="id"
    />
  );
};
```

### Zustand Store 标准结构
```ts
// src/stores/useMyStore.ts
interface MyState {
  items: MyItem[];
  setItems: (items: MyItem[]) => void;
}

export const useMyStore = create<MyState>((set) => ({
  items: [],
  setItems: (items) => set({ items }),
}));
```

---

## 必读文件

| 文件 | 说明 | 优先级 |
|:---|:---|:---|
| `docs/architecture/frontend_page_map.md` | 页面→路由→Store→权限 映射 | 必须 |
| `docs/ui/style_guide.md` | 色彩与布局规范（CEC Blue Token） | 必须 |
| `.cursor/rules/frontend-gen.mdc` | 完整前端生成规范 | 必须 |
| `docs/architecture/e2e_traceability.md` | 新增页面时检查影响范围 | 新增路由时必须 |
| `frontend/src/test/utils.tsx` | `renderWithProviders` 测试工具 | 写测试时必须 |

---

## 关键决策点

| 遇到 X | 选 A 而非 B | 理由 |
|:---|:---|:---|
| 列表 + 搜索 + 分页 | `ProTable` | 内置分页/排序/搜索，开箱即用 |
| 表单（新建/编辑） | `ModalForm` / `DrawerForm` | 避免整页跳转，UX 更流畅 |
| 服务端数据（随时变化） | TanStack Query `useQuery` | 自动缓存 + 失效重新请求 |
| 跨页共享状态（用户信息/租户） | Zustand Store | 比 Context 性能更好，无 re-render 风险 |
| 新增页面后 | 同步更新 `frontend_page_map.md` | 强制要求，见 `global-constraints.mdc` §16 |
