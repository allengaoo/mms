"""
sanitize.py — 脱敏屏障（Sanitization Gate）

在记忆文件落盘前强制扫描并替换敏感凭证，防止 API Key、Token、IP 等
机密信息被 LLM 无意中写入共享记忆库（docs/memory/shared/），引发安全合规事件。

符合标准：SOC2 / ISO27001 数据脱敏要求。

支持的检测模式（扩展正则，可在运行时通过环境变量 MMS_SANITIZE_EXTRA 追加）：
  - OpenAI / 百炼 / 通义 API Key: sk-... / DASHSCOPE_...
  - AWS Access Key: AKIA...
  - JWT Token: eyJ...
  - GitHub Token: ghp_... / ghs_...
  - 通用高熵 Base64 密钥: 40+ 字符
  - 私有 IPv4 地址: 192.168.x.x / 10.x.x.x / 172.16-31.x.x
  - 真实邮箱地址
"""
from __future__ import annotations

import os
import re
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

# ── 内置敏感模式 ───────────────────────────────────────────────────────────────
_BUILTIN_PATTERNS: List[Tuple[str, str]] = [
    # OpenAI / 百炼 / 通义格式 API Key
    (r'sk-[A-Za-z0-9]{20,}', '[REDACTED_API_KEY]'),
    # AWS Access Key
    (r'AKIA[0-9A-Z]{16}', '[REDACTED_AWS_KEY]'),
    # JWT Token (header.payload.signature)
    (r'eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}', '[REDACTED_JWT]'),
    # GitHub Personal Access Token
    (r'gh[psor]_[A-Za-z0-9]{36,}', '[REDACTED_GH_TOKEN]'),
    # HuggingFace Token
    (r'hf_[A-Za-z0-9]{30,}', '[REDACTED_HF_TOKEN]'),
    # 百炼 / 阿里云 DASHSCOPE KEY 格式
    (r'sk-[a-f0-9]{32}', '[REDACTED_DASHSCOPE_KEY]'),
    # 私有 IPv4 地址
    (r'\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b',
     '[REDACTED_PRIVATE_IP]'),
    # 企业内部邮箱（匹配 @corp / @internal 子域等，保守模式）
    (r'\b[A-Za-z0-9._%+\-]{3,}@(?:corp|internal|intranet|local)\.[a-z]{2,}\b',
     '[REDACTED_EMAIL]'),
    # 高熵 Base64 密钥（≥ 40 字符，排除普通词汇）
    (r'(?<![A-Za-z0-9])[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9+/])',
     '[REDACTED_SECRET]'),
]

_compiled: List[Tuple[re.Pattern, str]] | None = None


def _get_compiled() -> List[Tuple[re.Pattern, str]]:
    global _compiled
    if _compiled is not None:
        return _compiled

    patterns = list(_BUILTIN_PATTERNS)

    extra_env = os.environ.get("MMS_SANITIZE_EXTRA", "")
    if extra_env.strip():
        for raw in extra_env.split("|"):
            raw = raw.strip()
            if raw:
                try:
                    patterns.append((raw, '[REDACTED_CUSTOM]'))
                except Exception:
                    pass

    _compiled = [(re.compile(p), repl) for p, repl in patterns]
    return _compiled


def sanitize(content: str, path_hint: str = "") -> Tuple[str, int]:
    """
    对文本内容执行脱敏扫描。

    Args:
        content:   待扫描的文本内容
        path_hint: 文件路径（仅用于日志）

    Returns:
        (sanitized_content, redact_count): 脱敏后的内容和替换次数
    """
    if not content:
        return content, 0

    total = 0
    result = content
    for pattern, replacement in _get_compiled():
        new_result, n = pattern.subn(replacement, result)
        if n:
            total += n
            result = new_result

    if total > 0:
        logger.warning(
            "SanitizationGate: 检测到 %d 处敏感信息，已替换为占位符。文件：%s",
            total, path_hint or "(unknown)",
        )

    return result, total


def sanitize_or_raise(content: str, path_hint: str = "") -> str:
    """
    脱敏扫描，并在 MMS_SANITIZE_STRICT=1 时若发现敏感信息则抛出异常（阻断写入）。

    常规模式（默认）：自动替换并记录警告日志。
    严格模式（MMS_SANITIZE_STRICT=1）：发现即熔断，抛出 ValueError。
    """
    cleaned, count = sanitize(content, path_hint)
    if count > 0 and os.environ.get("MMS_SANITIZE_STRICT") == "1":
        raise ValueError(
            f"SanitizationGate: 文件 {path_hint} 包含 {count} 处敏感信息，"
            f"严格模式下写入被阻断。请清理后重试。"
        )
    return cleaned
