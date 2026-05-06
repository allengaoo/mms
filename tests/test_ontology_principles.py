"""
tests/test_ontology_principles.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Ontology Design Principles 合规性检查

确保所有 ObjectType 和 Action YAML 文件符合
assets/ontology_schema/_config/ontology_design_principles.yaml 中定义的原则。

CI 中每次 PR 都会运行此测试，防止引入新的 schema 反模式。
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_SCHEMA = _ROOT / "assets" / "ontology_schema"
_PRINCIPLES_FILE = _SCHEMA / "_config" / "ontology_design_principles.yaml"
_OBJECTS_DIR = _SCHEMA / "objects"
_ACTIONS_DIR = _SCHEMA / "actions"


def _load_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        pytest.fail(f"Failed to load YAML {path}: {e}")


def _get_principle_ids() -> List[str]:
    principles = _load_yaml(_PRINCIPLES_FILE)
    return [p["id"] for p in principles.get("principles", [])]


def _schema_files(directory: Path) -> List[Path]:
    if not directory.exists():
        return []
    return sorted(f for f in directory.glob("*.yaml") if not f.name.startswith("_"))


# ─── 原则文件自身完整性测试 ─────────────────────────────────────────────────────

class TestPrinciplesFile:
    def test_principles_file_exists(self):
        assert _PRINCIPLES_FILE.exists(), f"Design principles file not found: {_PRINCIPLES_FILE}"

    def test_principles_have_required_fields(self):
        principles = _load_yaml(_PRINCIPLES_FILE)
        required = {"id", "label", "statement", "rationale", "status"}
        for p in principles.get("principles", []):
            missing = required - set(p.keys())
            assert not missing, f"Principle '{p.get('id', '?')}' missing fields: {missing}"

    def test_all_principles_active_or_deprecated(self):
        principles = _load_yaml(_PRINCIPLES_FILE)
        valid_statuses = {"active", "deprecated"}
        for p in principles.get("principles", []):
            assert p.get("status") in valid_statuses, (
                f"Principle '{p.get('id')}' has invalid status: {p.get('status')}"
            )

    def test_principle_ids_unique(self):
        ids = _get_principle_ids()
        assert len(ids) == len(set(ids)), f"Duplicate principle IDs found: {ids}"


# ─── ObjectType 合规性测试（新建文件必须声明 declared_principles） ───────────────

# 现有文件的豁免名单（在引入原则文件前已存在，逐步补全）
_EXISTING_OBJECTS_EXEMPT = {
    "arch_decision.yaml",      # 将被 Phase 2 重构为 Decision ObjectType
    "code_class.yaml",         # 低层技术对象，不直接面向用户
    "code_file.yaml",
    "code_module.yaml",
    "domain_concept.yaml",
    "memory_node.yaml",        # Phase 2 拆分目标，废弃中
    "pattern.yaml",            # Phase 2 重构目标
}


class TestObjectTypeCompliance:
    @pytest.mark.parametrize("schema_file", _schema_files(_OBJECTS_DIR))
    def test_object_type_has_id(self, schema_file: Path):
        data = _load_yaml(schema_file)
        assert "id" in data, f"{schema_file.name}: missing 'id' field"

    @pytest.mark.parametrize("schema_file", _schema_files(_OBJECTS_DIR))
    def test_object_type_has_description(self, schema_file: Path):
        data = _load_yaml(schema_file)
        assert "description" in data, f"{schema_file.name}: missing 'description' field"

    @pytest.mark.parametrize("schema_file", _schema_files(_OBJECTS_DIR))
    def test_new_object_type_declares_principles(self, schema_file: Path):
        """新建的 ObjectType 文件（非豁免）必须声明 declared_principles。"""
        if schema_file.name in _EXISTING_OBJECTS_EXEMPT:
            pytest.skip(f"{schema_file.name} is in legacy exempt list (pending Phase 2 refactor)")
        data = _load_yaml(schema_file)
        assert "declared_principles" in data, (
            f"{schema_file.name}: missing 'declared_principles' field. "
            f"New ObjectType files must declare which design principles they follow. "
            f"See assets/ontology_schema/_config/ontology_design_principles.yaml"
        )

    @pytest.mark.parametrize("schema_file", _schema_files(_OBJECTS_DIR))
    def test_declared_principles_are_valid(self, schema_file: Path):
        """declared_principles 中引用的原则 ID 必须在 principles 文件中存在。"""
        if schema_file.name in _EXISTING_OBJECTS_EXEMPT:
            pytest.skip(f"{schema_file.name} is in legacy exempt list")
        data = _load_yaml(schema_file)
        if "declared_principles" not in data:
            return
        valid_ids = set(_get_principle_ids())
        declared = data["declared_principles"]
        if isinstance(declared, list):
            for pid in declared:
                assert pid in valid_ids, (
                    f"{schema_file.name}: references unknown principle '{pid}'. "
                    f"Valid IDs: {sorted(valid_ids)}"
                )


# ─── Action 合规性测试 ────────────────────────────────────────────────────────

_EXISTING_ACTIONS_EXEMPT = {
    "bootstrap.yaml",
    "distill.yaml",
    "dream.yaml",
    "promote_draft.yaml",
    "retire_memory.yaml",
}


class TestActionCompliance:
    @pytest.mark.parametrize("schema_file", _schema_files(_ACTIONS_DIR))
    def test_action_has_id(self, schema_file: Path):
        data = _load_yaml(schema_file)
        assert "id" in data, f"{schema_file.name}: missing 'id' field"

    @pytest.mark.parametrize("schema_file", _schema_files(_ACTIONS_DIR))
    def test_action_has_description(self, schema_file: Path):
        data = _load_yaml(schema_file)
        assert "description" in data, f"{schema_file.name}: missing 'description' field"

    @pytest.mark.parametrize("schema_file", _schema_files(_ACTIONS_DIR))
    def test_new_action_declares_principles(self, schema_file: Path):
        if schema_file.name in _EXISTING_ACTIONS_EXEMPT:
            pytest.skip(f"{schema_file.name} is in legacy exempt list")
        data = _load_yaml(schema_file)
        assert "declared_principles" in data, (
            f"{schema_file.name}: new Action files must declare 'declared_principles'"
        )


# ─── God Object 检测器 ────────────────────────────────────────────────────────

class TestGodObjectDetection:
    @pytest.mark.parametrize("schema_file", _schema_files(_OBJECTS_DIR))
    def test_no_type_based_semantic_switching(self, schema_file: Path):
        """检测 type 字段控制语义切换的 God Object 反模式。"""
        if schema_file.name in _EXISTING_OBJECTS_EXEMPT:
            pytest.skip(f"{schema_file.name} is God Object under Phase 2 refactor")
        data = _load_yaml(schema_file)
        props = data.get("properties", {})
        # type 字段若 enum > 3，且文件不是 _memory_base（基础 schema），则警告
        if "type" in props and schema_file.name != "_memory_base.yaml":
            type_enum = props["type"].get("enum", [])
            if len(type_enum) > 3:
                pytest.fail(
                    f"{schema_file.name}: 'type' field has {len(type_enum)} enum values "
                    f"({type_enum}). This may indicate a God Object anti-pattern (P4). "
                    f"Consider splitting into separate ObjectTypes."
                )
