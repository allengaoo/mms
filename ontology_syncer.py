"""
ontology_syncer.py — 本体语义漂移修补器（EP-130）

根据 AstDiffResult 自动修补 Ontology YAML 文件，
防止代码变更后本体定义与实现脱节（Semantic Drift）。

修补策略（保守原则）：
  ✅ 自动处理（低风险）：
     - 新增 Class 字段 → 在对应 ObjectDef.properties 中追加新 property
     - fingerprint 更新 → 更新 ast_pointer.fingerprint

  ⚠️ 只告警，不自动修改（高风险）：
     - 方法签名变更 → 标记 ast_pointer.drift=true
     - 删除 Class/Method → 标记对应 ObjectDef/ActionDef 为 STALE

禁止自动修改：
  - ObjectDef.constraints（影响全局约束）
  - ObjectDef.lifecycle（影响状态机）
  - ActionDef.inputs/outputs（影响调用方）
  - 任何 required: true 的字段

EP-130 | 2026-04-18
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

_HERE = Path(__file__).resolve().parent
try:
    from _paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE.parent.parent
_ONTOLOGY_DIR = _ROOT / "docs" / "memory" / "ontology"

_logger = logging.getLogger(__name__)

try:
    sys.path.insert(0, str(_HERE))
    from ast_diff import AstDiffResult, ChangeKind, ContractChange
except ImportError:
    _logger.warning("ast_diff 未找到，ontology_syncer 将无法工作")
    AstDiffResult = None  # type: ignore[misc,assignment]
    ChangeKind = None  # type: ignore[misc,assignment]
    ContractChange = None  # type: ignore[misc,assignment]

try:
    import yaml  # type: ignore[import]
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


# ── 数据结构 ─────────────────────────────────────────────────────────────────

@dataclass
class SyncAction:
    """单条同步动作记录。"""
    kind: str         # "auto_patched" | "drift_marked" | "stale_marked" | "skipped"
    file_path: str    # Ontology YAML 文件路径
    description: str
    change: Optional[object] = None   # 关联的 ContractChange


@dataclass
class SyncReport:
    """本体同步报告。"""
    actions: List[SyncAction] = field(default_factory=list)
    patched_files: List[str] = field(default_factory=list)
    drift_warnings: List[str] = field(default_factory=list)
    stale_warnings: List[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = ["=== Ontology Sync Report ==="]
        if not self.actions:
            lines.append("无需同步（无契约变更影响本体绑定）")
            return "\n".join(lines)
        for a in self.actions:
            prefix = "✅" if a.kind == "auto_patched" else "⚠️"
            lines.append(f"  {prefix} [{a.kind}] {a.description}")
        if self.drift_warnings:
            lines.append("\n漂移告警（需人工确认）：")
            for w in self.drift_warnings:
                lines.append(f"  ⚠️  {w}")
        if self.stale_warnings:
            lines.append("\nSTALE 告警（本体定义可能已过时）：")
            for w in self.stale_warnings:
                lines.append(f"  🔴 {w}")
        return "\n".join(lines)


# ── YAML 读写工具 ─────────────────────────────────────────────────────────────

def _load_yaml(path: Path) -> Optional[dict]:
    """加载 YAML 文件，失败返回 None。"""
    if not path.exists() or not _HAS_YAML:
        return None
    try:
        content = path.read_text(encoding="utf-8")
        return yaml.safe_load(content) or {}
    except Exception as e:
        _logger.debug("加载 YAML 失败 %s: %s", path, e)
        return None


def _save_yaml(path: Path, data: dict) -> bool:
    """保存 YAML 文件，失败返回 False。"""
    if not _HAS_YAML:
        return False
    try:
        content = yaml.dump(
            data,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
            indent=2,
        )
        path.write_text(content, encoding="utf-8")
        return True
    except Exception as e:
        _logger.warning("保存 YAML 失败 %s: %s", path, e)
        return False


# ── Ontology YAML 扫描 ────────────────────────────────────────────────────────

def _find_ontology_files_with_ast_pointer(ontology_dir: Path) -> Dict[str, Path]:
    """
    扫描本体目录，找到所有包含 ast_pointer.file_path 字段的 YAML 文件。
    返回 {implementation_file_path: yaml_path} 映射。
    """
    bindings: Dict[str, Path] = {}
    if not ontology_dir.exists() or not _HAS_YAML:
        return bindings

    for yaml_path in ontology_dir.rglob("*.yaml"):
        data = _load_yaml(yaml_path)
        if not data:
            continue
        ast_pointer = data.get("ast_pointer") or {}
        impl_file = ast_pointer.get("file_path", "")
        if impl_file:
            bindings[impl_file] = yaml_path

    return bindings


# ── 自动修补：更新 fingerprint ────────────────────────────────────────────────

def _update_fingerprint(yaml_path: Path, new_fingerprint: str) -> bool:
    """更新 YAML 中的 ast_pointer.fingerprint 字段。"""
    data = _load_yaml(yaml_path)
    if not data:
        return False

    ast_pointer = data.get("ast_pointer")
    if not isinstance(ast_pointer, dict):
        return False

    ast_pointer["fingerprint"] = new_fingerprint
    ast_pointer["bound_at"] = datetime.now(timezone.utc).isoformat()
    ast_pointer["drift"] = False
    data["ast_pointer"] = ast_pointer

    return _save_yaml(yaml_path, data)


# ── 自动修补：追加新增属性 ────────────────────────────────────────────────────

def _append_property(yaml_path: Path, method_name: str, signature: str) -> bool:
    """
    在 ObjectDef 的 properties 中追加新方法/字段。
    只追加到 properties 节，禁止修改 constraints/lifecycle。
    """
    data = _load_yaml(yaml_path)
    if not data:
        return False

    # 只处理 ObjectTypeDef（有 properties 字段的）
    properties = data.get("properties")
    if not isinstance(properties, dict):
        return False

    # 防止重复追加
    if method_name in properties:
        return False

    properties[method_name] = {
        "type": "unknown",
        "required": False,
        "description": f"[auto-generated by ontology_syncer] 签名: {signature[:100]}",
        "source_ep": "EP-130",
        "auto_generated": True,
    }
    data["properties"] = properties
    return _save_yaml(yaml_path, data)


# ── 标记漂移 ─────────────────────────────────────────────────────────────────

def _mark_drift(yaml_path: Path, reason: str) -> bool:
    """在 YAML 中标记 ast_pointer.drift=true。"""
    data = _load_yaml(yaml_path)
    if not data:
        return False

    ast_pointer = data.get("ast_pointer")
    if not isinstance(ast_pointer, dict):
        return False

    ast_pointer["drift"] = True
    ast_pointer["drift_reason"] = reason
    data["ast_pointer"] = ast_pointer
    return _save_yaml(yaml_path, data)


# ── 核心同步器 ───────────────────────────────────────────────────────────────

class OntologySyncer:
    """
    本体语义漂移修补器。

    使用方式：
        syncer = OntologySyncer()
        report = syncer.sync(diff_result, ast_index_after)
        print(report.summary())
    """

    def __init__(self, ontology_dir: Path = _ONTOLOGY_DIR):
        self.ontology_dir = ontology_dir
        self._bindings: Optional[Dict[str, Path]] = None

    def _ensure_bindings(self):
        if self._bindings is None:
            self._bindings = _find_ontology_files_with_ast_pointer(self.ontology_dir)

    def sync(
        self,
        diff_result,
        ast_index_after: Optional[Dict[str, dict]] = None,
        dry_run: bool = False,
    ) -> SyncReport:
        """
        根据 AstDiffResult 同步本体 YAML。

        Args:
            diff_result: ast_diff.diff_ast() 的输出
            ast_index_after: 变更后的 ast_index（用于更新 fingerprint）
            dry_run: 只打印，不写文件
        """
        report = SyncReport()
        if not diff_result or not diff_result.changes:
            return report

        self._ensure_bindings()
        bindings = self._bindings or {}

        for change in diff_result.changes:
            yaml_path = bindings.get(change.file_path)
            if not yaml_path:
                continue  # 该文件无 Ontology 绑定，跳过

            if change.kind == ChangeKind.ADDED_METHOD and change.method_name:
                # ✅ 自动处理：新增方法 → 追加到 properties
                if not dry_run:
                    ok = _append_property(
                        yaml_path,
                        change.method_name,
                        change.after_signature or "",
                    )
                else:
                    ok = True
                action_kind = "auto_patched" if ok else "skipped"
                report.actions.append(SyncAction(
                    kind=action_kind,
                    file_path=str(yaml_path),
                    description=f"追加方法 {change.method_name} → {yaml_path.name}",
                    change=change,
                ))
                if ok and not dry_run:
                    report.patched_files.append(str(yaml_path))

            elif change.kind == ChangeKind.MODIFIED_METHOD:
                # ⚠️ 只告警：签名变更
                if not dry_run:
                    _mark_drift(yaml_path, f"方法 {change.method_name} 签名已变更")
                warning = (
                    f"{change.method_name} 签名变更 in {yaml_path.name}：\n"
                    f"  before: {change.before_signature}\n"
                    f"  after:  {change.after_signature}"
                )
                report.drift_warnings.append(warning)
                report.actions.append(SyncAction(
                    kind="drift_marked",
                    file_path=str(yaml_path),
                    description=f"标记漂移: {change.method_name} 签名变更",
                    change=change,
                ))

            elif change.kind in (ChangeKind.REMOVED_CLASS, ChangeKind.REMOVED_METHOD):
                # 🔴 STALE 告警
                stale_desc = (
                    f"{'类' if change.kind == ChangeKind.REMOVED_CLASS else '方法'} "
                    f"{change.class_name or change.method_name} 已被删除，"
                    f"本体 {yaml_path.name} 可能已过时"
                )
                report.stale_warnings.append(stale_desc)
                report.actions.append(SyncAction(
                    kind="stale_marked",
                    file_path=str(yaml_path),
                    description=stale_desc,
                    change=change,
                ))

            elif change.kind == ChangeKind.FINGERPRINT_CHANGED:
                # 更新 fingerprint（无明细变更时的 fallback）
                if ast_index_after and not dry_run:
                    new_fp = (ast_index_after.get(change.file_path) or {}).get("fingerprint", "")
                    if new_fp:
                        _update_fingerprint(yaml_path, new_fp)
                        report.actions.append(SyncAction(
                            kind="auto_patched",
                            file_path=str(yaml_path),
                            description=f"更新 fingerprint → {yaml_path.name}",
                            change=change,
                        ))

        return report


def sync_after_unit_run(
    before_index: Dict[str, dict],
    after_index: Dict[str, dict],
    scope_files: Optional[List[str]] = None,
    dry_run: bool = False,
    ontology_dir: Path = _ONTOLOGY_DIR,
) -> SyncReport:
    """
    便捷函数：postcheck 阶段调用，执行 diff + sync 全流程。
    """
    try:
        from ast_diff import diff_ast  # type: ignore[import]
    except ImportError:
        _logger.warning("ast_diff 未找到，跳过本体同步")
        return SyncReport()

    diff_result = diff_ast(before_index, after_index, scope_files)
    if not diff_result.changes:
        return SyncReport()

    syncer = OntologySyncer(ontology_dir=ontology_dir)
    return syncer.sync(diff_result, ast_index_after=after_index, dry_run=dry_run)
