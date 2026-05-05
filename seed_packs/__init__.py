"""
seed_packs — MMS 种子包注册中心（EP-130）

设计参考：squads-cli 的 "Everything is a file, packs are directories" 哲学。
每个种子包是一个独立目录，包含可以直接 shutil.copytree 复制的文件树。

目录结构：
  seed_packs/
    base/                    ← 通用基础约束（所有项目必注入）
    fastapi_sqlmodel/        ← FastAPI + SQLModel 后端栈
    fastapi_kafka/           ← Kafka 消息队列栈
    react_zustand/           ← React + Zustand 前端栈
    palantir_arch/           ← Palantir 风格分层架构约束

每个目录下必须有：
  match_conditions.yaml    ← 由 dep_sniffer 读取，决定是否激活此包
  docs/memory/shared/      ← 直接 copytree 到目标项目的记忆文件

EP-130 | 2026-04-18
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import List, Optional

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent.parent

try:
    sys.path.insert(0, str(_HERE.parent))
    from mms_config import cfg as _cfg  # type: ignore[import]
except (ImportError, AttributeError):
    _cfg = None


def get_pack_dir(pack_name: str) -> Path:
    """返回种子包目录的绝对路径。"""
    return _HERE / pack_name


def list_packs() -> List[str]:
    """列出所有可用的种子包名称。"""
    return [
        d.name for d in _HERE.iterdir()
        if d.is_dir() and not d.name.startswith("_") and not d.name.startswith(".")
    ]


def install_packs(
    pack_names: List[str],
    target_docs: Path,
    dry_run: bool = False,
) -> List[str]:
    """
    将指定种子包的 docs/ 目录内容复制到目标 docs/ 目录。
    squads-cli 风格：shutil.copytree，无解析器，无代码生成。

    Returns:
        安装成功的包名列表
    """
    installed = []
    for pack_name in pack_names:
        pack_dir = get_pack_dir(pack_name)
        if not pack_dir.exists():
            continue
        pack_docs = pack_dir / "docs"
        if not pack_docs.exists():
            continue

        if dry_run:
            print(f"  [dry-run] 将注入种子包: {pack_name}")
            installed.append(pack_name)
            continue

        try:
            shutil.copytree(
                str(pack_docs),
                str(target_docs),
                dirs_exist_ok=True,
            )
            installed.append(pack_name)
        except (OSError, shutil.Error) as e:
            import logging
            logging.getLogger(__name__).warning("种子包 %s 安装失败: %s", pack_name, e)

    return installed
