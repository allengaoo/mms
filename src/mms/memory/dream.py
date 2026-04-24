#!/usr/bin/env python3
"""
dream.py — MMS autoDream：自动知识萃取引擎

从三路来源提取知识候选，通过 LLM 生成记忆草稿，形成学习闭环：
  ① git log（EP 相关 commit，自动过滤）
  ② EP 文件 Surprises & Discoveries 节
  ③ EP 文件 Decision Log 节

输出：docs/memory/private/dream/DRAFT-{date}-{n}.md

用法：
    mms dream --ep EP-118                   # 针对单个 EP 萃取
    mms dream --since 7d                    # 近 7 天所有 EP 相关 commit
    mms dream --dry-run                     # 只打印 prompt，不调用 LLM
    mms dream --list                        # 列出所有草稿
    mms dream --promote                     # 交互式审核草稿 → 提升为正式记忆
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent

try:
    import sys as _sys
    _sys.path.insert(0, str(_HERE))
    from mms.utils.mms_config import cfg as _cfg  # type: ignore[import]
except Exception:
    _cfg = None  # type: ignore[assignment]
try:
    from mms.utils._paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE.parent.parent
_MEMORY_ROOT = _ROOT / "docs" / "memory"
_DREAM_DIR = _MEMORY_ROOT / "private" / "dream"
_EP_DIR = _ROOT / "docs" / "execution_plans"

_G = "\033[92m"
_Y = "\033[93m"
_R = "\033[91m"
_C = "\033[96m"
_B = "\033[1m"
_D = "\033[2m"
_X = "\033[0m"


def _ok(msg: str) -> None:
    print(f"  {_G}✅{_X} {msg}")


def _warn(msg: str) -> None:
    print(f"  {_Y}⚠️{_X}  {msg}")


def _err(msg: str) -> None:
    print(f"  {_R}❌{_X} {msg}")


def _info(msg: str) -> None:
    print(f"  {_D}ℹ️  {msg}{_X}")


# ── git 历史读取 ──────────────────────────────────────────────────────────────

def get_git_commits(since: str = "7d", ep_filter: Optional[str] = None) -> List[Dict]:
    """
    读取近 N 天内的 git commits（可按 EP 过滤）。

    Args:
        since: 时间范围，格式 "7d" / "14d" / "30d"
        ep_filter: EP 编号（如 "EP-118"），None 表示所有 commit

    Returns:
        List[{ hash, subject, date, files_changed }]
    """
    days_match = re.match(r"(\d+)d", since)
    days = int(days_match.group(1)) if days_match else 7

    cmd = [
        "git", "log",
        f"--since={days} days ago",
        "--format=%H|||%s|||%ai",
        "--name-only",
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=str(_ROOT),
            # fallback: config.yaml → runner.timeout.dream_git_seconds (default=30)
            timeout=int(getattr(_cfg, "runner_timeout_dream_git", 30)) if _cfg else 30
        )
        if result.returncode != 0:
            return []
    except Exception:
        return []

    commits: List[Dict] = []
    current: Optional[Dict] = None
    for line in result.stdout.splitlines():
        if "|||" in line:
            if current:
                commits.append(current)
            parts = line.split("|||")
            if len(parts) >= 3:
                current = {
                    "hash": parts[0][:8],
                    "subject": parts[1].strip(),
                    "date": parts[2][:10],
                    "files_changed": [],
                }
        elif line.strip() and current:
            current["files_changed"].append(line.strip())

    if current:
        commits.append(current)

    # EP 过滤
    if ep_filter:
        ep_norm = ep_filter.upper()
        ep_lower = ep_norm.lower()
        commits = [
            c for c in commits
            if ep_lower in c["subject"].lower()
            or any(ep_lower in f.lower() for f in c["files_changed"])
        ]

    return commits


# ── EP 章节提取 ───────────────────────────────────────────────────────────────

def get_ep_sections(ep_id: str) -> Dict[str, str]:
    """
    从 EP 文件提取关键章节：Surprises & Discoveries、Decision Log、Outcomes。

    Returns:
        { "surprises": str, "decisions": str, "outcomes": str }
    """
    ep_norm = ep_id.upper()
    ep_files = list(_EP_DIR.glob(f"*{ep_norm}*.md"))
    if not ep_files:
        all_eps = list(_EP_DIR.glob("*.md"))
        ep_files = [f for f in all_eps if ep_norm.lower() in f.name.lower()]

    if not ep_files:
        return {"surprises": "", "decisions": "", "outcomes": ""}

    content = ep_files[0].read_text(encoding="utf-8")

    def _extract_section(patterns: List[str]) -> str:
        for pat in patterns:
            m = re.search(pat, content, re.DOTALL | re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ""

    return {
        "surprises": _extract_section([
            r"##\s*Surprises\s*[&＆]\s*Discoveries[^\n]*\n(.*?)(?=\n##|\Z)",
            r"##\s*意外发现[^\n]*\n(.*?)(?=\n##|\Z)",
        ]),
        "decisions": _extract_section([
            r"##\s*Decision\s*Log[^\n]*\n(.*?)(?=\n##|\Z)",
            r"##\s*决策日志[^\n]*\n(.*?)(?=\n##|\Z)",
            r"##\s*架构决策[^\n]*\n(.*?)(?=\n##|\Z)",
        ]),
        "outcomes": _extract_section([
            r"##\s*Outcomes\s*(?:[&＆]|and)\s*Retrospective[^\n]*\n(.*?)(?=\n##|\Z)",
            r"##\s*复盘[^\n]*\n(.*?)(?=\n##|\Z)",
        ]),
    }


# ── LLM Prompt ───────────────────────────────────────────────────────────────

_DREAM_PROMPT = """\
你是 MDP 平台的知识蒸馏引擎。请从以下工程日志中提取值得长期保存的工程经验，生成 1-3 条记忆草稿。

