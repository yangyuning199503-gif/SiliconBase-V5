#!/usr/bin/env python3
"""
路径工具 - 跨平台统一路径管理
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

治理目标：消灭所有硬编码 Windows 路径（D:\\, C:\\, E:\\）。
所有路径操作必须收敛到此模块。
"""

import os
import sys
from pathlib import Path

_PROJECT_ROOT: Path | None = None


def get_project_root() -> Path:
    """
    获取项目根目录

    检测策略：
    1. 从当前文件向上追溯，找到包含 .env 或 config/ 的目录
    2. Fallback：向上4层（core/utils/ -> core/ -> SiliconBase_V5/ -> project_root）
    """
    global _PROJECT_ROOT
    if _PROJECT_ROOT is None:
        current = Path(__file__).resolve()
        for parent in current.parents:
            if (parent / ".env").exists() or (parent / "config").is_dir():
                _PROJECT_ROOT = parent
                break
        if _PROJECT_ROOT is None:
            # fallback: 向上4层
            _PROJECT_ROOT = current.parent.parent.parent.parent
    return _PROJECT_ROOT


def normalize_path(path_str: str) -> Path:
    """
    将字符串路径统一为 Path 对象

    自动处理：
    - 环境变量展开（%APPDATA% -> 实际路径）
    - 用户目录展开（~ -> /home/user 或 C:\\Users\\user）
    - 分隔符统一（\\ -> / 在 Path 内部自动处理）
    """
    expanded = os.path.expandvars(os.path.expanduser(path_str))
    return Path(expanded)


def is_path_within_scope(path: Path, allowed_bases: list[Path]) -> bool:
    """
    检查路径是否在允许的基目录范围内（防路径遍历攻击）

    Args:
        path: 待检查路径
        allowed_bases: 允许的基目录列表

    Returns:
        bool: 是否在允许范围内
    """
    try:
        resolved = path.resolve()
        for base in allowed_bases:
            base_resolved = base.resolve()
            try:
                resolved.relative_to(base_resolved)
                return True
            except ValueError:
                continue
        return False
    except (OSError, RuntimeError):
        return False


def get_default_app_paths() -> dict[str, str]:
    """
    获取跨平台的默认应用路径

    Returns:
        Dict[str, str]: 平台相关的默认路径字典
    """
    if sys.platform == "win32":
        return {
            "program_files": os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            "program_files_x86": os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
            "app_data": os.path.expandvars(r"%APPDATA%"),
            "local_app_data": os.path.expandvars(r"%LOCALAPPDATA%"),
            "home": str(Path.home()),
        }
    elif sys.platform == "darwin":
        return {
            "applications": "/Applications",
            "user_applications": str(Path.home() / "Applications"),
            "home": str(Path.home()),
        }
    else:  # linux / other
        return {
            "applications": "/usr/share/applications",
            "bin": "/usr/bin",
            "local_bin": str(Path.home() / ".local" / "bin"),
            "home": str(Path.home()),
        }


def get_writable_data_dir(subdir: str | None = None) -> Path:
    """
    获取可写的数据目录

    跨平台：
    - Windows: %APPDATA%/SiliconBase/
    - macOS: ~/Library/Application Support/SiliconBase/
    - Linux: ~/.local/share/SiliconBase/
    """
    if sys.platform == "win32":
        base = Path(os.path.expandvars(r"%APPDATA%")) / "SiliconBase"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "SiliconBase"
    else:
        base = Path.home() / ".local" / "share" / "SiliconBase"

    if subdir:
        base = base / subdir

    base.mkdir(parents=True, exist_ok=True)
    return base


def safe_path_str(path: Path) -> str:
    """
    获取安全的字符串路径表示（统一使用正斜杠）

    用于跨平台的配置文件输出、日志记录等。
    """
    return path.as_posix()
