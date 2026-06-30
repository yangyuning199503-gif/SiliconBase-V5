#!/usr/bin/env python3
"""
修复 .venv 的 pyvenv.cfg，使其指向项目内的本地 Python 解释器。

用途：项目被打包移动到别的目录后，运行此脚本即可让 .venv 重新可用，
      无需重新下载依赖。
"""
from __future__ import annotations

import sys
from pathlib import Path


def repair() -> None:
    project_root = Path(__file__).parent.parent.resolve()
    venv_dir = project_root / ".venv"
    pyvenv_cfg = venv_dir / "pyvenv.cfg"
    python_home = project_root / ".python" / "cpython-3.10-windows-x86_64-none"

    if not python_home.exists():
        print(f"[repair_venv] 错误：未找到项目内 Python 解释器: {python_home}")
        print("[repair_venv] 请先复制 Python 解释器到 .python/ 目录")
        sys.exit(1)

    if not pyvenv_cfg.exists():
        print(f"[repair_venv] 错误：未找到 {pyvenv_cfg}")
        sys.exit(1)

    lines = pyvenv_cfg.read_text(encoding="utf-8").splitlines()
    new_lines = []
    changed = False
    for line in lines:
        if line.startswith("home ="):
            old_home = line.split("=", 1)[1].strip()
            new_home = str(python_home)
            if old_home != new_home:
                print(f"[repair_venv] 更新 home: {old_home} -> {new_home}")
                line = f"home = {new_home}"
                changed = True
            else:
                print(f"[repair_venv] home 已正确: {new_home}")
        new_lines.append(line)

    if changed:
        pyvenv_cfg.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        print("[repair_venv] .venv 修复完成")
    else:
        print("[repair_venv] 无需修复")


if __name__ == "__main__":
    repair()
