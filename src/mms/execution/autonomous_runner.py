"""
src/mms/execution/autonomous_runner.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Track B: Autonomous Runner — ReAct（Reason + Act）自治循环

架构：
  ┌─────────────────────────────────────────────────────────┐
  │  System Prompt（任务描述 + ToolRegistry 描述）            │
  │        ↓                                                │
  │  [Turn 1..N] LLM 生成 Action → 本地执行 Tool            │
  │            → Observation 追加到消息历史                  │
  │        ↓                                                │
  │  LLM 调用 tool_finish → 循环结束                        │
  └─────────────────────────────────────────────────────────┘

安全边界：
  - max_turns:      最大循环轮次（默认 10，防止无限循环）
  - token_budget:   累计 token 上限（超出则强制结束）
  - timeout_s:      总执行超时（超出则强制结束并汇报进度）

依赖：
  - mms.agent_tools.registry（ToolRegistry）
  - mms.providers.bailian（BailianProvider.complete_with_tools）
  - mms.utils.mms_config（读取 agent 配置）

版本：v1.0 | 创建于：2026-05-02 | Sprint 3
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys
_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# ─── 数据类 ──────────────────────────────────────────────────────────────────

@dataclass
class TurnRecord:
    """单轮 ReAct 记录。"""
    turn: int
    action_type: str      # "tool_call" | "text" | "finish"
    tool_name: str = ""
    tool_args: Dict[str, Any] = field(default_factory=dict)
    tool_result: str = ""
    text_content: str = ""
    elapsed_s: float = 0.0


@dataclass
class AutonomousResult:
    """Autonomous Runner 最终结果。"""
    ep_id: str
    success: bool
    finish_reason: str = ""      # "tool_finish" | "max_turns" | "timeout" | "error"
    turns_used: int = 0
    elapsed_s: float = 0.0
    turns: List[TurnRecord] = field(default_factory=list)
    final_summary: str = ""
    error: str = ""
    dry_run: bool = False

    @property
    def message(self) -> str:
        if self.success:
            return f"✅ 自治完成（{self.turns_used} 轮 / {self.elapsed_s:.1f}s）"
        return f"❌ 自治失败（{self.finish_reason}）: {self.error[:100]}"


# ─── System Prompt 生成 ───────────────────────────────────────────────────────

_SYSTEM_PROMPT_TEMPLATE = """你是木兰 AI 编码助手的自治执行引擎（Autonomous Mode）。

## 当前任务
EP 编号：{ep_id}
任务描述：{task_desc}

## 执行规则
1. 你必须在完成任务前优先调用工具了解项目架构和代码结构，不要凭空假设。
2. 在生成代码变更前，先调用 tool_get_ast 了解目标文件结构。
3. 生成代码后，先调用 tool_dry_run_diff 验证，通过后再调用 tool_run_pytest 确认测试。
4. 任务完成或无法继续时，调用 tool_finish 结束。
5. 每轮只调用一个工具，等待结果后再决定下一步。

## 剩余轮次预算
当前轮次：{current_turn}/{max_turns}

{tools_section}

