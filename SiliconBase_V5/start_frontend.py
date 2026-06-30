#!/usr/bin/env python3
"""
SiliconBase V5 前端启动脚本
使用 PowerShell 执行 npm 命令，避免环境变量问题
"""
import subprocess
import time
import webbrowser
from pathlib import Path


def print_banner():
    print("""
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║   SiliconBase V5.0 - 前端启动器                          ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
""")

def run_powershell_command(command, cwd):
    """使用 PowerShell 执行命令"""
    ps_command = f'cd "{cwd}"; {command}'
    return subprocess.run(
        ['powershell', '-Command', ps_command],
        capture_output=True,
        text=True
    )

def main():
    print_banner()

    # 获取脚本所在目录的绝对路径
    script_dir = Path(__file__).parent.resolve()
    frontend_dir = script_dir / "frontend"

    print(f"[i] 脚本目录: {script_dir}")
    print(f"[i] 前端目录: {frontend_dir}")

    # 检查前端目录是否存在
    if not frontend_dir.exists():
        print(f"[x] 错误: 前端目录不存在: {frontend_dir}")
        print("    请确保 frontend 文件夹在正确的位置")
        input("\n按回车键退出...")
        return

    # 检查Node.js
    print("\n[i] 检查 Node.js...")
    result = run_powershell_command('node -v', frontend_dir)
    if result.returncode != 0:
        print("[x] 未检测到Node.js，请先安装")
        print("    下载地址: https://nodejs.org/")
        print("\n或者手动进入 frontend 目录执行:")
        print("    cd frontend")
        print("    npm install")
        print("    npm run dev")
        input("\n按回车键退出...")
        return

    print(f"[ok] Node.js 已安装: {result.stdout.strip()}")

    # 安装依赖
    if not (frontend_dir / "node_modules").exists():
        print("\n[i] 首次运行，正在安装依赖（可能需要几分钟）...")
        print("    执行: npm install")
        result = run_powershell_command('npm install', frontend_dir)
        if result.returncode != 0:
            print("[x] 依赖安装失败:")
            print(result.stderr)
            input("\n按回车键退出...")
            return
        print("[ok] 依赖安装完成")
    else:
        print("[ok] 依赖已安装")

    # 启动前端
    print("\n[i] 正在启动前端...")
    print("    访问地址: http://localhost:8600/docs")
    print("    按 Ctrl+C 停止\n")

    # 延迟后打开浏览器
    def open_browser_delayed():
        time.sleep(3)
        webbrowser.open("http://localhost:8600/docs")

    import threading
    threading.Thread(target=open_browser_delayed, daemon=True).start()

    # 运行前端（使用 PowerShell 启动新窗口）
    ps_command = f'cd "{frontend_dir}"; npm run dev'
    subprocess.run(['powershell', '-Command', ps_command])

if __name__ == "__main__":
    main()
