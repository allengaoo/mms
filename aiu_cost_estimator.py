"""
aiu_cost_estimator.py — AIU 代价估算器

类比数据库查询优化器的 Cost-Based Optimizer（CBO）。
为每个 AIU 步骤估算执行代价，决定：
  - token_budget：分配多少上下文 token
  - model_hint：推荐用哪个模型执行
  - context_files_ranked：按相关性排序的文件列表
  - exec_priority：同 order 内的执行优先级

代价模型（类比 CBO 中的 Cardinality Estimation）：
  1. 文件复杂度统计（行数、函数数、import 深度）
  2. 层间传播代价（修改 L3 → 代价传播至 L4/L5）
  3. 历史成功率（从 feedback_stats.jsonl 读取）
  4. AIU 类型固有代价（基于经验的基准 token 消耗）

EP-129 | 2026-04-22
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
try:
    from _paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE.parent.parent
_FEEDBACK_STATS = _ROOT / "docs" / "memory" / "_system" / "feedback_stats.jsonl"

# ── 可配置常量（硬编码为 fallback，优先从 mms_config 读取）────────────────────

try:
    import sys as _sys
    _sys.path.insert(0, str(_HERE))
    from mms_config import cfg as _cfg  # type: ignore[import]
    _TOKEN_MIN: int = int(getattr(_cfg, "cost_estimator_token_min", 1500))
    _TOKEN_MAX: int = int(getattr(_cfg, "cost_estimator_token_max", 16000))
    _DEFAULT_SUCCESS_RATE: float = float(getattr(_cfg, "cost_estimator_default_success_rate", 0.8))
    _CHARS_PER_TOKEN: int = int(getattr(_cfg, "cost_estimator_chars_per_token", 4))
    _MIN_TOKEN_FOR_FILE: int = int(getattr(_cfg, "cost_estimator_min_token_for_file", 200))
    _UNKNOWN_FILE_TOKEN: int = int(getattr(_cfg, "cost_estimator_unknown_file_token", 500))
    _FILES_FOR_COST: int = int(getattr(_cfg, "cost_estimator_files_for_cost", 3))
except (ImportError, AttributeError):
    _TOKEN_MIN = 1500
    _TOKEN_MAX = 16000
    _DEFAULT_SUCCESS_RATE = 0.8
    _CHARS_PER_TOKEN = 4
    _MIN_TOKEN_FOR_FILE = 200
    _UNKNOWN_FILE_TOKEN = 500
    _FILES_FOR_COST = 3

import logging

_logger = logging.getLogger(__name__)

try:
    import sys as _sys
    _sys.path.insert(0, str(_HERE))
    from aiu_types import AIUType, AIUStep, AIU_EXEC_ORDER  # type: ignore[import]
except ImportError:
    try:
        from mms.aiu_types import AIUType, AIUStep, AIU_EXEC_ORDER  # type: ignore[import]
    except ImportError:
        raise


# ── AIU 类型固有基准代价（tokens）────────────────────────────────────────────

# 基于实践经验：每种 AIU 执行时所需的最小上下文 token 数
AIU_BASE_COST: Dict[str, int] = {
    AIUType.SCHEMA_ADD_FIELD.value:         2500,
    AIUType.SCHEMA_MODIFY_FIELD.value:      2000,
    AIUType.SCHEMA_ADD_RELATION.value:      3000,
    AIUType.CONTRACT_ADD_REQUEST.value:     1500,
    AIUType.CONTRACT_ADD_RESPONSE.value:    1500,
    AIUType.CONTRACT_MODIFY_RESPONSE.value: 1800,
    AIUType.LOGIC_ADD_CONDITION.value:      2500,
    AIUType.LOGIC_ADD_BRANCH.value:         3000,
    AIUType.LOGIC_ADD_LOOP.value:           3500,
    AIUType.LOGIC_EXTRACT_METHOD.value:     3500,
    AIUType.LOGIC_ADD_GUARD.value:          2000,
    AIUType.QUERY_ADD_SELECT.value:         2500,
    AIUType.QUERY_ADD_FILTER.value:         2000,
    AIUType.MUTATION_ADD_INSERT.value:      3000,
    AIUType.MUTATION_ADD_UPDATE.value:      3000,
    AIUType.MUTATION_ADD_DELETE.value:      2000,
    AIUType.ROUTE_ADD_ENDPOINT.value:       3500,
    AIUType.ROUTE_ADD_PERMISSION.value:     1500,
    AIUType.FRONTEND_ADD_PAGE.value:        4000,
    AIUType.FRONTEND_ADD_STORE.value:       3000,
    AIUType.FRONTEND_BIND_API.value:        2500,
    AIUType.EVENT_ADD_PRODUCER.value:       3000,
    AIUType.EVENT_ADD_CONSUMER.value:       3500,
    AIUType.CACHE_ADD_READ.value:           2000,
    AIUType.CONFIG_MODIFY.value:            1500,
    AIUType.TEST_ADD_UNIT.value:            3000,
    AIUType.TEST_ADD_INTEGRATION.value:     4000,
    AIUType.DOC_SYNC.value:                 1500,
}

# 层间传播代价权重（修改这层时，其依赖层额外增加的 token 消耗比例）
LAYER_PROPAGATION_COST: Dict[str, float] = {
    "L3_domain":        1.3,   # 数据模型变更影响 L4/L5，需要额外上下文
    "L2_infrastructure": 1.2,
    "L4_application":   1.0,
    "L5_interface":     0.9,
    "testing":          0.8,
    "docs":             0.7,
}

# 模型选择阈值
MODEL_THRESHOLDS = {
    "fast":    4000,   # token_budget ≤ 4000 → fast 模型
    "capable": 8000,   # token_budget ≤ 8000 → capable 模型（超过则仍用 capable）
}


# ── 文件复杂度统计 ────────────────────────────────────────────────────────────

def estimate_file_complexity(file_path: str) -> Dict[str, int]:
    """
    估算文件复杂度，用于调整 token 预算。

    返回：
      {
        "lines": 总行数,
        "functions": 函数/方法数,
        "imports": import 行数,
        "complexity_score": 综合复杂度分（0-100）
      }
    """
    # 兼容绝对/相对路径
    p = Path(file_path)
    full_path = p if p.is_absolute() else _ROOT / file_path
    if not full_path.exists():
        return {"lines": 0, "functions": 0, "imports": 0, "complexity_score": 0}

    try:
        content = full_path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        _logger.debug("estimate_file_complexity 读取文件失败 %s: %s", file_path, exc)
        return {"lines": 0, "functions": 0, "imports": 0, "complexity_score": 0}

    lines = content.count("\n")
    functions = len(re.findall(r"^\s*(def |async def )", content, re.MULTILINE))
    imports = len(re.findall(r"^(import |from )", content, re.MULTILINE))

    # 综合复杂度分（0-100）：行数为主，函数数和 import 数辅助
    complexity_score = min(
        int(lines / 10) + functions * 2 + imports,
        100
    )
    return {
        "lines": lines,
        "functions": functions,
        "imports": imports,
        "complexity_score": complexity_score,
    }


def estimate_token_for_file(file_path: str, ratio: float = 0.3) -> int:
    """
    估算读取一个文件片段所需的 token 数。
    ratio: 实际读取文件内容的比例（摘要模式下约 0.3）
    """
    if not file_path:
        return _UNKNOWN_FILE_TOKEN

    p = Path(file_path)
    full_path = p if p.is_absolute() else _ROOT / file_path
    if not full_path.exists():
        return _UNKNOWN_FILE_TOKEN

    try:
        content_len = len(full_path.read_text(encoding="utf-8", errors="ignore"))
    except OSError as exc:
        _logger.debug("estimate_token_for_file 读取失败 %s: %s", file_path, exc)
        return _UNKNOWN_FILE_TOKEN

    estimated_tokens = int(content_len / _CHARS_PER_TOKEN * ratio)
    return max(estimated_tokens, _MIN_TOKEN_FOR_FILE)


# ── 历史成功率查询 ────────────────────────────────────────────────────────────

def get_historical_success_rate(aiu_type: str) -> float:
    """
    从 feedback_stats.jsonl 查询某 AIU 类型的历史执行成功率。
    类比 CBO 中的统计信息（Statistics）查询。

    返回：成功率 [0.0, 1.0]，无历史数据时返回 0.8（乐观估计）
    """
    if not _FEEDBACK_STATS.exists():
        return 0.8  # 无历史数据，乐观估计

    try:
        import json
        success_count = 0
        total_count = 0
        for line in _FEEDBACK_STATS.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("aiu_type") == aiu_type:
                total_count += 1
                if record.get("success", False):
                    success_count += 1
        if total_count == 0:
            return _DEFAULT_SUCCESS_RATE
        return round(success_count / total_count, 3)
    except OSError as exc:
        _logger.debug("get_historical_success_rate 读取 feedback_stats 失败: %s", exc)
        return _DEFAULT_SUCCESS_RATE


# ── 代价估算主函数 ────────────────────────────────────────────────────────────

class AIUCostEstimator:
    """
    AIU 代价估算器。

    为 AIUPlan 中的每个步骤计算执行代价：
      - token_budget：基准代价 + 文件复杂度调整 + 层传播系数
      - model_hint：基于 token_budget 选择模型
      - context_files_ranked：按相关性+复杂度排序的文件列表
    """

    def estimate_step(
        self,
        step: AIUStep,
        all_unit_files: Optional[List[str]] = None,
    ) -> AIUStep:
        """
        为单个 AIU 步骤估算代价，更新 token_budget 和 model_hint。

        Args:
            step: 待估算的 AIU 步骤
            all_unit_files: DagUnit 的全部文件（用于文件排序）

        Returns:
            更新后的 AIUStep（原地修改并返回）
        """
        # 1. 基准代价
        base_cost = AIU_BASE_COST.get(step.aiu_type, 3000)

        # 2. 文件复杂度调整
        files = step.target_files or (all_unit_files or [])
        file_cost = sum(estimate_token_for_file(f) for f in files[:_FILES_FOR_COST])

        # 3. 层传播系数
        layer_factor = LAYER_PROPAGATION_COST.get(step.layer, 1.0)

        # 4. 历史成功率调整（成功率低 → 分配更多 token）
        success_rate = get_historical_success_rate(step.aiu_type)
        history_factor = 1.0 + (1.0 - success_rate) * 0.5  # 成功率 50% → +25% token

        # 综合计算
        estimated_budget = int(
            (base_cost + file_cost) * layer_factor * history_factor
        )
        # 限制在合理范围（_TOKEN_MIN / _TOKEN_MAX 来自 mms_config）
        step.token_budget = max(_TOKEN_MIN, min(estimated_budget, _TOKEN_MAX))

        # 5. 模型选择
        if step.token_budget <= MODEL_THRESHOLDS["fast"]:
            step.model_hint = "fast"
        else:
            step.model_hint = "capable"

        return step

    def estimate_plan(
        self,
        steps: List[AIUStep],
        all_unit_files: Optional[List[str]] = None,
    ) -> List[AIUStep]:
        """
        为 AIUPlan 的全部步骤估算代价。
        同时对 context_files 进行优先级排序（高复杂度文件排前）。
        """
        for step in steps:
            self.estimate_step(step, all_unit_files)

        # 对 target_files 按复杂度降序排序（让 LLM 先看到最复杂的文件）
        for step in steps:
            if len(step.target_files) > 1:
                step.target_files = self._rank_files_by_complexity(step.target_files)

        return steps

    @staticmethod
    def _rank_files_by_complexity(files: List[str]) -> List[str]:
        """按复杂度降序排序文件列表。"""
        scored = [
            (f, estimate_file_complexity(f)["complexity_score"])
            for f in files
        ]
        scored.sort(key=lambda x: -x[1])
        return [f for f, _ in scored]

    def get_total_budget(self, steps: List[AIUStep]) -> int:
        """计算整个 AIUPlan 的总 token 预算（串行执行下的上界）。"""
        return sum(s.token_budget for s in steps)

    def get_critical_path_budget(self, steps: List[AIUStep]) -> int:
        """
        计算关键路径（最长依赖链）的 token 预算。
        类比数据库执行计划的关键路径代价。
        """
        if not steps:
            return 0

        # 构建依赖图，动态规划计算最长路径
        id_to_step = {s.aiu_id: s for s in steps}
        memo: Dict[str, int] = {}

        def dp(aiu_id: str) -> int:
            if aiu_id in memo:
                return memo[aiu_id]
            step = id_to_step.get(aiu_id)
            if step is None:
                return 0
            if not step.depends_on:
                memo[aiu_id] = step.token_budget
                return step.token_budget
            max_dep = max(dp(dep) for dep in step.depends_on)
            result = max_dep + step.token_budget
            memo[aiu_id] = result
            return result

        return max(dp(s.aiu_id) for s in steps)