## 重要约束
- 代码变更必须通过 tool_dry_run_diff 验证（返回 ✅ 才可继续）
- 架构层级规则必须遵守（通过 tool_query_ontology 了解约束）
- 不要生成超过 200 行的代码 diff（需要则拆分为多个工具调用）
"""

_TOOL_FINISH_DEF = {
    "type": "function",
    "function": {
        "name": "tool_finish",
        "description": "标记任务完成或放弃，结束自治循环。",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["success", "partial", "failed"],
                    "description": "完成状态：success=全部完成，partial=部分完成，failed=无法完成",
                },
                "summary": {
                    "type": "string",
                    "description": "执行摘要（完成了什么，遇到了什么问题）",
                },
            },
            "required": ["status", "summary"],
        },
    },
}


# ─── 核心执行循环 ─────────────────────────────────────────────────────────────

def run_autonomous(
    ep_id: str,
    model: str = "qwen3-32b",
    dry_run: bool = False,
    skip_precheck: bool = False,
    skip_postcheck: bool = False,
    max_turns: Optional[int] = None,
    token_budget: Optional[int] = None,
    timeout_s: Optional[float] = None,
    task_desc: str = "",
    verbose: bool = True,
) -> AutonomousResult:
    """
    Autonomous Runner 主入口。

    Args:
        ep_id:          EP 编号
        model:          LLM 模型名（需支持 Tool-Calling）
        dry_run:        不写文件
        skip_precheck:  跳过 precheck（EP Runner 传入）
        skip_postcheck: 跳过 postcheck
        max_turns:      最大轮次（None 时从 config 读取，默认 10）
        token_budget:   Token 预算（None 时从 config 读取）
        timeout_s:      总超时秒数
        task_desc:      任务描述（空时从 EP 文件读取）
        verbose:        打印执行过程

    Returns:
        AutonomousResult
    """
    start = time.monotonic()
    result = AutonomousResult(ep_id=ep_id, success=False, dry_run=dry_run)

    def log(msg: str) -> None:
        if verbose:
            print(msg)

    # ── 读取配置 ──────────────────────────────────────────────────────────────
    try:
        from mms.utils.mms_config import cfg  # type: ignore
        agent_cfg = cfg.get("agent", {})
    except Exception:
        agent_cfg = {}

    _max_turns = max_turns or agent_cfg.get("max_autonomous_turns", 10)
    _token_budget = token_budget or agent_cfg.get("autonomous_token_budget", 80000)
    _timeout_s = timeout_s or agent_cfg.get("autonomous_timeout", 600)

    log(f"\n{'═' * 60}")
    log(f"  MMS Autonomous Runner  ·  {ep_id}  ·  model={model}")
    log(f"  max_turns={_max_turns}  token_budget={_token_budget}  timeout={_timeout_s}s")
    log(f"{'═' * 60}")

    # ── 加载工具注册表 ────────────────────────────────────────────────────────
    try:
        from mms.agent_tools.registry import get_tool_registry  # type: ignore
        tool_registry = get_tool_registry()
    except Exception as e:
        result.error = f"ToolRegistry 初始化失败: {e}"
        result.finish_reason = "error"
        return result

    # 工具描述（包含 tool_finish）
    tool_schemas = tool_registry.get_schemas() + [_TOOL_FINISH_DEF]
    tools_section = tool_registry.get_system_prompt_section()

    # ── 读取任务描述 ──────────────────────────────────────────────────────────
    if not task_desc:
        task_desc = _read_ep_task_desc(ep_id)

    # ── 初始化 Provider ───────────────────────────────────────────────────────
    try:
        from mms.providers.bailian import BailianProvider  # type: ignore
        provider = BailianProvider(model=model)
        if not provider.is_available():
            result.error = f"Provider {model} 不可用（API Key 未配置或网络不可达）"
            result.finish_reason = "error"
            log(f"  ❌ {result.error}")
            return result
    except Exception as e:
        result.error = f"Provider 初始化失败: {e}"
        result.finish_reason = "error"
        log(f"  ❌ {result.error}")
        return result

    # ── 构建初始消息历史 ──────────────────────────────────────────────────────
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        ep_id=ep_id,
        task_desc=task_desc or "（未提供任务描述，请通过 tool_query_ontology 了解项目背景）",
        current_turn=1,
        max_turns=_max_turns,
        tools_section=tools_section,
    )
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"请开始执行任务：{ep_id}"},
    ]

    total_tokens = 0

    # ── ReAct 主循环 ──────────────────────────────────────────────────────────
    for turn in range(1, _max_turns + 1):
        elapsed = time.monotonic() - start
        if elapsed > _timeout_s:
            result.finish_reason = "timeout"
            result.error = f"超时（{elapsed:.0f}s > {_timeout_s}s）"
            log(f"\n  ⏰ 超时，结束自治循环")
            break

        log(f"\n  ── Turn {turn}/{_max_turns} ────────────────────────")
        turn_start = time.monotonic()
        turn_record = TurnRecord(turn=turn, action_type="text")

        # 更新 system prompt 中的轮次信息
        messages[0]["content"] = system_prompt.replace(
            f"当前轮次：{turn - 1 if turn > 1 else 1}/{_max_turns}",
            f"当前轮次：{turn}/{_max_turns}"
        )

        # 调用 LLM（带 Tool-Calling）
        try:
            response_msg = provider.complete_with_tools(
                messages=messages,
                tools=tool_schemas,
                max_tokens=min(4096, max(1024, _token_budget - total_tokens)),
            )
        except Exception as e:
            result.error = f"Turn {turn} LLM 调用失败: {e}"
            result.finish_reason = "error"
            log(f"  ❌ LLM 调用失败: {e}")
            break

        # 追加 assistant 消息到历史
        messages.append({"role": "assistant", **response_msg})

        tool_calls = response_msg.get("tool_calls") or []
        text_content = response_msg.get("content") or ""

        # ── 处理工具调用 ────────────────────────────────────────────────────
        if tool_calls:
            for tc in tool_calls:
                fn = tc.get("function", {})
                tool_name = fn.get("name", "")
                tool_args_str = fn.get("arguments", "{}")
                tool_call_id = tc.get("id", f"call_{turn}")

                try:
                    tool_args = json.loads(tool_args_str)
                except json.JSONDecodeError:
                    tool_args = {}

                log(f"  🔧 调用工具: {tool_name}({json.dumps(tool_args, ensure_ascii=False)[:80]})")

                # 处理 tool_finish
                if tool_name == "tool_finish":
                    status = tool_args.get("status", "success")
                    summary = tool_args.get("summary", "")
                    result.success = status in ("success", "partial")
                    result.finish_reason = "tool_finish"
                    result.final_summary = summary
                    result.turns_used = turn
                    log(f"\n  ✅ 任务完成（{status}）: {summary[:100]}")
                    result.elapsed_s = time.monotonic() - start
                    return result

                # 调用注册的工具
                tool_result = tool_registry.call(tool_name, **tool_args)
                observation = tool_result.to_message()

                log(f"  📋 结果: {'成功' if tool_result.success else '失败'} "
                    f"| {observation[:80]}...")

                turn_record.action_type = "tool_call"
                turn_record.tool_name = tool_name
                turn_record.tool_args = tool_args
                turn_record.tool_result = observation[:500]

                # 追加工具结果到消息历史
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": observation,
                })

        elif text_content:
            # 纯文本回复（思考过程或最终结论）
            log(f"  💬 LLM: {text_content[:150]}...")
            turn_record.action_type = "text"
            turn_record.text_content = text_content[:500]

            # 如果没有工具调用且有文本，追加用户提示继续
            messages.append({
                "role": "user",
                "content": "请继续。如果任务已完成，请调用 tool_finish；否则调用下一个工具。",
            })
        else:
            # 空响应
            messages.append({
                "role": "user",
                "content": "未收到有效响应，请调用工具或 tool_finish 结束。",
            })

        turn_record.elapsed_s = time.monotonic() - turn_start
        result.turns.append(turn_record)

    # 超出最大轮次
    if result.finish_reason not in ("tool_finish", "error", "timeout"):
        result.finish_reason = "max_turns"
        result.error = f"达到最大轮次 {_max_turns}，任务未完成"
        result.success = False
        log(f"\n  ⚠️  达到最大轮次 {_max_turns}，强制结束")

    result.turns_used = len(result.turns)
    result.elapsed_s = time.monotonic() - start
    return result


# ─── 辅助函数 ─────────────────────────────────────────────────────────────────

def _read_ep_task_desc(ep_id: str) -> str:
    """从 EP Markdown 文件中读取任务描述（首行 # 标题）。"""
    try:
        from mms.utils._paths import _PROJECT_ROOT  # type: ignore
        ep_dir = _PROJECT_ROOT / "docs" / "execution_plans"
        for ep_file in ep_dir.glob(f"{ep_id}_*.md"):
            lines = ep_file.read_text(encoding="utf-8").splitlines()
            for line in lines[:10]:
                if line.startswith("#"):
                    return line.lstrip("#").strip()
    except Exception:
        pass
    return f"执行任务 {ep_id}"
