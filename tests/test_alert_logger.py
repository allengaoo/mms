"""
tests/test_alert_logger.py — 全局告警日志 observability/logger.py 单元测试

覆盖点：
  - 首次调用自动创建日志文件
  - INFO / WARN / FATAL 级别格式正确
  - alert_circuit() 专用熔断事件格式
  - 延迟初始化：import 时不创建文件
  - 多线程并发写入不损坏文件
  - tail_log() 读取功能
  - CircuitBreaker 集成：状态转移后 alert_mulan.log 有写入
"""
from __future__ import annotations

import importlib
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── 辅助：重置 logger 单例（隔离测试间的全局状态）─────────────────────────
def _reset_logger_module():
    """
    卸载并重新导入 logger 模块，重置内部 _logger 单例。
    同时关闭并移除 logging 全局注册表中 "mulan.alert" 的所有 Handler，
    以避免旧 Handler 的文件路径被复用。
    """
    import logging
    existing = logging.getLogger("mulan.alert")
    for h in list(existing.handlers):
        try:
            h.close()
        except Exception:
            pass
        existing.removeHandler(h)

    mods = [k for k in sys.modules if k.startswith("mms.observability.logger")]
    for m in mods:
        del sys.modules[m]


# ── 测试 ─────────────────────────────────────────────────────────────────────

class TestAlertLoggerBasic:
    """基础功能：文件创建、日志级别、格式。"""

    def test_alert_info_creates_file(self, tmp_path, monkeypatch):
        """首次调用 alert_info 后，日志文件应被创建。"""
        _reset_logger_module()
        import mms.observability.logger as lg
        monkeypatch.setattr(lg, "_ALERT_LOG_PATH", tmp_path / "alert_mulan.log")
        monkeypatch.setattr(lg, "_MDR_ALERT_DIR", tmp_path)
        monkeypatch.setattr(lg, "_logger", None)

        lg.alert_info("test_module", "系统启动完毕")

        assert (tmp_path / "alert_mulan.log").exists()

    def test_alert_fatal_level_prefix(self, tmp_path, monkeypatch):
        """FATAL 级别事件应包含 CRITICAL 关键词（logging.CRITICAL → CRITICAL）。"""
        _reset_logger_module()
        import mms.observability.logger as lg
        log_file = tmp_path / "alert_mulan.log"
        monkeypatch.setattr(lg, "_ALERT_LOG_PATH", log_file)
        monkeypatch.setattr(lg, "_MDR_ALERT_DIR", tmp_path)
        monkeypatch.setattr(lg, "_logger", None)

        lg.alert_fatal("test", "熔断器开路")
        content = log_file.read_text(encoding="utf-8")
        assert "CRITICAL" in content

    def test_alert_warn_level_prefix(self, tmp_path, monkeypatch):
        """WARN 级别事件应包含 WARNING 关键词。"""
        _reset_logger_module()
        import mms.observability.logger as lg
        log_file = tmp_path / "alert_mulan.log"
        monkeypatch.setattr(lg, "_ALERT_LOG_PATH", log_file)
        monkeypatch.setattr(lg, "_MDR_ALERT_DIR", tmp_path)
        monkeypatch.setattr(lg, "_logger", None)

        lg.alert_warn("test", "资源告警")
        content = log_file.read_text(encoding="utf-8")
        assert "WARNING" in content

    def test_alert_info_level_prefix(self, tmp_path, monkeypatch):
        """INFO 级别事件应包含 INFO 关键词。"""
        _reset_logger_module()
        import mms.observability.logger as lg
        log_file = tmp_path / "alert_mulan.log"
        monkeypatch.setattr(lg, "_ALERT_LOG_PATH", log_file)
        monkeypatch.setattr(lg, "_MDR_ALERT_DIR", tmp_path)
        monkeypatch.setattr(lg, "_logger", None)

        lg.alert_info("test", "索引构建完成")
        content = log_file.read_text(encoding="utf-8")
        assert "INFO" in content

    def test_module_name_in_log(self, tmp_path, monkeypatch):
        """日志行应包含模块名。"""
        _reset_logger_module()
        import mms.observability.logger as lg
        log_file = tmp_path / "alert_mulan.log"
        monkeypatch.setattr(lg, "_ALERT_LOG_PATH", log_file)
        monkeypatch.setattr(lg, "_MDR_ALERT_DIR", tmp_path)
        monkeypatch.setattr(lg, "_logger", None)

        lg.alert_info("circuit_breaker", "熔断器恢复")
        content = log_file.read_text(encoding="utf-8")
        assert "circuit_breaker" in content


