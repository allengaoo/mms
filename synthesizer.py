#!/usr/bin/env python3
"""
MMS Synthesizer — LLM 意图合成器（v2.2，三级检索漏斗）

将用户的简短任务描述，经过三级检索漏斗提取可信上下文，
调用 qwen3-32b 生成结构化的 Cursor EP 起手提示词。

三级检索漏斗（无向量、无全文检索引擎）：
  第一级  历史任务相似匹配（Jaccard + 时间衰减）
          → 命中时用历史验证路径约束 LLM，大幅减少文件路径幻觉
  第二级  记忆关键词匹配（injector.py 增强版）
          → 从记忆库检索相关技术约束和经验教训
  第三级  极简知识索引兜底（task_quickmap.yaml 静态映射）
          → 始终有输出，任何任务类型均可获得最小必读上下文

用法：
    python scripts/mms/cli.py synthesize "为对象类型新增批量导出 API" --template ep-backend-api
    python scripts/mms/cli.py synthesize "修复 Kafka 消费者丢消息" --template ep-debug --extra "只影响 ingestion worker"
    python scripts/mms/cli.py synthesize "新增前端画布组件" --interactive
    python scripts/mms/cli.py synthesize "修复登录 401" --template ep-debug --refresh-maps
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import List, Optional

_HERE = Path(__file__).resolve().parent
try:
    from _paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE.parent.parent
_MEMORY_ROOT = _ROOT / "docs" / "memory"
_TEMPLATES_DIR = _MEMORY_ROOT / "templates"
_SYSTEM_DIR = _MEMORY_ROOT / "_system"
_CODEMAP_PATH = _SYSTEM_DIR / "codemap.md"
_FUNCMAP_PATH = _SYSTEM_DIR / "funcmap.md"
_QUICKMAP_PATH = _SYSTEM_DIR / "task_quickmap.yaml"
_E2E_TRACE_PATH = _ROOT / "docs" / "architecture" / "e2e_traceability.md"

try:
    import sys as _sys
    _sys.path.insert(0, str(_HERE))
    from mms_config import cfg as _mms_cfg  # type: ignore[import]
except Exception:
    _mms_cfg = None  # type: ignore[assignment]

# 以下默认值可被 config.yaml 的 synthesize 节覆盖
_CODEMAP_MAX_CHARS = 3000   # codemap 章节最大字符数
_FUNCMAP_MAX_LINES = 40     # funcmap 关键词匹配最大行数
_E2E_CONTEXT_LINES = 12     # e2e 降级扫描时的上下文行数


def _load_synthesize_config() -> dict:
    """
    从 config.yaml 读取 synthesize 节配置，返回扁平化字典。
    读取失败时返回空 dict，所有参数回退到调用方的默认值。
    """
    config_path = _SYSTEM_DIR / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        import yaml  # type: ignore[import]
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        return raw.get("synthesize", {})
    except Exception:  # noqa: BLE001
        # yaml 不可用（未安装）或解析失败时静默降级
        return {}

# ── 已支持的 EP 类型模板 ─────────────────────────────────────────────────────
SUPPORTED_TEMPLATES = {
    "ep-backend-api":    "新增后端 API / Service / Repository",
    "ep-frontend":       "新增前端页面 / 组件 / Zustand Store",
    "ep-ontology":       "本体层操作（对象/链接/Action/Function）",
    "ep-data-pipeline":  "数据管道（Connector / SyncJob / Worker）",
    "ep-debug":          "Bug 诊断 / 热修复 / 性能问题",
    "ep-devops":         "运维 / 部署 / 本地调试环境 / K8s 配置",
    "ep-others":         "跨层重构 / 安全加固 / 性能优化 / 测试补全 / 文档整理 / MMS 系统自身优化",
}

# ── Synthesis Prompt 模板 ────────────────────────────────────────────────────
_SYNTHESIS_SYSTEM = """你是 MDP 平台（企业级本体元数据平台）的 AI 架构助手。
你的任务是将用户的简短任务描述，结合已检索的项目记忆和 EP 类型模板，
生成一段高质量的「Cursor 起手提示词」，帮助 Cursor AI 快速理解上下文并生成准确的执行计划。

【文件路径约束 — 极重要，违反则提示词无效】
本次已通过「架构意图分类 + 确定性路径解析」自动定位到真实文件路径（见「架构图谱解析」节）。
  ✅ 优先使用「架构图谱解析」节中的已验证路径，这些路径经过磁盘验证，100% 真实存在。
  ✅ 如需补充文件，从「项目目录快照（codemap）」或「函数签名索引」中选取。
  ❌ 禁止凭经验推理文件路径（常见幻觉：src/services/...、pages/layout/index.tsx、menuStore.ts 等）。

