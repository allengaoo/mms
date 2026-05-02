"""
src/mms/bootstrap/ontology_populator.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Bootstrap v2 顶层编排器（action_bootstrap 的完整实现）

执行 action_bootstrap 中定义的 9 条 Rules，将 Layer 0（物理代码）
转化为 Layer 2（记忆本体图）的初始状态。

替代旧版 cmd_bootstrap 中分散在 cli.py 的逻辑，
并注册 fn_infer_layer / fn_build_code_graph 到 FunctionRegistry。

版本：v2.0 | 创建于：2026-04-30 | Bootstrap v2
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

try:
    from mms.utils._paths import _PROJECT_ROOT as _DEFAULT_ROOT  # type: ignore
except ImportError:
    _DEFAULT_ROOT = Path.cwd()


# ─── 报告数据类 ───────────────────────────────────────────────────────────────

@dataclass
class BootstrapV2Report:
    project_root: str = ""
    elapsed_s: float = 0.0
    detected_stacks: List[str] = field(default_factory=list)
    stack_confidence: float = 0.0
    injected_seed_packs: List[str] = field(default_factory=list)

    # AST 统计
    files_scanned: int = 0
    classes_found: int = 0
    methods_found: int = 0

    # 代码图统计
    graph_nodes: int = 0
    graph_edges: int = 0
    cycle_count: int = 0

    # 推断统计
    classes_inferred: int = 0
    classes_skipped: int = 0
    layer_distribution: Dict[str, int] = field(default_factory=dict)

    # 记忆生成统计
    memories_generated: int = 0
    memories_per_layer: Dict[str, int] = field(default_factory=dict)
    memory_files: List[str] = field(default_factory=list)

    dry_run: bool = False
    errors: List[str] = field(default_factory=list)

    def print_summary(self) -> None:
        """打印 Bootstrap 执行摘要。"""
        print(f"\n{'='*60}")
        print(f"  MMS Bootstrap v2 完成（耗时 {self.elapsed_s:.1f}s，零 LLM 调用）")
        print(f"{'='*60}")
        print(f"  项目根目录 : {self.project_root}")
        print(f"  技术栈     : {self.detected_stacks} ({self.stack_confidence:.0%})")
        print(f"  种子包     : {len(self.injected_seed_packs)} 个已注入")
        print()
        print(f"  AST 扫描   : {self.files_scanned} 个文件 / "
              f"{self.classes_found} 个类 / {self.methods_found} 个方法")
        print(f"  依赖图     : {self.graph_nodes} 节点 / "
              f"{self.graph_edges} 边 / {self.cycle_count} 个循环依赖")
        print()
        print(f"  层推断     : {self.classes_inferred} 个类（跳过 {self.classes_skipped} 个）")
        if self.layer_distribution:
            for layer, count in sorted(self.layer_distribution.items()):
                print(f"               {layer:<10}: {count} 个类")
        print()
        print(f"  记忆生成   : {self.memories_generated} 条 MEM-BOOT-*.md")
        if self.memories_per_layer:
            for layer, count in sorted(self.memories_per_layer.items()):
                print(f"               {layer:<10}: {count} 条")
        if self.dry_run:
            print(f"\n  ⚠️  dry-run 模式，文件未实际写入")
        if self.errors:
            print(f"\n  ⚠️  {len(self.errors)} 个错误：")
            for e in self.errors:
                print(f"     - {e}")
        print(f"{'='*60}\n")


# ─── bootstrap_project 主函数 ─────────────────────────────────────────────────

# ── 项目文档自动扫描（Step 1.5）─────────────────────────────────────────────

# 特征文件列表（按优先级排列）
_DOC_CANDIDATES = [
    "CONTRIBUTING.md",
    ".cursorrules",
    "ARCHITECTURE.md",
    "CODING_GUIDELINES.md",
    "docs/arch.md",
    "docs/ARCHITECTURE.md",
    ".github/CONTRIBUTING.md",
    "DEVELOPMENT.md",
    "CONVENTIONS.md",
]


def _absorb_project_docs(
    root: Path,
    dry_run: bool,
    log,
) -> List[str]:
    """
    Step 1.5: 扫描项目根目录下的开发文档，调用 seed_absorber 蒸馏为约束规则。

    生成结果写入 docs/memory/shared/CC/_absorb_draft/（需人工 promote）。
    无 API key 时降级为跳过（不报错）。

    Returns:
        已处理的文件名列表
    """
    found_files = [root / name for name in _DOC_CANDIDATES if (root / name).exists()]
    if not found_files:
        return []

    log(f"\n▶ Step 1.5/6 · 项目文档扫描（发现 {len(found_files)} 个文档）...")
    for f in found_files:
        log(f"  📄 {f.name}")

    out_dir = root / "docs" / "memory" / "shared" / "CC" / "_absorb_draft"
    processed: List[str] = []

    try:
        from mms.analysis.seed_absorber import absorb  # type: ignore
    except ImportError:
        log("  ⚠️  seed_absorber 未找到，跳过文档蒸馏")
        return []

    for fpath in found_files:
        try:
            absorb(
                str(fpath),
                dry_run=dry_run,
                out_dir=str(out_dir) if not dry_run else None,
            )
            processed.append(fpath.name)
            log(f"  ✅ 已蒸馏: {fpath.name}")
        except Exception as e:
            err_msg = str(e)
            # 无 API Key 或网络错误时静默跳过（不阻断 Bootstrap 主流程）
            if "API" in err_msg or "key" in err_msg.lower() or "auth" in err_msg.lower():
                log(f"  ⚠️  {fpath.name} 蒸馏跳过（未配置 LLM API Key）")
            else:
                log(f"  ⚠️  {fpath.name} 蒸馏失败（可忽略）: {err_msg[:80]}")

    if processed and not dry_run:
        log(f"  📂 草稿已写入: docs/memory/shared/CC/_absorb_draft/")
        log(f"  💡 使用 mulan seed list 查看，人工审核后可 promote 到 CC/")

    return processed


def bootstrap_project(
    project_root: Optional[Path] = None,
    dry_run: bool = False,
    skip_ast: bool = False,
    skip_seeds: bool = False,
    skip_memory_gen: bool = False,
    skip_doc_absorb: bool = False,
    min_confidence: float = 0.5,
    max_per_layer: int = 10,
    verbose: bool = True,
) -> BootstrapV2Report:
    """
    Bootstrap v2：完整执行 action_bootstrap 的 9 条 Rules。

    这是 cli.py cmd_bootstrap 的新实现，取代旧版分散逻辑。

    Args:
        project_root:     项目根目录（默认当前工作区）
        dry_run:          不写文件，只返回分析结果
        skip_ast:         跳过 AST 扫描和所有后续步骤
        skip_seeds:       跳过种子包注入
        skip_memory_gen:  跳过初始记忆生成（只做结构分析）
        min_confidence:   层推断最低置信度（低于此值不生成记忆）
        max_per_layer:    每层最多生成记忆数
        verbose:          是否打印步骤进度

    Returns:
        BootstrapV2Report
    """
    root = project_root or _DEFAULT_ROOT
    report = BootstrapV2Report(project_root=str(root), dry_run=dry_run)
    start = time.time()
    report.absorbed_docs = []  # type: ignore[attr-defined]

    def log(msg: str) -> None:
        if verbose:
            print(msg)

    # ── 注册 Function 实现到 FunctionRegistry ─────────────────────────────────
    try:
        from mms.ontology.registry import get_ontology_registry  # type: ignore
        onto = get_ontology_registry()
        from mms.bootstrap.signal_fusion import infer_layer, detect_code_object_type
        from mms.bootstrap.code_graph_builder import build_code_graph
        onto.functions.register_implementation("fn_infer_layer", infer_layer)
        onto.functions.register_implementation("fn_detect_code_object_type", detect_code_object_type)
        onto.functions.register_implementation("fn_build_code_graph", build_code_graph)
    except Exception as e:
        report.errors.append(f"OntologyRegistry 注册失败: {e}")

    # ── Rule 01: 技术栈嗅探 ────────────────────────────────────────────────────
    log("\n▶ Step 1/6 · 技术栈嗅探（action_bootstrap Rule 01）...")
    try:
        from mms.analysis.dep_sniffer import sniff  # type: ignore
        profile = sniff(root=root)
        report.detected_stacks = profile.detected_stacks
        report.stack_confidence = profile.confidence
        log(f"  检测到栈：{profile.detected_stacks}  置信度：{profile.confidence:.0%}")
        log(f"  扫描来源：{profile.scan_sources}")
    except Exception as e:
        report.errors.append(f"技术栈嗅探失败: {e}")
        report.detected_stacks = ["base"]

    # ── Step 1.5: 项目文档自动蒸馏（可选，不阻断主流程）─────────────────────────
    if not skip_doc_absorb:
        try:
            absorbed = _absorb_project_docs(root=root, dry_run=dry_run, log=log)
            report.absorbed_docs = absorbed  # type: ignore[attr-defined]
        except Exception as e:
            log(f"  ⚠️  文档扫描异常（跳过）: {e}")
    else:
        log("\n▶ Step 1.5/6 · 跳过项目文档扫描（--skip-doc-absorb）")

    # ── Rule 02: 种子包注入 ────────────────────────────────────────────────────
    if not skip_seeds:
        log("\n▶ Step 2/6 · 注入种子包（v3.1 格式优先）...")
        try:
            from seed_packs import install_packs  # type: ignore
            target_docs = root / "docs"
            installed = install_packs(
                pack_names=report.detected_stacks,
                target_docs=target_docs,
                dry_run=dry_run,
            )
            report.injected_seed_packs = installed or []
            log(f"  ✅ 已注入 {len(report.injected_seed_packs)} 个种子包")
        except Exception as e:
            report.errors.append(f"种子包注入失败: {e}")
    else:
        log("\n▶ Step 2/6 · 跳过种子包注入（--skip-seeds）")

    if skip_ast:
        log("\n▶ Step 3-6 · 跳过 AST 相关步骤（--skip-ast）")
        report.elapsed_s = time.time() - start
        if verbose:
            report.print_summary()
        return report

    # ── Rule 03: AST 骨架化 ────────────────────────────────────────────────────
    log("\n▶ Step 3/6 · AST 骨架化（生成 CodeFile + CodeClass 实例）...")
    ast_index: Dict = {}
    try:
        from mms.analysis.ast_skeleton import build_ast_index  # type: ignore
        t0 = time.time()
        ast_index = build_ast_index(root=root, dry_run=dry_run)
        elapsed = time.time() - t0

        total_classes = sum(len(v.get("classes", [])) for v in ast_index.values())
        total_methods = sum(
            len(c.get("methods", []))
            for v in ast_index.values()
            for c in v.get("classes", [])
        )
        report.files_scanned  = len(ast_index)
        report.classes_found  = total_classes
        report.methods_found  = total_methods
        log(f"  ✅ {len(ast_index)} 个文件 / {total_classes} 个类 / "
            f"{total_methods} 个方法（{elapsed:.1f}s）")
    except Exception as e:
        report.errors.append(f"AST 骨架化失败: {e}")

    # ── Rule 04: 构建代码依赖图 ───────────────────────────────────────────────
    log("\n▶ Step 4/6 · 构建代码依赖图（depends_on / implements 边）...")
    code_graph = None
    in_degrees: Dict[str, int] = {}
    try:
        from mms.bootstrap.code_graph_builder import build_code_graph  # type: ignore
        code_graph = build_code_graph(ast_index=ast_index, project_root=root)
        in_degrees = code_graph.in_degree
        report.graph_nodes = code_graph.stats.get("node_count", 0)
        report.graph_edges = code_graph.stats.get("edge_count", 0)
        report.cycle_count = code_graph.stats.get("cycle_count", 0)
        max_cls = code_graph.stats.get("max_in_degree_class", "")
        log(f"  ✅ {report.graph_nodes} 节点 / {report.graph_edges} 边 / "
            f"{report.cycle_count} 循环依赖")
        if max_cls:
            log(f"  🔑 最高入度类: {max_cls} (in={code_graph.stats.get('max_in_degree', 0)})")

        # 写入代码图缓存（供后续 mulan graph 命令使用）
        if not dry_run:
            import json
            graph_cache = root / "docs" / "memory" / "_system" / "code_graph.json"
            graph_cache.parent.mkdir(parents=True, exist_ok=True)
            cache_data = {
                "stats": code_graph.stats,
                "in_degree": {k: v for k, v in list(code_graph.in_degree.items())[:200]},
                "top_depends_on": [
                    {"source": e.source_fqn[:80], "target": e.target_fqn[:80]}
                    for e in code_graph.depends_on[:100]
                ],
            }
            graph_cache.write_text(json.dumps(cache_data, ensure_ascii=False, indent=2))
    except Exception as e:
        report.errors.append(f"代码图构建失败: {e}")

    # ── Rule 05+06: 五路信号推断 ──────────────────────────────────────────────
    log("\n▶ Step 5/6 · 五路信号推断（fn_infer_layer + fn_detect_code_object_type）...")
    inference_results = {}
    layer_dist: Dict[str, int] = {}
    try:
        from mms.bootstrap.signal_fusion import infer_all  # type: ignore
        inference_results = infer_all(
            ast_index=ast_index,
            code_graph_in_degrees=in_degrees,
            min_confidence=min_confidence,
            project_root=root,
            detected_stacks=report.detected_stacks,
        )
        inferred = sum(1 for _, (li, _) in inference_results.items() if li.confidence >= min_confidence)
        skipped  = len(inference_results) - inferred
        report.classes_inferred = inferred
        report.classes_skipped  = skipped

        for _, (li, _) in inference_results.items():
            if li.inferred_layer != "UNKNOWN":
                layer_dist[li.inferred_layer] = layer_dist.get(li.inferred_layer, 0) + 1
        report.layer_distribution = layer_dist

        log(f"  ✅ {inferred} 个类推断成功（跳过 {skipped} 个低置信度）")
        for layer, count in sorted(layer_dist.items()):
            log(f"     {layer:<10}: {count} 个类")
    except Exception as e:
        report.errors.append(f"信号推断失败: {e}")

    # ── Rule 07+08: 生成初始记忆 ─────────────────────────────────────────────
    if not skip_memory_gen and inference_results:
        log(f"\n▶ Step 6/6 · 生成初始 MemoryNode（min_confidence={min_confidence}）...")
        try:
            from mms.bootstrap.memory_seed_generator import generate_seed_memories  # type: ignore
            shared_dir = root / "docs" / "memory" / "shared"
            gen_report = generate_seed_memories(
                inference_results=inference_results,
                ast_index=ast_index,
                output_dir=shared_dir,
                min_confidence=min_confidence,
                max_per_layer=max_per_layer,
                dry_run=dry_run,
            )
            report.memories_generated = gen_report.total
            report.memories_per_layer = gen_report.layer_distribution
            report.memory_files = [str(m.file_path) for m in gen_report.generated]
            log(f"  ✅ 生成 {gen_report.total} 条 MEM-BOOT-*.md")
            for layer, count in sorted(gen_report.layer_distribution.items()):
                log(f"     {layer:<10}: {count} 条")
        except Exception as e:
            report.errors.append(f"记忆生成失败: {e}")
    elif skip_memory_gen:
        log("\n▶ Step 6/6 · 跳过初始记忆生成（--skip-memory-gen）")
    else:
        log("\n▶ Step 6/6 · 推断结果为空，跳过记忆生成")

    report.elapsed_s = time.time() - start
    if verbose:
        report.print_summary()
    return report