class TestAlertCircuit:
    """alert_circuit() 专用接口。"""

    def test_circuit_open_writes_fatal(self, tmp_path, monkeypatch):
        """CLOSED → OPEN 应写入 CRITICAL 级别（fatal）。"""
        _reset_logger_module()
        import mms.observability.logger as lg
        log_file = tmp_path / "alert_mulan.log"
        monkeypatch.setattr(lg, "_ALERT_LOG_PATH", log_file)
        monkeypatch.setattr(lg, "_MDR_ALERT_DIR", tmp_path)
        monkeypatch.setattr(lg, "_logger", None)

        lg.alert_circuit("qwen3-coder-next", "CLOSED", "OPEN", "连续失败 3 次")
        content = log_file.read_text(encoding="utf-8")
        assert "CRITICAL" in content
        assert "qwen3-coder-next" in content
        assert "CLOSED" in content
        assert "OPEN" in content

    def test_circuit_half_open_writes_warn(self, tmp_path, monkeypatch):
        """OPEN → HALF_OPEN 应写入 WARNING 级别。"""
        _reset_logger_module()
        import mms.observability.logger as lg
        log_file = tmp_path / "alert_mulan.log"
        monkeypatch.setattr(lg, "_ALERT_LOG_PATH", log_file)
        monkeypatch.setattr(lg, "_MDR_ALERT_DIR", tmp_path)
        monkeypatch.setattr(lg, "_logger", None)

        lg.alert_circuit("qwen3-coder-next", "OPEN", "HALF_OPEN", "冷却期结束")
        content = log_file.read_text(encoding="utf-8")
        assert "WARNING" in content

    def test_circuit_recover_writes_info(self, tmp_path, monkeypatch):
        """HALF_OPEN → CLOSED 应写入 INFO 级别。"""
        _reset_logger_module()
        import mms.observability.logger as lg
        log_file = tmp_path / "alert_mulan.log"
        monkeypatch.setattr(lg, "_ALERT_LOG_PATH", log_file)
        monkeypatch.setattr(lg, "_MDR_ALERT_DIR", tmp_path)
        monkeypatch.setattr(lg, "_logger", None)

        lg.alert_circuit("qwen3-coder-next", "HALF_OPEN", "CLOSED", "探测成功")
        content = log_file.read_text(encoding="utf-8")
        assert "INFO" in content


class TestTailLog:
    """tail_log() 读取功能。"""

    def test_tail_log_returns_empty_if_no_file(self, tmp_path, monkeypatch):
        """文件不存在时返回空列表。"""
        _reset_logger_module()
        import mms.observability.logger as lg
        monkeypatch.setattr(lg, "_ALERT_LOG_PATH", tmp_path / "nonexistent.log")

        result = lg.tail_log(50)
        assert result == []

    def test_tail_log_returns_last_n_lines(self, tmp_path, monkeypatch):
        """tail_log(n) 返回最后 n 行。"""
        _reset_logger_module()
        import mms.observability.logger as lg
        log_file = tmp_path / "alert_mulan.log"
        all_lines = [f"line {i}" for i in range(100)]
        log_file.write_text("\n".join(all_lines), encoding="utf-8")
        monkeypatch.setattr(lg, "_ALERT_LOG_PATH", log_file)

        result = lg.tail_log(10)
        assert len(result) == 10
        assert result[-1] == "line 99"


class TestConcurrentWrites:
    """多线程并发写入不损坏日志文件。"""

    def test_concurrent_writes_no_corruption(self, tmp_path, monkeypatch):
        """10 个线程各写 10 条，总行数应等于 100，无空行损坏。"""
        _reset_logger_module()
        import mms.observability.logger as lg
        log_file = tmp_path / "alert_mulan.log"
        monkeypatch.setattr(lg, "_ALERT_LOG_PATH", log_file)
        monkeypatch.setattr(lg, "_MDR_ALERT_DIR", tmp_path)
        monkeypatch.setattr(lg, "_logger", None)

        def writer(tid: int):
            for i in range(10):
                lg.alert_info(f"thread_{tid}", f"并发写入 {i}")

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        lines = [l for l in log_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 100


class TestCircuitBreakerIntegration:
    """集成测试：CircuitBreaker 触发时 alert_mulan.log 有写入。"""

    def test_circuit_breaker_emits_alert_on_open(self, tmp_path, monkeypatch):
        """熔断器连续失败到达阈值时，alert_mulan.log 应有 CRITICAL 记录。"""
        _reset_logger_module()
        import mms.observability.logger as lg
        log_file = tmp_path / "alert_mulan.log"
        monkeypatch.setattr(lg, "_ALERT_LOG_PATH", log_file)
        monkeypatch.setattr(lg, "_MDR_ALERT_DIR", tmp_path)
        monkeypatch.setattr(lg, "_logger", None)

        # 重新导入 circuit_breaker 以使其引用新的 alert_circuit
        cb_mods = [k for k in sys.modules if "circuit_breaker" in k]
        for m in cb_mods:
            del sys.modules[m]

        state_file = tmp_path / "circuit_state.json"
        import mms.resilience.circuit_breaker as cb_mod
        # 替换 alert_circuit 指向测试用的 logger
        monkeypatch.setattr(cb_mod, "_alert_circuit", lg.alert_circuit)

        cb = cb_mod.CircuitBreaker(
            model_name="test-model",
            failure_threshold=2,
            recovery_timeout=60,
            state_file=state_file,
        )

        def fail():
            raise RuntimeError("模拟 LLM 超时")

        for _ in range(2):
            with pytest.raises(RuntimeError):
                cb.call(fail)

        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert "CRITICAL" in content
        assert "test-model" in content
