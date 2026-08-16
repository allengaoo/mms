#!/usr/bin/env python3
"""
MDP Memory System — 知识蒸馏器 v2.1（EP-108 重构）

将 EP 执行记录蒸馏为结构化记忆文件（MEM-*.md），并自动更新索引。

核心流程：
  1. 加载 EP 执行计划文件（可选：私有记忆 private/EP-NNN/）
  2. 上下文压缩（deepseek-r1:8b，30K→2K token）
  3. 知识蒸馏（deepseek-r1:8b，提炼教训/决策/模式）
  4. 相似度检测（nomic-embed-text，避免重复记忆）
  5. 生成 MEM-*.md 文件（原子写入）
  6. 增量更新 MEMORY_INDEX.json
  7. 运行 GC（LFU 淘汰 + tier 重计算）
  8. 写入审计日志

用法：
  python scripts/memory_distill.py --ep EP-108
  python scripts/memory_distill.py --ep EP-108 --ep-file custom/path.md
  python scripts/memory_distill.py --ep EP-108 --dry-run
  python scripts/memory_distill.py --ep EP-108 --resume MMS-20260411-a1b2c3
  python scripts/memory_distill.py --list-incomplete
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# 将 scripts/ 目录加入 sys.path，使 mms 包可直接 import
sys.path.insert(0, str(Path(__file__).parent))

from mms.core.indexer import IncrementalIndexer
from mms.core.writer import atomic_write
from mms.observability.audit import AuditLogger
from mms.observability.tracer import new_trace_id
from mms.providers.claude import ProviderPendingError
from mms.providers.factory import auto_detect, get_embed
from mms.resilience.checkpoint import Checkpoint
from mms.resilience.circuit_breaker import CircuitBreaker, CircuitOpenError
from mms.resilience.retry import RetryExhaustedError, with_retry
from mms.router import compress_context

# ─── 路径配置 ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
MEMORY_ROOT = PROJECT_ROOT / "docs" / "memory"
SHARED_DIR = MEMORY_ROOT / "shared"
PRIVATE_DIR = MEMORY_ROOT / "private"
INDEX_FILE = MEMORY_ROOT / "MEMORY_INDEX.json"
EP_PLANS_DIR = PROJECT_ROOT / "docs" / "execution_plans"

# Layer × Dimension 目录映射
LAYER_DIM_DIRS: Dict[Tuple[str, str], Path] = {
    ("L1", "D1"): SHARED_DIR / "L1_platform" / "D1_security",
    ("L1", "D3"): SHARED_DIR / "L1_platform" / "D3_observability",
    ("L2", "D9"): SHARED_DIR / "L2_infrastructure" / "D9_database",
    ("L2", "D6"): SHARED_DIR / "L2_infrastructure" / "D6_messaging",
    ("L2", "D4"): SHARED_DIR / "L2_infrastructure" / "D4_resilience",
    ("L2", "D5"): SHARED_DIR / "L2_infrastructure" / "D5_distributed",
    ("L2", "D7"): SHARED_DIR / "L2_infrastructure" / "D7_cache",
    ("L3", "ontology"): SHARED_DIR / "L3_domain" / "ontology",
    ("L3", "data_pipeline"): SHARED_DIR / "L3_domain" / "data_pipeline",
    ("L3", "governance"): SHARED_DIR / "L3_domain" / "governance",
    ("L4", "D2"): SHARED_DIR / "L4_application" / "D2_architecture",
    ("L5", "D8"): SHARED_DIR / "L5_interface" / "D8_api",
    ("L5", "D10"): SHARED_DIR / "L5_interface" / "D10_testing",
    ("CC", "decisions"): SHARED_DIR / "cross_cutting" / "decisions",
    ("CC", "patterns"): SHARED_DIR / "cross_cutting" / "patterns",
}

# 蒸馏 Prompt 模板（针对 deepseek-r1:8b 优化，≤2K token 输入）
_DISTILL_PROMPT = """
你是 MDP 项目的记忆蒸馏器。从以下 EP 摘要中提炼结构化记忆。

EP 编号：{ep_id}
EP 摘要：
{ep_summary}

现有记忆标签（避免重复）：
{existing_tags}

