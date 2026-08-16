# Unit 执行上下文： U1
> token 预算：16,000 (capable) | 文件：1 个
> 架构层：L4_application


## 任务

**在 task_matcher.py 中注册新模板标签**




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

### scripts/mms/task_matcher.py
```python
"""
task_matcher.py — 任务相似度匹配器（MMS 三级检索漏斗 · 第一级）

算法：无向量、无全文检索引擎
  1. 从任务描述中提取标签集（中文词块 + 英文词 + 模板类型 + 记忆层标签）

from __future__ import annotations
import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any

class TaskRecord:
    """历史任务的持久化格式（task_history.jsonl 中的单行 JSON）。"""
    def to_dict(self) -> Dict[str, Any]:
    def from_dict(d: Dict[str, Any]) -> "TaskRecord":
class MatchResult:
    """相似任务命中结果。"""
class TaskMatcher:
    """
    def __init__(
    def extract_tags(self, task: str, template: Optional[str] = None) -> List[str]:
        """
    def find_similar(
    def append_record(self, record: TaskRecord) -> None:
        """
    def build_record(
    def _load_records(self) -> List[TaskRecord]:
        """从 task_history.jsonl 加载所有记录，跳过损坏的行。"""
    def _time_weight(self, ts_str: str, now: datetime) -> float:
        """根据历史记录时间戳计算衰减权重。"""
    def _jaccard(self, a: set, b: set) -> float:
        """计算两个标签集的 Jaccard 相似度。"""
    def _best_match(
```

### 相关记忆约束（来自 docs/memory/MEMORY.md）

- [autobegin 后禁止再调 session.begin()](shared/L2_infrastructure/D9_database/MEM-DB-002.md) — session.execute() 触发 autobegin 后再调 begin() 报 InvalidRequestError，选 Strategy A 或 B
- [控制面/数据面严格分离（架构基线）](shared/cross_cutting/decisions/AD-003.md) — services/control 只写 MySQL；向量/搜索写入必须通过 services/dispatch 发 Kafka 事件
- [双栈部署流量路由陷阱](shared/L4_application/workers/MEM-L-008.md) — Compose 和 K8s 并存时，K8s Service 和 Compose port-forward 可能路由到不同实例
- [知识索引三层架构](shared/cross_cutting/decisions/AD-008.md) — MEMORY_INDEX.json（机器）+ MEMORY.md（Agent）+ task_quickmap.yaml（静态兜底）三层分工
- [多租户隔离与配额治理规则](shared/BIZ/BIZ-003.md) — 配额检查在 Service 层执行，Quota 超限返回 E_QUOTA_EXCEEDED
## 验证命令

```bash
python3 scripts/mms/arch_check.py --ci
```

---
*token 使用：~709 / 16,000 (capable)*
