"""
Mulan Benchmark v2 — 主 Runner

职责：
  1. 根据 BenchmarkConfig 决定运行哪些层
  2. 按依赖顺序调度各层 Evaluator（Layer3 → Layer2 → Layer1）
  3. 将结果交给 Reporter 输出

扩展方式（新增评测层）：
  1. 在 benchmark/v2/ 下创建 layer_new/ 目录
  2. 实现 BaseEvaluator 子类
  3. 在 _EVALUATOR_REGISTRY 中注册

运行示例（命令行）：
  mulan benchmark                     # 离线模式（仅 Layer3）
  mulan benchmark --level fast        # Layer2 + Layer3
  mulan benchmark --level full        # 全部三层
  mulan benchmark --layer 3           # 指定单层
  mulan benchmark --output markdown --output-path reports/bench.md
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Type

from benchmark.v2.schema import (
    BaseEvaluator,
    BenchmarkConfig,
    BenchmarkLayer,
    BenchmarkResult,
    LayerResult,
    RunLevel,
)
from benchmark.v2.layer3_safety.evaluator  import SafetyEvaluator
from benchmark.v2.layer2_memory.evaluator  import MemoryEvaluator
from benchmark.v2.layer1_swebench.evaluator import SWEBenchEvaluator
from benchmark.v2.reporters.console  import print_result
from benchmark.v2.reporters.markdown import save_markdown


# ─────────────────────────────────────────────────────────────────────────────
# 评测器注册表
# ─────────────────────────────────────────────────────────────────────────────

_EVALUATOR_REGISTRY: Dict[BenchmarkLayer, Type[BaseEvaluator]] = {
    BenchmarkLayer.LAYER3_SAFETY:   SafetyEvaluator,
    BenchmarkLayer.LAYER2_MEMORY:   MemoryEvaluator,
    BenchmarkLayer.LAYER1_SWEBENCH: SWEBenchEvaluator,
}

# 各级别默认运行的层（按执行顺序排列）
_LEVEL_LAYERS: Dict[RunLevel, List[BenchmarkLayer]] = {
    RunLevel.OFFLINE_ONLY: [BenchmarkLayer.LAYER3_SAFETY],
    RunLevel.FAST:         [BenchmarkLayer.LAYER3_SAFETY, BenchmarkLayer.LAYER2_MEMORY],
    RunLevel.FULL:         [
        BenchmarkLayer.LAYER3_SAFETY,
        BenchmarkLayer.LAYER2_MEMORY,
        BenchmarkLayer.LAYER1_SWEBENCH,
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# Runner 核心
# ─────────────────────────────────────────────────────────────────────────────

def run_benchmark(config: BenchmarkConfig) -> BenchmarkResult:
    """运行 Benchmark 并返回结果"""
    result = BenchmarkResult(
        config={
            "level":         config.level.name,
            "domains":       config.domains,
            "dry_run":       config.dry_run,
            "llm_available": config.llm_available,
            "max_tasks":     config.max_tasks,
        }
    )

    # 确定要运行的层
    layers_to_run = config.layers or _LEVEL_LAYERS.get(config.level, [BenchmarkLayer.LAYER3_SAFETY])

    for layer in layers_to_run:
        evaluator_cls = _EVALUATOR_REGISTRY.get(layer)
        if not evaluator_cls:
            print(f"  [WARN] 未找到 {layer} 的评测器，跳过", file=sys.stderr)
            continue

        evaluator = evaluator_cls()

        # 如果当前环境不满足评测条件，跳过
        if not config.llm_available and not evaluator.is_offline_capable:
            print(f"  [SKIP] {layer.name}: 需要 LLM API（当前为离线模式）", file=sys.stderr)
            continue

        print(f"  [RUN]  Layer {layer.value}: {layer.name} ...", file=sys.stderr)
        t0 = time.monotonic()
        try:
            layer_result = evaluator.run(config)
        except Exception as exc:
            layer_result = LayerResult(
                layer=layer,
                name=evaluator.__class__.__name__,
                tasks_total=0,
                tasks_passed=0,
                tasks_skipped=0,
                tasks_failed=0,
                score=0.0,
                error=f"评测器异常: {exc}",
                duration_seconds=time.monotonic() - t0,
            )
        result.layer_results[layer.value] = layer_result
        print(
            f"  [DONE] Layer {layer.value} 得分: {layer_result.score:.4f} "
            f"({layer_result.tasks_passed}/{layer_result.tasks_total} 通过, "
            f"{layer_result.duration_seconds:.1f}s)",
            file=sys.stderr,
        )

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 报告输出
# ─────────────────────────────────────────────────────────────────────────────

def report(result: BenchmarkResult, config: BenchmarkConfig) -> None:
    """根据配置输出评测报告"""
    fmt = config.output_format.lower()

    if fmt == "console":
        print_result(result, verbose=config.verbose)

    elif fmt == "json":
        def _serialize(obj):
            if hasattr(obj, "value"):
                return obj.value
            if hasattr(obj, "__dataclass_fields__"):
                return asdict(obj)
            return str(obj)
        data = json.dumps(asdict(result), default=_serialize, indent=2, ensure_ascii=False)
        if config.output_path:
            Path(config.output_path).write_text(data, encoding="utf-8")
        else:
            print(data)

    elif fmt == "markdown":
        content = save_markdown(result, config.output_path)
        if not config.output_path:
            print(content)

    else:
        print(f"[WARN] 未知输出格式: {fmt}，回退到 console", file=sys.stderr)
        print_result(result, verbose=config.verbose)


# ─────────────────────────────────────────────────────────────────────────────
# CLI 入口（供 benchmark/run_benchmark_v2.py 调用）
# ─────────────────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="mulan benchmark",
        description="木兰（Mulan）三层 Benchmark v2 — 端侧 AI 代码工程工具链评测",
    )
    parser.add_argument(
        "--level", choices=["offline", "fast", "full"], default="offline",
        help="运行级别: offline=仅安全门控(无需LLM), fast=+记忆质量, full=+SWE-bench",
    )
    parser.add_argument(
        "--layer", type=int, choices=[1, 2, 3], default=None,
        help="仅运行指定单层（覆盖 --level）",
    )
    parser.add_argument(
        "--domain", nargs="+", default=["generic_python"],
        metavar="DOMAIN",
        help="评测 domain（可多选），默认: generic_python",
    )
    parser.add_argument(
        "--max-tasks", type=int, default=None,
        help="每层最多运行的任务数（调试用）",
    )
    parser.add_argument(
        "--llm", action="store_true", default=False,
        help="声明 LLM API 可用（开启在线评测维度）",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=False,
        help="仅打印任务列表，不实际执行",
    )
    parser.add_argument(
        "--output", choices=["console", "json", "markdown"], default="console",
        help="输出格式",
    )
    parser.add_argument(
        "--output-path", default=None,
        help="报告保存路径（json/markdown 时使用）",
    )
    parser.add_argument("-v", "--verbose", action="store_true", default=False)

    args = parser.parse_args(argv)

    level_map = {
        "offline": RunLevel.OFFLINE_ONLY,
        "fast":    RunLevel.FAST,
        "full":    RunLevel.FULL,
    }
    level = level_map[args.level]

    layers = None
    if args.layer:
        layers = [BenchmarkLayer(args.layer)]

    config = BenchmarkConfig(
        level=level,
        layers=layers or _LEVEL_LAYERS[level],
        domains=args.domain,
        max_tasks=args.max_tasks,
        dry_run=args.dry_run,
        llm_available=args.llm,
        output_format=args.output,
        output_path=args.output_path,
        verbose=args.verbose,
        repo_root=str(Path(__file__).resolve().parent.parent.parent),
    )

    print(f"[Mulan Benchmark v2] 级别: {args.level.upper()}", file=sys.stderr)
    result = run_benchmark(config)
    report(result, config)

    # 非零退出码表示评测未通过
    return 0 if result.overall_score >= 0.6 else 1
