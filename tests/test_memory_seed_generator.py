"""
tests/test_memory_seed_generator.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
memory_seed_generator 模块单元测试（14 用例）

覆盖范围：
  MG-01~04  标签与概念提取
  MG-05~07  Markdown 渲染正确性
  MG-08~14  generate_seed_memories 核心逻辑
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Dict, Tuple

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mms.bootstrap.memory_seed_generator import (
    GeneratorReport,
    _extract_about_concepts,
    _extract_tags,
    _render_memory_md,
    generate_seed_memories,
)
from mms.bootstrap.signal_fusion import LayerInference, ObjectTypeMapping, SignalBreakdown


# ─── 工具：构造推断结果 ───────────────────────────────────────────────────────

def _make_result(
    layer: str = "APP",
    confidence: float = 0.8,
    code_type: str = "Service",
    mem_type: str = "pattern",
    tier: str = "warm",
) -> Tuple[LayerInference, ObjectTypeMapping]:
    layer_inf = LayerInference(
        inferred_layer=layer,
        confidence=confidence,
        signal_breakdown=SignalBreakdown(),
        all_scores={layer: confidence},
    )
    obj_map = ObjectTypeMapping(
        code_object_type=code_type,
        memory_node_type=mem_type,
        suggested_tier=tier,
        suggested_layer=layer,
    )
    return layer_inf, obj_map


def _make_ast_index(fqn: str, methods: list = None, bases: list = None) -> dict:
    file_path, class_name = fqn.split("::")
    return {
        file_path: {
            "lang": "python",
            "classes": [{
                "name": class_name,
                "bases": bases or [],
                "annotations": [],
                "methods": methods or [],
                "fingerprint": "fp123",
            }],
            "imports": [],
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
# MG-01  CamelCase 拆解标签
# ─────────────────────────────────────────────────────────────────────────────
def test_mg01_extract_tags_camelcase_split():
    """UserOrderService → 拆分为 [user, order, service, ...]。"""
    tags = _extract_tags("UserOrderService", "APP", "Service")
    assert "user" in tags
    assert "order" in tags
    assert "service" in tags


# ─────────────────────────────────────────────────────────────────────────────
# MG-02  层级专属标签
# ─────────────────────────────────────────────────────────────────────────────
def test_mg02_extract_tags_layer_specific():
    """ADAPTER 层 → 结果含 rest-api。"""
    tags = _extract_tags("UserController", "ADAPTER", "Controller")
    assert "rest-api" in tags or "controller" in tags


# ─────────────────────────────────────────────────────────────────────────────
# MG-03  标签去重
# ─────────────────────────────────────────────────────────────────────────────
def test_mg03_extract_tags_dedup():
    """重复的 tag 被 set 去重，没有重复元素。"""
    tags = _extract_tags("ServiceService", "APP", "Service")
    assert len(tags) == len(set(tags))


# ─────────────────────────────────────────────────────────────────────────────
# MG-04  about_concepts 过滤短词
# ─────────────────────────────────────────────────────────────────────────────
def test_mg04_extract_about_concepts_min_len():
    """长度 <= 3 的词被过滤（如 'Id', 'By'）。"""
    concepts = _extract_about_concepts("UserById", "DOMAIN")
    for c in concepts:
        assert len(c) > 3, f"短词 '{c}' 不应出现在 about_concepts 中"


# ─────────────────────────────────────────────────────────────────────────────
# MG-05  渲染的 frontmatter 可被 yaml.safe_load 解析
# ─────────────────────────────────────────────────────────────────────────────
def test_mg05_render_memory_md_valid_frontmatter():
    """_render_memory_md 输出的 frontmatter 是合法 YAML。"""
    import yaml
    content = _render_memory_md(
        memory_id="MEM-BOOT-001",
        class_name="OrderService",
        file_path="src/service/order_service.py",
        layer="APP",
        tier="warm",
        code_type="Service",
        tags=["order", "service"],
        about_concepts=["order", "application-service"],
        fingerprint="fp123",
        methods=[{"name": "create", "signature": "(self, dto)", "is_async": False}],
        bases=[],
        annotations=[],
        layer_confidence=0.85,
    )
    # 提取 frontmatter（--- 之间的内容）
    parts = content.split("---")
    assert len(parts) >= 3
    fm = yaml.safe_load(parts[1])
    assert fm is not None
    assert isinstance(fm, dict)


# ─────────────────────────────────────────────────────────────────────────────
# MG-06  frontmatter 必填字段
# ─────────────────────────────────────────────────────────────────────────────
def test_mg06_render_memory_md_required_fields():
    """frontmatter 必须包含 id / type / layer / tier / tags。"""
    import yaml
    content = _render_memory_md(
        memory_id="MEM-BOOT-002",
        class_name="PaymentService",
        file_path="src/payment/payment_service.py",
        layer="APP",
        tier="warm",
        code_type="Service",
        tags=["payment", "service"],
        about_concepts=["payment"],
        fingerprint="",
        methods=[],
        bases=[],
        annotations=[],
        layer_confidence=0.9,
    )
    parts = content.split("---")
    fm = yaml.safe_load(parts[1])
    for field in ["id", "type", "layer", "tier", "tags"]:
        assert field in fm, f"frontmatter 缺少必填字段: {field}"


# ─────────────────────────────────────────────────────────────────────────────
# MG-07  方法列表展示上限 5 个，超出时显示省略提示
# ─────────────────────────────────────────────────────────────────────────────
def test_mg07_render_memory_md_method_limit():
    """超过 5 个方法时，正文显示 '...共 N 个方法'。"""
    methods = [
        {"name": f"method_{i}", "signature": "(self)", "is_async": False}
        for i in range(8)
    ]
    content = _render_memory_md(
        memory_id="MEM-BOOT-003",
        class_name="BigService",
        file_path="src/big_service.py",
        layer="APP",
        tier="warm",
        code_type="Service",
        tags=[],
        about_concepts=[],
        fingerprint="",
        methods=methods,
        bases=[],
        annotations=[],
        layer_confidence=0.7,
    )
    assert "共 8 个方法" in content


# ─────────────────────────────────────────────────────────────────────────────
# MG-08  置信度低于 min_confidence → 被跳过
# ─────────────────────────────────────────────────────────────────────────────
def test_mg08_generate_min_confidence_skip():
    """confidence=0.3 < min_confidence=0.5 → skipped 列表包含该类。"""
    fqn = "src/vague.py::VagueClass"
    results = {fqn: _make_result(layer="APP", confidence=0.3)}
    ast_index = _make_ast_index(fqn)

    with tempfile.TemporaryDirectory() as tmp:
        report = generate_seed_memories(
            inference_results=results,
            ast_index=ast_index,
            output_dir=Path(tmp),
            min_confidence=0.5,
            dry_run=True,
        )
    assert fqn in report.skipped
    assert report.total == 0


# ─────────────────────────────────────────────────────────────────────────────
# MG-09  每层上限控制
# ─────────────────────────────────────────────────────────────────────────────
def test_mg09_generate_max_per_layer_limit():
    """max_per_layer=1 时，同层第 2 个类被跳过。"""
    results = {
        "src/s1.py::Service1": _make_result(layer="APP", confidence=0.9),
        "src/s2.py::Service2": _make_result(layer="APP", confidence=0.85),
    }
    ast_index = {
        **_make_ast_index("src/s1.py::Service1"),
        **_make_ast_index("src/s2.py::Service2"),
    }
    with tempfile.TemporaryDirectory() as tmp:
        report = generate_seed_memories(
            inference_results=results,
            ast_index=ast_index,
            output_dir=Path(tmp),
            min_confidence=0.5,
            max_per_layer=1,
            dry_run=True,
        )
    assert report.total == 1
    assert len(report.skipped) == 1


# ─────────────────────────────────────────────────────────────────────────────
# MG-10  dry_run=True → 无文件写入，report 非空
# ─────────────────────────────────────────────────────────────────────────────
def test_mg10_generate_dry_run_no_files():
    """dry_run=True → 目录无新文件，但 report.generated 包含记录。"""
    fqn = "src/service.py::GoodService"
    results = {fqn: _make_result(layer="APP", confidence=0.9)}
    ast_index = _make_ast_index(fqn)

    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp) / "shared"
        report = generate_seed_memories(
            inference_results=results,
            ast_index=ast_index,
            output_dir=out_dir,
            min_confidence=0.5,
            dry_run=True,
        )
        # dry_run 时不写文件
        all_files = list(Path(tmp).rglob("*.md"))
        assert len(all_files) == 0
    assert report.total >= 1


# ─────────────────────────────────────────────────────────────────────────────
# MG-11  记忆 ID 序号递增
# ─────────────────────────────────────────────────────────────────────────────
def test_mg11_generate_memory_id_sequence():
    """生成的记忆 ID 从 MEM-BOOT-001 开始递增。"""
    results = {
        f"src/s{i}.py::Svc{i}": _make_result(layer="APP", confidence=0.9)
        for i in range(3)
    }
    ast_index = {}
    for i in range(3):
        ast_index.update(_make_ast_index(f"src/s{i}.py::Svc{i}"))

    with tempfile.TemporaryDirectory() as tmp:
        report = generate_seed_memories(
            inference_results=results,
            ast_index=ast_index,
            output_dir=Path(tmp),
            min_confidence=0.5,
            dry_run=True,
        )

    ids = [m.memory_id for m in report.generated]
    assert "MEM-BOOT-001" in ids
    assert "MEM-BOOT-002" in ids
    assert "MEM-BOOT-003" in ids


# ─────────────────────────────────────────────────────────────────────────────
# MG-12  memory_node_type="skip" 的类被跳过
# ─────────────────────────────────────────────────────────────────────────────
def test_mg12_generate_skip_memory_node_type():
    """memory_node_type=skip → 不生成记忆文件。"""
    fqn = "src/utils.py::SomeUtil"
    results = {fqn: _make_result(layer="CC", confidence=0.8, code_type="Util", mem_type="skip")}
    ast_index = _make_ast_index(fqn)

    with tempfile.TemporaryDirectory() as tmp:
        report = generate_seed_memories(
            inference_results=results,
            ast_index=ast_index,
            output_dir=Path(tmp),
            min_confidence=0.5,
            dry_run=True,
        )
    assert fqn in report.skipped
    assert report.total == 0


# ─────────────────────────────────────────────────────────────────────────────
# MG-13  layer_distribution 正确统计
# ─────────────────────────────────────────────────────────────────────────────
def test_mg13_generate_layer_distribution():
    """2 个 ADAPTER + 1 个 DOMAIN → layer_distribution 正确。"""
    results = {
        "src/c1.py::Controller1": _make_result(layer="ADAPTER", confidence=0.9, code_type="Controller", mem_type="pattern"),
        "src/c2.py::Controller2": _make_result(layer="ADAPTER", confidence=0.85, code_type="Controller", mem_type="pattern"),
        "src/r1.py::Repo1": _make_result(layer="DOMAIN", confidence=0.9, code_type="Repository", mem_type="pattern"),
    }
    ast_index = {}
    for fqn in results:
        ast_index.update(_make_ast_index(fqn))

    with tempfile.TemporaryDirectory() as tmp:
        report = generate_seed_memories(
            inference_results=results,
            ast_index=ast_index,
            output_dir=Path(tmp),
            min_confidence=0.5,
            max_per_layer=10,
            dry_run=True,
        )
    assert report.layer_distribution.get("ADAPTER", 0) == 2
    assert report.layer_distribution.get("DOMAIN", 0) == 1


# ─────────────────────────────────────────────────────────────────────────────
# MG-14  report.total == len(report.generated)
# ─────────────────────────────────────────────────────────────────────────────
def test_mg14_generate_report_total_property():
    """`report.total` 等于 `len(report.generated)`。"""
    results = {
        "src/svc.py::MyService": _make_result(layer="APP", confidence=0.9),
    }
    ast_index = _make_ast_index("src/svc.py::MyService")

    with tempfile.TemporaryDirectory() as tmp:
        report = generate_seed_memories(
            inference_results=results,
            ast_index=ast_index,
            output_dir=Path(tmp),
            dry_run=True,
        )
    assert report.total == len(report.generated)
