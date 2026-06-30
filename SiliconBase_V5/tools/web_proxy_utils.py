#!/usr/bin/env python3
"""
Windows 系统代理读取工具

让 Python 的 HTTP 客户端（aiohttp/requests/playwright）自动跟随
Windows 系统代理设置，避免浏览器能访问外网但 Python 工具不行的尴尬。
"""

import os
import sys

IS_WINDOWS = sys.platform == "win32"


def _get_windows_system_proxy() -> str | None:
    """
    读取 Windows 注册表中的系统代理设置。

    Returns:
        代理 URL（如 http://127.0.0.1:19828）或 None
    """
    if not IS_WINDOWS:
        return None

    try:
        import winreg
    except ImportError:
        return None

    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        )
        proxy_enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
        proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
        winreg.CloseKey(key)

        if not proxy_enable or not proxy_server:
            return None

        # ProxyServer 可能是 "127.0.0.1:19828" 或 "http=127.0.0.1:19828;https=127.0.0.1:19828"
        # 我们统一处理成 http:// 前缀的 URL
        proxy_server = proxy_server.strip()

        if proxy_server.startswith("http://") or proxy_server.startswith("https://"):
            return proxy_server

        # 如果包含分号，取 https= 或 http= 后面的值
        if ";" in proxy_server:
            parts = {}
            for segment in proxy_server.split(";"):
                if "=" in segment:
                    proto, addr = segment.split("=", 1)
                    parts[proto.strip()] = addr.strip()
            # 优先 https，其次 http
            addr = parts.get("https") or parts.get("http")
            if addr:
                return f"http://{addr}"
            return None

        # 简单的 host:port 格式
        return f"http://{proxy_server}"

    except FileNotFoundError:
        return None
    except Exception:
        return None


def get_system_proxy() -> str | None:
    """
    获取系统代理地址。

    优先级：
    1. 环境变量 HTTPS_PROXY / https_proxy / HTTP_PROXY / http_proxy
    2. Windows 注册表中的系统代理设置

    Returns:
        代理 URL（如 http://127.0.0.1:19828）或 None
    """
    # 1. 环境变量优先
    for env_var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        proxy = os.environ.get(env_var)
        if proxy:
            return proxy

    # 2. Windows 系统代理
    return _get_windows_system_proxy()


def requests_proxies() -> dict:
    """
    生成 requests 库可用的 proxies 字典。

    Returns:
        {"http": proxy, "https": proxy} 或 {}
    """
    proxy = get_system_proxy()
    if proxy:
        return {"http": proxy, "https": proxy}
    return {}


def aiohttp_proxy() -> str | None:
    """
    生成 aiohttp 可用的 proxy 字符串。

    Returns:
        如 http://127.0.0.1:19828 或 None
    """
    return get_system_proxy()


def playwright_proxy() -> dict | None:
    """
    生成 Playwright 可用的 proxy 配置字典。

    Returns:
        {"server": "http://127.0.0.1:19828"} 或 None
    """
    proxy = get_system_proxy()
    if proxy:
        return {"server": proxy}
    return None
