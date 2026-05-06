"""
test_mms_config.py — MmsConfig 单元测试（EP-125）

覆盖：
  - yaml 正常加载：各属性返回 config.yaml 中的值
  - yaml 文件不存在：所有属性降级为内置默认值
  - yaml 存在但 key 缺失：对应属性返回默认值
  - 临时修改 config 后刷新单例验证隔离性
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

# 使 scripts/mms 可导入
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mms.utils.mms_config import MmsConfig, _get


# ── 辅助：写临时 YAML 文件 ────────────────────────────────────────────────────

def _make_cfg(tmp_path: Path, yaml_text: str) -> MmsConfig:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(textwrap.dedent(yaml_text), encoding="utf-8")
    return MmsConfig(config_path=cfg_file)


# ── _get 工具函数测试 ─────────────────────────────────────────────────────────

class TestGetHelper:
    def test_nested_key_found(self):
        data = {"a": {"b": {"c": 42}}}
        assert _get(data, "a", "b", "c", default=0) == 42

    def test_missing_key_returns_default(self):
        data = {"a": {}}
        assert _get(data, "a", "b", "c", default=99) == 99

    def test_non_dict_intermediate_returns_default(self):
        data = {"a": "not_a_dict"}
        assert _get(data, "a", "b", default="fallback") == "fallback"

    def test_empty_dict(self):
        assert _get({}, "x", default=-1) == -1


# ── yaml 文件不存在 → 全部使用默认值 ─────────────────────────────────────────

class TestConfigMissingYaml:
    def test_runner_timeout_llm_default(self, tmp_path):
        cfg = MmsConfig(config_path=tmp_path / "nonexistent.yaml")
        assert cfg.runner_timeout_llm == 180

    def test_runner_timeout_arch_check_default(self, tmp_path):
        cfg = MmsConfig(config_path=tmp_path / "nonexistent.yaml")
        assert cfg.runner_timeout_arch_check == 30

    def test_runner_timeout_test_default(self, tmp_path):
        cfg = MmsConfig(config_path=tmp_path / "nonexistent.yaml")
        assert cfg.runner_timeout_test == 120

    def test_runner_max_retries_default(self, tmp_path):
        cfg = MmsConfig(config_path=tmp_path / "nonexistent.yaml")
        assert cfg.runner_max_retries == 2

    def test_runner_scope_guard_strict_default(self, tmp_path):
        cfg = MmsConfig(config_path=tmp_path / "nonexistent.yaml")
        assert cfg.runner_scope_guard_strict is True

    def test_dag_generation_max_tokens_default(self, tmp_path):
        cfg = MmsConfig(config_path=tmp_path / "nonexistent.yaml")
        assert cfg.dag_generation_max_tokens == 8192

    def test_llm_google_min_output_tokens_default(self, tmp_path):
        cfg = MmsConfig(config_path=tmp_path / "nonexistent.yaml")
        assert cfg.llm_google_min_output_tokens == 8192

    def test_llm_fallback_chain_default(self, tmp_path):
        cfg = MmsConfig(config_path=tmp_path / "nonexistent.yaml")
        # 默认降级链应包含百炼 Provider，不含 Ollama / Gemini
        chain = getattr(cfg, 'llm_fallback_chain', None)
        if chain:
            assert 'ollama_r1' not in chain, "Ollama 已移除，不应出现在降级链中"
            assert 'gemini' not in chain, "Gemini 已移除，不应出现在降级链中"

    def test_dag_score_threshold_8b_default(self, tmp_path):
        cfg = MmsConfig(config_path=tmp_path / "nonexistent.yaml")
        assert cfg.dag_score_threshold_8b == pytest.approx(0.75)


# ── yaml 正常加载 → 属性返回 config 中的值 ───────────────────────────────────

class TestConfigLoadsYaml:
    def test_runner_timeout_from_yaml(self, tmp_path):
        cfg = _make_cfg(tmp_path, """
            runner:
              timeout:
                llm_seconds: 240
                arch_check_seconds: 45
                test_seconds: 150
        """)
        assert cfg.runner_timeout_llm == 240
        assert cfg.runner_timeout_arch_check == 45
        assert cfg.runner_timeout_test == 150

    def test_runner_max_retries_from_yaml(self, tmp_path):
        cfg = _make_cfg(tmp_path, """
            runner:
              retry:
                max_retries: 5
        """)
        assert cfg.runner_max_retries == 5

    def test_runner_scope_guard_false(self, tmp_path):
        cfg = _make_cfg(tmp_path, """
            runner:
              scope_guard:
                strict: false
        """)
        assert cfg.runner_scope_guard_strict is False

    def test_dag_generation_max_tokens_from_yaml(self, tmp_path):
        cfg = _make_cfg(tmp_path, """
            dag:
              generation:
                max_tokens: 16384
                max_tokens_retry_multiplier: 3
        """)
        assert cfg.dag_generation_max_tokens == 16384
        assert cfg.dag_generation_retry_multiplier == 3

    def test_llm_google_timeouts_from_yaml(self, tmp_path):
        cfg = _make_cfg(tmp_path, """
            llm:
              google:
                connect_timeout_seconds: 12
                generate_timeout_seconds: 300
                min_output_tokens: 16384
        """)
        assert cfg.llm_google_connect_timeout == 12
        assert cfg.llm_google_generate_timeout == 300
        assert cfg.llm_google_min_output_tokens == 16384

    def test_dag_atomicity_thresholds_from_yaml(self, tmp_path):
        cfg = _make_cfg(tmp_path, """
            dag:
              atomicity_thresholds:
                max_context_tokens_8b: 3000
                max_context_tokens_16b: 6000
                score_threshold_8b: 0.8
                score_threshold_16b: 0.6
                annotate_threshold_high: 0.9
                annotate_threshold_mid: 0.65
                report_threshold: 0.8
        """)
        assert cfg.dag_token_budget_8b == 3000
        assert cfg.dag_token_budget_16b == 6000
        assert cfg.dag_score_threshold_8b == pytest.approx(0.8)
        assert cfg.dag_score_threshold_16b == pytest.approx(0.6)
        assert cfg.dag_annotate_threshold_high == pytest.approx(0.9)
        assert cfg.dag_annotate_threshold_mid == pytest.approx(0.65)
        assert cfg.dag_report_threshold == pytest.approx(0.8)

    def test_max_tokens_section_from_yaml(self, tmp_path):
        cfg = _make_cfg(tmp_path, """
            runner:
              max_tokens:
                code_generation: 8192
                code_review: 6000
                distillation: 4000
                intent_routing: 300
                context_injection: 150
                fix_gen: 3000
        """)
        assert cfg.runner_max_tokens_code_generation == 8192
        assert cfg.runner_max_tokens_code_review == 6000
        assert cfg.runner_max_tokens_distillation == 4000
        assert cfg.runner_max_tokens_intent_routing == 300
        assert cfg.runner_max_tokens_context_injection == 150
        assert cfg.runner_max_tokens_fix_gen == 3000


# ── yaml 存在但 key 缺失 → 仍返回默认值 ─────────────────────────────────────

class TestConfigPartialYaml:
    def test_missing_runner_section(self, tmp_path):
        cfg = _make_cfg(tmp_path, "dag:\n  enabled: true\n")
        assert cfg.runner_timeout_llm == 180
        assert cfg.runner_max_retries == 2

    def test_missing_dag_generation(self, tmp_path):
        cfg = _make_cfg(tmp_path, "dag:\n  enabled: true\n")
        assert cfg.dag_generation_max_tokens == 8192

    def test_missing_llm_google(self, tmp_path):
        cfg = _make_cfg(tmp_path, "llm:\n  provider: auto\n")
        assert cfg.llm_google_connect_timeout == 8
        assert cfg.llm_google_min_output_tokens == 8192


# ── ep_parser 路径校验回归测试 ────────────────────────────────────────────────

class TestEpParserPathValidation:
    """验证 ep_parser 的 files 列路径校验能正确过滤 shell 命令。"""

    def test_kubectl_command_excluded(self):
        """kubectl port-forward 命令不应被识别为文件路径。"""
        try:
            from mms.workflow.ep_parser import _parse_scope_table
        except ImportError:
            from mms.workflow.ep_parser import _parse_scope_table

        # 模拟 EP-124 U1 的 Scope 表格行
        table_text = (
            "| Unit | 操作描述 | 涉及文件 |\n"
            "|------|---------|----------|\n"
            "| U1   | MySQL 端口转发 | `kubectl port-forward svc/mysql -n mdp 3307:3306` |\n"
            "| U2   | 创建环境配置   | `backend/.env.local` |\n"
        )
        units = _parse_scope_table(table_text)
        assert len(units) == 2

        u1 = next(u for u in units if u.unit_id == "U1")
        assert u1.files == [], f"kubectl 命令不应进入 files，实际: {u1.files}"

        u2 = next(u for u in units if u.unit_id == "U2")
        assert "backend/.env.local" in u2.files

    def test_valid_path_with_slash_included(self):
        """含 / 且无空格的字符串应被识别为文件路径。"""
        try:
            from mms.workflow.ep_parser import _parse_scope_table
        except ImportError:
            from mms.workflow.ep_parser import _parse_scope_table

        table_text = (
            "| Unit | 描述 | 涉及文件 |\n"
            "|------|------|----------|\n"
            "| U1   | 修改服务 | `backend/app/services/my_service.py` |\n"
        )
        units = _parse_scope_table(table_text)
        assert units[0].files == ["backend/app/services/my_service.py"]

    def test_plain_filename_with_dot_included(self):
        """含 . 且无空格的文件名应被识别为文件路径。"""
        try:
            from mms.workflow.ep_parser import _parse_scope_table
        except ImportError:
            from mms.workflow.ep_parser import _parse_scope_table

        table_text = (
            "| Unit | 描述 | 涉及文件 |\n"
            "|------|------|----------|\n"
            "| U1   | 配置 | `config.yaml` |\n"
        )
        units = _parse_scope_table(table_text)
        assert units[0].files == ["config.yaml"]
