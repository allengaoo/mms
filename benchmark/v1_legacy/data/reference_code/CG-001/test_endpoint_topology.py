"""
测试套件：CG-001 GET /objects/{object_id}/topology
用途：验证生成代码的结构和语义正确性（4 级评估）
"""
import ast
import re
from pathlib import Path


def _load_source(path: str) -> str:
    """加载待评估的源码字符串"""
    return Path(path).read_text(encoding="utf-8")


def _parse_tree(source: str) -> ast.Module:
    return ast.parse(source)


class TestCG001Structure:
    """Level 2: 结构契约检查（不需要运行环境）"""

    def test_has_get_router_decorator(self, generated_source: str):
        """必须有 @router.get 装饰器"""
        assert "@router.get" in generated_source, "缺少 @router.get 装饰器"

    def test_has_response_model(self, generated_source: str):
        """路由装饰器必须包含 response_model 参数"""
        assert "response_model" in generated_source, "缺少 response_model 参数"

    def test_has_require_permission(self, generated_source: str):
        """必须有权限守卫"""
        assert (
            "require_permission" in generated_source
            or "ont:object:view" in generated_source
        ), "缺少权限守卫 require_permission"

    def test_has_depends_get_context(self, generated_source: str):
        """SecurityContext 必须通过 Depends 注入"""
        assert "Depends" in generated_source and (
            "get_context" in generated_source or "get_current_user" in generated_source
        ), "SecurityContext 未通过 Depends 注入"

    def test_no_bare_return(self, generated_source: str):
        """禁止裸返回列表或字典"""
        assert "return []" not in generated_source, "存在裸列表返回"
        assert re.search(r"return \{\}", generated_source) is None, "存在裸字典返回"

    def test_function_signature(self, generated_source: str):
        """端点函数必须是 async def"""
        assert "async def get_object_topology" in generated_source, (
            "缺少 async def get_object_topology 函数"
        )

    def test_no_forbidden_imports(self, generated_source: str):
        """禁止直接 import 基础设施层"""
        forbidden = ["import pymilvus", "import aiokafka", "import elasticsearch"]
        for f in forbidden:
            assert f not in generated_source, f"存在禁止的 import: {f}"


class TestCG001ArchConstraints:
    """Level 3: 架构约束检查（需要 arch_check.py 支持）"""

    def test_ac4_envelope_format(self, generated_source: str):
        """AC-4：必须使用信封格式（success_response/ResponseHelper）"""
        assert (
            "success_response" in generated_source
            or "ResponseHelper" in generated_source
            or "ResponseSchema" in generated_source
        ), "AC-4 违规：缺少 ResponseHelper/success_response 信封"

    def test_no_session_in_endpoint(self, generated_source: str):
        """Endpoint 层不得直接操作 session"""
        assert "session.execute" not in generated_source, (
            "Endpoint 层不得直接调用 session.execute（业务下沉到 Service 层）"
        )
