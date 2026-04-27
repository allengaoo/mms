---
id: AC-TS-08
layer: APP
tier: warm
type: anti_pattern
language: typescript
pack: typescript_nestjs
about_concepts: [react, useEffect, async, cleanup, memory-leak]
cites_files: []
created_at: "2026-04-27"
---

# React useEffect 禁止直接传入 async 函数

## 反模式（Anti-Pattern）

`useEffect` 的回调函数**不能**是 `async` 函数。原因是 `async` 函数返回 Promise，而 `useEffect` 期望回调返回 `void` 或清理函数（cleanup function）。直接传入 `async` 函数会导致无法执行 cleanup，造成内存泄漏。

```typescript
// ❌ 错误：直接传入 async 函数
useEffect(async () => {   // ❌ async useEffect！
  const data = await fetchData();
  setData(data);
  // 返回的是 Promise，不是 cleanup 函数！
  // 组件卸载时无法取消 fetchData，可能在卸载后 setState 导致内存泄漏
}, []);
```

```typescript
// ✅ 正确方案 1：在 useEffect 内部定义并调用 async 函数
useEffect(() => {
  let cancelled = false;   // 取消标志

  const fetchData = async () => {
    try {
      const result = await api.getUser(userId);
      if (!cancelled) {    // 组件未卸载时才更新状态
        setUser(result);
      }
    } catch (err) {
      if (!cancelled) setError(err);
    }
  };

  fetchData();

  return () => {           // ✅ cleanup 函数
    cancelled = true;
  };
}, [userId]);

// ✅ 正确方案 2（推荐）：使用 TanStack Query 替代 useEffect 数据获取
// 完全不需要 useEffect 处理数据请求！
const { data: user, error } = useQuery({
  queryKey: ['users', userId],
  queryFn: () => api.getUser(userId),
});

// ✅ 正确方案 3：使用 AbortController 取消 fetch
useEffect(() => {
  const controller = new AbortController();

  fetch(`/api/users/${userId}`, { signal: controller.signal })
    .then(res => res.json())
    .then(setUser)
    .catch(err => { if (err.name !== 'AbortError') setError(err); });

  return () => controller.abort();   // ✅ 组件卸载时取消请求
}, [userId]);
```

## 参考

- React 文档：[You Might Not Need an Effect](https://react.dev/learn/you-might-not-need-an-effect)
- React 文档：[useEffect cleanup](https://react.dev/reference/react/useEffect#parameters)