# 输入信息

## EP 编号
{ep_id}

## Git Commits（近期实际提交记录）
{commits_text}

## EP 意外发现（Surprises & Discoveries）
{surprises}

## EP 决策日志（Decision Log）
{decisions}

## EP 复盘（Outcomes & Retrospective）
{outcomes}

# 输出格式

每条候选记忆使用以下格式，用 `---MEMORY-DRAFT---` 分隔：

---MEMORY-DRAFT---
title: <一句话，说明 WHAT（20字内）>
type: <lesson | pattern | anti-pattern | decision>
layer: <L1_platform | L2_infrastructure | L3_domain | L4_application | L5_interface | cross_cutting>
dimension: <D1 | D2 | D3 | D4 | D5 | D6 | D7 | D8 | D9 | D10>
tags: [<tag1>, <tag2>, <tag3>]
description: <30-60字语义摘要，帮助 LLM 判断是否相关>

## WHERE（适用场景）
<在什么情况下会用到这条记忆>

## HOW（核心实现/注意事项）
<具体做法或代码模式，1-3 个要点>

## WHEN（触发条件/危险信号）
<什么信号表明需要用这条记忆>
---MEMORY-DRAFT---

# 筛选标准（重要）
✅ 应该保存：发现了新的反模式、做了不显而易见的设计决策、踩了可重复的坑
❌ 不应该保存：只是按已有模式实现了常规功能、Bug 修复根因已在记忆库、重复已知约束
❌ 不允许：生成空洞的通用建议（如"要写测试"等无具体指导的废话）

