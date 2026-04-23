"""
私有记忆隔离协议 — MMS v2.2
=================================
设计原则：
  - 私有记忆 = 单个 EP 执行期间的临时笔记/草稿，生命周期绑定 EP
  - 公有记忆 = 多次蒸馏验证后的稳定知识，存于 shared/
  - 私有记忆禁止跨 EP 直接引用；要共享必须通过 promote 命令升级

目录结构：
  docs/memory/private/
    {ep_id}/
      notes/         临时笔记（.md）
      decisions/     本 EP 做出的架构决策草稿
      _meta.json     EP 元数据（状态、创建时间、关联的 shared 记忆 ID）

生命周期：
  init   → noting → promote/clean
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# ── 路径常量 ──────────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).parent
_MMS_ROOT   = _SCRIPT_DIR.parent.parent  # 项目根
_PRIVATE_DIR = _MMS_ROOT / "docs" / "memory" / "private"
_SHARED_DIR  = _MMS_ROOT / "docs" / "memory" / "shared"


# ── 辅助：原子写 JSON ─────────────────────────────────────────────────────────
def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


# ── EP ID 校验 ────────────────────────────────────────────────────────────────
_EP_PATTERN = re.compile(r"^EP-\d{3,}$", re.IGNORECASE)


def _validate_ep_id(ep_id: str) -> str:
    ep_id = ep_id.strip().upper()
    if not _EP_PATTERN.match(ep_id):
        raise ValueError(f"EP ID 格式错误: '{ep_id}'，示例: EP-110")
    return ep_id


# ── 核心操作 ──────────────────────────────────────────────────────────────────

def init_ep(ep_id: str, description: str = "") -> Path:
    """
    初始化一个 EP 的私有记忆工作区。
    幂等：已存在时更新 description，不覆盖已有笔记。
    """
    ep_id = _validate_ep_id(ep_id)
    ep_dir = _PRIVATE_DIR / ep_id
    ep_dir.mkdir(parents=True, exist_ok=True)
    (ep_dir / "notes").mkdir(exist_ok=True)
    (ep_dir / "decisions").mkdir(exist_ok=True)

    meta_path = ep_dir / "_meta.json"
    meta = _read_json(meta_path)

    if not meta:
        meta = {
            "ep_id":        ep_id,
            "status":       "active",
            "description":  description,
            "created_at":   datetime.now(timezone.utc).isoformat(),
            "updated_at":   datetime.now(timezone.utc).isoformat(),
            "notes":        [],
            "decisions":    [],
            "promoted_to":  [],   # 已升级到 shared 的记忆 ID
        }
    else:
        if description:
            meta["description"] = description
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()

    _write_json(meta_path, meta)
    return ep_dir


def add_note(ep_id: str, title: str, content: str, note_type: str = "notes") -> Path:
    """
    向 EP 私有工作区添加笔记或决策草稿。
    note_type: 'notes' | 'decisions'
    返回创建的文件路径。
    """
    ep_id  = _validate_ep_id(ep_id)
    ep_dir = _PRIVATE_DIR / ep_id

    if not ep_dir.exists():
        raise FileNotFoundError(
            f"EP {ep_id} 工作区未初始化，请先运行: mms private init {ep_id}"
        )
    if note_type not in ("notes", "decisions"):
        raise ValueError("note_type 必须是 'notes' 或 'decisions'")

    # 生成文件名（时间戳 + slug）
    ts    = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug  = re.sub(r"[^\w\-]", "_", title.lower())[:40]
    fname = f"{ts}_{slug}.md"
    fpath = ep_dir / note_type / fname

    fpath.write_text(
        f"# {title}\n\n"
        f"<!-- ep_id: {ep_id} | created: {datetime.now(timezone.utc).isoformat()} -->\n\n"
        f"{content}\n",
        encoding="utf-8",
    )

    # 更新 _meta.json
    meta = _read_json(ep_dir / "_meta.json")
    meta.setdefault(note_type, []).append(
        {"title": title, "file": str(fpath.relative_to(_MMS_ROOT))}
    )
    meta["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(ep_dir / "_meta.json", meta)

    return fpath


def list_eps(status: Optional[str] = None) -> List[dict]:
    """
    列出所有 EP 私有工作区。
    status: 'active' | 'closed' | None(全部)
    """
    if not _PRIVATE_DIR.exists():
        return []

    result = []
    for ep_dir in sorted(_PRIVATE_DIR.iterdir()):
        if not ep_dir.is_dir():
            continue
        meta_path = ep_dir / "_meta.json"
        if not meta_path.exists():
            continue
        meta = _read_json(meta_path)
        if status and meta.get("status") != status:
            continue
        result.append(meta)
    return result


def promote_note(ep_id: str, note_file: str, target_layer: str, new_id: str) -> Path:
    """
    将私有笔记提升为公有 shared 记忆。
    - note_file: 相对于 private/{ep_id}/ 的文件路径，如 notes/20260412_xxx.md
    - target_layer: 目标层，如 L3_domain/ontology
    - new_id: 新的记忆 ID，如 MEM-L-028

    升级流程：
    1. 将文件复制到 shared/{target_layer}/{new_id}.md
    2. 在 _meta.json 中记录 promoted_to
    3. 原文件保留（供回溯），添加头部注释表明已升级
    """
    ep_id    = _validate_ep_id(ep_id)
    ep_dir   = _PRIVATE_DIR / ep_id
    src_path = ep_dir / note_file

    if not src_path.exists():
        raise FileNotFoundError(f"源文件不存在: {src_path}")

    dst_dir  = _SHARED_DIR / target_layer
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst_path = dst_dir / f"{new_id}.md"

    if dst_path.exists():
        raise FileExistsError(f"目标文件已存在: {dst_path}，请确认 new_id 是否重复")

    # 复制文件
    shutil.copy2(src_path, dst_path)

    # 在原文件头部标记已升级
    original = src_path.read_text(encoding="utf-8")
    src_path.write_text(
        f"<!-- ⬆️  已升级: 公有记忆 {new_id} @ shared/{target_layer}/{new_id}.md -->\n\n"
        + original,
        encoding="utf-8",
    )

    # 更新 _meta.json
    meta = _read_json(ep_dir / "_meta.json")
    meta.setdefault("promoted_to", []).append(
        {
            "source_file": note_file,
            "target_id":   new_id,
            "target_file": f"shared/{target_layer}/{new_id}.md",
            "promoted_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    meta["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(ep_dir / "_meta.json", meta)

    return dst_path


def close_ep(ep_id: str, keep_promoted: bool = True) -> None:
    """
    关闭 EP 工作区。
    - keep_promoted=True: 清理未升级的笔记，保留已升级记录
    - keep_promoted=False: 完全删除（谨慎使用）
    """
    ep_id  = _validate_ep_id(ep_id)
    ep_dir = _PRIVATE_DIR / ep_id

    if not ep_dir.exists():
        raise FileNotFoundError(f"EP {ep_id} 工作区不存在")

    meta = _read_json(ep_dir / "_meta.json")
    promoted_count = len(meta.get("promoted_to", []))

    if keep_promoted:
        # 删除 notes/ 和 decisions/ 下未升级的文件
        promoted_files = {
            item["source_file"] for item in meta.get("promoted_to", [])
        }
        for subdir in ("notes", "decisions"):
            subpath = ep_dir / subdir
            if subpath.exists():
                for f in subpath.iterdir():
                    rel = f"{subdir}/{f.name}"
                    if rel not in promoted_files:
                        f.unlink()
        meta["status"]     = "closed"
        meta["closed_at"]  = datetime.now(timezone.utc).isoformat()
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(ep_dir / "_meta.json", meta)
    else:
        shutil.rmtree(ep_dir)

    return promoted_count
