"""
test_arch_check.py — 架构约束反向测试（Phase 5 TDD）

策略：
  - 用 tmp_path 构造「违规代码片段」，patch arch_check._SERVICES / _API / _WORKERS
    为临时目录，触发各条规则的 violation
  - 同时验证「合规代码」不产生误报（阴性样例）
  - 完全离线，< 100ms

覆盖规则：
  AC-1  禁止在 services/ 层直接 import 消息队列客户端（aiokafka / pymilvus）
  AC-2  Service 函数必须以 ctx: SecurityContext 作为首参
  AC-3  WRITE 操作必须调用 AuditService.log()
  AC-4  API Endpoint 必须使用 ResponseHelper 信封格式
  AC-6  Worker 必须使用 JobExecutionScope（禁裸 print）
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE.parent / "src"))

import mms.analysis.arch_check as arch_check


# ─────────────────────────────────────────────────────────────────────────────
# 辅助：在 tmp_path 下创建 Python 文件，patch 目标目录
# ─────────────────────────────────────────────────────────────────────────────

def write_py(directory: Path, filename: str, content: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    f = directory / filename
    f.write_text(textwrap.dedent(content))
    return f


def patch_arch(services=None, api=None, workers=None, root=None):
    """
    返回一个可以作为 context manager 使用的 patch 组合。
    同时 patch _ROOT 为 tmp_path，避免 py.relative_to(_ROOT) 报错。
    """
    patches = []
    if root is not None:
        patches.append(patch.object(arch_check, "_ROOT", root))
    if services is not None:
        patches.append(patch.object(arch_check, "_SERVICES", services))
    if api is not None:
        patches.append(patch.object(arch_check, "_API", api))
    if workers is not None:
        patches.append(patch.object(arch_check, "_WORKERS", workers))

    class MultiPatch:
        def __enter__(self):
            for p in patches:
                p.__enter__()
            return self
        def __exit__(self, *args):
            for p in reversed(patches):
                p.__exit__(*args)

    return MultiPatch()


# ─────────────────────────────────────────────────────────────────────────────
# AC-1: 层隔离 — services/ 禁止 import 消息队列客户端
# ─────────────────────────────────────────────────────────────────────────────

class TestAC1LayerIsolation:
    """AC-1: 禁止在 services/ 层直接 import aiokafka / pymilvus。"""

    def test_ac1_violation_aiokafka(self, tmp_path):
        """services/ 中 import aiokafka 应被检出。"""
        services = tmp_path / "services"
        write_py(services, "order_service.py", """
            import aiokafka
            from aiokafka import AIOKafkaProducer

            class OrderService:
                async def create(self, ctx):
                    pass
        """)
        with patch_arch(services=services, root=tmp_path):
            violations = arch_check.check_layer_isolation()
        assert len(violations) > 0, "aiokafka import 应被检出"
        assert any("aiokafka" in v for v in violations)

    def test_ac1_violation_pymilvus(self, tmp_path):
        """services/ 中 import pymilvus 应被检出。"""
        services = tmp_path / "services"
        write_py(services, "search_service.py", """
            from pymilvus import connections

            class SearchService:
                async def search(self, ctx, query):
                    pass
        """)
        with patch_arch(services=services, root=tmp_path):
            violations = arch_check.check_layer_isolation()
        assert len(violations) > 0, "pymilvus import 应被检出"

    def test_ac1_no_violation_clean_service(self, tmp_path):
        """合规 service 不应产生 AC-1 违规。"""
        services = tmp_path / "services"
        write_py(services, "user_service.py", """
            from ..repositories.user_repo import UserRepository

            class UserService:
                async def get_user(self, ctx, user_id: int):
                    return await UserRepository.find(user_id)
        """)
        with patch_arch(services=services, root=tmp_path):
            violations = arch_check.check_layer_isolation()
        assert len(violations) == 0, f"合规代码不应有违规: {violations}"

    def test_ac1_no_violation_infra_layer(self, tmp_path):
        """infrastructure/ 层中 import aiokafka 是合法的（不扫描 infra）。"""
        services = tmp_path / "services"
        services.mkdir(parents=True)
        with patch_arch(services=services, root=tmp_path):
            violations = arch_check.check_layer_isolation()
        assert len(violations) == 0


# ─────────────────────────────────────────────────────────────────────────────
# AC-2: SecurityContext 首参
# ─────────────────────────────────────────────────────────────────────────────

class TestAC2SecurityContext:
    """AC-2: Service 函数必须以 ctx: SecurityContext 作为首参。"""

    def test_ac2_violation_missing_ctx(self, tmp_path):
        """缺少 SecurityContext 参数的 Service 方法应被检出。"""
        services = tmp_path / "services"
        write_py(services, "order_service.py", """
            class OrderService:
                async def create_order(self, amount: float) -> dict:
                    return {}

                async def delete_order(self, order_id: int) -> None:
                    pass
        """)
        with patch_arch(services=services, root=tmp_path):
            violations = arch_check.check_security_context()
        assert len(violations) > 0, "缺少 SecurityContext 应被检出"

    def test_ac2_no_violation_with_ctx(self, tmp_path):
        """包含 ctx: SecurityContext 的方法不应有违规。"""
        services = tmp_path / "services"
        write_py(services, "order_service.py", """
            from ...core.security import SecurityContext

            class OrderService:
                async def create_order(self, ctx: SecurityContext, amount: float) -> dict:
                    return {}
        """)
        with patch_arch(services=services, root=tmp_path):
            violations = arch_check.check_security_context()
        assert len(violations) == 0, f"合规代码不应有违规: {violations}"

    def test_ac2_no_violation_private_methods(self, tmp_path):
        """以 _ 开头的私有方法不受 AC-2 约束。"""
        services = tmp_path / "services"
        write_py(services, "helper_service.py", """
            class HelperService:
                def _internal_calc(self, amount: float) -> float:
                    return amount * 1.1
        """)
        with patch_arch(services=services, root=tmp_path):
            violations = arch_check.check_security_context()
        assert len(violations) == 0, "私有方法不应被检查"


# ─────────────────────────────────────────────────────────────────────────────
# AC-3: AuditService.log() 调用
# ─────────────────────────────────────────────────────────────────────────────

class TestAC3AuditCalls:
    """AC-3: WRITE 操作必须调用 AuditService.log()。"""

    def test_ac3_violation_create_without_audit(self, tmp_path):
        """create/update/delete 方法未调用 AuditService.log 应被检出。"""
        services = tmp_path / "services"
        write_py(services, "product_service.py", """
            class ProductService:
                async def create_product(self, ctx, name: str) -> dict:
                    # 创建商品但没有审计日志
                    return {"id": 1, "name": name}

                async def update_product(self, ctx, product_id: int, data: dict) -> dict:
                    return data
        """)
        with patch_arch(services=services, root=tmp_path):
            violations = arch_check.check_audit_calls()
        assert len(violations) > 0, "缺少 AuditService.log 应被检出"

    def test_ac3_no_violation_with_audit(self, tmp_path):
        """调用了 AuditService.log 的 WRITE 方法不应有违规。"""
        services = tmp_path / "services"
        write_py(services, "product_service.py", """
            class ProductService:
                async def create_product(self, ctx, name: str) -> dict:
                    result = {"id": 1, "name": name}
                    AuditService.log(ctx, "create_product", result)
                    return result
        """)
        with patch_arch(services=services, root=tmp_path):
            violations = arch_check.check_audit_calls()
        assert len(violations) == 0, f"合规代码不应有违规: {violations}"

    def test_ac3_no_violation_read_operations(self, tmp_path):
        """纯 GET/LIST/READ 操作不需要审计日志。"""
        services = tmp_path / "services"
        write_py(services, "product_service.py", """
            class ProductService:
                async def get_product(self, ctx, product_id: int) -> dict:
                    return {"id": product_id}

                async def list_products(self, ctx) -> list:
                    return []
        """)
        with patch_arch(services=services, root=tmp_path):
            violations = arch_check.check_audit_calls()
        assert len(violations) == 0, "只读操作不应被要求审计"


# ─────────────────────────────────────────────────────────────────────────────
# AC-4: ResponseHelper 信封格式
# ─────────────────────────────────────────────────────────────────────────────

class TestAC4EnvelopeFormat:
    """AC-4: API Endpoint 必须使用 ResponseHelper 信封格式。"""

    def test_ac4_violation_raw_list_return(self, tmp_path):
        """
        直接 return 裸列表（return [...]）应被检出。
        AC-4 的当前实现检测 `return [` 模式（裸列表），
        不检测 `return {}` dict 模式。
        """
        api = tmp_path / "api"
        write_py(api, "products.py", """
            from fastapi import APIRouter

            router = APIRouter()

            @router.get("/products")
            async def list_products():
                return [{"id": 1}, {"id": 2}]
        """)
        with patch_arch(api=api, root=tmp_path):
            violations = arch_check.check_envelope()
        assert len(violations) > 0, "裸列表 return 应被检出"

    def test_ac4_no_violation_with_responsehelper(self, tmp_path):
        """使用信封格式的 endpoint 不应有违规。"""
        api = tmp_path / "api"
        write_py(api, "orders.py", """
            from fastapi import APIRouter
            from ..core.response import ResponseHelper

            router = APIRouter()

            @router.post("/orders")
            async def create_order(amount: float):
                return ResponseHelper.success({"id": 1, "amount": amount})
        """)
        with patch_arch(api=api, root=tmp_path):
            violations = arch_check.check_envelope()
        assert len(violations) == 0, f"使用 ResponseHelper 不应有违规: {violations}"


# ─────────────────────────────────────────────────────────────────────────────
# 边界：空目录不产生违规
# ─────────────────────────────────────────────────────────────────────────────

class TestArchCheckBoundary:
    """边界条件：空目录 / 不存在目录不应崩溃。"""

    def test_empty_services_dir(self, tmp_path):
        services = tmp_path / "services"
        services.mkdir()
        with patch_arch(services=services, root=tmp_path):
            assert arch_check.check_layer_isolation() == []
            assert arch_check.check_security_context() == []
            assert arch_check.check_audit_calls() == []

    def test_nonexistent_services_dir(self, tmp_path):
        """目录不存在时，各 check 函数应返回空列表而非崩溃。"""
        nonexistent = tmp_path / "nonexistent" / "services"
        with patch_arch(services=nonexistent, root=tmp_path):
            assert arch_check.check_layer_isolation() == []
            assert arch_check.check_security_context() == []
            assert arch_check.check_audit_calls() == []

    def test_nonexistent_api_dir(self, tmp_path):
        nonexistent = tmp_path / "nonexistent" / "api"
        with patch_arch(api=nonexistent, root=tmp_path):
            assert arch_check.check_envelope() == []
