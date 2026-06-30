from __future__ import annotations

"""兼容性包装器。

历史上 Stage91 独立 runner 缺失，但 Stage90 脚本本身会同时生成
stage90_mainline_event_alpha_matrix_latest.* 与
stage91_branch_event_alpha_matrix_latest.*。

这个模块只做一件事：复用 Stage90 主流程，保证旧脚本引用
`python -m tools.stage91_branch_event_alpha_matrix` 时不再报缺文件。
"""

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.stage90_event_alpha_matrix import main as _stage90_main


def main() -> None:
    _stage90_main()


if __name__ == "__main__":
    main()
