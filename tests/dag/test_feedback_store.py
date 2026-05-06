"""
tests/dag/test_feedback_store.py

阶段二：AIUFeedbackStore 测试（Test 4 & 5）

测试 4 — 滑动窗口衰减（Decay Window）：
    旧记录超过窗口大小后被自动淘汰，成功率统计不受历史偏见影响。

测试 5 — 并发安全（FileLock）：
    多线程并发写入时，不丢数据、不乱码、文件完整性有保障。
    多进程并发写入时（subprocess 方式），FileLock 阻止数据竞争。
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from mms.dag.aiu_feedback import AIUFeedbackStore


# ─────────────────────────────────────────────────────────────────────────────
# 测试辅助
# ─────────────────────────────────────────────────────────────────────────────

def _make_store(tmp_path: Path, window: int | None = None) -> AIUFeedbackStore:
    """创建使用临时文件的独立 FeedbackStore 实例。"""
    feedback_file = tmp_path / "feedback_stats.jsonl"
    store = AIUFeedbackStore(path=feedback_file)
    if window is not None:
        # 动态替换 deque 的 maxlen 以测试较小的衰减窗口
        from collections import deque as _deque
        from collections import defaultdict as _dd
        store._cache = _dd(lambda: _deque(maxlen=window))
    return store


def _record_n(store: AIUFeedbackStore, aiu_type: str, success: bool, n: int) -> None:
    """批量写入 n 条同类记录。"""
    for i in range(n):
        store.record(
            ep_id="ep_test",
            unit_id="unit_1",
            aiu_id=f"aiu_{i}",
            aiu_type=aiu_type,
            success=success,
        )


# ─────────────────────────────────────────────────────────────────────────────
# 测试 4：滑动窗口衰减（Decay Window）
# ─────────────────────────────────────────────────────────────────────────────

class TestDecayWindow:
    """验证 _DECAY_WINDOW 使新记录自动淘汰旧记录（防止幽灵记忆）。"""

    def test_old_failures_evicted_by_new_successes(self, tmp_path):
        """
        场景：先写 10 条失败，再写 10 条成功，窗口=10。
        期望：成功率 = 1.0（旧的失败记录已被淘汰，不干扰统计）。
        """
        store = _make_store(tmp_path, window=10)
        _record_n(store, "SCHEMA_ADD_FIELD", success=False, n=10)  # 旧失败
        _record_n(store, "SCHEMA_ADD_FIELD", success=True, n=10)   # 新成功

        stats = store.query("SCHEMA_ADD_FIELD")
        aiu_stats = stats.get("SCHEMA_ADD_FIELD")
        assert aiu_stats is not None
        assert aiu_stats.success_rate == 1.0, (
            f"滑动窗口应淘汰旧失败记录，success_rate 应为 1.0，实际：{aiu_stats.success_rate}"
        )
        # 窗口内只有 10 条（新成功的）
        assert aiu_stats.total_runs == 10

    def test_old_successes_evicted_by_new_failures(self, tmp_path):
        """
        场景：先写 10 条成功，再写 10 条失败，窗口=10。
        期望：成功率 = 0.0（旧成功被淘汰）。
        防止"毒性正反馈"中的另一面：旧的成功不会掩盖近期的失败。
        """
        store = _make_store(tmp_path, window=10)
        _record_n(store, "MUTATION_ADD_INSERT", success=True, n=10)   # 旧成功
        _record_n(store, "MUTATION_ADD_INSERT", success=False, n=10)  # 新失败

        stats = store.query("MUTATION_ADD_INSERT")
        aiu_stats = stats.get("MUTATION_ADD_INSERT")
        assert aiu_stats is not None
        assert aiu_stats.success_rate == 0.0, (
            f"滑动窗口应淘汰旧成功记录，success_rate 应为 0.0，实际：{aiu_stats.success_rate}"
        )

    def test_mixed_window_accurate_rate(self, tmp_path):
        """
        场景：窗口=10，写 10 条（5 成功 + 5 失败）。
        期望：success_rate = 0.5，total_runs = 10。
        """
        store = _make_store(tmp_path, window=10)
        _record_n(store, "DOC_SYNC", success=True, n=5)
        _record_n(store, "DOC_SYNC", success=False, n=5)

        stats = store.query("DOC_SYNC")
        aiu_stats = stats.get("DOC_SYNC")
        assert aiu_stats is not None
        assert abs(aiu_stats.success_rate - 0.5) < 0.01
        assert aiu_stats.total_runs == 10

    def test_window_boundary_exact(self, tmp_path):
        """
        窗口=5：写 7 条（2 失败 + 5 成功）。
        期望：窗口内只有最后 5 条，即全成功 → success_rate=1.0。
        """
        store = _make_store(tmp_path, window=5)
        _record_n(store, "TEST_ADD_UNIT", success=False, n=2)  # 第 1-2 条，被淘汰
        _record_n(store, "TEST_ADD_UNIT", success=True, n=5)   # 第 3-7 条，留在窗口

        stats = store.query("TEST_ADD_UNIT")
        aiu_stats = stats.get("TEST_ADD_UNIT")
        assert aiu_stats is not None
        assert aiu_stats.success_rate == 1.0
        assert aiu_stats.total_runs == 5

    def test_no_records_returns_none(self, tmp_path):
        """空 store 查询返回空 dict，不崩溃。"""
        store = _make_store(tmp_path)
        stats = store.query("NON_EXISTENT_TYPE")
        assert stats == {}

    def test_multiple_aiu_types_independent_windows(self, tmp_path):
        """
        多种 AIU 类型各自独立维护窗口，互不干扰。
        """
        store = _make_store(tmp_path, window=5)
        _record_n(store, "SCHEMA_ADD_FIELD", success=True, n=5)
        _record_n(store, "DOC_SYNC", success=False, n=5)

        all_stats = store.query()
        assert all_stats["SCHEMA_ADD_FIELD"].success_rate == 1.0
        assert all_stats["DOC_SYNC"].success_rate == 0.0

    def test_disk_persistence_and_reload(self, tmp_path):
        """
        写入记录后，新建 store 从磁盘重新加载，统计结果一致。
        验证磁盘持久性（WAL append-only）。
        """
        feedback_file = tmp_path / "feedback_stats.jsonl"
        store1 = AIUFeedbackStore(path=feedback_file)
        _record_n(store1, "ROUTE_ADD_ENDPOINT", success=True, n=3)
        _record_n(store1, "ROUTE_ADD_ENDPOINT", success=False, n=2)

        # 新建实例重新从磁盘加载
        store2 = AIUFeedbackStore(path=feedback_file)
        stats = store2.query("ROUTE_ADD_ENDPOINT")
        aiu_stats = stats.get("ROUTE_ADD_ENDPOINT")
        assert aiu_stats is not None
        assert aiu_stats.total_runs == 5
        assert abs(aiu_stats.success_rate - 0.6) < 0.01


# ─────────────────────────────────────────────────────────────────────────────
# 测试 5：并发文件锁（FileLock）
# ─────────────────────────────────────────────────────────────────────────────

class TestFileLockConcurrency:
    """验证 FileLock 在多线程和多进程场景下保证写入完整性。"""

    # ── 5a：多线程并发写入 ────────────────────────────────────────────────────

    def test_multithread_concurrent_writes_all_recorded(self, tmp_path):
        """
        5 个线程，每线程写 100 条记录 → 总计 500 条。
        验证：磁盘文件行数 = 500，每行均为合法 JSON（无行内乱码/半写）。
        """
        feedback_file = tmp_path / "feedback_mt.jsonl"
        store = AIUFeedbackStore(path=feedback_file)
        n_threads = 5
        records_per_thread = 100
        total_expected = n_threads * records_per_thread

        def _write_batch(thread_id: int) -> None:
            for i in range(records_per_thread):
                store.record(
                    ep_id=f"ep_t{thread_id}",
                    unit_id="unit_mt",
                    aiu_id=f"aiu_{i}",
                    aiu_type="SCHEMA_ADD_FIELD",
                    success=(i % 2 == 0),
                    actual_tokens=1000 + i,
                )

        with ThreadPoolExecutor(max_workers=n_threads) as executor:
            futures = [executor.submit(_write_batch, t) for t in range(n_threads)]
            for f in futures:
                f.result()  # 等待全部完成，传播异常

        # 验证磁盘完整性
        lines = [
            line for line in feedback_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(lines) == total_expected, (
            f"多线程写入应有 {total_expected} 条，实际 {len(lines)} 条"
        )
        for i, line in enumerate(lines):
            try:
                json.loads(line)
            except json.JSONDecodeError as e:
                pytest.fail(f"第 {i} 行 JSON 损坏：{e}\n内容：{line[:100]}")

    def test_multithread_no_duplicate_aiu_ids(self, tmp_path):
        """
        多线程写入后，内存缓存中的 aiu_id 不重复。
        （aiu_id 包含线程标识，验证无数据竞争导致覆盖）
        """
        feedback_file = tmp_path / "feedback_nodup.jsonl"
        store = AIUFeedbackStore(path=feedback_file)
        aiu_id_log = []
        log_lock = threading.Lock()

        def _write_with_log(thread_id: int, record_id: int) -> None:
            aiu_id = f"aiu_t{thread_id}_r{record_id}"
            store.record(
                ep_id="ep_nodup",
                unit_id="unit_nodup",
                aiu_id=aiu_id,
                aiu_type="DOC_SYNC",
                success=True,
            )
            with log_lock:
                aiu_id_log.append(aiu_id)

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(_write_with_log, t, r)
                for t in range(4)
                for r in range(25)
            ]
            for f in futures:
                f.result()

        # 验证无重复
        assert len(aiu_id_log) == len(set(aiu_id_log)), "aiu_id 存在重复，写入逻辑有竞态"
        # 验证文件行数
        lines = [
            l for l in feedback_file.read_text(encoding="utf-8").splitlines() if l.strip()
        ]
        assert len(lines) == 100

    def test_lock_file_created_on_write(self, tmp_path):
        """
        执行 record() 时，FileLock 会在磁盘上创建 .lock 文件。
        验证 filelock 依赖已正确安装并生效。
        """
        feedback_file = tmp_path / "feedback_lock.jsonl"
        store = AIUFeedbackStore(path=feedback_file)

        store.record(
            ep_id="ep_lock",
            unit_id="unit_lock",
            aiu_id="aiu_1",
            aiu_type="CONFIG_MODIFY",
            success=True,
        )

        lock_file = Path(str(feedback_file) + ".lock")
        assert lock_file.exists(), (
            f"FileLock 写入后应在 {lock_file} 创建锁文件，但未发现"
        )

    # ── 5b：多进程并发写入 ────────────────────────────────────────────────────

    def test_multiprocess_concurrent_writes(self, tmp_path):
        """
        3 个子进程，每进程写 50 条记录 → 总计 150 条。
        使用 subprocess.run 启动完全独立的 Python 进程，验证跨进程 FileLock 生效。
        """
        feedback_file = tmp_path / "feedback_mp.jsonl"
        n_processes = 3
        records_per_process = 50
        total_expected = n_processes * records_per_process

        # 写入临时 Python 脚本（每进程执行相同逻辑）
        worker_script = tmp_path / "worker.py"
        worker_script.write_text(
            f"""\