如果没有值得保存的新知识，只输出：NO_NEW_KNOWLEDGE
"""


def _call_llm(prompt: str) -> str:
    """调用 LLM 生成记忆草稿"""
    sys.path.insert(0, str(_HERE))
    try:
        from mms.providers.factory import get_provider_for_task  # type: ignore[import]
    except ImportError:
        try:
            from mms.providers.factory import get_provider_for_task  # type: ignore[import]
        except ImportError:
            return ""

    try:
        provider = get_provider_for_task("distillation")
        if provider is None:
            return ""
        # fallback: config.yaml → runner.max_tokens.distillation (default=3000)
        max_tok = int(getattr(_cfg, "runner_max_tokens_distillation", 3000)) if _cfg else 3000
        return provider.complete(prompt, max_tokens=max_tok)
    except Exception as exc:
        _warn(f"LLM 调用失败：{exc}")
        return ""


# ── 草稿解析 ─────────────────────────────────────────────────────────────────

def parse_dream_response(raw: str) -> List[Dict]:
    """解析 LLM 返回内容，提取结构化草稿"""
    if not raw or "NO_NEW_KNOWLEDGE" in raw:
        return []

    drafts = []
    blocks = re.split(r"---MEMORY-DRAFT---", raw)
    for block in blocks:
        block = block.strip()
        if not block:
            continue

        def _field(pat: str) -> str:
            m = re.search(pat, block, re.MULTILINE)
            return m.group(1).strip() if m else ""

        title = _field(r"^title:\s*(.+)$")
        if not title:
            continue

        tags_raw = _field(r"^tags:\s*\[(.+)\]")
        tags = [t.strip().strip("\"'") for t in tags_raw.split(",") if t.strip()]

        where_m = re.search(r"##\s*WHERE[^\n]*\n(.*?)(?=\n##|\Z)", block, re.DOTALL)
        how_m = re.search(r"##\s*HOW[^\n]*\n(.*?)(?=\n##|\Z)", block, re.DOTALL)
        when_m = re.search(r"##\s*WHEN[^\n]*\n(.*?)(?=\n##|\Z)", block, re.DOTALL)

        drafts.append({
            "title": title,
            "type": _field(r"^type:\s*(.+)$") or "lesson",
            "layer": _field(r"^layer:\s*(.+)$") or "cross_cutting",
            "dimension": _field(r"^dimension:\s*(.+)$") or "D2",
            "tags": tags,
            "description": _field(r"^description:\s*(.+)$"),
            "where": (where_m.group(1).strip() if where_m else ""),
            "how": (how_m.group(1).strip() if how_m else ""),
            "when": (when_m.group(1).strip() if when_m else ""),
        })

    return drafts


# ── 草稿 I/O ─────────────────────────────────────────────────────────────────

def _next_draft_path(ep_id: str) -> Path:
    """计算下一个草稿文件路径（自动递增序号）"""
    _DREAM_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    prefix = f"DRAFT-{today}-"
    existing = sorted(_DREAM_DIR.glob(f"{prefix}*.md"))
    n = len(existing) + 1
    return _DREAM_DIR / f"{prefix}{n:02d}.md"


# ── Auto-Link：自动建边（Phase 3, MMS v4.0）─────────────────────────────────

_FILE_PATH_RE = re.compile(
    r"(?:^|\s|[`'\"])("
    r"[\w./\-]+"
    r"\.(?:py|ts|tsx|js|java|go|yaml|yml|json|toml|md)"
    r")(?:\s|[`'\"]|$)",
    re.MULTILINE,
)


def _extract_file_paths(content: str) -> List[str]:
    """从文本中提取代码/配置文件路径（零 LLM，正则匹配）。"""
    matches = _FILE_PATH_RE.findall(content)
    result = []
    seen: set = set()
    for m in matches:
        m = m.strip("\"'`")
        if m and m not in seen and len(m) > 4:
            seen.add(m)
            result.append(m)
    return result


def _match_domain_concepts(content: str, tags: List[str]) -> List[str]:
    """
    从 _system/routing/layers.yaml 的 keywords 字段匹配领域概念 ID。
    零 LLM，基于关键词规则。
    """
    try:
        import yaml  # type: ignore[import]
        routing_dir = _MEMORY_ROOT / "_system" / "routing"
        layers_file = routing_dir / "layers.yaml"
        if not layers_file.exists():
            return []
        data = yaml.safe_load(layers_file.read_text(encoding="utf-8")) or {}
        layers = data.get("layers", {})

        content_lower = content.lower()
        tags_lower = [t.lower() for t in tags]
        matched: List[str] = []

        for layer_id, layer_data in layers.items():
            if not isinstance(layer_data, dict):
                continue
            keywords = layer_data.get("keywords", []) or []
            for kw in keywords:
                kw_lower = kw.lower()
                if kw_lower in content_lower or kw_lower in tags_lower:
                    concept_id = layer_id.lower().replace("_", "-")
                    if concept_id not in matched:
                        matched.append(concept_id)
                    break
        return matched
    except Exception:  # noqa: BLE001
        return []


def _find_tag_overlapping_memories(tags: List[str]) -> List[str]:
    """
    轻量 impacts 边候选：找到与当前记忆 tags 高度重叠的其他 hot 记忆。
    返回记忆 ID 列表。只在 runner_enable_auto_impacts=True 时调用。
    """
    try:
        from mms.memory.graph_resolver import MemoryGraph
        graph = MemoryGraph()
        all_hot = graph.all_hot()
        tags_set = set(t.lower() for t in tags)
        overlapping = []
        for node in all_hot:
            node_tags = set(t.lower() for t in node.tags)
            intersection = tags_set & node_tags
            if len(intersection) >= 2 and len(intersection) / max(len(tags_set), 1) >= 0.5:
                overlapping.append(node.id)
        return overlapping[:5]  # 最多 5 个，避免过度建边
    except Exception:  # noqa: BLE001
        return []


def _auto_link(content: str, fm: dict) -> dict:
    """
    三步自动建边（纯函数：不修改传入 fm，返回需要合并的字段 dict）。

    Step 1: cites_files  — 正则提取文件路径（零 LLM，< 1ms）
    Step 2: about_concepts — 从 layers.yaml keywords 匹配领域概念（零 LLM）
    Step 3: impacts       — tag 重叠检测（可选，受 enable_auto_impacts 控制）

    参数：
        content : 记忆文件内容（包含正文）
        fm      : 当前 front-matter dict（只读）

    返回：
        需要合并回 front-matter 的字段 dict（调用方负责写入）
    """
    updates: dict = {}

    # Step 1: cites_files（零 LLM，正则）
    found_files = _extract_file_paths(content)
    if found_files:
        existing = fm.get("cites_files", []) or []
        if isinstance(existing, str):
            existing = [existing]
        merged = sorted(set(list(existing) + found_files))
        if merged != list(existing):
            updates["cites_files"] = merged

    # Step 2: about_concepts（零 LLM，keywords 匹配）
    concepts = _match_domain_concepts(content, fm.get("tags", []) or [])
    if concepts:
        existing_concepts = fm.get("about_concepts", []) or []
        if isinstance(existing_concepts, str):
            existing_concepts = [existing_concepts]
        merged_concepts = sorted(set(list(existing_concepts) + concepts))
        if merged_concepts != list(existing_concepts):
            updates["about_concepts"] = merged_concepts

    # Step 3: impacts（可选，tag 重叠，受 feature flag 控制）
    try:
        enable_auto_impacts = False
        if _cfg:
            enable_auto_impacts = getattr(_cfg, "runner_enable_auto_impacts", False)
    except Exception:  # noqa: BLE001
        enable_auto_impacts = False

    if enable_auto_impacts and fm.get("tier") == "hot":
        overlaps = _find_tag_overlapping_memories(fm.get("tags", []) or [])
        if overlaps:
            existing_impacts = fm.get("impacts", []) or []
            if isinstance(existing_impacts, str):
                existing_impacts = [existing_impacts]
            merged_impacts = sorted(set(list(existing_impacts) + overlaps))
            if merged_impacts != list(existing_impacts):
                updates["impacts"] = merged_impacts

    return updates


def _apply_auto_link_to_file(path: Path) -> None:
    """
    读取已存在的记忆文件，运行 _auto_link，将更新写回 front-matter。
    写回前经过 SanitizationGate。
    """
    try:
        content = path.read_text(encoding="utf-8")
        # 简单提取 front-matter dict（复用 graph_resolver 的解析逻辑）
        from mms.memory.graph_resolver import _parse_frontmatter
        fm = _parse_frontmatter(content)
        updates = _auto_link(content, fm)

        if not updates:
            return  # 无需更新

        # 将更新注入 front-matter（追加新字段，不修改已有字段）
        def _yaml_list(name: str, items: list) -> str:
            lines = [f"{name}:"]
            for item in items:
                lines.append(f"  - {item}")
            return "\n".join(lines)

        extra_lines = []
        for field_name, value in updates.items():
            if isinstance(value, list):
                extra_lines.append(_yaml_list(field_name, value))
            else:
                extra_lines.append(f"{field_name}: {value}")

        # 在 closing --- 之前插入新字段
        new_content = re.sub(
            r"(\n---\n)",
            "\n" + "\n".join(extra_lines) + r"\1",
            content,
            count=1,
        )

        try:
            from mms.core.sanitize import sanitize_or_raise
            new_content = sanitize_or_raise(new_content, path_hint=str(path))
        except ImportError:
            pass
        path.write_text(new_content, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def save_draft(ep_id: str, draft: Dict) -> Path:
    """将单条草稿保存为标准 MEM 格式的 Markdown 文件"""
    path = _next_draft_path(ep_id)
    today = datetime.now().strftime("%Y-%m-%d")

    layer = draft.get("layer", "cross_cutting")
    tags_yaml = "[" + ", ".join(draft.get("tags", [])) + "]"

    content = f"""---
