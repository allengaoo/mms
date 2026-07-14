"""Projection between ontology Markdown documents and ``MemoryRecord``."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable

import yaml

from .repository import MemoryRecord

_FRONT_MATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
_PROVENANCE_KEYS = (
    "module",
    "source_ep",
    "generalized",
    "dimension",
    "source",
    "ast_pointer",
    "class_name",
    "fingerprint",
)


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return [value]


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _extract_title(body: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            raw = line[2:].strip()
            return raw.split("·", 1)[-1].strip() if "·" in raw else raw
    return ""


@runtime_checkable
class OntologyProjection(Protocol):
    def to_record(
        self,
        front_matter: Dict[str, Any],
        body: str,
        *,
        path: Any = None,
    ) -> MemoryRecord:
        ...

    def from_record(self, record: MemoryRecord) -> Tuple[Dict[str, Any], str]:
        ...


class FrontMatterProjection:
    """Lossless semantic projection for the current Markdown representation."""

    def parse(self, document: str, *, path: Any = None) -> MemoryRecord:
        match = _FRONT_MATTER.match(document)
        if not match:
            raise ValueError("memory document is missing YAML front matter")
        front_matter = yaml.safe_load(match.group(1)) or {}
        if not isinstance(front_matter, dict):
            raise ValueError("memory front matter must be a mapping")
        return self.to_record(front_matter, document[match.end():], path=path)

    def to_record(
        self,
        front_matter: Dict[str, Any],
        body: str,
        *,
        path: Any = None,
    ) -> MemoryRecord:
        memory_id = str(front_matter.get("id", "")).strip()
        if not memory_id:
            raise ValueError("memory front matter requires a non-empty id")

        provenance = {
            key: front_matter[key]
            for key in _PROVENANCE_KEYS
            if key in front_matter
        }
        return MemoryRecord(
            id=memory_id,
            body=body,
            title=str(front_matter.get("title") or _extract_title(body)),
            object_type=str(
                front_matter.get("object_type")
                or front_matter.get("type")
                or ""
            ),
            layer=str(front_matter.get("layer", "")),
            tier=str(front_matter.get("tier", "warm")),
            tags=[str(item) for item in _as_list(front_matter.get("tags"))],
            related_to=_as_list(
                front_matter.get(
                    "related_to",
                    front_matter.get("related_memories"),
                )
            ),
            cites_files=[
                str(item) for item in _as_list(front_matter.get("cites_files"))
            ],
            impacts=[str(item) for item in _as_list(front_matter.get("impacts"))],
            about_concepts=[
                str(item) for item in _as_list(front_matter.get("about_concepts"))
            ],
            contradicts=[
                str(item) for item in _as_list(front_matter.get("contradicts"))
            ],
            derived_from=[
                str(item) for item in _as_list(front_matter.get("derived_from"))
            ],
            version=_as_int(front_matter.get("version"), 1),
            access_count=_as_int(front_matter.get("access_count"), 0),
            created_at=front_matter.get("created_at"),
            updated_at=front_matter.get("updated_at"),
            provenance=provenance,
            metadata=dict(front_matter),
            path=path,
        )

    def from_record(self, record: MemoryRecord) -> Tuple[Dict[str, Any], str]:
        front_matter = dict(record.metadata)
        front_matter["id"] = record.id
        self._overlay(front_matter, "layer", record.layer)
        self._overlay(front_matter, "tier", record.tier, default="warm")
        self._overlay(front_matter, "tags", record.tags)
        if "related_to" in front_matter:
            front_matter["related_to"] = record.related_to
        elif "related_memories" in front_matter:
            front_matter["related_memories"] = record.related_to
        elif record.related_to:
            front_matter["related_to"] = record.related_to
        self._overlay(front_matter, "cites_files", record.cites_files)
        self._overlay(front_matter, "impacts", record.impacts)
        self._overlay(front_matter, "about_concepts", record.about_concepts)
        self._overlay(front_matter, "contradicts", record.contradicts)
        self._overlay(front_matter, "derived_from", record.derived_from)
        self._overlay(front_matter, "version", record.version, default=1)
        self._overlay(front_matter, "access_count", record.access_count, default=0)
        self._overlay(front_matter, "created_at", record.created_at)
        self._overlay(front_matter, "updated_at", record.updated_at)

        if "object_type" in front_matter:
            front_matter["object_type"] = record.object_type
        elif "type" in front_matter and record.object_type:
            front_matter["type"] = record.object_type
        elif record.object_type:
            front_matter["object_type"] = record.object_type

        if "title" in front_matter:
            self._overlay(front_matter, "title", record.title)
        for key, value in record.provenance.items():
            self._overlay(front_matter, key, value)
        return front_matter, record.body

    def render(self, record: MemoryRecord) -> str:
        front_matter, body = self.from_record(record)
        yaml_text = yaml.safe_dump(
            front_matter,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        ).rstrip()
        return f"---\n{yaml_text}\n---\n{body.lstrip(chr(10))}"

    @staticmethod
    def _overlay(
        front_matter: Dict[str, Any],
        key: str,
        value: Any,
        *,
        default: Any = None,
    ) -> None:
        if key in front_matter or (
            value != default and value not in (None, "", [], {})
        ):
            front_matter[key] = value
