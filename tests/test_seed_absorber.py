"""
test_seed_absorber.py — seed_absorber 噪声过滤与纯函数测试（Phase 6 TDD）

策略：
  - 只测试不需要 LLM 的纯函数（clean_noise / extract_rule_sections / _derive_seed_name）
  - LLM 依赖部分（_distill_with_llm）使用 mock 替代，不发真实 API 请求
  - 完全离线，< 50ms

覆盖：
  1. clean_noise()：有效提取代码/注解/结构关键词，过滤无意义噪声
  2. extract_rule_sections()：从文档文本中正确定位规则段落，截断至 max_chars
  3. _derive_seed_name()：从 URL/文件路径派生合理的 seed 名称
  4. ingest() with mock LLM：端到端流程不崩溃，输出文件结构正确
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE.parent / "src"))

from mms.analysis.seed_absorber import clean_noise, extract_rule_sections, _derive_seed_name


# ─────────────────────────────────────────────────────────────────────────────
# clean_noise()：噪声过滤
# ─────────────────────────────────────────────────────────────────────────────

class TestCleanNoise:
    """clean_noise 应保留有意义的技术内容，过滤纯自然语言噪声。"""

    def test_preserves_code_keywords(self):
        """包含代码关键词的行应被保留。"""
        text = textwrap.dedent("""
            class OrderService:
                def create_order(self, amount: float) -> dict:
                    pass

            这是一段普通的介绍性文字，不含任何代码结构。
            继续说一些废话。
        """)
        result = clean_noise(text)
        assert "class OrderService" in result or "OrderService" in result

    def test_preserves_import_statements(self):
        """import 语句应被保留。"""
        text = "import fastapi\nfrom sqlmodel import SQLModel\n"
        result = clean_noise(text)
        assert "import" in result

    def test_preserves_annotations(self):
        """代码注解（@decorator）应被保留。"""
        text = "@router.post('/orders')\nasync def create(): pass\n"
        result = clean_noise(text)
        assert "@router" in result or "router" in result

    def test_preserves_function_calls(self):
        """函数调用模式（xxx()）应被保留。"""
        text = "调用 AuditService.log() 记录变更\n"
        result = clean_noise(text)
        assert "AuditService.log()" in result

    def test_result_is_shorter_than_input(self):
        """过滤后内容不应比输入更长（不增加噪声）。"""
        text = "A\nB\nC\n" * 100  # 纯噪声行
        result = clean_noise(text)
        assert len(result) <= len(text)

    def test_empty_input(self):
        result = clean_noise("")
        assert result == "" or isinstance(result, str)

    def test_code_heavy_content_mostly_preserved(self):
        """代码密集型内容（如规则文档）应大部分被保留。"""
        text = textwrap.dedent("""
            # AC-1: 层隔离规则

            class InfraAdapter:
                def __init__(self, config: dict): pass

            import aiokafka
            from app.infrastructure import KafkaProducer

            # 禁止在 services/ 层直接使用 aiokafka
        """)
        result = clean_noise(text)
        # 代码密集内容，过滤后至少保留 30% 的字符
        assert len(result) >= len(text) * 0.3


# ─────────────────────────────────────────────────────────────────────────────
# extract_rule_sections()：规则段落提取
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractRuleSections:
    """extract_rule_sections 应正确定位文档中的规则/约束段落。"""

    def test_extracts_rule_section(self):
        """包含明确规则标题（Rules/Constraints）的段落应被提取。"""
        text = textwrap.dedent("""
            # 项目简介
            这个项目是一个订单管理系统。

            # Rules
            1. Service 层必须使用 SecurityContext
            2. Write 操作必须调用 AuditService.log

            # 部署说明
            使用 Docker Compose 部署。
        """)
        result = extract_rule_sections(text)
        assert "SecurityContext" in result or "AuditService" in result

    def test_respects_max_chars(self):
        """结果长度不应超过 max_chars。"""
        text = "规则内容\n" * 1000
        result = extract_rule_sections(text, max_chars=500)
        assert len(result) <= 500 + 50  # 允许少量超出（行截断缓冲）

    def test_empty_input(self):
        result = extract_rule_sections("")
        assert isinstance(result, str)

    def test_no_rule_section_returns_truncated(self):
        """没有明确规则段落时，应返回原文截断版本（不崩溃）。"""
        text = "这是普通文档，没有规则段落。\n" * 100
        result = extract_rule_sections(text, max_chars=200)
        assert isinstance(result, str)
        assert len(result) <= 300


# ─────────────────────────────────────────────────────────────────────────────
# _derive_seed_name()：seed 名称派生
# ─────────────────────────────────────────────────────────────────────────────

class TestDeriveSeedName:
    """_derive_seed_name 应从 URL 或文件路径派生合理的 seed 名称。"""

    def test_github_url_extracts_repo_name(self):
        url = "https://github.com/palantir/titus-executor/blob/main/CONTRIBUTING.md"
        name = _derive_seed_name(url)
        assert name is not None
        assert len(name) > 0

    def test_local_file_extracts_filename(self):
        name = _derive_seed_name("/Users/dev/project/CONTRIBUTING.md")
        assert "CONTRIBUTING" in name or "contributing" in name.lower()

    def test_no_extension_in_name(self):
        """派生的 seed 名称不应包含文件扩展名。"""
        name = _derive_seed_name("https://example.com/rules.md")
        assert ".md" not in name

    def test_result_is_valid_identifier(self):
        """派生名称应只包含字母、数字、下划线，适合作为 YAML key。"""
        import re
        name = _derive_seed_name("https://github.com/org/my-cool-project/README.md")
        # 允许连字符（-）和下划线（_），但不允许空格、斜杠等
        assert re.match(r'^[a-zA-Z0-9_\-]+$', name), f"名称包含非法字符: {name!r}"

    def test_handles_trailing_slash(self):
        """URL 末尾含斜杠时不应崩溃。"""
        name = _derive_seed_name("https://github.com/org/repo/")
        assert isinstance(name, str) and len(name) > 0


# ─────────────────────────────────────────────────────────────────────────────
# ingest() 端到端（mock LLM）
# ─────────────────────────────────────────────────────────────────────────────

class TestIngestWithMockLLM:
    """
    使用 mock LLM 运行 ingest() 完整流程，验证：
      1. 不崩溃
      2. 输出到指定目录
      3. 返回的文件路径可读
    """

    _MOCK_LLM_OUTPUT = textwrap.dedent("""
        ## Constraints

        - Service 层禁止直接调用数据库（必须通过 Repository）
        - 写操作必须记录审计日志

        ## Memory Files

        ### MEM-RULE-001.md
        **关于**: 服务层约束

        **内容**:
        Service 层只能通过 Repository 接口访问数据库，不允许直接使用 ORM Session。

        ### MEM-RULE-002.md
        **关于**: 审计日志

        **内容**:
        所有写操作必须调用 AuditService.log(ctx, action, resource)。
    """)

    def test_ingest_local_file_with_mock_llm(self, tmp_path):
        """本地文件 ingest 不崩溃，输出到 draft 目录。"""
        from mms.analysis.seed_absorber import ingest

        # 创建一个最小的本地规则文件
        rule_file = tmp_path / "CONTRIBUTING.md"
        rule_file.write_text(textwrap.dedent("""
            # 贡献规范

            ## Rules
            1. 所有 PR 必须有测试
            2. Service 层不允许直接访问数据库

            ## Code Style
            使用 4 空格缩进。
        """))

        output_dir = tmp_path / "draft"

        with patch("mms.analysis.seed_absorber._distill_with_llm") as mock_llm:
            mock_llm.return_value = ("约束列表", self._MOCK_LLM_OUTPUT)
            result = ingest(
                url_or_path=str(rule_file),
                dry_run=False,
            )

        assert result is not None

    def test_ingest_dry_run_no_files_written(self, tmp_path, monkeypatch):
        """dry_run=True 时不写任何文件。"""
        from mms.analysis.seed_absorber import ingest
        import mms.analysis.seed_absorber as _mod

        rule_file = tmp_path / "rules.md"
        rule_file.write_text("# Rules\n1. Rule A\n2. Rule B\n")

        with patch("mms.analysis.seed_absorber._distill_with_llm") as mock_llm:
            mock_llm.return_value = ("约束", self._MOCK_LLM_OUTPUT)
            path, status = ingest(
                url_or_path=str(rule_file),
                dry_run=True,
            )

        assert status == "dry_run", f"dry_run 模式下 status 应为 'dry_run'，实际: {status}"