本项目架构层对应的路径规范（仅作参考，以架构图谱解析结果为准）：
  - 前端布局：frontend/src/layouts/<Name>Layout.tsx
  - 前端配置：frontend/src/config/<name>.ts（navigation.ts 是菜单配置）
  - 前端页面：frontend/src/pages/<module>/index.tsx
  - 前端服务：frontend/src/services/<name>.ts
  - 后端路由：backend/app/api/v1/endpoints/<name>.py
  - 后端服务：backend/app/services/control/<name>_service.py
  - 后端核心：backend/app/core/<module>.py

输出要求：
- 使用 Markdown 格式
- 严格按照"输出结构"生成，不要添加额外说明
- 约束来自记忆系统和 codemap，不要捏造不存在的约束或路径
- 语言：中文"""

_SYNTHESIS_USER = """## 用户任务描述
{task_description}

---

## 【最高优先级】架构图谱解析结果（确定性，零幻觉）
{arch_graph_context}

## [第一级] 历史相似任务命中（已验证的真实文件路径）
{history_context}

## [第三级] 极简知识索引（任务类型必读文件 + 核心记忆）
{quickmap_context}

## 项目目录快照（codemap — 文件路径的补充来源）
{codemap_context}

## 相关函数签名索引（funcmap — 已有实现参考）
{funcmap_context}

## 全链路追踪切片（e2e_traceability — 相关模块的端到端路径）
{e2e_context}

## [第二级] 相关记忆上下文（已从记忆系统检索）
{memory_context}

## EP 类型参考模板
{template_content}

## 用户自定义要求（可选）
{custom_requirements}

---
检索漏斗命中级别：{funnel_level}（L1=历史命中 / L2=记忆命中 / L3=极简索引兜底）
架构图谱解析：layer={arch_layer}, operation={arch_operation}, confidence={arch_confidence}

请按以下结构生成「Cursor EP 起手提示词」。

【文件路径优先级规则（严格执行）】
1. ✅ 「架构图谱解析」中的文件路径经过磁盘验证，是第一优先级，必须直接采用。
2. ✅ 若「历史命中」非空，其 hit_files 已被真实执行过，作为第二优先级补充。
3. ✅ 「极简索引」的 must_read_files 是任务类型最小骨架，全部包含。
4. ❌ 禁止凭推理/经验创造任何未出现在以上来源中的文件路径。

### 1. 任务背景与目标
（1-3 句话说明业务价值和技术目标）

### 2. 涉及层次与模块
（列出预计影响的代码层次和文件范围，路径必须来自「架构图谱解析」或历史命中，用 bullet list）

### 3. 关键约束提醒（来自记忆系统，≤5 条）
（最重要的架构约束、安全规则、反模式警告，格式：🔥 [来源ID] 内容）

### 4. 建议加载文件（Cursor @mention 列表）
（格式：`@真实路径/文件名` — 说明用途；路径必须来自架构图谱解析或历史命中）

### 5. EP 类型声明
（从以下选一个：后端API / 前端 / 本体 / 数据管道 / 运维 / 调试）

### 6. 起手指令（供 Cursor 执行）
（一段完整的指令，告诉 Cursor 接下来要做什么；所有文件引用必须使用真实验证路径）

---

【重要：以下两节是 EP 文件的必要结构，Cursor 生成执行计划时必须包含，否则 mms precheck 无法建立基线】

### 7. Scope 表格（EP 文件必须包含此节）

请要求 Cursor 在 EP 文件中生成如下格式的 `## Scope` 节（**节名必须是 `## Scope`**）：

```markdown
## Scope

| Unit | 操作描述 | 涉及文件 |
|------|---------|---------|
| U1   | （描述操作） | `路径/文件.py` |
| U2   | （描述操作） | `路径/文件.py`, `路径/文件2.py` |
```

- 每行对应一个原子操作单元（Unit）
- 「涉及文件」必须使用反引号包裹的真实路径（来自架构图谱解析）
- 运维/调试类任务若无代码变更文件，可填 `（脚本/命令，无代码变更）`

### 8. Testing Plan（EP 文件必须包含此节）

请要求 Cursor 在 EP 文件中生成如下格式的 `## Testing Plan` 节（**节名必须是 `## Testing Plan`**）：