id: {path.stem}
status: draft
source_ep: {ep_id.upper()}
layer: {layer}
dimension: {draft.get("dimension", "D2")}
type: {draft.get("type", "lesson")}
tier: warm
tags: {tags_yaml}
description: "{draft.get("description", "")}"
created_at: "{today}"
last_accessed: "{today}"
access_count: 0
---
# {draft["title"]}

## WHERE（适用场景）
{draft.get("where", "待补充")}

## HOW（核心实现）
{draft.get("how", "待补充")}

## WHEN（触发条件 / 危险信号）
{draft.get("when", "待补充")}
"""
    try:
        from mms.core.sanitize import sanitize_or_raise
        content = sanitize_or_raise(content, path_hint=str(path))
    except ImportError:
        pass
    path.write_text(content, encoding="utf-8")

    # Auto-Link：写入后自动建立图边（cites_files, about_concepts）
    _apply_auto_link_to_file(path)

    return path


# ── promote 流程 ──────────────────────────────────────────────────────────────

def _get_next_mem_id() -> str:
    """从 MEMORY_INDEX.json 推算下一个可用的 MEM-L-XXX ID"""
    index_file = _MEMORY_ROOT / "MEMORY_INDEX.json"
    try:
        idx = json.loads(index_file.read_text(encoding="utf-8"))
        nodes = idx.get("nodes", [])
        nums = [
            int(re.search(r"\d+", n["id"]).group())
            for n in nodes
            if re.match(r"MEM-L-\d+", n.get("id", ""))
            and re.search(r"\d+", n.get("id", ""))
        ]
        return f"MEM-L-{(max(nums) + 1) if nums else 1:03d}"
    except Exception:
        return "MEM-L-XXX"


def _layer_to_dir(layer: str) -> Path:
    """将 layer 字符串映射到目标目录"""
    mapping = {
        "L1": _MEMORY_ROOT / "shared" / "L1_platform",
        "L2": _MEMORY_ROOT / "shared" / "L2_infrastructure",
        "L3": _MEMORY_ROOT / "shared" / "L3_domain",
        "L4": _MEMORY_ROOT / "shared" / "L4_application",
        "L5": _MEMORY_ROOT / "shared" / "L5_interface",
    }
    for prefix, path in mapping.items():
        if prefix in layer:
            return path
    return _MEMORY_ROOT / "shared" / "cross_cutting" / "decisions"


def promote_draft(draft_path: Path) -> Optional[Path]:
    """将单条草稿提升为正式记忆（交互式）"""
    content = draft_path.read_text(encoding="utf-8")
    print(f"\n{_B}─── 草稿预览 ───────────────────────────────────────────{_X}")
    preview = content[:700]
    print(preview + ("..." if len(content) > 700 else ""))
    print(f"{_B}────────────────────────────────────────────────────────{_X}")

    layer_m = re.search(r"^layer:\s*(.+)$", content, re.MULTILINE)
    layer = layer_m.group(1).strip() if layer_m else "cross_cutting"
    target_dir = _layer_to_dir(layer)
    new_id = _get_next_mem_id()

    print(f"\n  建议 ID：{_C}{new_id}{_X}")
    print(f"  目标目录：{target_dir.relative_to(_ROOT)}")

    try:
        choice = input(f"\n  [{_G}p{_X}]提升 / [{_Y}e{_X}]修改 ID / [{_R}s{_X}]跳过: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        return None

    if choice == "s":
        return None
    if choice == "e":
        try:
            new_id = input(f"  输入新 ID（当前 {new_id}）: ").strip() or new_id
        except (KeyboardInterrupt, EOFError):
            return None

    # 替换 id 和 status 字段
    new_content = re.sub(r"^id:\s*.*$", f"id: {new_id}", content, flags=re.MULTILINE)
    new_content = re.sub(r"^status:\s*draft.*\n?", "", new_content, flags=re.MULTILINE)

    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{new_id}.md"
    try:
        from mms.core.sanitize import sanitize_or_raise
        new_content = sanitize_or_raise(new_content, path_hint=str(target_path))
    except ImportError:
        pass
    target_path.write_text(new_content, encoding="utf-8")
    draft_path.unlink()

    # Auto-Link：promote 后自动建立图边（cites_files, about_concepts）
    _apply_auto_link_to_file(target_path)

    _ok(f"已提升：{target_path.relative_to(_ROOT)}")
    print(f"  {_D}下一步：mms validate + mms gc 更新索引{_X}")
    return target_path


# ── 主函数 ────────────────────────────────────────────────────────────────────

def run_dream(
    ep_id: Optional[str] = None,
    since: str = "7d",
    promote: bool = False,
    list_drafts: bool = False,
    dry_run: bool = False,
) -> int:
    """
    autoDream 主入口。

    Returns: 0=success, 1=error
    """
    _DREAM_DIR.mkdir(parents=True, exist_ok=True)

    # ── 列出草稿 ──────────────────────────────────────────────────────────────
    if list_drafts:
        drafts = sorted(_DREAM_DIR.glob("DRAFT-*.md"))
        if not drafts:
            try:
                path_display = _DREAM_DIR.relative_to(_ROOT)
            except ValueError:
                path_display = _DREAM_DIR
            print(f"  {_D}暂无草稿（{path_display}）{_X}")
            return 0
        print(f"\n{_B}记忆草稿列表（{len(drafts)} 条）{_X}")
        print("─" * 60)
        for d in drafts:
            lines = d.read_text(encoding="utf-8").splitlines()
            title_line = next((l for l in lines if l.startswith("# ")), d.name)
            ep_m = re.search(r"^source_ep:\s*(.+)$", "\n".join(lines), re.MULTILINE)
            ep_tag = ep_m.group(1).strip() if ep_m else ""
            print(f"  {_C}{d.name}{_X}  [{ep_tag}]  {title_line[2:55]}")
        print("─" * 60)
        print(f"  运行 {_C}mms dream --promote{_X} 审核并提升草稿")
        return 0

    # ── promote 模式 ──────────────────────────────────────────────────────────
    if promote:
        drafts = sorted(_DREAM_DIR.glob("DRAFT-*.md"))
        if not drafts:
            _warn("暂无待审核草稿，先运行 mms dream --ep EP-NNN 生成草稿")
            return 0
        print(f"\n{_B}交互式草稿审核（{len(drafts)} 条待审核）{_X}\n")
        promoted = 0
        for draft_path in drafts:
            result = promote_draft(draft_path)
            if result:
                promoted += 1
        print(f"\n{_G}完成：已提升 {promoted}/{len(drafts)} 条草稿{_X}")
        return 0

    # ── 萃取模式 ──────────────────────────────────────────────────────────────
    print(f"\n{_B}MMS autoDream · 知识自动萃取{_X}")
    print("─" * 60)

    # Step 1: 收集输入
    print(f"\n{_C}▶ Step 1 · 收集输入源{_X}")
    commits = get_git_commits(since=since, ep_filter=ep_id)
    _info(f"Git commits：{len(commits)} 条")

    ep_sections: Dict[str, str] = {"surprises": "", "decisions": "", "outcomes": ""}
    if ep_id:
        ep_sections = get_ep_sections(ep_id)
        _info(f"EP Surprises：{'有内容' if ep_sections['surprises'] else '（空）'}")
        _info(f"EP Decisions：{'有内容' if ep_sections['decisions'] else '（空）'}")

    if not commits and not any(ep_sections.values()):
        _warn("未找到有效输入（无相关 commit 且 EP 章节为空）")
        _info("提示：--since 14d 扩大范围，或检查 EP 文件是否含 Surprises & Discoveries 节")
        return 0

    # Step 2: 构造 prompt
    print(f"\n{_C}▶ Step 2 · 构造 LLM prompt{_X}")
    commits_text = "\n".join(
        f"- [{c['hash']}] {c['date']} {c['subject']}"
        + (f"\n  {', '.join(c['files_changed'][:4])}" if c["files_changed"] else "")
        for c in commits[:20]
    ) or "（无相关 commit）"

    prompt = _DREAM_PROMPT.format(
        ep_id=ep_id.upper() if ep_id else f"（时间范围：{since}）",
        commits_text=commits_text,
        surprises=ep_sections.get("surprises") or "（无）",
        decisions=ep_sections.get("decisions") or "（无）",
        outcomes=ep_sections.get("outcomes") or "（无）",
    )
    _info(f"Prompt 估算约 {len(prompt) // 4} tokens")

    if dry_run:
        print(f"\n{_Y}[dry-run] Prompt 预览（前 600 字符）:{_X}")
        print(prompt[:600] + "...")
        return 0

    # Step 3: 调用 LLM
    print(f"\n{_C}▶ Step 3 · 调用 LLM{_X}")
    _info("正在调用 qwen3-32b...")
    raw = _call_llm(prompt)
    if not raw:
        _err("LLM 调用失败或返回为空")
        _info("检查 DASHSCOPE_API_KEY，或运行 mms status 查看 Provider 状态")
        return 1

    # Step 4: 解析 & 保存
    print(f"\n{_C}▶ Step 4 · 解析并保存草稿{_X}")
    drafts_data = parse_dream_response(raw)

    if not drafts_data:
        _ok("LLM 判断：本次无值得保存的新知识（NO_NEW_KNOWLEDGE）")
        return 0

    saved: List[Path] = []
    for d in drafts_data:
        path = save_draft(ep_id or "UNKNOWN", d)
        _ok(f"草稿已保存：{path.relative_to(_ROOT)}")
        print(f"    {_D}{d['title']}{_X}")
        saved.append(path)

    print(f"\n{'─' * 60}")
    print(f"  {_G}{_B}已生成 {len(saved)} 条记忆草稿{_X}")
    print(f"\n  下一步：")
    print(f"    {_C}mms dream --list{_X}       查看草稿列表")
    print(f"    {_C}mms dream --promote{_X}    审核并提升为正式记忆\n")
    return 0
