#!/usr/bin/env python3
"""
benchmark_generator.py — Benchmark 逆向合成数据管道

从 Git commit diff 逆向生成 Layer 2 记忆质量测试 case。

核心流程：
  1. 扫描目标仓库的 Git commit（筛选 fix:/feat: 前缀）
  2. 提取 commit 的代码 diff 和修改文件路径
  3. 调用 Qwen3-32B 逆向生成用户意图描述（业务自然语言）
  4. 将生成结果写入 benchmark/v2/layer2_memory/tasks/synthetic/ 目录

防过拟合设计：
  - 生成的 case 打 source: synthetic 标记，默认不参与主评测
  - 人工审核后才能改为 reviewed: true，才会被 runner 执行
  - 合成 case 永远不会替换 human case，只作为扩充
  - 评测报告单独区分 human/synthetic 的得分

使用方式：
  python3 scripts/benchmark_generator.py --repo /path/to/java-project --max 50
  python3 scripts/benchmark_generator.py --repo . --domain generic_python --dry-run

审核工作流：
  生成后，运行 mulan benchmark review-synthetic 交互式审核
  或手动编辑 YAML 文件将 reviewed: false 改为 reviewed: true
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

_OUTPUT_DIR = _REPO / "benchmark" / "v2" / "layer2_memory" / "tasks" / "synthetic"

# ── ANSI 颜色 ─────────────────────────────────────────────────────────────────
_GREEN  = "\033[92m"
_YELLOW = "\033[93m"
_BLUE   = "\033[94m"
_RED    = "\033[91m"
_RESET  = "\033[0m"
_BOLD   = "\033[1m"


# ── Git 操作 ──────────────────────────────────────────────────────────────────

def get_relevant_commits(repo_path: Path, max_commits: int = 100) -> List[Dict[str, str]]:
    """
    获取 fix:/feat: 前缀的 commit 列表。
    返回 [{hash, subject, author_date}] 列表。
    """
    result = subprocess.run(
        [
            "git", "log",
            "--format=%H|%s|%ai",
            "--diff-filter=M",
            f"-{max_commits * 3}",  # 多取一些，筛选后取 max_commits
        ],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        print(f"{_RED}git log 失败: {result.stderr}{_RESET}")
        return []

    commits = []
    for line in result.stdout.strip().splitlines():
        if "|" not in line:
            continue
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        hash_, subject, date = parts
        # 只取 fix:/feat:/refactor: 前缀的 commit
        if re.match(r'^(fix|feat|refactor|perf)[\(:]', subject, re.IGNORECASE):
            commits.append({"hash": hash_, "subject": subject, "date": date})
            if len(commits) >= max_commits:
                break

    return commits


def get_commit_diff(repo_path: Path, commit_hash: str, max_chars: int = 3000) -> Optional[str]:
    """提取 commit 的代码 diff（截断到 max_chars）。"""
    result = subprocess.run(
        ["git", "show", "--stat", "--patch", "-U2", commit_hash],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        return None
    return result.stdout[:max_chars]


def get_modified_files(repo_path: Path, commit_hash: str) -> List[str]:
    """获取 commit 修改的文件路径列表。"""
    result = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "-r", "--name-only", commit_hash],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return []
    return [f.strip() for f in result.stdout.splitlines() if f.strip()]


# ── LLM 逆向意图生成 ─────────────────────────────────────────────────────────

def generate_intent(diff: str, subject: str) -> Optional[str]:
    """
    调用 Qwen3-32B 从 diff 逆向生成用户意图描述。
    LLM 不可用时返回 None（case 标记为 needs_review）。
    """
    prompt = f"""你是一个高级架构师，正在分析代码变更。

commit 标题：{subject}

代码 diff（片段）：
```
{diff[:2000]}
```

