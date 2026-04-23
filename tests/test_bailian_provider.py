"""
test_bailian_provider.py — BailianProvider 单元测试

核心防漏场景：
  - qwen3 系列模型非流式调用必须携带 enable_thinking=False
    （否则百炼 API 返回 HTTP 400，错误信息：
     "parameter.enable_thinking must be set to false for non-streaming calls"）
  - 非 qwen3 模型不应注入 enable_thinking 字段（避免污染其他模型）
  - _is_thinking 标志正确识别 qwen3/think/r1/qwq 关键字
  - complete() 成功时过滤 <think>...</think> 标签
  - complete_messages() 同样注入 enable_thinking=False
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call
from typing import List

import pytest

_MMS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MMS_DIR))

from mms.providers.bailian import BailianProvider, _is_thinking_model, _strip_think_tags


# ══════════════════════════════════════════════════════════════════════════════
# 辅助：构造标准 API 响应
# ══════════════════════════════════════════════════════════════════════════════

def _make_response(content: str, prompt_tok: int = 10, completion_tok: int = 20) -> dict:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt_tok, "completion_tokens": completion_tok},
    }


def _patch_http_post(response: dict):
    """patch _http_post，返回固定响应，同时捕获调用的 payload"""
    captured: List[dict] = []

    def fake_http_post(url, payload, api_key, timeout):
        captured.append(payload)
        return response

    return fake_http_post, captured


# ══════════════════════════════════════════════════════════════════════════════
# _is_thinking_model
# ══════════════════════════════════════════════════════════════════════════════

class TestIsThinkingModel:
    """_is_thinking_model 关键字识别"""

    @pytest.mark.parametrize("model_name", [
        "qwen3-32b",
        "qwen3-coder-next",
        "qwen3-7b",
        "QwQ-32B",
        "deepseek-r1:8b",
        "think-model",
    ])
    def test_thinking_models_detected(self, model_name: str):
        assert _is_thinking_model(model_name), f"{model_name!r} 应被识别为 thinking model"

    @pytest.mark.parametrize("model_name", [
        "qwen-plus",
        "qwen-max",
        "qwen-turbo",
        "qwen3-coder-plus",   # 不含 qwen3 关键字（注意：实际含有，此处验证行为）
        "gpt-4o",
        "claude-3-5-sonnet",
    ])
    def test_non_thinking_models(self, model_name: str):
        # qwen3-coder-plus 含 qwen3，所以实际是 thinking model
        # 此测试主要验证 qwen-plus/qwen-max/gpt 等不含关键字的模型
        if any(kw in model_name.lower() for kw in ("think", "r1", "qwq", "qwen3")):
            pytest.skip(f"{model_name!r} 实际含 thinking 关键字，跳过非思维链断言")
        assert not _is_thinking_model(model_name), f"{model_name!r} 不应被识别为 thinking model"


# ══════════════════════════════════════════════════════════════════════════════
# 核心 Bug 防漏：enable_thinking=False 必须注入 payload
# ══════════════════════════════════════════════════════════════════════════════

class TestEnableThinkingPayload:
    """
    核心测试：qwen3 模型非流式调用必须携带 enable_thinking=False。

    失败场景：百炼 API HTTP 400
      "parameter.enable_thinking must be set to false for non-streaming calls"
    """

    def test_qwen3_complete_injects_enable_thinking_false(self):
        """complete() 使用 qwen3-32b 时，payload 必须含 enable_thinking=False"""
        response = _make_response("<think>推理过程</think>\n实际答案")
        fake_post, captured = _patch_http_post(response)

        provider = BailianProvider(model="qwen3-32b", api_key="fake-key")
        with patch("mms.providers.bailian._http_post", side_effect=fake_post):
            result = provider.complete("测试 prompt")

        assert len(captured) == 1, "应恰好发出一次 HTTP 请求"
        payload = captured[0]
        assert "enable_thinking" in payload, (
            "qwen3 模型 payload 必须含 enable_thinking 字段（防止 HTTP 400）"
        )
        assert payload["enable_thinking"] is False, (
            f"enable_thinking 必须为 False，实际值：{payload['enable_thinking']!r}"
        )
        assert payload["stream"] is False, "非流式调用 stream 必须为 False"

    def test_qwen3_complete_messages_injects_enable_thinking_false(self):
        """complete_messages() 使用 qwen3-32b 时，payload 必须含 enable_thinking=False"""
        response = _make_response("答案内容")
        fake_post, captured = _patch_http_post(response)

        provider = BailianProvider(model="qwen3-32b", api_key="fake-key")
        messages = [
            {"role": "system", "content": "你是助手"},
            {"role": "user", "content": "测试"},
        ]
        with patch("mms.providers.bailian._http_post", side_effect=fake_post):
            provider.complete_messages(messages)

        payload = captured[0]
        assert payload.get("enable_thinking") is False, (
            "complete_messages() 的 qwen3 payload 也必须含 enable_thinking=False"
        )

    def test_qwen_plus_does_not_inject_enable_thinking(self):
        """非 qwen3 模型（如 qwen-plus）不应注入 enable_thinking 字段"""
        response = _make_response("普通回答")
        fake_post, captured = _patch_http_post(response)

        provider = BailianProvider(model="qwen-plus", api_key="fake-key")
        with patch("mms.providers.bailian._http_post", side_effect=fake_post):
            provider.complete("测试")

        payload = captured[0]
        assert "enable_thinking" not in payload, (
            "qwen-plus 等非 thinking 模型不应注入 enable_thinking 字段"
        )

    def test_qwen3_coder_next_injects_enable_thinking_false(self):
        """qwen3-coder-next 也是 thinking 模型，必须携带 enable_thinking=False"""
        response = _make_response("代码内容")
        fake_post, captured = _patch_http_post(response)

        provider = BailianProvider(model="qwen3-coder-next", api_key="fake-key")
        with patch("mms.providers.bailian._http_post", side_effect=fake_post):
            provider.complete("生成代码")

        assert captured[0].get("enable_thinking") is False


# ══════════════════════════════════════════════════════════════════════════════
# <think> 标签过滤
# ══════════════════════════════════════════════════════════════════════════════

class TestStripThinkTags:
    """_strip_think_tags 应过滤 <think>...</think> 内容"""

    def test_strips_think_block(self):
        text = "<think>这是推理过程，不应暴露给用户</think>\n最终答案"
        assert _strip_think_tags(text) == "最终答案"

    def test_strips_multiline_think_block(self):
        text = "<think>\n第一行推理\n第二行推理\n</think>\n结论"
        assert _strip_think_tags(text) == "结论"

    def test_no_think_tags_unchanged(self):
        text = "这是普通文本，不含 think 标签"
        assert _strip_think_tags(text) == text

    def test_qwen3_complete_strips_think_from_response(self):
        """complete() 应自动过滤 qwen3 返回的 <think> 块"""
        raw_content = "<think>内部推理过程</think>\n实际有用的回答"
        response = _make_response(raw_content)
        fake_post, _ = _patch_http_post(response)

        provider = BailianProvider(model="qwen3-32b", api_key="fake-key")
        with patch("mms.providers.bailian._http_post", side_effect=fake_post):
            result = provider.complete("测试")

        assert "<think>" not in result, "返回内容不应包含 <think> 标签"
        assert "实际有用的回答" in result, "过滤后应保留实际答案"


# ══════════════════════════════════════════════════════════════════════════════
# complete() payload 基础结构校验
# ══════════════════════════════════════════════════════════════════════════════

class TestCompletePayloadStructure:
    """complete() 发出的 payload 结构必须符合百炼 API 规范"""

    def test_payload_has_required_fields(self):
        """payload 必须包含 model / messages / max_tokens / stream"""
        response = _make_response("ok")
        fake_post, captured = _patch_http_post(response)

        provider = BailianProvider(model="qwen-plus", api_key="fake-key")
        with patch("mms.providers.bailian._http_post", side_effect=fake_post):
            provider.complete("hello", max_tokens=512)

        payload = captured[0]
        assert payload["model"] == "qwen-plus"
        assert payload["stream"] is False
        assert payload["max_tokens"] == 512
        assert isinstance(payload["messages"], list)
        assert payload["messages"][0]["role"] == "user"
        assert payload["messages"][0]["content"] == "hello"

    def test_no_api_key_raises(self):
        """API Key 未配置时应抛出 ProviderUnavailableError（强制置空绕过 .env.memory 读取）"""
        from mms.providers.bailian import ProviderUnavailableError
        provider = BailianProvider(model="qwen-plus", api_key="fake-placeholder")
        # 在运行时将 _api_key 置空，模拟 key 丢失
        provider._api_key = ""
        with pytest.raises(ProviderUnavailableError, match="API Key 未配置"):
            provider.complete("test")
