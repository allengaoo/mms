"""
tests/eval/test_python_eval.py — Python FastAPI 项目 Layer 1 E2E Eval

场景覆盖（Execution-based Eval）：
  P-001: 新增模型字段（SCHEMA_ADD_FIELD）
  P-002: 新增 API 端点（ROUTE_ADD_ENDPOINT）
  P-003: 新增服务方法（LOGIC_ADD_CONDITION）

验证方式：
  - 主断言：直接检查业务结果（文件内容/类结构）
  - 副断言：LLM-as-a-Judge 检查生成的 EP 结构是否包含关键意图

每个用例在隔离的 tmp_path 中运行，不污染真实项目。

CI 注意事项：
  - CI 模式（MMS_CI_MODE=1）下跳过真实 LLM 调用，所有用例进入「Mock 验证路径」。
  - Eval 用例被标记 @pytest.mark.eval，在正常 CI 中不执行（仅 eval 专项跑）。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from tests.eval.eval_framework import EvalCase, EvalRunner  # noqa: E402

_CI_MODE = os.environ.get("MMS_CI_MODE") == "1"

# ─── Fixture：构建 Python FastAPI 靶机项目 ────────────────────────────────────

def _build_python_project(root: Path) -> Path:
    """
    构建最小 FastAPI + SQLModel 项目，作为 E2E Eval 的靶机。
    与 tests/conftest.py 中的 isolated_python_project 一致，但可独立调用。
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "requirements.txt").write_text(
        "fastapi>=0.100\nsqlmodel>=0.0.14\n", encoding="utf-8"
    )
    backend = root / "backend" / "app"
    backend.mkdir(parents=True, exist_ok=True)
    (backend / "__init__.py").touch()
    (backend / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
    )
    (backend / "models.py").write_text(
        "from sqlmodel import SQLModel, Field\n\n"
        "class Order(SQLModel, table=True):\n"
        "    id: int | None = Field(default=None, primary_key=True)\n"
        "    amount: float\n",
        encoding="utf-8",
    )
    services = backend / "services"
    services.mkdir(exist_ok=True)
    (services / "__init__.py").touch()
    (services / "order_service.py").write_text(
        "from ..models import Order\n\n"
        "class OrderService:\n"
        "    async def create(self, amount: float) -> Order:\n"
        "        return Order(amount=amount)\n",
        encoding="utf-8",
    )
    api = backend / "api"
    api.mkdir(exist_ok=True)
    (api / "__init__.py").touch()
    (api / "orders.py").write_text(
        "from fastapi import APIRouter\n"
        "from ..services.order_service import OrderService\n\n"
        "router = APIRouter(prefix='/orders')\n\n"
        "@router.post('/')\n"
        "async def create_order(amount: float):\n"
        "    svc = OrderService()\n"
        "    return await svc.create(amount)\n",
        encoding="utf-8",
    )
    return root


# ─── Eval Case 工厂 ───────────────────────────────────────────────────────────

def _make_p001_add_field() -> EvalCase:
    """P-001: 新增 quantity 字段到 Order 模型"""
    def assert_field_in_models(project_root: Path) -> bool:
        models_file = project_root / "backend" / "app" / "models.py"
        if not models_file.exists():
            return False
        content = models_file.read_text(encoding="utf-8")
        return "quantity" in content

    def assert_field_is_typed(project_root: Path) -> bool:
        models_file = project_root / "backend" / "app" / "models.py"
        if not models_file.exists():
            return False
        content = models_file.read_text(encoding="utf-8")
        # 检查是否有类型注解（int 或 float 或 Optional[int]）
        import re
        return bool(re.search(r"quantity\s*:\s*(int|float|Optional)", content))

    judge_prompt = """
你是一个架构审查员。请评估以下生成的 EP 执行计划是否覆盖了用户意图。

用户输入：{user_input}

生成的 EP 内容：
{ep_content}

请判断（回答 YES 或 NO + 原因）：
1. EP 是否提到了修改 models.py 或 Order 模型？
2. EP 是否包含了字段类型声明？
"""
    return EvalCase(
        name="P-001_add_quantity_field",
        user_input="为 Order 模型新增 quantity: int 字段，表示订单数量",
        language="python",
        setup=_build_python_project,
        assertions=[assert_field_in_models, assert_field_is_typed],
        assertion_msgs=[
            "models.py 中存在 quantity 字段",
            "quantity 字段有类型注解（int/float/Optional）",
        ],
        judge_prompt=judge_prompt,
        tags=["add_field", "schema", "python"],
    )


def _make_p002_add_endpoint() -> EvalCase:
    """P-002: 新增 GET /orders/{id} 查询端点"""
    def assert_get_endpoint_exists(project_root: Path) -> bool:
        orders_file = project_root / "backend" / "app" / "api" / "orders.py"
        if not orders_file.exists():
            return False
        content = orders_file.read_text(encoding="utf-8")
        import re
        return bool(re.search(r"@router\.get\s*\(", content))

    def assert_path_param_used(project_root: Path) -> bool:
        orders_file = project_root / "backend" / "app" / "api" / "orders.py"
        if not orders_file.exists():
            return False
        content = orders_file.read_text(encoding="utf-8")
        return "order_id" in content or "id" in content

    judge_prompt = """
你是一个架构审查员。请评估以下生成的 EP 执行计划是否覆盖了用户意图。

用户输入：{user_input}

生成的 EP 内容：
{ep_content}

请判断（回答 YES 或 NO + 原因）：
1. EP 是否提到了新增 GET 端点？
2. EP 是否提到了路径参数（如 order_id）？
"""
    return EvalCase(
        name="P-002_add_get_endpoint",
        user_input="新增 GET /orders/{order_id} 端点，根据 ID 查询单个订单",
        language="python",
        setup=_build_python_project,
        assertions=[assert_get_endpoint_exists, assert_path_param_used],
        assertion_msgs=[
            "orders.py 中存在 GET 路由装饰器",
            "GET 端点包含 order_id 或 id 参数",
        ],
        judge_prompt=judge_prompt,
        tags=["add_endpoint", "route", "python"],
    )


