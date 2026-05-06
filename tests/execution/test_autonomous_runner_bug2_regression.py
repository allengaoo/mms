"""
test_autonomous_runner_bug2_regression.py — Bug 2 回归测试：JSON 解析错误正确反馈

验证修复：当 LLM 返回的 tool_call.function.arguments 不是合法 JSON 时，
必须将错误作为 Observation 反馈给 LLM，而不是静默设置 tool_args={} 并继续执行。

Bug 根因：
  原代码中 except json.JSONDecodeError: tool_args = {}
  这导致：
  1. tool_registry.call(tool_name, **{}) 向下游传递空参数字典
  2. 下游 Tool 因缺少必填参数抛出不受控的 TypeError，使整个 ReAct 循环崩溃
  3. 即使不崩溃，Tool 也会收到错误输入，产生不可预测的副作用

修复方案：
  捕获 JSONDecodeError → 构造 [JSON_PARSE_ERROR] 错误消息 → 
  追加为 role=tool 的 Observation → continue 跳过本次调用 →
  LLM 在下一轮看到错误反馈后可以自我纠正。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mms.execution.autonomous_runner import run_autonomous, MaxTurnsExceededError


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _tool_call_response(name: str, args: Dict[str, Any], tool_id: str = None) -> Dict:
    """构造合法的工具调用响应。"""
    return {
        "content": "",
        "tool_calls": [{
            "id": tool_id or f"call_{name}",
            "function": {
                "name": name,
                "arguments": json.dumps(args, ensure_ascii=False),
            },
        }],
        "usage": {"total_tokens": 80},
    }


def _malformed_tool_call_response(name: str, bad_args: str, tool_id: str = "call_bad") -> Dict:
    """构造携带非法 JSON 参数的工具调用响应。"""
    return {
        "content": "",
        "tool_calls": [{
            "id": tool_id,
            "function": {
                "name": name,
                "arguments": bad_args,  # 故意传入非法 JSON
            },
        }],
        "usage": {"total_tokens": 80},
    }


def _finish_response(summary: str = "完成") -> Dict:
    return _tool_call_response("tool_finish", {"summary": summary})


def _text_response(text: str = "思考中...") -> Dict:
    return {
        "content": text,
        "tool_calls": [],
        "usage": {"total_tokens": 50},
    }


def _run(responses: List[Dict], max_turns: int = 8) -> Any:
    """用 mock LLM 运行 Autonomous Runner，完全隔离真实 LLM 和工具。"""
    mock_prov = MagicMock()
    mock_prov.complete_with_tools.side_effect = responses

    with patch("mms.providers.bailian.BailianProvider", return_value=mock_prov), \
         patch("mms.execution.autonomous_runner._read_ep_task_desc", return_value="测试任务"):
        return run_autonomous(
            ep_id="EP-BUG2-TEST",
            model="qwen3-32b",
            dry_run=True,
            max_turns=max_turns,
            task_desc="测试任务",
            verbose=False,
        )


# ── 核心回归测试：JSON 解析错误不静默吞咽 ─────────────────────────────────────

class TestJSONDecodeErrorNotSilentlySwallowed:
    """
    Bug 2 核心验证：malformed JSON 不得被静默忽略。
    修复前：error → tool_args={} → 继续调用 tool，可能崩溃或产生副作用。
    修复后：error → 错误消息写入消息历史 → continue 到下一轮。
    """

    def test_malformed_json_loop_does_not_crash(self):
        """
        LLM 返回 malformed JSON 时，循环不应崩溃（TypeError/KeyError/etc），
        最终可以正常退出（通过后续的 tool_finish）。
        """
        responses = [
            _malformed_tool_call_response("tool_query_ontology", "{ bad json !!!"),
            _finish_response("修复后完成"),
        ]
        result = _run(responses)
        # 循环应能正常完成，而不是抛出未捕获的 TypeError
        assert result is not None
        assert result.finish_reason in ("tool_finish", "max_turns", "error")

    def test_malformed_json_then_valid_finishes_successfully(self):
        """
        第一轮 malformed JSON → 第二轮 LLM 修正并调用 tool_finish → 成功完成。
        这是修复后的「自愈」能力验证。
        """
        responses = [
            _malformed_tool_call_response("tool_get_ast", "{{invalid}}"),
            _finish_response("LLM 自愈完成"),
        ]
        result = _run(responses)
        assert result.success is True
        assert result.finish_reason == "tool_finish"
        assert "自愈" in result.final_summary

    def test_multiple_malformed_json_does_not_cascade_crash(self):
        """
        连续多轮 malformed JSON，循环不应崩溃。
        最终因超出 max_turns 结束（不是抛出 TypeError）。
        """
        responses = [
            _malformed_tool_call_response("tool_a", "not json"),
            _malformed_tool_call_response("tool_b", "also not json"),
            _malformed_tool_call_response("tool_c", "still not json"),
        ]
        result = _run(responses, max_turns=3)
        # 不应崩溃，finish_reason 应为 max_turns（不是 error 且不是异常）
        assert result.finish_reason in ("max_turns", "tool_finish")
        assert result.success is False  # 3轮都是 malformed，不可能 success

    def test_empty_arguments_string_does_not_crash(self):
        """
        arguments 为空字符串时（不是 '{}'），也应被 JSONDecodeError 捕获并处理。
        空字符串是 `json.loads('')` 会抛出 JSONDecodeError 的典型情况。
        """
        responses = [
            _malformed_tool_call_response("tool_query_ontology", ""),
            _finish_response("空参数容错"),
        ]
        result = _run(responses)
        # 不崩溃即通过
        assert result is not None

    def test_partial_json_does_not_crash(self):
        """截断的 JSON（如流式传输中断）应被容错处理。"""
        responses = [
            _malformed_tool_call_response("tool_write_file", '{"path": "main.py", "content":'),
            _finish_response("截断容错"),
        ]
        result = _run(responses)
        assert result is not None


class TestJSONDecodeErrorFeedbackMechanism:
    """
    验证错误反馈机制：错误必须以 role=tool 消息写回消息历史，
    供 LLM 在下一轮感知并自我修正。
    """

    def test_error_feedback_allows_llm_to_be_called_second_time(self):
        """
        malformed JSON 处理后，循环应继续，LLM 应被调用第二次（接收错误反馈并修正）。
        这是验证 continue 语义正确性的关键指标。
        """
        spy_provider = MagicMock()
        spy_provider.complete_with_tools.side_effect = [
            _malformed_tool_call_response("tool_query_ontology", "bad json"),
            _finish_response("已感知错误并完成"),
        ]

        with patch("mms.providers.bailian.BailianProvider", return_value=spy_provider), \
             patch("mms.execution.autonomous_runner._read_ep_task_desc", return_value="测试"):
            result = run_autonomous(
                ep_id="EP-BUG2-SPY",
                model="qwen3-32b",
                dry_run=True,
                max_turns=5,
                task_desc="spy",
                verbose=False,
            )

        # LLM 应被调用两次：第一次返回 malformed JSON，第二次（修正后）返回 tool_finish
        assert spy_provider.complete_with_tools.call_count == 2, (
            f"LLM 应被调用 2 次（第1次 malformed，第2次修正），"
            f"实际调用次数：{spy_provider.complete_with_tools.call_count}"
        )
        # 最终应成功完成
        assert result.success is True

    def test_malformed_json_tool_not_called_with_empty_dict(self):
        """
        关键回归：malformed JSON 时，tool_registry.call 不应被调用（包括空参数调用）。
        修复前：json.JSONDecodeError → tool_args={} → tool_registry.call(name) → TypeError。
        修复后：json.JSONDecodeError → 反馈消息 → continue（跳过 tool_registry.call）。
        """
        mock_tool_registry = MagicMock()
        mock_tool_registry.get_schemas.return_value = []
        mock_tool_registry.get_system_prompt_section.return_value = "工具说明"

        mock_prov = MagicMock()
        mock_prov.complete_with_tools.side_effect = [
            _malformed_tool_call_response("tool_query_ontology", "{invalid"),
            _finish_response("完成"),
        ]

        with patch("mms.providers.bailian.BailianProvider", return_value=mock_prov), \
             patch("mms.execution.autonomous_runner._read_ep_task_desc", return_value="测试"), \
             patch("mms.agent_tools.registry.get_tool_registry", return_value=mock_tool_registry):
            result = run_autonomous(
                ep_id="EP-BUG2-NO-EMPTY-CALL",
                model="qwen3-32b",
                dry_run=True,
                max_turns=5,
                task_desc="测试",
                verbose=False,
            )

        # tool_registry.call 不应被调用（malformed JSON 应在 continue 之前跳过）
        # 如果有调用，检查第一次调用不是用空参数调用 tool_query_ontology
        for call_args in mock_tool_registry.call.call_args_list:
            args, kwargs = call_args
            if args and args[0] == "tool_query_ontology":
                pytest.fail(
                    f"tool_query_ontology 不应被调用（malformed JSON），"
                    f"但收到了调用：args={args}, kwargs={kwargs}"
                )


class TestJSONDecodeErrorRecoverySequence:
    """
    验证自愈序列：malformed JSON → error 反馈 → LLM 修正 → 正常完成。
    模拟真实场景中 LLM 流式输出中断后重试的流程。
    """

    def test_one_bad_then_good_tool_call_succeeds(self):
        """
        序列：malformed → 合法 tool_call → tool_finish。
        修复后，合法的工具调用在 malformed 之后仍能正常执行。
        """
        responses = [
            _malformed_tool_call_response("tool_get_ast", "{{truncated"),
            _tool_call_response("tool_query_ontology", {"query": "OrderService"}),
            _finish_response("两步完成"),
        ]
        result = _run(responses, max_turns=5)
        # 合法的 tool_query_ontology 调用应能正常执行
        assert result.finish_reason == "tool_finish"
        assert result.success is True

    def test_finish_after_bad_json_does_not_lose_track(self):
        """
        malformed JSON 后直接 tool_finish，turns_used 应正确计数。
        """
        responses = [
            _malformed_tool_call_response("tool_x", "not valid json"),
            _finish_response("直接完成"),
        ]
        result = _run(responses, max_turns=5)
        assert result.success is True
        # turns_used 应 >= 1（malformed 轮 + finish 轮）
        assert result.turns_used >= 1
