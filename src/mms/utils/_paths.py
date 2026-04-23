"""
_paths.py — MMS 项目路径解析（独立项目兼容）

提供 get_project_root() 函数，支持两种运行模式：
  1. 独立项目：<repo>/        （mms 作为仓库根目录）
  2. 嵌入模式：<monorepo>/scripts/mms/（mms 嵌入其他项目）

路径解析策略（按优先级）：
  1. 环境变量 MMS_PROJECT_ROOT 指定的路径（最高优先级，CI/Docker 使用）
  2. 当前 mms 目录本身（如果包含 docs/memory/ 目录，说明是独立项目）
  3. 父目录的父目录（scripts/mms/ → project root，兼容 MDP 嵌入模式）
  4. 当前 mms 目录（兜底，即使没有 docs/ 也能运行）

使用方式：
    from mms.utils._paths import get_project_root
    _ROOT = get_project_root()
"""
from __future__ import annotations

import os
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _is_valid_project_root(path: Path) -> bool:
    """
    判断给定路径是否是有效的 MMS 项目根（含 docs/memory/shared/ 和 docs/execution_plans/）。
    用 shared/ 和 execution_plans/ 双重判断，避免误匹配 Cursor 的记忆目录（仅有 _system/private/）。
    """
    return (
        (path / "docs" / "memory" / "shared").exists()
        or (path / "docs" / "execution_plans").exists()
        or (path / "docs" / "specs").exists()
        or (path / "docs" / "models").exists()
    )


def get_project_root() -> Path:
    """
    获取 MMS 当前运行时的项目根目录。

    独立项目模式：返回 mms/ 项目根（docs/memory/shared/ 在其下）
    嵌入 MDP 模式：返回 mdp-xxx/ 目录（docs/memory/shared/ 在 mdp-xxx/docs/memory/shared/）

    src/mms/ 布局下，_HERE = src/mms/utils/，项目根在 parents[2]（即 mms/project root）。
    """
    # 优先级 1：环境变量
    env_root = os.environ.get("MMS_PROJECT_ROOT")
    if env_root:
        p = Path(env_root)
        if p.exists():
            return p

    # 优先级 2–5：逐级向上查找包含 docs/ 的目录
    for candidate in [_HERE, _HERE.parent, _HERE.parent.parent, _HERE.parent.parent.parent]:
        if _is_valid_project_root(candidate):
            return candidate

    # 兜底：返回 mms 包所在的祖先目录
    return _HERE.parent.parent.parent


# 缓存，避免重复解析
_PROJECT_ROOT: Path = get_project_root()

# 常用路径快捷方式
DOCS_MEMORY = _PROJECT_ROOT / "docs" / "memory"
DOCS_MEMORY_SYSTEM = _PROJECT_ROOT / "docs" / "memory" / "_system"
DOCS_MEMORY_SHARED = _PROJECT_ROOT / "docs" / "memory" / "shared"
DOCS_EXECUTION_PLANS = _PROJECT_ROOT / "docs" / "execution_plans"
MMS_ROOT = _HERE.parent.parent  # MMS 代码根目录（src/mms/）
