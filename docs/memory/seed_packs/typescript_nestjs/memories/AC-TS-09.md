---
id: AC-TS-09
layer: ADAPTER
tier: warm
type: pattern
language: typescript
pack: typescript_nestjs
about_concepts: [nestjs, exception-filter, response-envelope, error-handling]
cites_files: []
created_at: "2026-04-27"
---

# NestJS 全局异常过滤器统一包装为标准信封格式

## 模式（Pattern）

所有 API 的错误响应必须通过全局异常过滤器统一格式化为标准信封 `{code, message, data}`，禁止各 Controller 自行构造错误响应格式。

```typescript
// src/common/filters/http-exception.filter.ts
import { ExceptionFilter, Catch, ArgumentsHost, HttpException, HttpStatus } from '@nestjs/common';
import { Request, Response } from 'express';

@Catch()
export class AllExceptionsFilter implements ExceptionFilter {
  catch(exception: unknown, host: ArgumentsHost) {
    const ctx = host.switchToHttp();
    const response = ctx.getResponse<Response>();
    const request = ctx.getRequest<Request>();

    let status = HttpStatus.INTERNAL_SERVER_ERROR;
    let code = 50000;
    let message = 'Internal server error';

    if (exception instanceof HttpException) {
      status = exception.getStatus();
      code = status * 100;   // 40400, 40100 等业务错误码
      const exceptionResponse = exception.getResponse();
      message = typeof exceptionResponse === 'string'
        ? exceptionResponse
        : (exceptionResponse as any).message || message;
    } else if (exception instanceof BusinessException) {
      status = HttpStatus.BAD_REQUEST;
      code = (exception as BusinessException).code;
      message = (exception as BusinessException).message;
    }

    response.status(status).json({
      code,
      message: Array.isArray(message) ? message.join('; ') : message,
      data: null,
      timestamp: new Date().toISOString(),
      path: request.url,
    });
  }
}

// main.ts：全局注册
app.useGlobalFilters(new AllExceptionsFilter());
```

## 成功响应拦截器（配套）

```typescript
// src/common/interceptors/response.interceptor.ts
@Injectable()
export class ResponseInterceptor<T> implements NestInterceptor<T, ApiResponse<T>> {
  intercept(context: ExecutionContext, next: CallHandler): Observable<ApiResponse<T>> {
    return next.handle().pipe(
      map(data => ({
        code: 20000,
        message: 'success',
        data,
      })),
    );
  }
}
```

## 参考

- NestJS 文档：[Exception filters](https://docs.nestjs.com/exception-filters)
