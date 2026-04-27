---
id: AC-TS-10
layer: PLATFORM
tier: warm
type: lesson
language: typescript
pack: typescript_nestjs
about_concepts: [openapi, codegen, type-safety, frontend-backend-contract, typescript]
cites_files: []
created_at: "2026-04-27"
---

# OpenAPI codegen 必须在 CI 中验证前后端类型一致

## 教训（Lesson）

前后端分离项目中，手写前端 API 接口类型（TypeScript interface）会与后端实际接口长期漂移，导致编译时看起来正确但运行时报错。必须从 OpenAPI spec 自动生成类型定义，并在 CI 中验证一致性。

```typescript
// ❌ 错误：手写前端 API 类型（与后端逐渐漂移）
// src/types/api.ts
export interface User {
  id: number;
  name: string;
  email: string;
  // 3个月后后端加了 avatar 字段，前端不知道
  // 6个月后后端把 name 改成了 fullName，前端还在用 name
}
```

```bash
# ✅ 正确：从 OpenAPI spec 自动生成类型

# 安装 openapi-typescript
npm install -D openapi-typescript

# package.json scripts
{
  "scripts": {
    "gen:api": "openapi-typescript http://localhost:3000/api-json -o src/types/api-generated.ts",
    "check:api": "openapi-typescript http://localhost:3000/api-json -o /tmp/api-check.ts && diff src/types/api-generated.ts /tmp/api-check.ts"
  }
}
```

```typescript
// 使用生成的类型（src/types/api-generated.ts 由 codegen 自动维护）
import type { components } from '@/types/api-generated';

type User = components['schemas']['UserResponse'];   // ✅ 永远与后端同步

// 配合 openapi-fetch（类型安全的 fetch 客户端）
import createClient from 'openapi-fetch';
const client = createClient<paths>({ baseUrl: 'http://localhost:3000' });

const { data, error } = await client.GET('/users/{id}', {
  params: { path: { id: userId } }   // ✅ 路径参数有类型检查
});
```

## CI 流水线集成

```yaml
# .github/workflows/api-contract.yml
- name: Check API type consistency
  run: |
    npm run build          # 启动后端，生成 OpenAPI spec
    npm run check:api      # 验证前端生成的类型与后端 spec 一致
```

## 参考

- openapi-typescript：https://openapi-ts.dev/
- openapi-fetch：https://openapi-ts.dev/openapi-fetch/
- NestJS Swagger：https://docs.nestjs.com/openapi/introduction
