#!/usr/bin/env python3
"""
arch_resolver.py — MMS-OG v3.0 确定性路径解析器

基于 arch_schema/layers.yaml + codemap.md，将"意图分类结果"转换为
真实存在于代码库的文件路径列表（零 LLM，零幻觉）。

核心设计：
  路径 100% 来自 codemap.md 快照（代码库的事实镜像），
  不允许 LLM 或任何推理逻辑凭空创造路径。

主要功能：
  1. resolve_files(layer, keywords)  — 层 + 关键词 → 验证过的真实路径
  2. grep_codemap(keywords)          — 在 codemap.md 中搜索关键词
  3. validate_path(path)             — 检查路径是否在 codemap 中存在
  4. resolve_from_intent(result)     — 直接从 IntentResult 解析路径

用法：
  from mms.analysis.arch_resolver import ArchResolver
  resolver = ArchResolver()
  files = resolver.resolve_from_intent(intent_result)
  # files 全部来自 codemap，不含幻觉路径
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List, Optional, Set

_HERE = Path(__file__).resolve().parent
try:
    from mms.utils._paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE.parent.parent
_SCHEMA_DIR = _ROOT / "docs" / "memory" / "_system" / "routing"
_LAYERS_PATH = _SCHEMA_DIR / "layers.yaml"
_CODEMAP_PATH = _ROOT / "docs" / "memory" / "_system" / "mms.memory.codemap.md"

_MAX_FILES_PER_RESOLUTION = 8   # 单次解析最多返回的文件数
_MIN_TOKEN_LENGTH = 4           # codemap grep 时的最小 token 长度（统一，避免不一致）
_FALLBACK_PREFIX_LIMIT = 2      # 降级时最多扫描的 path_prefixes 数量
_FALLBACK_FILES_PER_PREFIX = 3  # 降级时每目录最多取的文件数
# 降级扫描时按层前缀决定扩展名：key 为包含该字符串的前缀 → value 为 glob 模式
_PREFIX_EXTENSION_MAP = [
    ("frontend", "*.ts"),
    ("frontend", "*.tsx"),
    ("backend", "*.py"),
]
_DEFAULT_EXTENSION = "*.py"


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore[import]
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}


class ArchResolver:
    """
    确定性文件路径解析器。

    所有返回的路径均来自 codemap.md（代码库快照），不含 LLM 推理。
    """

    def __init__(self) -> None:
        self._layers_data: Optional[dict] = None
        self._codemap_lines: Optional[List[str]] = None
        self._codemap_paths: Optional[Set[str]] = None

    def _ensure_loaded(self) -> None:
        if self._layers_data is None:
            self._layers_data = _load_yaml(_LAYERS_PATH)
        if self._codemap_lines is None:
            self._codemap_lines = self._load_codemap()
            self._codemap_paths = self._index_codemap_paths()

    def _load_codemap(self) -> List[str]:
        """读取 codemap.md 的所有行。"""
        if not _CODEMAP_PATH.exists():
            return []
        return _CODEMAP_PATH.read_text(encoding="utf-8").splitlines()

    def _index_codemap_paths(self) -> Set[str]:
        """
        从 codemap.md 中提取所有文件/目录路径。
        codemap 格式通常是树状结构，路径以 / 分隔。
        提取规则：查找包含 '/' 的非注释行。
        """
        paths: Set[str] = set()
        if not self._codemap_lines:
            return paths

        for line in self._codemap_lines:
            stripped = line.strip()
            # 提取看起来像路径的部分（含 / 且不是纯注释）
            if "/" in stripped and not stripped.startswith("#"):
                # 从行中提取路径片段（去掉树状字符如 ├── │ └── ）
                clean = re.sub(r"[│├└─ ]+", " ", stripped).strip()
                # 提取最长的路径段
                for token in clean.split():
                    if "/" in token and len(token) > _MIN_TOKEN_LENGTH:
                        # 去掉尾部的描述文字
                        path_token = token.rstrip(",:；。")
                        if path_token:
                            paths.add(path_token)
        return paths

    # ── 公共 API ──────────────────────────────────────────────────────────────

    def resolve_from_intent(self, intent_result: "IntentResult") -> List[str]:  # type: ignore[name-defined]  # noqa: F821
        """
        从意图分类结果直接解析真实文件路径。

        步骤：
          1. 从 layers.yaml 获取该层的 path_prefixes + entry_files
          2. 用 intent_result.entry_files_hint 补充候选路径
          3. 用命中的关键词在 codemap.md 中 grep 扩展
          4. 验证所有候选路径（在 codemap 中存在或磁盘上真实存在）
          5. 去重排序，截取 MAX_FILES_PER_RESOLUTION 条

        参数：
            intent_result: IntentClassifier.classify() 的返回值

        返回：
            真实存在的文件/目录路径列表（最多 MAX_FILES_PER_RESOLUTION 条）
        """
        self._ensure_loaded()

        candidates: List[str] = []

        # 1. 从 layers.yaml 取入口文件（最可信）
        layers = (self._layers_data or {}).get("layers", {})
        layer_def = layers.get(intent_result.layer, {})
        candidates.extend(layer_def.get("entry_files", []))

        # 2. 从 intent_result.entry_files_hint 补充（可能来自规则或 LLM）
        # 若 hint 是目录路径（以 "/" 结尾或 is_dir()），自动展开其下的 .md 文件
        for hint in intent_result.entry_files_hint:
            if not hint:
                continue
            hint_path = _ROOT / hint
            if hint.endswith("/") or hint_path.is_dir():
                # 优先展开 .md 文档；无 md 时按前缀规则回退展开代码文件
                md_files = sorted(hint_path.glob("*.md"))
                if md_files:
                    for md_file in md_files:
                        rel = str(md_file.relative_to(_ROOT))
                        if rel not in candidates:
                            candidates.append(rel)
                else:
                    ext = _DEFAULT_EXTENSION
                    for key, pattern in _PREFIX_EXTENSION_MAP:
                        if key in hint:
                            ext = pattern
                            break
                    for code_file in sorted(hint_path.glob(ext))[:_FALLBACK_FILES_PER_PREFIX]:
                        rel = str(code_file.relative_to(_ROOT))
                        if rel not in candidates:
                            candidates.append(rel)
            elif hint not in candidates:
                candidates.append(hint)

        # 3. 用关键词在 codemap 中 grep 扩展
        if intent_result.matched_keywords:
            grep_results = self.grep_codemap(intent_result.matched_keywords[:5])
            for p in grep_results:
                if p not in candidates:
                    candidates.append(p)

        # 4. 验证：只保留真实存在的「文件」（排除目录，防止 path_prefix 混入）
        verified: List[str] = []
        seen: Set[str] = set()
        for path in candidates:
            if path in seen:
                continue
            seen.add(path)
            full = _ROOT / path
            # 只接受文件（is_file()），排除目录和不存在的路径
            if full.is_file():
                verified.append(path)
            elif not full.exists() and self.validate_path(path):
                # codemap 中存在（快照记录了该文件）但本地不存在 → 也接受
                verified.append(path)

        # 5. 若验证后为空，降级返回层的 path_prefixes 中匹配的真实文件（glob）
        if not verified:
            prefixes = layer_def.get("path_prefixes", [])
            for prefix in prefixes[:_FALLBACK_PREFIX_LIMIT]:
                prefix_path = _ROOT / prefix
                if prefix_path.is_dir():
                    # 按前缀关键字选扩展名（可配置），避免写死 "backend"/"frontend"
                    ext = _DEFAULT_EXTENSION
                    for key, pattern in _PREFIX_EXTENSION_MAP:
                        if key in prefix:
                            ext = pattern
                            break
                    for fp in sorted(prefix_path.glob(ext))[:_FALLBACK_FILES_PER_PREFIX]:
                        rel = str(fp.relative_to(_ROOT))
                        if rel not in seen:
                            verified.append(rel)
                            seen.add(rel)
                elif prefix_path.is_file():
                    rel = str(prefix_path.relative_to(_ROOT))
                    if rel not in seen:
                        verified.append(rel)
                        seen.add(rel)

        return verified[:_MAX_FILES_PER_RESOLUTION]

    def resolve_files(self, layer: str, keywords: Optional[List[str]] = None) -> List[str]:
        """
        给定层 ID 和可选关键词，返回该层的真实文件路径。

        参数：
            layer:    层 ID，如 "ADAPTER"（通用 5 层）或旧格式 "L5_frontend"（兼容）
            keywords: 可选关键词列表，用于在层内进一步精确定位

        返回：
            验证过的真实路径列表
        """
        self._ensure_loaded()

        layers = (self._layers_data or {}).get("layers", {})
        layer_def = layers.get(layer, {})

        candidates = list(layer_def.get("entry_files", []))

        if keywords:
            # 在 codemap 中 grep 关键词，并过滤到该层的 path_prefixes
            prefixes = layer_def.get("path_prefixes", [])
            grep_results = self.grep_codemap(keywords[:5])
            for p in grep_results:
                if any(p.startswith(prefix) or prefix in p for prefix in prefixes):
                    if p not in candidates:
                        candidates.append(p)

        verified = [p for p in candidates if self.validate_path(p)]
        return verified[:_MAX_FILES_PER_RESOLUTION]

    def grep_codemap(self, keywords: List[str]) -> List[str]:
        """
        在 codemap.md 中按关键词搜索，返回匹配的文件/目录路径。

        匹配规则：
          - 关键词不区分大小写
          - 同一行匹配任意一个关键词即算匹配
          - 从匹配行中提取路径段（包含 / 的 token）

        参数：
            keywords: 搜索关键词列表

        返回：
            从 codemap.md 中提取的路径列表（未验证是否在磁盘上存在）
        """
        self._ensure_loaded()

        if not self._codemap_lines or not keywords:
            return []

        kws_lower = [kw.lower() for kw in keywords]
        results: List[str] = []
        seen: Set[str] = set()

        for line in self._codemap_lines:
            line_lower = line.lower()
            # 检查是否命中任意关键词
            if not any(kw in line_lower for kw in kws_lower):
                continue

            # 从该行提取路径
            clean = re.sub(r"[│├└─ ]+", " ", line).strip()
            for token in clean.split():
                if "/" in token and len(token) > 4:
                    path = token.rstrip(",:；。")
                    if path and path not in seen:
                        seen.add(path)
                        results.append(path)

        return results[:_MAX_FILES_PER_RESOLUTION * 2]  # 返回多一些，留给 validate 过滤

    def validate_path(self, path: str) -> bool:
        """
        验证路径是否存在于 codemap 或磁盘上。

        优先检查 codemap（快速），降级检查磁盘（准确但慢）。
        """
        if not path:
            return False

        self._ensure_loaded()

        # 方法1：在 codemap 中精确匹配
        if self._codemap_paths:
            if path in self._codemap_paths:
                return True
            # 模糊匹配：按路径分段匹配，避免子串误判
            # 规则：规范化后逐段比较（避免 "foo/bar" 误匹配 "foo/barbaz"）
            norm = path.replace("\\", "/").strip("/")
            norm_parts = norm.split("/")
            for cp in self._codemap_paths:
                cp_norm = cp.replace("\\", "/").strip("/")
                cp_parts = cp_norm.split("/")
                # 只接受「path 是 cp 的后缀路径段」或「cp 是 path 的后缀路径段」
                if (
                    cp_parts[-len(norm_parts):] == norm_parts
                    or norm_parts[-len(cp_parts):] == cp_parts
                ):
                    return True

        # 方法2：磁盘检查（兜底）
        full_path = _ROOT / path
        return full_path.exists()

    def get_layer_prefixes(self, layer: str) -> List[str]:
        """返回某层的 path_prefixes 列表。"""
        self._ensure_loaded()
        layers = (self._layers_data or {}).get("layers", {})
        return layers.get(layer, {}).get("path_prefixes", [])

    def get_layer_entry_files(self, layer: str) -> List[str]:
        """返回某层的 entry_files 列表。"""
        self._ensure_loaded()
        layers = (self._layers_data or {}).get("layers", {})
        return layers.get(layer, {}).get("entry_files", [])

    def get_universal_files(self) -> List[str]:
        """返回 intent_map.yaml 中定义的通用补充文件。"""
        from scripts.mms.intent_classifier import _load_yaml  # type: ignore[import]
        intent_map_path = _SCHEMA_DIR / "intent_map.yaml"
        data = _load_yaml(intent_map_path)
        return data.get("universal_files", [])

    # ── EP-130 新增：双轨路由（AST 骨架 + Ontology 约束）────────────────────────

    def resolve_with_ast_skeleton(
        self,
        intent_result,
        token_budget: int = 1500,
        include_neighbors: bool = True,
    ) -> dict:
        """
        EP-130 双轨路由：在现有路径解析基础上，
        额外从 ast_index.json 提取对应文件的骨架片段。

        返回：{
            "files": [str, ...],           # 现有 arch_resolver 逻辑的文件列表
            "ast_skeleton": str,           # repo_map 风格的骨架文本（已 Token-Fit 裁剪）
            "ontology_constraints": [str], # 该层的约束条款摘要
        }
        """
        # 第一步：用现有逻辑解析文件
        files = self.resolve_from_intent(intent_result)

        # 第二步：加载 repo_map（惰性导入，避免循环依赖）
        ast_skeleton_text = ""
        try:
            sys.path.insert(0, str(_HERE))
            from mms.memory.repo_map import RepoMap  # type: ignore[import]
            rm = RepoMap()
            if files:
                ast_skeleton_text = rm.build_context(
                    target_files=files,
                    token_budget=token_budget,
                    include_neighbors=include_neighbors,
                )
        except Exception:
            pass  # AST 骨架获取失败时静默降级，不影响正常路由

        # 第三步：提取该层的约束条款（从 layers.yaml hot_memories 列出的记忆 ID）
        ontology_constraints = []
        try:
            self._ensure_loaded()
            layers = (self._layers_data or {}).get("layers", {})
            layer_id = getattr(intent_result, "layer", "") or ""
            layer_data = layers.get(layer_id, {})
            hot_memories = layer_data.get("hot_memories", [])
            if hot_memories:
                ontology_constraints = hot_memories[:5]  # 最多 5 条，避免超出预算
        except Exception:
            pass

        return {
            "files": files,
            "ast_skeleton": ast_skeleton_text,
            "ontology_constraints": ontology_constraints,
        }


# ── CLI 入口（调试用）────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if not args:
        print("用法:")
        print("  arch_resolver.py layer L5_frontend          # 查看层的入口文件")
        print("  arch_resolver.py grep navigation sidebar     # 在 codemap 中搜索")
        print("  arch_resolver.py validate frontend/src/config/navigation.ts  # 验证路径")
        sys.exit(0)

    cmd = args[0]
    rest = args[1:]
    resolver = ArchResolver()

    if cmd == "layer":
        layer_id = rest[0] if rest else "ADAPTER"
        entry = resolver.get_layer_entry_files(layer_id)
        prefixes = resolver.get_layer_prefixes(layer_id)
        print(f"\n层：{layer_id}")
        print("入口文件：")
        for f in entry:
            exists = "✅" if resolver.validate_path(f) else "❌"
            print(f"  {exists} {f}")
        print(f"路径前缀：{prefixes}")

    elif cmd == "grep":
        results = resolver.grep_codemap(rest)
        print(f"\n关键词 grep {rest} 结果：")
        for r in results:
            exists = "✅" if resolver.validate_path(r) else "❓"
            print(f"  {exists} {r}")

    elif cmd == "validate":
        path = " ".join(rest)
        exists = resolver.validate_path(path)
        print(f"{'✅' if exists else '❌'} {path}")

    else:
        print(f"未知命令: {cmd}")
