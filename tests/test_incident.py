"""
tests/test_incident.py — 崩溃现场保全 observability/incident.py 单元测试

覆盖点：
  - set_last_llm_context / get_last_llm_context 正确存取
  - KeyboardInterrupt 走原始 sys.__excepthook__，不介入
  - 致命崩溃时创建 incident 目录和核心文件
  - call_stack.dmp 包含异常类型和局部变量
  - JSONDecodeError 时写入 prompt_context.txt（有毒提示词）
  - 无 LLM 上下文时不写 prompt_context.txt
  - incident_manifest.json 格式正确
  - 崩溃处理器调用 alert_fatal
  - 处理器内部崩溃时退化为标准输出，不二次崩溃
  - install_crash_handler() 正确替换 sys.excepthook
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_incident_module(mdr_dir: Path):
    """加载 incident 模块并将 MDR 路径指向临时目录。"""
    mods = [k for k in sys.modules if k.startswith("mms.observability.incident")]
    for m in mods:
        del sys.modules[m]
    import mms.observability.incident as inc
    inc._MDR_INCIDENT_DIR = mdr_dir / "incident"
    return inc


class TestContextVars:
    """LLM 上下文 ContextVar 读写。"""

    def test_set_and_get_last_llm_context(self, tmp_path):
        """set 后 get 应返回相同内容。"""
        inc = _make_incident_module(tmp_path)
        inc.set_last_llm_context("你好，请生成代码", "```python\nprint('hello')\n```")
        prompt, response = inc.get_last_llm_context()
        assert prompt == "你好，请生成代码"
        assert "print" in response

    def test_empty_context_returns_empty_strings(self, tmp_path):
        """未设置时返回空字符串。"""
        # 重新创建新的 ContextVar 实例以确保干净状态
        inc = _make_incident_module(tmp_path)
        # 先清空
        inc.set_last_llm_context("", "")
        prompt, response = inc.get_last_llm_context()
        assert prompt == ""
        assert response == ""


class TestCrashHandler:
    """mulan_crash_handler() 核心行为。"""

    def test_keyboard_interrupt_calls_sys_excepthook(self, tmp_path):
        """KeyboardInterrupt 应转发给 sys.__excepthook__，不创建 incident。"""
        inc = _make_incident_module(tmp_path)
        original_called = []

        with patch("sys.__excepthook__", side_effect=lambda *a: original_called.append(True)):
            try:
                raise KeyboardInterrupt("用户中断")
            except KeyboardInterrupt as e:
                inc.mulan_crash_handler(KeyboardInterrupt, e, e.__traceback__)

        assert original_called, "sys.__excepthook__ 应被调用"
        assert not (tmp_path / "incident").exists() or not list((tmp_path / "incident").iterdir()), \
            "不应创建 incident 目录"

    def test_fatal_crash_creates_incident_dir(self, tmp_path):
        """致命崩溃应在 MDR/incident/ 下创建 incident 子目录。"""
        inc = _make_incident_module(tmp_path)
        try:
            raise ValueError("模拟致命错误")
        except ValueError as e:
            inc.mulan_crash_handler(ValueError, e, e.__traceback__)

        incident_dir = tmp_path / "incident"
        assert incident_dir.exists()
        subdirs = list(incident_dir.iterdir())
        assert len(subdirs) == 1
        assert subdirs[0].name.startswith("inc_")

    def test_call_stack_dmp_contains_exc_type(self, tmp_path):
        """call_stack.dmp 应包含异常类型名称。"""
        inc = _make_incident_module(tmp_path)
        try:
            raise RuntimeError("JSON 解析失败")
        except RuntimeError as e:
            inc.mulan_crash_handler(RuntimeError, e, e.__traceback__)

        incident_dir = tmp_path / "incident"
        inc_subdirs = list(incident_dir.iterdir())
        dmp = inc_subdirs[0] / "call_stack.dmp"
        assert dmp.exists()
        content = dmp.read_text(encoding="utf-8")
        assert "RuntimeError" in content
        assert "JSON 解析失败" in content

    def test_call_stack_dmp_contains_local_variables(self, tmp_path):
        """call_stack.dmp 的局部变量区段应包含崩溃帧的变量。"""
        inc = _make_incident_module(tmp_path)

        def inner_func():
            magic_variable = "MAGIC_VALUE_12345"  # noqa: F841
            raise TypeError("类型不匹配")

        try:
            inner_func()
        except TypeError as e:
            inc.mulan_crash_handler(TypeError, e, e.__traceback__)

        incident_dir = tmp_path / "incident"
        inc_subdirs = list(incident_dir.iterdir())
        dmp = inc_subdirs[0] / "call_stack.dmp"
        content = dmp.read_text(encoding="utf-8")
        assert "magic_variable" in content
        assert "MAGIC_VALUE_12345" in content

    def test_prompt_context_written_when_llm_context_exists(self, tmp_path):
        """存在 LLM 上下文时，应写入 prompt_context.txt。"""
        inc = _make_incident_module(tmp_path)
        inc.set_last_llm_context(
            prompt="请为我生成一个 FastAPI 路由",
            response='{"route": "/api/v1/test"',  # 残缺 JSON，触发 JSONDecodeError 场景
        )
        try:
            raise json.JSONDecodeError("Expecting value", '{"route":', 9)
        except json.JSONDecodeError as e:
            inc.mulan_crash_handler(json.JSONDecodeError, e, e.__traceback__)

        incident_dir = tmp_path / "incident"
        inc_subdirs = list(incident_dir.iterdir())
        pctx = inc_subdirs[0] / "prompt_context.txt"
        assert pctx.exists()
        content = pctx.read_text(encoding="utf-8")
        assert "FastAPI" in content
        assert "route" in content

    def test_no_prompt_context_when_empty(self, tmp_path):
        """无 LLM 上下文时，不应创建 prompt_context.txt。"""
        inc = _make_incident_module(tmp_path)
        inc.set_last_llm_context("", "")  # 清空
        try:
            raise OSError("文件不存在")
        except OSError as e:
            inc.mulan_crash_handler(OSError, e, e.__traceback__)

        incident_dir = tmp_path / "incident"
        inc_subdirs = list(incident_dir.iterdir())
        pctx = inc_subdirs[0] / "prompt_context.txt"
        assert not pctx.exists()

    def test_incident_manifest_json_format(self, tmp_path):
        """incident_manifest.json 应包含 incident_id, ts, exc_type, files 字段。"""
        inc = _make_incident_module(tmp_path)
        try:
            raise KeyError("missing_key")
        except KeyError as e:
            inc.mulan_crash_handler(KeyError, e, e.__traceback__)

        incident_dir = tmp_path / "incident"
        inc_subdirs = list(incident_dir.iterdir())
        manifest_path = inc_subdirs[0] / "incident_manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        assert "incident_id" in manifest
        assert "ts" in manifest
        assert manifest["exc_type"] == "KeyError"
        assert "files" in manifest
        assert "call_stack.dmp" in manifest["files"]

    def test_crash_handler_calls_alert_fatal(self, tmp_path):
        """崩溃处理器应调用 alert_fatal() 写入告警日志。"""
        inc = _make_incident_module(tmp_path)
        called_with = []

        with patch("mms.observability.logger.alert_fatal", side_effect=lambda *a, **k: called_with.append(a)):
            try:
                raise AttributeError("对象没有该属性")
            except AttributeError as e:
                inc.mulan_crash_handler(AttributeError, e, e.__traceback__)

        assert len(called_with) > 0
        assert "AttributeError" in str(called_with[0])

    def test_crash_handler_self_safe(self, tmp_path, capsys):
        """处理器内部崩溃时退化为 stderr 输出，不向外传播异常。"""
        inc = _make_incident_module(tmp_path)
        # 让 _write_call_stack 内部抛出异常，模拟写入失败
        with patch.object(inc, "_write_call_stack", side_effect=OSError("磁盘满了")):
            try:
                raise RuntimeError("测试致命错误")
            except RuntimeError as e:
                # 不应向外抛出任何异常
                inc.mulan_crash_handler(RuntimeError, e, e.__traceback__)

        captured = capsys.readouterr()
        assert "RuntimeError" in captured.err or "CRITICAL" in captured.err


class TestInstallCrashHandler:
    """install_crash_handler() 正确安装 sys.excepthook。"""

    def test_install_replaces_sys_excepthook(self, tmp_path):
        """安装后 sys.excepthook 应指向 mulan_crash_handler。"""
        original = sys.excepthook
        try:
            inc = _make_incident_module(tmp_path)
            inc.install_crash_handler()
            assert sys.excepthook is inc.mulan_crash_handler
        finally:
            sys.excepthook = original  # 恢复，避免影响其他测试
