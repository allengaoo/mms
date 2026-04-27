---
id: AC-TS-07
layer: DOMAIN
tier: warm
type: lesson
language: typescript
pack: typescript_nestjs
about_concepts: [nestjs, typeorm, repository, module-boundary, dependency]
cites_files: []
created_at: "2026-04-27"
---

# NestJS TypeORM Repository 不能跨模块引用，必须封装为 Service

## 教训（Lesson）

在 NestJS 中，通过 `@InjectRepository(Entity)` 注入的 Repository 只能在其注册的模块内使用。直接在其他模块注入另一个模块的 Repository 违反了模块封装原则，并导致代码耦合。

```typescript
// ❌ 错误：OrdersModule 直接注入 UsersModule 的 UserRepository
@Module({
  imports: [
    TypeOrmModule.forFeature([Order]),
    TypeOrmModule.forFeature([User]),   // ❌ 直接引入 User Entity（越界！）
  ],
  providers: [OrdersService],
})
export class OrdersModule {}

@Injectable()
export class OrdersService {
  constructor(
    @InjectRepository(User)
    private userRepo: Repository<User>,   // ❌ 跨模块使用 Repository
  ) {}
}
```

```typescript
// ✅ 正确：通过 UsersService 封装，模块间通过 Service 接口通信

// users.module.ts
@Module({
  imports: [TypeOrmModule.forFeature([User])],
  providers: [UsersService],
  exports: [UsersService],   // ✅ 导出 Service，不导出 Repository
})
export class UsersModule {}

// orders.module.ts
@Module({
  imports: [
    TypeOrmModule.forFeature([Order]),
    UsersModule,              // ✅ 导入模块，通过 Service 访问
  ],
  providers: [OrdersService],
})
export class OrdersModule {}

@Injectable()
export class OrdersService {
  constructor(
    private usersService: UsersService,   // ✅ 通过 Service 访问用户数据
  ) {}
}
```

## 参考

- NestJS 文档：[Module Reference](https://docs.nestjs.com/fundamentals/module-ref)
- NestJS TypeORM：[Repository pattern](https://docs.nestjs.com/techniques/database#repository-pattern)