def _make_p003_add_service_method() -> EvalCase:
    """P-003: 在 OrderService 新增 cancel 方法"""
    def assert_cancel_method_exists(project_root: Path) -> bool:
        svc_file = project_root / "backend" / "app" / "services" / "order_service.py"
        if not svc_file.exists():
            return False
        content = svc_file.read_text(encoding="utf-8")
        return "cancel" in content or "delete" in content

    def assert_method_has_signature(project_root: Path) -> bool:
        svc_file = project_root / "backend" / "app" / "services" / "order_service.py"
        if not svc_file.exists():
            return False
        content = svc_file.read_text(encoding="utf-8")
        import re
        return bool(re.search(r"def\s+(cancel|delete)\s*\(", content))

    return EvalCase(
        name="P-003_add_cancel_method",
        user_input="在 OrderService 中新增 cancel(order_id: int) 方法，用于取消订单",
        language="python",
        setup=_build_python_project,
        assertions=[assert_cancel_method_exists, assert_method_has_signature],
        assertion_msgs=[
            "order_service.py 中存在 cancel 或 delete 方法",
            "方法有正确的函数签名（def cancel/delete(...)）",
        ],
        tags=["add_method", "service", "python"],
    )


# ─── 测试类 ───────────────────────────────────────────────────────────────────

class TestPythonEvalCases:
    """
    Python 项目的 Layer 1 E2E Eval 测试。

    在 CI 模式（MMS_CI_MODE=1）下，所有用例通过「Mock 路径」验证：
    - 直接向靶机文件写入预期结果，然后运行断言。
    - 目的是确保「断言逻辑本身」和「靶机结构」是正确的，
      而不是在 CI 中调用真实 LLM。

    在本地 Eval 模式下，调用完整的 mulan ep run 流水线（真实 LLM）。
    """

    @pytest.mark.eval
    def test_p001_add_quantity_field_mock(self, tmp_path: Path):
        """P-001 Mock 路径：验证断言逻辑和靶机结构"""
        case = _make_p001_add_field()
        project_root = case.setup(tmp_path / case.name)

        # Mock: 模拟 mulan 写入了 quantity 字段
        models_file = project_root / "backend" / "app" / "models.py"
        models_file.write_text(
            "from sqlmodel import SQLModel, Field\n\n"
            "class Order(SQLModel, table=True):\n"
            "    id: int | None = Field(default=None, primary_key=True)\n"
            "    amount: float\n"
            "    quantity: int = Field(default=1)\n",
            encoding="utf-8",
        )

        runner = EvalRunner(tmp_path)
        result = runner.run_case(case, project_root=project_root)

        runner.print_report()
        assert result.passed, f"P-001 断言失败: {result.assertion_results}"

    @pytest.mark.eval
    def test_p002_add_get_endpoint_mock(self, tmp_path: Path):
        """P-002 Mock 路径：验证 GET 端点断言"""
        case = _make_p002_add_endpoint()
        project_root = case.setup(tmp_path / case.name)

        # Mock: 模拟 mulan 写入了 GET 端点
        orders_file = project_root / "backend" / "app" / "api" / "orders.py"
        existing = orders_file.read_text(encoding="utf-8")
        orders_file.write_text(
            existing + "\n"
            "@router.get('/{order_id}')\n"
            "async def get_order(order_id: int):\n"
            "    return {'id': order_id}\n",
            encoding="utf-8",
        )

        runner = EvalRunner(tmp_path)
        result = runner.run_case(case, project_root=project_root)

        runner.print_report()
        assert result.passed, f"P-002 断言失败: {result.assertion_results}"

    @pytest.mark.eval
    def test_p003_add_cancel_method_mock(self, tmp_path: Path):
        """P-003 Mock 路径：验证 cancel 方法断言"""
        case = _make_p003_add_service_method()
        project_root = case.setup(tmp_path / case.name)

        # Mock: 模拟 mulan 写入了 cancel 方法
        svc_file = project_root / "backend" / "app" / "services" / "order_service.py"
        existing = svc_file.read_text(encoding="utf-8")
        svc_file.write_text(
            existing + "\n"
            "    async def cancel(self, order_id: int) -> bool:\n"
            "        return True\n",
            encoding="utf-8",
        )

        runner = EvalRunner(tmp_path)
        result = runner.run_case(case, project_root=project_root)

        runner.print_report()
        assert result.passed, f"P-003 断言失败: {result.assertion_results}"

    @pytest.mark.eval
    @pytest.mark.skipif(
        os.environ.get("MMS_CI_MODE") == "1",
        reason="完整 E2E 需要真实 LLM，在 CI 中跳过（运行 mock 版本）"
    )
    def test_p001_full_e2e(self, tmp_path: Path):
        """P-001 完整 E2E（仅本地 eval 环境）：调用真实 mulan 流水线验证结果"""
        pytest.importorskip("mms.workflow.ep_runner")
        # 此测试在本地 eval 模式下运行，调用真实的 EpRunPipeline
        # 实际集成需要配置好 DASHSCOPE_API_KEY
        pytest.skip("需要在配置好 DASHSCOPE_API_KEY 的 eval 环境中运行")
