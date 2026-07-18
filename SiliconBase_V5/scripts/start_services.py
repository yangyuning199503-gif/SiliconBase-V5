#!/usr/bin/env python3
"""
SiliconBase V5 服务启动脚本

提供统一的启动入口，自动检查端口配置并启动服务。

用法:
    python scripts/start_services.py          # 启动所有服务
    python scripts/start_services.py --api    # 仅启动 API
    python scripts/start_services.py --ws     # 仅启动 WebSocket
    python scripts/start_services.py --check  # 仅检查配置
"""

import argparse
import os
import socket
import subprocess
import sys
import time

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config.system_ports import SYSTEM_PORTS, get_api_url, get_ws_url
except ImportError:
    print("[ERROR] 无法导入端口配置")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════════════════

def is_port_in_use(host: str, port: int) -> bool:
    """检查端口是否被占用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True

def wait_for_port(host: str, port: int, timeout: int = 30) -> bool:
    """等待端口就绪"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        if not is_port_in_use(host, port):
            # 端口未被占用，服务可能已启动或已关闭
            time.sleep(0.5)
            continue
        # 端口被占用，尝试连接
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            try:
                s.connect((host, port))
                return True
            except Exception as e:
                print(f"[WARNING] 连接端口失败: {e}")
        time.sleep(0.5)
    return False

def print_banner():
    """打印启动横幅"""
    print("""
╔═══════════════════════════════════════════════════════════════════════╗
║                                                                       ║
║              SiliconBase V5 - 硅基生命底座                             ║
║                                                                       ║
╠═══════════════════════════════════════════════════════════════════════╣
║  端口配置:                                                            ║
║    - HTTP API:   {}:{:5}  →  {}  ║
║    - WebSocket:  {}:{:5}  →  {}  ║
╚═══════════════════════════════════════════════════════════════════════╝
    """.format(
        SYSTEM_PORTS['api']['host'], SYSTEM_PORTS['api']['port'], get_api_url(),
        SYSTEM_PORTS['websocket']['host'], SYSTEM_PORTS['websocket']['port'], get_ws_url()
    ))

# ═══════════════════════════════════════════════════════════════════════════════
# 服务启动函数
# ═══════════════════════════════════════════════════════════════════════════════

def start_api_server() -> subprocess.Popen | None:
    """启动 API 服务器"""
    api_cfg = SYSTEM_PORTS['api']
    host = api_cfg['host']
    port = api_cfg['port']

    if is_port_in_use(host, port):
        print(f"[WARNING] API 端口 {port} 已被占用，可能已有服务运行")
        return None

    print("[INFO] 正在启动 API 服务器...")
    print(f"[INFO] 监听地址: {host}:{port}")

    try:
        # 使用 api/run.py 启动
        proc = subprocess.Popen(
            [sys.executable, "-m", "api.run", "--host", host, "--port", str(port)],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # 等待服务启动
        if wait_for_port(host, port, timeout=10):
            print(f"[OK] API 服务器已启动: {get_api_url()}")
            return proc
        else:
            print("[ERROR] API 服务器启动超时")
            proc.terminate()
            return None

    except Exception as e:
        print(f"[ERROR] 启动 API 服务器失败: {e}")
        return None

def check_configuration():
    """检查配置"""
    print("=" * 70)
    print("配置检查")
    print("=" * 70)
    print()

    api_cfg = SYSTEM_PORTS['api']
    ws_cfg = SYSTEM_PORTS['websocket']

    # 检查端口占用
    api_in_use = is_port_in_use(api_cfg['host'], api_cfg['port'])
    ws_in_use = is_port_in_use(ws_cfg['host'], ws_cfg['port'])

    print(f"HTTP API ({api_cfg['host']}:{api_cfg['port']}):")
    print(f"  URL: {get_api_url()}")
    print(f"  端口状态: {'被占用' if api_in_use else '空闲'}")
    print()

    print(f"WebSocket ({ws_cfg['host']}:{ws_cfg['port']}):")
    print(f"  URL: {get_ws_url()}")
    print(f"  端口状态: {'被占用' if ws_in_use else '空闲'}")
    print()

    if not api_in_use:
        print("[OK] API/WebSocket 端口空闲，可以启动服务")
    else:
        print("[INFO] 服务可能已在运行")

    print()
    return True

# ═══════════════════════════════════════════════════════════════════════════════
# 主函数
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="SiliconBase V5 服务启动脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/start_services.py          # 启动服务
  python scripts/start_services.py --api    # 仅启动 API 服务
  python scripts/start_services.py --check  # 仅检查配置
        """
    )
    parser.add_argument("--api", action="store_true", help="仅启动 API 服务")
    parser.add_argument("--check", action="store_true", help="仅检查配置")

    args = parser.parse_args()

    print_banner()

    if args.check:
        check_configuration()
        return

    # 启动服务（WebSocket 统一由 API 服务器处理）
    if args.api or not args.check:
        start_api_server()
        print()

    print("=" * 70)
    print("启动完成")
    print("=" * 70)
    print()
    print("按 Ctrl+C 停止服务")

    try:
        # 保持运行
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[INFO] 正在停止服务...")

if __name__ == "__main__":
    main()
