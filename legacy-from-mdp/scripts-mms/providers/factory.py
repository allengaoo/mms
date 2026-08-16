"""
LLM Provider 工厂与自动探测

职责：
  1. 按环境变量构建 Provider 实例池
  2. 按任务类型路由到合适的 Provider
  3. 按 fallback_chain 顺序自动探测可用 Provider

任务 → 模型映射（EP-132：全链路切换为百炼小模型）：

  reasoning             → bailian_plus   (qwen3-32b)           [主：意图合成/蒸馏]
  distillation          → bailian_plus   (qwen3-32b)           [主]
                        → ollama_r1      (deepseek-r1:8b)      [降级]
  context_compression   → bailian_plus   (qwen3-32b)           [主]
  task_routing          → bailian_plus   (qwen3-32b)           [主]
  intent_classification → bailian_plus   (qwen3-32b)           [主：意图分类 LLM 兜底]
                        → ollama_r1      (deepseek-r1:8b)      [降级]
  code_review           → bailian_plus   (qwen3-32b)           [主：语义评审（EP-132 从 Gemini 切换）]
                        → gemini         (gemini-2.5-pro)      [降级（保留为 fallback）]
                        → ollama_r1      (deepseek-r1:8b)      [二级降级]
  code_generation       → bailian_coder  (qwen3-coder-next)    [主：代码生成（capable）]
                        → ollama_coder   (deepseek-coder-v2)   [降级]
  code_generation_simple→ bailian_coder  (qwen3-coder-next)    [主：代码生成（fast）]
                        → ollama_coder   (deepseek-coder-v2)   [降级]
  dag_orchestration     → bailian_plus   (qwen3-32b)           [主：DAG 生成（EP-132 从 Gemini 切换）]
                        → gemini         (gemini-2.5-pro)      [降级（保留为 fallback）]
                        → ollama_r1      (deepseek-r1:8b)      [二级降级]
  complex_architecture  → bailian_plus   (qwen3-32b)           [主]
                        → gemini         (gemini-2.5-pro)      [降级]
                        → claude         (Pending 模式)         [最终兜底]

路由覆盖：
  可通过环境变量 MMS_TASK_MODEL_OVERRIDE=task:provider_id,...  覆盖默认映射
  示例：MMS_TASK_MODEL_OVERRIDE=dag_orchestration:gemini,code_review:gemini
"""
import os
from pathlib import Path
from typing import Dict, List, Optional

from .bailian import BailianEmbedProvider, BailianProvider, _load_env_file
from .base import AllProvidersUnavailableError, LLMProvider
from .claude import ClaudeProvider
from .gemini import GeminiProvider
from .ollama import OllamaEmbedProvider, OllamaProvider

# 任务 → Provider ID 默认映射（EP-132：全链路切换为百炼小模型）
# 可通过 MMS_TASK_MODEL_OVERRIDE 环境变量在运行时覆盖（格式：task:provider,...）
_TASK_MODEL_MAP_DEFAULT: Dict[str, str] = {
    "reasoning":               "bailian_plus",   # 意图合成/蒸馏/质量门
    "distillation":            "bailian_plus",
    "context_compression":     "bailian_plus",
    "task_routing":            "bailian_plus",
    "intent_classification":   "bailian_plus",   # EP-132 新增：意图分类 LLM 兜底
    "code_review":             "bailian_plus",   # EP-132：从 gemini 切换为百炼
    "code_generation":         "bailian_coder",  # capable 路径 → qwen3-coder-next
    "code_generation_simple":  "bailian_coder",  # fast 路径 → qwen3-coder-next
    "dag_orchestration":       "bailian_plus",   # EP-132：从 gemini 切换为百炼
    "complex_architecture":    "bailian_plus",   # EP-132：从 gemini 切换为百炼
}

# 降级链：百炼优先，Gemini 作为高质量降级，Ollama 作为离线降级，Claude 兜底
_FALLBACK_CHAIN: List[str] = [
    "bailian_plus",
    "bailian_coder",
    "gemini",        # EP-132：Gemini 降为第三顺位（保留为 fallback）
    "ollama_r1",
    "ollama_coder",
    "claude",
]


def _build_task_model_map() -> Dict[str, str]:
    """
    构建任务→模型映射，支持通过环境变量运行时覆盖。

    覆盖格式：MMS_TASK_MODEL_OVERRIDE=dag_orchestration:gemini,code_review:gemini
    用途：A/B 测试、临时回退到 Gemini、CI 环境固定模型
    """
    mapping = dict(_TASK_MODEL_MAP_DEFAULT)
    override_str = os.environ.get("MMS_TASK_MODEL_OVERRIDE", "").strip()
    if override_str:
        for pair in override_str.split(","):
            pair = pair.strip()
            if ":" not in pair:
                continue
            task, provider_id = pair.split(":", 1)
            task = task.strip()
            provider_id = provider_id.strip()
            if task and provider_id:
                mapping[task] = provider_id
    return mapping


# 运行时映射（模块加载时构建，支持环境变量覆盖）
_TASK_MODEL_MAP: Dict[str, str] = _build_task_model_map()

# 全局 Provider 池（延迟初始化，避免 import 时触发 HTTP 检查）
_PROVIDERS: Optional[Dict[str, LLMProvider]] = None
_EMBED_PROVIDER = None


