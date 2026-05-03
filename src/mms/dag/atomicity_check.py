"""
atomicity_check.py — MMS Unit 原子性验证器

验证一个 Unit 是否满足小模型（8B/16B）可执行的 4 条原子化标准：

  A1 - 文件数量：≤ max_files_per_unit（默认 2）
  A2 - 上下文 tokens：≤ model 对应阈值（8B:4000, 16B:8000）
  A3 - 架构层一致性：所有文件属于同一架构层（违反时警告）
  A4 - 自动验证性：有 pytest 路径 OR arch_check 覆盖

阈值来源：docs/memory/_system/config.yaml → dag.atomicity_thresholds

用法：
  python3 scripts/mms/atomicity_check.py --files f1.py f2.py --model 8b
  python3 scripts/mms/atomicity_check.py --unit U3 --ep EP-117 --model 16b
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Set, Tuple

_ROOT = Path(__file__).resolve().parents[2]     # src/（用于文件相对路径拼接）
_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # 项目根（/Users/.../mms）

# code_graph.json 路径（由 code_graph_builder 生成，位于项目根下）
_CODE_GRAPH_PATH = _PROJECT_ROOT / "docs" / "memory" / "_system" / "code_graph.json"

try:
    import sys as _sys
    _sys.path.insert(0, str(_HERE))
    from mms.utils.mms_config import cfg as _cfg  # type: ignore[import]
except Exception:
    _cfg = None  # type: ignore[assignment]

# ANSI 颜色
_G = "\033[92m"
_Y = "\033[93m"
_R = "\033[91m"
_C = "\033[96m"
_B = "\033[1m"
_X = "\033[0m"

# ── 层路径前缀映射 ────────────────────────────────────────────────────────────

_LAYER_PREFIX: Dict[str, str] = {
    "backend/app/api":              "L5_interface",
    "backend/app/services":         "L4_application",
    "backend/app/workers":          "L4_application",
    "backend/app/domain":           "L3_domain",
    "backend/app/infrastructure":   "L2_infrastructure",
    "backend/app/core":             "L1_platform",
    "frontend/src/pages":           "L5_interface",
    "frontend/src/components":      "L5_interface",
    "frontend/src/services":        "L5_interface",
    "frontend/src/stores":          "L4_application",
    "scripts/mms":                  "L4_application",
    "docs/memory":                  "docs",
    "docs/architecture":            "docs",
    "docs/execution_plans":         "docs",
    "backend/tests":                "testing",
    "frontend/src/__tests__":       "testing",
    "frontend/src/pages/__tests__": "testing",
    "scripts/mms/tests":            "testing",
}

_ARCH_CHECK_LAYERS = {
    "L4_application", "L5_interface", "L2_infrastructure", "L3_domain",
}


def infer_layer(file_path: str) -> str:
    """从文件路径推断所属架构层"""
    for prefix, layer in sorted(_LAYER_PREFIX.items(), key=lambda x: -len(x[0])):
        if file_path.replace("\\", "/").startswith(prefix):
            return layer
    if "test" in file_path.lower():
        return "testing"
    if file_path.endswith(".md") or file_path.startswith("docs/"):
        return "docs"
    return "unknown"


# ── 代码图谱连通性辅助（A3 升级）────────────────────────────────────────────

def _build_file_graph(code_graph_path: Path = _CODE_GRAPH_PATH) -> Dict[str, Set[str]]:
    """
    从 code_graph.json 构建文件级无向邻接表。

    code_graph.json 的 top_depends_on 字段存储了类级有向边（source 依赖 target）：
      {"source": "src/a.py::ClassA", "target": "src/b.py::ClassB"}
    此函数将其转为文件级无向图（忽略方向），用于连通性检查。

    Returns:
        {file_path: {neighbor_file, ...}, ...}，仅包含有边的文件
    """
    if not code_graph_path.exists():
        return {}
    try:
        data = json.loads(code_graph_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    graph: Dict[str, Set[str]] = defaultdict(set)
    for edge in data.get("top_depends_on", []):
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        if "::" not in src or "::" not in tgt:
            continue
        src_file = src.split("::")[0].replace("\\", "/")
        tgt_file = tgt.split("::")[0].replace("\\", "/")
        if src_file != tgt_file:
            graph[src_file].add(tgt_file)
            graph[tgt_file].add(src_file)  # 无向化：双向可达

    return dict(graph)


def _normalize_path(file_path: str) -> str:
    """规范化文件路径为相对路径（去除项目根前缀）。"""
    p = file_path.replace("\\", "/")
    for root in (str(_PROJECT_ROOT), str(_ROOT)):
        root_str = root.replace("\\", "/").rstrip("/") + "/"
        if p.startswith(root_str):
            return p[len(root_str):]
    return p


def _are_files_connected(files: List[str], graph: Dict[str, Set[str]]) -> Tuple[bool, List[str]]:
    """
    使用 BFS 检查文件列表中所有文件是否属于同一连通分量。

    Args:
        files: 要检查的文件路径列表（相对路径）
        graph: 文件级无向邻接表

    Returns:
        (is_connected, isolated_files)
        - is_connected: True 表示所有文件均连通（或只有 ≤1 个文件）
        - isolated_files: 与其他文件完全不相连的文件列表
    """
    if len(files) <= 1:
        return True, []

    norm_files = [_normalize_path(f) for f in files]
    file_set: Set[str] = set(norm_files)

    # BFS 从第一个文件出发，遍历所有可达的"目标文件集合中的成员"
    start = norm_files[0]
    visited: Set[str] = {start}
    queue: deque = deque([start])

    while queue:
        curr = queue.popleft()
        for neighbor in graph.get(curr, set()):
            if neighbor in file_set and neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)

    isolated = [files[i] for i, nf in enumerate(norm_files) if nf not in visited]
    return len(isolated) == 0, isolated


def estimate_tokens(file_paths: List[str]) -> int:
    """
    估算文件列表的总 token 数（粗略：字节数 // 4 × 0.8 保守系数）。
    不存在的文件按 0 处理。
    """
    total_bytes = 0
    for fp in file_paths:
        abs_path = _ROOT / fp if not Path(fp).is_absolute() else Path(fp)
        if abs_path.exists():
            total_bytes += abs_path.stat().st_size
    return int(total_bytes / 4 * 0.8)


# ── 检查结果 ──────────────────────────────────────────────────────────────────

class CheckResult(NamedTuple):
    passed: bool
    label: str
    detail: str
    is_warning: bool = False  # True = 警告（不阻断），False = 错误（阻断）


def check_a1_file_count(files: List[str], max_files: int = 2) -> CheckResult:
    """A1：文件数量 ≤ max_files"""
    count = len(files)
    passed = count <= max_files
    return CheckResult(
        passed=passed,
        label="A1 文件数量",
        detail=f"{count} 个文件（阈值 ≤ {max_files}）",
    )


def check_a2_token_budget(
    files: List[str],
    model: str = "capable",
    thresholds: Optional[Dict[str, int]] = None,
) -> CheckResult:
    """A2：上下文 token 估算 ≤ model 对应阈值"""
    if thresholds is None:
        # fallback: config.yaml → dag.atomicity_thresholds.max_context_tokens_{model} (default=4000/8000)
        _t8b = int(getattr(_cfg, "dag_token_budget_8b", 4000)) if _cfg else 4000
        _t16b = int(getattr(_cfg, "dag_token_budget_16b", 8000)) if _cfg else 8000
        thresholds = {"8b": _t8b, "16b": _t16b, "capable": 999999}

    limit = thresholds.get(model, 999999)
    estimated = estimate_tokens(files)
    passed = estimated <= limit

    return CheckResult(
        passed=passed,
        label="A2 Token 估算",
        detail=f"~{estimated:,} tokens（{model} 阈值 ≤ {limit:,}）",
    )


def check_a3_layer_consistency(
    files: List[str],
    code_graph_path: Optional[Path] = None,
) -> CheckResult:
    """
    A3：评估文件集合的内聚性（Cohesion）。

    策略（双轨，优先使用代码图谱）：
      Track A（优先）：代码图谱连通性检查
        - 从 code_graph.json 构建文件级无向邻接表
        - 检查所有文件是否属于同一连通分量
        - 优点：精确反映实际代码耦合，不依赖路径规则
        - 若 code_graph.json 不存在或文件不在图中，降级至 Track B

      Track B（Fallback）：架构层路径前缀检查
        - 原有逻辑：所有文件属于同一架构层
        - 层不一致为警告（is_warning=True），不硬性阻断
    """
    if not files:
        return CheckResult(passed=True, label="A3 内聚性", detail="无文件")

    graph = _build_file_graph(code_graph_path or _CODE_GRAPH_PATH)

    # Track A：代码图谱连通性（仅当图已加载且包含本次文件中至少一个文件时激活）
    norm_files = [_normalize_path(f) for f in files]
    files_in_graph = [nf for nf in norm_files if nf in graph]

    if graph and len(files) > 1 and files_in_graph:
        is_connected, isolated = _are_files_connected(files, graph)
        if is_connected:
            return CheckResult(
                passed=True,
                label="A3 内聚性",
                detail=f"代码图谱连通（{len(files)} 个文件属同一连通分量）",
            )
        else:
            isolated_names = [Path(f).name for f in isolated]
            return CheckResult(
                passed=False,
                label="A3 内聚性",
                detail=f"代码图谱不连通，孤立文件：{', '.join(isolated_names)}",
                is_warning=True,  # 不连通为警告，不硬性阻断
            )

    # Track B：架构层路径前缀检查（Fallback）
    layers = [infer_layer(f) for f in files]
    business_layers = [lyr for lyr in layers if lyr not in ("testing", "docs", "unknown")]

    if not business_layers:
        return CheckResult(
            passed=True,
            label="A3 内聚性",
            detail=f"全部为 testing/docs 文件（{', '.join(set(layers))}）[层一致性 fallback]",
        )

    unique_layers = set(business_layers)
    passed = len(unique_layers) <= 1
    layer_map = {f: infer_layer(f) for f in files}
    detail_parts = [f"{Path(f).name}→{lyr}" for f, lyr in layer_map.items()]
    suffix = "" if graph else "（图谱不可用，使用层一致性 fallback）"

    return CheckResult(
        passed=passed,
        label="A3 内聚性",
        detail=f"{', '.join(detail_parts)}{suffix}",
        is_warning=not passed,
    )


def check_a4_verifiability(
    files: List[str],
    test_files: Optional[List[str]] = None,
) -> CheckResult:
    """A4：有 pytest 路径 OR arch_check 覆盖（可自动验证）"""
    # 检查是否有测试文件
    all_files = (files or []) + (test_files or [])
    has_test_file = any(
        "test" in Path(f).name.lower() or "spec" in Path(f).name.lower()
        for f in all_files
    )

    # 检查 arch_check 是否覆盖（涉及 services/ 或 api/ 层）
    layers = [infer_layer(f) for f in files]
    has_arch_check = any(lyr in _ARCH_CHECK_LAYERS for lyr in layers)

    passed = has_test_file or has_arch_check

    if has_test_file:
        detail = "有测试文件（pytest 覆盖）"
    elif has_arch_check:
        detail = f"arch_check 覆盖（层：{', '.join(set(layers))}）"
    else:
        detail = "无测试文件，所在层不在 arch_check 覆盖范围"

    return CheckResult(passed=passed, label="A4 可验证性", detail=detail)


# ── 综合评分 ──────────────────────────────────────────────────────────────────

def compute_atomicity_score(results: List[CheckResult]) -> float:
    """
    计算原子化综合得分（0.0-1.0）。
    - A1、A2、A4 为硬性标准（权重 0.3 each）
    - A3 为软性标准（权重 0.1，警告不扣分）
    """
    weights = [0.3, 0.3, 0.1, 0.3]  # A1, A2, A3, A4
    score = 0.0
    for i, result in enumerate(results):
        w = weights[i] if i < len(weights) else 0.1
        if result.passed:
            score += w
        elif result.is_warning:
            score += w * 0.5  # 警告得一半分
    return round(score, 2)


# ── 主验证函数 ────────────────────────────────────────────────────────────────

def validate_unit(
    files: List[str],
    model: str = "capable",
    test_files: Optional[List[str]] = None,
    max_files: int = 2,
    token_thresholds: Optional[Dict[str, int]] = None,
    verbose: bool = True,
) -> Tuple[bool, float, List[CheckResult]]:
    """
    验证 Unit 原子性。

    Returns:
        (is_atomic: bool, score: float, results: List[CheckResult])
        is_atomic = True 表示该 Unit 适合指定 model 执行
    """
    if token_thresholds is None:
        # fallback: config.yaml → dag.atomicity_thresholds.max_context_tokens_{model} (default=4000/8000)
        _tt8b = int(getattr(_cfg, "dag_token_budget_8b", 4000)) if _cfg else 4000
        _tt16b = int(getattr(_cfg, "dag_token_budget_16b", 8000)) if _cfg else 8000
        token_thresholds = {"8b": _tt8b, "16b": _tt16b, "capable": 999999}

    results = [
        check_a1_file_count(files, max_files),
        check_a2_token_budget(files, model, token_thresholds),
        check_a3_layer_consistency(files),
        check_a4_verifiability(files, test_files),
    ]

    score = compute_atomicity_score(results)

    # 硬性标准（A1、A2、A4）失败 → 不是原子 Unit
    hard_fails = [r for r in results if not r.passed and not r.is_warning]
    is_atomic = len(hard_fails) == 0

    if verbose:
        _print_results(results, score, model, is_atomic)

    return is_atomic, score, results


def _print_results(
    results: List[CheckResult],
    score: float,
    model: str,
    is_atomic: bool,
) -> None:
    """打印原子性验证结果"""
    print(f"\n{_B}原子性验证{_X}（model={model}）")
    print("─" * 50)
    for r in results:
        if r.passed:
            icon = f"{_G}✅{_X}"
        elif r.is_warning:
            icon = f"{_Y}⚠️ {_X}"
        else:
            icon = f"{_R}❌{_X}"
        print(f"  {icon} {r.label:<16} {r.detail}")
    print("─" * 50)

    score_bar = "█" * int(score * 10) + "░" * (10 - int(score * 10))
    if is_atomic:
        verdict = f"{_G}{_B}✅ ATOMIC{_X}（score={score:.2f}）  适合 {model} 模型执行"
    else:
        verdict = f"{_R}{_B}❌ NOT ATOMIC{_X}（score={score:.2f}）  建议用 capable 模型 或 拆分 Unit"

    print(f"  得分 [{score_bar}] {score:.2f}")
    print(f"  {verdict}\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="mms.dag.atomicity_check.py — MMS Unit 原子性验证",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 scripts/mms/atomicity_check.py --files scripts/mms/dag_model.py --model 8b
  python3 scripts/mms/atomicity_check.py --files f1.py f2.py f3.py --model 16b
  python3 scripts/mms/atomicity_check.py --unit U3 --ep EP-117 --model 8b
""",
    )
    parser.add_argument("--files", nargs="+", default=[], help="涉及文件列表")
    parser.add_argument("--test-files", nargs="+", default=[], help="测试文件列表")
    parser.add_argument("--model", choices=["8b", "16b", "capable"], default="capable",
                        help="目标执行模型（default: capable）")
    parser.add_argument("--unit", help="Unit ID（与 --ep 配合，从 DAG 状态自动读取文件）")
    parser.add_argument("--ep", help="EP ID（与 --unit 配合使用）")
    parser.add_argument("--max-files", type=int, default=2, help="文件数量上限（default: 2）")
    parser.add_argument("--quiet", action="store_true", help="静默模式（只输出得分）")
    args = parser.parse_args()

    files = list(args.files)
    test_files = list(args.test_files)

    # 若指定了 --unit + --ep，从 DAG 状态文件读取文件列表
    if args.unit and args.ep:
        try:
            from mms.dag.dag_model import DagState  # type: ignore[import]
        except ImportError:
            from mms.dag.dag_model import DagState  # type: ignore[import]
        try:
            dag = DagState.load(args.ep)
            unit = dag._get_unit(args.unit)
            files = list(unit.files) if not files else files
            test_files = list(unit.test_files) if not test_files else test_files
            if not args.quiet:
                print(f"  从 DAG 加载：{args.ep} {args.unit} → {len(files)} 个文件")
        except Exception as e:
            print(f"⚠️  无法加载 DAG 状态：{e}", file=sys.stderr)

    if not files:
        print("⚠️  未指定文件（--files 或 --unit+--ep），以空文件列表验证", file=sys.stderr)

    is_atomic, score, results = validate_unit(
        files=files,
        model=args.model,
        test_files=test_files,
        max_files=args.max_files,
        verbose=not args.quiet,
    )

    if args.quiet:
        print(f"{score:.2f} {'ATOMIC' if is_atomic else 'NOT_ATOMIC'}")

    return 0 if is_atomic else 1


if __name__ == "__main__":
    sys.exit(main())
