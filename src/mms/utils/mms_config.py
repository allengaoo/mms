"""
mms_config.py — MMS 系统配置统一加载模块（EP-125）

单例 ConfigLoader，从 docs/memory/_system/config.yaml 读取所有可调参数。
yaml 不可用（未安装）或文件不存在时，静默降级为内置默认值。

使用方式：
    from mms.utils.mms_config import cfg

    timeout = cfg.runner_timeout_llm       # int，LLM 调用超时秒数
    max_tokens = cfg.runner_max_tokens_code_generation  # int

所有属性均带降级注释，格式：
    # fallback: config.yaml → <yaml.key.path> (default=<value>)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

_HERE = Path(__file__).resolve().parent

# 配置文件搜索策略（独立项目兼容）：
#   1. 环境变量 MMS_CONFIG_PATH 指定的路径
#   2. mms 项目根目录下的 docs/memory/_system/config.yaml（作为独立项目运行）
#   3. mms 目录的父目录下的 docs/memory/_system/config.yaml（嵌入 MDP 项目运行）
def _find_config_path() -> Path:
    env_path = Path(os.environ["MMS_CONFIG_PATH"]) if "MMS_CONFIG_PATH" in os.environ else None
    if env_path and env_path.exists():
        return env_path
    candidates = [
        _HERE / "docs" / "memory" / "_system" / "config.yaml",
        _HERE.parent.parent / "docs" / "memory" / "_system" / "config.yaml",
    ]
    for c in candidates:
        if c.exists():
            return c
    return _HERE / "docs" / "memory" / "_system" / "config.yaml"  # 不存在时降级到默认


_CONFIG_PATH = _find_config_path()


def _load_yaml(path: Path) -> Dict[str, Any]:
    """加载 YAML 文件，失败时返回空 dict。"""
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore[import]
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _get(data: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    """安全地从嵌套字典中取值，键不存在时返回 default。"""
    cur = data
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
        if cur is default:
            return default
    return cur


class MmsConfig:
    """
    MMS 系统配置单例。

    所有字段从 config.yaml 读取，yaml 不可用时使用内置默认值。
    属性名规则：<section>_<subsection>_<key>（下划线分隔）
    """

    def __init__(self, config_path: Path = _CONFIG_PATH) -> None:
        self._raw = _load_yaml(config_path)

    # ── runner.timeout ────────────────────────────────────────────────────

    @property
    def runner_timeout_llm(self) -> int:
        # fallback: config.yaml → runner.timeout.llm_seconds (default=180)
        return int(_get(self._raw, "runner", "timeout", "llm_seconds", default=180))

    @property
    def runner_timeout_arch_check(self) -> int:
        # fallback: config.yaml → runner.timeout.arch_check_seconds (default=30)
        return int(_get(self._raw, "runner", "timeout", "arch_check_seconds", default=30))

    @property
    def runner_timeout_test(self) -> int:
        # fallback: config.yaml → runner.timeout.test_seconds (default=120)
        return int(_get(self._raw, "runner", "timeout", "test_seconds", default=120))

    @property
    def runner_timeout_postcheck_test(self) -> int:
        # fallback: config.yaml → runner.timeout.postcheck_test_seconds (default=300)
        return int(_get(self._raw, "runner", "timeout", "postcheck_test_seconds", default=300))

    @property
    def runner_timeout_postcheck_drift(self) -> int:
        # fallback: config.yaml → runner.timeout.postcheck_drift_seconds (default=60)
        return int(_get(self._raw, "runner", "timeout", "postcheck_drift_seconds", default=60))

    @property
    def runner_timeout_unit_cmd(self) -> int:
        # fallback: config.yaml → runner.timeout.unit_cmd_seconds (default=120)
        return int(_get(self._raw, "runner", "timeout", "unit_cmd_seconds", default=120))

    @property
    def runner_timeout_dream_git(self) -> int:
        # fallback: config.yaml → runner.timeout.dream_git_seconds (default=30)
        return int(_get(self._raw, "runner", "timeout", "dream_git_seconds", default=30))

    @property
    def runner_timeout_synthesizer_index(self) -> int:
        # fallback: config.yaml → runner.timeout.synthesizer_index_seconds (default=30)
        return int(_get(self._raw, "runner", "timeout", "synthesizer_index_seconds", default=30))

    # ── runner.retry ──────────────────────────────────────────────────────

    @property
    def runner_max_retries(self) -> int:
        # fallback: config.yaml → runner.retry.max_retries (default=2)
        return int(_get(self._raw, "runner", "retry", "max_retries", default=2))

    # ── runner.internal_review ────────────────────────────────────────────

    @property
    def runner_enable_internal_review(self) -> bool:
        # fallback: config.yaml → runner.enable_internal_review (default=False)
        # 也可通过环境变量 MMS_ENABLE_INTERNAL_REVIEW=true 开启
        val = _get(self._raw, "runner", "enable_internal_review", default=False)
        return bool(val)

    @property
    def runner_enable_auto_impacts(self) -> bool:
        """是否自动建 impacts 边（tag 集合重叠检测）。默认 false，避免无谓计算。"""
        val = _get(self._raw, "runner", "enable_auto_impacts", default=False)
        return bool(val)

    # ── graph.confidence_threshold ────────────────────────────────────────

    @property
    def graph_confidence_threshold(self) -> int:
        """
        hybrid_search 的图置信度阈值：图检索结果少于此数时触发 keyword fallback。
        默认 3。可通过 config.yaml 的 graph.confidence_threshold 配置。
        """
        val = _get(self._raw, "graph", "confidence_threshold", default=3)
        try:
            return int(val)
        except (TypeError, ValueError):
            return 3

    # ── runner.scope_guard ────────────────────────────────────────────────

    @property
    def runner_scope_guard_strict(self) -> bool:
        # fallback: config.yaml → runner.scope_guard.strict (default=True)
        val = _get(self._raw, "runner", "scope_guard", "strict", default=True)
        return bool(val)

    # ── runner.max_tokens ─────────────────────────────────────────────────

    @property
    def runner_max_tokens_code_generation(self) -> int:
        # fallback: config.yaml → runner.max_tokens.code_generation (default=4096)
        return int(_get(self._raw, "runner", "max_tokens", "code_generation", default=4096))

    @property
    def runner_max_tokens_code_review(self) -> int:
        # fallback: config.yaml → runner.max_tokens.code_review (default=4096)
        return int(_get(self._raw, "runner", "max_tokens", "code_review", default=4096))

    @property
    def runner_max_tokens_distillation(self) -> int:
        # fallback: config.yaml → runner.max_tokens.distillation (default=3000)
        return int(_get(self._raw, "runner", "max_tokens", "distillation", default=3000))

    @property
    def runner_max_tokens_intent_routing(self) -> int:
        # fallback: config.yaml → runner.max_tokens.intent_routing (default=200)
        return int(_get(self._raw, "runner", "max_tokens", "intent_routing", default=200))

    @property
    def runner_max_tokens_context_injection(self) -> int:
        # fallback: config.yaml → runner.max_tokens.context_injection (default=100)
        return int(_get(self._raw, "runner", "max_tokens", "context_injection", default=100))

    @property
    def runner_max_tokens_fix_gen(self) -> int:
        # fallback: config.yaml → runner.max_tokens.fix_gen (default=2048)
        return int(_get(self._raw, "runner", "max_tokens", "fix_gen", default=2048))

    # ── dag.generation ────────────────────────────────────────────────────

    @property
    def dag_generation_max_tokens(self) -> int:
        # fallback: config.yaml → dag.generation.max_tokens (default=8192)
        return int(_get(self._raw, "dag", "generation", "max_tokens", default=8192))

    @property
    def dag_generation_retry_multiplier(self) -> int:
        # fallback: config.yaml → dag.generation.max_tokens_retry_multiplier (default=2)
        return int(_get(self._raw, "dag", "generation", "max_tokens_retry_multiplier", default=2))

    # ── dag.atomicity_thresholds ──────────────────────────────────────────

    @property
    def dag_token_budget_8b(self) -> int:
        # fallback: config.yaml → dag.atomicity_thresholds.max_context_tokens_8b (default=4000)
        return int(_get(self._raw, "dag", "atomicity_thresholds", "max_context_tokens_8b", default=4000))

    @property
    def dag_token_budget_16b(self) -> int:
        # fallback: config.yaml → dag.atomicity_thresholds.max_context_tokens_16b (default=8000)
        return int(_get(self._raw, "dag", "atomicity_thresholds", "max_context_tokens_16b", default=8000))

    @property
    def dag_score_threshold_8b(self) -> float:
        # fallback: config.yaml → dag.atomicity_thresholds.score_threshold_8b (default=0.75)
        return float(_get(self._raw, "dag", "atomicity_thresholds", "score_threshold_8b", default=0.75))

    @property
    def dag_score_threshold_16b(self) -> float:
        # fallback: config.yaml → dag.atomicity_thresholds.score_threshold_16b (default=0.50)
        return float(_get(self._raw, "dag", "atomicity_thresholds", "score_threshold_16b", default=0.50))

    @property
    def dag_annotate_threshold_high(self) -> float:
        # fallback: config.yaml → dag.atomicity_thresholds.annotate_threshold_high (default=0.85)
        return float(_get(self._raw, "dag", "atomicity_thresholds", "annotate_threshold_high", default=0.85))

    @property
    def dag_annotate_threshold_mid(self) -> float:
        # fallback: config.yaml → dag.atomicity_thresholds.annotate_threshold_mid (default=0.60)
        return float(_get(self._raw, "dag", "atomicity_thresholds", "annotate_threshold_mid", default=0.60))

    @property
    def dag_report_threshold(self) -> float:
        # fallback: config.yaml → dag.atomicity_thresholds.report_threshold (default=0.75)
        return float(_get(self._raw, "dag", "atomicity_thresholds", "report_threshold", default=0.75))

    # ── llm.google ────────────────────────────────────────────────────────

    @property
    def llm_google_connect_timeout(self) -> int:
        # fallback: config.yaml → llm.google.connect_timeout_seconds (default=8)
        return int(_get(self._raw, "llm", "google", "connect_timeout_seconds", default=8))

    @property
    def llm_google_generate_timeout(self) -> int:
        # fallback: config.yaml → llm.google.generate_timeout_seconds (default=180)
        return int(_get(self._raw, "llm", "google", "generate_timeout_seconds", default=180))

    @property
    def llm_google_min_output_tokens(self) -> int:
        # fallback: config.yaml → llm.google.min_output_tokens (default=8192)
        return int(_get(self._raw, "llm", "google", "min_output_tokens", default=8192))

    # ── llm.bailian ───────────────────────────────────────────────────────

    @property
    def llm_bailian_connect_timeout(self) -> int:
        # fallback: config.yaml → llm.bailian.connect_timeout_seconds (default=8)
        # 注：config.yaml 中 bailian 节在 llm.bailian，若不存在则读 llm 默认
        val = _get(self._raw, "llm", "bailian", "connect_timeout_seconds", default=None)
        if val is None:
            # bailian 未单独配置，读 google 同名字段作为通用超时参考，或使用内置值
            return 8
        return int(val)

    @property
    def llm_bailian_generate_timeout(self) -> int:
        # fallback: config.yaml → llm.bailian.generate_timeout_seconds (default=120)
        val = _get(self._raw, "llm", "bailian", "generate_timeout_seconds", default=None)
        return int(val) if val is not None else 120

    @property
    def llm_bailian_embed_timeout(self) -> int:
        # fallback: config.yaml → llm.bailian.embed_timeout_seconds (default=30)
        val = _get(self._raw, "llm", "bailian", "embed_timeout_seconds", default=None)
        return int(val) if val is not None else 30

    # ── llm.ollama (deprecated, 保留以兼容旧 config.yaml，当前不使用) ────

    @property
    def llm_ollama_connect_timeout(self) -> int:
        """Deprecated: Ollama 已移除，保留属性以防旧 config.yaml 报错。"""
        return int(_get(self._raw, "llm", "ollama", "connect_timeout_seconds", default=3))

    @property
    def llm_ollama_generate_timeout(self) -> int:
        """Deprecated."""
        return int(_get(self._raw, "llm", "ollama", "generate_timeout_seconds", default=120))

    @property
    def llm_ollama_embed_timeout(self) -> int:
        """Deprecated."""
        return int(_get(self._raw, "llm", "ollama", "embed_timeout_seconds", default=30))

    # ── trace（诊断追踪，EP-127） ─────────────────────────────────────────────

    @property
    def trace_enabled(self) -> bool:
        # fallback: config.yaml → trace.enabled (default=false)
        return bool(_get(self._raw, "trace", "enabled", default=False))

    @property
    def trace_default_level(self) -> int:
        # fallback: config.yaml → trace.default_level (default=4)
        return int(_get(self._raw, "trace", "default_level", default=4))

    @property
    def trace_max_events(self) -> int:
        # fallback: config.yaml → trace.max_events_per_ep (default=5000)
        return int(_get(self._raw, "trace", "max_events_per_ep", default=5000))

    @property
    def trace_preview_chars(self) -> int:
        # fallback: config.yaml → trace.preview_chars (default=200)
        return int(_get(self._raw, "trace", "preview_chars", default=200))

    @property
    def trace_report_auto_save(self) -> bool:
        # fallback: config.yaml → trace.report.auto_save (default=true)
        return bool(_get(self._raw, "trace", "report", "auto_save", default=True))

    @property
    def trace_report_use_color(self) -> bool:
        # fallback: config.yaml → trace.report.use_color (default=true)
        return bool(_get(self._raw, "trace", "report", "use_color", default=True))

    # ── runner.token_budget ───────────────────────────────────────────────────

    @property
    def runner_token_budget_fast(self) -> int:
        # fallback: config.yaml → runner.token_budget.fast (default=2000)
        return int(_get(self._raw, "runner", "token_budget", "fast", default=2000))

    @property
    def runner_token_budget_capable(self) -> int:
        # fallback: config.yaml → runner.token_budget.capable (default=4000)
        return int(_get(self._raw, "runner", "token_budget", "capable", default=4000))

    # ── compare.truncate ──────────────────────────────────────────────────────

    @property
    def compare_diff_truncate_chars(self) -> int:
        # fallback: config.yaml → compare.diff_truncate_chars (default=3000)
        return int(_get(self._raw, "compare", "diff_truncate_chars", default=3000))

    @property
    def compare_code_truncate_chars(self) -> int:
        # fallback: config.yaml → compare.code_truncate_chars (default=4000)
        return int(_get(self._raw, "compare", "code_truncate_chars", default=4000))

    # ── gc.edge_decay（图谱边衰减配置，Phase 2 新增） ────────────────────────────

    @property
    def gc_edge_decay_factor(self) -> float:
        # fallback: config.yaml → gc.edge_decay_factor (default=0.8)
        return float(_get(self._raw, "gc", "edge_decay_factor", default=0.8))

    @property
    def gc_edge_prune_threshold(self) -> float:
        # fallback: config.yaml → gc.edge_prune_threshold (default=0.2)
        return float(_get(self._raw, "gc", "edge_prune_threshold", default=0.2))

    @property
    def gc_edge_decay_window_eps(self) -> int:
        # fallback: config.yaml → gc.edge_decay_window_eps (default=20)
        return int(_get(self._raw, "gc", "edge_decay_window_eps", default=20))

    # ── analysis（AST 解析器配置） ─────────────────────────────────────────────

    @property
    def analysis_use_tree_sitter(self) -> bool:
        """
        是否启用 Tree-sitter 作为 Java/Go AST 解析后端。
        默认 False（使用内置正则解析器）。
        启用条件：1. 此配置为 true；2. 已安装 pip install "mulan[tree_sitter]"
        fallback: config.yaml → analysis.use_tree_sitter (default=false)
        """
        return bool(_get(self._raw, "analysis", "use_tree_sitter", default=False))

    @property
    def analysis_tree_sitter_languages(self) -> list:
        """
        Tree-sitter 启用时处理的语言列表。Python 始终使用标准库 ast，不在此列表中。
        fallback: config.yaml → analysis.tree_sitter_languages (default=["java", "go"])
        """
        val = _get(self._raw, "analysis", "tree_sitter_languages", default=["java", "go"])
        return list(val) if isinstance(val, (list, tuple)) else ["java", "go"]

    # ── benchmark ─────────────────────────────────────────────────────────────

    @property
    def benchmark_max_context_chars(self) -> int:
        # fallback: config.yaml → benchmark.max_context_chars (default=12000)
        return int(_get(self._raw, "benchmark", "max_context_chars", default=12000))

    @property
    def benchmark_codegen_max_tokens(self) -> int:
        # fallback: config.yaml → benchmark.codegen_max_tokens (default=2048)
        return int(_get(self._raw, "benchmark", "codegen_max_tokens", default=2048))

    @property
    def benchmark_result_preview_chars(self) -> int:
        # fallback: config.yaml → benchmark.result_preview_chars (default=3000)
        return int(_get(self._raw, "benchmark", "result_preview_chars", default=3000))


# ── 全局单例 ──────────────────────────────────────────────────────────────────

_cfg: Optional[MmsConfig] = None


def get_cfg(config_path: Path = _CONFIG_PATH) -> MmsConfig:
    """返回全局 MmsConfig 单例（懒加载）。"""
    global _cfg
    if _cfg is None:
        _cfg = MmsConfig(config_path)
    return _cfg


# 快捷别名，直接 `from mms_config import cfg` 使用
cfg: MmsConfig = get_cfg()
