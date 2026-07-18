#!/usr/bin/env python3
"""
SiliconBase V5 - 一键启动脚本
启动顺序: PostgreSQL → 后端 → 前端
"""
import logging
import signal
import subprocess
import sys
import time
from pathlib import Path

# 配置日志
logger = logging.getLogger(__name__)

# 进程列表，用于优雅退出
processes = []

def print_banner():
    print("""
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║   SiliconBase V5.0 - 一键启动器                          ║
║                                                          ║
║   启动顺序: PostgreSQL → 后端API → 前端                  ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
""")

def run_in_terminal(title, command, cwd):
    """在新终端窗口中运行命令"""
    try:
        # 使用 PowerShell 启动新窗口
        ps_command = f'Start-Process powershell -ArgumentList "-NoExit","-Command","chcp 65001; cd \\"{cwd}\\"; {command}" -WindowStyle Normal -Verb RunAs'
        subprocess.Popen(['powershell', '-Command', ps_command], cwd=cwd)
        print(f"[✓] {title} 启动窗口已打开")
        return True
    except Exception as e:
        print(f"[x] 启动 {title} 失败: {e}")
        return False

def check_postgres():
    """检查PostgreSQL是否运行"""
    import os
    password = os.environ.get('POSTGRES_PASSWORD', '')
    if not password:
        raise RuntimeError(
            "[StartAll] 错误: 未设置 POSTGRES_PASSWORD 环境变量。\n"
            "    请设置: set POSTGRES_PASSWORD=your_password"
        )
    try:
        import psycopg2
        conn = psycopg2.connect(
            host='localhost', port=5432, database='siliconbase',
            user='postgres', password=password
        )
        conn.close()
        return True
    except ImportError as e:
        logger.error(f"[StartAll] psycopg2模块未安装: {e}", exc_info=True)
        print("❌ PostgreSQL连接失败: psycopg2模块未安装")
        return False
    except psycopg2.OperationalError as e:
        logger.warning(f"[StartAll] PostgreSQL连接失败 (服务可能未运行): {e}")
        return False
    except psycopg2.Error as e:
        logger.error(f"[StartAll] PostgreSQL连接错误: {e}", exc_info=True)
        print(f"❌ PostgreSQL连接错误: {e}")
        return False
    except Exception as e:
        logger.error(f"[StartAll] PostgreSQL检查未知错误: {e}", exc_info=True)
        print(f"❌ PostgreSQL检查未知错误: {e}")
        return False

def signal_handler(sig, frame):
    """Ctrl+C 信号处理"""
    print('\n[!] 接收到中断信号，正在关闭...')
    sys.exit(0)

def main():
    print_banner()

    # 注册信号处理
    signal.signal(signal.SIGINT, signal_handler)

    # 获取项目目录
    script_dir = Path(__file__).parent.resolve()
    print(f"[i] 项目目录: {script_dir}\n")

    # ===== 第1步: 启动 PostgreSQL =====
    print("=" * 50)
    print("步骤 1/3: 启动 PostgreSQL")
    print("=" * 50)

    if check_postgres():
        print("[✓] PostgreSQL 已在运行\n")
    else:
        print("[!] PostgreSQL 未运行，尝试启动...")
        subprocess.run([sys.executable, str(script_dir / "start_postgres.py")])
        time.sleep(3)

        if check_postgres():
            print("[✓] PostgreSQL 启动成功\n")
        else:
            print("[x] PostgreSQL 启动失败，请手动检查\n")
            input("按回车键退出...")
            return

    # ===== 第2步: 启动后端 =====
    print("=" * 50)
    print("步骤 2/3: 启动后端API服务")
    print("=" * 50)

    backend_cmd = f'& "{script_dir}\\.venv\\Scripts\\python.exe" api/run.py'
    if run_in_terminal("后端API", backend_cmd, script_dir):
        print("[i] 后端API 地址: http://localhost:8600")
        print("[i] API文档: http://localhost:8600/docs\n")
        time.sleep(2)
    else:
        print("[x] 后端启动失败\n")

    # ===== 第3步: 启动前端 =====
    print("=" * 50)
    print("步骤 3/3: 启动前端")
    print("=" * 50)

    frontend_dir = script_dir / "frontend"
    if not (frontend_dir / "node_modules").exists():
        print("[i] 首次运行，需要先安装前端依赖...")
        print("    执行: npm install")
        subprocess.run(['powershell', '-Command', f'cd "{frontend_dir}"; npm install'])

    frontend_cmd = 'npm run dev'
    if run_in_terminal("前端", frontend_cmd, frontend_dir):
        print("[i] 前端地址: http://localhost:5173")
        print("[i] 等待启动中...\n")
    else:
        print("[x] 前端启动失败\n")

    # ===== 启动完成 =====
    print("=" * 50)
    print("所有服务已启动！")
    print("=" * 50)
    print("""
访问地址:
  • 前端界面: http://localhost:5173
  • 后端API:  http://localhost:8600
  • API文档:  http://localhost:8600/docs
  • 数据库:   PostgreSQL localhost:5432

快捷操作:
  • 按 Ctrl+C 关闭此窗口（服务继续运行）
  • 关闭终端窗口可停止对应服务
  • 日志显示在各服务窗口中
    """)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[!] 监控已停止，服务仍在运行")
        print("    关闭各终端窗口可停止服务")

if __name__ == "__main__":
    main()