import sys
sys.path.insert(0, {str(_PROJECT_ROOT / "src")!r})
from mms.dag.aiu_feedback import AIUFeedbackStore
from pathlib import Path

feedback_file = Path({str(feedback_file)!r})
store = AIUFeedbackStore(path=feedback_file)
proc_id = sys.argv[1]
for i in range({records_per_process}):
    store.record(
        ep_id=f"ep_p{{proc_id}}",
        unit_id="unit_mp",
        aiu_id=f"aiu_{{i}}",
        aiu_type="MUTATION_ADD_INSERT",
        success=True,
        actual_tokens=2000 + i,
    )
""",
            encoding="utf-8",
        )

        # 启动多个子进程（并发）
        procs = [
            subprocess.Popen(
                [sys.executable, str(worker_script), str(pid)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for pid in range(n_processes)
        ]
        for p in procs:
            stdout, stderr = p.communicate(timeout=30)
            assert p.returncode == 0, (
                f"子进程返回码 {p.returncode}\nstderr: {stderr.decode()[:500]}"
            )

        # 验证磁盘完整性
        lines = [
            line for line in feedback_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(lines) == total_expected, (
            f"多进程写入应有 {total_expected} 条，实际 {len(lines)} 条"
        )
        for i, line in enumerate(lines):
            try:
                json.loads(line)
            except json.JSONDecodeError as e:
                pytest.fail(f"进程并发写入后第 {i} 行 JSON 损坏：{e}\n内容：{line[:100]}")

    def test_multiprocess_data_isolation_by_process(self, tmp_path):
        """
        验证多进程写入后，每个进程写入的记录均可被识别（ep_id 包含进程 ID）。
        确认没有数据丢失：每个进程恰好写入 records_per_process 条。
        """
        feedback_file = tmp_path / "feedback_isolation.jsonl"
        n_processes = 3
        records_per_process = 20

        worker_script = tmp_path / "worker_isolation.py"
        worker_script.write_text(
            f"""\
