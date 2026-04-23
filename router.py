"""
MMS 多模型路由器

职责：按任务类型选择合适的 Provider，并写入审计日志。
是 memory_distill.py 和其他工具的统一入口。

模型分工（本地 Ollama 优先，Claude 兜底）：
  推理类任务  → deepseek-r1:8b     蒸馏/路由/压缩/质量门
  代码类任务  → deepseek-coder-v2:16b  简单代码生成
  复杂架构    → Claude Sonnet 4.6  跨层变更（Pending 模式，人工处理）
"""
from typing import Optional, Tuple

from .observability import audit as _audit
from .observability import tracer as _tracer
from .providers import factory
from .providers.base import LLMProvider


def get_provider(
    task: str,
    trace_id: Optional[str] = None,
    ep_id: Optional[str] = None,
) -> Tuple[LLMProvider, str]:
    """
    按任务类型获取可用 Provider，写入路由审计日志。

    Args:
        task:     任务类型（distillation / context_compression / task_routing /
                  code_review / code_generation_simple / complex_architecture）
        trace_id: 调用方传入的 trace_id；为 None 时自动生成
        ep_id:    关联的 EP 编号（如 "EP-108"），用于审计

    Returns:
        (provider, trace_id) 元组

    Example:
        provider, tid = get_provider("distillation", ep_id="EP-108")
        result = provider.complete(prompt)
    """
    if trace_id is None:
        trace_id = _tracer.new_trace_id()

    provider = factory.auto_detect(task)

    _audit.AuditLogger().log(
        trace_id=trace_id,
        op="route",
        task=task,
        model=provider.model_name,
        ep=ep_id,
        result="ok",
    )

    return provider, trace_id


def compress_context(
    long_text: str,
    max_output_tokens: int = 2000,
    trace_id: Optional[str] = None,
    ep_id: Optional[str] = None,
) -> str:
    """
    将长文本（如完整 EP 记录）压缩为简洁摘要，
    供后续蒸馏步骤使用，避免超出小模型的上下文窗口。

    使用 deepseek-r1:8b 执行，适合 30K → 2K token 的压缩比。
    """
    provider, trace_id = get_provider("context_compression", trace_id, ep_id)

    prompt = (
        f"请将以下技术文档压缩为结构化摘要，保留所有关键决策、错误教训和模式。\n"
        f"输出格式：Markdown 列表，最多 {max_output_tokens // 4} 个要点，每点不超过 2 行。\n\n"
        f"---\n{long_text}\n---"
    )
    return provider.complete(prompt, max_tokens=max_output_tokens)
