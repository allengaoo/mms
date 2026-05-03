"""
代码生成质量度量模块 (EP-132)

4 级评估指标定义与计算：
  Level 1: AST 语法通过率（syntax_pass_rate）
  Level 2: 结构契约通过率（contract_pass_rate）
  Level 3: 架构约束通过率（arch_check_pass_rate）
  Level 4: 参考测试通过率（test_pass_rate）

核心基准指标（Pass@1 + Resolve Rate）：
  pass_at_1    : 一次执行即通过 Level 4 测试的概率（无需反馈回环）
  resolve_rate : 在最多 3 级 Feedback 回退机制下的最终问题修复率

综合指标：
  codegen_score: 加权综合分（Level1×0.1 + Level2×0.3 + Level3×0.3 + Level4×0.3）
                 [已降级为遗留指标，新测试应优先看 pass_at_1 和 resolve_rate]

设计原则（EP-132）：
  - 确定性：每个指标有明确计算公式，结果可复现
  - 可扩展：新指标只需添加 CodegenMetricResult 字段，不修改评估器逻辑
  - 可对比：三个索引系统（pageindex/hybrid_rag/ontology）使用同一套指标

# === 扩展新指标的标准流程 ===
# 1. 在 CodegenMetricResult 添加新字段（带默认值，向后兼容）
#    如: new_metric: float = 0.0
# 2. 在 codegen_evaluator.py 的 evaluate() 中填充新字段
#    如: result.new_metric = compute_new_metric(...)
# 3. 在 CodegenSystemSummary 添加聚合属性（@property）
#    如: @property def avg_new_metric(self) -> float: ...
# 4. 在 run_codegen.py 的报告输出中添加展示
# 5. 添加对应单元测试（tests/test_codegen_quality.py 或 benchmark/tests/）
# 注意：不要修改 Level 1-4 的计算逻辑，以保证历史数据可比性
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class LevelResult:
    """单级评估结果"""
    level: int                          # 评估级别（1-4）
    name: str                           # 级别名称
    passed: int                         # 通过的检查项数
    total: int                          # 总检查项数
    errors: List[str] = field(default_factory=list)  # 失败原因列表
    skipped: bool = False               # 是否跳过（无参考文件等）
    skip_reason: Optional[str] = None   # 跳过原因

    @property
    def pass_rate(self) -> float:
        """
        通过率计算：passed / total，跳过时返回 NaN。

        公式：pass_rate = passed / total  (0.0 ~ 1.0)
        跳过时：NaN（不参与加权综合分计算）
        """
        if self.skipped or self.total == 0:
            return float("nan")
        return self.passed / self.total

    @property
    def pass_rate_pct(self) -> str:
        """格式化百分比字符串"""
        r = self.pass_rate
        if math.isnan(r):
            return "N/A"
        return f"{r * 100:.1f}%"


@dataclass
class CodegenMetricResult:
    """
    单条任务的完整代码生成质量评估结果（EP-132 v2.0）

    核心指标（v2.0）：
      pass_at_1:    一次执行即通过 pytest 的概率（布尔值→同批次内统计）
      resolve_rate: 在 3 级 Feedback 回退机制下的最终问题修复率

    Legacy 指标（保留兼容性）：
      codegen_score: 旧版加权公式评分（已降级为参考指标，不作为主评分）
    """
    task_id: str                        # 任务 ID（如 CG-001）
    category: str                       # 任务类别
    difficulty: str                     # 难度

    level1_syntax: LevelResult = field(default_factory=lambda: LevelResult(1, "syntax", 0, 0))
    level2_contract: LevelResult = field(default_factory=lambda: LevelResult(2, "contract", 0, 0))
    level3_arch: LevelResult = field(default_factory=lambda: LevelResult(3, "arch_check", 0, 0))
    level4_test: LevelResult = field(default_factory=lambda: LevelResult(4, "test_pass", 0, 0))

    generated_tokens: int = 0           # 生成代码的估算 token 数
    retrieval_tokens: int = 0           # 检索/上下文 token 数
    latency_ms: float = 0.0             # 端到端延迟（毫秒）
    system_name: str = ""               # 索引系统名（pageindex/hybrid_rag/ontology）

    # ── 核心指标（v2.0）────────────────────────────────────────────────────────
    # Pass@1：首次 pytest 执行是否通过（True = 一次成功）
    # 由 CodeGenEvaluator 在 level4_test 评估后设置
    _first_attempt_passed: bool = field(default=False)

    # Resolve Rate：经过 ≤ 3 次 Feedback 回退后是否最终通过
    # True = 在 max_retries 次内成功修复，False = 全部失败
    _resolved: bool = field(default=False)

    # 实际使用的回退次数（0 = 首次即过，1~3 = 经过N次反馈）
    _feedback_rounds: int = field(default=0)

    @property
    def pass_at_1(self) -> bool:
        """
        Pass@1：首次执行即通过 pytest 的概率。

        定义：首次代码生成后，不经过任何 Feedback 回退，直接通过 L4 测试。
        计算：_first_attempt_passed 在评估器首次 pytest 调用成功时置 True。
        """
        return self._first_attempt_passed

    @property
    def resolve_rate(self) -> bool:
        """
        Resolve Rate：在 3 级 Feedback 回退机制下的最终修复成功率。

        定义：经过至多 max_retries（通常为 3）次 Feedback 修正后，最终通过 pytest。
        解读：
          True  → 问题已解决（可能首次，也可能经过1~3轮反馈）
          False → 3次反馈后仍未通过
        """
        return self._resolved

    @property
    def codegen_score(self) -> float:
        """
        综合代码生成质量分（0.0 ~ 1.0）。

        加权公式（EP-132 v1.0）：
          raw_weights = {L1: 0.10, L2: 0.30, L3: 0.30, L4: 0.30}

          有效权重 = 只计算非 NaN 的级别，等比重新归一化：
            valid_weights = {k: v for k, v in weights.items() if not isnan(level_k.pass_rate)}
            normalized_w = {k: v / sum(valid_weights.values()) for k, v in valid_weights.items()}
            score = sum(normalized_w[k] * level_k.pass_rate for k in valid_weights)

          特殊情况：所有级别均 NaN → 返回 NaN
        """
        levels = [
            (self.level1_syntax, 0.10),
            (self.level2_contract, 0.30),
            (self.level3_arch, 0.30),
            (self.level4_test, 0.30),
        ]
        return calc_codegen_score(levels)

    @property
    def cost_efficiency(self) -> float:
        """
        成本效率：质量分 / (检索 token 数 / 1000)。

        公式：
          efficiency = codegen_score / (retrieval_tokens / 1000 + 1e-6)

        解读：
          - 值越高：更少 token 消耗达到更高质量
          - 1e-6 防止除零
        """
        score = self.codegen_score
        if math.isnan(score) or self.retrieval_tokens == 0:
            return float("nan")
        return score / (self.retrieval_tokens / 1000 + 1e-6)

    def to_dict(self) -> Dict:
        """序列化为可 JSON 化的字典（供报告生成使用）"""
        return {
            "task_id": self.task_id,
            "category": self.category,
            "difficulty": self.difficulty,
            "system": self.system_name,
            "level1_syntax": {
                "pass_rate": _safe_float(self.level1_syntax.pass_rate),
                "passed": self.level1_syntax.passed,
                "total": self.level1_syntax.total,
                "skipped": self.level1_syntax.skipped,
            },
            "level2_contract": {
                "pass_rate": _safe_float(self.level2_contract.pass_rate),
                "passed": self.level2_contract.passed,
                "total": self.level2_contract.total,
                "errors": self.level2_contract.errors,
                "skipped": self.level2_contract.skipped,
            },
            "level3_arch": {
                "pass_rate": _safe_float(self.level3_arch.pass_rate),
                "passed": self.level3_arch.passed,
                "total": self.level3_arch.total,
                "errors": self.level3_arch.errors,
                "skipped": self.level3_arch.skipped,
            },
            "level4_test": {
                "pass_rate": _safe_float(self.level4_test.pass_rate),
                "passed": self.level4_test.passed,
                "total": self.level4_test.total,
                "errors": self.level4_test.errors,
                "skipped": self.level4_test.skipped,
            },
            # v2.0 核心指标（Pass@1 + Resolve Rate）
            "pass_at_1": self.pass_at_1,
            "resolve_rate": self.resolve_rate,
            "feedback_rounds": self._feedback_rounds,
            # Legacy 参考指标
            "codegen_score": _safe_float(self.codegen_score),
            "cost_efficiency": _safe_float(self.cost_efficiency),
            "generated_tokens": self.generated_tokens,
            "retrieval_tokens": self.retrieval_tokens,
            "latency_ms": self.latency_ms,
        }


@dataclass
class CodegenSystemSummary:
    """
    一个索引系统在所有任务上的聚合统计（EP-132 v2.0）

    核心指标（v2.0）：
      pass_at_1_rate:  Pass@1 通过率 = 首次即通过的任务数 / 总任务数
      resolve_rate:    Resolve Rate = 最终解决的任务数 / 总任务数

    Legacy 参考指标（保留兼容性）：
      avg_score = mean(codegen_score for all tasks where not NaN)
    """
    system_name: str
    task_results: List[CodegenMetricResult] = field(default_factory=list)

    @property
    def pass_at_1_rate(self) -> float:
        """
        Pass@1 通过率：首次执行即通过 pytest 的任务比例。

        公式：pass_at_1_rate = count(pass_at_1 == True) / total_tasks
        """
        if not self.task_results:
            return float("nan")
        return sum(1 for r in self.task_results if r.pass_at_1) / len(self.task_results)

    @property
    def final_resolve_rate(self) -> float:
        """
        最终修复率：经过至多 3 次 Feedback 后最终成功的任务比例。

        公式：resolve_rate = count(resolve_rate == True) / total_tasks
        """
        if not self.task_results:
            return float("nan")
        return sum(1 for r in self.task_results if r.resolve_rate) / len(self.task_results)

    @property
    def avg_feedback_rounds(self) -> float:
        """平均反馈轮次（0 = 首次即过，越低越好）"""
        if not self.task_results:
            return float("nan")
        return sum(r._feedback_rounds for r in self.task_results) / len(self.task_results)

    @property
    def avg_score(self) -> float:
        """平均综合分（Legacy 参考指标）"""
        valid = [r.codegen_score for r in self.task_results if not math.isnan(r.codegen_score)]
        return sum(valid) / len(valid) if valid else float("nan")

    @property
    def avg_cost_efficiency(self) -> float:
        """平均成本效率"""
        valid = [r.cost_efficiency for r in self.task_results if not math.isnan(r.cost_efficiency)]
        return sum(valid) / len(valid) if valid else float("nan")

    @property
    def syntax_pass_rate(self) -> float:
        """L1 语法通过率（汇总）"""
        passed = sum(r.level1_syntax.passed for r in self.task_results)
        total = sum(r.level1_syntax.total for r in self.task_results)
        return passed / total if total > 0 else float("nan")

    @property
    def contract_pass_rate(self) -> float:
        """L2 契约通过率（汇总）"""
        passed = sum(r.level2_contract.passed for r in self.task_results)
        total = sum(r.level2_contract.total for r in self.task_results)
        return passed / total if total > 0 else float("nan")

    @property
    def arch_check_pass_rate(self) -> float:
        """L3 架构通过率（汇总）"""
        passed = sum(r.level3_arch.passed for r in self.task_results)
        total = sum(r.level3_arch.total for r in self.task_results)
        return passed / total if total > 0 else float("nan")

    @property
    def test_pass_rate(self) -> float:
        """L4 测试通过率（汇总）"""
        passed = sum(r.level4_test.passed for r in self.task_results)
        total = sum(r.level4_test.total for r in self.task_results)
        return passed / total if total > 0 else float("nan")

    def by_category(self) -> Dict[str, float]:
        """按类别分组的平均分"""
        cats: Dict[str, List[float]] = {}
        for r in self.task_results:
            s = r.codegen_score
            if not math.isnan(s):
                cats.setdefault(r.category, []).append(s)
        return {k: sum(v) / len(v) for k, v in cats.items()}

    def by_difficulty(self) -> Dict[str, float]:
        """按难度分组的平均分"""
        diffs: Dict[str, List[float]] = {}
        for r in self.task_results:
            s = r.codegen_score
            if not math.isnan(s):
                diffs.setdefault(r.difficulty, []).append(s)
        return {k: sum(v) / len(v) for k, v in diffs.items()}


# ─────────────────────────────────────────────────────────────────────────────
# 计算函数
# ─────────────────────────────────────────────────────────────────────────────

def calc_codegen_score(
    level_pairs: List[tuple],
) -> float:
    """
    计算综合代码生成质量分。

    公式：
      1. 过滤掉 pass_rate 为 NaN 的级别（跳过或无参考文件）
      2. 对剩余级别的权重等比归一化（权重之和 = 1.0）
      3. 加权求和

    Args:
        level_pairs: [(LevelResult, weight), ...]

    Returns:
        综合分（0.0 ~ 1.0），全部 NaN 则返回 NaN
    """
    valid = [(lvl, w) for lvl, w in level_pairs if not math.isnan(lvl.pass_rate)]
    if not valid:
        return float("nan")
    total_w = sum(w for _, w in valid)
    if total_w <= 0:
        return float("nan")
    return sum((lvl.pass_rate * w / total_w) for lvl, w in valid)


def aggregate_system_scores(
    results: List[CodegenMetricResult],
) -> CodegenSystemSummary:
    """
    聚合单个系统的所有任务结果。

    Args:
        results: 该系统所有任务的评估结果列表

    Returns:
        CodegenSystemSummary 汇总对象
    """
    if not results:
        return CodegenSystemSummary(system_name="unknown", task_results=[])
    system_name = results[0].system_name
    return CodegenSystemSummary(system_name=system_name, task_results=results)


def compare_systems(
    summaries: List[CodegenSystemSummary],
) -> Dict[str, Dict]:
    """
    多系统对比分析（EP-132）。

    输出结构：
      {
        "winner": str,           # 综合分最高的系统
        "rankings": [{system, avg_score, by_difficulty, by_category}, ...]
        "delta_vs_best": {system: delta}  # 与最佳系统的分差
      }
    """
    if not summaries:
        return {}

    sorted_summaries = sorted(
        summaries,
        key=lambda s: s.avg_score if not math.isnan(s.avg_score) else -1,
        reverse=True,
    )
    best_score = sorted_summaries[0].avg_score

    return {
        "winner": sorted_summaries[0].system_name,
        "rankings": [
            {
                "system": s.system_name,
                "avg_score": _safe_float(s.avg_score),
                "avg_cost_efficiency": _safe_float(s.avg_cost_efficiency),
                "syntax_pass_rate": _safe_float(s.syntax_pass_rate),
                "contract_pass_rate": _safe_float(s.contract_pass_rate),
                "arch_check_pass_rate": _safe_float(s.arch_check_pass_rate),
                "test_pass_rate": _safe_float(s.test_pass_rate),
                "by_category": s.by_category(),
                "by_difficulty": s.by_difficulty(),
            }
            for s in sorted_summaries
        ],
        "delta_vs_best": {
            s.system_name: _safe_float(
                (s.avg_score - best_score) if not math.isnan(s.avg_score) else float("nan")
            )
            for s in sorted_summaries
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────────────────────────────────────

def _safe_float(v: float) -> object:
    """NaN → None（JSON 序列化友好）"""
    return None if math.isnan(v) else round(v, 4)
