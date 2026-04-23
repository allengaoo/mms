"""
Ollama 本地 LLM 适配器

支持模型：
  - deepseek-r1:8b      推理任务（蒸馏、路由、质量验收）
  - deepseek-coder-v2:16b 代码生成任务
  - nomic-embed-text    相似度嵌入（可选，用于重复记忆检测）

使用 OpenAI 兼容接口（/v1/chat/completions）和原生 embeddings 接口，
仅依赖 Python 3.9 stdlib（urllib.request + json + re）。
"""
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import List

from .base import EmbedProvider, LLMProvider, ProviderUnavailableError

_DEFAULT_BASE_URL = "http://localhost:11434"
try:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from mms.utils.mms_config import cfg as _cfg_ollama  # type: ignore[import]
except Exception:
    _cfg_ollama = None  # type: ignore[assignment]

# fallback: config.yaml → llm.ollama.connect_timeout_seconds (default=3)
_CONNECT_TIMEOUT = int(getattr(_cfg_ollama, "llm_ollama_connect_timeout", 3)) if _cfg_ollama else 3
# fallback: config.yaml → llm.ollama.generate_timeout_seconds (default=120)
_GENERATE_TIMEOUT = int(getattr(_cfg_ollama, "llm_ollama_generate_timeout", 120)) if _cfg_ollama else 120
# fallback: config.yaml → llm.ollama.embed_timeout_seconds (default=30)
_EMBED_TIMEOUT = int(getattr(_cfg_ollama, "llm_ollama_embed_timeout", 30)) if _cfg_ollama else 30

# 需要过滤 <think> 标签的模型关键字
_REASONING_MODEL_KEYWORDS = ("r1", "think", "qwq")


def _is_reasoning_model(model_name: str) -> bool:
    name_lower = model_name.lower()
    return any(kw in name_lower for kw in _REASONING_MODEL_KEYWORDS)


def _strip_think_tags(text: str) -> str:
    """过滤 deepseek-r1 等推理模型输出的 <think>...</think> 推理链"""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return cleaned.strip()


def _http_post(url: str, payload: dict, timeout: int) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise ProviderUnavailableError(
            f"Ollama HTTP {e.code}: {body[:200]}"
        ) from e
    except (urllib.error.URLError, OSError) as e:
        raise ProviderUnavailableError(f"Ollama 连接失败: {e}") from e


class OllamaProvider(LLMProvider):
    """
    Ollama 文本生成适配器，使用 OpenAI 兼容接口。

    Example:
        provider = OllamaProvider(model="deepseek-r1:8b")
        if provider.is_available():
            result = provider.complete("请分析以下代码...")
    """

    def __init__(
        self,
        model: str,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: int = _GENERATE_TIMEOUT,
    ) -> None:
        self.model_name = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._is_reasoning = _is_reasoning_model(model)

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self._base_url}/api/version")
            with urllib.request.urlopen(req, timeout=_CONNECT_TIMEOUT) as resp:
                return resp.status == 200
        except Exception:
            return False

    def complete(self, prompt: str, max_tokens: int = 4096) -> str:
        url = f"{self._base_url}/v1/chat/completions"
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        t0 = time.monotonic()
        try:
            data = _http_post(url, payload, self._timeout)
            latency_ms = (time.monotonic() - t0) * 1000

            content = data["choices"][0]["message"]["content"]
            if self._is_reasoning:
                content = _strip_think_tags(content)

            # Ollama OpenAI 兼容接口的 token 统计
            usage = data.get("usage", {})
            prompt_tok  = usage.get("prompt_tokens")
            output_tok  = usage.get("completion_tokens")
            # 部分版本 Ollama 用 prompt_eval_count / eval_count
            if prompt_tok is None:
                prompt_tok = data.get("prompt_eval_count")
            if output_tok is None:
                output_tok = data.get("eval_count")

            try:
                from mms.utils.model_tracker import record as _track
                _track(
                    model=self.model_name,
                    provider="ollama",
                    prompt_tok=prompt_tok,
                    output_tok=output_tok,
                    latency_ms=latency_ms,
                    success=True,
                )
            except Exception:
                pass

            return content
        except Exception as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            try:
                from mms.utils.model_tracker import record as _track
                _track(
                    model=self.model_name,
                    provider="ollama",
                    prompt_tok=None,
                    output_tok=None,
                    latency_ms=latency_ms,
                    success=False,
                    error=str(exc),
                )
            except Exception:
                pass
            raise


class OllamaEmbedProvider(EmbedProvider):
    """
    Ollama 嵌入适配器，使用 nomic-embed-text 模型。
    仅用于蒸馏阶段的重复记忆检测，不用于检索路径。

    Example:
        embed = OllamaEmbedProvider()
        v1 = embed.embed("Kafka 单节点需要设置 replication.factor=1")
        v2 = embed.embed("Kafka 副本因子配置")
        print(embed.cosine_similarity(v1, v2))  # 0.92
    """

    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str = _DEFAULT_BASE_URL,
    ) -> None:
        self.model_name = model
        self._base_url = base_url.rstrip("/")

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self._base_url}/api/version")
            with urllib.request.urlopen(req, timeout=_CONNECT_TIMEOUT) as resp:
                return resp.status == 200
        except Exception:
            return False

    def embed(self, text: str) -> List[float]:
        url = f"{self._base_url}/api/embeddings"
        payload = {"model": self.model_name, "prompt": text}
        data = _http_post(url, payload, _EMBED_TIMEOUT)
        return data["embedding"]
