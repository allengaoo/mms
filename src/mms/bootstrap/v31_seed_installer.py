"""
v3.1 seed pack installer — docs/memory/seed_packs/{name}/meta.yaml

Reads meta.yaml (always_inject / memories), copies memories into
docs/memory/shared/{layer}/ via MarkdownRepository.put so MEMORY_INDEX
is updated immediately.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

logger = logging.getLogger(__name__)

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent.parent  # src/mms/bootstrap → repo root
_DEFAULT_V31_ROOT = _ROOT / "docs" / "memory" / "seed_packs"

# dep_sniffer stack ids → v3.1 pack directory names
_STACK_TO_V31: Dict[str, str] = {
    "fastapi_sqlmodel": "python_fastapi",
    "spring_boot": "java_spring_boot",
    "go_gin": "go_microservice",
    "react_zustand": "typescript_nestjs",
    "base": "cross_cutting",
}


def v31_packs_root(memory_root: Optional[Path] = None) -> Path:
    if memory_root is not None:
        return Path(memory_root) / "seed_packs"
    return _DEFAULT_V31_ROOT


def list_v31_packs(memory_root: Optional[Path] = None) -> List[str]:
    root = v31_packs_root(memory_root)
    if not root.is_dir():
        return []
    return sorted(
        d.name
        for d in root.iterdir()
        if d.is_dir()
        and not d.name.startswith("_")
        and (d / "meta.yaml").exists()
    )


def _load_meta(pack_dir: Path) -> Dict:
    meta_path = pack_dir / "meta.yaml"
    if not meta_path.exists():
        return {}
    try:
        import yaml  # type: ignore
        return yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
    except Exception:
        # Minimal fallback: only parse always_inject / id without PyYAML
        meta: Dict = {}
        for line in meta_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("id:"):
                meta["id"] = line.split(":", 1)[1].strip().strip("\"'")
            elif line.startswith("always_inject:"):
                meta["always_inject"] = "true" in line.lower()
        return meta


def discover_always_inject_packs(memory_root: Optional[Path] = None) -> List[str]:
    """Return v3.1 pack ids with always_inject: true."""
    root = v31_packs_root(memory_root)
    result = []
    for name in list_v31_packs(memory_root):
        meta = _load_meta(root / name)
        if meta.get("always_inject") is True:
            result.append(str(meta.get("id") or name))
    return result


def resolve_v31_pack_names(
    detected_stacks: Iterable[str],
    memory_root: Optional[Path] = None,
) -> List[str]:
    """Union of always_inject packs and stack-mapped v3.1 packs."""
    names: Set[str] = set(discover_always_inject_packs(memory_root))
    available = set(list_v31_packs(memory_root))
    for stack in detected_stacks:
        mapped = _STACK_TO_V31.get(stack, stack)
        if mapped in available:
            names.add(mapped)
        if stack in available:
            names.add(stack)
    always = set(discover_always_inject_packs(memory_root))
    ordered = sorted(names & always) + sorted(names - always)
    return ordered


def install_v31_packs(
    pack_names: List[str],
    memory_root: Path,
    *,
    dry_run: bool = False,
    include_always_inject: bool = True,
) -> List[str]:
    """
    Install v3.1 packs into shared/ and update MEMORY_INDEX via repository.put.

    Returns list of successfully installed pack ids.
    """
    memory_root = Path(memory_root)
    packs_root = memory_root / "seed_packs"
    if include_always_inject:
        pack_names = resolve_v31_pack_names(pack_names, memory_root)

    if not pack_names:
        return []

    if dry_run:
        for name in pack_names:
            print(f"  [dry-run] 将注入 v3.1 种子包: {name}")
        return list(pack_names)

    from mms.adapters import get_repository
    from mms.adapters.markdown_repo import MarkdownRepository
    from mms.ports.projection import FrontMatterProjection

    repo = get_repository(memory_root=memory_root)
    projection = FrontMatterProjection()
    installed: List[str] = []

    prev_sanitize = os.environ.get("MMS_SANITIZE_DISABLE")
    os.environ["MMS_SANITIZE_DISABLE"] = "1"
    try:
        for pack_name in pack_names:
            pack_dir = packs_root / pack_name
            memories_dir = pack_dir / "memories"
            if not memories_dir.is_dir():
                logger.warning("v3.1 pack %s missing memories/", pack_name)
                continue
            count = 0
            for md in sorted(memories_dir.glob("*.md")):
                try:
                    original = md.read_text(encoding="utf-8")
                    record = projection.parse(original, path=md)
                    layer = MarkdownRepository._normalize_layer(record.layer or "CC")
                    target = (
                        Path(memory_root).resolve()
                        / "shared"
                        / layer
                        / f"{record.id}.md"
                    )
                    # Preserve seed front-matter formatting via repository API
                    repo.import_raw(original, target)  # type: ignore[attr-defined]
                    count += 1
                except Exception as exc:
                    logger.warning(
                        "failed to install %s from %s: %s", md.name, pack_name, exc
                    )
            if count:
                installed.append(pack_name)
                logger.info(
                    "installed %s memories from v3.1 pack %s", count, pack_name
                )
    finally:
        if prev_sanitize is None:
            os.environ.pop("MMS_SANITIZE_DISABLE", None)
        else:
            os.environ["MMS_SANITIZE_DISABLE"] = prev_sanitize

    return installed


def load_pack_constraints(pack_name: str, memory_root: Optional[Path] = None) -> List[Dict]:
    """Load rules[] from a pack's constraints.yaml (empty if missing)."""
    root = v31_packs_root(memory_root)
    path = root / pack_name / "constraints.yaml"
    if not path.exists():
        return []
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return list(data.get("rules") or [])
    except Exception:
        return []


def load_process_gates(memory_root: Optional[Path] = None) -> List[Dict]:
    """Aggregate process gates from always_inject packs."""
    gates: List[Dict] = []
    for pack in discover_always_inject_packs(memory_root):
        for rule in load_pack_constraints(pack, memory_root):
            kind = rule.get("kind") or ""
            if kind in {
                "process_gate",
                "learning_policy",
                "testing_policy",
                "security_policy",
            }:
                gates.append({**rule, "pack": pack})
    return gates
