#!/usr/bin/env python3
"""
MMS 记忆文件 Schema 校验器

用途：
  - pre-commit hook：提交前自动校验变更的 MEM-*.md 文件
  - CI/CD 检查：验证整个记忆库的 Schema 合规性
  - 迁移工具：批量为旧文件添加 version: 1 字段

用法：
  python scripts/mms/validate.py                     # 校验所有记忆文件
  python scripts/mms/validate.py --changed-only      # 只校验 git diff 变更文件
  python scripts/mms/validate.py --file MEM-L-010    # 校验单个文件（ID 或路径）
  python scripts/mms/validate.py --migrate-add-version  # 批量添加 version: 1

退出码：
  0 — 全部通过
  1 — 有文件校验失败
  2 — 工具自身错误（Schema 文件不存在等）
"""
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_MEMORY_ROOT = Path(__file__).parent.parent.parent / "docs" / "memory"
_SCHEMA_FILE = _MEMORY_ROOT / "_system" / "schema.json"

_REQUIRED_FIELDS = ["id", "layer", "dimension", "type", "tier", "tags", "source_ep", "created_at", "version"]
# 接受短格式（L2）和长格式（L2_infrastructure）
_VALID_LAYERS = {"L1", "L2", "L3", "L4", "L5", "CC", "BIZ",
                 "L1_platform", "L2_infrastructure", "L3_domain",
                 "L4_application", "L5_interface", "cross_cutting"}
_VALID_TYPES = {
    "lesson", "decision", "error", "pattern", "skill",
    # BIZ 层专属类型
    "business-flow", "actor-model", "constraint", "edge-case",
}
_VALID_TIERS = {"hot", "warm", "cold", "archive"}
# 接受标准前缀和遗留前缀 MEM-DB（EP-107 迁移时使用）；ENV 前缀用于部署环境快照记忆
_ID_PATTERN = re.compile(r"^(MEM-L|MEM-E|MEM-DB|AD|PAT|SKL|BIZ|ENV)-[0-9A-Z][0-9A-Z-]*$")
_EP_PATTERN = re.compile(r"^EP-[0-9]+$")
_DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def parse_frontmatter(content: str) -> Optional[Dict]:
    """提取并解析 YAML front-matter（不依赖 pyyaml，手动解析）"""
    if not content.startswith("---"):
        return None
    lines = content.split("\n")
    end_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return None

    fm: Dict = {}
    for line in lines[1:end_idx]:
        if not line.strip() or line.strip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, raw_val = line.partition(":")
        key = key.strip()
        raw_val = raw_val.strip()

        # 处理数组（简单格式：[a, b, c]）
        if raw_val.startswith("[") and raw_val.endswith("]"):
            inner = raw_val[1:-1]
            items = [v.strip().strip("\"'") for v in inner.split(",") if v.strip()]
            fm[key] = items
        # 布尔值
        elif raw_val.lower() in ("true", "false"):
            fm[key] = raw_val.lower() == "true"
        # 整数
        elif raw_val.lstrip("-").isdigit():
            fm[key] = int(raw_val)
        # 字符串（去引号）
        else:
            fm[key] = raw_val.strip("\"'")

    return fm


def validate_frontmatter(fm: Dict, filepath: Path) -> List[str]:
    """
    校验 front-matter 内容，返回错误列表（空列表=通过）。
    """
    errors: List[str] = []

    # 必填字段
    for field in _REQUIRED_FIELDS:
        if field not in fm:
            errors.append(f"缺少必填字段: '{field}'")

    if "id" in fm:
        if not _ID_PATTERN.match(str(fm["id"])):
            errors.append(f"id 格式错误: '{fm['id']}'（应匹配 MEM-L/MEM-E/AD/PAT/SKL-xxx）")

    if "layer" in fm and fm["layer"] not in _VALID_LAYERS:
        errors.append(f"layer 值非法: '{fm['layer']}'（合法值: {sorted(_VALID_LAYERS)}）")

    if "type" in fm and fm["type"] not in _VALID_TYPES:
        errors.append(f"type 值非法: '{fm['type']}'（合法值: {sorted(_VALID_TYPES)}）")

    if "tier" in fm and fm["tier"] not in _VALID_TIERS:
        errors.append(f"tier 值非法: '{fm['tier']}'（合法值: {sorted(_VALID_TIERS)}）")

    if "tags" in fm:
        if not isinstance(fm["tags"], list) or len(fm["tags"]) == 0:
            errors.append("tags 必须是非空数组")

    if "source_ep" in fm and not _EP_PATTERN.match(str(fm["source_ep"])):
        errors.append(f"source_ep 格式错误: '{fm['source_ep']}'（应为 EP-NNN）")

    if "created_at" in fm and not _DATE_PATTERN.match(str(fm["created_at"])):
        errors.append(f"created_at 格式错误: '{fm['created_at']}'（应为 YYYY-MM-DD）")

    if "version" in fm:
        if not isinstance(fm["version"], int) or fm["version"] < 1:
            errors.append(f"version 必须是 ≥1 的整数，当前: '{fm['version']}'")

    return errors


