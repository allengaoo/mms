---
id: MEM-L-027
layer: L5_interface
module: testing
dimension: D10
type: lesson
tier: hot
description: "前端测试用 MSW 拦截 API 请求（不做真实 HTTP）；renderWithProviders 注入 Store 和 Router 上下文"
tags: [frontend, vitest, msw, mock-service-worker, api-mock, renderWithProviders, testing]
source_ep: EP-110
created_at: "2026-04-12"
last_accessed: "2026-04-12"
access_count: 3
related_memories: [MEM-L-026, MEM-L-023]
also_in: []
generalized: true
version: 1
---

# MEM-L-027 · 前端用 MSW 拦截 API 请求，`renderWithProviders` 注入 Store 和 Router

## WHERE（在哪个模块/场景中）

`frontend/src/test/` — 测试工具函数和 MSW handlers。
所有 `frontend/src/pages/**/*.test.tsx` 和 `*.test.ts` 组件测试。

## WHAT（发生了什么）

直接 Mock Axios 模块（`vi.mock('axios')`）时：
1. Mock 粒度过粗，无法模拟特定 URL 的不同响应（如第一次 200，第二次 500）
2. Mock 不感知 HTTP Method（GET/POST 共用同一 Mock），导致假阳性
3. MSW 被遗漏时，真实 API 请求在 jsdom 中失败，产生网络错误噪音
4. 组件依赖 Zustand Store / React Router 时，直接 render 缺少 Provider，抛出上下文错误

## WHY（根本原因）

MSW 在网络层拦截请求，对组件代码完全透明（不需要修改组件代码来支持测试）。
`renderWithProviders` 统一注入必要的 Provider（QueryClient、Router、Store），
避免每个测试文件重复编写 Provider 包装。

## HOW（解决方案）

```typescript
// ✅ 正确：MSW + renderWithProviders

// frontend/src/test/mocks/handlers/ontology.ts
import { http, HttpResponse } from 'msw';

export const ontologyHandlers = [
  http.get('/api/v1/object-types', () => {
    return HttpResponse.json({
      code: 200,
      data: [{ id: 'uuid-1', name: 'Company', displayName: '企业' }],
      meta: { total: 1, page: 1, page_size: 20 },
    });
  }),

  http.post('/api/v1/object-types', async ({ request }) => {
    const body = await request.json();
    return HttpResponse.json({
      code: 201,
      data: { id: 'new-uuid', ...body },
    }, { status: 201 });
  }),

  // 模拟错误场景
  http.delete('/api/v1/object-types/:id', ({ params }) => {
    if (params.id === 'protected-id') {
      return HttpResponse.json(
        { code: 409, message: '对象类型被引用，无法删除' },
        { status: 409 }
      );
    }
    return HttpResponse.json({ code: 200, data: null });
  }),
];

// frontend/src/test/utils.tsx
import { render } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

export function renderWithProviders(
  ui: React.ReactElement,
  options?: { initialEntries?: string[] }
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },  // 测试中不重试
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={options?.initialEntries ?? ['/']}>
        {ui}
      </MemoryRouter>
    </QueryClientProvider>
  );
}

// frontend/src/pages/ontology/ObjectTypeListPage.test.tsx
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { server } from '@/test/mocks/server';  // MSW server
import { http, HttpResponse } from 'msw';
import { renderWithProviders } from '@/test/utils';
import ObjectTypeListPage from './ObjectTypeListPage';

describe('ObjectTypeListPage', () => {
  test('应该显示对象类型列表', async () => {
    renderWithProviders(<ObjectTypeListPage />);
    await waitFor(() => {
      expect(screen.getByText('企业')).toBeInTheDocument();
    });
  });

  test('删除受保护的对象类型时应显示错误消息', async () => {
    // 在单个测试中覆盖 handler
    server.use(
      http.delete('/api/v1/object-types/protected-id', () =>
        HttpResponse.json({ code: 409, message: '对象类型被引用，无法删除' }, { status: 409 })
      )
    );
    renderWithProviders(<ObjectTypeListPage />);
    await userEvent.click(screen.getByRole('button', { name: '删除' }));
    await waitFor(() => {
      expect(screen.getByText('对象类型被引用，无法删除')).toBeInTheDocument();
    });
  });
});

// ❌ 错误：直接 Mock Axios（粒度粗，侵入性强）
vi.mock('axios', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: { code: 200, data: [] } }),
    // 🚨 POST/DELETE/PATCH 全部返回同一个 Mock，无法区分 URL
  }
}));
```

**MSW 初始化**（`frontend/src/test/mocks/server.ts`）：
```typescript
import { setupServer } from 'msw/node';
import { ontologyHandlers } from './handlers/ontology';
import { pipelineHandlers } from './handlers/pipeline';

export const server = setupServer(...ontologyHandlers, ...pipelineHandlers);

// vitest.setup.ts
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
```

## WHEN（触发条件）

- 新增前端页面时（同步编写组件测试）
- 测试在 CI 中偶发性网络错误时（检查 MSW Handler 是否覆盖全部 API 调用）
- 组件测试报 "useStore requires a QueryClient Provider" 错误时（用 renderWithProviders）
