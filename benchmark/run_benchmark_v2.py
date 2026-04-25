#!/usr/bin/env python3
"""
Mulan Benchmark v2 — 独立运行入口

用法：
  python benchmark/run_benchmark_v2.py                         # 离线模式
  python benchmark/run_benchmark_v2.py --level fast            # 记忆质量 + 安全门控
  python benchmark/run_benchmark_v2.py --level full --llm      # 全量（需 LLM API）
  python benchmark/run_benchmark_v2.py --layer 3 --verbose     # 仅安全门控，详细输出
  python benchmark/run_benchmark_v2.py --output markdown --output-path reports/bench.md
"""
import sys
from pathlib import Path

# 确保项目根和 src/ 在模块搜索路径中
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from benchmark.v2.runner import main

if __name__ == "__main__":
    sys.exit(main())
