"""Version-control contract for memory backends."""

from __future__ import annotations

from typing import Any, Dict, List, Protocol, runtime_checkable


@runtime_checkable
class VersionStore(Protocol):
    def snapshot(self, label: str, description: str = "") -> str:
        ...

    def branch(self, name: str) -> str:
        ...

    def merge(self, source: str, target: str = "main") -> Dict[str, Any]:
        ...

    def rollback(self, reference: str) -> None:
        ...

    def history(self, memory_id: str) -> List[Dict[str, Any]]:
        ...


class NullVersionStore:
    """Explicit placeholder used by backends without native version control."""

    _MESSAGE = "the active memory backend does not implement version control"

    def snapshot(self, label: str, description: str = "") -> str:
        raise NotImplementedError(self._MESSAGE)

    def branch(self, name: str) -> str:
        raise NotImplementedError(self._MESSAGE)

    def merge(self, source: str, target: str = "main") -> Dict[str, Any]:
        raise NotImplementedError(self._MESSAGE)

    def rollback(self, reference: str) -> None:
        raise NotImplementedError(self._MESSAGE)

    def history(self, memory_id: str) -> List[Dict[str, Any]]:
        raise NotImplementedError(self._MESSAGE)
