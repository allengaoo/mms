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
    seed_memories_loaded: int = 0      # Phase 8: 注入的 seed pack 记忆数量
    weights_profile_used: str = ""     # Phase 3: 使用的权重 profile 名称

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
        gc_archived: List[str] = getattr(self, "gc_archived", [])
        if gc_archived:
            print(f"  结构性GC : 归档 {len(gc_archived)} 个孤立节点")
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
    weights_profile: Optional[str] = None,
    weights_overrides: Optional[dict] = None,
) -> BootstrapV2Report:
    """
    Bootstrap v2：完整执行 action_bootstrap 的 9 条 Rules。

    这是 cli.py cmd_bootstrap 的新实现，取代旧版分散逻辑。

    Args:
        project_root:      项目根目录（默认当前工作区）
        dry_run:           不写文件，只返回分析结果
        skip_ast:          跳过 AST 扫描和所有后续步骤
        skip_seeds:        跳过种子包注入
        skip_memory_gen:   跳过初始记忆生成（只做结构分析）
        min_confidence:    层推断最低置信度（低于此值不生成记忆）
        max_per_layer:     每层最多生成记忆数
        verbose:           是否打印步骤进度
        weights_profile:   信号权重模板名（"java_spring_boot"/"python_fastapi"/"go_gin" 等）
                           None 时自动从 .mms/bootstrap_config.yaml 读取，再 fallback 到 base
        weights_overrides: 精细覆盖单个权重（如 {"annotation": 0.45}），与模板合并

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
            from mms.bootstrap.seed_packs import install_packs  # type: ignore
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

        # 自动从 .mms/bootstrap_config.yaml 读取权重 profile（若调用方未显式指定）
        effective_profile = weights_profile
        effective_overrides = weights_overrides
        if effective_profile is None:
            mms_config_path = root / ".mms" / "bootstrap_config.yaml"
            if mms_config_path.exists():
                try:
                    import yaml as _yaml
                    cfg = _yaml.safe_load(mms_config_path.read_text()) or {}
                    effective_profile = cfg.get("signal_weights_profile")
                    cfg_overrides = cfg.get("signal_weights")
                    if cfg_overrides and isinstance(cfg_overrides, dict):
                        effective_overrides = {**cfg_overrides, **(effective_overrides or {})}
                except Exception:
                    pass

        if effective_profile:
            log(f"  使用信号权重模板: {effective_profile}")

        inference_results = infer_all(
            ast_index=ast_index,
            code_graph_in_degrees=in_degrees,
            min_confidence=min_confidence,
            project_root=root,
            detected_stacks=report.detected_stacks,
            weights_profile=effective_profile,
            weights_overrides=effective_overrides,
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

    # ── Rule 07+08: 生成初始记忆（增量模式）────────────────────────────────────
    if not skip_memory_gen and inference_results:
        log(f"\n▶ Step 6/6 · 生成初始 MemoryNode（min_confidence={min_confidence}）...")
        try:
            from mms.bootstrap.memory_seed_generator import generate_seed_memories  # type: ignore
            shared_dir = root / "docs" / "memory" / "shared"

            # 增量 Bootstrap：扫描已有 MEM-BOOT-*.md，提取 class_name → fingerprint 映射
            # 若推断出的类的 fingerprint 与已有记忆一致，跳过生成（幂等）
            existing_boot_fps: dict = {}
            if shared_dir.exists():
                import re as _re
                for md_path in shared_dir.rglob("MEM-BOOT-*.md"):
                    try:
                        text = md_path.read_text(encoding="utf-8", errors="ignore")
                        cls_m = _re.search(r"class_name:\s*(\S+)", text)
                        if not cls_m:
                            continue
                        class_name_key = cls_m.group(1).strip()
                        # 提取 fingerprint（可能为空）
                        fp_m = _re.search(r"fingerprint:\s*(sha256:[a-f0-9]+)", text)
                        fp_val = fp_m.group(1) if fp_m else ""
                        existing_boot_fps[class_name_key] = fp_val
                    except Exception:
                        pass
            if existing_boot_fps:
                log(f"  ℹ️  已有 {len(existing_boot_fps)} 条 MEM-BOOT 记忆，增量模式生效")

            gen_report = generate_seed_memories(
                inference_results=inference_results,
                ast_index=ast_index,
                output_dir=shared_dir,
                min_confidence=min_confidence,
                max_per_layer=max_per_layer,
                dry_run=dry_run,
                existing_fingerprints=existing_boot_fps,
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

    # ── Rule 08: 结构性 GC（孤立 Bootstrap 节点归档）────────────────────────────
    # 在完整 AST 运行完成后，对比现有 MEM-BOOT-*.md 与最新 AST index：
    # 若某节点的 class_name 已不在 ast_index 中，说明对应类已被删除/重命名，
    # 将该节点移入 _archived/ 子目录（软删除，保留历史）。
    #
    # 此 GC 与 entropy_scan 的 LFU 访问频率清理完全独立：
    #   - 结构性 GC：代码锚点丢失（源码删类）→ 孤立节点
    #   - LFU 清理：记忆从未被查询访问（access_count=0）→ 低价值节点
    if not skip_ast and not dry_run and ast_index:
        try:
            gc_report = _run_structural_gc(
                ast_index=ast_index,
                project_root=root,
                dry_run=dry_run,
                log=log,
            )
            report.gc_archived = gc_report  # type: ignore[attr-defined]
        except Exception as e:
            log(f"  ⚠️  结构性 GC 异常（跳过）: {e}")
            report.errors.append(f"结构性 GC 失败: {e}")

    report.elapsed_s = time.time() - start

    # ── Phase 8: Schema 演进反馈回路 ──────────────────────────────────────────
    if not dry_run:
        try:
            from mms.bootstrap.schema_evolution import (
                BootstrapRunStats,
                record_bootstrap_run,
            )
            import uuid as _uuid
            gc_archived_list: List[str] = getattr(report, "gc_archived", [])
            mem_paths = [Path(p) for p in report.memory_files if p]
            evo_stats = BootstrapRunStats(
                run_id=str(_uuid.uuid4())[:8],
                project_path=str(root),
                weights_profile=report.weights_profile_used
                    if hasattr(report, "weights_profile_used") else "base",
                total_files=report.files_scanned,
                total_classes=report.classes_found,
                memories_generated=report.memories_generated,
                memories_archived=len(gc_archived_list),
                inferences=inferences if "inferences" in dir() else {},
                memory_files=mem_paths,
            )
            log_p, md_p = record_bootstrap_run(
                evo_stats,
                output_dir=root / "docs" / "memory" / "_system",
            )
            log(f"  📊  Schema 演进报告已更新: {md_p.name}")
        except Exception as e:
            log(f"  ⚠️  Schema 演进报告生成失败（跳过）: {e}")

    if verbose:
        report.print_summary()
    return report


def _run_structural_gc(
    ast_index: Dict,
    project_root: Path,
    dry_run: bool,
    log,
) -> List[str]:
    """
    Rule 08: 结构性 GC — 将孤立的 MEM-BOOT-*.md 归档（软删除）。

    判断孤立标准：MEM-BOOT-*.md 中记录的 class_name 在最新 ast_index 中不存在
    （即对应的源码类已被删除/重命名）。

    归档策略：
        - 将孤立节点移至同层的 _archived/ 子目录（不物理删除）
        - 归档文件名添加 .orphan 后缀，方便识别
        - 在归档文件头部追加注释说明归档原因

    Args:
        ast_index:      最新的 AST index（来自本次 Bootstrap 运行）
        project_root:   项目根目录
        dry_run:        若 True，只报告不执行移动
        log:            日志函数

    Returns:
        已归档的文件路径列表（相对 project_root）
    """
    import re as _re
    import shutil

    shared_dir = project_root / "docs" / "memory" / "shared"
    if not shared_dir.exists():
        return []

    # 构建当前所有 class_name 的集合（用于快速查找）
    current_class_names: set = set()
    for file_data in ast_index.values():
        for cls in file_data.get("classes", []):
            name = cls.get("name", "")
            if name:
                current_class_names.add(name)

    archived: List[str] = []

    for md_path in sorted(shared_dir.rglob("MEM-BOOT-*.md")):
        # 跳过已在 _archived 目录中的文件
        if "_archived" in md_path.parts:
            continue

        try:
            text = md_path.read_text(encoding="utf-8", errors="ignore")
            m = _re.search(r"class_name:\s*(\S+)", text)
            if not m:
                continue
            class_name = m.group(1).strip()
        except Exception:
            continue

        if class_name in current_class_names:
            continue  # 对应类仍然存在，保留

        # 对应类已消失 → 归档
        archived_dir = md_path.parent / "_archived"
        archived_path = archived_dir / (md_path.stem + ".orphan.md")

        rel = str(md_path.relative_to(project_root))
        if dry_run:
            log(f"  🗑  [dry-run] 孤立节点待归档: {rel}")
        else:
            archived_dir.mkdir(parents=True, exist_ok=True)
            # 在文件头部追加归档说明
            import datetime as _dt
            archive_header = (
                f"<!-- ARCHIVED: class '{class_name}' no longer exists in AST index. "
                f"Archived by structural GC on {_dt.date.today()}. -->\n"
            )
            archived_path.write_text(archive_header + text, encoding="utf-8")
            md_path.unlink()
            log(f"  🗑  孤立节点已归档: {rel} → _archived/{archived_path.name}")

        archived.append(rel)

    if archived:
        log(f"\n▶ [结构性 GC] 共归档 {len(archived)} 个孤立 Bootstrap 节点"
            f"{'（dry-run，未实际移动）' if dry_run else ''}")
    else:
        log("\n▶ [结构性 GC] 未发现孤立节点，图谱一致")

    return archived
