"""
SiliconBase Cloud API 启动脚本

用于启动 API 服务

使用方法:
    python run.py              # 默认配置启动
    python run.py --port 8080  # 指定端口
    python run.py --host 127.0.0.1 --port 9000 --reload
"""

import os
import sys
from pathlib import Path

# ========== DPI 感知设置（必须在任何 GUI/截图操作之前）==========
if sys.platform == "win32":
    try:
        from core.vision.dpi import set_process_dpi_aware
        set_process_dpi_aware()
    except Exception:
        pass

# ========== 【P0-001】优先加载 .env 文件环境变量 ==========
# 必须在任何其他导入之前加载，否则会导致配置初始化时环境变量未设置
try:
    from dotenv import load_dotenv
    dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path, override=True, interpolate=True)  # interpolate=True 展开 ${VAR} 变量引用
        print(f"[配置] 已加载环境变量: {dotenv_path}")
        # 验证 POSTGRES_PASSWORD 是否加载成功
        pg_pwd = os.environ.get('POSTGRES_PASSWORD', '')
        if pg_pwd:
            print(f"[配置] PostgreSQL密码已设置 ({len(pg_pwd)}字符)")
    else:
        print(f"[配置] 【警告】.env 文件未找到: {dotenv_path}")
except ImportError:
    print("[配置] 【警告】python-dotenv 未安装，无法加载 .env 文件")

# ========== Windows多进程支持 ==========
# 【CRITICAL】必须在其他导入之前调用freeze_support()
# 否则multiprocessing会导致子进程重新导入主模块，引发系统重启
if sys.platform == 'win32':
    import multiprocessing
    multiprocessing.freeze_support()

import argparse

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ========== Windows asyncio 事件循环策略修复 ==========
# 【修复】Windows 上使用 SelectorEventLoopPolicy 避免 lifespan 阻塞
if sys.platform == 'win32':
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    print("[系统] Windows事件循环策略已设置")

import uvicorn

# 【P1修复】WebSocket 心跳参数从环境变量读取，避免后端忙时误断
WS_PING_INTERVAL = float(os.getenv("UVICORN_WS_PING_INTERVAL", "30.0"))
WS_PING_TIMEOUT = float(os.getenv("UVICORN_WS_PING_TIMEOUT", "60.0"))


def main():
    parser = argparse.ArgumentParser(description="SiliconBase Cloud API Server")
    # 【云端部署】默认使用 0.0.0.0 允许外部访问
    # 本地开发请使用: --host 127.0.0.1
    parser.add_argument("--host", default="0.0.0.0", help="主机地址 (默认: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8600, help="端口号 (默认: 8600)")
    parser.add_argument("--reload", action="store_true", help="启用热重载（开发模式）")
    parser.add_argument("--workers", type=int, default=1, help="工作进程数（生产环境）")
    parser.add_argument("--log-level", default="info",
                        choices=["debug", "info", "warning", "error", "critical"],
                        help="日志级别")

    args = parser.parse_args()

    print(f"""
    ╔═══════════════════════════════════════════════════════════╗
    ║              SiliconBase Cloud API                        ║
    ║                   云端部署 API 服务                        ║
    ╠═══════════════════════════════════════════════════════════╣
    ║  文档地址: http://{args.host}:{args.port}/docs                     ║
    ║  WebSocket: ws://{args.host}:{args.port}/ws/{{user_id}}            ║
    ╠═══════════════════════════════════════════════════════════╣
    ║  端口配置:                                                ║
    ║    - HTTP API:  {args.port}                                   ║
    ║    - WebSocket: {args.port} (统一由 FastAPI 处理)             ║
    ╚═══════════════════════════════════════════════════════════╝
    """)

    # 根据模式选择启动方式
    print(f"[启动] 正在启动后端服务: {args.host}:{args.port}")
    print("[启动] 正在加载核心模块...", flush=True)

    # 预导入模块，确保在 Uvicorn 启动前完成所有初始化
    try:
        print("[启动] 【成功】核心模块加载完成", flush=True)
    except Exception as e:
        print(f"[启动] 【失败】核心模块加载失败: {e}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print("[启动] 正在启动服务器...", flush=True)

    # ========== Windows 兼容性参数 ==========
    # 【修复】使用 h11 HTTP 解析器替代 httptools，解决 Windows 兼容性问题
    # 【关键修复】直接传入 app 对象而不是字符串，避免 Windows 上的重新导入问题
    uvicorn_kwargs = {
        "host": args.host,
        "port": args.port,
        "log_level": args.log_level,
        "loop": "asyncio",        # 明确指定 asyncio 事件循环
        "http": "h11",            # 使用纯 Python h11 替代 C 扩展 httptools
        "access_log": False,      # 【修复】Windows start命令创建新控制台后stdout句柄关闭，禁用access_log避免ValueError: I/O operation on closed file
        "ws_ping_interval": WS_PING_INTERVAL,  # WebSocket ping 间隔
        "ws_ping_timeout": WS_PING_TIMEOUT,    # WebSocket ping 超时
    }

    # 【修复】配置 uvicorn 日志输出到文件，避免 Windows 控制台关闭时 stdout 句柄已失效导致崩溃
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    uvicorn_log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            },
        },
        "handlers": {
            "default": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "default",
                "filename": str(log_dir / "uvicorn.log"),
                "maxBytes": 10 * 1024 * 1024,
                "backupCount": 5,
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO"},
            "uvicorn.error": {"handlers": ["default"], "level": "INFO"},
            "uvicorn.access": {"handlers": ["default"], "level": "INFO"},
            "websockets": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "websockets.server": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.protocols.websockets": {"handlers": ["default"], "level": "INFO"},
        },
    }

    try:
        # 【修复】Windows上使用字符串形式启动，确保HTTP服务正确绑定
        print(f"[启动] 服务器运行中: http://{args.host}:{args.port}", flush=True)
        uvicorn.run(
            "api.cloud_api:app",
            reload=args.reload,
            log_config=uvicorn_log_config,
            **uvicorn_kwargs
        )
    except Exception as e:
        print(f"[启动] 【错误】服务器启动失败: {e}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
