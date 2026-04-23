"""
阿里云百炼（DashScope）LLM 适配器

使用 OpenAI 兼容接口，无第三方依赖（纯 stdlib）。

支持模型：
  - qwen3-32b          推理任务（蒸馏、路由、压缩、质量验收）
  - qwen3-coder-next   代码生成任务
  - text-embedding-v3  相似度嵌入（重复记忆检测，预留接口）

认证：
  优先读取环境变量 DASHSCOPE_API_KEY，
  其次读取 .env.memory 文件中的同名配置。

端点：
  https://dashscope.aliyuncs.com/compatible-mode/v1

健康检查：
  GET /v1/models（携带 Authorization 头），返回 200 视为可用。
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional

from .base import EmbedProvider, LLMProvider, ProviderUnavailableError

_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
try:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from mms_config import cfg as _cfg_bailian  # type: ignore[import]
except Exception:
    _cfg_bailian = None  # type: ignore[assignment]

# fallback: config.yaml → llm.bailian.connect_timeout_seconds (default=8)
_CONNECT_TIMEOUT = int(getattr(_cfg_bailian, "llm_bailian_connect_timeout", 8)) if _cfg_bailian else 8
# fallback: config.yaml → llm.bailian.generate_timeout_seconds (default=120)
_GENERATE_TIMEOUT = int(getattr(_cfg_bailian, "llm_bailian_generate_timeout", 120)) if _cfg_bailian else 120
# fallback: config.yaml → llm.bailian.embed_timeout_seconds (default=30)
_EMBED_TIMEOUT = int(getattr(_cfg_bailian, "llm_bailian_embed_timeout", 30)) if _cfg_bailian else 30

# 支持 <think> 过滤的模型关键字（Qwen3 思维链模式 / DeepSeek-R1 兼容）
_THINKING_MODEL_KEYWORDS = ("think", "r1", "qwq", "qwen3")

try:
    from _paths import _PROJECT_ROOT as _PROOT  # type: ignore[import]
except ImportError:
    _PROOT = Path(__file__).resolve().parent.parent
# .env.memory 路径（优先级低于真实环境变量）
_ENV_FILE = _PROOT / ".env.memory"

# 缓存：避免重复读文件
_ENV_CACHE: Optional[dict] = None


def _load_env_file() -> dict:
    """读取 .env.memory 文件，返回 key→value 字典（缓存，首次调用后复用）"""
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
    """
    按优先级读取配置值：
      1. 真实环境变量（os.environ）
      2. .env.memory 文件
      3. default
    """
    val = os.environ.get(key, "").strip()
    if val:
        return val
    return _load_env_file().get(key, default)


def _load_api_key() -> str:
    return _get_config("DASHSCOPE_API_KEY")


def _is_thinking_model(model_name: str) -> bool:
    name_lower = model_name.lower()
    return any(kw in name_lower for kw in _THINKING_MODEL_KEYWORDS)


def _strip_think_tags(text: str) -> str:
    """过滤思维链模型输出的 <think>...</think> 推理过程"""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return cleaned.strip()


def _http_post(url: str, payload: dict, api_key: str, timeout: int) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise ProviderUnavailableError(
            f"百炼 API HTTP {e.code}: {body[:300]}"
        ) from e
    except (urllib.error.URLError, OSError) as e:
        raise ProviderUnavailableError(f"百炼 API 连接失败: {e}") from e


def _http_get(url: str, api_key: str, timeout: int) -> Optional[dict]:
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception:
        pass
    return None


class BailianProvider(LLMProvider):
    """
    阿里云百炼文本生成适配器，使用 OpenAI 兼容接口。

    Example:
        provider = BailianProvider(model="qwen3-32b")
        if provider.is_available():
            result = provider.complete("请分析以下代码...")
    """

    def __init__(
        self,
        model: str = "qwen3-32b",
        api_key: Optional[str] = None,
        base_url: str = _BASE_URL,
        timeout: int = _GENERATE_TIMEOUT,
    ) -> None:
        self.model_name = model
        self._api_key = api_key or _load_api_key()
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._is_thinking = _is_thinking_model(model)

    def is_available(self) -> bool:
        if not self._api_key:
            return False
        result = _http_get(
            f"{self._base_url}/models",
            self._api_key,
            _CONNECT_TIMEOUT,
        )
        return result is not None

    def complete_messages(
        self,
        messages: list,
        max_tokens: int = 4096,
    ) -> str:
        """
        支持多角色消息（system + user）的完整接口。
        messages 格式：[{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
        """
        if not self._api_key:
            raise ProviderUnavailableError(
                "百炼 API Key 未配置，请设置环境变量 DASHSCOPE_API_KEY "
                "或在 .env.memory 中添加 DASHSCOPE_API_KEY=sk-..."
            )
        url = f"{self._base_url}/chat/completions"
        payload: dict = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": False,
        }
        # 百炼 qwen3 系列非流式调用必须显式关闭 thinking，否则 API 返回 HTTP 400
        if self._is_thinking:
            payload["enable_thinking"] = False
        t0 = time.monotonic()
        try:
            data = _http_post(url, payload, self._api_key, self._timeout)
            latency_ms = (time.monotonic() - t0) * 1000
            content: str = data["choices"][0]["message"]["content"]
            if self._is_thinking:
                content = _strip_think_tags(content)
            usage = data.get("usage", {})
            try:
                from mms.model_tracker import record as _track
                _track(
                    model=self.model_name,
                    provider="bailian",
                    prompt_tok=usage.get("prompt_tokens"),
                    output_tok=usage.get("completion_tokens"),
                    latency_ms=latency_ms,
                    success=True,
                )
            except Exception:
                pass
            return content
        except Exception as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            try:
                from mms.model_tracker import record as _track
                _track(
                    model=self.model_name,
                    provider="bailian",
                    prompt_tok=None,
                    output_tok=None,
                    latency_ms=latency_ms,
                    success=False,
                    error=str(exc),
                )
            except Exception:
                pass
            raise

    def complete(self, prompt: str, max_tokens: int = 4096) -> str:
        if not self._api_key:
            raise ProviderUnavailableError(
                "百炼 API Key 未配置，请设置环境变量 DASHSCOPE_API_KEY "
                "或在 .env.memory 中添加 DASHSCOPE_API_KEY=sk-..."
            )

        url = f"{self._base_url}/chat/completions"
        payload: dict = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "stream": False,
        }
        # 百炼 qwen3 系列非流式调用必须显式关闭 thinking，否则 API 返回 HTTP 400
        if self._is_thinking:
            payload["enable_thinking"] = False

        t0 = time.monotonic()
        try:
            data = _http_post(url, payload, self._api_key, self._timeout)
            latency_ms = (time.monotonic() - t0) * 1000

            content: str = data["choices"][0]["message"]["content"]
            if self._is_thinking:
                content = _strip_think_tags(content)

            # 追踪 token 用量（百炼响应包含 usage 字段）
            usage = data.get("usage", {})
            try:
                from mms.model_tracker import record as _track
                _track(
                    model=self.model_name,
                    provider="bailian",
                    prompt_tok=usage.get("prompt_tokens"),
                    output_tok=usage.get("completion_tokens"),
                    latency_ms=latency_ms,
                    success=True,
                )
            except Exception:
                pass  # 追踪失败不影响主流程

            return content
        except Exception as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            try:
                from mms.model_tracker import record as _track
                _track(
                    model=self.model_name,
                    provider="bailian",
                    prompt_tok=None,
                    output_tok=None,
                    latency_ms=latency_ms,
                    success=False,
                    error=str(exc),
                )
            except Exception:
                pass
            raise


class BailianEmbedProvider(EmbedProvider):
    """
    阿里云百炼嵌入适配器（text-embedding-v3）。
    仅用于蒸馏阶段的重复记忆检测，不在检索路径中使用。

    Example:
        embed = BailianEmbedProvider()
        v1 = embed.embed("Kafka 单节点需要设置 replication.factor=1")
        v2 = embed.embed("Kafka 副本因子配置")
        print(embed.cosine_similarity(v1, v2))  # ~0.9
    """

    def __init__(
        self,
        model: str = "text-embedding-v3",
        api_key: Optional[str] = None,
        base_url: str = _BASE_URL,
    ) -> None:
        self.model_name = model
        self._api_key = api_key or _load_api_key()
        self._base_url = base_url.rstrip("/")

    def is_available(self) -> bool:
        if not self._api_key:
            return False
        result = _http_get(
            f"{self._base_url}/models",
            self._api_key,
            _CONNECT_TIMEOUT,
        )
        return result is not None

    def embed(self, text: str) -> List[float]:
        if not self._api_key:
            raise ProviderUnavailableError("百炼 API Key 未配置")

        url = f"{self._base_url}/embeddings"
        payload = {
            "model": self.model_name,
            "input": text,
            "encoding_format": "float",
        }
        t0 = time.monotonic()
        try:
            data = _http_post(url, payload, self._api_key, _EMBED_TIMEOUT)
            latency_ms = (time.monotonic() - t0) * 1000
            usage = data.get("usage", {})
            try:
                from mms.model_tracker import record as _track
                _track(
                    model=self.model_name,
                    provider="bailian",
                    prompt_tok=usage.get("prompt_tokens") or usage.get("total_tokens"),
                    output_tok=None,
                    latency_ms=latency_ms,
                    success=True,
                )
            except Exception:
                pass
            return data["data"][0]["embedding"]
        except Exception as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            try:
                from mms.model_tracker import record as _track
                _track(
                    model=self.model_name,
                    provider="bailian",
                    prompt_tok=None,
                    output_tok=None,
                    latency_ms=latency_ms,
                    success=False,
                    error=str(exc),
                )
            except Exception:
                pass
            raise
