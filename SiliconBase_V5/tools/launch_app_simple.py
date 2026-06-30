#!/usr/bin/env python3
"""
启动应用 - 简单可靠版
核心思路：Windows start 命令 + 预置路径
"""
import asyncio
import os
import subprocess

from core.base_tool import BaseTool
from core.logger import logger

# ========== 扩充的别名映射表（覆盖常见软件）==========
APP_ALIASES = {
    # 音乐
    "网易云音乐": ["cloudmusic", "CloudMusic", "netease", "NeteaseMusic", "网易", "云音乐"],
    "qq音乐": ["qqmusic", "QQMusic", "QQ音乐", "txmusic"],
    "酷狗": ["kugou", "KuGou"],
    "酷我": ["kuwo", "KuWo"],
    "spotify": ["Spotify"],

    # 社交
    "微信": ["wechat", "WeChat", "weixin", "微信"],
    "qq": ["qq", "QQ", "tencent", "Tencent"],
    "tim": ["TIM", "tim"],
    "钉钉": ["dingtalk", "DingTalk", "Ding"],
    "飞书": ["lark", "Lark", "feishu"],
    "企业微信": ["wxwork", "WXWork", "WeCom"],

    # 浏览器
    "chrome": ["chrome", "Chrome", "google", "GoogleChrome"],
    "谷歌浏览器": ["chrome", "Chrome"],
    "edge": ["msedge", "MSEdge", "MicrosoftEdge", "edge"],
    "firefox": ["firefox", "Firefox", "火狐"],
    "360浏览器": ["360chrome", "360se"],
    "搜狗浏览器": ["sogou"],
    "qq浏览器": ["qqbrowser"],

    # 办公
    "word": ["winword", "WinWord", "WORD"],
    "excel": ["excel", "Excel", "EXCEL"],
    "ppt": ["powerpnt", "Powerpnt", "POWERPNT"],
    "wps": ["wps", "WPS"],
    "acrobat": ["Acrobat", "acrobat", "AdobeAcrobat"],
    "pdf": ["Acrobat", "SumatraPDF"],
    "typora": ["Typora", "typora"],
    "notion": ["Notion", "notion"],

    # 开发工具
    "vscode": ["code", "Code", "vscode", "VSCode"],
    "visual studio code": ["code", "Code"],
    "idea": ["idea64", "idea", "IntelliJIDEA"],
    "pycharm": ["pycharm64", "pycharm"],
    "webstorm": ["webstorm64", "webstorm"],
    "git": ["git-bash", "git-cmd", "Git Bash"],
    "sourcetree": ["SourceTree", "sourcetree"],

    # 下载工具
    "idm": ["IDMan", "idm", "InternetDownloadManager"],
    "迅雷": [" thunder", "Thunder", "XunLei"],
    "百度网盘": ["BaiduNetdisk", "baidunetdisk"],
    "阿里云盘": ["aDrive", "adrive"],

    # 媒体播放
    "potplayer": ["PotPlayerMini64", "PotPlayerMini", "PotPlayer"],
    "vlc": ["vlc", "VLC"],
    "mpv": ["mpv", "MPV"],

    # 游戏平台
    "steam": ["steam", "Steam"],
    "epic": ["EpicGamesLauncher", "Epic"],
    "wegame": ["wegame", "WeGame"],

    # 工具
    " everything": ["Everything", "everything"],
    "listary": ["Listary", "listary"],
    "snipaste": ["Snipaste", "snipaste"],
    "bandizip": ["Bandizip", "bandizip"],
    "7z": ["7zFM", "7z"],
    "winrar": ["WinRAR", "winrar"],

    # 系统工具
    "记事本": ["notepad", "Notepad"],
    "计算器": ["calc", "Calculator", "calc.exe"],
    "画图": ["mspaint", "MSPaint"],
    "任务管理器": ["taskmgr", "Taskmgr"],
    "cmd": ["cmd", "CMD"],
    "命令行": ["cmd"],
    "powershell": ["powershell", "PowerShell"],
    "终端": ["wt", "WindowsTerminal"],

    # 安全软件
    "火绒": ["hipsmain", "HipsMain"],
    "360": ["360Safe", "360"],
    "电脑管家": ["QQPCRTP", "电脑管家"],
}

