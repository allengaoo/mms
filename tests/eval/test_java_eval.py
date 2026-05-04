"""
tests/eval/test_java_eval.py — Java Spring Boot 项目 Layer 1 E2E Eval

场景覆盖：
  J-001: 在 JPA Entity 中新增字段（SCHEMA_ADD_FIELD）
  J-002: 在 Repository 中新增查询方法（QUERY_ADD_SELECT）
  J-003: 在 Controller 中新增 API 端点（ROUTE_ADD_ENDPOINT）
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from tests.eval.eval_framework import EvalCase, EvalRunner  # noqa: E402


# ─── 靶机构建 ─────────────────────────────────────────────────────────────────

def _build_java_project(root: Path) -> Path:
    """构建最小 Spring Boot + JPA 项目（基于 tests/fixtures/spring-boot-demo 结构）"""
    root.mkdir(parents=True, exist_ok=True)
    (root / "pom.xml").write_text(
        "<project>\n  <modelVersion>4.0.0</modelVersion>\n"
        "  <groupId>com.example</groupId>\n"
        "  <artifactId>demo</artifactId>\n"
        "  <version>0.0.1-SNAPSHOT</version>\n"
        "  <parent>\n    <groupId>org.springframework.boot</groupId>\n"
        "    <artifactId>spring-boot-starter-parent</artifactId>\n"
        "    <version>3.2.0</version>\n  </parent>\n</project>",
        encoding="utf-8",
    )

    domain = root / "src" / "main" / "java" / "com" / "example" / "demo" / "domain"
    domain.mkdir(parents=True, exist_ok=True)
    (domain / "Order.java").write_text(
        "package com.example.demo.domain;\n\n"
        "import jakarta.persistence.*;\n\n"
        "@Entity\n@Table(name = \"orders\")\n"
        "public class Order {\n\n"
        "    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)\n"
        "    private Long id;\n\n"
        "    private Double amount;\n\n"
        "    public Long getId() { return id; }\n"
        "    public Double getAmount() { return amount; }\n"
        "    public void setAmount(Double amount) { this.amount = amount; }\n"
        "}\n",
        encoding="utf-8",
    )

    repository = root / "src" / "main" / "java" / "com" / "example" / "demo" / "repository"
    repository.mkdir(parents=True, exist_ok=True)
    (repository / "OrderRepository.java").write_text(
        "package com.example.demo.repository;\n\n"
        "import com.example.demo.domain.Order;\n"
        "import org.springframework.data.jpa.repository.JpaRepository;\n\n"
        "public interface OrderRepository extends JpaRepository<Order, Long> {\n}\n",
        encoding="utf-8",
    )

    controller = root / "src" / "main" / "java" / "com" / "example" / "demo" / "controller"
    controller.mkdir(parents=True, exist_ok=True)
    (controller / "OrderController.java").write_text(
        "package com.example.demo.controller;\n\n"
        "import org.springframework.web.bind.annotation.*;\n\n"
        "@RestController\n@RequestMapping(\"/orders\")\n"
        "public class OrderController {\n\n"
        "    @PostMapping\n"
        "    public String createOrder() { return \"created\"; }\n"
        "}\n",
        encoding="utf-8",
    )
    return root


# ─── Eval Cases ───────────────────────────────────────────────────────────────

def _make_j001_add_field() -> EvalCase:
    """J-001: 在 Order Entity 新增 quantity 字段"""
    def assert_field_in_entity(project_root: Path) -> bool:
        entity_file = (
            project_root / "src" / "main" / "java" / "com" / "example"
            / "demo" / "domain" / "Order.java"
        )
        if not entity_file.exists():
            return False
        return "quantity" in entity_file.read_text(encoding="utf-8")

    def assert_has_getter(project_root: Path) -> bool:
        entity_file = (
            project_root / "src" / "main" / "java" / "com" / "example"
            / "demo" / "domain" / "Order.java"
        )
        if not entity_file.exists():
            return False
        content = entity_file.read_text(encoding="utf-8")
        import re
        return bool(re.search(r"getQuantity|setQuantity", content))

    judge_prompt = """
用户意图：{user_input}
生成的 EP：{ep_content}