输出要求：严格返回 JSON 数组，每条记忆包含：
- id_suffix: 推荐的 ID 后缀（如 "025"）
- id_prefix: MEM-L / MEM-E / AD / PAT
- layer: L1-L5 或 CC
- dimension: D1-D10 或 ontology/data_pipeline/governance/decisions/patterns
- type: lesson / decision / error / pattern
- tier: hot（常用）/ warm（偶用）
- tags: 字符串数组（3-6 个关键词）
- title: 简洁的记忆标题（≤30字）
- where: 哪个模块/场景
- what: 发生了什么
- why: 根本原因
- how: 解决方案或最佳实践
- when: 触发条件

只输出 JSON，不要其他内容。示例：
[{{"id_prefix":"MEM-L","id_suffix":"025","layer":"L2","dimension":"D6","type":"lesson","tier":"warm","tags":["kafka","partition"],"title":"示例标题","where":"...","what":"...","why":"...","how":"...","when":"..."}}]
""".strip()


# ─── 辅助函数 ────────────────────────────────────────────────────────────────

def load_ep_content(ep_id: str, ep_file: Optional[Path] = None) -> str:
    """加载 EP 执行计划文件内容"""
    if ep_file and ep_file.exists():
        return ep_file.read_text(encoding="utf-8")

    candidates = list(EP_PLANS_DIR.glob(f"{ep_id}_*.md")) + \
                 list(EP_PLANS_DIR.glob(f"{ep_id}.md"))
    if candidates:
        return candidates[0].read_text(encoding="utf-8")

    private_dir = PRIVATE_DIR / ep_id
    if private_dir.exists():
        parts = [f.read_text(encoding="utf-8") for f in sorted(private_dir.glob("*.md"))]
        if parts:
            return "\n\n---\n\n".join(parts)

    return f"EP 文件未找到：{ep_id}（请通过 --ep-file 指定路径）"


def get_existing_tags() -> List[str]:
    """收集现有记忆的所有 tags，用于去重提示"""
    tags: set = set()
    for md in MEMORY_ROOT.rglob("MEM-*.md"):
        content = md.read_text(encoding="utf-8")
        m = re.search(r"tags:\s*\[([^\]]+)\]", content)
        if m:
            for t in m.group(1).split(","):
                tags.add(t.strip().strip("\"'"))
    return sorted(tags)


def next_memory_id(prefix: str, layer: str, dim: str) -> str:
    """生成下一个可用的记忆 ID（扫描目录找最大编号）"""
    target_dir = LAYER_DIM_DIRS.get((layer, dim), SHARED_DIR / "cross_cutting" / "patterns")
    max_num = 0
    pattern = re.compile(rf"{re.escape(prefix)}-(\d+)\.md$")
    for md in MEMORY_ROOT.rglob(f"{prefix}-*.md"):
        m = pattern.search(md.name)
        if m:
            max_num = max(max_num, int(m.group(1)))
    return f"{prefix}-{str(max_num + 1).zfill(3)}"


def generate_memory_file(mem: dict, ep_id: str) -> Tuple[Path, str]:
    """根据蒸馏结果生成 MEM-*.md 文件内容和路径"""
    layer = mem.get("layer", "CC")
    dim = mem.get("dimension", "patterns")
    prefix = mem.get("id_prefix", "MEM-L")
    mem_id = f"{prefix}-{mem.get('id_suffix', '000').zfill(3)}"
    today = datetime.date.today().strftime("%Y-%m-%d")

    target_dir = LAYER_DIM_DIRS.get((layer, dim), SHARED_DIR / "cross_cutting" / "patterns")
    target_dir.mkdir(parents=True, exist_ok=True)

    tags_str = "[" + ", ".join(mem.get("tags", [])) + "]"
    content = f"""---
id: {mem_id}
layer: {layer}
dimension: {dim}
type: {mem.get("type", "lesson")}
tier: {mem.get("tier", "warm")}
tags: {tags_str}
source_ep: {ep_id}
created_at: "{today}"
last_accessed: "{today}"
access_count: 0
related_memories: []
also_in: []
generalized: false
version: 1
---

# {mem_id} · {mem.get("title", "未命名记忆")}

## WHERE（在哪个模块/场景中）
{mem.get("where", "")}

## WHAT（发生了什么）
{mem.get("what", "")}

## WHY（根本原因）
{mem.get("why", "")}

## HOW（解决方案）
{mem.get("how", "")}

