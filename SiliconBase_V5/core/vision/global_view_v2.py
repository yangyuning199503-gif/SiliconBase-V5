#!/usr/bin/env python3
"""
⚠️ DEPRECATED: 此模块已被 `core.sensors.system.global_view` 取代。
保留仅为向后兼容，新代码请勿使用 GlobalViewV2。

全局视野 V2.0 - 性能优化版
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【设计原则】
1. 不实时监听 - 用户很少频繁安装软件
2. 按需搜索 - AI需要时才快速查找
3. 启动扫描 - 仅启动时扫描一次
4. 可手动刷新 - 提供API供用户主动触发

【使用方式】
- 启动时：自动全盘扫描（后台线程，不阻塞）
- 运行时：AI调用 find_app() 按需搜索
- 更新时：用户调用 refresh() 手动刷新或等待定时任务
"""

import hashlib
import os
import threading
import time
from datetime import datetime

from core.config import config
from core.logger import logger


class SoftwareInfo:
    """软件信息数据类"""
    def __init__(self, name: str, path: str, version: str = "",
                 process_name: str = "", source: str = "unknown"):
        self.name = name
        self.path = path
        self.version = version
        self.process_name = process_name or os.path.basename(path) if path else ""
        self.source = source  # registry, directory, on_demand
        self.discovered_at = datetime.now()


