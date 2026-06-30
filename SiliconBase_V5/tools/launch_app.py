#!/usr/bin/env python3
"""
原子工具：启动应用（根据名称查找并启动）
修复版：增加窗口等待重试，返回更准确的执行信息
Windows路径处理增强版：支持中文、空格、特殊字符路径
2026-03-11 修复：将run改为_execute，异常处理交由基类统一处理
"""
import asyncio
import os
import subprocess
import time

import win32api
import win32con
import win32gui
import win32process

from core.base_tool import BaseTool
from core.error_codes import FILE_NOT_FOUND, INVALID_PARAMS, format_error
from core.logger import logger

# 延迟导入 global_view 避免循环导入
global_view = None
def _get_global_view():
    global global_view
    if global_view is None:
        from sensors.system.global_view import global_view as gv
        global_view = gv
    return global_view


class LaunchApp(BaseTool):
    """启动应用工具 - 系统内置"""
    tool_id = "launch_app"
    tool_owner = "system"  # 系统内置工具
    name = "启动应用"
    description = "根据应用名称，查找并启动该应用，自动避免启动卸载程序，并返回窗口信息。"
    input_schema = {
        "type": "object",
        "properties": {
            "app_name": {"type": "string", "description": "应用名称，用于查找并启动应用（可与exe_path同时提供）"},
            "name": {"type": "string", "description": "应用名称（app_name的别名，兼容参数）"},
            "exe_path": {"type": "string", "description": "直接指定可执行文件完整路径（优先使用）"}
        },
        "anyOf": [
            {"required": ["app_name"]},
            {"required": ["name"]},
            {"required": ["exe_path"]}
        ]
    }

    APP_ALIASES = {
        # 音乐
        "网易云音乐": ["cloudmusic.exe", "cloudmusic", "NetEase", "CloudMusic"],
        "qq音乐": ["QQMusic.exe", "qqmusic", "QQ音乐"],
        "酷狗": ["KuGou.exe", "kugou"],
        "酷我": ["kuwo.exe", "KuWo"],
        "spotify": ["Spotify.exe"],
        # 社交
        "微信": ["wechat.exe", "WeChat", "weixin", "Weixin"],
        "weixin": ["Weixin.exe", "weixin.exe"],
        "qq": ["qq.exe", "QQ", "QQProtect"],
        "tim": ["TIM.exe", "tim"],
        "钉钉": ["DingTalk.exe", "dingtalk"],
        "飞书": ["Lark.exe", "lark", "feishu"],
        # 浏览器
        "chrome": ["chrome.exe", "Chrome", "GoogleChrome"],
        "谷歌浏览器": ["chrome.exe"],
        "edge": ["msedge.exe", "Edge", "MicrosoftEdge"],
        "firefox": ["firefox.exe", "Firefox", "火狐"],
        "360浏览器": ["360chrome.exe", "360se.exe"],
        "qq浏览器": ["QQBrowser.exe", "qqbrowser"],
        # 办公
        "word": ["winword.exe", "WORD"],
        "excel": ["excel.exe", "EXCEL"],
        "ppt": ["powerpnt.exe", "POWERPNT"],
        "wps": ["wps.exe", "WPS"],
        "acrobat": ["Acrobat.exe", "Acrobat"],
        # 开发工具
        "vscode": ["Code.exe", "code", "vscode"],
        "visual studio code": ["Code.exe"],
        "idea": ["idea64.exe", "idea.exe"],
        "pycharm": ["pycharm64.exe", "pycharm.exe"],
        "git": ["git-bash.exe", "git-cmd.exe"],
        # 下载
        "idm": ["IDMan.exe", "idm"],
        "迅雷": ["Thunder.exe", " thunder"],
        "百度网盘": ["BaiduNetdisk.exe", "baidunetdisk"],
        # 媒体
        "potplayer": ["PotPlayerMini64.exe", "PotPlayerMini.exe"],
        "vlc": ["vlc.exe"],
        # 游戏
        "steam": ["steam.exe", "Steam"],
        "epic": ["EpicGamesLauncher.exe"],
        "梦幻西游": ["mhxy.exe", "MHXY", "梦话西游"],
        "mhxy": ["mhxy.exe"],
        # 工具
        "everything": ["Everything.exe"],
        "snipaste": ["Snipaste.exe"],
        "bandizip": ["Bandizip.exe"],
        # 系统
        "记事本": ["notepad.exe"],
        "计算器": ["calc.exe", "Calculator"],
        "画图": ["mspaint.exe"],
        "任务管理器": ["taskmgr.exe"],
        "cmd": ["cmd.exe"],
        "命令行": ["cmd.exe"],
        "powershell": ["powershell.exe"],
        "终端": ["wt.exe", "WindowsTerminal.exe"],
    }

    # 预置常见软件路径（作为兜底，避免遍历注册表）
    PRESET_PATHS = {
        "cloudmusic": [
            r"D:\CloudMusic（网易云）\cloudmusic.exe",
            r"D:\CloudMusic\cloudmusic.exe",
            r"C:\Program Files (x86)\Netease\CloudMusic\cloudmusic.exe",
            r"C:\Program Files\Netease\CloudMusic\cloudmusic.exe",
        ],
        "wechat": [
            r"D:\Weixin\Weixin.exe",
            r"C:\Program Files\Tencent\WeChat\WeChat.exe",
            r"C:\Program Files (x86)\Tencent\WeChat\WeChat.exe",
            r"C:\Users\%USERNAME%\AppData\Roaming\Tencent\WeChat\WeChat.exe",
            r"D:\Program Files\Tencent\WeChat\WeChat.exe",
            r"D:\Program Files (x86)\Tencent\WeChat\WeChat.exe",
        ],
        "qq": [
            r"C:\Program Files\Tencent\QQ\Bin\QQ.exe",
            r"C:\Program Files (x86)\Tencent\QQ\Bin\QQ.exe",
        ],
        "chrome": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ],
        "code": [
            r"C:\Users\%USERNAME%\AppData\Local\Programs\Microsoft VS Code\Code.exe",
            r"C:\Program Files\Microsoft VS Code\Code.exe",
        ],
        "mhxy": [
            r"D:\Netease\梦幻西游\mhxy.exe",
            r"D:\Netease\MHXY\mhxy.exe",
            r"D:\梦幻西游\mhxy.exe",
            r"C:\Netease\梦幻西游\mhxy.exe",
            r"C:\Program Files\Netease\梦幻西游\mhxy.exe",
            r"D:\Game\梦幻西游\mhxy.exe",
            r"D:\Games\梦幻西游\mhxy.exe",
            r"C:\Users\%USERNAME%\AppData\Local\Netease\梦幻西游\mhxy.exe",
        ],
    }

    async def _execute_async(self, **kwargs) -> dict:
        """
        异步启动应用 - 显式桥接到线程池

        应用启动和窗口等待本质上是同步的系统调用，无法真正异步化。
        使用 run_in_executor 将阻塞操作放到线程池中执行，避免阻塞事件循环。
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._execute(**kwargs))

    def _execute(self, **kwargs) -> dict:
        """启动应用 - 异常由基类统一处理"""
        exe_path = kwargs.get("exe_path")
        # 兼容处理：支持 name/app 作为 app_name 的别名
        app_name = kwargs.get("app_name") or kwargs.get("name") or kwargs.get("app")

        # 模式2: 直接通过exe_path启动
        if exe_path:
            # 确保路径是字符串类型（处理可能的unicode编码问题）
            if isinstance(exe_path, bytes):
                try:
                    exe_path = exe_path.decode('utf-8')
                except UnicodeDecodeError:
                    exe_path = exe_path.decode('gbk', errors='ignore')

            exe_path = exe_path.strip()
            if not exe_path:
                return format_error(INVALID_PARAMS, detail="exe_path不能为空")

            # 【修复】标准化路径：处理中文、空格、特殊字符、正反斜杠
            exe_path = os.path.normpath(exe_path)

            # 【增强】检查路径是否存在
            if not os.path.exists(exe_path):
                return format_error(FILE_NOT_FOUND, detail=f"路径不存在: {exe_path}")

            # 【增强】检查是否是文件（而非目录）
            if not os.path.isfile(exe_path):
                return format_error(FILE_NOT_FOUND, detail=f"不是有效文件: {exe_path}")

            # 【增强】检查是否是可执行文件（.exe后缀）
            if not exe_path.lower().endswith('.exe'):
                return format_error(INVALID_PARAMS, detail=f"不是可执行文件: {exe_path}")

            # 【增强】检查文件是否有执行权限（Windows下检查是否可读）
            if not os.access(exe_path, os.R_OK | os.X_OK):
                return format_error(INVALID_PARAMS, detail=f"没有执行权限: {exe_path}")

            # 检查是否是卸载程序
            if self._is_uninstaller(exe_path):
                return format_error(INVALID_PARAMS, detail="不能启动卸载程序")

            # 使用路径中的文件名作为app_name（用于窗口查找和返回信息）
            if not app_name:
                app_name = os.path.splitext(os.path.basename(exe_path))[0]

        # 模式1: 通过app_name查找路径
        elif app_name:
            app_name = app_name.strip()
            if not app_name:
                return format_error(INVALID_PARAMS, detail="应用名称不能为空")

            exe_path = self._get_valid_app_path(app_name)
            if not exe_path:
                # 【Phase 4】友好的失败提示，引导用户提供路径
                aliases = self.APP_ALIASES.get(app_name, [])
                alias_hint = f"（也可尝试：{', '.join(aliases[:3])}）" if aliases else ""

                return {
                    "success": False,
                    "error_code": "APP_NOT_FOUND",
                    "user_message": f"暂时找不到'{app_name}'{alias_hint}。请告诉我安装路径（如：D:\\软件名\\程序.exe），我会记住以后直接打开！",
                    "data": None
                }

        else:
            return format_error(INVALID_PARAMS, detail="需要提供app_name或exe_path参数")

        # 启动应用（可能抛出FileNotFoundError, PermissionError, OSError等，由基类捕获）
        proc = subprocess.Popen([exe_path],
                               shell=False,  # 不使用shell，避免额外的转义问题
                               cwd=os.path.dirname(exe_path) if os.path.dirname(exe_path) else None)
        logger.info(f"[LaunchApp] 启动进程: {exe_path}, PID: {proc.pid}")

        # 等待窗口出现，最长10秒，每0.5秒检查一次
        max_wait = 10
        wait_interval = 0.5
        window_info = None
        for _ in range(int(max_wait / wait_interval)):
            window_info = self._get_window_info(app_name, exe_path)
            if window_info and not window_info.get("abnormal", False):
                break
            time.sleep(wait_interval)

        # 【Phase 2: 记忆路径】启动成功后记忆路径
        self._memorize_path(app_name, exe_path)

        if window_info:
            user_msg = f"已成功启动应用 '{app_name}'，进程PID: {proc.pid}"
            # 【2026-03-09 增强】添加更详细的窗口验证信息
            is_abnormal = window_info.get("abnormal", False)
            return {
                "success": True,
                "error_code": None,
                "user_message": user_msg,
                "data": {
                    "message": user_msg,
                    "path": exe_path,
                    "pid": proc.pid,
                    "window": window_info,
                    "verification": "verified" if not is_abnormal else "abnormal_detected",
                    "window_state": {
                        "title": window_info.get("title", ""),
                        "hwnd": window_info.get("hwnd"),
                        "is_visible": True,
                        "is_normal": not is_abnormal
                    }
                }
            }
        else:
            # 进程已启动，但窗口未找到（可能后台启动），返回部分成功
            user_msg = f"应用 '{app_name}' 进程已启动（PID: {proc.pid}），未检测到主窗口，可能正在后台启动"
            return {
                "success": True,
                "error_code": None,
                "user_message": user_msg,
                "data": {
                    "message": user_msg,
                    "path": exe_path,
                    "pid": proc.pid,
                    "window": None,
                    "verification": "unverified",
                    "window_state": None
                }
            }

    def _get_valid_app_path(self, app_name: str, user_id: str = "default") -> str:
        """获取有效的应用路径 - 【优化】避免卡死，优先快速查找"""
        search_names = self.APP_ALIASES.get(app_name, [app_name])

        # 【优化1】先去重，减少搜索次数
        unique_names = []
        seen = set()
        for name in search_names:
            base = name.lower().replace('.exe', '')
            if base not in seen:
                seen.add(base)
                unique_names.append(name)

        # 【Phase 2: 最高优先级】检查记忆的路径（精确匹配）
        memorized_path = self._get_memorized_path(app_name, user_id)
        if memorized_path and os.path.exists(memorized_path):
            logger.info(f"[LaunchApp] 从记忆中找到路径: {app_name} -> {memorized_path}")
            return memorized_path

        # 【Phase 2增强】向量语义搜索 - 支持模糊匹配（如"梦幻西游"→"梦幻西游路径"）
        vector_path = self._get_vector_searched_path(app_name, user_id)
        if vector_path and os.path.exists(vector_path):
            logger.info(f"[LaunchApp] 从向量记忆找到路径: {app_name} -> {vector_path}")
            return vector_path

        # 【优化2】注册表查找（最快，不遍历文件）
        for name in unique_names:
            path = self._find_in_registry(name)
            if path:
                return path

        # 【优化3】PATH中查找（快）
        for name in unique_names:
            path = self._find_exe_in_path(name)
            if path:
                return path

        # 【优化4】预置路径查找（避免遍历注册表）
        for name in unique_names:
            base = name.lower().replace('.exe', '')
            if base in self.PRESET_PATHS:
                for path in self.PRESET_PATHS[base]:
                    # 处理 %USERNAME% 环境变量
                    expanded_path = os.path.expandvars(path)
                    if os.path.exists(expanded_path):
                        logger.info(f"[LaunchApp] 从预置路径找到: {app_name} -> {expanded_path}")
                        return expanded_path

        # 【优化4.5】查询 global_view 磁盘扫描数据库（关键修复！）
        global_view_path = self._find_in_global_view(app_name, unique_names)
        if global_view_path:
            logger.info(f"[LaunchApp] 从 global_view 找到: {app_name} -> {global_view_path}")
            return global_view_path

        # 【优化5】桌面快捷方式（限制数量，避免卡死）
        desktop_path = self._find_desktop_shortcut_fast(app_name, unique_names[:3])
        if desktop_path:
            return desktop_path

        # 【优化6】开始菜单快捷方式（限制数量）
        startmenu_path = self._find_startmenu_shortcut_fast(app_name, unique_names[:3])
        if startmenu_path:
            return startmenu_path

        return None

    def _find_in_global_view(self, app_name: str, search_names: list, user_id: str = "default") -> str:
        """
        【关键修复】查询 global_view 磁盘扫描数据库和文件索引

        1. 首先查询 software_info 表（传统软件信息）
        2. 然后查询 file_index 表（全盘扫描的文件索引）
        """
        try:
            # 【关键修复】延迟获取 global_view 避免循环导入
            gv = _get_global_view()
            if gv is None:
                return None

            # 1. 查询 software_info 表（已安装的软件）
            for name in search_names[:3]:
                results = gv.db.search(name, user_id=user_id)
                if results:
                    for result in results:
                        install_path = result.get('install_path', '')
                        process_name = result.get('process_name', '')

                        if install_path and os.path.exists(install_path):
                            if install_path.lower().endswith('.exe'):
                                return install_path
                            if os.path.isdir(install_path):
                                exe_path = self._find_exe_in_directory(install_path, search_names)
                                if exe_path:
                                    return exe_path

                        if process_name and install_path and os.path.isdir(install_path):
                            full_path = os.path.join(install_path, process_name)
                            if os.path.exists(full_path):
                                return full_path

            # 2. 【新增】查询 file_index 表（全盘扫描的文件索引）
            for name in search_names[:3]:
                # 使用新的 search_files 方法查询可执行文件
                file_results = gv.search_files(
                    keyword=name,
                    file_type="executable",
                    user_id=user_id,
                    limit=5
                )

                for file_info in file_results:
                    file_path = file_info.get('file_path', '')
                    if file_path and os.path.exists(file_path) and file_path.lower().endswith('.exe'):
                        # 验证文件名匹配
                        file_name = os.path.basename(file_path).lower().replace('.exe', '')
                        for search_name in search_names:
                            search_lower = search_name.lower().replace('.exe', '')
                            if search_lower in file_name or file_name in search_lower:
                                logger.info(f"[LaunchApp] 从 file_index 找到: {app_name} -> {file_path}")
                                return file_path

            # 3. 【新增】查询记忆系统（语义搜索）
            try:
                memory_path = self._find_app_path_from_memory(search_names)
                if memory_path:
                    return memory_path
            except Exception as e:
                logger.debug(f"[LaunchApp] 查询记忆系统失败: {e}")

            logger.debug(f"[LaunchApp] global_view 未找到: {app_name}")
        except Exception as e:
            logger.debug(f"[LaunchApp] 查询 global_view 失败: {e}")
        return None

    def _find_exe_in_directory(self, directory: str, search_names: list) -> str:
        """在目录中查找匹配的可执行文件"""
        try:
            for file in os.listdir(directory):
                if file.lower().endswith('.exe'):
                    file_lower = file.lower().replace('.exe', '')
                    # 检查是否匹配搜索名称
                    for name in search_names:
                        name_lower = name.lower().replace('.exe', '')
                        if name_lower in file_lower or file_lower in name_lower:
                            full_path = os.path.join(directory, file)
                            if os.path.exists(full_path):
                                return full_path
        except Exception:
            pass
        return None

    def _call_async(self, coro):
        """在 sync 方法中安全调用 async 代码"""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            return asyncio.run_coroutine_threadsafe(coro, loop).result()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()

    async def _find_app_path_from_memory_async(self, search_names: list) -> str:
        """异步：从记忆中查找应用路径（语义搜索）"""
        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()
        for name in search_names[:3]:
            results = await ms.retrieve_memories(
                user_id="default",
                query=name,
                level="medium",
                limit=3,
                use_semantic=True
            )
            for mem in results:
                content = mem.get("content", "")
                if ":" in content:
                    file_name, file_path = content.split(":", 1)
                    if os.path.exists(file_path) and file_path.lower().endswith('.exe'):
                        return file_path
        return None

    def _find_app_path_from_memory(self, search_names: list) -> str:
        """从记忆中查找应用路径（语义搜索）"""
        return self._call_async(self._find_app_path_from_memory_async(search_names))

    async def _get_memorized_path_async(self, app_name: str, user_id: str = "default") -> str:
        """异步：从记忆中获取应用路径（精确匹配）"""
        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()
        memories = await ms.query_memories(
            user_id=user_id,
            layer="medium",
            mem_type="app_path",
            limit=20
        )
        for mem in memories:
            content = mem.get("content", "") if isinstance(mem, dict) else str(mem)
            if app_name in content and "路径:" in content:
                parts = content.split("路径:", 1)
                if len(parts) == 2:
                    path = parts[1].strip()
                    if os.path.exists(path):
                        return path
        return None

    def _get_memorized_path(self, app_name: str, user_id: str = "default") -> str:
        """【Phase 2】从记忆中获取应用路径（精确匹配）"""
        return self._call_async(self._get_memorized_path_async(app_name, user_id))

    async def _get_vector_searched_path_async(self, app_name: str, user_id: str = "default") -> str:
        """异步：使用向量语义搜索查找应用路径"""
        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()
        results = await ms.retrieve_memories(
            user_id=user_id,
            query=f"{app_name} 路径",
            level="medium",
            limit=5,
            use_semantic=True
        )
        for mem in results:
            content = mem.get("content", "") if isinstance(mem, dict) else str(mem)
            if "路径:" in content:
                parts = content.split("路径:", 1)
                if len(parts) == 2:
                    path = parts[1].strip()
                    if os.path.exists(path):
                        return path
        return None

    def _get_vector_searched_path(self, app_name: str, user_id: str = "default") -> str:
        """【Phase 2增强】使用向量语义搜索查找应用路径"""
        return self._call_async(self._get_vector_searched_path_async(app_name, user_id))

    async def _memorize_path_async(self, app_name: str, exe_path: str, user_id: str = "default"):
        """异步：记忆应用路径"""
        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()
        content = f"{app_name}路径:{exe_path}"
        await ms.add_memory(
            user_id=user_id,
            content=content,
            memory_type="app_path",
            layer="medium",
            scene=f"app_{app_name}"
        )
        logger.info(f"[LaunchApp] 已记忆路径: {app_name} -> {exe_path}")

    def _memorize_path(self, app_name: str, exe_path: str, user_id: str = "default"):
        """【Phase 2】记忆应用路径"""
        try:
            self._call_async(self._memorize_path_async(app_name, exe_path, user_id))
        except Exception as e:
            logger.debug(f"[LaunchApp] 记忆路径失败: {e}")

    def _find_in_registry(self, exe_name: str) -> str:
        """【新增】查询 Windows 注册表 App Paths（最快）"""
        import winreg
        if not exe_name.lower().endswith('.exe'):
            exe_name += '.exe'

        for hkey in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
            try:
                with winreg.OpenKey(hkey,
                    f"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\{exe_name}") as key:
                    path, _ = winreg.QueryValueEx(key, None)
                    if path and os.path.exists(path):
                        return path
            except Exception:
                pass
        return None

    def _find_desktop_shortcut_fast(self, app_name: str, search_names: list) -> str:
        """【优化】桌面快捷方式查找 - 限制文件数避免卡死"""
        import glob

        desktop_paths = [
            os.path.join(os.path.expanduser("~"), "Desktop"),
            os.path.join(os.path.expanduser("~"), "桌面"),
        ]

        for desktop in desktop_paths:
            if not os.path.exists(desktop):
                continue

            # 【关键优化】只取前50个lnk文件，避免遍历整个桌面
            lnk_files = glob.glob(os.path.join(desktop, "*.lnk"))[:50]

            for lnk_file in lnk_files:
                lnk_name = os.path.splitext(os.path.basename(lnk_file))[0].lower()

                for search_name in search_names:
                    search_lower = search_name.lower().replace('.exe', '')
                    # 简单匹配：包含关系或前3字符相同
                    if (search_lower in lnk_name or
                        lnk_name in search_lower or
                        (len(search_lower) >= 3 and len(lnk_name) >= 3 and
                         search_lower[:3] == lnk_name[:3])):
                        try:
                            target = self._resolve_shortcut(lnk_file)
                            if target and os.path.exists(target):
                                return target
                        except Exception:
                            continue

        return None

    def _find_startmenu_shortcut_fast(self, app_name: str, search_names: list) -> str:
        """【新增】开始菜单快捷方式查找 - 限制文件数避免卡死"""
        import glob

        startmenu_paths = [
            os.path.join(os.environ.get("PROGRAMDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs"),
            os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "Microsoft", "Windows", "Start Menu", "Programs"),
        ]

        for startmenu in startmenu_paths:
            if not os.path.exists(startmenu):
                continue

            # 只取前30个lnk文件，避免遍历太多
            lnk_files = glob.glob(os.path.join(startmenu, "**", "*.lnk"), recursive=True)[:30]

            for lnk_file in lnk_files:
                lnk_name = os.path.splitext(os.path.basename(lnk_file))[0].lower()

                for search_name in search_names:
                    search_lower = search_name.lower().replace('.exe', '')
                    # 匹配逻辑与桌面相同
                    if (search_lower in lnk_name or
                        lnk_name in search_lower or
                        (len(search_lower) >= 3 and len(lnk_name) >= 3 and
                         search_lower[:3] == lnk_name[:3])):
                        try:
                            target = self._resolve_shortcut(lnk_file)
                            if target and os.path.exists(target):
                                logger.info(f"[LaunchApp] 通过开始菜单找到: {app_name} -> {target}")
                                return target
                        except Exception:
                            continue

        return None

    def _find_desktop_shortcut(self, app_name: str, search_names: list) -> str:
        """【新增】在桌面查找快捷方式并解析目标路径"""
        import glob

        desktop_paths = [
            os.path.join(os.path.expanduser("~"), "Desktop"),
            os.path.join(os.path.expanduser("~"), "桌面"),
        ]

        for desktop in desktop_paths:
            if not os.path.exists(desktop):
                continue

            # 搜索所有.lnk文件
            for lnk_file in glob.glob(os.path.join(desktop, "*.lnk")):
                lnk_name = os.path.splitext(os.path.basename(lnk_file))[0].lower()

                # 检查是否匹配搜索名称
                for search_name in search_names:
                    if search_name.lower() in lnk_name or lnk_name in search_name.lower():
                        try:
                            # 解析快捷方式目标
                            target = self._resolve_shortcut(lnk_file)
                            if target and os.path.exists(target) and not self._is_uninstaller(target):
                                logger.info(f"[LaunchApp] 通过桌面快捷方式找到应用: {app_name} -> {target}")
                                return os.path.normpath(target)
                        except Exception as e:
                            logger.debug(f"[LaunchApp] 解析快捷方式失败: {lnk_file}, {e}")

        return None

    def _find_startmenu_shortcut(self, app_name: str, search_names: list) -> str:
        """【新增】在开始菜单查找快捷方式"""
        import glob

        startmenu_paths = [
            os.path.join(os.environ.get("PROGRAMDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs"),
            os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "Microsoft", "Windows", "Start Menu", "Programs"),
        ]

        for startmenu in startmenu_paths:
            if not os.path.exists(startmenu):
                continue

            # 递归搜索所有.lnk文件
            for lnk_file in glob.glob(os.path.join(startmenu, "**", "*.lnk"), recursive=True):
                lnk_name = os.path.splitext(os.path.basename(lnk_file))[0].lower()

                for search_name in search_names:
                    if search_name.lower() in lnk_name or lnk_name in search_name.lower():
                        try:
                            target = self._resolve_shortcut(lnk_file)
                            if target and os.path.exists(target) and not self._is_uninstaller(target):
                                logger.info(f"[LaunchApp] 通过开始菜单找到应用: {app_name} -> {target}")
                                return os.path.normpath(target)
                        except Exception as e:
                            logger.debug(f"[LaunchApp] 解析快捷方式失败: {lnk_file}, {e}")

        return None

    def _resolve_shortcut(self, lnk_path: str) -> str:
        """【新增】解析Windows快捷方式(.lnk)的目标路径"""
        try:
            import win32com.client
            shell = win32com.client.Dispatch("WScript.Shell")
            shortcut = shell.CreateShortCut(lnk_path)
            target = shortcut.Targetpath
            # 如果目标是.exe，直接返回
            if target and target.endswith('.exe'):
                return target
            # 如果目标不是.exe（可能是脚本等），返回None
            return None
        except Exception as e:
            logger.debug(f"[LaunchApp] 解析快捷方式异常: {e}")
            return None

    def _find_exe_in_path(self, filename: str) -> str:
        """在PATH中查找可执行文件"""
        if not filename.endswith(".exe"):
            filename += ".exe"
        for path in os.environ["PATH"].split(os.pathsep):
            full = os.path.join(path, filename)
            if os.path.isfile(full):
                # 【修复】标准化返回的路径
                return os.path.normpath(full)
        return None

    def _is_uninstaller(self, path: str) -> bool:
        """检查是否是卸载程序"""
        lower = path.lower()
        uninstall_keywords = ['uninstall', 'uninst', '卸载', '删除']
        return any(kw in lower for kw in uninstall_keywords)

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
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                handle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ,
                                              False, pid)
                exe = win32process.GetModuleFileNameEx(handle, 0)
                win32api.CloseHandle(handle)
                process_name = os.path.basename(exe).lower()
            except Exception:
                process_name = ""
            if process_name == target_exe:
                abnormal = any(kw in title.lower() for kw in ['卸载', '修复', 'uninstall', 'repair'])
                windows.append({
                    "hwnd": hwnd,
                    "title": title,
                    "abnormal": abnormal
                })
            return True

        win32gui.EnumWindows(enum_callback, None)

        if not windows:
            return None
        normal = [w for w in windows if not w["abnormal"]]
        if normal:
            return normal[0]
        return windows[0]
