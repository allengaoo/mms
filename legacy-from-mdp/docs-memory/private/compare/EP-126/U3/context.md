# Unit 执行上下文： U3
> token 预算：16,000 (capable) | 文件：1 个
> 架构层：L5_interface


## 任务

**在 cli.py 中添加新模板选项和说明**




### 层边界契约（L5_interface）

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

### scripts/mms/cli.py
```python
"""

def c(text: str, color: str) -> str:
def header(title: str) -> None:
def ok(msg: str) -> None:
def warn(msg: str) -> None:
def err(msg: str) -> None:
def info(msg: str) -> None:
def cmd_help(args: argparse.Namespace) -> int:
    """help 子命令：彩色命令参考"""
def _print_command_help(cmd_name: str) -> None:
    """打印单个命令的详细帮助"""
def _print_full_help() -> None:
    """打印完整彩色命令参考"""
def cmd_status(args: argparse.Namespace) -> int:
def _print_memory_stats() -> None:
    """打印记忆库 tier 分布统计"""
def cmd_distill(args: argparse.Namespace) -> int:
def cmd_gc(args: argparse.Namespace) -> int:
def cmd_validate(args: argparse.Namespace) -> int:
def cmd_search(args: argparse.Namespace) -> int:
def cmd_list(args: argparse.Namespace) -> int:
def cmd_hook(args: argparse.Namespace) -> int:
def cmd_incomplete(args: argparse.Namespace) -> int:
def cmd_private(args: argparse.Namespace) -> int:
def cmd_reset_circuit(args: argparse.Namespace) -> int:
def build_parser() -> argparse.ArgumentParser:
def cmd_verify(args: argparse.Namespace) -> int:
    """verify 子命令：调用 verify.py 主逻辑"""
def cmd_codemap(args: argparse.Namespace) -> int:
    """codemap 子命令：生成代码目录快照"""
def cmd_funcmap(args: argparse.Namespace) -> int:
    """funcmap 子命令：生成函数签名索引"""
def cmd_usage(args: argparse.Namespace) -> int:
    """usage 子命令：展示模型调用统计报告"""
def cmd_synthesize(args: argparse.Namespace) -> int:
    """synthesize 子命令：LLM 意图合成，生成结构化 Cursor 起手提示词"""
def cmd_precheck(args: argparse.Namespace) -> int:
    """precheck 子命令：代码修改前检查门控"""
def cmd_postcheck(args: argparse.Namespace) -> int:
    """postcheck 子命令：代码修改后测试与后校验"""
def cmd_actions(args: argparse.Namespace) -> int:
    """actions 子命令：列出或查看 MMS 系统的 ActionDef / FunctionDef 定义"""
def cmd_graph(args: argparse.Namespace) -> int:
    """graph 子命令：记忆知识图谱查询（探索/反查/影响分析）"""
def cmd_unit(args: argparse.Namespace) -> int:
    """unit 子命令：DAG 任务编排（EP-117）"""
def _load_inject_manifest() -> dict:
    """加载 INJECT_MANIFEST.json 配置"""
def _cmd_inject_dispatch(args: argparse.Namespace) -> int:
    """inject 命令分发，支持 --mode 分层注入"""
def cmd_ep(args: argparse.Namespace) -> int:
    """ep 子命令：交互式 EP 工作流向导"""
def cmd_dream(args: argparse.Namespace) -> int:
    """dream 子命令：autoDream 知识萃取"""
def cmd_template(args: argparse.Namespace) -> int:
    """template 子命令：代码模板库"""
def main() -> int:
```

### 相关记忆约束（来自 docs/memory/MEMORY.md）

- [API 响应必须用 Envelope 格式](shared/L5_interface/D8_api/MEM-L-020.md) — 返回 {"code": 200, "data": ..., "meta": ...}，禁止裸列表或裸字典
- [DomainException 必须映射 error_registry](shared/L5_interface/D8_api/MEM-L-022.md) — raise DomainException(code="E_MODULE_ID")，code 必须在 error_registry.md 中注册
- [大数据量列表 API 必须用 cursor 分页](shared/L5_interface/D8_api/MEM-L-021.md) — offset 分页在百万级数据退化严重，超过 10K 条必须改 cursor-based
- [管理页面用 React + ProComponents](shared/L5_interface/frontend/MEM-L-023.md) — Amis JSON 只用于 Chat2App 模块，管理页面必须是 TypeScript React 组件
- [ObjectType 版本历史通过独立 API 暴露](shared/L3_domain/ontology/MEM-L-015.md) — 版本历史不应内联在 ObjectType 详情 API 中
## 验证命令

```bash
python3 scripts/mms/arch_check.py --ci
```

---
*token 使用：~854 / 16,000 (capable)*
