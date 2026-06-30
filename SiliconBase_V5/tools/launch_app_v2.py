#!/usr/bin/env python3
"""
原子工具：启动应用 V2 - 冷启动优化版
不依赖数据库，优先使用 Windows 原生方式查找
"""
import os
import subprocess
import time
import winreg

import win32api
import win32con
import win32gui
import win32process

from core.base_tool import BaseTool
from core.error_codes import FILE_NOT_FOUND, INVALID_PARAMS, TOOL_EXECUTION_ERROR, format_error
from core.logger import logger


class LaunchAppV2(BaseTool):
    """启动应用工具 V2 - 无需数据库扫描"""
    tool_id = "launch_app"
    tool_owner = "system"
    name = "启动应用"
    description = "根据应用名称智能查找并启动，支持冷启动（无需预扫描）"
    input_schema = {
        "type": "object",
        "properties": {
            "app_name": {"type": "string", "description": "应用名称（如：网易云音乐、chrome、微信）"},
            "name": {"type": "string", "description": "应用名称别名"},
            "exe_path": {"type": "string", "description": "直接指定完整路径（优先）"}
        },
        "anyOf": [
            {"required": ["app_name"]},
            {"required": ["name"]},
            {"required": ["exe_path"]}
        ]
    }

    # 别名映射：用户说的名称 -> 可能的exe文件名
    APP_ALIASES = {
        "网易云音乐": ["cloudmusic", "CloudMusic", "netease", "NeteaseMusic"],
        "网易云": ["cloudmusic"],
        "微信": ["wechat", "WeChat"],
        "qq": ["qq", "QQ", "Tim"],
        "chrome": ["chrome", "GoogleChrome"],
        "edge": ["msedge", "MicrosoftEdge"],
        "firefox": ["firefox", "Firefox"],
        "记事本": ["notepad"],
        "计算器": ["calc", "Calculator"],
        "word": ["winword"],
        "excel": ["excel"],
        "ppt": ["powerpnt"],
    }

    # 预置常见安装路径（作为最后兜底）
    COMMON_PATHS = {
        "cloudmusic": [
            r"D:\CloudMusic（网易云）\cloudmusic.exe",
            r"D:\CloudMusic\cloudmusic.exe",
            r"C:\Program Files (x86)\Netease\CloudMusic\cloudmusic.exe",
            r"C:\Program Files\Netease\CloudMusic\cloudmusic.exe",
        ],
        "wechat": [
            r"C:\Program Files\Tencent\WeChat\WeChat.exe",
            r"C:\Program Files (x86)\Tencent\WeChat\WeChat.exe",
        ],
        "qq": [
            r"C:\Program Files\Tencent\QQ\Bin\QQ.exe",
            r"C:\Program Files (x86)\Tencent\QQ\Bin\QQ.exe",
        ],
    }

    async def _execute_async(self, **kwargs) -> dict:
        """真正的异步启动应用 - 查找走线程池，启动走 asyncio"""
        import asyncio
        loop = asyncio.get_event_loop()

        exe_path = kwargs.get("exe_path")
        app_name = kwargs.get("app_name") or kwargs.get("name")

        if not app_name and not exe_path:
            return format_error(INVALID_PARAMS, detail="需要提供app_name或exe_path")

        # 模式1: 直接指定路径
        if exe_path:
            return await self._launch_by_path_async(exe_path, app_name or os.path.basename(exe_path))

        # 模式2: 智能查找（阻塞IO，扔线程池，不卡事件循环）
        found_path = await loop.run_in_executor(None, self._smart_find, app_name)
        if found_path:
            return await self._launch_by_path_async(found_path, app_name)

        # 失败
        return {
            "success": False,
            "error_code": "APP_NOT_FOUND",
            "user_message": f"未找到 '{app_name}'。建议：1.使用exe_path参数指定完整路径 2.尝试英文名如'cloudmusic'",
            "data": None
        }

    async def run(self, **kwargs) -> dict:
        return await self.run_async(**kwargs)

    def _execute(self, **kwargs) -> dict:
        """同步入口 - 直接走同步逻辑，禁止 asyncio.run() 桥接"""
        return self._execute_sync(**kwargs)

    def _execute_sync(self, **kwargs) -> dict:
        """纯同步执行逻辑（供 _execute 在事件循环线程中直接调用）"""
        exe_path = kwargs.get("exe_path")
        app_name = kwargs.get("app_name") or kwargs.get("name")

        if not app_name and not exe_path:
            return format_error(INVALID_PARAMS, detail="需要提供app_name或exe_path")

        if exe_path:
            return self._launch_by_path(exe_path, app_name or os.path.basename(exe_path))

        found_path = self._smart_find(app_name)
        if found_path:
            return self._launch_by_path(found_path, app_name)

        return {
            "success": False,
            "error_code": "APP_NOT_FOUND",
            "user_message": f"未找到 '{app_name}'。建议：1.使用exe_path参数指定完整路径 2.尝试英文名如'cloudmusic'",
            "data": None
        }

    async def _launch_by_path_async(self, exe_path: str, app_name: str) -> dict:
        """异步启动应用 - Windows下使用线程池调用同步Popen，避免asyncio对中文路径的兼容问题"""
        import asyncio
        loop = asyncio.get_event_loop()

        exe_path = os.path.normpath(exe_path)

        # 检查路径是否存在
        if not os.path.exists(exe_path):
            return format_error(FILE_NOT_FOUND, detail=f"路径不存在: {exe_path}")

        # 如果是目录，在里面找exe（同步操作，扔线程池）
        if os.path.isdir(exe_path):
            result = await loop.run_in_executor(None, self._find_exe_in_dir, exe_path)
            if result is None:
                return format_error(INVALID_PARAMS, detail=f"目录中未找到可执行文件: {exe_path}")
            exe_path = result

        # 检查是否是卸载程序
        if self._is_uninstaller(exe_path):
            return format_error(INVALID_PARAMS, detail="不能启动卸载程序")

        # 【修复】Windows下使用线程池调用同步subprocess.Popen，对中文/全角字符路径更可靠
        try:
            result = await loop.run_in_executor(
                None, self._launch_by_path, exe_path, app_name
            )
            return result
        except Exception as e:
            detail = str(e) or f"启动进程失败，路径: {exe_path}。可能是路径包含特殊字符或权限不足"
            return format_error(TOOL_EXECUTION_ERROR, detail=detail)

    def _find_exe_in_dir(self, dir_path: str) -> str:
        """在目录中查找可执行文件（供线程池调用）"""
        for file in os.listdir(dir_path):
            if file.lower().endswith('.exe') and not self._is_uninstaller(file):
                return os.path.join(dir_path, file)
        return None

    def _smart_find(self, app_name: str) -> str:
        """
        智能查找应用路径 - 优先级从高到低
        """
        # 获取所有可能的搜索名称
        search_names = self._get_search_names(app_name)
        logger.info(f"[LaunchApp] 查找 '{app_name}'，搜索名称: {search_names}")

        # 1. 【最高优先级】Windows 注册表 App Paths
        for name in search_names:
            path = self._find_in_app_paths(name)
            if path:
                logger.info(f"[LaunchApp] 通过 App Paths 找到: {path}")
                return path

        # 2. 【次优先级】PATH 环境变量
        for name in search_names:
            path = self._find_in_path(name)
            if path:
                logger.info(f"[LaunchApp] 通过 PATH 找到: {path}")
                return path

        # 3. 【第三优先级】桌面快捷方式
        for name in search_names:
            path = self._find_in_shortcuts(name)
            if path:
                logger.info(f"[LaunchApp] 通过快捷方式找到: {path}")
                return path

        # 4. 【兜底】预置常见路径
        for name in search_names:
            if name.lower() in self.COMMON_PATHS:
                for path in self.COMMON_PATHS[name.lower()]:
                    if os.path.exists(path):
                        logger.info(f"[LaunchApp] 通过预置路径找到: {path}")
                        return path

        return None

    def _get_search_names(self, app_name: str) -> list:
        """获取所有可能的搜索名称"""
        names = [app_name]

        # 添加别名
        if app_name in self.APP_ALIASES:
            names.extend(self.APP_ALIASES[app_name])

        # 添加带.exe后缀的版本
        names_with_exe = []
        for name in names:
            if not name.lower().endswith('.exe'):
                names_with_exe.append(name + '.exe')
        names.extend(names_with_exe)

        # 去重并保持顺序
        seen = set()
        unique_names = []
        for name in names:
            lower_name = name.lower()
            if lower_name not in seen:
                seen.add(lower_name)
                unique_names.append(name)

        return unique_names

    def _find_in_app_paths(self, exe_name: str) -> str:
        """
        查询 Windows 注册表 App Paths
        这是安装软件时自动写入的，最可靠
        """
        if not exe_name.lower().endswith('.exe'):
            exe_name += '.exe'

        # 查询两个注册表位置
        reg_paths = [
            (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\" + exe_name),
            (winreg.HKEY_CURRENT_USER, "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\" + exe_name),
        ]

        for hkey, key_path in reg_paths:
            try:
                with winreg.OpenKey(hkey, key_path) as key:
                    path, _ = winreg.QueryValueEx(key, None)
                    if path and os.path.exists(path):
                        return path
            except Exception:
                continue

        return None

    def _find_in_path(self, exe_name: str) -> str:
        """在 PATH 环境变量中查找"""
        if not exe_name.lower().endswith('.exe'):
            exe_name += '.exe'

        try:
            result = subprocess.run(
                ['where', exe_name],
                capture_output=True,
                timeout=3,
                shell=False
            )
            if result.returncode == 0:
                paths = result.stdout.decode('utf-8', errors='ignore').strip().split('\n')
                for path in paths:
                    path = path.strip()
                    if path and os.path.exists(path):
                        return path
        except Exception:
            pass

        # 备用：手动遍历 PATH
        for path_dir in os.environ.get("PATH", "").split(os.pathsep):
            full_path = os.path.join(path_dir, exe_name)
            if os.path.isfile(full_path):
                return full_path

        return None

    def _find_in_shortcuts(self, app_name: str) -> str:
        """查找桌面和开始菜单快捷方式"""
        import glob

        # 可能的快捷方式名称
        shortcut_names = [app_name]
        if not app_name.lower().endswith('.exe'):
            shortcut_names.append(app_name + '.exe')

        # 搜索路径
        search_paths = [
            os.path.join(os.path.expanduser("~"), "Desktop"),
            os.path.join(os.path.expanduser("~"), "桌面"),
            os.path.join(os.environ.get("PROGRAMDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs"),
            os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "Microsoft", "Windows", "Start Menu", "Programs"),
        ]

        for base_path in search_paths:
            if not os.path.exists(base_path):
                continue

            for lnk_file in glob.glob(os.path.join(base_path, "**", "*.lnk"), recursive=True):
                lnk_name = os.path.splitext(os.path.basename(lnk_file))[0].lower()

                # 模糊匹配
                for search_name in shortcut_names:
                    search_lower = search_name.lower().replace('.exe', '')
                    if (search_lower in lnk_name or
                        lnk_name in search_lower or
                        search_lower[:4] == lnk_name[:4]):  # 前4字符匹配
                        try:
                            target = self._resolve_shortcut(lnk_file)
                            if target and os.path.exists(target):
                                return target
                        except Exception:
                            continue

        return None

    def _resolve_shortcut(self, lnk_path: str) -> str:
        """解析 Windows 快捷方式"""
        try:
            import win32com.client
            shell = win32com.client.Dispatch("WScript.Shell")
            shortcut = shell.CreateShortCut(lnk_path)
            target = shortcut.Targetpath
            if target and target.endswith('.exe') and os.path.exists(target):
                return target
        except Exception:
            pass
        return None

    def _launch_by_path(self, exe_path: str, app_name: str) -> dict:
        """通过路径启动应用"""
        # 标准化路径
        exe_path = os.path.normpath(exe_path)

        # 检查路径是否存在
        if not os.path.exists(exe_path):
            return format_error(FILE_NOT_FOUND, detail=f"路径不存在: {exe_path}")

        # 如果是目录，在里面找exe
        if os.path.isdir(exe_path):
            for file in os.listdir(exe_path):
                if file.lower().endswith('.exe') and not self._is_uninstaller(file):
                    exe_path = os.path.join(exe_path, file)
                    break
            else:
                return format_error(INVALID_PARAMS, detail=f"目录中未找到可执行文件: {exe_path}")

        # 检查是否是卸载程序
        if self._is_uninstaller(exe_path):
            return format_error(INVALID_PARAMS, detail="不能启动卸载程序")

        # 启动
        try:
            proc = subprocess.Popen(
                [exe_path],
                shell=False,
                cwd=os.path.dirname(exe_path) if os.path.dirname(exe_path) else None
            )
            logger.info(f"[LaunchApp] 启动成功: {exe_path}, PID: {proc.pid}")

            # 等待窗口
            time.sleep(0.5)
            window_info = self._get_window_info(app_name, exe_path)

            return {
                "success": True,
                "user_message": f"已成功启动 '{app_name}'",
                "data": {
                    "path": exe_path,
                    "pid": proc.pid,
                    "window": window_info
                }
            }
        except Exception as e:
            detail = str(e) or f"启动进程失败，路径: {exe_path}。可能是路径包含特殊字符或权限不足"
            return format_error(TOOL_EXECUTION_ERROR, detail=detail)

    def _is_uninstaller(self, path: str) -> bool:
        """检查是否是卸载程序"""
        lower = path.lower()
        keywords = ['uninstall', 'uninst', '卸载', 'setup', 'installer']
        return any(kw in lower for kw in keywords)

    def _get_window_info(self, app_name: str, exe_path: str) -> dict:
        """获取窗口信息"""
        target_exe = os.path.basename(exe_path).lower()
        windows = []

        def enum_callback(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd)
            if not title:
                return True
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                handle = win32api.OpenProcess(
                    win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ,
                    False, pid
                )
                exe = win32process.GetModuleFileNameEx(handle, 0)
                win32api.CloseHandle(handle)
                if os.path.basename(exe).lower() == target_exe:
                    windows.append({"hwnd": hwnd, "title": title})
            except Exception:
                pass
            return True

        win32gui.EnumWindows(enum_callback, None)
        return windows[0] if windows else None


# 兼容旧版本
LaunchApp = LaunchAppV2
