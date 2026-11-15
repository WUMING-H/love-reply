#!/usr/bin/env python3
"""命令行入口薄壳：保持 `python scripts/profile_tool.py ...` 这个调用方式不变。

实现已拆分到 `profile_tool/` 包（storage / render / guard / commands / cli）。
这个文件只做一件事：把调用转给包里的 main。所有文档、CI 里的
`python scripts/profile_tool.py <子命令>` 都继续有效。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 保证 `import profile_tool` 解析到同目录的包，而不是这个同名文件本身。
sys.path.insert(0, str(Path(__file__).resolve().parent))

from profile_tool.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
