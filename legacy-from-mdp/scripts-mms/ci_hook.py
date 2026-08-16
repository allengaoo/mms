#!/usr/bin/env python3
"""
MMS CI/CD 集成钩子生成器

功能：
  install  — 安装 .git/hooks/pre-commit（自动校验变更的记忆文件）
  remove   — 移除已安装的 hook
  check    — 手动执行校验（CI pipeline 中使用，失败时 exit(1)）

用法：
  python scripts/mms/ci_hook.py install   # 本地开发：安装 pre-commit hook
  python scripts/mms/ci_hook.py remove    # 移除 hook
  python scripts/mms/ci_hook.py check     # CI 中使用：校验所有记忆文件
"""
import os
import stat
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_HOOK_FILE = _PROJECT_ROOT / ".git" / "hooks" / "pre-commit"

_HOOK_CONTENT = """\
#!/bin/sh
# MMS pre-commit hook — 自动校验变更的记忆文件 Schema
# 由 python scripts/mms/ci_hook.py install 生成

python scripts/mms/validate.py --changed-only
if [ $? -ne 0 ]; then
  echo ""
  echo "❌ 记忆文件 Schema 校验失败，请修复上述错误后再提交。"
  echo "💡 修复提示："
  echo "   · 缺少 version 字段？运行：python scripts/mms/validate.py --migrate-add-version"
  echo "   · 查看 Schema 规则：docs/memory/_system/schema.json"
  echo "   · 贡献指南：docs/memory/CONTRIBUTING.md"
  exit 1
fi
"""


def install() -> None:
    if not (_PROJECT_ROOT / ".git").exists():
        print("❌ 当前目录不是 git 仓库根目录")
        sys.exit(1)

    _HOOK_FILE.parent.mkdir(parents=True, exist_ok=True)

    if _HOOK_FILE.exists():
        backup = _HOOK_FILE.with_suffix(".pre-mms.bak")
        _HOOK_FILE.rename(backup)
        print(f"⚠️  已备份原有 pre-commit hook 到: {backup.name}")

    _HOOK_FILE.write_text(_HOOK_CONTENT, encoding="utf-8")
    current_mode = _HOOK_FILE.stat().st_mode
    _HOOK_FILE.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"✅ pre-commit hook 已安装: {_HOOK_FILE}")
    print("   每次 git commit 时将自动校验变更的记忆文件。")


def remove() -> None:
    if not _HOOK_FILE.exists():
        print("ℹ️  未找到 MMS pre-commit hook，无需移除")
        return

    content = _HOOK_FILE.read_text(encoding="utf-8")
    if "MMS pre-commit hook" not in content:
        print("⚠️  当前 pre-commit hook 非 MMS 生成，跳过移除以避免误删")
        return

    backup = _HOOK_FILE.with_suffix(".mms.bak")
    _HOOK_FILE.rename(backup)
    print(f"✅ MMS pre-commit hook 已移除（备份到 {backup.name}）")

    original_backup = _HOOK_FILE.with_suffix(".pre-mms.bak")
    if original_backup.exists():
        original_backup.rename(_HOOK_FILE)
        print(f"✅ 已恢复原有 pre-commit hook")


def check() -> None:
    """CI 模式：校验全部记忆文件，失败时 exit(1)"""
    result = subprocess.run(
        [sys.executable, "scripts/mms/validate.py"],
        cwd=str(_PROJECT_ROOT),
    )
    sys.exit(result.returncode)


def main() -> None:
    args = sys.argv[1:]

    if not args or args[0] not in ("install", "remove", "check"):
        print("用法：python scripts/mms/ci_hook.py [install|remove|check]")
        print("  install — 安装 pre-commit hook")
        print("  remove  — 移除 pre-commit hook")
        print("  check   — 校验所有记忆文件（CI 使用）")
        sys.exit(1)

    {"install": install, "remove": remove, "check": check}[args[0]]()


if __name__ == "__main__":
    main()