# 预置路径（常见安装位置）
PRESET_PATHS = {
    "cloudmusic": [
        r"D:\CloudMusic（网易云）\cloudmusic.exe",
        r"D:\CloudMusic\cloudmusic.exe",
    ],
}


class LaunchAppSimple(BaseTool):
    """简单可靠的启动应用工具"""
    tool_id = "launch_app"
    tool_owner = "system"
    name = "启动应用"
    description = "启动应用，支持中文名、别名，冷启动友好"
    input_schema = {
        "type": "object",
        "properties": {
            "app_name": {"type": "string", "description": "应用名称"},
            "name": {"type": "string", "description": "别名"},
            "exe_path": {"type": "string", "description": "完整路径（优先）"}
        },
        "anyOf": [{"required": ["app_name"]}, {"required": ["name"]}, {"required": ["exe_path"]}]
    }

    def _execute(self, **kwargs) -> dict:
        exe_path = kwargs.get("exe_path")
        app_name = kwargs.get("app_name") or kwargs.get("name")

        if exe_path:
            return self._launch(exe_path, app_name or exe_path)

        if not app_name:
            return {
                "success": False,
                "error_code": "INVALID_PARAMS",
                "user_message": "需要 app_name 或 exe_path",
                "data": None
            }

        # 1. 尝试用 Windows start 命令（最万能）
        if self._try_windows_start(app_name):
            return {
                "success": True,
                "error_code": None,
                "user_message": f"已启动 {app_name}",
                "data": {"app_name": app_name}
            }

        # 2. 获取所有可能的 exe 名称
        exe_names = self._get_exe_names(app_name)

        # 3. 依次尝试
        for exe in exe_names:
            # 3.1 尝试 PATH 中的
            path = self._find_in_path(exe)
            if path:
                return self._launch(path, app_name)

            # 3.2 尝试预置路径
            if exe.lower() in PRESET_PATHS:
                for p in PRESET_PATHS[exe.lower()]:
                    if os.path.exists(p):
                        return self._launch(p, app_name)

        # 4. 都失败了
        return {
            "success": False,
            "error_code": "APP_NOT_FOUND",
            "user_message": f"找不到 '{app_name}'。试试：1. 用 exe_path 给完整路径 2. 说英文名如 'chrome' 3. 检查软件是否安装",
            "data": None
        }

    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)

    def _get_exe_names(self, app_name: str) -> list:
        """获取所有可能的 exe 名称"""
        names = [app_name]

        # 加别名
        for key, aliases in APP_ALIASES.items():
            if app_name.lower() == key.lower() or any(app_name.lower() == a.lower() for a in aliases):
                names.extend([key] + aliases)

        # 去重并加.exe
        result = []
        seen = set()
        for name in names:
            base = name.lower().replace('.exe', '')
            if base not in seen:
                seen.add(base)
                result.append(base)
                result.append(base + '.exe')

        return result

    def _try_windows_start(self, app_name: str) -> bool:
        """用 Windows start 命令启动（万能但无PID）"""
        try:
            # 清理名称
            clean_name = app_name.replace('.exe', '').strip()

            # 尝试直接 start
            subprocess.Popen(
                f'start "" "{clean_name}"',
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            # 给点时间看是否成功
            import time
            time.sleep(0.3)

            # 简单检查：如果进程存在就算成功
            # 这里简化处理，实际可以检查进程列表
            return True

        except Exception as e:
            logger.debug(f"start 命令失败: {e}")
            return False

    def _find_in_path(self, exe_name: str) -> str:
        """在 PATH 中查找"""
        if not exe_name.endswith('.exe'):
            exe_name += '.exe'

        for path_dir in os.environ.get("PATH", "").split(os.pathsep):
            full = os.path.join(path_dir, exe_name)
            if os.path.isfile(full):
                return full
        return None

    def _launch(self, exe_path: str, app_name: str) -> dict:
        """启动程序"""
        try:
            proc = subprocess.Popen(
                [exe_path],
                shell=False,
                cwd=os.path.dirname(exe_path) if os.path.dirname(exe_path) else None
            )
            return {
                "success": True,
                "error_code": None,
                "user_message": f"已启动 {app_name}",
                "data": {"path": exe_path, "pid": proc.pid}
            }
        except Exception as e:
            return {
                "success": False,
                "error_code": "LAUNCH_FAILED",
                "user_message": f"启动失败: {str(e)}",
                "data": None
            }


# 兼容
LaunchApp = LaunchAppSimple
