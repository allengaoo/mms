"""
src/mms/bootstrap/code_graph_builder.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
代码依赖图构建器（fn_build_code_graph 的 Python 实现）

从 ast_index.json 的 imports 字段提取项目内部跨文件依赖，
构建带权有向图：
  节点 = CodeClass（file_path::ClassName）
  边   = depends_on（import 依赖）/ implements（继承/接口实现）

版本：v1.0 | 创建于：2026-04-30 | Bootstrap v2
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# ─── 数据类 ──────────────────────────────────────────────────────────────────

@dataclass
class DependsOnEdge:
    source_fqn: str   # file_path::ClassName
    target_fqn: str
    source_file: str
    target_file: str
    weight: float = 1.0


@dataclass
class ImplementsEdge:
    source_fqn: str
    target_name: str   # 可能只有短名（父类未全限定）


@dataclass
class ContainsEdge:
    module_path: str
    file_path: str


@dataclass
class CodeGraph:
    """代码依赖图（fn_build_code_graph 的输出）。"""
    # 节点
    classes: Dict[str, dict] = field(default_factory=dict)       # fqn → class_data
    files: Dict[str, dict] = field(default_factory=dict)         # file_path → file_data
    modules: Dict[str, List[str]] = field(default_factory=dict)  # module_path → [file_paths]

    # 边
    depends_on: List[DependsOnEdge] = field(default_factory=list)
    implements: List[ImplementsEdge] = field(default_factory=list)
    contains: List[ContainsEdge] = field(default_factory=list)

    # 预计算索引（供 fn_infer_layer 快速查询）
    in_degree: Dict[str, int] = field(default_factory=dict)       # fqn → 被依赖次数
    out_degree: Dict[str, int] = field(default_factory=dict)      # fqn → 依赖他人次数
    out_by_layer: Dict[str, Dict[str, int]] = field(default_factory=dict)  # fqn → {layer: count}

    # 统计
    stats: dict = field(default_factory=dict)

    def get_in_degree(self, fqn: str) -> int:
        return self.in_degree.get(fqn, 0)

    def get_dependents(self, fqn: str) -> List[str]:
        """返回所有依赖该类的类（被依赖方 → 调用方）。"""
        return [e.source_fqn for e in self.depends_on if e.target_fqn == fqn]

    def get_dependencies(self, fqn: str) -> List[str]:
        """返回该类依赖的所有类（调用方 → 被依赖方）。"""
        return [e.target_fqn for e in self.depends_on if e.source_fqn == fqn]

    def detect_cycles(self) -> List[List[str]]:
        """检测循环依赖（Tarjan SCC 算法简化版）。"""
        visited: Set[str] = set()
        rec_stack: Set[str] = set()
        cycles: List[List[str]] = []

        # 邻接表
        adj: Dict[str, List[str]] = defaultdict(list)
        for e in self.depends_on:
            adj[e.source_fqn].append(e.target_fqn)

        def dfs(node: str, path: List[str]) -> None:
            visited.add(node)
            rec_stack.add(node)
            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    dfs(neighbor, path + [neighbor])
                elif neighbor in rec_stack:
                    # 找到环，提取环路径
                    cycle_start = path.index(neighbor) if neighbor in path else 0
                    cycles.append(path[cycle_start:] + [neighbor])

            rec_stack.discard(node)

        for node in list(self.classes.keys()):
            if node not in visited:
                dfs(node, [node])

        return cycles[:10]  # 最多返回 10 个环，避免输出过多


# ─── 类名解析工具 ─────────────────────────────────────────────────────────────

def _build_name_to_fqn_index(ast_index: Dict[str, dict]) -> Dict[str, List[str]]:
    """
    构建 短类名 → [file_path::ClassName] 的反向索引。
    用于将 import 中的短类名解析为全限定名。
    """
    index: Dict[str, List[str]] = defaultdict(list)
    for file_path, file_data in ast_index.items():
        for cls in (file_data.get("classes") or []):
            name = cls.get("name", "")
            if name:
                fqn = f"{file_path}::{name}"
                index[name].append(fqn)
    return index


def _is_stdlib_or_third_party(import_name: str, lang: str) -> bool:
    """判断是否是标准库或第三方库（过滤掉，只保留项目内部依赖）。"""
    if lang == "python":
        stdlib_prefixes = [
            "os", "sys", "re", "json", "pathlib", "typing", "dataclasses",
            "collections", "itertools", "functools", "abc", "enum",
            "datetime", "time", "logging", "threading", "asyncio",
            "unittest", "io", "copy", "math", "random",
        ]
        third_party_prefixes = [
            "fastapi", "pydantic", "sqlalchemy", "django", "flask",
            "pytest", "httpx", "requests", "aiohttp", "celery",
            "redis", "kafka", "grpc", "boto3", "yaml", "structlog",
        ]
        lower = import_name.lower()
        return any(lower.startswith(p) for p in stdlib_prefixes + third_party_prefixes)

    elif lang == "java":
        return import_name.startswith(("java.", "javax.", "org.springframework",
                                       "org.hibernate", "com.fasterxml",
                                       "io.swagger", "lombok"))

    elif lang == "go":
        return "/" not in import_name or import_name.startswith("golang.org/")

    elif lang == "typescript":
        return import_name.startswith(("@angular/", "@nestjs/", "rxjs",
                                       "express", "lodash", "axios"))
    return False


# ─── fn_build_code_graph 实现 ─────────────────────────────────────────────────

def build_code_graph(
    ast_index: Dict[str, dict],
    project_root: Optional[Path] = None,
    filter_external: bool = True,
) -> CodeGraph:
    """
    从 ast_index.json 构建代码依赖图。

    实现 fn_build_code_graph Function。

    Args:
        ast_index:       build_ast_index() 的输出（{file_path: FileSkeleton dict}）
        project_root:    项目根目录（用于路径解析）
        filter_external: 是否过滤掉标准库/第三方依赖（默认 True）

    Returns:
        CodeGraph 对象
    """
    graph = CodeGraph()

    # Step 1: 建立名称索引
    name_to_fqn = _build_name_to_fqn_index(ast_index)

    # Step 2: 填充节点（CodeFile + CodeClass）
    for file_path, file_data in ast_index.items():
        lang = file_data.get("lang", "unknown")
        graph.files[file_path] = {
            "lang": lang,
            "package": file_data.get("package", ""),
            "imports": file_data.get("imports", []),
            "class_count": len(file_data.get("classes", [])),
        }

        # 模块聚合（按目录）
        module_path = str(Path(file_path).parent)
        if module_path not in graph.modules:
            graph.modules[module_path] = []
        graph.modules[module_path].append(file_path)

        # contains 边：模块 → 文件
        graph.contains.append(ContainsEdge(
            module_path=module_path,
            file_path=file_path,
        ))

        for cls in (file_data.get("classes") or []):
            name = cls.get("name", "")
            if not name:
                continue
            fqn = f"{file_path}::{name}"
            graph.classes[fqn] = {
                "name": name,
                "file_path": file_path,
                "lang": lang,
                "bases": cls.get("bases", []),
                "annotations": cls.get("annotations", []),
                "methods": cls.get("methods", []),
                "fingerprint": cls.get("fingerprint", ""),
            }

    # Step 3: 构建 depends_on 边（从 imports + 类使用分析）
    for file_path, file_data in ast_index.items():
        lang = file_data.get("lang", "unknown")
        imports = file_data.get("imports", [])
        file_classes = [cls.get("name", "") for cls in (file_data.get("classes") or [])]

        for imp_name in imports:
            if not imp_name or not imp_name[0].isupper():
                continue  # 只处理大写开头（类名）
            if filter_external and _is_stdlib_or_third_party(imp_name, lang):
                continue

            # 解析 import 名到 FQN
            candidate_fqns = name_to_fqn.get(imp_name, [])
            for candidate_fqn in candidate_fqns:
                target_file = candidate_fqn.split("::")[0]
                if target_file == file_path:
                    continue  # 跳过自引用

                # 为文件中每个类建立 depends_on 边
                for source_class in file_classes:
                    if not source_class:
                        continue
                    source_fqn = f"{file_path}::{source_class}"
                    graph.depends_on.append(DependsOnEdge(
                        source_fqn=source_fqn,
                        target_fqn=candidate_fqn,
                        source_file=file_path,
                        target_file=target_file,
                    ))

    # Step 4: 构建 implements 边（从 bases 字段）
    for fqn, cls_data in graph.classes.items():
        for base in (cls_data.get("bases") or []):
            if base and base != "object":
                graph.implements.append(ImplementsEdge(
                    source_fqn=fqn,
                    target_name=base,
                ))

    # Step 5: 计算 in_degree / out_degree
    for edge in graph.depends_on:
        graph.in_degree[edge.target_fqn] = graph.in_degree.get(edge.target_fqn, 0) + 1
        graph.out_degree[edge.source_fqn] = graph.out_degree.get(edge.source_fqn, 0) + 1

    # Step 6: 统计
    cycles = graph.detect_cycles()
    graph.stats = {
        "node_count":    len(graph.classes),
        "file_count":    len(graph.files),
        "module_count":  len(graph.modules),
        "edge_count":    len(graph.depends_on),
        "impl_count":    len(graph.implements),
        "cycle_count":   len(cycles),
        "avg_in_degree": (
            sum(graph.in_degree.values()) / len(graph.in_degree)
            if graph.in_degree else 0.0
        ),
        "max_in_degree": max(graph.in_degree.values()) if graph.in_degree else 0,
        "max_in_degree_class": max(graph.in_degree, key=lambda k: graph.in_degree[k])
            if graph.in_degree else "",
    }

    return graph
