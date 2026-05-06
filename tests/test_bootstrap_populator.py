"""
tests/test_bootstrap_populator.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ontology_populator (bootstrap_project) 单元测试（12 用例）

覆盖范围：
  BP-01~04  skip_* 标志组合
  BP-05     dry_run 文件不写入
  BP-06     错误积累不崩溃
  BP-07     报告字段基本完整性
  BP-08~10  _absorb_project_docs 分支
  BP-11     空项目不崩溃
  BP-12     print_summary 任意字段不抛异常
"""
from __future__ import annotations

import sys
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mms.bootstrap.ontology_populator import (
    BootstrapV2Report,
    _absorb_project_docs,
    bootstrap_project,
)


# ─────────────────────────────────────────────────────────────────────────────
# BP-01  skip_ast=True → 步骤 3-6 跳过，报告有效
# ─────────────────────────────────────────────────────────────────────────────
def test_bp01_skip_ast_returns_early():
    """skip_ast=True 时，Bootstrap 提前返回，report 结构完整。"""
    with tempfile.TemporaryDirectory() as tmp:
        report = bootstrap_project(
            project_root=Path(tmp),
            dry_run=True,
            skip_ast=True,
            skip_doc_absorb=True,
            verbose=False,
        )
    assert isinstance(report, BootstrapV2Report)
    assert report.files_scanned == 0      # 未扫描
    assert report.classes_found == 0
    assert report.elapsed_s > 0


# ─────────────────────────────────────────────────────────────────────────────
# BP-02  skip_seeds=True → injected_seed_packs 为空列表
# ─────────────────────────────────────────────────────────────────────────────
def test_bp02_skip_seeds_no_injection():
    """skip_seeds=True → 不调用 install_packs，injected_seed_packs=[]。"""
    with tempfile.TemporaryDirectory() as tmp:
        report = bootstrap_project(
            project_root=Path(tmp),
            dry_run=True,
            skip_ast=True,
            skip_seeds=True,
            skip_doc_absorb=True,
            verbose=False,
        )
    assert report.injected_seed_packs == []


# ─────────────────────────────────────────────────────────────────────────────
# BP-03  skip_memory_gen=True → memories_generated=0
# ─────────────────────────────────────────────────────────────────────────────
def test_bp03_skip_memory_gen():
    """skip_memory_gen=True → 不生成任何记忆文件。"""
    with tempfile.TemporaryDirectory() as tmp:
        report = bootstrap_project(
            project_root=Path(tmp),
            dry_run=True,
            skip_memory_gen=True,
            skip_doc_absorb=True,
            verbose=False,
        )
    assert report.memories_generated == 0


# ─────────────────────────────────────────────────────────────────────────────
# BP-04  skip_doc_absorb=True → absorbed_docs 不被填充（或为 []）
# ─────────────────────────────────────────────────────────────────────────────
def test_bp04_skip_doc_absorb():
    """skip_doc_absorb=True → _absorb_project_docs 不被调用。"""
    with tempfile.TemporaryDirectory() as tmp:
        with patch("mms.bootstrap.ontology_populator._absorb_project_docs") as mock_absorb:
            bootstrap_project(
                project_root=Path(tmp),
                dry_run=True,
                skip_ast=True,
                skip_doc_absorb=True,
                verbose=False,
            )
        mock_absorb.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# BP-05  dry_run=True → docs/ 目录无新 .md 写入
# ─────────────────────────────────────────────────────────────────────────────
def test_bp05_dry_run_no_files_written():
    """dry_run=True 时，不写入任何 MEM-BOOT-*.md 文件。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # 创建最简单的 Python 文件供 AST 扫描
        src = root / "src"
        src.mkdir()
        (src / "sample.py").write_text("class SampleService:\n    pass\n")

        report = bootstrap_project(
            project_root=root,
            dry_run=True,
            skip_doc_absorb=True,
            verbose=False,
        )
        md_files = list(root.rglob("MEM-BOOT-*.md"))
    assert len(md_files) == 0


# ─────────────────────────────────────────────────────────────────────────────
# BP-06  内部步骤抛异常 → 错误被积累到 report.errors，不崩溃
# ─────────────────────────────────────────────────────────────────────────────
def test_bp06_error_accumulation_no_crash():
    """即使内部步骤失败，bootstrap_project 也不应抛出异常，而是将错误积累到 errors。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # 创建一个损坏的 pyproject.toml 来干扰嗅探（但不致命）
        (root / "pyproject.toml").write_text("invalid toml content [[[\n")

        report = bootstrap_project(
            project_root=root,
            dry_run=True,
            skip_doc_absorb=True,
            verbose=False,
        )
    # 即使有错误，也不应崩溃
    assert isinstance(report, BootstrapV2Report)
    assert isinstance(report.errors, list)
    assert isinstance(report.elapsed_s, float)


