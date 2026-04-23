"""
记忆注入引擎 — MMS v2.2
==========================
设计目标：
  1. 任务理解：从自然语言任务描述中提取 (layer, module, keywords) 三元组
  2. 多层检索：跨 L1~L5 + CC 层检索最相关的记忆，按分数排序
  3. 上下文压缩：对超长记忆文件提取关键段落（HOW + WHEN），降低 token 消耗
  4. Prompt 前缀生成：格式化为结构化的 Markdown 块，可直接粘贴到 Cursor
  5. 意图分类：规则匹配优先，低置信度时触发百炼 qwen3-32b LLM fallback

用法（CLI）：
  mms inject "新增对象类型 API，需要 ProTable 和 Zustand Store"
  mms inject "修复 Avro 序列化失败" --top-k 8 --output inject_ctx.md
  mms inject "数据管道 Connector" --no-compress

输出格式（inject-output.md 模板）：
  <!-- MMS-INJECT | task: ... | memories: N | tokens: ~N | ep: ... -->
  ## 相关记忆（自动注入）
  ### [MEM-L-002] Avro 序列化静默失败根因...
  **HOW**: ...
  **WHEN**: ...
  ---
  <!-- END-MMS-INJECT -->
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── 路径常量 ──────────────────────────────────────────────────────────────────
_SCRIPT_DIR   = Path(__file__).parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
_MEMORY_ROOT  = _PROJECT_ROOT / "docs" / "memory"
_INDEX_FILE   = _MEMORY_ROOT / "MEMORY_INDEX.json"

try:
    import sys as _sys
    _sys.path.insert(0, str(_SCRIPT_DIR))
    from mms_config import cfg as _cfg  # type: ignore[import]
except Exception:
    _cfg = None  # type: ignore[assignment]

# ── 任务 → 层/模块的规则映射（无 LLM 时的降级策略）────────────────────────────
_KEYWORD_LAYER_MAP: List[Tuple[List[str], List[str]]] = [
    # (触发词列表, [layer, module])
    (["api", "endpoint", "路由", "response", "request", "状态码", "envelope",
      "apiresponse", "protable", "前端", "页面", "react", "zustand", "store",
      "component", "组件", "button", "权限按钮", "permissiongate"],
     ["L5", "L5-D8", "L5-frontend", "L5-D10"]),

    (["kafka", "avro", "schema", "序列化", "message", "消息", "topic",
      "schema-registry", "normalize"],
     ["L2", "L2-D6"]),

    (["mysql", "session", "transaction", "事务", "alembic", "migration",
      "session.begin", "autobegin"],
     ["L2", "L2-D9"]),

    (["objecttypedef", "linktypedef", "actiondef", "functiondef", "本体",
      "ontology", "action", "回写", "overlay", "primary_key", "unique_key",
      "sharedproperty", "shared_property"],
     ["L3", "L3-ontology"]),

    (["connector", "syncjob", "ingestionworker", "数据管道", "pipeline",
      "datacatalog", "column", "列映射", "data_catalog"],
     ["L3", "L3-data_pipeline"]),

    (["tenantquota", "quota", "配额", "cr", "change request", "审批",
      "changerequest", "governance", "治理"],
     ["L3", "L3-governance"]),

    (["worker", "jobexecutionscope", "cqrs", "docker", "k8s", "kubectl",
      "deployment", "image", "deploy"],
     ["L4", "L4-workers"]),

    (["tenant_id", "securitycontext", "rls", "多租户", "audit", "auditservice"],
     ["L1", "L1-D1"]),

    (["test", "测试", "polyfactory", "dirty-equals", "msw", "vitest",
      "pytest", "renderWithProviders"],
     ["L5", "L5-D10"]),

    (["iceberg", "minio", "s3", "存储", "iceberg commit"],
     ["L2", "L2-storage"]),
]


# ── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class MemorySnippet:
    """单条记忆的注入片段"""
    memory_id:  str
    title:      str
    tier:       str
    file_path:  str
    score:      float
    how_section: str = ""    # HOW 段落（压缩后）
    when_section: str = ""   # WHEN 段落（触发条件）


@dataclass
class InjectionResult:
    """注入结果，可序列化为 Prompt 前缀"""
    task_description: str
    memories: List[MemorySnippet]
    detected_layers: List[str]
    estimated_tokens: int = 0

    def to_prompt_prefix(self) -> str:
        lines = [
            f"<!-- MMS-INJECT | task: {self.task_description[:60]} "
            f"| memories: {len(self.memories)} "
            f"| tokens: ~{self.estimated_tokens} -->",
            "",
            "## 相关记忆（自动注入，基于 MMS v2.2 推理式检索）",
            f"**任务**: {self.task_description}",
            f"**检测到的层**: {', '.join(self.detected_layers) if self.detected_layers else '跨层'}",
            "",
        ]

        for i, mem in enumerate(self.memories, 1):
            tier_badge = {"hot": "🔥", "warm": "⚡", "cold": "❄️"}.get(mem.tier, "·")
            lines.append(f"### {i}. {tier_badge} [{mem.memory_id}] {mem.title}")

            if mem.how_section:
                lines.append("")
                lines.append("**如何做**：")
                # 截取 HOW 段落（最多 600 字符）
                how = mem.how_section.strip()
                if len(how) > 600:
                    how = how[:600] + "\n...(更多详情见原文)"
                lines.append(how)

            if mem.when_section:
                lines.append("")
                lines.append("**何时触发**：")
                lines.append(mem.when_section.strip()[:300])

            lines.append(f"\n> 原文: `docs/memory/{mem.file_path}`")
            lines.append("\n---")

        lines.append("\n<!-- END-MMS-INJECT -->")
        result = "\n".join(lines)

        # 更新 token 估算（粗略：1 token ≈ 1.5 中文字符 / 4 英文字符）
        self.estimated_tokens = len(result) // 3
        return result


# ── 核心引擎 ──────────────────────────────────────────────────────────────────

class MemoryInjector:
    """
    记忆注入引擎。

    调用方式：
        injector = MemoryInjector()
        result = injector.inject("新增对象类型 API", top_k=5)
        print(result.to_prompt_prefix())
    """

    def __init__(self) -> None:
        self._index: Optional[Dict] = None

    def _load_index(self) -> Dict:
        if self._index is None:
            import json
            if _INDEX_FILE.exists():
                self._index = json.loads(_INDEX_FILE.read_text(encoding="utf-8"))
            else:
                self._index = {}
        return self._index

    # ── 任务分类（规则 + 可选 LLM）──────────────────────────────────────────

    def _classify_task(self, task: str) -> List[str]:
        """
        从任务描述中提取相关节点 ID 列表（如 ["L5", "L5-D8", "L3", "L3-ontology"]）。
        策略：先用规则匹配，如果 LLM 可用则用 qwen3-32b 二次增强。
        """
        task_lower = task.lower()
        matched_nodes: List[str] = []

        for keywords, node_ids in _KEYWORD_LAYER_MAP:
            if any(kw in task_lower for kw in keywords):
                matched_nodes.extend(node_ids)

        # 去重，保持顺序
        seen = set()
        unique_nodes = []
        for n in matched_nodes:
            if n not in seen:
                seen.add(n)
                unique_nodes.append(n)

        # 如果没匹配到，默认返回高频层（L1+L2 全局约束 + L5 接口层）
        if not unique_nodes:
            unique_nodes = ["L1", "L2", "L5"]

        # 可选：尝试用百炼 LLM 增强分类（快速 prompt，不阻塞）
        try:
            self._enhance_with_llm(task, unique_nodes)
        except Exception:
            pass  # LLM 不可用时静默降级，规则匹配已足够

        return unique_nodes

    def _enhance_with_llm(self, task: str, current_nodes: List[str]) -> None:
        """
        可选 LLM 增强：用 qwen3-32b 分析任务，补充可能遗漏的节点。
        结果直接修改 current_nodes（in-place）。
        """
        try:
            from providers.factory import auto_detect  # type: ignore[import]
            provider = auto_detect("intent_classification")
        except Exception:
            return  # LLM 不可用时静默跳过
        if not provider.is_available():
            return

        # 获取所有节点 ID 列表（从索引中）
        index = self._load_index()
        all_node_ids = self._collect_all_node_ids(index.get("tree", []))

        prompt = f"""你是 MDP 平台的代码助手。请根据以下任务描述，从给定的节点列表中选出最相关的 2-4 个节点 ID。
