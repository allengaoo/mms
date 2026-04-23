"""
测试套件：CG-017 KafkaEventPublisher.publish_with_retry
"""
import re


class TestCG017Structure:
    """Level 2: 结构契约检查"""

    def test_no_direct_aiokafka_import(self, generated_source: str):
        """禁止直接 import aiokafka（AC-1）"""
        assert "import aiokafka" not in generated_source, (
            "AC-1 违规：禁止在 Service/Infrastructure 直接 import aiokafka"
        )

    def test_has_normalize_record(self, generated_source: str):
        """必须调用 normalize_record（防止 MEM-L-002 静默失败）"""
        assert "normalize_record" in generated_source, (
            "MEM-L-002 违规：发送前必须调用 normalize_record"
        )

    def test_has_tenacity_retry(self, generated_source: str):
        """必须使用 tenacity 重试"""
        assert "tenacity" in generated_source or "AsyncRetrying" in generated_source or "retry" in generated_source.lower(), (
            "缺少 tenacity 重试逻辑"
        )

    def test_has_structlog(self, generated_source: str):
        """必须使用 structlog 记录日志（禁止 print）"""
        assert "structlog" in generated_source or "log." in generated_source, (
            "缺少 structlog 日志记录"
        )
        assert "print(" not in generated_source, "禁止使用 print()"

    def test_has_trace_id(self, generated_source: str):
        """日志必须含 trace_id"""
        assert "trace_id" in generated_source, "日志缺少 trace_id 字段"

    def test_has_publish_with_retry_method(self, generated_source: str):
        """必须有 publish_with_retry 方法"""
        assert "publish_with_retry" in generated_source, "缺少 publish_with_retry 方法"