# ─────────────────────────────────────────────────────────────────────────────
# BP-07  报告基础字段完整性
# ─────────────────────────────────────────────────────────────────────────────
def test_bp07_report_fields_basic():
    """report 必须包含 elapsed_s / detected_stacks / dry_run / errors。"""
    with tempfile.TemporaryDirectory() as tmp:
        report = bootstrap_project(
            project_root=Path(tmp),
            dry_run=True,
            skip_ast=True,
            skip_doc_absorb=True,
            verbose=False,
        )
    assert hasattr(report, "elapsed_s")
    assert hasattr(report, "detected_stacks")
    assert hasattr(report, "dry_run")
    assert hasattr(report, "errors")
    assert report.dry_run is True
    assert report.elapsed_s >= 0.0
    assert isinstance(report.detected_stacks, list)


# ─────────────────────────────────────────────────────────────────────────────
# BP-08  _absorb_project_docs：项目根无特征文件 → 返回 []
# ─────────────────────────────────────────────────────────────────────────────
def test_bp08_absorb_docs_no_candidates():
    """空项目目录无特征文件 → _absorb_project_docs 返回空列表。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        log_calls = []
        result = _absorb_project_docs(root=root, dry_run=True, log=log_calls.append)
    assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# BP-09  _absorb_project_docs：seed_absorber 不可 import → 静默跳过
# ─────────────────────────────────────────────────────────────────────────────
def test_bp09_absorb_docs_import_error():
    """seed_absorber ImportError → 静默返回 []，不崩溃。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # 创建 CONTRIBUTING.md 使得特征文件存在
        (root / "CONTRIBUTING.md").write_text("# Contribution Guide\n")

        log_calls = []
        # patch absorb import 为失败
        with patch.dict("sys.modules", {"mms.analysis.seed_absorber": None}):
            result = _absorb_project_docs(root=root, dry_run=True, log=log_calls.append)

    assert isinstance(result, list)
    # 应该有日志提示跳过
    assert any("跳过" in msg or "seed_absorber" in msg for msg in log_calls)


# ─────────────────────────────────────────────────────────────────────────────
# BP-10  _absorb_project_docs：absorb 抛 API key 异常 → 静默跳过，不进 errors
# ─────────────────────────────────────────────────────────────────────────────
def test_bp10_absorb_docs_api_key_error():
    """absorb 抛含 'API key' 的异常 → 静默跳过。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "CONTRIBUTING.md").write_text("# Guide\n")

        log_calls = []
        mock_absorb_module = MagicMock()
        mock_absorb_module.absorb.side_effect = Exception("API key not configured")

        with patch.dict("sys.modules", {"mms.analysis.seed_absorber": mock_absorb_module}):
            result = _absorb_project_docs(root=root, dry_run=True, log=log_calls.append)

    # API key 错误静默跳过，不崩溃
    assert isinstance(result, list)
    # 日志中应有 API Key 相关跳过提示
    skip_logged = any("跳过" in m or "API" in m or "api" in m.lower() for m in log_calls)
    assert skip_logged


# ─────────────────────────────────────────────────────────────────────────────
# BP-11  空项目目录不崩溃
# ─────────────────────────────────────────────────────────────────────────────
def test_bp11_bootstrap_empty_project():
    """对空临时目录运行完整 bootstrap → exit 正常，不抛 Exception。"""
    with tempfile.TemporaryDirectory() as tmp:
        report = bootstrap_project(
            project_root=Path(tmp),
            dry_run=True,
            skip_doc_absorb=True,
            verbose=False,
        )
    assert isinstance(report, BootstrapV2Report)
    # 空项目 files_scanned 可能为 0，不要求生成记忆
    assert report.files_scanned >= 0


# ─────────────────────────────────────────────────────────────────────────────
# BP-12  print_summary 对任意字段组合不抛异常
# ─────────────────────────────────────────────────────────────────────────────
def test_bp12_print_summary_no_exception():
    """各种字段组合下 print_summary() 不应抛任何异常。"""
    import io
    import contextlib

    cases = [
        BootstrapV2Report(),  # 全默认
        BootstrapV2Report(
            elapsed_s=1.5,
            detected_stacks=["spring_boot", "fastapi_sqlmodel"],
            stack_confidence=0.87,
            injected_seed_packs=["spring_boot"],
            files_scanned=120,
            classes_found=80,
            methods_found=350,
            graph_nodes=80,
            graph_edges=150,
            cycle_count=2,
            classes_inferred=20,
            classes_skipped=60,
            layer_distribution={"ADAPTER": 5, "APP": 8, "DOMAIN": 7},
            memories_generated=15,
            memories_per_layer={"ADAPTER": 5, "APP": 8, "DOMAIN": 2},
            dry_run=True,
            errors=["step 3 failed", "step 5 failed"],
        ),
        BootstrapV2Report(dry_run=False, errors=[]),
    ]
    for report in cases:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            report.print_summary()  # 不应抛异常
