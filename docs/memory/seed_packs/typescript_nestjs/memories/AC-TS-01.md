---
id: AC-TS-01
layer: ADAPTER
tier: hot
type: arch_constraint
language: typescript
pack: typescript_nestjs
about_concepts: [nestjs, guard, jwt, authorization, security, api]
cites_files: []
created_at: "2026-04-27"
---

# NestJS 写接口必须绑定 @UseGuards(JwtAuthGuard)，禁止裸露写接口

## 约束（Constraint）

任何负责处理写操作（`@Post`、`@Put`、`@Patch`、`@Delete`）的控制器方法，必须绑定 `@UseGuards(JwtAuthGuard)` 或等效的权限校验装饰器。

```typescript
// ❌ 错误：裸露的写接口，任何人都可以调用
@Controller('users')
export class UsersController {
  @Post()               // ❌ 无鉴权！任何人可创建用户
  create(@Body() dto: CreateUserDto) {
    return this.usersService.create(dto);
  }

  @Delete(':id')        // ❌ 无鉴权！任何人可删除用户
  remove(@Param('id') id: string) {
    return this.usersService.remove(+id);
  }
}
```

```typescript
// ✅ 正确：所有写接口都有鉴权守卫
@Controller('users')
@UseGuards(JwtAuthGuard)   // ✅ 类级别守卫，保护所有路由（推荐）
export class UsersController {

  @Get(':id')              // GET 可以公开（或单独加 guard）
  @Public()                // 使用 @Public() 装饰器标记公开路由
  findOne(@Param('id') id: string) {
    return this.usersService.findOne(+id);
  }

  @Post()                  // ✅ 继承类级别 JwtAuthGuard
  create(@Body() dto: CreateUserDto, @CurrentUser() user: User) {
    return this.usersService.create(dto, user);
  }

  @Delete(':id')           // ✅ 继承类级别 JwtAuthGuard
  @Roles(Role.Admin)       // 额外的角色守卫
  remove(@Param('id') id: string) {
    return this.usersService.remove(+id);
  }
}
```

## 全局守卫 + 白名单模式（推荐）

```typescript
// app.module.ts：全局注册 JwtAuthGuard，默认所有路由需鉴权
providers: [
  { provide: APP_GUARD, useClass: JwtAuthGuard },
  { provide: APP_GUARD, useClass: RolesGuard },
]

// 需要公开的路由使用 @Public() 装饰器显式标记
@SetMetadata('isPublic', true)
export const Public = () => SetMetadata('isPublic', true);
```

## 参考

- NestJS 文档：[Guards](https://docs.nestjs.com/guards)
- 参考实现：`nestjs/nest/sample/19-auth-jwt/`