任务：用一句话描述开发者修改这段代码时的业务意图（从用户视角，自然语言）。
格式：直接输出一句指令，如"给用户服务增加 Redis 缓存，避免重复查询数据库"
不要输出解释性文字，只输出意图描述本身。"""

    try:
        from mms.llm.bailian_provider import BailianProvider
        provider = BailianProvider()
        result = provider.chat(prompt, model="qwen3-32b", max_tokens=100)
        return result.strip() if result else None
    except Exception:
        return None


# ── Case 生成 ─────────────────────────────────────────────────────────────────

def generate_case(
    commit: Dict[str, str],
    repo_path: Path,
    domain: str,
    use_llm: bool = False,
) -> Optional[Dict[str, Any]]:
    """从单个 commit 生成一个 benchmark case。"""
    diff = get_commit_diff(repo_path, commit["hash"])
    if not diff:
        return None

    modified_files = get_modified_files(repo_path, commit["hash"])
    if not modified_files:
        return None

    # 尝试 LLM 生成意图
    intent = None
    if use_llm:
        intent = generate_intent(diff, commit["subject"])

    # LLM 不可用时，用 commit subject 作为意图（需人工审核改写）
    if not intent:
        intent = f"[需审核] {commit['subject']}"

    case_id = f"synthetic_{domain}_{uuid.uuid4().hex[:8]}"
    return {
        "case_id": case_id,
        "domain": domain,
        "source": "synthetic",
        "reviewed": False,       # 人工审核前不参与主评测
        "generated_at": datetime.now().strftime("%Y-%m-%d"),
        "commit_hash": commit["hash"][:12],
        "commit_subject": commit["subject"],
        "task": {
            "query": intent,
            "expected_file_mentions": modified_files[:5],  # Ground truth
            "difficulty": "medium",
        },
        "retrieval": {
            "relevant_ids": [],  # 留空，等记忆系统建立后手动/自动填充
            "top_k": 5,
        },
    }


# ── YAML 输出 ─────────────────────────────────────────────────────────────────

def write_cases(cases: List[Dict[str, Any]], domain: str, dry_run: bool = False) -> Path:
    """将生成的 case 写入 YAML 文件。"""
    output_dir = _OUTPUT_DIR / domain
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"synthetic_{timestamp}.yaml"

    yaml_lines = [
        "# 自动生成的合成 Benchmark 数据",
        f"# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "# 注意：reviewed: false 的 case 不参与主评测，需人工审核后改为 reviewed: true",
        "",
        "cases:",
    ]

    for case in cases:
        yaml_lines.append(f"  - case_id: {case['case_id']}")
        yaml_lines.append(f"    domain: {case['domain']}")
        yaml_lines.append(f"    source: synthetic")
        yaml_lines.append(f"    reviewed: false")
        yaml_lines.append(f"    generated_at: '{case['generated_at']}'")
        yaml_lines.append(f"    commit_hash: '{case['commit_hash']}'")
        safe_subject = case['commit_subject'].replace('"', "'")
        yaml_lines.append(f"    commit_subject: \"{safe_subject}\"")
        yaml_lines.append(f"    task:")
        safe_query = case['task']['query'].replace('"', "'")
        yaml_lines.append(f"      query: \"{safe_query}\"")
        yaml_lines.append(f"      difficulty: {case['task']['difficulty']}")
        yaml_lines.append(f"      expected_file_mentions:")
        for f in case["task"]["expected_file_mentions"]:
            yaml_lines.append(f"        - \"{f}\"")
        yaml_lines.append(f"    retrieval:")
        yaml_lines.append(f"      relevant_ids: []")
        yaml_lines.append(f"      top_k: {case['retrieval']['top_k']}")
        yaml_lines.append("")

    content = "\n".join(yaml_lines)

    if dry_run:
        print(f"\n{_BOLD}[dry-run] 将写入:{_RESET} {output_file}")
        print(content[:500] + ("..." if len(content) > 500 else ""))
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file.write_text(content, encoding="utf-8")
        print(f"{_GREEN}✓ 写入 {len(cases)} 个 case → {output_file}{_RESET}")

    return output_file


# ── 主函数 ────────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="从 Git commit 逆向生成 Benchmark 测试 case",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--repo", default=".",
        help="目标 Git 仓库路径（默认：当前目录）",
    )
    parser.add_argument(
        "--max", type=int, default=20,
        help="最多生成 case 数量（默认 20）",
    )
    parser.add_argument(
        "--domain", default="generic_python",
        help="benchmark domain 标签（默认 generic_python）",
    )
    parser.add_argument(
        "--llm", action="store_true",
        help="调用 LLM 生成意图描述（需配置百炼 API Key）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只预览，不写入文件",
    )
    args = parser.parse_args(argv)

    repo_path = Path(args.repo).resolve()
    if not (repo_path / ".git").exists():
        print(f"{_RED}错误: {repo_path} 不是 Git 仓库{_RESET}")
        return 1

    print(f"\n{_BOLD}Benchmark 合成数据生成器{_RESET}")
    print(f"  仓库: {repo_path}")
    print(f"  目标 case 数: {args.max}")
    print(f"  domain: {args.domain}")
    print(f"  LLM 模式: {'启用' if args.llm else '禁用（使用 commit subject 作为意图）'}")

    # 1. 获取候选 commit
    print(f"\n{_BLUE}▶ 扫描 Git commit...{_RESET}")
    commits = get_relevant_commits(repo_path, max_commits=args.max * 2)
    if not commits:
        print(f"{_YELLOW}未找到符合条件的 commit（fix:/feat: 前缀）{_RESET}")
        return 0
    print(f"  找到 {len(commits)} 个候选 commit")

    # 2. 生成 case
    print(f"\n{_BLUE}▶ 生成 case...{_RESET}")
    cases = []
    for i, commit in enumerate(commits[:args.max]):
        case = generate_case(commit, repo_path, args.domain, use_llm=args.llm)
        if case:
            cases.append(case)
            status = "✓" if not case["task"]["query"].startswith("[需审核]") else "⚡"
            print(f"  {status} [{i+1}/{args.max}] {commit['hash'][:8]} — {commit['subject'][:50]}")

    if not cases:
        print(f"{_YELLOW}没有成功生成任何 case{_RESET}")
        return 0

    # 3. 写入
    write_cases(cases, args.domain, dry_run=args.dry_run)

    print(f"\n{_BOLD}完成！{_RESET}")
    print(f"  生成: {len(cases)} 个 case（全部标记为 reviewed: false）")
    print(f"  审核: 运行 mulan benchmark review-synthetic 进行人工审核")
    print(f"  或: 手动编辑 YAML 文件将 reviewed: false 改为 reviewed: true")
    return 0


if __name__ == "__main__":
    sys.exit(main())