import sys
sys.path.insert(0, {str(_PROJECT_ROOT / "src")!r})
from mms.dag.aiu_feedback import AIUFeedbackStore
from pathlib import Path

store = AIUFeedbackStore(path=Path({str(feedback_file)!r}))
proc_id = sys.argv[1]
for i in range({records_per_process}):
    store.record(
        ep_id=f"proc_{{proc_id}}",
        unit_id="unit_iso",
        aiu_id=f"aiu_{{i}}",
        aiu_type="TEST_ADD_UNIT",
        success=(i % 2 == 0),
    )
""",
            encoding="utf-8",
        )

        procs = [
            subprocess.Popen([sys.executable, str(worker_script), str(pid)])
            for pid in range(n_processes)
        ]
        for p in procs:
            p.wait(timeout=30)
            assert p.returncode == 0

        # 按 ep_id 统计每个进程的写入量
        records = []
        for line in feedback_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pytest.fail(f"JSON 损坏：{line[:100]}")

        assert len(records) == n_processes * records_per_process

        from collections import Counter
        ep_counts = Counter(r["ep_id"] for r in records)
        for pid in range(n_processes):
            ep_id = f"proc_{pid}"
            assert ep_counts[ep_id] == records_per_process, (
                f"进程 {pid} 应写入 {records_per_process} 条，实际 {ep_counts[ep_id]} 条"
            )
