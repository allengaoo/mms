"""
repo_map.py — Repo-Map 局部子图排序器 + 动态 Token-Fit（EP-130）

基于 aider 的 repo-map 核心思想，在 MMS 的 AIU 执行阶段：
  1. 以"目标文件集合"为中心，构建局部引用子图（BFS 1-2 跳）
  2. 对子图中的符号按引用频率排序（类 PageRank，简化版）
  3. 将排序结果动态裁剪至 token 预算（二分搜索）

与 aider 的差异（离线约束 + MMS 上下文已知）：
  - 不用 tree-sitter，Python 用 ast_index.json 已有骨架
  - 不做全仓库 PageRank，只做局部子图（目标文件已由 arch_resolver 确定）
  - token 计数用 len//4（无 tiktoken）

输出格式（送入 LLM 的骨架文本）：
  backend/app/services/control/ontology_service.py:
  ⋮...
  │class OntologyService:
  │    async def create_object_type(self, ctx: SecurityContext, ...) -> ...: ...
  │    async def list_object_types(self, ctx: SecurityContext, ...) -> ...: ...
  ⋮...

EP-130 | 2026-04-18
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

_HERE = Path(__file__).resolve().parent
try:
    from _paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE.parent.parent
_AST_INDEX_PATH = _ROOT / "docs" / "memory" / "_system" / "ast_index.json"

# ── 可配置常量 ────────────────────────────────────────────────────────────────

try:
    sys.path.insert(0, str(_HERE))
    from mms_config import cfg as _cfg  # type: ignore[import]
    _CHARS_PER_TOKEN: int = int(getattr(_cfg, "repo_map_chars_per_token", 4))
    _DEFAULT_MAP_TOKENS: int = int(getattr(_cfg, "repo_map_default_tokens", 1500))
    _BFS_MAX_DEPTH: int = int(getattr(_cfg, "repo_map_bfs_depth", 2))
    _MAX_NEIGHBOR_FILES: int = int(getattr(_cfg, "repo_map_max_neighbors", 6))
except (ImportError, AttributeError):
    _CHARS_PER_TOKEN = 4
    _DEFAULT_MAP_TOKENS = 1500
    _BFS_MAX_DEPTH = 2
    _MAX_NEIGHBOR_FILES = 6


# ── 数据结构 ─────────────────────────────────────────────────────────────────

@dataclass
class MapEntry:
    """排序后的 Repo-Map 条目（一个文件的骨架片段）。"""
    file_path: str
    rank_score: float         # 越高越优先（引用次数 + 与目标文件的距离）
    content_lines: List[str]  # 骨架文本行（aider 风格，含 │ 前缀）
    token_estimate: int       # 估算 token 数

    @property
    def text(self) -> str:
        return "\n".join(self.content_lines)


# ── AST Index 加载 ────────────────────────────────────────────────────────────

_ast_index_cache: Optional[Dict[str, dict]] = None


def _load_ast_index(path: Path = _AST_INDEX_PATH) -> Dict[str, dict]:
    """加载 ast_index.json，带缓存。"""
    global _ast_index_cache
    if _ast_index_cache is None:
        if not path.exists():
            _ast_index_cache = {}
        else:
            try:
                _ast_index_cache = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                _ast_index_cache = {}
    return _ast_index_cache


def invalidate_cache():
    """手动清除缓存（bootstrap 后调用）。"""
    global _ast_index_cache
    _ast_index_cache = None


# ── 引用图构建 ────────────────────────────────────────────────────────────────

def _build_reference_graph(index: Dict[str, dict]) -> Dict[str, Set[str]]:
    """
    构建文件引用图：如果文件 A 的 imports 中包含文件 B 定义的类名，
    则 A → B 建立有向边。

    返回：{file_path: set(referenced_file_paths)}
    """
    # 先建立 class_name → file_path 的反向索引
    class_to_file: Dict[str, str] = {}
    for file_path, skeleton in index.items():
        for cls in skeleton.get("classes", []):
            name = cls.get("name", "")
            if name:
                class_to_file[name] = file_path

    # 构建引用图
    graph: Dict[str, Set[str]] = defaultdict(set)
    for file_path, skeleton in index.items():
        for imp in skeleton.get("imports", []):
            target = class_to_file.get(imp)
            if target and target != file_path:
                graph[file_path].add(target)

    return graph


# ── 局部子图 BFS ─────────────────────────────────────────────────────────────

def _local_subgraph_bfs(
    target_files: List[str],
    graph: Dict[str, Set[str]],
    max_depth: int = _BFS_MAX_DEPTH,
    max_neighbors: int = _MAX_NEIGHBOR_FILES,
) -> Dict[str, float]:
    """
    以目标文件集合为中心，BFS 扩展 max_depth 跳，
    返回 {file_path: rank_score}（目标文件 score=1.0，每跳衰减 0.5）。
    """
    scores: Dict[str, float] = {}
    visited: Set[str] = set()
    queue: List[Tuple[str, int, float]] = []

    for f in target_files:
        scores[f] = 1.0
        visited.add(f)
        queue.append((f, 0, 1.0))

    # 构建反向图（被谁引用）
    reverse_graph: Dict[str, Set[str]] = defaultdict(set)
    for src, targets in graph.items():
        for tgt in targets:
            reverse_graph[tgt].add(src)

    head = 0
    while head < len(queue):
        current_file, depth, score = queue[head]
        head += 1

        if depth >= max_depth:
            continue

        # 正向（本文件引用了谁）+ 反向（谁引用了本文件）
        neighbors = graph.get(current_file, set()) | reverse_graph.get(current_file, set())
        for neighbor in sorted(neighbors)[:max_neighbors]:
            if neighbor not in visited:
                neighbor_score = score * 0.5
                scores[neighbor] = max(scores.get(neighbor, 0.0), neighbor_score)
                visited.add(neighbor)
                queue.append((neighbor, depth + 1, neighbor_score))

    return scores


# ── 骨架文本生成（aider 风格）────────────────────────────────────────────────

def _render_skeleton(file_path: str, skeleton: dict, score: float) -> Optional[MapEntry]:
    """将骨架数据渲染为 aider 风格的文本片段。"""
    lines = [f"{file_path}:"]

    classes = skeleton.get("classes", [])
    top_funcs = skeleton.get("top_level_functions", [])

    if not classes and not top_funcs:
        return None

    lines.append("⋮...")

    for cls in classes:
        bases_str = ", ".join(cls.get("bases", []))
        if bases_str:
            lines.append(f"│class {cls['name']}({bases_str}):")
        else:
            lines.append(f"│class {cls['name']}:")

        docstring = cls.get("docstring", "")
        if docstring:
            lines.append(f"│    \"{docstring}\"")

        methods = cls.get("methods", [])
        for method in methods:
            async_prefix = "async " if method.get("is_async") else ""
            sig = method.get("signature", "(...)")
            decorators = method.get("decorators", [])
            if decorators:
                lines.append(f"│    @{decorators[0]}")
            doc = method.get("docstring", "")
            lines.append(f"│    {async_prefix}def {method['name']}{sig}: ...")
            if doc:
                lines.append(f"│        \"{doc}\"")
        lines.append("⋮...")

    for fn in top_funcs:
        async_prefix = "async " if fn.get("is_async") else ""
        sig = fn.get("signature", "(...)")
        lines.append(f"│{async_prefix}def {fn['name']}{sig}: ...")

    if len(lines) > 2:
        text = "\n".join(lines)
        token_est = len(text) // _CHARS_PER_TOKEN
        return MapEntry(
            file_path=file_path,
            rank_score=score,
            content_lines=lines,
            token_estimate=token_est,
        )
    return None


# ── 动态 Token-Fit（二分搜索）────────────────────────────────────────────────

def _token_fit(entries: List[MapEntry], token_budget: int) -> List[MapEntry]:
    """
    按 rank_score 降序排列 entries，
    用二分搜索找出在 token_budget 内最多能放多少个 entry。

    aider 做法：binary-search 逼近预算上限，而非贪心截断。
    """
    # 按 rank_score 降序排列
    sorted_entries = sorted(entries, key=lambda e: e.rank_score, reverse=True)

    # 计算前缀累计 token
    cumulative = []
    total = 0
    for e in sorted_entries:
        total += e.token_estimate
        cumulative.append(total)

    # 二分搜索：找最大 k 使得 cumulative[k-1] <= token_budget
    lo, hi = 0, len(sorted_entries)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if cumulative[mid - 1] <= token_budget:
            lo = mid
        else:
            hi = mid - 1

    return sorted_entries[:lo]


# ── 核心 API ─────────────────────────────────────────────────────────────────

class RepoMap:
    """
    局部 Repo-Map 生成器。

    使用方式：
        repo_map = RepoMap()
        context = repo_map.build_context(
            target_files=["backend/app/services/control/ontology_service.py"],
            token_budget=1500,
        )
        # context 是 aider 风格的骨架文本字符串
    """

    def __init__(self, ast_index_path: Path = _AST_INDEX_PATH):
        self._index_path = ast_index_path
        self._index: Optional[Dict[str, dict]] = None
        self._graph: Optional[Dict[str, Set[str]]] = None

    def _ensure_loaded(self):
        if self._index is None:
            self._index = _load_ast_index(self._index_path)
        if self._graph is None:
            self._graph = _build_reference_graph(self._index)

    def build_context(
        self,
        target_files: List[str],
        token_budget: int = _DEFAULT_MAP_TOKENS,
        include_neighbors: bool = True,
    ) -> str:
        """
        为给定目标文件集合构建 Repo-Map 上下文字符串。

        Args:
            target_files: 任务直接涉及的文件路径列表（相对于项目根）
            token_budget: 最大 token 数（约 len//4 字符数）
            include_neighbors: 是否包含引用图中的邻居文件

        Returns:
            aider 风格的骨架文本字符串
        """
        self._ensure_loaded()
        if not self._index:
            return ""

        # 计算各文件的 rank_score
        if include_neighbors and self._graph:
            scores = _local_subgraph_bfs(
                target_files, self._graph,
                max_depth=_BFS_MAX_DEPTH,
                max_neighbors=_MAX_NEIGHBOR_FILES,
            )
        else:
            scores = {f: 1.0 for f in target_files}

        # 只处理有骨架数据的文件
        entries: List[MapEntry] = []
        for file_path, score in scores.items():
            skeleton = self._index.get(file_path)
            if not skeleton:
                continue
            entry = _render_skeleton(file_path, skeleton, score)
            if entry:
                entries.append(entry)

        if not entries:
            return ""

        # 动态 Token-Fit
        fitted = _token_fit(entries, token_budget)

        return "\n\n".join(e.text for e in fitted)

    def get_fingerprints(self, files: List[str]) -> Dict[str, str]:
        """获取指定文件的 AST 指纹（用于漂移检测）。"""
        self._ensure_loaded()
        result = {}
        for f in files:
            skeleton = self._index.get(f, {}) if self._index else {}
            fp = skeleton.get("fingerprint", "")
            if fp:
                result[f] = fp
        return result

    def get_class_names(self, file_path: str) -> List[str]:
        """获取指定文件中所有 Class 名称。"""
        self._ensure_loaded()
        skeleton = (self._index or {}).get(file_path, {})
        return [cls["name"] for cls in skeleton.get("classes", []) if cls.get("name")]

    def get_method_signatures(self, file_path: str, class_name: str) -> List[dict]:
        """获取指定文件中某 Class 的所有方法签名。"""
        self._ensure_loaded()
        skeleton = (self._index or {}).get(file_path, {})
        for cls in skeleton.get("classes", []):
            if cls.get("name") == class_name:
                return cls.get("methods", [])
        return []

    def bind_entry_points(self, layers_config: dict) -> Dict[str, str]:
        """
        将 layers.yaml 的 entry_files 绑定到 ast_index 中的实际骨架。
        返回 {file_path: fingerprint} 的绑定结果。
        """
        self._ensure_loaded()
        bindings: Dict[str, str] = {}
        for layer_id, layer_data in (layers_config.get("layers") or {}).items():
            for entry_file in layer_data.get("entry_files", []):
                fp = (self._index or {}).get(entry_file, {}).get("fingerprint", "")
                if fp:
                    bindings[entry_file] = fp
        return bindings
