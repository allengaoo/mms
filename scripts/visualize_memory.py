#!/usr/bin/env python3
"""
visualize_memory.py — MMS 记忆图谱诊断页面生成器

生成一个自包含的 HTML 文件，包含：
  - Tab 1: 记忆图谱（vis-network 交互图）
  - Tab 2: AST 文件树视图
  - Tab 3: AST↔记忆节点映射表

用法：
    python3 scripts/visualize_memory.py                          # 默认输出到 memory_viz.html
    python3 scripts/visualize_memory.py -o /tmp/viz.html         # 指定输出路径
    python3 scripts/visualize_memory.py --memory-root docs/memory --project MyApp
    python3 scripts/visualize_memory.py --open                   # 生成后自动用浏览器打开
"""

import argparse
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent

# 把 src/ 加入 Python 路径（本地开发用）
sys.path.insert(0, str(_PROJECT_ROOT / "src"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="生成 MMS 记忆图谱诊断 HTML 页面",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "-o", "--output",
        default="memory_viz.html",
        help="输出 HTML 文件路径（默认: memory_viz.html）",
    )
    parser.add_argument(
        "--memory-root",
        default=None,
        help="记忆目录路径（默认: <project_root>/docs/memory）",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="项目名称（用于页面标题，默认取目录名）",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="生成完成后自动在浏览器中打开",
    )
    parser.add_argument(
        "--title",
        default="MMS 记忆图谱诊断",
        help="HTML 页面标题（默认: 'MMS 记忆图谱诊断'）",
    )

    args = parser.parse_args()

    # 解析路径
    memory_root = Path(args.memory_root) if args.memory_root else _PROJECT_ROOT / "docs" / "memory"
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path

    project_name = args.project or _PROJECT_ROOT.name

    if not memory_root.exists():
        print(f"❌ 记忆目录不存在: {memory_root}", file=sys.stderr)
        sys.exit(1)

    print(f"📂 扫描记忆目录: {memory_root}")

    # 导入诊断模块
    try:
        from mms.diagnostics.memory_viz import MemoryVizCollector
        from mms.diagnostics.html_renderer import render_html
    except ImportError as e:
        print(f"❌ 无法导入诊断模块: {e}", file=sys.stderr)
        print("请确保已安装项目依赖，或从项目根目录运行。", file=sys.stderr)
        sys.exit(1)

    # 收集数据
    collector = MemoryVizCollector(memory_root=memory_root, project_root=_PROJECT_ROOT)
    data = collector.collect(project_name=project_name)

    print(
        f"✅ 收集完成: {data.stats['total_nodes']} 节点 | "
        f"{data.stats['total_edges']} 边 | "
        f"{data.stats['total_ast_mappings']} AST 映射"
    )

    drift_count = data.stats.get("drift_count", 0)
    if drift_count > 0:
        print(f"⚠️  检测到 {drift_count} 个 AST drift 节点，请及时更新记忆。")

    layer_dist = data.stats.get("layer_distribution", {})
    if layer_dist:
        dist_str = " | ".join(f"{k}:{v}" for k, v in sorted(layer_dist.items()))
        print(f"📊 层分布: {dist_str}")

    # 渲染 HTML
    html_content = render_html(data, title=args.title)

    # 写入文件
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding="utf-8")
    print(f"📄 已生成: {output_path}  ({len(html_content) // 1024} KB)")

    # 可选：自动打开浏览器
    if args.open:
        _open_browser(output_path)


def _open_browser(path: Path) -> None:
    url = f"file://{path.resolve()}"
    print(f"🌐 正在打开浏览器: {url}")
    try:
        import platform
        system = platform.system()
        if system == "Darwin":
            subprocess.run(["open", url], check=False)
        elif system == "Linux":
            subprocess.run(["xdg-open", url], check=False)
        elif system == "Windows":
            subprocess.run(["start", url], shell=True, check=False)
        else:
            print(f"⚠️  未知操作系统，请手动打开: {url}")
    except Exception as e:
        print(f"⚠️  无法自动打开浏览器: {e}，请手动打开: {url}")


if __name__ == "__main__":
    main()
