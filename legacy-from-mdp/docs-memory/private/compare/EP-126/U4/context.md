# Unit 执行上下文： U4
> token 预算：16,000 (capable) | 文件：1 个
> 架构层：testing


## 任务

**新增测试验证新模板在各模块均已注册**




### 层边界契约（testing）

L5 — 接口层（API Endpoints）

**典型文件路径**：`backend/app/api/v1/endpoints/*.py`

**边界入口**：FastAPI Router + Pydantic Request/Response Schema

**必须出现**：
```python
# 1. 路由装饰器 + response_model（禁止省略）
@router.get("/path", response_model=BaseResponse[ListData[T]])

# 2. 权限守卫（在路由函数签名上方）
@require_permission("domain:resource:action")

# 3. SecurityContext 从依赖注入获取（禁止硬编码）
async def list_objects(
    ctx: SecurityContext = Depends(get_current_user),
    ...
)

# 4. 统一返回 ResponseHelper（禁止裸字典）
return ResponseHelper.ok(data=result, meta={"total": total})
```

**禁止出现**：
- 业务逻辑（SELECT/INSERT/UPDATE 查询）→ 下沉到 Service 层
- `return []` 裸列表 / `return {"key": "val"}` 裸字典（AC-4 红线）
- `import pymilvus` / `import aiokafka` / `import elasticsearch`（AC-1 红线）
- `session` 对象直接在 endpoint 中操作

**典型函数签名**：
```python
async def list_{resource}(
    ctx: SecurityContext = Depends(get_current_user),
    filter_params: {Resource}FilterParams = Depends(),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> BaseResponse[ListData[{Resource}Response]]:
```

---

## 涉及文件摘要

### scripts/mms/tests/test_synthesizer_structure.py
```python
"""
test_synthesizer_structure.py — 验证 synthesizer.py 输出的结构完整性

核心防漏场景：
  - mms synthesize 生成的起手提示词必须包含 ## Scope 节（含表格格式说明）

from __future__ import annotations
import sys
import textwrap
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

class TestSynthesizerPromptStructure:
    """验证 _SYNTHESIS_USER prompt 包含对 Scope/Testing Plan 节的要求"""
    def test_synthesis_user_contains_scope_requirement(self):
        """_SYNTHESIS_USER 必须明确要求 EP 文件包含 ## Scope 节"""
    def test_synthesis_user_contains_testing_plan_requirement(self):
        """_SYNTHESIS_USER 必须明确要求 EP 文件包含 ## Testing Plan 节"""
    def test_synthesis_user_contains_scope_table_format(self):
        """_SYNTHESIS_USER 应包含 Scope 表格格式示例（| Unit | 操作描述 | 涉及文件 |）"""
    def test_synthesis_user_contains_precheck_warning(self):
        """_SYNTHESIS_USER 应提示 Scope/Testing Plan 是 precheck 必要结构"""
class TestEpDevopsTemplate:
    """验证 ep-devops 模板已注册且文件存在"""
    def test_ep_devops_in_supported_templates(self):
        """ep-devops 必须在 SUPPORTED_TEMPLATES 中注册"""
    def test_ep_devops_template_file_exists(self):
        """ep-devops.md 模板文件必须存在于磁盘"""
    def test_ep_devops_template_contains_scope_section(self):
        """ep-devops.md 必须包含 ## Scope 节（范例）"""
    def test_ep_devops_template_contains_testing_plan_section(self):
        """ep-devops.md 必须包含 ## Testing Plan 节（范例）"""
    def test_ep_devops_in_codemap_sections(self):
        """ep-devops 必须在 _TEMPLATE_CODEMAP_SECTIONS 中注册"""
    def test_ep_devops_in_e2e_keywords(self):
        """ep-devops 必须在 _TEMPLATE_E2E_KEYWORDS 中注册"""
class TestAllTemplatesConsistency:
    """验证所有已注册模板的 .md 文件存在且包含必要节"""
    def test_all_registered_templates_have_files(self):
        """所有 SUPPORTED_TEMPLATES 中的模板必须有对应的 .md 文件"""
    def test_all_templates_contain_scope_section(self):
        """所有 EP 模板都应包含 ## Scope 节（引导 LLM 生成标准格式）"""
    def test_all_templates_contain_testing_plan_section(self):
        """所有 EP 模板都应包含 ## Testing Plan 节（引导 LLM 生成标准格式）"""
class TestEpParserScopeAndTestingPlan:
    """验证 ep_parser 能正确解析含 Scope + Testing Plan 节的 EP 文件"""
    def test_parses_scope_units_from_devops_ep(self, tmp_path):
        """ep_parser 应能从运维类 EP 的 Scope 表格中解析出 Unit 列表"""
    def test_parses_testing_plan_section_exists(self, tmp_path):
        """ep_parser 解析后 testing_files 即使为空，Testing Plan 节也应被识别"""
    def test_standard_ep_with_both_sections_parses_correctly(self, tmp_path):
        """含完整 Scope 表格和 Testing Plan 文件列表的 EP 应被正确解析"""
```

### 相关记忆约束（来自 docs/memory/MEMORY.md）

- [autobegin 后禁止再调 session.begin()](shared/L2_infrastructure/D9_database/MEM-DB-002.md) — session.execute() 触发 autobegin 后再调 begin() 报 InvalidRequestError，选 Strategy A 或 B
- [Python or 不能用于数值型默认值](shared/L2_infrastructure/D4_resilience/MEM-L-001.md) — `0 or default` 返回 default（错误），数值字段必须用 `if x is None`
- [Avro 序列化静默失败：必须过归一化门](shared/L2_infrastructure/D4_resilience/MEM-L-002.md) — Kafka 发送前必须调 normalize_record()，禁止发送含 date/Decimal/UUID 原生类型
- [Avro 格式必须一致：container 非 schemaless](shared/L2_infrastructure/D6_messaging/MEM-L-011.md) — 生产端用 fastavro.write，消费端必须用 fastavro.reader，混用导致解析错误
- [Schema Registry BACKWARD 兼容](shared/L2_infrastructure/D6_messaging/MEM-L-006.md) — 新字段必须有 default 值，否则旧 Consumer 反序列化失败
## 验证命令

```bash
pytest scripts/mms/tests/test_synthesizer_structure.py -v
python3 scripts/mms/arch_check.py --ci
```

---
*token 使用：~926 / 16,000 (capable)*
