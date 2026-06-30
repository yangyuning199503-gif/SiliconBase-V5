#!/usr/bin/env python3
"""
跨平台路径解析器

提供统一的路径处理功能，支持：
- 模板路径解析（如 data/raw/{symbol}_15m.csv）
- 运行时目录管理
- 跨平台下载目录检测
- 路径分隔符统一处理

使用方法:
    from core.platform_adapter import PathResolver

    paths = PathResolver("/path/to/project")

    # 解析模板路径
    csv_path = paths.resolve_template_path("data/raw/{symbol}_15m.csv", symbol="BTC")
    # 结果: /path/to/project/data/raw/btc_15m.csv

    # 获取运行时目录
    runtime = paths.get_runtime_dir()  # 自动创建

    # 获取下载目录（跨平台）
    downloads = paths.get_downloads_dir()
"""

import os
import re
from pathlib import Path
from typing import Any


class PathResolver:
    """
    跨平台路径解析器

    统一处理不同操作系统下的路径问题，特别针对btc_system的需求：
    - Windows/macOS/Linux 路径分隔符差异
    - 模板变量替换（{symbol}, {date}等）
    - 相对路径到绝对路径的转换
    """

    def __init__(self, base_path: str | Path):
        """
        初始化路径解析器

        Args:
            base_path: 项目根目录，所有相对路径基于此目录解析
        """
        self.base_path = Path(base_path).resolve()

    def resolve_template_path(self, template: str, **kwargs) -> Path:
        """
        解析模板路径，替换占位符变量

        支持的占位符格式:
            - {symbol} -> 交易对符号（自动转小写）
            - {date}   -> 日期
            - {time}   -> 时间
            - 自定义变量通过 kwargs 传入

        Args:
            template: 模板路径，如 "data/raw/{symbol}_15m.csv"
            **kwargs: 变量名和值，如 symbol="BTC"

        Returns:
            解析后的Path对象

        Examples:
            >>> resolver = PathResolver("/project")
            >>> resolver.resolve_template_path("data/{symbol}.csv", symbol="BTC")
            PosixPath('/project/data/btc.csv')
            >>> resolver.resolve_template_path("reports/{date}/{symbol}.json",
            ...                               date="2024-01", symbol="ETH")
            PosixPath('/project/reports/2024-01/eth.json')
        """
        if not template:
            return self.base_path

        path_str = template

        # 替换所有占位符
        for key, value in kwargs.items():
            placeholder = f"{{{key}}}"
            if placeholder in path_str:
                # 对symbol特殊处理：转小写
                if key.lower() == 'symbol':
                    path_str = path_str.replace(placeholder, str(value).lower())
                else:
                    path_str = path_str.replace(placeholder, str(value))

        # 统一使用正斜杠，pathlib会自动处理为系统分隔符
        path_str = path_str.replace("\\", "/")

        path = Path(path_str)

        # 相对路径转为绝对路径
        if not path.is_absolute():
            path = self.base_path / path

        return path.resolve()

    def resolve_with_defaults(self, template: str, defaults: dict[str, Any],
                              **overrides) -> Path:
        """
        使用默认值解析模板，允许覆盖

        Args:
            template: 模板路径
            defaults: 默认变量值
            **overrides: 覆盖的变量值

        Returns:
            解析后的Path对象

        Examples:
            >>> resolver = PathResolver("/project")
            >>> defaults = {"symbol": "btc", "interval": "15m"}
            >>> resolver.resolve_with_defaults("data/{symbol}_{interval}.csv",
            ...                                defaults, symbol="ETH")
            PosixPath('/project/data/eth_15m.csv')
        """
        # 合并默认值和覆盖值
        variables = {**defaults, **overrides}
        return self.resolve_template_path(template, **variables)

    def get_runtime_dir(self, subdir: str | None = None) -> Path:
        """
        获取运行时目录（用于.pid、状态文件等）

        Args:
            subdir: 子目录名（可选）

        Returns:
            运行时目录Path对象（自动创建）
        """
        runtime = self.base_path / ".runtime" / subdir if subdir else self.base_path / ".runtime"

        runtime.mkdir(parents=True, exist_ok=True)
        return runtime

    def get_data_dir(self, subdir: str | None = None) -> Path:
        """
        获取数据目录

        Args:
            subdir: 子目录名（可选），如 "raw", "processed"

        Returns:
            数据目录Path对象（自动创建）
        """
        data = self.base_path / "data" / subdir if subdir else self.base_path / "data"

        data.mkdir(parents=True, exist_ok=True)
        return data

    def get_reports_dir(self, subdir: str | None = None) -> Path:
        """
        获取报告目录

        Args:
            subdir: 子目录名（可选），如 "research", "backtest"

        Returns:
            报告目录Path对象（自动创建）
        """
        reports = self.base_path / "reports" / subdir if subdir else self.base_path / "reports"

        reports.mkdir(parents=True, exist_ok=True)
        return reports

    def get_logs_dir(self) -> Path:
        """
        获取日志目录

        Returns:
            日志目录Path对象（自动创建）
        """
        logs = self.base_path / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        return logs

    def get_downloads_dir(self) -> Path:
        r"""
        获取用户下载目录（跨平台）

        检测顺序:
            1. Windows: %USERPROFILE%\Downloads
            2. macOS: ~/Downloads
            3. Linux: $XDG_DOWNLOAD_DIR 或 ~/Downloads
            4. 回退: 用户主目录

        Returns:
            下载目录Path对象
        """
        home = Path.home()

        # Windows: 尝试从环境变量获取
        if os.name == 'nt':
            # 标准Windows下载目录
            downloads = home / "Downloads"
            if downloads.exists():
                return downloads

        # macOS / Linux
        # 检查 XDG_DOWNLOAD_DIR (Linux标准)
        xdg_downloads = os.environ.get('XDG_DOWNLOAD_DIR')
        if xdg_downloads:
            path = Path(xdg_downloads)
            if path.exists():
                return path

        # 标准下载目录
        downloads = home / "Downloads"
        if downloads.exists():
            return downloads

        # 回退到用户主目录
        return home

    def get_user_home(self) -> Path:
        """
        获取用户主目录（跨平台）

        Returns:
            用户主目录Path对象
        """
        return Path.home()

    def get_temp_dir(self) -> Path:
        """
        获取临时目录

        Returns:
            临时目录Path对象
        """
        import tempfile
        return Path(tempfile.gettempdir())

    def expand_user_path(self, path: str | Path) -> Path:
        """
        展开用户目录符号 ~

        Args:
            path: 可能包含 ~ 的路径

        Returns:
            展开后的Path对象
        """
        return Path(path).expanduser().resolve()

    def make_relative_to_base(self, path: str | Path) -> Path:
        """
        将绝对路径转为相对于base_path的路径

        Args:
            path: 绝对路径

        Returns:
            相对路径Path对象
        """
        try:
            return Path(path).resolve().relative_to(self.base_path)
        except ValueError:
            # path不在base_path下，返回原路径
            return Path(path).resolve()

    def ensure_dir(self, path: str | Path) -> Path:
        """
        确保目录存在，不存在则创建

        Args:
            path: 目录路径

        Returns:
            确保存在的目录Path对象
        """
        path = Path(path)
        if not path.is_absolute():
            path = self.base_path / path

        path.mkdir(parents=True, exist_ok=True)
        return path

    def safe_filename(self, name: str, replace_with: str = "_") -> str:
        """
        生成安全的文件名（移除非法字符）

        Args:
            name: 原始文件名
            replace_with: 替换字符

        Returns:
            安全的文件名
        """
        # Windows/macOS/Linux 非法字符
        illegal_chars = '<>:"/\\|?*'

        for char in illegal_chars:
            name = name.replace(char, replace_with)

        # 移除控制字符
        name = re.sub(r'[\x00-\x1f]', '', name)

        # 限制长度
        if len(name) > 255:
            name = name[:255]

        return name.strip()

    def split_template(self, template: str) -> tuple:
        """
        拆分模板路径为目录和文件模板

        Args:
            template: 如 "data/raw/{symbol}_15m.csv"

        Returns:
            (目录部分, 文件模板)
            如 ("data/raw", "{symbol}_15m.csv")
        """
        parts = template.replace("\\", "/").rsplit("/", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return ".", parts[0]

    def list_template_variables(self, template: str) -> list:
        """
        列出模板中的所有变量名

        Args:
            template: 模板路径

        Returns:
            变量名列表

        Examples:
            >>> PathResolver.list_template_variables("data/{symbol}_{interval}.csv")
            ['symbol', 'interval']
        """
        pattern = r'\{([^}]+)\}'
        return re.findall(pattern, template)

    def __repr__(self) -> str:
        return f"PathResolver(base_path='{self.base_path}')"


# =============================================================================
# 便捷函数
# =============================================================================

def get_default_resolver() -> PathResolver:
    """
    获取默认解析器（基于当前工作目录）

    Returns:
        PathResolver实例
    """
    return PathResolver(Path.cwd())


def resolve_btc_system_path(
    btc_system_path: str | Path | None = None
) -> Path | None:
    """
    自动检测并解析btc_system路径

    Args:
        btc_system_path: 指定路径，为None时自动检测

    Returns:
        有效的btc_system路径或None
    """
    if btc_system_path:
        path = Path(btc_system_path).resolve()
        if path.exists() and (path / "config.yml").exists():
            return path
        return None

    # 自动检测候选路径
    candidates = [
        # Windows - V5集成路径
        Path("E:/SiliconBase_V5/SiliconBase_V5/btc_system"),
        Path("F:/btc_system_v1"),
        Path("C:/btc_system_v1"),
        Path("D:/btc_system_v1"),
        # Windows - 用户目录
        Path.home() / "btc_system_v1",
        Path.home() / "btc_system",
        # macOS/Linux
        Path.home() / "btc_system_v1",
        Path.home() / "btc_system",
        Path("/opt/btc_system_v1"),
        Path("/usr/local/btc_system"),
    ]

    for path in candidates:
        try:
            if path.exists() and (path / "config.yml").exists():
                return path.resolve()
        except Exception:
            continue

    return None


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 平台抽象层的路径处理组件，为 btc_system 提供
# 统一的路径解析能力，解决跨平台路径分隔符、模板变量替换等问题。
#
# 【核心功能】
# 1. 模板路径解析：支持 {symbol} 等占位符的替换
# 2. 目录管理：运行时目录、数据目录、报告目录的统一管理
# 3. 跨平台兼容：自动处理Windows/macOS/Linux的路径差异
# 4. 便捷函数：自动检测btc_system路径等
#
# 【使用场景】
# - btc_system autopilot 路径解析
# - 状态文件读写
# - 数据CSV文件定位
# - 报告文件生成
#
# 【关联文件】
# - core/platform/__init__.py: 平台层入口
# - core/platform/factory.py: 平台工厂
# - btc_system/tools/okx_demo_autopilot.py: 主要使用方
#
# 【向后兼容】
# 所有方法都支持相对路径和绝对路径，不传参数时使用合理的默认值。
# =============================================================================
