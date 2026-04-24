"""
internal_reviewer.py — 双角色自评审（Dual-Role Self-Reflection）

Feature flag 控制，默认关闭。通过环境变量或 config.yaml 开启：
  MMS_ENABLE_INTERNAL_REVIEW=true
  或 config.yaml: runner.enable_internal_review: true

工作流：
  Coder（qwen3-coder-next）生成代码 Diff
    → Reviewer（qwen3-32b）审查违规（依据注入的 Ontology + AC）
    → 若发现违规 → 生成修改建议 → 打回 Coder 重写（最多 N 轮）
    → 通过 or 超次数 → 返回最终内容

使用示例：
  from mms.execution.internal_reviewer import maybe_review
  content, accepted, feedback = maybe_review(
      diff_content=raw_llm_output,
      ontology_context=injected_context,
      unit_meta={"ep_id": "EP-123", "unit_id": "U2"},
  )
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

# ── Feature Flag ─────────────────────────────────────────────────────────────

def _review_enabled() -> bool:
    """读取 feature flag：环境变量 > config.yaml > 默认关闭。"""
    env_val = os.environ.get("MMS_ENABLE_INTERNAL_REVIEW", "").lower()
    if env_val in ("1", "true", "yes", "on"):
        return True
    if env_val in ("0", "false", "no", "off"):
        return False
    try:
        from mms.utils.mms_config import cfg  # type: ignore[import]
        return bool(getattr(cfg, "runner_enable_internal_review", False))
    except ImportError:
        return False


_MAX_REVIEW_ROUNDS = 2  # Coder 最多被打回重写的次数

# ── Reviewer Prompt ──────────────────────────────────────────────────────────

_REVIEWER_SYSTEM = """\
你是一位资深架构师，正在对 AI Coder 生成的代码 Diff 进行审查。
你的唯一职责：根据【Ontology 约束】和【验收条件（AC）】，
判断代码是否违反了架构规范。

【审查规则】
1. 只检查真实的架构违规（如：Controller 直接访问 DB、缺少 DTO、空指针未处理等）
2. 不评价代码风格（格式、注释、命名风格不是违规）
3. 不提出功能性建议（只审查约束合规性）
4. 如果代码合规，直接输出：APPROVED

【输出格式】（违规时）
VIOLATION:
- <具体违规项1（附行号或代码片段）>
- <具体违规项2>
SUGGESTION:
<针对违规项的最小修改建议，以 diff 格式或说明形式，不超过 200 字>
"""

_REVIEWER_USER = """\
【当前任务】
EP: {ep_id}  Unit: {unit_id}

【Ontology 与 AC 约束】
{ontology_context}

【待审查的代码 Diff】
{diff_content}

请直接输出审查结论（APPROVED 或 VIOLATION/SUGGESTION）：
"""


def _call_reviewer(
    diff_content: str,
    ontology_context: str,
    ep_id: str,
    unit_id: str,
    timeout: int = 60,
) -> str:
    """调用 qwen3-32b（Reviewer 角色）审查代码 Diff。"""
    user_msg = _REVIEWER_USER.format(
        ep_id=ep_id,
        unit_id=unit_id,
        ontology_context=ontology_context[:2000],
        diff_content=diff_content[:4000],
    )
    try:
        from mms.providers.factory import auto_detect  # type: ignore[import]
        provider = auto_detect("intent_classification")  # → qwen3-32b
        return provider.complete(
            prompt=user_msg,
            system=_REVIEWER_SYSTEM,
            max_tokens=1024,
        )
    except Exception as exc:
        return f"APPROVED (Reviewer 不可用: {exc})"


def _parse_review(review_output: str) -> Tuple[bool, str]:
    """
    解析 Reviewer 输出。

    Returns:
        (approved: bool, suggestion: str)
    """
    text = review_output.strip()
    if text.upper().startswith("APPROVED"):
        return True, ""

    suggestion = ""
    if "SUGGESTION:" in text:
        suggestion = text.split("SUGGESTION:", 1)[1].strip()
    elif "VIOLATION:" in text:
        suggestion = text.split("VIOLATION:", 1)[1].strip()

    return False, suggestion


# ── 主接口 ───────────────────────────────────────────────────────────────────

def maybe_review(
    diff_content: str,
    ontology_context: str = "",
    unit_meta: Optional[dict] = None,
) -> Tuple[str, bool, str]:
    """
    如果 feature flag 开启，执行双角色自评审；否则直接通过。

    Args:
        diff_content:      LLM 生成的代码 Diff 原文
        ontology_context:  已注入的 Ontology + AC 字符串
        unit_meta:         包含 ep_id / unit_id 的字典

    Returns:
        (final_content: str, accepted: bool, feedback: str)
        - final_content: 最终通过的内容（可能是多轮后的版本）
        - accepted:      True = 通过评审（或 flag 关闭）
        - feedback:      最后一次 Reviewer 的反馈（通过时为空）
    """
    if not _review_enabled():
        return diff_content, True, ""

    meta = unit_meta or {}
    ep_id = meta.get("ep_id", "EP-?")
    unit_id = meta.get("unit_id", "U?")

    current_content = diff_content
    last_feedback = ""

    for round_num in range(1, _MAX_REVIEW_ROUNDS + 1):
        print(f"  🔍 [InternalReviewer] 第 {round_num} 轮评审（{ep_id} {unit_id}）...")
        review_output = _call_reviewer(
            diff_content=current_content,
            ontology_context=ontology_context,
            ep_id=ep_id,
            unit_id=unit_id,
        )
        approved, suggestion = _parse_review(review_output)

        if approved:
            print(f"  ✅ [InternalReviewer] 通过（第 {round_num} 轮）")
            return current_content, True, ""

        last_feedback = suggestion
        print(f"  ⚠️  [InternalReviewer] 发现违规，打回重写：\n     {suggestion[:200]}")

        if round_num < _MAX_REVIEW_ROUNDS:
            # 将违规反馈注入内容供调用方重新生成（返回 feedback，由 unit_runner 触发重试）
            return current_content, False, last_feedback

    # 超过最大轮数，强制通过（带警告），不阻塞工作流
    print(f"  ⚠️  [InternalReviewer] 超过最大评审轮数（{_MAX_REVIEW_ROUNDS}），强制通过")
    return current_content, True, f"[评审超次] {last_feedback}"