## WHEN（触发条件）
{mem.get("when", "")}
"""
    file_path = target_dir / f"{mem_id}.md"
    return file_path, content


def check_duplicate(
    new_tags: List[str],
    existing_tags_per_id: Dict[str, List[str]],
    threshold: float = 0.6,
) -> Optional[str]:
    """Tag 重叠率检测（不依赖向量），返回疑似重复的 ID"""
    new_set = set(new_tags)
    for mem_id, tags in existing_tags_per_id.items():
        existing_set = set(tags)
        if not existing_set:
            continue
        overlap = len(new_set & existing_set) / len(new_set | existing_set)
        if overlap >= threshold:
            return mem_id
    return None


# ─── 主流程 ──────────────────────────────────────────────────────────────────

def run_distillation(
    ep_id: str,
    ep_file: Optional[Path],
    dry_run: bool,
    trace_id: str,
    resume_checkpoint: Optional[str],
) -> List[str]:
    """
    执行蒸馏主流程，返回新生成的记忆 ID 列表。
    支持断点续传（通过 resume_checkpoint 指定 trace_id）。
    """
    logger = AuditLogger()
    cp = Checkpoint()
    indexer = IncrementalIndexer()
    cb = CircuitBreaker(model_name="deepseek-r1:8b")

    t_start = time.time()

    # 恢复断点
    checkpoint_state = None
    if resume_checkpoint:
        checkpoint_state = cp.load(resume_checkpoint)
        if checkpoint_state:
            trace_id = checkpoint_state.trace_id
            print(f"📌 恢复断点：{trace_id}（已完成: {checkpoint_state.processed_sections}）")

    # Step 1: 加载 EP 内容
    if not (checkpoint_state and checkpoint_state.is_section_done("load")):
        print(f"📖 加载 EP: {ep_id}...")
        ep_content = load_ep_content(ep_id, ep_file)
        cp.save(trace_id, {
            "ep_id": ep_id, "op": "distillation",
            "processed_sections": ["load"],
            "pending_sections": ["compress", "distill", "write"],
            "ep_content_len": len(ep_content),
            "partial_results": [],
        })
    else:
        ep_content = load_ep_content(ep_id, ep_file)

    # Step 2: 上下文压缩（EP 过长时）
    if not (checkpoint_state and checkpoint_state.is_section_done("compress")):
        if len(ep_content) > 8000:
            print(f"🗜️  上下文压缩（原始 {len(ep_content)} 字符）...")
            try:
                ep_summary = cb.call(
                    with_retry(max_attempts=3)(compress_context),
                    ep_content, 2000, trace_id, ep_id
                )
            except (CircuitOpenError, RetryExhaustedError) as e:
                print(f"⚠️  压缩跳过（{e.__class__.__name__}），使用原文前 8000 字符")
                ep_summary = ep_content[:8000]
        else:
            ep_summary = ep_content
        cp.save(trace_id, {
            "ep_id": ep_id, "op": "distillation",
            "processed_sections": ["load", "compress"],
            "pending_sections": ["distill", "write"],
            "partial_results": [],
        })
    else:
        ep_summary = ep_content[:8000]

    # Step 3: 知识蒸馏
    if not (checkpoint_state and checkpoint_state.is_section_done("distill")):
        existing_tags = get_existing_tags()
        prompt = _DISTILL_PROMPT.format(
            ep_id=ep_id,
            ep_summary=ep_summary[:6000],
            existing_tags=", ".join(existing_tags[:50]),
        )

        try:
            provider = auto_detect("distillation")
            print(f"🧠 调用 {provider.model_name} 进行知识蒸馏...")

            @with_retry(max_attempts=3, exceptions=(Exception,))
            def call_llm():
                return cb.call(provider.complete, prompt, 2000)

            raw_output = call_llm()
        except ProviderPendingError as e:
            print(str(e))
            logger.log(trace_id, "distill", ep=ep_id, result="pending",
                       error=str(e)[:200])
            return []
        except (CircuitOpenError, RetryExhaustedError) as e:
            print(f"❌ 蒸馏失败: {e}")
            logger.log(trace_id, "distill", ep=ep_id, result="error",
                       error=str(e)[:200])
            return []

        # 解析 JSON 输出
        json_match = re.search(r"\[.*\]", raw_output, re.DOTALL)
        if not json_match:
            print(f"⚠️  模型输出无法解析为 JSON，原始输出：\n{raw_output[:500]}")
            return []

        try:
            memories = json.loads(json_match.group())
        except json.JSONDecodeError as e:
            print(f"⚠️  JSON 解析错误: {e}")
            return []

        cp.save(trace_id, {
            "ep_id": ep_id, "op": "distillation",
            "processed_sections": ["load", "compress", "distill"],
            "pending_sections": ["write"],
            "partial_results": memories,
        })
    else:
        memories = checkpoint_state.partial_results if checkpoint_state else []

    # Step 4: 写入记忆文件
    new_ids: List[str] = []
    existing_tags_per_id = {}

    if not dry_run:
        print(f"💾 写入 {len(memories)} 条新记忆...")
        for mem in memories:
            file_path, content = generate_memory_file(mem, ep_id)
            mem_id = file_path.stem

            # 重复检测
            dup = check_duplicate(mem.get("tags", []), existing_tags_per_id)
            if dup:
                print(f"   ⚠️  {mem_id} 与 {dup} 重复率过高，跳过")
                continue

            atomic_write(file_path, content)
            existing_tags_per_id[mem_id] = mem.get("tags", [])
            new_ids.append(mem_id)

            # 增量更新索引
            indexer.add_memory({
                "id": mem_id,
                "layer_id": mem.get("layer", "CC"),
                "dim_id": mem.get("dimension", "patterns"),
                "title": mem.get("title", ""),
                "tier": mem.get("tier", "warm"),
                "tags": mem.get("tags", []),
                "file": str(file_path.relative_to(MEMORY_ROOT)),
            })
            print(f"   ✅ {mem_id}: {mem.get('title', '')}")
    else:
        print(f"[DRY-RUN] 将生成 {len(memories)} 条记忆（未实际写入）：")
        for mem in memories:
            print(f"   · {mem.get('id_prefix', 'MEM-L')}-{mem.get('id_suffix', '?')}: {mem.get('title', '')}")

    # Step 5: 运行 GC
    if new_ids and not dry_run:
        print("♻️  运行 GC...")
        subprocess.run([sys.executable, "scripts/memory_gc.py"], cwd=str(PROJECT_ROOT))

    # 清理断点 + 写审计日志
    cp.complete(trace_id)
    elapsed_ms = int((time.time() - t_start) * 1000)
    logger.log(trace_id, "distill", ep=ep_id, result="ok",
               new_memories=new_ids, elapsed_ms=elapsed_ms,
               token_estimate=len(ep_summary) // 4)

    return new_ids


# ─── CLI ─────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MDP Memory System — 知识蒸馏器 v2.1"
    )
    parser.add_argument("--ep", help="EP 编号（如 EP-108）")
    parser.add_argument("--ep-file", help="EP 文件路径（覆盖自动查找）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不写入文件")
    parser.add_argument("--resume", metavar="TRACE_ID", help="从断点恢复")
    parser.add_argument("--list-incomplete", action="store_true",
                        help="列出所有未完成的蒸馏任务")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.list_incomplete:
        cp = Checkpoint()
        incomplete = cp.list_incomplete()
        if not incomplete:
            print("✅ 无未完成的蒸馏任务")
        else:
            print(f"⏳ 未完成的蒸馏任务（{len(incomplete)} 个）：")
            for tid in incomplete:
                state = cp.load(tid)
                print(f"  · {tid}  EP={state.ep_id if state else '?'}")
        return 0

    if not args.ep:
        print("❌ 请指定 --ep 参数（如 --ep EP-108）")
        return 1

    ep_file = Path(args.ep_file) if args.ep_file else None
    trace_id = new_trace_id()

    print(f"\n{'='*55}")
    print(f"  MMS 知识蒸馏器 v2.1  |  {args.ep}  |  {trace_id}")
    print(f"{'='*55}\n")

    new_ids = run_distillation(
        ep_id=args.ep,
        ep_file=ep_file,
        dry_run=args.dry_run,
        trace_id=trace_id,
        resume_checkpoint=args.resume,
    )

    if new_ids:
        print(f"\n✅ 蒸馏完成：新增 {len(new_ids)} 条记忆")
        for mid in new_ids:
            print(f"   · {mid}")
    elif not args.dry_run:
        print("\nℹ️  本次蒸馏未产生新记忆（可能已存在或模型输出为空）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