只输出节点 ID，用逗号分隔，不要有任何解释。

任务：{task}

可用节点：{', '.join(all_node_ids)}

当前已选：{', '.join(current_nodes)}

你的补充选择（如果当前已足够，输出空）："""

        # fallback: config.yaml → runner.max_tokens.context_injection (default=100)
        max_tok = int(getattr(_cfg, "runner_max_tokens_context_injection", 100)) if _cfg else 100
        response = provider.complete(prompt, max_tokens=max_tok, temperature=0.0)
        if not response:
            return

        # 解析 LLM 返回的节点 ID
        extra_nodes = [
            n.strip() for n in response.split(",")
            if n.strip() in all_node_ids and n.strip() not in current_nodes
        ]
        current_nodes.extend(extra_nodes[:2])  # 最多追加 2 个

    def _collect_all_node_ids(self, tree: List[Dict]) -> List[str]:
        """递归收集索引树中所有 node_id"""
        result = []
        for node in tree:
            result.append(node.get("node_id", ""))
            result.extend(self._collect_all_node_ids(node.get("nodes", [])))
        return [n for n in result if n]

    # ── 记忆检索 ────────────────────────────────────────────────────────────

    def _retrieve_memories(
        self, nodes: List[str], task: str, top_k: int
    ) -> List[MemorySnippet]:
        """从索引中检索候选记忆，计算相关性分数并排序"""
        index = self._load_index()
        task_lower = task.lower()

        # 展开所有候选记忆（来自指定节点 + 全局 hot 记忆）
        candidates: List[Dict] = []
        self._collect_memories(index.get("tree", []), nodes, candidates)

        # 计算每条记忆的分数
        scored: List[Tuple[float, Dict]] = []
        for mem in candidates:
            score = self._score_memory(mem, task_lower, nodes)
            if score > 0:
                scored.append((score, mem))

        # 排序（分数降序），取 top_k
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:top_k]

        # 构建 MemorySnippet
        snippets = []
        for score, mem in top:
            snippet = MemorySnippet(
                memory_id=mem.get("id", "?"),
                title=mem.get("title", ""),
                tier=mem.get("tier", "warm"),
                file_path=mem.get("file", ""),
                score=score,
            )
            snippets.append(snippet)

        return snippets

    def _collect_memories(
        self, tree: List[Dict], target_nodes: List[str], out: List[Dict]
    ) -> None:
        """递归遍历索引树，收集目标节点下的记忆，以及全局 hot 记忆"""
        for node in tree:
            node_id = node.get("node_id", "")
            in_target = any(
                node_id == n or node_id.startswith(n + "-") or n.startswith(node_id)
                for n in target_nodes
            )

            for mem in node.get("memories", []):
                # 命中目标节点，或者是 hot 记忆（全局规则记忆）
                if in_target or mem.get("tier") == "hot":
                    if mem not in out:
                        out.append(mem)

            # 递归处理子节点
            self._collect_memories(node.get("nodes", []), target_nodes, out)

    def _score_memory(
        self, mem: Dict, task_lower: str, target_nodes: List[str]
    ) -> float:
        """
        综合评分（满分 10 分）：
        - tier 分数：hot=3, warm=2, cold=1
        - 关键词匹配：title 中每个关键词 +1（最多 +4）
        - tags 匹配：每个 tag 命中 +0.5（最多 +2）
        - 节点命中：所在节点在 target_nodes 中 +1
        """
        score = 0.0

        # tier 基础分
        tier = mem.get("tier", "warm")
        score += {"hot": 3.0, "warm": 2.0, "cold": 1.0}.get(tier, 1.0)

        # title 关键词匹配
        title_lower = mem.get("title", "").lower()
        kw_hits = sum(1 for kw in task_lower.split() if len(kw) > 2 and kw in title_lower)
        score += min(kw_hits, 4) * 1.0

        # tags 匹配
        tags = mem.get("tags", [])
        tag_hits = sum(1 for tag in tags if tag in task_lower)
        score += min(tag_hits, 4) * 0.5

        # access_count 频次分（高频记忆更值得推荐，上限 0.8 防止过度压制领域记忆）
        access = mem.get("access_count", 0)
        score += min(access / 20.0, 0.8)

        # 节点内优先奖励：明确属于目标节点的记忆额外 +1.5
        # 防止全局 hot 跨领域记忆（如 AD-002 RLS）压过特定领域记忆
        mem_node = mem.get("node_id", "")
        if mem_node and any(
            mem_node == n or mem_node.startswith(n + "-") or n.startswith(mem_node)
            for n in target_nodes
        ):
            score += 1.5

        return score

    # ── 内容提取与压缩 ───────────────────────────────────────────────────────

    def _load_and_compress(
        self, snippet: MemorySnippet, compress: bool
    ) -> None:
        """读取记忆文件，提取 HOW + WHEN 段落"""
        if not snippet.file_path:
            snippet.how_section = "(file 路径未配置，请检查 MEMORY_INDEX.json 中的 file 字段)"
            return
        fpath = _MEMORY_ROOT / snippet.file_path
        if not fpath.exists() or fpath.is_dir():
            snippet.how_section = "(文件不存在或路径指向目录，请检查 MEMORY_INDEX.json)"
            return

        content = fpath.read_text(encoding="utf-8", errors="ignore")

        # 跳过 front-matter
        parts = content.split("---\n", 2)
        body = parts[2] if len(parts) >= 3 else content

        if compress:
            # HOW 段落：支持 MEM-L-xxx 的 "HOW" 和 AD-xxx 的 "决策/Rationale/Decision"
            how = self._extract_section(body, "HOW")
            if not how:
                how = self._extract_section_first_of(
                    body, ["决策", "Rationale", "Decision", "结论"]
                )
            snippet.how_section = how

            # WHEN 段落：支持 MEM-L-xxx 的 "WHEN" 和 AD-xxx 的 "适用场景/背景/Context"
            when = self._extract_section(body, "WHEN")
            if not when:
                when = self._extract_section_first_of(
                    body, ["适用场景", "背景", "Context", "影响", "Impact"]
                )
            snippet.when_section = when
        else:
            # 不压缩：返回全文
            snippet.how_section = body[:2000]
            snippet.when_section = ""

    def _extract_section(self, body: str, section_name: str) -> str:
        """
        提取特定 Markdown 二级标题段落（## HOW / ## WHEN 等）。
        返回该段落的纯文本内容（不含标题行）。
        """
        pattern = re.compile(
            r"##\s+[^\n]*" + re.escape(section_name) + r"[^\n]*\n(.*?)(?=\n##\s|\Z)",
            re.DOTALL | re.IGNORECASE,
        )
        m = pattern.search(body)
        if m:
            return m.group(1).strip()
        return ""

    def _extract_section_first_of(self, body: str, candidates: list) -> str:
        """
        按候选名称列表顺序，提取第一个匹配的 Markdown 二级标题段落。
        用于 AD 类记忆使用中文标题（如"决策"、"背景"）的场景。
        """
        for name in candidates:
            result = self._extract_section(body, name)
            if result:
                return result
        return ""

    # ── 公开接口 ─────────────────────────────────────────────────────────────

    def inject(
        self,
        task_description: str,
        top_k: int = 5,
        compress: bool = True,
    ) -> InjectionResult:
        """
        主入口：输入任务描述，输出注入结果。

        参数：
            task_description: 自然语言任务描述
            top_k:            最多注入的记忆条数（默认 5）
            compress:         是否压缩（只取 HOW + WHEN 段落）

        返回：
            InjectionResult（可调用 .to_prompt_prefix() 生成 Markdown 字符串）
        """
        # 1. 任务分类
        detected_nodes = self._classify_task(task_description)

        # 2. 多层检索
        snippets = self._retrieve_memories(detected_nodes, task_description, top_k)

        # 3. 内容加载与压缩
        for snippet in snippets:
            self._load_and_compress(snippet, compress)

        # 4. 构建结果
        result = InjectionResult(
            task_description=task_description,
            memories=snippets,
            detected_layers=detected_nodes,
        )
        result.estimated_tokens = len(result.to_prompt_prefix()) // 3

        return result


# ── 命令行独立运行 ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python -m mms.injector <任务描述> [--top-k N] [--no-compress]")
        sys.exit(1)

    # 简单参数解析
    _args = sys.argv[1:]
    _top_k = 5
    _compress = True
    _task_parts = []

    i = 0
    while i < len(_args):
        if _args[i] == "--top-k" and i + 1 < len(_args):
            _top_k = int(_args[i + 1])
            i += 2
        elif _args[i] == "--no-compress":
            _compress = False
            i += 1
        else:
            _task_parts.append(_args[i])
            i += 1

    _task = " ".join(_task_parts)
    injector = MemoryInjector()
    result = injector.inject(_task, top_k=_top_k, compress=_compress)
    print(result.to_prompt_prefix())
