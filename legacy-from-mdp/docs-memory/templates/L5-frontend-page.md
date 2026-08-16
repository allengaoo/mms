# 模版：L5 接口层 · 前端页面/组件（小模型优化版）
# 适用：新增管理页面 / ProTable / DrawerForm / Zustand Store
# Token 预算：≤3K

---

## [TASK] 任务描述
**目标**：{组件名 + 功能说明（一句话）}
**层级坐标**：Layer 5 (interface/frontend) × React 18 + Ant Design ProComponents
**涉及文件**：
- `frontend/src/pages/{module}/{ComponentName}/index.tsx`
- `frontend/src/services/{module}Service.ts`（API 封装）
- `frontend/src/store/{module}Store.ts`（如需全局状态）

---

## [MEMORY] 本次必须遵守的记忆（4条核心）

**前端架构红线（MEM-L-023）**：
- ✅ 管理页面必须用 React + ProTable / DrawerForm / ProDescriptions（非 JSON 配置）
- ✅ Amis 仅用于 Chat2App 模块（否则出现双 Header + 无法单元测试）
- ✅ 数据获取使用 React Query（useQuery/useMutation），禁止 useEffect+setState
- ✅ API 调用封装在 `src/services/*.ts`（禁止组件直接调 Axios）

**Zustand Store 规范（MEM-L-024）**：
- ✅ Store 按业务域划分（`stores/ontology/`、`stores/governance/` 等），禁止 God Store
- ✅ 跨域状态读取用 selector（不引入新依赖）
- 新增 Store 后必须在 `frontend_page_map.md` Store 总览区域添加条目

**权限细粒度控制（MEM-L-025）**：
- ✅ 操作按钮/敏感字段必须用 `<PermissionGate permission="ont:object:edit">` 包裹
- ❌ 禁止只做路由级权限守卫（页面内按钮对无权限用户仍可见是常见漏洞）

**样式规范（style_guide.md）**：
- 顶部导航：Deep Blue `#2B55D5`（通过 ConfigProvider 注入，非硬编码）
- 侧边栏：Light Gray `#F7F8FA`

---

## [STATE] 系统状态
- EP: {当前EP编号} | 前端镜像: {version}
- 所需权限：`{domain}:{resource}:{action}`
- 路由路径：`/app/{module}/{page}`

---

## [CONSTRAINTS] 本层必守红线（7条）
- ✅ 严格 TypeScript（禁止 `any`，用具体类型或 `unknown`）
- ✅ 每个 API 调用必须有对应 MSW handler（`src/test/mocks/handlers/{module}.ts`）
- ✅ 组件测试用 `renderWithProviders`（含 QueryClient + MemoryRouter）
- ✅ 新增路由必须更新 `frontend_page_map.md`（含渲染技术、Store、权限列）
- ✅ Zustand Store 按业务域拆分，禁止单一 God Store
- ✅ 每个操作按钮/表单敏感字段必须用 `PermissionGate` 包裹
- ❌ 禁止：Amis JSON 用于管理页面（Amis 仅用于 Chat2App 模块）

---

## [EXAMPLE] 参考模式（来自 EP-103）
```tsx
// ✅ ProTable + useQuery 标准写法
const SyncJobList: React.FC = () => {
  const { data, isLoading } = useQuery({
    queryKey: ['sync-jobs'],
    queryFn: () => syncJobService.list(),
  });

  return (
    <ProTable<SyncJob>
      rowKey="id"
      loading={isLoading}
      dataSource={data?.data ?? []}
      columns={columns}
      toolBarRender={() => [<CreateButton key="create" />]}
    />
  );
};
```

---

## [OUTPUT] 输出格式
1. `pages/{module}/{ComponentName}/index.tsx` — 完整组件
2. `services/{module}Service.ts` — API 方法（如新增）
3. `test/mocks/handlers/{module}.ts` — MSW handler
4. `{ComponentName}.test.tsx` — Vitest 测试（renderWithProviders）
