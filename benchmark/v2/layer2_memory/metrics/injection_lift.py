"""
Layer 2 · D2 注入提升（Injection Lift）

评测"有记忆注入 vs 无记忆注入"对代码生成质量的提升。

核心指标：
  lift_pass_at_1   = Pass@1(with_injection) - Pass@1(without_injection)
  lift_token_roi   = lift_pass_at_1 / avg_injection_tokens * 1000
                     （每千个注入 token 带来的 Pass@1 提升）
  avg_injection_tokens — 平均注入的 token 数（越少越好）

运行前提：
  - 需要 LLM API（llm_available=True）
  - 仅在 RunLevel.FAST 或 FULL 时运行

扩展方式：
  - 新增任务：在 tasks/<domain>/*.yaml 中添加 code_gen_task 类型 case
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class InjectionLiftCase:
    """单个注入提升测试任务"""
    case_id:          str
    description:      str
    domain:           str
    task_description: str              # 模拟用户输入的任务描述
    required_imports: List[str]        # 生成代码中必须包含的导入/签名（用于离线检查）
    forbidden_patterns: List[str] = field(default_factory=list)
    reference_test:   Optional[str] = None   # pytest 可运行的测试脚本（在线评测用）
    metadata:         Dict[str, Any]  = field(default_factory=dict)


@dataclass
class InjectionLiftResult:
    """注入提升评测结果"""
    case_id:           str
    pass_at_1_with:    Optional[float] = None   # 有注入时的 Pass@1
    pass_at_1_without: Optional[float] = None   # 无注入时的 Pass@1
    lift:              float = 0.0              # 差值
    avg_injection_tokens: float = 0.0
    token_roi:         float = 0.0              # lift / (avg_tokens/1000)
    skipped:           bool = False
    skip_reason:       str = ""
    error:             str = ""


def compute_lift(results: List[InjectionLiftResult]) -> Dict[str, float]:
    """汇总注入提升指标"""
    valid = [r for r in results if not r.skipped and not r.error]
    if not valid:
        return {
            "avg_lift_pass_at_1": 0.0,
            "avg_token_roi":      0.0,
            "avg_injection_tokens": 0.0,
            "cases_evaluated":    0.0,
        }
    return {
        "avg_lift_pass_at_1":   round(sum(r.lift for r in valid) / len(valid), 4),
        "avg_token_roi":        round(sum(r.token_roi for r in valid) / len(valid), 4),
        "avg_injection_tokens": round(
            sum(r.avg_injection_tokens for r in valid) / len(valid), 1
        ),
        "cases_evaluated":      float(len(valid)),
    }


def mock_injection_lift_result(case: InjectionLiftCase) -> InjectionLiftResult:
    """
    在 dry_run 或无 LLM 环境下，返回占位结果。
    真实实现需要调用 LLM API 并比较结果。
    """
    return InjectionLiftResult(
        case_id=case.case_id,
        skipped=True,
        skip_reason="LLM API 不可用（dry_run 或 llm_available=False）",
    )
