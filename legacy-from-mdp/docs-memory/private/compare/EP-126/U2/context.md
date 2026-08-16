# Unit 执行上下文： U2
> token 预算：16,000 (capable) | 文件：1 个
> 架构层：L4_application


## 任务

**在 synthesizer.py 中注册新模板描述**




### 层边界契约（L4_application）

L4 — 应用服务层（Control Services）

**典型文件路径**：`backend/app/services/control/*_service.py`

**边界入口**：`async def method(ctx: SecurityContext, ...) -> DomainObject`

**必须出现**：
```python
# 1. 首参必须是 SecurityContext（AC-2 红线）
async def create_{resource}(ctx: SecurityContext, data: CreateRequest) -> DomainObject:

# 2. 所有 DB 查询必须有 tenant_id 过滤（AC-1 + RLS 规则）
stmt = select(Model).where(
    Model.tenant_id == ctx.tenant_id,
    Model.id == resource_id,
)

# 3. WRITE 方法必须调 AuditService.log（AC-3 红线）
await AuditService.log(ctx, action="create_{resource}", resource_id=obj.id)

# 4. 事务策略选 A 或 B，不混用（AC-11 红线）
# Strategy A（推荐写法）：
async with session.begin():
    session.add(obj)
    await AuditService.log(...)
# Strategy B（autobegin）：
await session.execute(stmt)
await session.commit()  # 显式 commit，禁止在 execute 后再 begin()
```

**禁止出现**：
- `import pymilvus` / `import aiokafka` / `import elasticsearch`（只走 infrastructure/ 适配器）
- `session.begin()` 在 `session.execute()` 之后（AC-11 红线）
- `print()` 语句（用 `structlog`）

**典型函数签名**：
```python
async def get_{resource}(ctx: SecurityContext, resource_id: str) -> {Resource}:
async def create_{resource}(ctx: SecurityContext, data: Create{Resource}Request) -> {Resource}:
async def update_{resource}(ctx: SecurityContext, resource_id: str, data: Update{Resource}Request) -> {Resource}:
async def delete_{resource}(ctx: SecurityContext, resource_id: str) -> None:
async def list_{resource}s(ctx: SecurityContext, filter: FilterParams) -> Tuple[List[{Resource}], int]:
```

---

## 涉及文件摘要

### scripts/mms/synthesizer.py
```python
"""

from __future__ import annotations
import sys
import time
from pathlib import Path
from typing import List, Optional

def _load_synthesize_config() -> dict:
    """
def synthesize(
def _build_history_hit_section(hit: "object") -> str:  # type: ignore[type-arg]
    """将历史任务命中结果格式化为 prompt 注入段落。"""
def _load_quickmap(template_name: Optional[str]) -> str:
    """
def _extract_quickmap_files(template_name: Optional[str]) -> List[str]:
    """从 task_quickmap.yaml 提取该任务类型的 must_read_files（供历史记录写入）。"""
def _extract_quickmap_memories(template_name: Optional[str]) -> List[str]:
    """从 task_quickmap.yaml 提取该任务类型的 hot_memories（供历史记录写入）。"""
def _refresh_maps() -> None:
    """调用 codemap.py 和 funcmap.py 刷新快照文件（--refresh-maps 触发）"""
def _load_codemap(template_name: Optional[str]) -> str:
    """
def _extract_funcmap(task: str, template_name: Optional[str]) -> str:
    """
def _extract_e2e_traceability(task: str, template_name: Optional[str]) -> str:
    """
def _extract_keywords(task: str, template_name: Optional[str]) -> list:
    """
def _inject_memories(task: str, top_k: int, compress: bool = True) -> str:
    """调用 MemoryInjector 检索相关记忆，返回压缩后的上下文文本"""
def _load_template(template_name: Optional[str]) -> str:
    """加载指定的 EP 类型模板内容"""
def _call_llm(user_prompt: str) -> str:
    """调用 qwen-plus 生成合成结果"""
def interactive_extra_requirements() -> str:
    """交互式补充用户自定义要求"""
def list_templates() -> None:
    """打印所有可用模板"""
```

### 相关记忆约束（来自 docs/memory/MEMORY.md）

- [autobegin 后禁止再调 session.begin()](shared/L2_infrastructure/D9_database/MEM-DB-002.md) — session.execute() 触发 autobegin 后再调 begin() 报 InvalidRequestError，选 Strategy A 或 B
- [控制面/数据面严格分离（架构基线）](shared/cross_cutting/decisions/AD-003.md) — services/control 只写 MySQL；向量/搜索写入必须通过 services/dispatch 发 Kafka 事件
- [双栈部署流量路由陷阱](shared/L4_application/workers/MEM-L-008.md) — Compose 和 K8s 并存时，K8s Service 和 Compose port-forward 可能路由到不同实例
- [多租户隔离与配额治理规则](shared/BIZ/BIZ-003.md) — 配额检查在 Service 层执行，Quota 超限返回 E_QUOTA_EXCEEDED
## 验证命令

```bash
python3 scripts/mms/arch_check.py --ci
```

---
*token 使用：~751 / 16,000 (capable)*
