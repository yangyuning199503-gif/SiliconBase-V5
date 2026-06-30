#!/usr/bin/env python3
"""
SiliconBase V5 系统端口统一配置

【配置说明】
- HTTP API 端口: 8600 (默认)
- WebSocket 端口: 8600（与 HTTP API 同端口，统一由 FastAPI 处理）
- 前端开发服务器: 5173 (默认)

【环境变量覆盖】
- SILICONBASE_API_PORT: 覆盖 HTTP API 端口
- SILICONBASE_WS_PORT: 覆盖 WebSocket 端口
- SILICONBASE_FRONTEND_PORT: 覆盖前端开发服务器端口

【使用示例】
    from config.system_ports import SYSTEM_PORTS, get_api_url, get_ws_url

    api_url = get_api_url()      # http://127.0.0.1:8600
    ws_url = get_ws_url()        # ws://127.0.0.1:8600
"""

import os
from typing import Any

# ═══════════════════════════════════════════════════════════════════════════════
# 默认端口配置
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_PORTS = {
    "api": {
        "port": 8600,
        "host": "127.0.0.1",
        "scheme": "http",
    },
    "websocket": {
        "port": 8600,
        "host": "127.0.0.1",
        "scheme": "ws",
    },
    "frontend": {
        "port": 5173,
        "host": "127.0.0.1",
        "scheme": "http",
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# 环境变量读取
# ═══════════════════════════════════════════════════════════════════════════════

def _get_env_int(name: str, default: int) -> int:
    """从环境变量读取整数"""
    try:
        return int(os.environ.get(name, default))
    except (ValueError, TypeError):
        return default

def _get_env_str(name: str, default: str) -> str:
    """从环境变量读取字符串"""
    return os.environ.get(name, default)

# ═══════════════════════════════════════════════════════════════════════════════
# 系统端口配置 (支持环境变量覆盖)
# ═══════════════════════════════════════════════════════════════════════════════

SYSTEM_PORTS: dict[str, dict[str, Any]] = {
    "api": {
        "port": _get_env_int("SILICONBASE_API_PORT", DEFAULT_PORTS["api"]["port"]),
        "host": _get_env_str("SILICONBASE_API_HOST", DEFAULT_PORTS["api"]["host"]),
        "scheme": _get_env_str("SILICONBASE_API_SCHEME", DEFAULT_PORTS["api"]["scheme"]),
    },
    "websocket": {
        "port": _get_env_int("SILICONBASE_WS_PORT", DEFAULT_PORTS["websocket"]["port"]),
        "host": _get_env_str("SILICONBASE_WS_HOST", DEFAULT_PORTS["websocket"]["host"]),
        "scheme": _get_env_str("SILICONBASE_WS_SCHEME", DEFAULT_PORTS["websocket"]["scheme"]),
    },
    "frontend": {
        "port": _get_env_int("SILICONBASE_FRONTEND_PORT", DEFAULT_PORTS["frontend"]["port"]),
        "host": _get_env_str("SILICONBASE_FRONTEND_HOST", DEFAULT_PORTS["frontend"]["host"]),
        "scheme": _get_env_str("SILICONBASE_FRONTEND_SCHEME", DEFAULT_PORTS["frontend"]["scheme"]),
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════════════════════

def get_api_url(path: str = "") -> str:
    """获取 API 完整 URL"""
    cfg = SYSTEM_PORTS["api"]
    base = f"{cfg['scheme']}://{cfg['host']}:{cfg['port']}"
    return f"{base}{path}" if path else base

def get_ws_url(path: str = "") -> str:
    """获取 WebSocket 完整 URL"""
    cfg = SYSTEM_PORTS["websocket"]
    base = f"{cfg['scheme']}://{cfg['host']}:{cfg['port']}"
    return f"{base}{path}" if path else base

def get_frontend_url(path: str = "") -> str:
    """获取前端完整 URL"""
    cfg = SYSTEM_PORTS["frontend"]
    base = f"{cfg['scheme']}://{cfg['host']}:{cfg['port']}"
    return f"{base}{path}" if path else base

def get_port_info() -> dict[str, Any]:
    """获取完整端口信息"""
    return {
        "api": {
            **SYSTEM_PORTS["api"],
            "url": get_api_url()
        },
        "websocket": {
            **SYSTEM_PORTS["websocket"],
            "url": get_ws_url()
        },
        "frontend": {
            **SYSTEM_PORTS["frontend"],
            "url": get_frontend_url()
        }
    }

# ═══════════════════════════════════════════════════════════════════════════════
# 向后兼容的导出
# ═══════════════════════════════════════════════════════════════════════════════

API_PORT = SYSTEM_PORTS["api"]["port"]
API_HOST = SYSTEM_PORTS["api"]["host"]
WS_PORT = SYSTEM_PORTS["websocket"]["port"]
WS_HOST = SYSTEM_PORTS["websocket"]["host"]
FRONTEND_PORT = SYSTEM_PORTS["frontend"]["port"]

__all__ = [
    "SYSTEM_PORTS",
    "DEFAULT_PORTS",
    "get_api_url",
    "get_ws_url",
    "get_frontend_url",
    "get_port_info",
    "API_PORT",
    "API_HOST",
    "WS_PORT",
    "WS_HOST",
    "FRONTEND_PORT",
]

# ═══════════════════════════════════════════════════════════════════════════════
# 命令行测试
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import json
    print("=" * 60)
    print("SiliconBase V5 端口配置信息")
    print("=" * 60)
    print()
    print(json.dumps(get_port_info(), indent=2, ensure_ascii=False))
    print()
    print("=" * 60)
    print("环境变量设置示例:")
    print("=" * 60)
    print("  set SILICONBASE_API_PORT=8700     # 修改 API 端口")
    print("  set SILICONBASE_WS_PORT=8701      # 修改 WebSocket 端口")
    print("  set SILICONBASE_FRONTEND_PORT=3000 # 修改前端端口")
