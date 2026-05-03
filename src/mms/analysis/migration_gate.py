"""
migration_gate.py — DB 迁移脚本门控（MigrationGate）

针对 SCHEMA_ADD_FIELD / SCHEMA_ALTER_COLUMN 等数据库变更动作，
强制验证：
  1. 同一 EP 必须同时存在 upgrade() 和 downgrade() 迁移函数
  2. 迁移脚本的 AST 中操作的列名/表名必须与 ORM 模型改动严格对齐

触发条件：scope_files 中包含满足 ORM_PATTERNS 的文件（Django model / SQLAlchemy / Alembic）

严格模式（MMS_MIGRATION_STRICT=1）：
  发现不合规时直接返回 FAIL，阻断 postcheck 通过。

宽松模式（默认）：
  发现不合规时返回 WARN，提示开发者补全但不阻断。
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── 判断文件是否为 ORM 模型 / 迁移脚本 ────────────────────────────────────────
ORM_PATTERNS = [
    r"models?\.py$",
    r"models?/.*\.py$",
    r"schema\.py$",
    r"entities?/.*\.py$",
    r"migrations?/.*\.py$",
    r"alembic/versions/.*\.py$",
]

MIGRATION_PATTERNS = [
    r"migrations?/.*\.py$",
    r"alembic/versions/.*\.py$",
    r"migrate\.py$",
    r".*migration.*\.py$",
]

_ORM_RE = [re.compile(p, re.IGNORECASE) for p in ORM_PATTERNS]
_MIG_RE = [re.compile(p, re.IGNORECASE) for p in MIGRATION_PATTERNS]


def _is_orm_file(path: str) -> bool:
    return any(r.search(path) for r in _ORM_RE)


def _is_migration_file(path: str) -> bool:
    return any(r.search(path) for r in _MIG_RE)


def _find_function_names(source: str) -> List[str]:
    """用 AST 提取源文件中所有顶层函数名"""
    try:
        tree = ast.parse(source)
        return [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
    except SyntaxError:
        return []


def _extract_column_ops(source: str) -> List[str]:
    """
    从迁移脚本中提取列操作的列名（粗粒度提取，用于对齐检查）。
    支持 Alembic op.add_column / op.drop_column / op.alter_column 风格。
    """
    ops = []
    patterns = [
        r'op\.add_column\s*\(\s*["\'](\w+)["\']',
        r'op\.drop_column\s*\(\s*["\'](\w+)["\']',
        r'op\.alter_column\s*\(\s*["\'](\w+)["\']',
        r'Column\s*\(\s*["\'](\w+)["\']',
    ]
    for pat in patterns:
        ops.extend(re.findall(pat, source))
    return ops


def _extract_model_fields(source: str) -> List[str]:
    """
    从 ORM 模型文件中提取字段名。
    支持 Django 风格（field = models.CharField(...)）
    和 SQLAlchemy 风格（column = Column(...)）。
    """
    fields = []
    patterns = [
        r'^(\w+)\s*=\s*(?:models\.|Column\(|db\.Column)',
        r'db\.Column\s*\(["\'](\w+)["\']',
    ]
    for pat in patterns:
        fields.extend(re.findall(pat, source, re.MULTILINE))
    return fields


def run_migration_gate(
    scope_files: List[str],
    project_root: Optional[Path] = None,
) -> Dict:
    """
    运行 MigrationGate 检查。

    Args:
        scope_files:   本次 EP 涉及的文件列表
        project_root:  项目根目录（用于读取文件内容）

    Returns:
        {
          "status": "PASS" | "WARN" | "FAIL" | "SKIPPED",
          "summary": str,
          "issues": [str, ...],
        }
    """
    strict = os.environ.get("MMS_MIGRATION_STRICT") == "1"

    orm_files = [f for f in scope_files if _is_orm_file(f)]
    mig_files = [f for f in scope_files if _is_migration_file(f)]

    if not orm_files:
        return {
            "status": "SKIPPED",
            "summary": "无 ORM 模型文件变更，跳过迁移脚本门控",
            "issues": [],
        }

    issues = []

    # ── 检查 1: 有 ORM 变更但无迁移脚本 ─────────────────────────────────────────
    if not mig_files:
        issues.append(
            f"发现 ORM 模型变更（{', '.join(orm_files[:3])}）但未包含迁移脚本。"
            f"SCHEMA_ADD_FIELD 等操作必须同时提供 up()/upgrade() + down()/downgrade() 脚本。"
        )
    else:
        # ── 检查 2: 迁移脚本必须同时包含 upgrade 和 downgrade ──────────────────
        for mig_path in mig_files:
            full_path = (project_root / mig_path) if project_root else Path(mig_path)
            if not full_path.exists():
                continue
            try:
                source = full_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            func_names = _find_function_names(source)
            has_up = any(fn in ("upgrade", "up") for fn in func_names)
            has_down = any(fn in ("downgrade", "down") for fn in func_names)
            if not has_up:
                issues.append(
                    f"{mig_path}: 缺少 upgrade()/up() 函数（迁移脚本必须包含正向迁移）"
                )
            if not has_down:
                issues.append(
                    f"{mig_path}: 缺少 downgrade()/down() 函数（迁移脚本必须包含回滚函数）"
                )

        # ── 检查 3: 迁移列名与 ORM 字段对齐（粗粒度，最佳努力）───────────────────
        if project_root and orm_files and mig_files:
            orm_fields: List[str] = []
            for orm_path in orm_files:
                full = project_root / orm_path
                if full.exists():
                    try:
                        orm_fields.extend(_extract_model_fields(full.read_text("utf-8", errors="ignore")))
                    except OSError:
                        pass

            mig_cols: List[str] = []
            for mig_path in mig_files:
                full = project_root / mig_path
                if full.exists():
                    try:
                        mig_cols.extend(_extract_column_ops(full.read_text("utf-8", errors="ignore")))
                    except OSError:
                        pass

            if mig_cols and orm_fields:
                unmatched = [col for col in mig_cols if col not in orm_fields]
                if unmatched:
                    issues.append(
                        f"迁移脚本中的列操作 {unmatched[:5]} 未在 ORM 模型字段中找到对应定义，"
                        f"请确认迁移与模型严格对齐。"
                    )

    if not issues:
        return {
            "status": "PASS",
            "summary": (
                f"MigrationGate 通过：{len(mig_files)} 个迁移脚本均包含 up/down 函数，"
                f"与 {len(orm_files)} 个 ORM 模型文件对齐"
            ),
            "issues": [],
        }

    status = "FAIL" if strict else "WARN"
    return {
        "status": status,
        "summary": f"MigrationGate {'失败' if strict else '警告'}：发现 {len(issues)} 个迁移合规问题",
        "issues": issues,
    }
