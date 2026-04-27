---
id: AC-TS-03
layer: ADAPTER
tier: hot
type: arch_constraint
language: typescript
pack: typescript_nestjs
about_concepts: [nestjs, dto, class-validator, input-validation, pipe]
cites_files: []
created_at: "2026-04-27"
---

# NestJS DTO 必须使用 class-validator 装饰器，禁止手写校验

## 约束（Constraint）

```typescript
// ❌ 错误：手写校验逻辑
@Controller('orders')
export class OrdersController {
  @Post()
  create(@Body() body: any) {   // 未类型化
    // 手写校验（繁琐、易遗漏）
    if (!body.productId || typeof body.productId !== 'number') {
      throw new BadRequestException('productId must be a number');
    }
    if (!body.quantity || body.quantity < 1) {
      throw new BadRequestException('quantity must be at least 1');
    }
    return this.ordersService.create(body);
  }
}
```

```typescript
// ✅ 正确：class-validator + ValidationPipe 自动校验
import { IsInt, IsPositive, IsString, IsOptional, MinLength } from 'class-validator';
import { Type } from 'class-transformer';

export class CreateOrderDto {
  @IsInt()
  @IsPositive()
  @Type(() => Number)
  productId: number;

  @IsInt()
  @Min(1)
  @Max(100)
  @Type(() => Number)
  quantity: number;

  @IsString()
  @MinLength(5)
  @IsOptional()
  remark?: string;
}

@Controller('orders')
export class OrdersController {
  @Post()
  create(@Body() dto: CreateOrderDto) {   // ValidationPipe 自动校验
    return this.ordersService.create(dto);
  }
}

// main.ts：全局开启 ValidationPipe
app.useGlobalPipes(new ValidationPipe({
  whitelist: true,              // 自动剔除未声明的字段（防止 mass assignment）
  forbidNonWhitelisted: true,   // 有未声明字段时抛出错误
  transform: true,              // 自动类型转换（配合 @Type）
}));
```

## 参考

- NestJS 文档：[Validation](https://docs.nestjs.com/techniques/validation)
- class-validator：https://github.com/typestack/class-validator