def find_all_memory_files() -> List[Path]:
    """查找 docs/memory/ 下所有 MEM-*.md 和 AD-*.md 文件"""
    files = []
    for pattern in ("MEM-*.md", "AD-*.md", "PAT-*.md", "SKL-*.md", "BIZ-*.md", "ENV-*.md"):
        files.extend(_MEMORY_ROOT.rglob(pattern))
    return [f for f in files if "_system" not in f.parts and "archive" not in f.parts]


def find_changed_files() -> List[Path]:
    """通过 git diff 找出当前暂存或未暂存的变更记忆文件"""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, cwd=_MEMORY_ROOT.parent.parent
        )
        changed = result.stdout.strip().splitlines()
        result2 = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True, text=True, cwd=_MEMORY_ROOT.parent.parent
        )
        changed += result2.stdout.strip().splitlines()

        memory_files = []
        for path_str in set(changed):
            if "docs/memory" in path_str and path_str.endswith(".md"):
                full = _MEMORY_ROOT.parent.parent / path_str
                if full.exists():
                    memory_files.append(full)
        return memory_files
    except Exception as e:
        print(f"⚠️  git diff 失败: {e}，回退到全量校验")
        return find_all_memory_files()


def migrate_add_version(files: List[Path]) -> Tuple[int, int]:
    """批量为缺少 version 字段的文件添加 version: 1"""
    added, skipped = 0, 0
    for fpath in files:
        content = fpath.read_text(encoding="utf-8")
        fm = parse_frontmatter(content)
        if fm is None or "version" in fm:
            skipped += 1
            continue
        # 在 created_at 行之后插入 version: 1
        new_content = re.sub(
            r"(created_at:.*\n)",
            r"\1version: 1\n",
            content,
            count=1
        )
        if new_content == content:
            # 没找到 created_at，在 --- 闭合前插入
            new_content = content.replace(
                "\n---\n", "\nversion: 1\n---\n", 1
            )
        from pathlib import Path as _P
        tmp = fpath.with_suffix(".tmp")
        tmp.write_text(new_content, encoding="utf-8")
        import os
        os.rename(tmp, fpath)
        added += 1
    return added, skipped


def run_validation(files: List[Path]) -> bool:
    """执行校验，输出结果，返回 True=全部通过"""
    passed = failed = 0
    seen_ids: Dict[str, Path] = {}

    for fpath in sorted(files):
        content = fpath.read_text(encoding="utf-8")
        fm = parse_frontmatter(content)

        if fm is None:
            print(f"❌ {fpath.name}: 缺少 YAML front-matter（文件应以 --- 开头）")
            failed += 1
            continue

        errors = validate_frontmatter(fm, fpath)

        # 唯一性检查
        mem_id = fm.get("id", "")
        if mem_id and mem_id in seen_ids:
            errors.append(f"id '{mem_id}' 与 {seen_ids[mem_id].name} 重复")
        elif mem_id:
            seen_ids[mem_id] = fpath

        if errors:
            print(f"❌ {fpath.name}:")
            for err in errors:
                print(f"   · {err}")
            failed += 1
        else:
            tier = fm.get("tier", "?")
            tags_count = len(fm.get("tags", []))
            ver = fm.get("version", "?")
            print(f"✅ {fpath.name}  (tier={tier}, tags={tags_count}, version={ver})")
            passed += 1

    print(f"\n{'='*50}")
    print(f"校验完成：{passed + failed} 个文件，{passed} 通过，{failed} 失败")
    return failed == 0


def main() -> int:
    args = sys.argv[1:]

    if "--migrate-add-version" in args:
        files = find_all_memory_files()
        print(f"🔧 迁移：为 {len(files)} 个文件添加 version: 1（已有则跳过）...")
        added, skipped = migrate_add_version(files)
        print(f"✅ 已添加: {added}，已跳过（已有 version）: {skipped}")
        return 0

    if "--file" in args:
        idx = args.index("--file")
        target = args[idx + 1] if idx + 1 < len(args) else ""
        matches = [f for f in find_all_memory_files() if target in f.name]
        if not matches:
            print(f"❌ 未找到文件: {target}")
            return 2
        files = matches
    elif "--changed-only" in args:
        files = find_changed_files()
        if not files:
            print("✅ 无变更的记忆文件，校验跳过")
            return 0
        print(f"🔍 检测到 {len(files)} 个变更文件...")
    else:
        files = find_all_memory_files()
        print(f"🔍 校验全部 {len(files)} 个记忆文件...")

    ok = run_validation(files)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
