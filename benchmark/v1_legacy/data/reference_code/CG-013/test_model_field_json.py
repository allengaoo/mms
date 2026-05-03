"""
测试套件：CG-013 ObjectTypeDef.metadata_json 字段
"""
import re


class TestCG013Structure:
    """Level 2: 结构契约检查"""

    def test_uses_sa_column_json(self, generated_source: str):
        """必须使用 sa_column=Column(JSON)"""
        assert "sa_column" in generated_source and "JSON" in generated_source, (
            "必须使用 sa_column=Column(JSON) 定义 JSON 列（MySQL 兼容）"
        )

    def test_no_json_type(self, generated_source: str):
        """禁止使用 JSON() 或 JsonType 等错误用法"""
        assert "JSON()" not in generated_source, "禁止使用 JSON()（应使用 Column(JSON)）"
        assert "JsonType" not in generated_source, "禁止使用 JsonType"

    def test_has_optional(self, generated_source: str):
        """字段应该是 Optional（允许 NULL）"""
        assert "Optional" in generated_source or "= None" in generated_source, (
            "metadata_json 应为 Optional（允许 NULL）"
        )

    def test_has_metadata_json_field(self, generated_source: str):
        """必须有 metadata_json 字段定义"""
        assert "metadata_json" in generated_source, "缺少 metadata_json 字段"
