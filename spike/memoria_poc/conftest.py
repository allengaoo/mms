from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from client import MemoriaClient

POC_DIR = Path(__file__).resolve().parent


def _load_dotenv() -> dict[str, str]:
    values: dict[str, str] = {}
    env_file = POC_DIR / ".env"
    if not env_file.exists():
        return values
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


@pytest.fixture(scope="session")
def memoria_client() -> MemoriaClient:
    dotenv = _load_dotenv()
    client = MemoriaClient(
        base_url=os.getenv("MEMORIA_URL", "http://127.0.0.1:8100"),
        master_key=os.getenv("MEMORIA_MASTER_KEY", dotenv.get("MEMORIA_MASTER_KEY")),
    )
    try:
        client.health()
    except Exception as error:
        pytest.skip(f"Memoria API is not available: {error}")
    client.create_api_key(
        user_id=f"mms-poc-{uuid.uuid4().hex[:8]}",
        name="MMS Phase 0 PoC",
    )
    return client
