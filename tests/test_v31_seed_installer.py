"""Tests for v3.1 seed pack installer + always_inject discovery."""
from __future__ import annotations

from pathlib import Path

import pytest

from mms.bootstrap.v31_seed_installer import (
    discover_always_inject_packs,
    install_v31_packs,
    load_process_gates,
    resolve_v31_pack_names,
)


@pytest.fixture()
def v31_fixture(tmp_path: Path) -> Path:
    memory = tmp_path / "docs" / "memory"
    pack = memory / "seed_packs" / "superpowers_sdlc"
    (pack / "memories").mkdir(parents=True)
    (pack / "meta.yaml").write_text(
        "id: superpowers_sdlc\nalways_inject: true\nlayer_affinity: [CC]\n",
        encoding="utf-8",
    )
    (pack / "constraints.yaml").write_text(
        "rules:\n"
        "  - id: SP-GATE-TEST\n"
        "    description: test gate\n"
        "    severity: ERROR\n"
        "    kind: process_gate\n",
        encoding="utf-8",
    )
    (pack / "memories" / "AD-SP-TEST.md").write_text(
        "---\n"
        "id: AD-SP-TEST\n"
        "layer: CC\n"
        "type: decision\n"
        "tier: hot\n"
        "tags: [superpowers, test]\n"
        "version: 1\n"
        "---\n\n"
        "# AD-SP-TEST\n\n"
        "fixture memory\n",
        encoding="utf-8",
    )
    return memory


def test_discover_always_inject(v31_fixture: Path) -> None:
    packs = discover_always_inject_packs(v31_fixture)
    assert "superpowers_sdlc" in packs


def test_resolve_includes_always_inject(v31_fixture: Path) -> None:
    names = resolve_v31_pack_names(["fastapi_sqlmodel"], v31_fixture)
    assert "superpowers_sdlc" in names


def test_install_writes_shared_and_index(v31_fixture: Path) -> None:
    installed = install_v31_packs(
        ["superpowers_sdlc"],
        memory_root=v31_fixture,
        dry_run=False,
        include_always_inject=True,
    )
    assert "superpowers_sdlc" in installed
    target = v31_fixture / "shared" / "CC" / "AD-SP-TEST.md"
    assert target.exists()
    index = v31_fixture / "MEMORY_INDEX.json"
    assert index.exists()
    text = index.read_text(encoding="utf-8")
    assert "AD-SP-TEST" in text


def test_load_process_gates(v31_fixture: Path) -> None:
    gates = load_process_gates(v31_fixture)
    assert any(g.get("id") == "SP-GATE-TEST" for g in gates)


def test_dry_run_does_not_write(v31_fixture: Path) -> None:
    installed = install_v31_packs(
        ["superpowers_sdlc"],
        memory_root=v31_fixture,
        dry_run=True,
    )
    assert installed == ["superpowers_sdlc"]
    assert not (v31_fixture / "shared").exists()
