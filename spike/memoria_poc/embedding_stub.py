"""Deterministic OpenAI-compatible embedding stub for the local Memoria PoC."""

from __future__ import annotations

import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIMENSION = 32


def embed(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values = [((digest[index % len(digest)] / 255.0) * 2.0) - 1.0 for index in range(DIMENSION)]
    magnitude = sum(value * value for value in values) ** 0.5 or 1.0
    return [value / magnitude for value in values]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(200, {"status": "ok"})
        else:
            self._json(404, {"detail": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/v1/embeddings":
            self._json(404, {"detail": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        raw_inputs = request.get("input", [])
        inputs = [raw_inputs] if isinstance(raw_inputs, str) else list(raw_inputs)
        data = [
            {"object": "embedding", "index": index, "embedding": embed(str(text))}
            for index, text in enumerate(inputs)
        ]
        self._json(
            200,
            {
                "object": "list",
                "model": request.get("model", "mms-poc-deterministic"),
                "data": data,
                "usage": {"prompt_tokens": 0, "total_tokens": 0},
            },
        )

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
