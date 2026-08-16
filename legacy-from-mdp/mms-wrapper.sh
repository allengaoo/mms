#!/usr/bin/env python3
"""
mms — MDP Memory System CLI 入口包装器

将此文件放在项目根目录，直接运行：
  ./mms status
  ./mms distill --ep EP-109
  ./mms search kafka replication

或通过 Python 运行：
  python mms status

嵌入到其他项目：
  1. 复制整个 scripts/mms/ 目录到目标项目
  2. 复制此 mms 文件到目标项目根目录
  3. 确保 docs/memory/ 目录结构已初始化
"""
import sys
from pathlib import Path

# 使 scripts/ 目录可被 import
_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT / "scripts"))

from mms.cli import main

if __name__ == "__main__":
    sys.exit(main())
