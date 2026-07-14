"""Small stdlib-only REST client used by the Memoria PoC tests."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional


class MemoriaHttpError(RuntimeError):
    pass


@dataclass
class MemoriaClient:
    base_url: str
    token: Optional[str] = None
    master_key: Optional[str] = None
    timeout: float = 10.0

    def request(
        self,
        method: str,
        path: str,
        payload: Optional[dict[str, Any]] = None,
        *,
        master: bool = False,
    ) -> Any:
        headers = {"Content-Type": "application/json"}
        if master:
            if not self.master_key:
                raise ValueError("master_key is required")
            headers["Authorization"] = f"Bearer {self.master_key}"
        elif self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base_url.rstrip("/") + path,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                if not raw:
                    return None
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return raw.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            raise MemoriaHttpError(
                f"{method} {path} returned HTTP {error.code}: {body}"
            ) from error

    def health(self) -> Any:
        return self.request("GET", "/health")

    def create_api_key(self, user_id: str, name: str) -> str:
        response = self.request(
            "POST",
            "/auth/keys",
            {"user_id": user_id, "name": name},
            master=True,
        )
        for key in ("raw_key", "key", "token", "api_key"):
            value = response.get(key) if isinstance(response, dict) else None
            if value:
                self.token = str(value)
                return self.token
        raise MemoriaHttpError(f"API key response did not contain a token: {response!r}")

    def store(self, content: str, **extra: Any) -> Any:
        return self.request(
            "POST",
            "/v1/memories",
            {"content": content, "memory_type": "semantic", **extra},
        )

    def list_memories(self, limit: int = 100) -> list[dict[str, Any]]:
        response = self.request("GET", f"/v1/memories?limit={limit}")
        if isinstance(response, dict):
            return list(response.get("items", []))
        return []

    def retrieve(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        response = self.request(
            "POST",
            "/v1/memories/retrieve",
            {
                "query": query,
                "top_k": top_k,
                "memory_types": ["semantic"],
                "session_id": None,
                "explain": True,
            },
        )
        if isinstance(response, dict):
            for key in ("items", "memories", "results"):
                if isinstance(response.get(key), list):
                    return list(response[key])
        return response if isinstance(response, list) else []

    def snapshot(self, name: str, description: str = "") -> Any:
        return self.request(
            "POST",
            "/v1/snapshots",
            {"name": name, "description": description},
        )

    def rollback(self, name: str) -> Any:
        return self.request("POST", f"/v1/snapshots/{urllib.parse.quote(name)}/rollback")

    def branch(self, name: str) -> Any:
        return self.request("POST", "/v1/branches", {"name": name})

    def checkout(self, name: str) -> Any:
        return self.request("POST", f"/v1/branches/{urllib.parse.quote(name)}/checkout")

    def merge(self, name: str, strategy: str = "append") -> Any:
        return self.request(
            "POST",
            f"/v1/branches/{urllib.parse.quote(name)}/merge",
            {"strategy": strategy},
        )
