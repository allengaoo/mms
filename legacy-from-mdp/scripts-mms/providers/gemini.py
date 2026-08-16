"""
Google Gemini LLM 适配器

使用 Google Generative Language API（REST），纯 stdlib，无第三方依赖。

支持模型：
  - gemini-2.5-pro    DAG 编排 / 代码语义评审（强推理，1M 上下文）
  - gemini-2.5-flash  快速任务（成本低）
  - gemini-2.0-flash  稳定版本

认证：
  优先读取环境变量 GOOGLE_API_KEY，
  其次读取 .env.memory 文件中的同名配置。

端点：
  https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent

健康检查：
  GET /v1beta/models（携带 ?key= 参数），返回 200 视为可用。
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from .base import LLMProvider, ProviderUnavailableError

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

try:
    import sys as _sys
    import os as _os
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from mms_config import cfg as _cfg  # type: ignore[import]
except Exception:
    _cfg = None  # type: ignore[assignment]

# fallback: config.yaml → llm.google.connect_timeout_seconds (default=8)
_CONNECT_TIMEOUT = int(getattr(_cfg, "llm_google_connect_timeout", 8)) if _cfg else 8
# fallback: config.yaml → llm.google.generate_timeout_seconds (default=180)
_GENERATE_TIMEOUT = int(getattr(_cfg, "llm_google_generate_timeout", 180)) if _cfg else 180
# fallback: config.yaml → llm.google.min_output_tokens (default=8192)
_MIN_OUTPUT_TOKENS = int(getattr(_cfg, "llm_google_min_output_tokens", 8192)) if _cfg else 8192

# .env.memory 路径（parents[3] = 项目根）
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env.memory"
_ENV_CACHE: Optional[dict] = None


def _load_env_file() -> dict:
    global _ENV_CACHE
    if _ENV_CACHE is not None:
        return _ENV_CACHE
    result: dict = {}
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip().strip('"').strip("'")
    _ENV_CACHE = result
    return result


def _get_config(key: str, default: str = "") -> str:
    val = os.environ.get(key, "").strip()
    if val:
        return val
    return _load_env_file().get(key, default)


def _load_api_key() -> str:
    key = _get_config("GOOGLE_API_KEY", "")
    if not key:
        raise ProviderUnavailableError(
            "GOOGLE_API_KEY 未配置。\n"
            "请在 .env.memory 中添加：GOOGLE_API_KEY=AIza..."
        )
    return key


class GeminiProvider(LLMProvider):
    """
    Google Gemini API 适配器。

    用途：
      - DAG 编排（mms unit generate）→ gemini-2.5-pro
      - 代码语义评审（mms unit compare 内置）→ gemini-2.5-pro
    """

    def __init__(
        self,
        model: str = "gemini-2.5-pro",
        api_key: Optional[str] = None,
    ) -> None:
        self.model_name = model
        self._api_key = api_key or ""

    def _key(self) -> str:
        if self._api_key:
            return self._api_key
        return _load_api_key()

    def is_available(self) -> bool:
        """GET /v1beta/models?key=... 检查 API Key 有效性"""
        try:
            key = _load_api_key()
        except ProviderUnavailableError:
            return False
        url = f"{_BASE_URL}/models?key={urllib.parse.quote(key, safe='')}"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=_CONNECT_TIMEOUT) as resp:
                return resp.status == 200
        except Exception:
            return False

    def complete(self, prompt: str, max_tokens: int = 8192) -> str:
        """
        调用 Gemini generateContent API。

        Args:
            prompt:     完整 prompt 文本
            max_tokens: 最大输出 token 数。
                        注意：gemini-2.5-pro 使用 thinking 模式，思考过程本身会消耗
                        大量 token，实际输出 token = max_tokens - thinking_tokens。
                        建议最小值 4096，DAG/评审任务建议 16384。

        Returns:
            生成的文本字符串

        Raises:
            ProviderUnavailableError: API 调用失败
        """
        key = self._key()
        url = f"{_BASE_URL}/models/{self.model_name}:generateContent?key={urllib.parse.quote(key, safe='')}"

        # gemini-2.5-pro 的 thinking 模式会消耗大量 token 作为内部推理
        # 确保 max_tokens 足够大，避免输出被截断为空
        # fallback: config.yaml → llm.google.min_output_tokens (default=8192)
        effective_max_tokens = max(max_tokens, _MIN_OUTPUT_TOKENS)

        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}],
                    "role": "user",
                }
            ],
            "generationConfig": {
                "maxOutputTokens": effective_max_tokens,
                "temperature": 0.2,
            },
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )

        start = time.time()
        try:
            with urllib.request.urlopen(req, timeout=_GENERATE_TIMEOUT) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            latency_ms = (time.time() - start) * 1000
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            exc = ProviderUnavailableError(
                f"Gemini API HTTP {e.code}：{e.reason}\n{err_body}"
            )
            try:
                from mms.model_tracker import record as _track
                _track(
                    model=self.model_name,
                    provider="gemini",
                    prompt_tok=None,
                    output_tok=None,
                    latency_ms=latency_ms,
                    success=False,
                    error=str(exc),
                )
            except Exception:
                pass
            raise exc from e
        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            exc = ProviderUnavailableError(
                f"Gemini API 调用失败（{type(e).__name__}）：{e}"
            )
            try:
                from mms.model_tracker import record as _track
                _track(
                    model=self.model_name,
                    provider="gemini",
                    prompt_tok=None,
                    output_tok=None,
                    latency_ms=latency_ms,
                    success=False,
                    error=str(exc),
                )
            except Exception:
                pass
            raise exc from e

        elapsed = time.time() - start

        # 解析响应
        try:
            candidates = body.get("candidates", [])
            if not candidates:
                block_reason = body.get("promptFeedback", {}).get("blockReason", "")
                raise ProviderUnavailableError(
                    f"Gemini 返回空候选（blockReason={block_reason}）"
                )

            candidate = candidates[0]
            finish_reason = candidate.get("finishReason", "")
            content = candidate.get("content", {})
            parts = content.get("parts", [])
            text = "".join(p.get("text", "") for p in parts).strip()

            if not text:
                # gemini-2.5-pro thinking 模式：MAX_TOKENS 时 parts 可能为空
                # 此时说明 max_tokens 不足以容纳思考 + 输出，需要增大
                usage = body.get("usageMetadata", {})
                thinking_tokens = usage.get("thoughtsTokenCount", 0)
                total_tokens = usage.get("totalTokenCount", 0)
                raise ProviderUnavailableError(
                    f"Gemini 返回内容为空（finishReason={finish_reason}）。\n"
                    f"思考 token={thinking_tokens}，总 token={total_tokens}，"
                    f"maxOutputTokens={effective_max_tokens}。\n"
                    f"请增大 max_tokens（建议 ≥ {thinking_tokens + 2000}）或使用 gemini-2.5-flash。"
                )

            # 记录成功调用统计
            usage = body.get("usageMetadata", {})
            latency_ms = elapsed * 1000
            try:
                from mms.model_tracker import record as _track
                _track(
                    model=self.model_name,
                    provider="gemini",
                    prompt_tok=usage.get("promptTokenCount"),
                    output_tok=usage.get("candidatesTokenCount"),
                    latency_ms=latency_ms,
                    success=True,
                )
            except Exception:
                pass

            return text
        except ProviderUnavailableError:
            raise
        except Exception as e:
            raise ProviderUnavailableError(
                f"Gemini 响应解析失败：{e}\n原始响应：{json.dumps(body)[:500]}"
            ) from e