def _get_env(key: str, default: str) -> str:
    """按优先级读取配置：os.environ > .env.memory > default"""
    val = os.environ.get(key, "").strip()
    if val:
        return val
    return _load_env_file().get(key, default)


def build_providers() -> Dict[str, LLMProvider]:
    """根据环境变量构建 Provider 实例池（可被测试替换）"""

    # ── 百炼（主力）────────────────────────────────────────────────────────────
    dashscope_key = _get_env("DASHSCOPE_API_KEY", "")
    bailian_base = _get_env(
        "DASHSCOPE_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    # ── Ollama（本地降级）───────────────────────────────────────────────────────
    ollama_base = _get_env("OLLAMA_BASE_URL", "http://localhost:11434")

    return {
        # 百炼 Provider（推理 + 代码）
        "bailian_plus": BailianProvider(
            model=_get_env("DASHSCOPE_MODEL_REASONING", "qwen3-32b"),
            api_key=dashscope_key or None,
            base_url=bailian_base,
        ),
        "bailian_coder": BailianProvider(
            model=_get_env("DASHSCOPE_MODEL_CODING", "qwen3-coder-next"),
            api_key=dashscope_key or None,
            base_url=bailian_base,
        ),

        # Ollama Provider（本地降级，无 API Key 要求）
        "ollama_r1": OllamaProvider(
            model=_get_env("OLLAMA_MODEL_REASONING", "deepseek-r1:8b"),
            base_url=ollama_base,
        ),
        "ollama_coder": OllamaProvider(
            model=_get_env("OLLAMA_MODEL_CODING", "deepseek-coder-v2:16b"),
            base_url=ollama_base,
        ),

        # Google Gemini（DAG 编排 + 代码语义评审）
        "gemini": GeminiProvider(
            model=_get_env("GOOGLE_MODEL_ORCHESTRATION", "gemini-2.5-pro"),
            api_key=_get_env("GOOGLE_API_KEY", "") or None,
        ),

        # Claude Pending（最终兜底，永不失败，人工介入）
        "claude": ClaudeProvider(),
    }


def build_embed_provider():
    """构建嵌入 Provider：百炼优先，Ollama 降级"""
    dashscope_key = _get_env("DASHSCOPE_API_KEY", "")
    bailian_base = _get_env(
        "DASHSCOPE_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    if dashscope_key:
        return BailianEmbedProvider(
            model=_get_env("DASHSCOPE_MODEL_EMBEDDING", "text-embedding-v3"),
            api_key=dashscope_key,
            base_url=bailian_base,
        )

    # 降级为 Ollama nomic-embed-text
    return OllamaEmbedProvider(
        model=_get_env("OLLAMA_MODEL_EMBEDDING", "nomic-embed-text"),
        base_url=_get_env("OLLAMA_BASE_URL", "http://localhost:11434"),
    )


def _ensure_initialized() -> None:
    global _PROVIDERS, _EMBED_PROVIDER
    if _PROVIDERS is None:
        _PROVIDERS = build_providers()
    if _EMBED_PROVIDER is None:
        _EMBED_PROVIDER = build_embed_provider()


def get(provider_id: str) -> LLMProvider:
    """按 ID 获取 Provider 实例"""
    _ensure_initialized()
    if provider_id not in _PROVIDERS:
        raise KeyError(
            f"未知 Provider ID: {provider_id}，"
            f"可用: {list(_PROVIDERS.keys())}"
        )
    return _PROVIDERS[provider_id]


def get_embed():
    """获取嵌入 Provider（百炼 text-embedding-v3 或 Ollama nomic-embed-text）"""
    _ensure_initialized()
    return _EMBED_PROVIDER


def auto_detect(task: str = "distillation") -> LLMProvider:
    """
    按任务类型自动选择可用 Provider。

    优先使用任务对应的首选模型（百炼），失败时按 fallback_chain 降级。
    最终兜底为 ClaudeProvider（Pending Prompt 模式，人工介入）。

    Raises:
        AllProvidersUnavailableError: 所有 Provider 均不可用（理论上不会发生，
            因为 ClaudeProvider.is_available() 始终返回 True）
    """
    _ensure_initialized()
    preferred = _TASK_MODEL_MAP.get(task, "bailian_plus")
    chain = [preferred] + [p for p in _FALLBACK_CHAIN if p != preferred]

    last_err: Optional[Exception] = None
    for provider_id in chain:
        provider = _PROVIDERS[provider_id]
        if provider.is_available():
            return provider
        last_err = Exception(
            f"{provider_id} ({provider.model_name}) 不可用"
        )

    raise AllProvidersUnavailableError(
        f"所有 Provider 均不可用，任务={task}，尝试链={chain}。\n"
        f"最后错误: {last_err}\n"
        f"请检查：\n"
        f"  1. DASHSCOPE_API_KEY 是否已设置（百炼）\n"
        f"  2. GOOGLE_API_KEY 是否已设置（Gemini）\n"
        f"  3. ollama serve 是否运行（本地降级）"
    )


def get_provider_for_task(task: str = "distillation") -> LLMProvider:
    """auto_detect 的别名，供 dream.py / unit_runner.py 调用"""
    return auto_detect(task)


def reset() -> None:
    """重置 Provider 池（测试用，强制重新初始化）"""
    global _PROVIDERS, _EMBED_PROVIDER
    _PROVIDERS = None
    _EMBED_PROVIDER = None
