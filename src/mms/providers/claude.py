"""
Claude Sonnet 4.6 适配器（Pending Prompt 模式）

设计决策：不直接接入 Anthropic API，而是将 prompt 写入
docs/memory/_system/pending_claude_prompts/ 目录，
由用户在 Cursor 中手动执行后，通过 --resume 参数继续流程。

触发场景：complex_architecture 任务 或 百炼 Provider 均不可用时的人工介入兜底。
"""
import datetime
import hashlib
from pathlib import Path

from .base import LLMProvider, ProviderUnavailableError

try:
    from mms.utils._paths import DOCS_MEMORY as _MEMORY_ROOT  # type: ignore[import]
except ImportError:
    _MEMORY_ROOT = Path(__file__).resolve().parent.parent / "docs" / "memory"

_PENDING_DIR = _MEMORY_ROOT / "_system" / "pending_claude_prompts"


class ProviderPendingError(ProviderUnavailableError):
    """
    Claude Provider 处于 Pending 模式。
    prompt 已写入文件，需要人工在 Cursor 中执行后继续。
    """

    def __init__(self, prompt_file: Path) -> None:
        self.prompt_file = prompt_file
        super().__init__(
            f"\n{'='*60}\n"
            f"[Claude Pending] prompt 已保存至：\n"
            f"  {prompt_file}\n\n"
            f"请在 Cursor 中执行该 prompt，将输出保存为同名 .response.md 文件，\n"
            f"然后运行：python scripts/memory_distill.py --resume <trace_id>\n"
            f"{'='*60}"
        )


class ClaudeProvider(LLMProvider):
    """
    Claude Sonnet 4.6 的 Pending Prompt 适配器。

    is_available() 始终返回 True（作为最终兜底，永不失败）。
    complete() 将 prompt 写入文件并抛出 ProviderPendingError，
    由调用方决定如何处理（等待人工 / 跳过 / 降级）。
    """

    model_name = "claude-sonnet-4-6"

    def __init__(self) -> None:
        _PENDING_DIR.mkdir(parents=True, exist_ok=True)

    def is_available(self) -> bool:
        return True

    def complete(self, prompt: str, max_tokens: int = 4096) -> str:
        prompt_file = self._save_prompt(prompt, max_tokens)
        raise ProviderPendingError(prompt_file)

    def _save_prompt(self, prompt: str, max_tokens: int) -> Path:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()[:6]
        fname = _PENDING_DIR / f"prompt_{ts}_{prompt_hash}.md"

        header = (
            f"# Claude Sonnet 4.6 — Pending Prompt\n\n"
            f"- 生成时间：{datetime.datetime.now().isoformat()}\n"
            f"- 最大输出：{max_tokens} tokens\n"
            f"- 状态：⏳ 待执行\n\n"
            f"## 操作说明\n\n"
            f"1. 将下方 `## Prompt` 内容复制到 Cursor 聊天框中执行\n"
            f"2. 将 Claude 的回复保存到同目录下的 `{fname.stem}.response.md`\n"
            f"3. 运行 `python scripts/memory_distill.py --resume <trace_id>` 继续\n\n"
            f"## Prompt\n\n"
        )
        fname.write_text(header + prompt, encoding="utf-8")
        return fname
