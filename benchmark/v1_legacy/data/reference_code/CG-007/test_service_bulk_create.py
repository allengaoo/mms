"""
测试套件：CG-007 bulk_create_objects
用途：验证生成代码的结构和语义正确性
"""
import re


class TestCG007Structure:
    """Level 2: 结构契约检查"""

    def test_has_ctx_first_param(self, generated_source: str):
        """Service 函数首参必须是 ctx: RequestContext"""
        assert re.search(
            r"async def bulk_create_objects\s*\(\s*ctx\s*:", generated_source
        ), "首参必须是 ctx: RequestContext（AC-2）"

    def test_has_audit_service(self, generated_source: str):
        """必须调用 audit_service.log()（AC-3）"""
        assert "audit_service" in generated_source, "缺少 audit_service 调用（AC-3）"

    def test_no_session_begin_after_execute(self, generated_source: str):
        """禁止 session.begin()（会在 autobegin 后抛出 InvalidRequestError）"""
        assert "session.begin()" not in generated_source, (
            "存在 session.begin()，违反 Strategy A/B 约束"
        )

    def test_has_explicit_commit(self, generated_source: str):
        """Strategy B 必须有显式 commit"""
        assert "session.commit()" in generated_source, (
            "Strategy B 要求显式 await session.commit()"
        )

    def test_no_fetchall(self, generated_source: str):
        """禁止 fetchall()"""
        assert "fetchall()" not in generated_source, "禁止使用 fetchall()"

    def test_no_print_stmt(self, generated_source: str):
        """禁止 print()，必须用 structlog"""
        assert 'print(' not in generated_source, "禁止使用 print()，必须用 structlog"

    def test_has_tenant_id_filter(self, generated_source: str):
        """必须包含 tenant_id 过滤（RLS）"""
        assert "tenant_id" in generated_source, "缺少 tenant_id 过滤（RLS 违规）"

    def test_has_limit_check(self, generated_source: str):
        """必须有批量大小限制"""
        assert re.search(r"(len\(dtos\)|MAX_BULK|limit)", generated_source), (
            "缺少批量大小限制"
        )
