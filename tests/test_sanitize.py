"""
test_sanitize.py — SanitizationGate 单元测试（Phase 2 TDD）

覆盖：
  1. 各类敏感凭证的检出（阳性样例）
  2. 正常内容的零误报（阴性样例）
  3. 边界条件（空内容、多模式同时命中、严格模式）
  4. 自定义扩展模式（MMS_SANITIZE_EXTRA 环境变量）

设计原则：
  - 使用 @pytest.mark.parametrize 数据驱动，新增场景只需增加参数行
  - 不依赖任何网络 / LLM / 外部服务
  - 每个用例在 1ms 内完成
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE.parent / "src"))

from mms.core.sanitize import sanitize, sanitize_or_raise


# ─────────────────────────────────────────────────────────────────────────────
# 阳性样例：各类敏感凭证，必须检出
# ─────────────────────────────────────────────────────────────────────────────

_POSITIVE_CASES = [
    # id, input_text, expected_placeholder_substr
    ("sk_openai",
     "OPENAI_KEY=sk-abcdefghijklmnopqrstuvwxyz",   # 纯字母数字，满足 {20,}
     "[REDACTED_API_KEY]"),

    ("sk_dashscope",
     "export DASHSCOPE_API_KEY=sk-abcdefghijklmnopqrstuvwxyz123456",
     "[REDACTED"),

    ("aws_access_key",
     "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE",
     "[REDACTED_AWS_KEY]"),

    ("github_pat",
     "token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef1234",  # 36+ 字符
     "[REDACTED_GH_TOKEN]"),

    ("github_server_token",
     "GH_TOKEN=ghs_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef1234",  # 36+ 字符
     "[REDACTED_GH_TOKEN]"),

    ("huggingface_token",
     "HF_TOKEN=hf_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef",
     "[REDACTED_HF_TOKEN]"),

    ("jwt_bearer",
     "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
     ".eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0"
     ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
     "[REDACTED_JWT]"),

    ("private_ip_192",
     "数据库地址: 192.168.1.100:5432",
     "[REDACTED_PRIVATE_IP]"),

    ("private_ip_10",
     "内网 Redis: 10.0.2.15:6379",
     "[REDACTED_PRIVATE_IP]"),

    ("private_ip_172",
     "部署地址: 172.16.0.1",
     "[REDACTED_PRIVATE_IP]"),

    ("corp_email",
     "联系方式：zhangsan@corp.example",
     "[REDACTED_EMAIL]"),

    ("high_entropy_base64",
     "secret_key = ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop",
     "[REDACTED_SECRET]"),

    ("multi_line_mixed",
     "host=10.0.0.1\nkey=sk-reallyLongKeyHere1234567890abcdef",
     "[REDACTED"),  # 两处都会被检出，只验证 REDACTED 出现
]


@pytest.mark.parametrize("case_id,input_text,expected_substr", _POSITIVE_CASES)
def test_sanitize_detects_sensitive(case_id: str, input_text: str, expected_substr: str):
    """各类敏感凭证必须被检出并替换。"""
    sanitized, count = sanitize(input_text)
    assert count >= 1, f"[{case_id}] 未检出任何敏感信息，count=0"
    assert expected_substr in sanitized, (
        f"[{case_id}] 替换占位符不符合预期。\n"
        f"输入: {input_text!r}\n"
        f"输出: {sanitized!r}\n"
        f"期望包含: {expected_substr!r}"
    )
    assert input_text not in sanitized or count == 0, (
        f"[{case_id}] 输出中仍包含原始敏感信息"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 阴性样例：正常内容，不应误报（假阳性率 = 0%）
# ─────────────────────────────────────────────────────────────────────────────

_NEGATIVE_CASES = [
    # id, input_text
    ("public_ip",
     "外部 IP：8.8.8.8（Google DNS）"),

    ("normal_url",
     "文档地址：https://docs.example.com/api"),

    ("markdown_code",
     "```python\ndef create_order(amount: float) -> dict:\n    return {}\n```"),

    ("short_base64",
     "签名摘要：YWJj（仅 3 个字符，低于阈值）"),

    ("localhost",
     "本地调试地址：127.0.0.1:8080"),

    ("memory_id",
     "记忆节点：MEM-L-001，关联记忆：AD-001"),

    ("email_public_domain",
     "邮件：user@gmail.com 或 admin@example.org"),

    ("version_string",
     "fastapi>=0.100.0,sqlmodel>=0.0.14"),

    ("sha256_prefix",
     "fingerprint: sha256:abcdef1234567890（指纹前缀非 API Key）"),

    ("chinese_text",
     "这是一段普通的中文文本，不包含任何敏感信息。"),
]


@pytest.mark.parametrize("case_id,input_text", _NEGATIVE_CASES)
def test_sanitize_no_false_positive(case_id: str, input_text: str):
    """正常内容不应触发误报（假阳性率 = 0%）。"""
    sanitized, count = sanitize(input_text)
    assert count == 0, (
        f"[{case_id}] 误报！正常内容被错误脱敏。count={count}\n"
        f"输入: {input_text!r}\n"
        f"输出: {sanitized!r}"
    )
    assert sanitized == input_text, "内容不应被修改"


# ─────────────────────────────────────────────────────────────────────────────
# 边界条件
# ─────────────────────────────────────────────────────────────────────────────

class TestSanitizeBoundary:
    """边界条件测试。"""

    def test_empty_string(self):
        sanitized, count = sanitize("")
        assert sanitized == ""
        assert count == 0

    def test_whitespace_only(self):
        sanitized, count = sanitize("   \n  ")
        assert count == 0

    def test_multiple_keys_in_one_text(self):
        """单段文本中包含多处敏感信息，每处都应被替换。"""
        text = (
            "DB=10.0.0.1\n"
            "KEY=sk-reallyLongApiKeyHere12345678901234\n"
            "TOKEN=AKIAIOSFODNN7EXAMPLE\n"
        )
        sanitized, count = sanitize(text)
        assert count >= 3, f"期望至少 3 处检出，实际 count={count}"
        assert "10.0" not in sanitized or "[REDACTED_PRIVATE_IP]" in sanitized
        assert "[REDACTED_AWS_KEY]" in sanitized

    def test_path_hint_does_not_affect_result(self):
        """path_hint 只影响日志，不影响脱敏结果。"""
        text = "key=AKIAIOSFODNN7EXAMPLE"
        result1, _ = sanitize(text, path_hint="")
        result2, _ = sanitize(text, path_hint="docs/memory/shared/MEM-001.md")
        assert result1 == result2

    def test_idempotent(self):
        """对已脱敏内容再次脱敏，结果不变（幂等性）。"""
        text = "key=sk-reallyLongApiKeyHere1234567890abc"
        first, _ = sanitize(text)
        second, count2 = sanitize(first)
        assert first == second
        assert count2 == 0, "二次脱敏不应再次触发替换"

    def test_content_preserved_around_redaction(self):
        """脱敏只替换敏感部分，周围内容保留。"""
        text = "前缀文字 AKIAIOSFODNN7EXAMPLE 后缀文字"
        sanitized, count = sanitize(text)
        assert "前缀文字" in sanitized
        assert "后缀文字" in sanitized
        assert count >= 1


# ─────────────────────────────────────────────────────────────────────────────
# 严格模式（MMS_SANITIZE_STRICT=1）
# ─────────────────────────────────────────────────────────────────────────────

class TestSanitizeStrictMode:
    """严格模式：发现敏感信息时抛出 ValueError 而非静默替换。"""

    def test_strict_mode_raises_on_sensitive(self, monkeypatch):
        monkeypatch.setenv("MMS_SANITIZE_STRICT", "1")
        with pytest.raises(ValueError, match="SanitizationGate"):
            sanitize_or_raise("key=AKIAIOSFODNN7EXAMPLE", path_hint="test.md")

    def test_strict_mode_passes_clean_content(self, monkeypatch):
        monkeypatch.setenv("MMS_SANITIZE_STRICT", "1")
        result = sanitize_or_raise("这是干净的内容，无敏感信息。")
        assert result == "这是干净的内容，无敏感信息。"

    def test_normal_mode_no_raise(self, monkeypatch):
        monkeypatch.delenv("MMS_SANITIZE_STRICT", raising=False)
        result = sanitize_or_raise("key=AKIAIOSFODNN7EXAMPLE")
        assert "[REDACTED_AWS_KEY]" in result


# ─────────────────────────────────────────────────────────────────────────────
# 自定义扩展模式（MMS_SANITIZE_EXTRA 环境变量）
# ─────────────────────────────────────────────────────────────────────────────

class TestSanitizeCustomPatterns:
    """验证通过环境变量动态追加自定义检测模式。"""

    def test_custom_pattern_detected(self, monkeypatch):
        """注入自定义模式后，对应内容被检出。"""
        import mms.core.sanitize as _mod
        _mod._compiled = None  # 重置缓存，强制重新编译

        monkeypatch.setenv("MMS_SANITIZE_EXTRA", r"CORP_TOKEN_[A-Z0-9]{8,}")
        _mod._compiled = None  # 重置缓存

        text = "认证：CORP_TOKEN_ABCD1234"
        sanitized, count = sanitize(text)

        _mod._compiled = None  # 清理环境，避免影响其他测试

        assert count >= 1, f"自定义模式未生效，count={count}"
        assert "CORP_TOKEN_ABCD1234" not in sanitized

    def test_invalid_custom_pattern_ignored(self, monkeypatch):
        """无效的自定义正则不应导致崩溃。"""
        import mms.core.sanitize as _mod
        _mod._compiled = None

        monkeypatch.setenv("MMS_SANITIZE_EXTRA", r"[invalid regex((")
        _mod._compiled = None

        # 不应抛出异常，正常处理（跳过无效模式）
        try:
            sanitize("普通文本")
        except re.error:
            pytest.fail("无效正则模式导致了崩溃")
        finally:
            _mod._compiled = None