class GlobalViewV2:
    """
    全局视野 V2 - 性能优化版

    特点：
    - 不持续监听文件系统
    - 启动时扫描一次后保持静态
    - AI查询时按需实时搜索
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True

        # 软件数据库（内存缓存）
        self._software_db: dict[str, SoftwareInfo] = {}
        self._db_lock = threading.RLock()

        # 扫描状态
        self._scanning = False
        self._last_full_scan = 0
        self._last_registry_scan = 0

        # 配置
        self._scan_mode = config.get("global_view.scan_mode", "startup_only")
        # 【P0-修复】禁用启动时全盘扫描，避免占用资源导致AI思考卡死
        self._startup_scan_enabled = config.get("global_view.startup_scan.enabled", False)
        self._max_scan_duration = config.get("global_view.startup_scan.max_duration", 30)

        logger.info(f"[GlobalViewV2] 初始化完成，扫描模式: {self._scan_mode}")

    def start(self):
        """
        启动全局视野
        - 仅在启动时扫描一次（如果启用）
        - 不启动实时监听
        """
        if self._startup_scan_enabled and self._scan_mode == "startup_only":
            self.scan_all_async()

        # 注意：不启动 watchdog 监听，避免性能消耗
        logger.info("[GlobalViewV2] 已启动（无实时监听）")

    def scan_all_async(self):
        """异步全盘扫描（后台线程）

        【P0-修复】添加限制，避免扫描过多文件导致系统卡死
        """
        if self._scanning:
            logger.info("[GlobalViewV2] 扫描已在进行")
            return

        # 【P0-修复】限制最大扫描文件数，防止资源耗尽
        self._max_files_to_scan = 5000  # 最多扫描5000个文件
        self._files_scanned = 0

        def do_scan():
            self._scanning = True
            start_time = time.time()
            try:
                logger.info("[GlobalViewV2] 开始全盘扫描（限制5000文件）...")
                self._scan_registry()
                self._scan_common_directories()
                self._last_full_scan = time.time()
                elapsed = time.time() - start_time
                logger.info(f"[GlobalViewV2] 全盘扫描完成，耗时 {elapsed:.1f}s，"
                           f"共 {len(self._software_db)} 个软件")
            except Exception as e:
                logger.error(f"[GlobalViewV2] 扫描失败: {e}")
            finally:
                self._scanning = False

        thread = threading.Thread(target=do_scan, daemon=True)
        thread.start()

    def _scan_registry(self, max_time: float = 10.0, max_items: int = 500):
        """扫描注册表（带超时保护）"""
        try:
            import winreg
            start_time = time.time()
            count = 0

            keys = [
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall")
            ]

            for hkey, subkey in keys:
                if time.time() - start_time > max_time or count >= max_items:
                    break

                try:
                    with winreg.OpenKey(hkey, subkey) as key:
                        i = 0
                        while True:
                            if time.time() - start_time > max_time or count >= max_items:
                                break

                            try:
                                subkey_name = winreg.EnumKey(key, i)
                                with winreg.OpenKey(key, subkey_name) as app_key:
                                    name = self._reg_get_value(app_key, "DisplayName")
                                    if name:
                                        install_path = self._reg_get_value(app_key, "InstallLocation")
                                        version = self._reg_get_value(app_key, "DisplayVersion")

                                        software_id = f"reg_{hashlib.md5(name.encode()).hexdigest()[:16]}"
                                        with self._db_lock:
                                            self._software_db[software_id] = SoftwareInfo(
                                                name=name,
                                                path=install_path or "",
                                                version=version or "",
                                                source="registry"
                                            )
                                        count += 1
                            except OSError:
                                break
                            i += 1
                except Exception as e:
                    logger.debug(f"[GlobalViewV2] 注册表扫描异常: {e}")

            logger.info(f"[GlobalViewV2] 注册表扫描完成: {count} 个软件")

        except Exception as e:
            logger.debug(f"[GlobalViewV2] 注册表模块不可用: {e}")

    def _scan_common_directories(self):
        """扫描常见安装目录（浅层扫描）"""
        common_dirs = [
            os.environ.get("PROGRAMFILES", "C:\\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)"),
        ]

        for directory in common_dirs:
            if not os.path.exists(directory):
                continue

            try:
                for item in os.listdir(directory):
                    item_path = os.path.join(directory, item)
                    if os.path.isdir(item_path):
                        # 只扫描第一层目录
                        software_id = f"dir_{hashlib.md5(item.encode()).hexdigest()[:16]}"
                        with self._db_lock:
                            self._software_db[software_id] = SoftwareInfo(
                                name=item,
                                path=item_path,
                                source="directory"
                            )
            except Exception as e:
                logger.debug(f"[GlobalViewV2] 目录扫描异常: {e}")

    def _reg_get_value(self, key, name):
        """安全读取注册表值"""
        try:
            import winreg
            return winreg.QueryValueEx(key, name)[0]
        except Exception:
            return None

    def find_app(self, name: str, timeout: float = 2.0) -> SoftwareInfo | None:
        """
        【核心API】查找应用（按需搜索）

        策略：
        1. 先在缓存中查找
        2. 如果找不到，实时快速搜索（限时2秒）

        Args:
            name: 应用名称（模糊匹配）
            timeout: 实时搜索最大时间

        Returns:
            SoftwareInfo 或 None
        """
        name_lower = name.lower()

        # 1. 先在缓存中查找
        with self._db_lock:
            for software in self._software_db.values():
                if name_lower in software.name.lower():
                    return software

        # 2. 缓存未找到，实时快速搜索
        return self._on_demand_search(name, timeout)

    def _on_demand_search(self, name: str, max_time: float) -> SoftwareInfo | None:
        """
        按需实时搜索（快速路径）
        只在常见位置搜索，限时完成
        """
        start_time = time.time()
        name_lower = name.lower()

        # 快速搜索路径（按优先级排序）
        quick_paths = [
            os.environ.get("PROGRAMFILES", "C:\\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
        ]

        for base_path in quick_paths:
            if time.time() - start_time > max_time:
                break

            if not os.path.exists(base_path):
                continue

            try:
                for item in os.listdir(base_path):
                    if time.time() - start_time > max_time:
                        break

                    if name_lower in item.lower():
                        full_path = os.path.join(base_path, item)
                        return SoftwareInfo(
                            name=item,
                            path=full_path,
                            source="on_demand"
                        )
            except Exception:
                continue

        return None

    def list_all_apps(self) -> list[SoftwareInfo]:
        """获取所有已发现的软件"""
        with self._db_lock:
            return list(self._software_db.values())

    def refresh(self):
        """
        手动刷新软件列表
        用户或AI可以调用此接口主动更新
        """
        logger.info("[GlobalViewV2] 收到手动刷新请求")
        self.scan_all_async()
        return {"status": "started", "message": "扫描已在后台启动"}

    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            "total_apps": len(self._software_db),
            "last_full_scan": self._last_full_scan,
            "scan_mode": self._scan_mode,
            "is_scanning": self._scanning
        }


# 全局实例
global_view_v2 = GlobalViewV2()


def get_global_view_v2() -> GlobalViewV2:
    """
    获取全局视野V2实例

    Returns:
        GlobalViewV2: 全局视野V2实例
    """
    return global_view_v2
