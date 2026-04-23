#!/usr/bin/env python3
"""
sandbox.py — MMS Git 沙箱

为 mms unit run 提供基于逐文件快照的可回滚执行环境。

设计原则：
  - 不使用 git stash（避免影响用户在工作区中其他未提交的变更）
  - 仅快照 unit.files 声明的文件（范围精确，不污染）
  - 回滚时：已追踪文件 git checkout，新建文件直接删除

用法（作为上下文管理器）：
    with GitSandbox(file_paths, root=_ROOT) as sb:
        # 在此修改文件（由 FileApplier 完成）
        if verification_passes:
            commit_hash = sb.commit("EP-119 U1: 实现 sandbox")
        else:
            sb.rollback()
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[2]

_G = "\033[92m"
_Y = "\033[93m"
_R = "\033[91m"
_C = "\033[96m"
_B = "\033[1m"
_D = "\033[2m"
_X = "\033[0m"


class SandboxError(Exception):
    """沙箱操作异常"""


class GitSandbox:
    """
    逐文件快照的 Git 沙箱。

    使用方式（非上下文管理器，显式管理生命周期）：
        sb = GitSandbox(file_paths, root=_ROOT)
        sb.snapshot()                  # 建立快照
        # ... 修改文件 ...
        if ok:
            sb.commit("message")
        else:
            sb.rollback()
    """

    def __init__(self, files: List[str], root: Path = _ROOT):
        """
        Args:
            files: 需要纳入沙箱管理的文件路径（相对于 root）
            root: 项目根目录
        """
        self.files = files
        self.root = root
        # 快照：{ 相对路径 -> 原始内容(bytes) | None(文件不存在) }
        self._snapshot: Dict[str, Optional[bytes]] = {}
        self._snapshotted = False
        # 记录由沙箱写入的新文件（原本不存在，回滚时需删除）
        self._new_files: List[str] = []

    def snapshot(self) -> None:
        """
        建立文件快照。
        已存在的文件：读取当前内容备份。
        不存在的文件：记录为 None（回滚时删除）。
        """
        self._snapshot.clear()
        self._new_files.clear()
        for rel_path in self.files:
            abs_path = self.root / rel_path
            if abs_path.exists():
                self._snapshot[rel_path] = abs_path.read_bytes()
            else:
                self._snapshot[rel_path] = None  # 文件不存在
        self._snapshotted = True

    def mark_new_file(self, rel_path: str) -> None:
        """
        标记一个沙箱外新建的文件（非 unit.files 内，但由 applier 新建）。
        回滚时一并删除。通常不需要调用此方法，FileApplier 会自动调用。
        """
        if rel_path not in self._new_files:
            self._new_files.append(rel_path)

    def rollback(self) -> None:
        """
        回滚所有文件到快照状态。

        - 快照为 bytes → 恢复文件内容
        - 快照为 None（原本不存在）→ 删除文件
        - _new_files 中的文件 → 删除
        """
        if not self._snapshotted:
            return

        for rel_path, original in self._snapshot.items():
            abs_path = self.root / rel_path
            if original is None:
                # 原本不存在，若现在存在则删除
                if abs_path.exists():
                    abs_path.unlink()
            else:
                # 恢复原始内容
                abs_path.parent.mkdir(parents=True, exist_ok=True)
                abs_path.write_bytes(original)

        # 删除沙箱外新建的文件
        for rel_path in self._new_files:
            abs_path = self.root / rel_path
            if abs_path.exists():
                abs_path.unlink()

    def commit(self, message: str) -> Optional[str]:
        """
        将沙箱内的变更提交为 git commit。

        Args:
            message: commit 消息

        Returns:
            commit hash（短），失败返回 None
        """
        try:
            subprocess.run(
                ["git", "add", "-A"],
                cwd=str(self.root), check=True, capture_output=True,
            )
            result = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=str(self.root), capture_output=True, text=True,
            )
            if result.returncode != 0:
                stderr = result.stderr.strip()
                if "nothing to commit" in stderr:
                    return None  # 无变更，不视为错误
                raise SandboxError(f"git commit 失败：{stderr[:200]}")

            hash_result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(self.root), capture_output=True, text=True,
            )
            return hash_result.stdout.strip() if hash_result.returncode == 0 else None

        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or b"").decode(errors="replace")
            raise SandboxError(f"git 操作失败：{stderr[:200]}") from e

    def diff_stat(self) -> str:
        """
        返回自快照以来的变更摘要（git diff --stat）。

        Returns:
            变更摘要字符串（供 --dry-run / --confirm 模式展示）
        """
        try:
            result = subprocess.run(
                ["git", "diff", "--stat", "HEAD"],
                cwd=str(self.root), capture_output=True, text=True,
            )
            stat = result.stdout.strip()

            # 补充：未追踪文件（新建文件不在 git diff 中）
            untracked_result = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard"],
                cwd=str(self.root), capture_output=True, text=True,
            )
            untracked = [
                f"  {line.strip()} (new file)"
                for line in untracked_result.stdout.splitlines()
                if line.strip() in self.files
            ]

            parts = []
            if stat:
                parts.append(stat)
            if untracked:
                parts.extend(untracked)
            return "\n".join(parts) if parts else "（无文件变更）"

        except Exception as exc:
            return f"（diff 获取失败：{exc}）"

    @property
    def changed_files(self) -> List[str]:
        """返回实际发生变更的文件列表（快照与当前内容不同）"""
        changed = []
        for rel_path, original in self._snapshot.items():
            abs_path = self.root / rel_path
            if original is None:
                if abs_path.exists():
                    changed.append(rel_path)
            else:
                if abs_path.exists():
                    if abs_path.read_bytes() != original:
                        changed.append(rel_path)
                else:
                    changed.append(rel_path)  # 文件被删除也算变更
        return changed

    def __enter__(self) -> "GitSandbox":
        self.snapshot()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        # 异常时自动回滚，正常退出不自动操作（由调用方决定 commit/rollback）
        if exc_type is not None:
            self.rollback()
        return False  # 不吞异常


def is_git_clean(root: Path = _ROOT) -> bool:
    """检查工作区是否干净（无未提交变更）"""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(root), capture_output=True, text=True,
        )
        return result.stdout.strip() == ""
    except Exception:
        return False


def get_tracked_status(files: List[str], root: Path = _ROOT) -> Dict[str, str]:
    """
    获取文件列表的 git 追踪状态。

    Returns:
        { rel_path -> "tracked" | "untracked" | "not_exists" }
    """
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=str(root), capture_output=True, text=True,
        )
        tracked_set = set(result.stdout.splitlines())
    except Exception:
        tracked_set = set()

    status = {}
    for f in files:
        abs_path = root / f
        if not abs_path.exists():
            status[f] = "not_exists"
        elif f in tracked_set:
            status[f] = "tracked"
        else:
            status[f] = "untracked"
    return status
