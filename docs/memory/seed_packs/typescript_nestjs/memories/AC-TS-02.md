---
id: AC-TS-02
layer: APP
tier: hot
type: arch_constraint
language: typescript
pack: typescript_nestjs
about_concepts: [react, feature-sliced-design, custom-hook, data-fetching, separation-of-concerns]
cites_files: []
created_at: "2026-04-27"
---

# React Page Component 禁止直接 fetch/axios，必须封装在 features/ Hook 中

## 约束（Constraint）

前端页面组件（Page Component）严禁直接在组件体内调用 `fetch` 或 `axios`。所有网络请求必须封装在 `features/xxx/api/` 目录下的自定义 Hook 中（`useQuery`/`useMutation`/SWR/TanStack Query）。

```tsx
// ❌ 错误：Page Component 直接调用 HTTP
// src/pages/users/UserDetailPage.tsx
export function UserDetailPage({ userId }: { userId: string }) {
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    fetch(`/api/users/${userId}`)   // ❌ Page 层直接 fetch！
      .then(res => res.json())
      .then(setUser);
  }, [userId]);

  return <div>{user?.name}</div>;
}
```

```tsx
// ✅ 正确：Feature-Sliced Design

// src/features/users/api/useUser.ts
export function useUser(userId: string) {
  return useQuery({
    queryKey: ['users', userId],
    queryFn: () => apiClient.get<User>(`/users/${userId}`).then(r => r.data),
  });
}

// src/features/users/api/useUpdateUser.ts
export function useUpdateUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: UpdateUserDto) =>
      apiClient.put<User>(`/users/${data.id}`, data).then(r => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['users'] }),
  });
}

// src/pages/users/UserDetailPage.tsx
export function UserDetailPage({ userId }: { userId: string }) {
  const { data: user, isLoading } = useUser(userId);   // ✅ 使用 Hook
  if (isLoading) return <Spinner />;
  return <UserProfile user={user} />;
}
```

## 目录结构规范

```
src/
├── features/
│   ├── users/
│   │   ├── api/            ← 所有 HTTP 请求（Hook 封装）
│   │   │   ├── useUser.ts
│   │   │   ├── useUsers.ts
│   │   │   └── useUpdateUser.ts
│   │   ├── components/     ← Users 特征专用组件
│   │   └── index.ts        ← 公开 API
│   └── orders/
│       └── api/
├── pages/                  ← 仅负责路由组合，禁止直接 fetch
└── shared/                 ← 跨特征共用（UI 组件、工具函数）
```

## 参考

- bulletproof-react：https://github.com/alan2207/bulletproof-react
- Feature-Sliced Design：https://feature-sliced.design/
