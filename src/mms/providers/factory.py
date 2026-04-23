"""
LLM Provider 工厂与自动探测

职责：
  1. 按环境变量构建 Provider 实例池
  2. 按任务类型路由到合适的 Provider
  3. 按 fallback_chain 顺序自动探测可用 Provider

任务 → 模型映射：

  reasoning             → bailian_plus   (qwen3-32b)        [主：意图合成/蒸馏]
  distillation          → bailian_plus   (qwen3-32b)        [主]
  context_compression   → bailian_plus   (qwen3-32b)        [主]
  task_routing          → bailian_plus   (qwen3-32b)        [主]
  intent_classification → bailian_plus   (qwen3-32b)        [主：意图分类 LLM 兜底]
  code_review           → bailian_plus   (qwen3-32b)        [主：语义评审]
  code_generation       → bailian_coder  (qwen3-coder-next) [主：代码生成（capable）]
  code_generation_simple→ bailian_coder  (qwen3-coder-next) [主：代码生成（fast）]
  dag_orchestration     → bailian_plus   (qwen3-32b)        [主：DAG 生成]
  complex_architecture  → bailian_plus   (qwen3-32b)        [主]

降级链：bailian_plus → bailian_coder → claude（人工介入兜底）

路由覆盖：
  可通过环境变量 MMS_TASK_MODEL_OVERRIDE=task:provider_id,...  覆盖默认映射
  示例：MMS_TASK_MODEL_OVERRIDE=code_generation:bailian_coder
"""
import os
from pathlib import Path
from typing import Dict, List, Optional

from .bailian import BailianEmbedProvider, BailianProvider, _load_env_file
from .base import AllProvidersUnavailableError, LLMProvider
from .claude import ClaudeProvider

# 任务 → Provider ID 默认映射
# 可通过 MMS_TASK_MODEL_OVERRIDE 环境变量在运行时覆盖（格式：task:provider,...）
_TASK_MODEL_MAP_DEFAULT: Dict[str, str] = {
    "reasoning":               "bailian_plus",
    "distillation":            "bailian_plus",
    "context_compression":     "bailian_plus",
    "task_routing":            "bailian_plus",
    "intent_classification":   "bailian_plus",
    "code_review":             "bailian_plus",
    "code_generation":         "bailian_coder",
    "code_generation_simple":  "bailian_coder",
    "dag_orchestration":       "bailian_plus",
    "complex_architecture":    "bailian_plus",
}

# 降级链：百炼双模型互备，Claude 作为人工介入最终兜底
_FALLBACK_CHAIN: List[str] = [
    "bailian_plus",
    "bailian_coder",
    "claude",
]


def _build_task_model_map() -> Dict[str, str]:
    """
    构建任务→模型映射，支持通过环境变量运行时覆盖。

    覆盖格式：MMS_TASK_MODEL_OVERRIDE=code_generation:bailian_coder
    用途：A/B 测试、CI 环境固定模型
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

        # Claude Pending（最终兜底，永不失败，人工介入）
        "claude": ClaudeProvider(),
    }


def build_embed_provider():
    """构建嵌入 Provider：仅使用百炼 text-embedding-v3。"""
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

    return None  # 无 DASHSCOPE_API_KEY 时嵌入不可用（Benchmark Hybrid RAG 模式需要）


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
    """获取嵌入 Provider（百炼 text-embedding-v3）"""
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
        if provider_id not in _PROVIDERS:
            continue
        provider = _PROVIDERS[provider_id]
        if provider.is_available():
            return provider
        last_err = Exception(
            f"{provider_id} ({provider.model_name}) 不可用"
        )

    raise AllProvidersUnavailableError(
        f"所有 Provider 均不可用，任务={task}，尝试链={chain}。\n"
        f"最后错误: {last_err}\n"
        f"请检查：DASHSCOPE_API_KEY 是否已在 .env.memory 中设置（百炼）"
    )


def get_provider_for_task(task: str = "distillation") -> LLMProvider:
    """auto_detect 的别名，供 dream.py / unit_runner.py 调用"""
    return auto_detect(task)


def reset() -> None:
    """重置 Provider 池（测试用，强制重新初始化）"""
    global _PROVIDERS, _EMBED_PROVIDER
    _PROVIDERS = None
    _EMBED_PROVIDER = None