请判断（YES/NO + 原因）：
1. EP 是否提到了修改 Order.java 或 JPA Entity？
2. EP 是否包含了添加字段及其 getter/setter 的步骤？
"""
    return EvalCase(
        name="J-001_add_quantity_field",
        user_input="在 Order JPA Entity 中新增 quantity（Integer 类型）字段，表示订单商品数量",
        language="java",
        setup=_build_java_project,
        assertions=[assert_field_in_entity, assert_has_getter],
        assertion_msgs=[
            "Order.java 中存在 quantity 字段",
            "Order.java 中存在 quantity 的 getter 或 setter",
        ],
        judge_prompt=judge_prompt,
        tags=["add_field", "schema", "java", "jpa"],
    )


def _make_j002_add_query_method() -> EvalCase:
    """J-002: 在 Repository 新增按金额范围查询的方法"""
    def assert_query_method_exists(project_root: Path) -> bool:
        repo_file = (
            project_root / "src" / "main" / "java" / "com" / "example"
            / "demo" / "repository" / "OrderRepository.java"
        )
        if not repo_file.exists():
            return False
        content = repo_file.read_text(encoding="utf-8")
        return "findBy" in content or "findAll" in content or "@Query" in content

    return EvalCase(
        name="J-002_add_query_method",
        user_input="在 OrderRepository 中新增 findByAmountBetween(min, max) 查询方法，用于按金额范围筛选订单",
        language="java",
        setup=_build_java_project,
        assertions=[assert_query_method_exists],
        assertion_msgs=[
            "OrderRepository.java 中存在查询方法（findBy... 或 @Query）",
        ],
        tags=["add_query", "repository", "java", "jpa"],
    )


def _make_j003_add_endpoint() -> EvalCase:
    """J-003: 在 Controller 新增 GET /{id} 端点"""
    def assert_get_mapping_exists(project_root: Path) -> bool:
        ctrl_file = (
            project_root / "src" / "main" / "java" / "com" / "example"
            / "demo" / "controller" / "OrderController.java"
        )
        if not ctrl_file.exists():
            return False
        return "@GetMapping" in ctrl_file.read_text(encoding="utf-8")

    return EvalCase(
        name="J-003_add_get_endpoint",
        user_input="在 OrderController 中新增 GET /orders/{id} 端点，根据 ID 查询单个订单",
        language="java",
        setup=_build_java_project,
        assertions=[assert_get_mapping_exists],
        assertion_msgs=["OrderController.java 中存在 @GetMapping 注解"],
        tags=["add_endpoint", "controller", "java", "spring"],
    )


# ─── 测试类 ───────────────────────────────────────────────────────────────────

class TestJavaEvalCases:

    @pytest.mark.eval
    def test_j001_add_field_mock(self, tmp_path: Path):
        """J-001 Mock 路径：直接写入预期 Java 代码验证断言逻辑"""
        case = _make_j001_add_field()
        project_root = case.setup(tmp_path / case.name)

        # Mock: 注入 quantity 字段
        entity_file = (
            project_root / "src" / "main" / "java" / "com" / "example"
            / "demo" / "domain" / "Order.java"
        )
        existing = entity_file.read_text(encoding="utf-8")
        entity_file.write_text(
            existing.replace(
                "    private Double amount;",
                "    private Double amount;\n\n"
                "    private Integer quantity;\n\n"
                "    public Integer getQuantity() { return quantity; }\n"
                "    public void setQuantity(Integer quantity) { this.quantity = quantity; }",
            ),
            encoding="utf-8",
        )

        runner = EvalRunner(tmp_path)
        result = runner.run_case(case, project_root=project_root)
        runner.print_report()
        assert result.passed, f"J-001 断言失败: {result.assertion_results}"

    @pytest.mark.eval
    def test_j002_add_query_method_mock(self, tmp_path: Path):
        """J-002 Mock 路径：注入查询方法验证断言"""
        case = _make_j002_add_query_method()
        project_root = case.setup(tmp_path / case.name)

        repo_file = (
            project_root / "src" / "main" / "java" / "com" / "example"
            / "demo" / "repository" / "OrderRepository.java"
        )
        repo_file.write_text(
            "package com.example.demo.repository;\n\n"
            "import com.example.demo.domain.Order;\n"
            "import org.springframework.data.jpa.repository.JpaRepository;\n"
            "import java.util.List;\n\n"
            "public interface OrderRepository extends JpaRepository<Order, Long> {\n"
            "    List<Order> findByAmountBetween(Double min, Double max);\n"
            "}\n",
            encoding="utf-8",
        )

        runner = EvalRunner(tmp_path)
        result = runner.run_case(case, project_root=project_root)
        runner.print_report()
        assert result.passed, f"J-002 断言失败: {result.assertion_results}"

    @pytest.mark.eval
    def test_j003_add_get_endpoint_mock(self, tmp_path: Path):
        """J-003 Mock 路径：注入 GET 端点验证断言"""
        case = _make_j003_add_endpoint()
        project_root = case.setup(tmp_path / case.name)

        ctrl_file = (
            project_root / "src" / "main" / "java" / "com" / "example"
            / "demo" / "controller" / "OrderController.java"
        )
        existing = ctrl_file.read_text(encoding="utf-8")
        ctrl_file.write_text(
            existing.replace(
                "    @PostMapping\n    public String createOrder() { return \"created\"; }",
                "    @PostMapping\n    public String createOrder() { return \"created\"; }\n\n"
                "    @GetMapping(\"/{id}\")\n"
                "    public String getOrder(@PathVariable Long id) { return \"order:\" + id; }",
            ),
            encoding="utf-8",
        )

        runner = EvalRunner(tmp_path)
        result = runner.run_case(case, project_root=project_root)
        runner.print_report()
        assert result.passed, f"J-003 断言失败: {result.assertion_results}"
