"""
tests/eval/test_go_eval.py — Go Gin 项目 Layer 1 E2E Eval

场景覆盖：
  G-001: 在 Go struct 中新增字段（SCHEMA_ADD_FIELD）
  G-002: 在 service 中新增方法（LOGIC_ADD_CONDITION）
  G-003: 在 handler 中新增路由处理函数（ROUTE_ADD_ENDPOINT）
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from tests.eval.eval_framework import EvalCase, EvalRunner  # noqa: E402


# ─── 靶机构建 ─────────────────────────────────────────────────────────────────

def _build_go_project(root: Path) -> Path:
    """构建最小 Go Gin 项目"""
    root.mkdir(parents=True, exist_ok=True)
    (root / "go.mod").write_text(
        "module github.com/example/demo\n\ngo 1.21\n\n"
        "require github.com/gin-gonic/gin v1.9.1\n",
        encoding="utf-8",
    )
    (root / "main.go").write_text(
        "package main\n\nimport \"github.com/gin-gonic/gin\"\n\n"
        "func main() {\n    r := gin.Default()\n    r.Run()\n}\n",
        encoding="utf-8",
    )

    internal = root / "internal"
    domain = internal / "domain"
    domain.mkdir(parents=True, exist_ok=True)
    (domain / "order.go").write_text(
        "package domain\n\n"
        "type Order struct {\n"
        "    ID     int64   `json:\"id\"`\n"
        "    Amount float64 `json:\"amount\"`\n"
        "}\n",
        encoding="utf-8",
    )

    service = internal / "service"
    service.mkdir(parents=True, exist_ok=True)
    (service / "order.go").write_text(
        "package service\n\n"
        "import \"github.com/example/demo/internal/domain\"\n\n"
        "type OrderService struct{}\n\n"
        "func (s *OrderService) Create(amount float64) (*domain.Order, error) {\n"
        "    return &domain.Order{Amount: amount}, nil\n"
        "}\n",
        encoding="utf-8",
    )

    handler = internal / "handler"
    handler.mkdir(parents=True, exist_ok=True)
    (handler / "order.go").write_text(
        "package handler\n\n"
        "import \"github.com/gin-gonic/gin\"\n\n"
        "func CreateOrder(c *gin.Context) {\n"
        "    c.JSON(200, gin.H{\"status\": \"created\"})\n"
        "}\n",
        encoding="utf-8",
    )
    return root


# ─── Eval Cases ───────────────────────────────────────────────────────────────

def _make_g001_add_field() -> EvalCase:
    """G-001: 在 Order struct 新增 Quantity 字段"""
    def assert_field_in_struct(project_root: Path) -> bool:
        domain_file = project_root / "internal" / "domain" / "order.go"
        if not domain_file.exists():
            return False
        return "Quantity" in domain_file.read_text(encoding="utf-8") or \
               "quantity" in domain_file.read_text(encoding="utf-8").lower()

    def assert_field_has_json_tag(project_root: Path) -> bool:
        domain_file = project_root / "internal" / "domain" / "order.go"
        if not domain_file.exists():
            return False
        content = domain_file.read_text(encoding="utf-8")
        return bool(re.search(r'[Qq]uantity\s+\w+\s+`json:', content))

    judge_prompt = """
用户意图：{user_input}
生成的 EP：{ep_content}

