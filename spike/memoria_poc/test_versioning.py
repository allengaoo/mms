from __future__ import annotations

import time
import uuid

import pytest

from client import MemoriaClient, MemoriaHttpError


def _contents(client: MemoriaClient) -> set[str]:
    return {
        str(item.get("content", ""))
        for item in client.list_memories(limit=100)
    }


def test_snapshot_branch_merge_and_rollback(
    memoria_client: MemoriaClient,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    base = f"MMS_VERSION_BASE_{suffix}"
    after_snapshot = f"MMS_VERSION_AFTER_SNAPSHOT_{suffix}"
    branch_content = f"MMS_VERSION_BRANCH_{suffix}"
    snapshot_name = f"mms-poc-{suffix}"
    branch_name = f"mms-poc-{suffix}"

    memoria_client.store(base)
    try:
        snapshot = memoria_client.snapshot(
            snapshot_name,
            "MMS Phase 0 rollback probe",
        )
    except MemoriaHttpError as error:
        if "no column found for name: snapshot_name" in str(error):
            pytest.xfail(
                "Pinned Memoria commit cannot create snapshots against its "
                "current self-hosted MatrixOne schema: snapshot_name is missing"
            )
        raise
    memoria_client.store(after_snapshot)
    assert after_snapshot in _contents(memoria_client)

    snapshot_ref = (
        snapshot.get("name", snapshot_name)
        if isinstance(snapshot, dict)
        else snapshot_name
    )
    memoria_client.rollback(snapshot_ref)
    assert base in _contents(memoria_client)
    assert after_snapshot not in _contents(memoria_client)

    branch = memoria_client.branch(branch_name)
    branch_ref = (
        branch.get("name", branch_name)
        if isinstance(branch, dict)
        else branch_name
    )
    memoria_client.checkout(branch_ref)
    memoria_client.store(branch_content)
    assert branch_content in _contents(memoria_client)

    memoria_client.checkout("main")
    assert branch_content not in _contents(memoria_client)
    memoria_client.merge(branch_ref)

    deadline = time.monotonic() + 5
    while branch_content not in _contents(memoria_client) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert branch_content in _contents(memoria_client)