```markdown
## Testing Plan

- `backend/tests/unit/services/test_xxx.py` — 验证 xxx
- `backend/tests/integration/test_xxx.py` — 端到端验证
```

- 运维/调试类任务若无新增测试，可填：
  ```markdown
  ## Testing Plan
  （本 EP 为运维/调试类，无新增测试文件；验收通过手动验证清单完成）
  ```
- 但节标题 `## Testing Plan` **必须存在**，否则 mms precheck 将报告 ⚠️ 警告
"""


def synthesize(
    task_description: str,
    template_name: Optional[str] = None,
    extra_requirements: Optional[str] = None,
    top_k: int = 5,
    refresh_maps: bool = False,
    author: Optional[str] = None,
) -> str:
    """
    核心合成函数（v3.0，架构图谱 + 三级检索漏斗）。

    新增：架构意图分类 + 确定性路径解析（IntentClassifier + ArchResolver + MemoryGraph）
    保留：历史任务匹配（L1）+ 记忆关键词匹配（L2）+ 极简索引兜底（L3）

    参数：
        task_description:   用户的自然语言任务描述
        template_name:      EP 类型模板名（如 "ep-backend-api"）
        extra_requirements: 用户自定义要求（追加到模板末尾）
        top_k:              第二级记忆检索数量
        refresh_maps:       True 时在合成前自动刷新 codemap + funcmap 快照
        author:             任务提交者标识（用于个人历史优先检索，可选）

    返回：
        结构化的 Cursor 起手提示词字符串
    """
    sys.path.insert(0, str(_HERE.parent))
    sys.path.insert(0, str(_HERE))

    cfg = _load_synthesize_config()

    # ── 0. 可选：刷新代码库快照 ────────────────────────────────────────────
    if refresh_maps:
        _refresh_maps()

    # ── A. 架构意图分类 + 确定性路径解析（v3.0 新增）─────────────────────
    # 这是消除"路径幻觉"的核心机制：
    # 先本地规则匹配（intent_map.yaml），置信度≥0.8 时跳过第1轮 LLM；
    # 再通过 ArchResolver 把层→真实文件路径（磁盘验证，零幻觉）；
    # 最后通过 MemoryGraph 做图遍历，补充与这些文件相关的记忆节点。
    arch_graph_context = ""
    arch_layer = "unknown"
    arch_operation = "unknown"
    arch_confidence = 0.0
    arch_resolved_files: List[str] = []

    try:
        try:
            from mms.intent_classifier import IntentClassifier
            from mms.arch_resolver import ArchResolver
            from mms.graph_resolver import MemoryGraph
        except ImportError:
            from intent_classifier import IntentClassifier  # type: ignore[no-redef]
            from arch_resolver import ArchResolver           # type: ignore[no-redef]
            from graph_resolver import MemoryGraph           # type: ignore[no-redef]

        classifier = IntentClassifier()
        intent = classifier.classify(task_description, use_llm_fallback=False)

        arch_layer = intent.layer
        arch_operation = intent.operation
        arch_confidence = intent.confidence

        # 路径解析（确定性）
        resolver = ArchResolver()
        arch_resolved_files = resolver.resolve_from_intent(intent)

        # 图遍历：通过文件 + 意图层的 hot_memories 找到关联记忆
        try:
            import yaml  # type: ignore[import]
            layers_path = _HERE.parent.parent / "docs" / "memory" / "ontology" / "arch_schema" / "layers.yaml"
            layers_data = yaml.safe_load(layers_path.read_text(encoding="utf-8")) or {} if layers_path.exists() else {}
            layer_hot_mems: List[str] = layers_data.get("layers", {}).get(arch_layer, {}).get("hot_memories", [])
        except Exception:  # noqa: BLE001
            layer_hot_mems = []

        graph = MemoryGraph()
        graph_context_str = graph.build_context_for_task(
            files=arch_resolved_files,
            seed_memories=layer_hot_mems,
            depth=1,
            max_nodes=6,
        )

        # 格式化架构图谱节
        lines = [
            f"**意图分类**：层={arch_layer} | 操作={arch_operation} | 置信度={arch_confidence:.2f}"
            + ("（本地命中，已跳过第1轮LLM）" if intent.skip_llm_round1 else ""),
            "",
            "**已验证的真实文件路径**（来自磁盘验证，直接使用，禁止修改）：",
        ]
        for f in arch_resolved_files:
            lines.append(f"- `{f}`")
        if graph_context_str and "无直接关联" not in graph_context_str:
            lines.append("")
            lines.append(graph_context_str)

        arch_graph_context = "\n".join(lines)

        skip_tag = "✅跳过LLM" if intent.skip_llm_round1 else "⚡调用LLM"
        print(
            f"  🗺 [架构图谱] layer={arch_layer} op={arch_operation} "
            f"conf={arch_confidence:.2f} {skip_tag} | 文件: {len(arch_resolved_files)} 个",
            flush=True,
        )

    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠ [架构图谱] 解析异常（降级，不影响结果）：{exc}", flush=True)
        arch_graph_context = "（架构图谱解析失败，回退到 codemap 模式）"

    # ── 三级检索漏斗（保留 v2.2 逻辑）─────────────────────────────────────
    history_section = ""
    history_hit_files: List[str] = []
    history_hit_memories: List[str] = []
    funnel_level = "L3"

    # ── 第一级：历史任务相似匹配 ────────────────────────────────────────────
    history_cfg = cfg.get("history", {})
    if history_cfg.get("enabled", True):
        try:
            try:
                from mms.task_matcher import TaskMatcher
            except ImportError:
                from task_matcher import TaskMatcher  # type: ignore[no-redef]

            matcher = TaskMatcher(
                history_top_x=history_cfg.get("history_top_x", 10),
                shared_top_y=history_cfg.get("shared_top_y", 20),
                similarity_threshold=history_cfg.get("similarity_threshold", 0.30),
                recent_days=history_cfg.get("time_decay", {}).get("recent_days", 7),
                medium_days=history_cfg.get("time_decay", {}).get("medium_days", 30),
                medium_weight=history_cfg.get("time_decay", {}).get("medium_weight", 0.7),
                old_weight=history_cfg.get("time_decay", {}).get("old_weight", 0.4),
                max_history_records=history_cfg.get("max_history_records", 500),
            )
            hit = matcher.find_similar(task_description, template_name, author)
            if hit:
                funnel_level = "L1"
                max_files = cfg.get("on_history_hit", {}).get("max_files_from_history", 5)
                history_hit_files = hit.record.hit_files[:max_files]
                history_hit_memories = hit.record.hit_memories
                history_section = _build_history_hit_section(hit)
                print(
                    f"  ✦ [第一级] 历史命中！相似度={hit.similarity:.2f}"
                    f"  任务：{hit.record.task[:40]}...",
                    flush=True,
                )
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠ [第一级] 历史检索异常（降级）：{exc}", flush=True)

    # ── 第二级：记忆关键词匹配（始终执行，补充第一级） ─────────────────────
    memory_cfg = cfg.get("memory_search", {})
    effective_top_k = memory_cfg.get("top_k", top_k)
    effective_compress = memory_cfg.get("compress", True)
    memory_context = _inject_memories(task_description, effective_top_k, effective_compress)
    if funnel_level == "L3" and memory_context and "（记忆检索失败" not in memory_context:
        funnel_level = "L2"
        print("  · [第二级] 记忆关键词匹配完成", flush=True)

    # ── 第三级：极简知识索引兜底 ────────────────────────────────────────────
    quickmap_cfg = cfg.get("quickmap", {})
    quickmap_section = ""
    if quickmap_cfg.get("enabled", True):
        quickmap_section = _load_quickmap(template_name)
        print("  · [第三级] 极简知识索引已加载", flush=True)

    # ── 结构化代码库上下文（codemap + funcmap + e2e） ─────────────────────
    codemap_ctx = _load_codemap(template_name)
    funcmap_ctx = _extract_funcmap(task_description, template_name)
    e2e_ctx = _extract_e2e_traceability(task_description, template_name)

    # ── 加载 EP 模板 ────────────────────────────────────────────────────────
    template_content = _load_template(template_name)

    # ── 构建 Prompt ─────────────────────────────────────────────────────────
    user_msg = _SYNTHESIS_USER.format(
        task_description=task_description,
        arch_graph_context=arch_graph_context,
        arch_layer=arch_layer,
        arch_operation=arch_operation,
        arch_confidence=f"{arch_confidence:.2f}",
        history_context=history_section or "（无历史命中）",
        quickmap_context=quickmap_section,
        codemap_context=codemap_ctx,
        funcmap_context=funcmap_ctx,
        e2e_context=e2e_ctx,
        memory_context=memory_context,
        template_content=template_content,
        custom_requirements=extra_requirements or "（无）",
        funnel_level=funnel_level,
    )

    # ── 调用 LLM（生成最终起手提示词）────────────────────────────────────
    result = _call_llm(user_msg)

    # ── 写入历史记录（第一级的原料，供下次使用）────────────────────────────
    # v3.0：同时记录架构图谱解析出的文件（比 quickmap 更精确）
    if cfg.get("record_after_synthesize", True) and history_cfg.get("enabled", True):
        try:
            try:
                from mms.task_matcher import TaskMatcher
            except ImportError:
                from task_matcher import TaskMatcher  # type: ignore[no-redef]

            all_files = list(dict.fromkeys(
                arch_resolved_files          # v3.0 新增：图谱解析的真实路径（优先级最高）
                + history_hit_files
                + _extract_quickmap_files(template_name)
            ))
            all_mems = list(dict.fromkeys(
                history_hit_memories + _extract_quickmap_memories(template_name)
            ))
            recorder = TaskMatcher(
                max_history_records=history_cfg.get("max_history_records", 500),
            )
            record = recorder.build_record(
                task=task_description,
                template=template_name,
                hit_memories=all_mems[:10],
                hit_files=all_files[:10],
                author=author,
            )
            recorder.append_record(record)
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠ 历史记录写入失败（不影响结果）：{exc}", flush=True)

    return result


def _build_history_hit_section(hit: "object") -> str:  # type: ignore[type-arg]
    """将历史任务命中结果格式化为 prompt 注入段落。"""
    lines = [
        f"**命中任务**：{hit.record.task}",
        f"**相似度**：{hit.similarity:.2f}  |  **共同标签**：{', '.join(hit.common_tags[:8])}",
        "",
        "**已验证的真实文件路径（直接参考，优先级最高）：**",
    ]
    for f in hit.record.hit_files:
        lines.append(f"- `{f}`")
    if hit.record.hit_memories:
        lines.append("")
        lines.append("**已验证的相关记忆 ID：**")
        for m in hit.record.hit_memories:
            lines.append(f"- {m}")
    return "\n".join(lines)


def _load_quickmap(template_name: Optional[str]) -> str:
    """
    从 task_quickmap.yaml 加载第三级极简知识索引。
    按 template_name 匹配任务类型，兜底使用 universal_context。
    不依赖 LLM，毫秒级返回，永远不为空。
    """
    if not _QUICKMAP_PATH.exists():
        return "（task_quickmap.yaml 不存在，请检查 docs/memory/_system/ 目录）"

    try:
        import yaml  # type: ignore[import]
        data = yaml.safe_load(_QUICKMAP_PATH.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        # yaml 不可用时返回文件头部文本
        raw = _QUICKMAP_PATH.read_text(encoding="utf-8")
        return raw[:800]

    task_types = data.get("task_types", {})
    universal = data.get("universal_context", {})

    lines = []

    # 通用必读（始终注入）
    always = universal.get("always_mention", [])
    universal_mems = universal.get("universal_memories", [])
    if always or universal_mems:
        lines.append("**通用必读（所有任务类型）：**")
        for f in always:
            lines.append(f"- `{f}`")
        if universal_mems:
            lines.append(f"- 核心记忆：{', '.join(universal_mems)}")
        lines.append("")

    # 任务类型专属
    key = template_name or ""
    task_cfg = task_types.get(key, {})
    if not task_cfg:
        # 未知任务类型 → 返回通用部分即可
        lines.append("（未匹配到具体任务类型，仅使用通用必读）")
        return "\n".join(lines)

    lines.append(f"**任务类型「{key}」必读文件：**")
    for f in task_cfg.get("must_read_files", []):
        lines.append(f"- `{f}`")

    hot_mems = task_cfg.get("hot_memories", [])
    if hot_mems:
        lines.append("")
        lines.append(f"**核心记忆 ID（优先读取）：** {', '.join(hot_mems)}")

    constraints = task_cfg.get("key_constraints", [])
    if constraints:
        lines.append("")
        lines.append("**核心约束（来自极简索引）：**")
        for c in constraints:
            lines.append(f"- 🔥 {c}")

    return "\n".join(lines)


def _extract_quickmap_files(template_name: Optional[str]) -> List[str]:
    """从 task_quickmap.yaml 提取该任务类型的 must_read_files（供历史记录写入）。"""
    if not _QUICKMAP_PATH.exists():
        return []
    try:
        import yaml  # type: ignore[import]
        data = yaml.safe_load(_QUICKMAP_PATH.read_text(encoding="utf-8")) or {}
        task_cfg = data.get("task_types", {}).get(template_name or "", {})
        return task_cfg.get("must_read_files", [])
    except Exception:  # noqa: BLE001
        return []


def _extract_quickmap_memories(template_name: Optional[str]) -> List[str]:
    """从 task_quickmap.yaml 提取该任务类型的 hot_memories（供历史记录写入）。"""
    if not _QUICKMAP_PATH.exists():
        return []
    try:
        import yaml  # type: ignore[import]
        data = yaml.safe_load(_QUICKMAP_PATH.read_text(encoding="utf-8")) or {}
        task_cfg = data.get("task_types", {}).get(template_name or "", {})
        universal = data.get("universal_context", {}).get("universal_memories", [])
        return list(dict.fromkeys(task_cfg.get("hot_memories", []) + universal))
    except Exception:  # noqa: BLE001
        return []


def _refresh_maps() -> None:
    """调用 codemap.py 和 funcmap.py 刷新快照文件（--refresh-maps 触发）"""
    import subprocess  # noqa: PLC0415
    for script, label in [
        (_HERE / "codemap.py", "codemap"),
        (_HERE / "funcmap.py", "funcmap"),
    ]:
        if script.exists():
            try:
                # fallback: config.yaml → runner.timeout.synthesizer_index_seconds (default=30)
                _idx_timeout = int(getattr(_mms_cfg, "runner_timeout_synthesizer_index", 30)) if _mms_cfg else 30
                subprocess.run(
                    [sys.executable, str(script)],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=_idx_timeout,
                )
                print(f"  ✓ {label} 已刷新", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"  ⚠ {label} 刷新失败：{exc}", flush=True)


# ── 模板类型 → codemap 关注目录的映射 ────────────────────────────────────────
# 决定从 codemap 中截取哪些章节（按后端/前端/混合）
_TEMPLATE_CODEMAP_SECTIONS = {
    "ep-backend-api":   ["后端应用层"],
    "ep-frontend":      ["前端源码"],
    "ep-ontology":      ["后端应用层", "前端源码"],
    "ep-data-pipeline": ["后端应用层"],
    "ep-debug":         ["后端应用层", "前端源码"],
    "ep-devops":        ["后端应用层", "前端源码", "部署"],  # 运维关注部署配置
    "ep-others":        ["后端应用层", "前端源码", "部署"],  # 通用兜底，全量检索
}

# 模板类型 → e2e_traceability 关键词（用于切片搜索）
_TEMPLATE_E2E_KEYWORDS = {
    "ep-backend-api":   ["API", "Service", "Endpoint", "Control Service"],
    "ep-frontend":      ["Frontend", "前端", "Page", "Store"],
    "ep-ontology":      ["Ontology", "ObjectType", "本体", "Object"],
    "ep-data-pipeline": ["Pipeline", "Connector", "Worker", "Ingestion", "数据管道"],
    "ep-debug":         [],  # debug 全量检索
    "ep-devops":        ["Deploy", "K8s", "Docker", "MySQL", "Redis", "部署"],
    "ep-others":        [],  # 通用兜底，不限定关键词，全量检索
}


def _load_codemap(template_name: Optional[str]) -> str:
    """
    加载 codemap.md 快照，按模板类型选择相关章节。
    codemap.md 是 codemap.py 自动生成的目录树，是文件路径的唯一可信来源。
    """
    if not _CODEMAP_PATH.exists():
        return (
            "（codemap.md 尚未生成，请先运行：`python3 scripts/mms/codemap.py`）\n"
            "【临时规则】在 codemap 未就绪期间，文件路径参考：\n"
            "  - 后端 API: backend/app/api/v1/endpoints/<name>.py\n"
            "  - 后端 Service: backend/app/services/control/<name>_service.py\n"
            "  - 前端 Service: frontend/src/services/<name>.ts\n"
            "  - 前端 Store: frontend/src/store/<name>Store.ts\n"
        )

    raw = _CODEMAP_PATH.read_text(encoding="utf-8")

    # 按模板类型决定截取哪些 ## 章节
    target_sections = _TEMPLATE_CODEMAP_SECTIONS.get(template_name or "", [])
    if not target_sections:
        # 无模板时截取全量（但限制字符数）
        trimmed = raw[:_CODEMAP_MAX_CHARS]
        if len(raw) > _CODEMAP_MAX_CHARS:
            trimmed += f"\n\n...（codemap 已截断，完整内容见 {_CODEMAP_PATH.relative_to(_ROOT)}）"
        return trimmed

    # 提取目标章节
    lines = raw.splitlines()
    result_lines: list = []
    capture = False
    chars = 0
    for line in lines:
        if line.startswith("## "):
            # 检查是否是目标章节
            capture = any(sec in line for sec in target_sections)
        if capture:
            result_lines.append(line)
            chars += len(line)
            if chars > _CODEMAP_MAX_CHARS:
                result_lines.append("...（已截断，避免 token 过多）")
                break

    if not result_lines:
        return raw[:_CODEMAP_MAX_CHARS]

    return "\n".join(result_lines)


def _extract_funcmap(task: str, template_name: Optional[str]) -> str:
    """
    从 funcmap.md 中提取与任务关键词匹配的函数签名行。
    用于告知 LLM 哪些函数已存在（避免重复实现或猜错签名）。
    """
    if not _FUNCMAP_PATH.exists():
        return "（funcmap.md 尚未生成，请先运行：`python3 scripts/mms/funcmap.py`）"

    raw = _FUNCMAP_PATH.read_text(encoding="utf-8")
    lines = raw.splitlines()

    # 从任务描述和模板类型中提取关键词
    keywords = _extract_keywords(task, template_name)

    if not keywords:
        # 无关键词时返回前几行（表头 + 少量示例）
        header_lines = [l for l in lines if l.startswith("#") or l.startswith("|")][:20]
        return "\n".join(header_lines) + "\n...（使用 --refresh-maps 获取完整索引）"

    matched: list = []
    for line in lines:
        line_lower = line.lower()
        if any(kw.lower() in line_lower for kw in keywords):
            matched.append(line)
        if len(matched) >= _FUNCMAP_MAX_LINES:
            break

    if not matched:
        return f"（funcmap 中未找到与关键词 {keywords} 匹配的函数签名）"

    header = "| 函数 | 文件 | 行号 | 说明 |\n|:--|:--|:--|:--|"
    return header + "\n" + "\n".join(matched)


def _extract_e2e_traceability(task: str, template_name: Optional[str]) -> str:
    """
    从 e2e_traceability.md 中提取与任务/模板相关的追踪切片。
    让 LLM 知道端到端模块对应的真实文件路径。
    """
    if not _E2E_TRACE_PATH.exists():
        return "（e2e_traceability.md 不存在）"

    raw = _E2E_TRACE_PATH.read_text(encoding="utf-8")
    lines = raw.splitlines()

    # 模板内置关键词 + 任务关键词合并
    template_kws = _TEMPLATE_E2E_KEYWORDS.get(template_name or "", [])
    task_kws = _extract_keywords(task, template_name)
    all_kws = list(set(template_kws + task_kws))

    if not all_kws:
        # 无关键词：返回文件头部（## 章节索引）
        section_headers = [l for l in lines if l.startswith("##")][:15]
        return "\n".join(section_headers)

    # 找到包含关键词的章节块（## 开头到下一个 ## 之间）
    sections_out: list = []
    current_block: list = []
    block_matches = False
    total_chars = 0

    for line in lines:
        if line.startswith("## "):
            if block_matches and current_block:
                block_text = "\n".join(current_block)
                sections_out.append(block_text)
                total_chars += len(block_text)
                if total_chars > 2000:
                    sections_out.append("...（e2e 切片已截断）")
                    current_block = []
                    block_matches = False
                    break
            current_block = [line]
            line_lower = line.lower()
            block_matches = any(kw.lower() in line_lower for kw in all_kws)
        else:
            if block_matches:
                current_block.append(line)
                # 也检查行内容是否包含关键词（提升章节内匹配精度）
                if not block_matches:
                    line_lower = line.lower()
                    if any(kw.lower() in line_lower for kw in all_kws):
                        block_matches = True

    # 最后一个块
    if block_matches and current_block and total_chars <= 2000:
        sections_out.append("\n".join(current_block))

    if not sections_out:
        # 降级：按行扫描，返回包含关键词的行及上下文
        context_lines: list = []
        for i, line in enumerate(lines):
            if any(kw.lower() in line.lower() for kw in all_kws):
                start = max(0, i - 2)
                end = min(len(lines), i + _E2E_CONTEXT_LINES)
                context_lines.extend(lines[start:end])
                context_lines.append("---")
                if len(context_lines) > 60:
                    break
        return "\n".join(context_lines) if context_lines else "（e2e_traceability 中未找到相关切片）"

    return "\n\n".join(sections_out)


def _extract_keywords(task: str, template_name: Optional[str]) -> list:
    """
    从任务描述中提取搜索关键词（中英文分词 + 模板内置关键词）。
    策略：优先取中文词语块和英文 CamelCase/snake_case 词。
    """
    import re  # noqa: PLC0415

    # 英文词（含 camelCase 拆分）
    words = re.findall(r"[A-Za-z][a-z]+|[A-Z]{2,}(?=[A-Z][a-z]|\d|\W|$)|[A-Z][a-z]*|\d+", task)
    en_kws = [w for w in words if len(w) >= 3]

    # 中文词块（2字以上）
    zh_chunks = re.findall(r"[\u4e00-\u9fff]{2,}", task)

    # 模板内置关键词补充
    template_extras: dict = {
        "ep-backend-api":   ["service", "endpoint", "router", "auth"],
        "ep-frontend":      ["frontend", "page", "store", "component"],
        "ep-ontology":      ["ontology", "object", "link", "action"],
        "ep-data-pipeline": ["connector", "pipeline", "worker", "ingestion"],
        "ep-debug":         ["error", "fix", "bug", "trace"],
    }
    extras = template_extras.get(template_name or "", [])

    all_kws = list(set(en_kws + zh_chunks + extras))
    # 过滤极短词和噪音
    stop = {"the", "and", "for", "with", "from", "that", "this", "are", "not", "api", "def"}
    return [k for k in all_kws if len(k) >= 3 and k.lower() not in stop]


def _inject_memories(task: str, top_k: int, compress: bool = True) -> str:
    """调用 MemoryInjector 检索相关记忆，返回压缩后的上下文文本"""
    try:
        try:
            from mms.injector import MemoryInjector
        except ImportError:
            from injector import MemoryInjector  # type: ignore[no-redef]

        injector = MemoryInjector()
        result = injector.inject(task_description=task, top_k=top_k, compress=compress)
        return result.to_prompt_prefix()
    except Exception as exc:
        return f"（记忆检索失败：{exc}；将基于模板继续合成）"


def _load_template(template_name: Optional[str]) -> str:
    """加载指定的 EP 类型模板内容"""
    if not template_name:
        return "（未指定 EP 类型模板，请使用 --template 参数选择场景）"

    # 支持带或不带 .md 后缀
    name = template_name if template_name.endswith(".md") else f"{template_name}.md"
    tpl_path = _TEMPLATES_DIR / name
    if not tpl_path.exists():
        available = ", ".join(SUPPORTED_TEMPLATES.keys())
        return f"（模板文件不存在：{name}。可用模板：{available}）"

    return tpl_path.read_text(encoding="utf-8")


def _call_llm(user_prompt: str) -> str:
    """调用 qwen3-32b 生成合成结果"""
    try:
        try:
            from mms.providers.factory import auto_detect
        except ImportError:
            from providers.factory import auto_detect  # type: ignore[no-redef]

        provider = auto_detect("reasoning")
        if not provider.is_available():
            return f"[synthesize] LLM 不可用（{provider.model_name}），请检查 DASHSCOPE_API_KEY"

        messages = [
            {"role": "system", "content": _SYNTHESIS_SYSTEM},
            {"role": "user",   "content": user_prompt},
        ]
        # fallback: config.yaml → runner.max_tokens.distillation (default=3000)
        _synth_max_tok = int(getattr(_mms_cfg, "runner_max_tokens_distillation", 3000)) if _mms_cfg else 3000
        return provider.complete_messages(messages, max_tokens=_synth_max_tok)

    except Exception as exc:
        return f"[synthesize] 调用失败：{exc}"


def interactive_extra_requirements() -> str:
    """交互式补充用户自定义要求"""
    print("\n" + "─" * 60)
    print("📝 自定义要求（回车跳过，Ctrl+D 结束输入）")
    print("   可输入：特殊约束、背景补充、不允许修改的文件、性能要求等")
    print("─" * 60)
    lines = []
    try:
        while True:
            line = input()
            lines.append(line)
    except EOFError:
        pass
    return "\n".join(lines).strip()


def list_templates() -> None:
    """打印所有可用模板"""
    print("\n可用 EP 类型模板（--template 参数）：\n")
    for name, desc in SUPPORTED_TEMPLATES.items():
        status = "✅" if (_TEMPLATES_DIR / f"{name}.md").exists() else "❌ 文件缺失"
        print(f"  {status}  {name:<22}  {desc}")
    print()
