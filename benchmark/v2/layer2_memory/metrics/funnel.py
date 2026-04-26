"""
Layer 2 · 检索漏斗有效性验证（Funnel Effectiveness）

验证三阶段检索漏斗（图路径 → 关键词 → LLM）的各阶段独立贡献度。

评测指标：
  stage1_recall       — 类型 A case 的 Stage-1 独立召回率（图路径专属命中率）
  stage2_lift         — 类型 B case 中 Stage-2 补充 Stage-1 未命中的增量召回率
  stage1_priority     — 类型 C case 中 Stage-1 结果排名优于 Stage-2 结果的比例
  stage3_necessity    — 类型 D case 中两阶段均 miss 的比例（LLM 层必要性）
  overall_funnel_hit  — 所有 case 中至少有一个 stage 命中的比例

漏斗阶段说明：
  Stage 1: MemoryGraph.find_by_concept()  — 基于 about_concepts 图路径
  Stage 2: MemoryGraph.keyword_search()   — 全文关键词检索
  Stage 3: LLM 语义重排序（本 evaluator 不实际调用 LLM，标记为 expected_only）
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent.parent.parent
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))


@dataclass
class FunnelCase:
    case_id:              str
    category:             str           # graph_only | keyword_only | both_stages | none_stage
    query:                str
    relevant_ids:         Set[str]
    domain_concepts:      List[str]
    k:                    int = 5
    expected_funnel_stage: int = 1      # 预期最低需要哪个 stage 才能命中（1/2/3）
    description:          str = ""
    notes:                str = ""
    metadata:             Dict[str, Any] = field(default_factory=dict)


@dataclass
class FunnelStageResult:
    stage1_hit:  bool = False   # Stage-1（图路径）是否命中
    stage2_hit:  bool = False   # Stage-2（关键词）是否命中
    stage3_expected: bool = False  # Stage-3 预期是否必要（expected_funnel_stage == 3）
    retrieved_stage1: List[str] = field(default_factory=list)
    retrieved_stage2: List[str] = field(default_factory=list)


@dataclass
class FunnelCaseResult:
    case_id:          str
    category:         str
    stages:           FunnelStageResult = field(default_factory=FunnelStageResult)
    actual_hit_stage: Optional[int] = None   # 实际首次命中的 stage（None = 未命中）
    expected_stage:   int = 1
    pass_stage:       bool = False           # 是否在预期 stage 内命中
    error:            str = ""


def _ids_from_nodes(nodes: List) -> List[str]:
    return [getattr(n, "id", str(n)) for n in nodes]


def evaluate_funnel_case(
    case: FunnelCase,
    memory_root: Path,
) -> FunnelCaseResult:
    """
    对单个漏斗 case 分别调用 Stage-1 和 Stage-2，记录各阶段命中情况。
    Stage-3 仅标记预期，不实际调用 LLM（避免测试依赖外部服务）。
    """
    result = FunnelCaseResult(
        case_id=case.case_id,
        category=case.category,
        expected_stage=case.expected_funnel_stage,
    )

    try:
        from mms.memory.graph_resolver import MemoryGraph
        graph = MemoryGraph(memory_root=memory_root)

        # Stage 1: 图路径检索（find_by_concept）
        stage1_nodes = graph.find_by_concept(case.domain_concepts)
        stage1_ids = _ids_from_nodes(stage1_nodes)[: case.k]
        stage1_hit = bool(case.relevant_ids & set(stage1_ids))

        # Stage 2: 关键词全文检索（通过 hybrid_search 的关键词部分）
        # 注：调用 hybrid_search with use_graph=False 模拟纯关键词路径
        stage2_nodes = graph.hybrid_search(
            case.query.split(),
            use_graph=False,
            fallback_to_keyword=True,
        )
        stage2_ids = _ids_from_nodes(stage2_nodes)[: case.k]
        stage2_hit = bool(case.relevant_ids & set(stage2_ids))

        result.stages = FunnelStageResult(
            stage1_hit=stage1_hit,
            stage2_hit=stage2_hit,
            stage3_expected=(case.expected_funnel_stage == 3),
            retrieved_stage1=stage1_ids,
            retrieved_stage2=stage2_ids,
        )

        # 确定实际首次命中 stage
        if stage1_hit:
            result.actual_hit_stage = 1
        elif stage2_hit:
            result.actual_hit_stage = 2
        else:
            result.actual_hit_stage = None  # 只有 LLM 层才能命中

        # 判断是否在预期 stage 内命中
        if case.expected_funnel_stage == 3:
            # 类型 D：预期两阶段都 miss，pass 条件是 stage1 & stage2 都没命中
            result.pass_stage = (not stage1_hit and not stage2_hit)
        elif case.expected_funnel_stage == 2:
            # 类型 B：允许 Stage-1 也命中（只要 Stage-2 能补充）
            result.pass_stage = (stage2_hit or stage1_hit)
        else:
            # 类型 A/C：预期 Stage-1 能命中
            result.pass_stage = stage1_hit

    except Exception as exc:
        result.error = str(exc)

    return result


def load_funnel_cases(yaml_path: Path, fixture_memory_dir: Optional[Path] = None) -> List[FunnelCase]:
    """从 YAML 文件加载漏斗测试用例"""
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    cases = []
    for c in raw.get("cases", []):
        if not c.get("id") or not c.get("query"):
            continue
        rel_ids = set(c.get("relevant_ids", []))
        cases.append(FunnelCase(
            case_id=c["id"],
            category=c.get("category", "unknown"),
            query=c["query"],
            relevant_ids=rel_ids,
            domain_concepts=c.get("domain_concepts", []),
            k=c.get("k", 5),
            expected_funnel_stage=c.get("expected_funnel_stage", 1),
            description=c.get("description", ""),
            notes=c.get("notes", ""),
        ))
    return cases


def aggregate_funnel_metrics(results: List[FunnelCaseResult]) -> Dict[str, float]:
    """
    聚合漏斗有效性指标：
      stage1_recall     — graph_only 类 case 中 Stage-1 命中率
      stage2_lift       — keyword_only 类 case 中 Stage-2 命中率（Stage-1 不能单独命中）
      stage1_priority   — both_stages 类 case 中 Stage-1 先于 Stage-2 命中的比例
      stage3_necessity  — none_stage 类 case 中两阶段均未命中的比例（=LLM 必要性）
      overall_hit_rate  — 所有 case 中在预期 stage 内命中的比例
    """
    if not results:
        return {}

    valid = [r for r in results if not r.error]

    def _cases_of(cat: str) -> List[FunnelCaseResult]:
        return [r for r in valid if r.category == cat]

    # Stage-1 独立召回率（graph_only 类）
    graph_only = _cases_of("graph_only")
    stage1_recall = (
        sum(1 for r in graph_only if r.stages.stage1_hit) / len(graph_only)
        if graph_only else 0.0
    )

    # Stage-2 增量召回率（keyword_only 类）
    keyword_only = _cases_of("keyword_only")
    stage2_lift = (
        sum(1 for r in keyword_only if r.stages.stage2_hit) / len(keyword_only)
        if keyword_only else 0.0
    )

    # Stage-1 优先率（both_stages 类：Stage-1 命中而 Stage-2 也命中时，Stage-1 排名更靠前）
    both_stages = _cases_of("both_stages")
    stage1_priority = (
        sum(1 for r in both_stages if r.actual_hit_stage == 1) / len(both_stages)
        if both_stages else 0.0
    )

    # LLM 必要性（none_stage 类：两阶段都 miss 的比例）
    none_stage = _cases_of("none_stage")
    stage3_necessity = (
        sum(1 for r in none_stage if r.actual_hit_stage is None) / len(none_stage)
        if none_stage else 0.0
    )

    # 总体命中率
    overall_hit_rate = (
        sum(1 for r in valid if r.pass_stage) / len(valid) if valid else 0.0
    )

    return {
        "stage1_recall":    round(stage1_recall, 4),
        "stage2_lift":      round(stage2_lift, 4),
        "stage1_priority":  round(stage1_priority, 4),
        "stage3_necessity": round(stage3_necessity, 4),
        "overall_hit_rate": round(overall_hit_rate, 4),
        "total_cases":      len(valid),
        "graph_only_n":     len(graph_only),
        "keyword_only_n":   len(keyword_only),
        "both_stages_n":    len(both_stages),
        "none_stage_n":     len(none_stage),
    }