请判断（YES/NO + 原因）：
1. EP 是否提到了修改 Go struct（Order）？
2. EP 是否包含了添加 JSON tag 的步骤？
"""
    return EvalCase(
        name="G-001_add_quantity_field",
        user_input="在 Order struct 中新增 Quantity int64 字段，并添加 json:'quantity' tag",
        language="go",
        setup=_build_go_project,
        assertions=[assert_field_in_struct, assert_field_has_json_tag],
        assertion_msgs=[
            "order.go struct 中存在 Quantity 字段",
            "Quantity 字段有 json tag",
        ],
        judge_prompt=judge_prompt,
        tags=["add_field", "schema", "go"],
    )


def _make_g002_add_service_method() -> EvalCase:
    """G-002: 在 OrderService 新增 Cancel 方法"""
    def assert_cancel_method_exists(project_root: Path) -> bool:
        svc_file = project_root / "internal" / "service" / "order.go"
        if not svc_file.exists():
            return False
        content = svc_file.read_text(encoding="utf-8")
        return "Cancel" in content or "cancel" in content

    def assert_method_returns_error(project_root: Path) -> bool:
        svc_file = project_root / "internal" / "service" / "order.go"
        if not svc_file.exists():
            return False
        content = svc_file.read_text(encoding="utf-8")
        return bool(re.search(r"func.*[Cc]ancel.*error", content))

    return EvalCase(
        name="G-002_add_cancel_method",
        user_input="在 OrderService 中新增 Cancel(id int64) error 方法，用于取消订单",
        language="go",
        setup=_build_go_project,
        assertions=[assert_cancel_method_exists, assert_method_returns_error],
        assertion_msgs=[
            "service/order.go 中存在 Cancel 方法",
            "Cancel 方法的返回值包含 error",
        ],
        tags=["add_method", "service", "go"],
    )


def _make_g003_add_handler() -> EvalCase:
    """G-003: 新增 GetOrder handler 函数"""
    def assert_get_handler_exists(project_root: Path) -> bool:
        handler_file = project_root / "internal" / "handler" / "order.go"
        if not handler_file.exists():
            return False
        content = handler_file.read_text(encoding="utf-8")
        return "GetOrder" in content or "getOrder" in content

    def assert_uses_path_param(project_root: Path) -> bool:
        handler_file = project_root / "internal" / "handler" / "order.go"
        if not handler_file.exists():
            return False
        content = handler_file.read_text(encoding="utf-8")
        return "Param" in content or ":id" in content or "id" in content.lower()

    return EvalCase(
        name="G-003_add_get_handler",
        user_input="新增 GetOrder handler 函数，从路径参数 :id 获取 order_id 并返回订单信息",
        language="go",
        setup=_build_go_project,
        assertions=[assert_get_handler_exists, assert_uses_path_param],
        assertion_msgs=[
            "handler/order.go 中存在 GetOrder 函数",
            "GetOrder 函数使用了路径参数 id",
        ],
        tags=["add_handler", "route", "go"],
    )


# ─── 测试类 ───────────────────────────────────────────────────────────────────

class TestGoEvalCases:

    @pytest.mark.eval
    def test_g001_add_field_mock(self, tmp_path: Path):
        """G-001 Mock 路径：注入 Quantity 字段验证断言"""
        case = _make_g001_add_field()
        project_root = case.setup(tmp_path / case.name)

        domain_file = project_root / "internal" / "domain" / "order.go"
        domain_file.write_text(
            "package domain\n\n"
            "type Order struct {\n"
            "    ID       int64   `json:\"id\"`\n"
            "    Amount   float64 `json:\"amount\"`\n"
            "    Quantity int64   `json:\"quantity\"`\n"
            "}\n",
            encoding="utf-8",
        )

        runner = EvalRunner(tmp_path)
        result = runner.run_case(case, project_root=project_root)
        runner.print_report()
        assert result.passed, f"G-001 断言失败: {result.assertion_results}"

    @pytest.mark.eval
    def test_g002_add_cancel_method_mock(self, tmp_path: Path):
        """G-002 Mock 路径：注入 Cancel 方法验证断言"""
        case = _make_g002_add_service_method()
        project_root = case.setup(tmp_path / case.name)

        svc_file = project_root / "internal" / "service" / "order.go"
        existing = svc_file.read_text(encoding="utf-8")
        svc_file.write_text(
            existing + "\n"
            "func (s *OrderService) Cancel(id int64) error {\n"
            "    return nil\n"
            "}\n",
            encoding="utf-8",
        )

        runner = EvalRunner(tmp_path)
        result = runner.run_case(case, project_root=project_root)
        runner.print_report()
        assert result.passed, f"G-002 断言失败: {result.assertion_results}"

    @pytest.mark.eval
    def test_g003_add_get_handler_mock(self, tmp_path: Path):
        """G-003 Mock 路径：注入 GetOrder handler 验证断言"""
        case = _make_g003_add_handler()
        project_root = case.setup(tmp_path / case.name)

        handler_file = project_root / "internal" / "handler" / "order.go"
        existing = handler_file.read_text(encoding="utf-8")
        handler_file.write_text(
            existing + "\n"
            "func GetOrder(c *gin.Context) {\n"
            "    id := c.Param(\"id\")\n"
            "    c.JSON(200, gin.H{\"id\": id})\n"
            "}\n",
            encoding="utf-8",
        )

        runner = EvalRunner(tmp_path)
        result = runner.run_case(case, project_root=project_root)
        runner.print_report()
        assert result.passed, f"G-003 断言失败: {result.assertion_results}"
