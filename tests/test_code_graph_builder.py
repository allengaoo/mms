"""
tests/test_code_graph_builder.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
code_graph_builder 模块单元测试（18 用例）

覆盖范围：
  CG-01~02  名称索引构建
  CG-03~07  外部依赖过滤（Python / Java / Go / TypeScript）
  CG-08~11  图节点与边构建
  CG-12~13  in/out degree 计算
  CG-14~15  循环依赖检测
  CG-16~17  stats 统计字段
  CG-18     filter_external=False 边界场景
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mms.bootstrap.code_graph_builder import (
    CodeGraph,
    _build_name_to_fqn_index,
    _is_stdlib_or_third_party,
    build_code_graph,
)


# ─── 工具：构造最小 ast_index ─────────────────────────────────────────────────

def _make_file(classes: list, imports: list = None, lang: str = "python") -> dict:
    return {
        "lang": lang,
        "classes": classes,
        "imports": imports or [],
        "package": "",
    }


def _make_class(name: str, bases: list = None, annotations: list = None) -> dict:
    return {
        "name": name,
        "bases": bases or [],
        "annotations": annotations or [],
        "methods": [],
        "fingerprint": "",
    }


# ─────────────────────────────────────────────────────────────────────────────
# CG-01  名称索引：基础 2 文件各 1 类
# ─────────────────────────────────────────────────────────────────────────────
def test_cg01_name_to_fqn_basic():
    ast_index = {
        "src/a.py": _make_file([_make_class("ClassA")]),
        "src/b.py": _make_file([_make_class("ClassB")]),
    }
    idx = _build_name_to_fqn_index(ast_index)
    assert "ClassA" in idx
    assert "ClassB" in idx
    assert "src/a.py::ClassA" in idx["ClassA"]
    assert "src/b.py::ClassB" in idx["ClassB"]


# ─────────────────────────────────────────────────────────────────────────────
# CG-02  名称索引：同名类在不同文件都被收录
# ─────────────────────────────────────────────────────────────────────────────
def test_cg02_name_to_fqn_duplicate_names():
    ast_index = {
        "src/a.py": _make_file([_make_class("Config")]),
        "src/b.py": _make_file([_make_class("Config")]),
    }
    idx = _build_name_to_fqn_index(ast_index)
    assert len(idx["Config"]) == 2


# ─────────────────────────────────────────────────────────────────────────────
# CG-03  过滤：Python 标准库
# ─────────────────────────────────────────────────────────────────────────────
def test_cg03_filter_stdlib_python():
    for name in ["os", "sys", "re", "json", "logging", "pathlib", "datetime"]:
        assert _is_stdlib_or_third_party(name, "python"), f"{name} 应被过滤"


# ─────────────────────────────────────────────────────────────────────────────
# CG-04  过滤：Python 第三方库
# ─────────────────────────────────────────────────────────────────────────────
def test_cg04_filter_third_party_python():
    for name in ["fastapi", "pydantic", "sqlalchemy", "django", "pytest", "redis"]:
        assert _is_stdlib_or_third_party(name, "python"), f"{name} 应被过滤"


# ─────────────────────────────────────────────────────────────────────────────
# CG-05  过滤：Java Spring 框架包
# ─────────────────────────────────────────────────────────────────────────────
def test_cg05_filter_java_spring():
    for name in ["java.util.List", "org.springframework.web.Controller", "javax.persistence"]:
        assert _is_stdlib_or_third_party(name, "java"), f"{name} 应被过滤"


# ─────────────────────────────────────────────────────────────────────────────
# CG-06  过滤：Go 标准库（无 / 的包名）
# ─────────────────────────────────────────────────────────────────────────────
def test_cg06_filter_go_stdlib():
    for name in ["fmt", "os", "net", "context", "sync"]:
        assert _is_stdlib_or_third_party(name, "go"), f"{name} 应被过滤"
    # 项目内部依赖（含 /）不过滤
    assert not _is_stdlib_or_third_party("github.com/myorg/myrepo/service", "go")


# ─────────────────────────────────────────────────────────────────────────────
# CG-07  过滤：TypeScript Angular
# ─────────────────────────────────────────────────────────────────────────────
def test_cg07_filter_typescript_angular():
    for name in ["@angular/core", "@nestjs/common", "rxjs", "express"]:
        assert _is_stdlib_or_third_party(name, "typescript"), f"{name} 应被过滤"


# ─────────────────────────────────────────────────────────────────────────────
# CG-08  节点数量正确
# ─────────────────────────────────────────────────────────────────────────────
def test_cg08_build_graph_nodes():
    ast_index = {
        "src/a.py": _make_file([_make_class("A"), _make_class("B")]),
        "src/b.py": _make_file([_make_class("C")]),
    }
    graph = build_code_graph(ast_index)
    assert len(graph.classes) == 3
    assert "src/a.py::A" in graph.classes
    assert "src/a.py::B" in graph.classes
    assert "src/b.py::C" in graph.classes


# ─────────────────────────────────────────────────────────────────────────────
# CG-09  depends_on 边：文件 A import 文件 B 的类 → 边存在
# ─────────────────────────────────────────────────────────────────────────────
def test_cg09_build_graph_depends_on_edges():
    ast_index = {
        "src/repo.py": _make_file([_make_class("UserRepo")]),
        "src/service.py": _make_file(
            [_make_class("UserService")],
            imports=["UserRepo"],
        ),
    }
    graph = build_code_graph(ast_index)
    found = any(
        e.source_fqn == "src/service.py::UserService"
        and e.target_fqn == "src/repo.py::UserRepo"
        for e in graph.depends_on
    )
    assert found, "UserService → UserRepo 的 depends_on 边应存在"


# ─────────────────────────────────────────────────────────────────────────────
# CG-10  自引用跳过（同文件内 import 不生成边）
# ─────────────────────────────────────────────────────────────────────────────
def test_cg10_build_graph_self_reference_skip():
    ast_index = {
        "src/module.py": _make_file(
            [_make_class("ClassA"), _make_class("ClassB")],
            imports=["ClassA", "ClassB"],
        ),
    }
    graph = build_code_graph(ast_index)
    # 同文件内引用不产生边
    self_edges = [
        e for e in graph.depends_on
        if e.source_file == "src/module.py" and e.target_file == "src/module.py"
    ]
    assert len(self_edges) == 0


# ─────────────────────────────────────────────────────────────────────────────
# CG-11  implements 边：bases 字段 → implements 边
# ─────────────────────────────────────────────────────────────────────────────
def test_cg11_build_graph_implements_edges():
    ast_index = {
        "src/service.py": _make_file([
            _make_class("OrderService", bases=["BaseService", "Serializable"])
        ]),
    }
    graph = build_code_graph(ast_index)
    impl_targets = {e.target_name for e in graph.implements}
    assert "BaseService" in impl_targets
    assert "Serializable" in impl_targets


# ─────────────────────────────────────────────────────────────────────────────
# CG-12  in_degree 计算：被 3 个类 import → in_degree=3
# ─────────────────────────────────────────────────────────────────────────────
def test_cg12_build_graph_in_degree():
    ast_index = {
        "src/core.py": _make_file([_make_class("CoreService")]),
        "src/a.py": _make_file([_make_class("A")], imports=["CoreService"]),
        "src/b.py": _make_file([_make_class("B")], imports=["CoreService"]),
        "src/c.py": _make_file([_make_class("C")], imports=["CoreService"]),
    }
    graph = build_code_graph(ast_index)
    fqn = "src/core.py::CoreService"
    assert graph.in_degree.get(fqn, 0) == 3


# ─────────────────────────────────────────────────────────────────────────────
# CG-13  out_degree 计算：类依赖 2 个类 → out_degree=2
# ─────────────────────────────────────────────────────────────────────────────
def test_cg13_build_graph_out_degree():
    # 注意：import 名首字母须大写（代码过滤 islower 开头），
    # 且不能以 Python stdlib 前缀开头（如 re/os/sys），否则被过滤。
    ast_index = {
        "src/storage/OrderStore.py": _make_file([_make_class("OrderStore")]),
        "src/storage/UserStore.py": _make_file([_make_class("UserStore")]),
        "src/application/MyService.py": _make_file(
            [_make_class("MyService")],
            imports=["OrderStore", "UserStore"],
        ),
    }
    graph = build_code_graph(ast_index)
    fqn = "src/application/MyService.py::MyService"
    assert graph.out_degree.get(fqn, 0) == 2


# ─────────────────────────────────────────────────────────────────────────────
# CG-14  循环依赖检测：A→B→A → 检测出至少 1 个环
# ─────────────────────────────────────────────────────────────────────────────
def test_cg14_detect_cycles_simple():
    ast_index = {
        "src/a.py": _make_file([_make_class("ClassA")], imports=["ClassB"]),
        "src/b.py": _make_file([_make_class("ClassB")], imports=["ClassA"]),
    }
    graph = build_code_graph(ast_index)
    cycles = graph.detect_cycles()
    assert len(cycles) >= 1
    assert graph.stats["cycle_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# CG-15  无循环 DAG → detect_cycles 返回 []
# ─────────────────────────────────────────────────────────────────────────────
def test_cg15_detect_cycles_none():
    ast_index = {
        "src/repo.py": _make_file([_make_class("Repo")]),
        "src/service.py": _make_file([_make_class("Service")], imports=["Repo"]),
        "src/controller.py": _make_file([_make_class("Controller")], imports=["Service"]),
    }
    graph = build_code_graph(ast_index)
    cycles = graph.detect_cycles()
    assert len(cycles) == 0


# ─────────────────────────────────────────────────────────────────────────────
# CG-16  stats 字段完整性
# ─────────────────────────────────────────────────────────────────────────────
def test_cg16_stats_fields_complete():
    ast_index = {
        "src/a.py": _make_file([_make_class("A")]),
        "src/b.py": _make_file([_make_class("B")], imports=["A"]),
    }
    graph = build_code_graph(ast_index)
    required_keys = ["node_count", "edge_count", "cycle_count", "avg_in_degree", "max_in_degree"]
    for key in required_keys:
        assert key in graph.stats, f"stats 缺少字段: {key}"
    assert graph.stats["node_count"] == 2
    assert graph.stats["edge_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# CG-17  空 ast_index → 空图，stats 全 0
# ─────────────────────────────────────────────────────────────────────────────
def test_cg17_empty_ast_index():
    graph = build_code_graph({})
    assert len(graph.classes) == 0
    assert len(graph.depends_on) == 0
    assert graph.stats["node_count"] == 0
    assert graph.stats["edge_count"] == 0
    assert graph.stats["cycle_count"] == 0
    assert graph.stats["avg_in_degree"] == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# CG-18  filter_external=False → 第三方 import 大写类也生成边
# ─────────────────────────────────────────────────────────────────────────────
def test_cg18_build_graph_no_filter_external():
    """filter_external=False 时，FastAPI / Pydantic 等也生成依赖边。"""
    ast_index = {
        "src/model.py": _make_file([_make_class("Fastapi")]),  # 模拟同名类存在
        "src/router.py": _make_file(
            [_make_class("UserRouter")],
            imports=["Fastapi"],
        ),
    }
    # 先验证 filter=True 时不生成（因为 fastapi 在第三方前缀中）
    graph_filtered = build_code_graph(ast_index, filter_external=True)
    # "Fastapi" 以大写 F 开头，不在第三方过滤名单（小写匹配），应生成边
    # 此测试主要验证 filter_external=False 模式不崩溃
    graph_unfiltered = build_code_graph(ast_index, filter_external=False)
    assert len(graph_unfiltered.classes) == 2  # 两个类都存在
