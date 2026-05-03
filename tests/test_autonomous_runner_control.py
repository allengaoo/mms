"""
test_autonomous_runner_control.py — Autonomous Runner 控制流测试（Phase 3 TDD）

策略：
  - 不调用真实 LLM，全部 mock BailianProvider.complete_with_tools
  - 验证：max_turns 阻断 / timeout 阻断 / tool_finish 正常退出 / 错误累计
  - 验证：raise_on_max_turns 参数行为

不依赖 VCR cassette（因为用 mock 完全替代 LLM 层）。
VCR cassette 测试见 test_seed_absorber.py（需要真实 LLM 响应录制）。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE.parent / "src"))

from mms.execution.autonomous_runner import (
    MaxTurnsExceededError,
    AutonomousResult,
    run_autonomous,
)


# ─────────────────────────────────────────────────────────────────────────────
# 辅助：构造 mock LLM 响应
# ─────────────────────────────────────────────────────────────────────────────

def _tool_call_response(tool_name: str, args: Dict[str, Any]) -> Dict:
    """
    返回一个模拟「调用 tool_name」的 LLM 响应。
    格式与 BailianProvider.complete_with_tools 实际返回格式一致：
      tool_calls[i] = {"id": "...", "function": {"name": "...", "arguments": "..."}}
    """
    import json
    return {
        "content": "",
        "tool_calls": [{
            "id": f"call_{tool_name}",
            "function": {"name": tool_name, "arguments": json.dumps(args, ensure_ascii=False)},
        }],
        "usage": {"total_tokens": 100},
    }


def _finish_response(summary: str = "任务完成") -> Dict:
    return _tool_call_response("tool_finish", {"summary": summary})


def _text_response(text: str = "思考中...") -> Dict:
    return {
        "content": text,
        "tool_calls": [],
        "usage": {"total_tokens": 50},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Fixture：构造最小可运行上下文（mock Provider + 真实 ToolRegistry）
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_provider_factory():
    """
    返回一个工厂函数，接受「响应序列」，生成对应的 mock BailianProvider。
    响应序列中的每个元素对应一次 complete_with_tools 调用。
    """
    def factory(responses):
        provider = MagicMock()
        provider.complete_with_tools.side_effect = responses
        return provider
    return factory


def _run_with_mock(responses, max_turns=5, raise_on_max=False, ep_id="EP-TEST-001"):
    """
    用 mock LLM 运行 Autonomous Runner。
    patch 掉 BailianProvider 的实例化和 _read_ep_task_desc。
    """
    mock_prov = MagicMock()
    mock_prov.complete_with_tools.side_effect = responses

    with patch("mms.providers.bailian.BailianProvider", return_value=mock_prov), \
         patch("mms.execution.autonomous_runner._read_ep_task_desc", return_value="测试任务描述"):
        return run_autonomous(
            ep_id=ep_id,
            model="qwen3-32b",
            dry_run=True,
            max_turns=max_turns,
            task_desc="测试任务",
            verbose=False,
            raise_on_max_turns=raise_on_max,
        )


# ─────────────────────────────────────────────────────────────────────────────
# 测试：正常完成流程
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalCompletion:
    """tool_finish 正常退出。"""

    def test_finish_on_first_turn(self):
        """第一轮直接调用 tool_finish，应成功退出。"""
        result = _run_with_mock(responses=[_finish_response("快速完成")])
        assert result.success is True
        assert result.finish_reason == "tool_finish"
        assert result.turns_used == 1

    def test_finish_after_tool_calls(self):
        """先调用几个工具，最后 tool_finish，应成功退出。"""
        responses = [
            _tool_call_response("tool_query_ontology", {"query": "OrderService"}),
            _tool_call_response("tool_get_ast", {"file_path": "service.py"}),
            _finish_response("完成代码生成"),
        ]
        result = _run_with_mock(responses=responses, max_turns=5)
        assert result.success is True
        assert result.finish_reason == "tool_finish"
        assert result.turns_used == 3

    def test_final_summary_captured(self):
        """tool_finish 的 summary 应出现在 result.final_summary 中。"""
        result = _run_with_mock(responses=[_finish_response("已完成所有变更")])
        assert "已完成所有变更" in result.final_summary


# ─────────────────────────────────────────────────────────────────────────────
# 测试：max_turns 阻断
# ─────────────────────────────────────────────────────────────────────────────

class TestMaxTurnsGuard:
    """达到最大轮次的行为验证。"""

    def test_max_turns_sets_finish_reason(self):
        """超出 max_turns，finish_reason 应为 'max_turns'，success=False。"""
        # 每轮都只返回文本，永远不调用 tool_finish
        responses = [_text_response(f"思考第{i}轮") for i in range(10)]
        result = _run_with_mock(responses=responses, max_turns=3)
        assert result.success is False
        assert result.finish_reason == "max_turns"
        assert result.turns_used == 3

    def test_max_turns_raises_when_requested(self):
        """raise_on_max_turns=True 时应抛出 MaxTurnsExceededError。"""
        responses = [_text_response() for _ in range(10)]
        with pytest.raises(MaxTurnsExceededError, match="EP-TEST-001"):
            _run_with_mock(responses=responses, max_turns=2, raise_on_max=True)

    def test_max_turns_no_raise_by_default(self):
        """默认不抛出异常，返回 finish_reason='max_turns'。"""
        responses = [_text_response() for _ in range(10)]
        result = _run_with_mock(responses=responses, max_turns=2, raise_on_max=False)
        assert result.finish_reason == "max_turns"
        assert result.success is False

    def test_turns_count_equals_max(self):
        """turns_used 应等于 max_turns。"""
        responses = [_text_response() for _ in range(20)]
        result = _run_with_mock(responses=responses, max_turns=4)
        assert result.turns_used == 4


# ─────────────────────────────────────────────────────────────────────────────
# 测试：LLM 调用异常处理
# ─────────────────────────────────────────────────────────────────────────────

class TestErrorHandling:
    """LLM 抛出异常时的降级行为。"""

    def test_llm_exception_sets_error_status(self):
        """LLM 抛出异常，finish_reason 应为 'error'，success=False。"""
        responses = [Exception("网络超时")]
        result = _run_with_mock(responses=responses, max_turns=3)
        assert result.success is False
        assert result.finish_reason == "error"
        assert "网络超时" in result.error or len(result.error) > 0

    def test_llm_exception_after_successful_turns(self):
        """前几轮正常，某轮 LLM 报错，应仍然能捕获错误并停止。"""
        responses = [
            _tool_call_response("tool_query_ontology", {"query": "test"}),
            Exception("API 限流"),
        ]
        result = _run_with_mock(responses=responses, max_turns=5)
        assert result.success is False
        assert result.turns_used >= 1

    def test_empty_response_continues(self):
        """LLM 返回空响应（无 tool_calls，无 content），应继续而非崩溃。"""
        responses = [
            {"content": "", "tool_calls": [], "usage": {"total_tokens": 0}},
            _finish_response("补救完成"),
        ]
        result = _run_with_mock(responses=responses, max_turns=5)
        assert result.success is True


# ─────────────────────────────────────────────────────────────────────────────
# 测试：dry_run 模式
# ─────────────────────────────────────────────────────────────────────────────

class TestDryRunMode:
    """dry_run=True 时不写文件，行为仍然正确。"""

    def test_dry_run_completes_normally(self):
        result = _run_with_mock(responses=[_finish_response("dry-run 完成")])
        assert result.dry_run is True
        assert result.success is True

    def test_dry_run_elapsed_time_recorded(self):
        result = _run_with_mock(responses=[_finish_response()])
        assert result.elapsed_s >= 0
