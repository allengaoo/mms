---
id: AC-TS-04
layer: DOMAIN
tier: warm
type: anti_pattern
language: typescript
pack: typescript_nestjs
about_concepts: [nestjs, circular-dependency, event-emitter, module-coupling]
cites_files: []
created_at: "2026-04-27"
---

# NestJS 模块间禁止直接注入 Service，跨模块通信用 EventEmitter2

## 反模式（Anti-Pattern）

NestJS 模块 A 直接注入模块 B 的 Service，当 B 也依赖 A 时形成循环依赖，即使用 `forwardRef()` 绕过也会导致不可预知的初始化顺序问题。

```typescript
// ❌ 危险：OrderModule 注入 InventoryService，InventoryModule 又注入 OrderService
// → 循环依赖！NestJS 需要用 forwardRef() 才能启动，架构已腐化

@Module({
  imports: [forwardRef(() => InventoryModule)],   // 坏味道！
  providers: [OrderService],
})
export class OrderModule {}

@Injectable()
export class OrderService {
  constructor(
    @Inject(forwardRef(() => InventoryService))
    private inventoryService: InventoryService,   // 循环依赖
  ) {}
}
```

```typescript
// ✅ 正确：通过 EventEmitter2 解耦
import { EventEmitter2 } from '@nestjs/event-emitter';

// OrderModule 发布事件（不依赖 InventoryModule）
@Injectable()
export class OrderService {
  constructor(private eventEmitter: EventEmitter2) {}

  async createOrder(dto: CreateOrderDto) {
    const order = await this.orderRepo.save(dto);
    this.eventEmitter.emit('order.created', { orderId: order.id, items: dto.items });
    return order;
  }
}

// InventoryModule 监听事件（不依赖 OrderModule）
@Injectable()
export class InventoryListener {
  @OnEvent('order.created')
  async handleOrderCreated(payload: OrderCreatedEvent) {
    await this.inventoryService.deductStock(payload.items);
  }
}
```

## 参考

- NestJS 文档：[Events](https://docs.nestjs.com/techniques/events)
- NestJS 文档：[Circular dependency](https://docs.nestjs.com/fundamentals/circular-dependency)
