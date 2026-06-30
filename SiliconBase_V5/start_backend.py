#!/usr/bin/env python3
"""
SiliconBase V5 - 后端API启动脚本
"""
import logging
import subprocess
import sys
import time
from pathlib import Path

# 配置日志
logger = logging.getLogger(__name__)

def print_banner():
    print("""
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║   SiliconBase V5 - 后端API启动器                         ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
""")

def check_venv():
    """检查虚拟环境"""
    script_dir = Path(__file__).parent.resolve()
    venv_python = script_dir / ".venv" / "Scripts" / "python.exe"

    if not venv_python.exists():
        print("[x] 虚拟环境不存在，请运行:")
        print("    python -m venv .venv")
        print("    .venv\\Scripts\\pip install -r requirements.txt")
        return None

    return str(venv_python)

def main():
    print_banner()

    script_dir = Path(__file__).parent.resolve()
    print(f"[i] 项目目录: {script_dir}")

    # 检查虚拟环境
    print("[i] 检查虚拟环境...")
    venv_python = check_venv()
    if not venv_python:
        input("\n按回车键退出...")
        return

    print(f"[✓] 虚拟环境: {venv_python}")

    # 检查关键依赖
    print("[i] 检查关键依赖...")
    try:
        subprocess.run(
            [venv_python, "-c", "import fastapi; import psycopg2"],
            capture_output=True,
            check=True
        )
        print("[✓] 依赖已安装")
    except subprocess.CalledProcessError as e:
        logger.error(f"[StartBackend] 依赖检查失败: {e}", exc_info=True)
        print("[!] 依赖可能不完整，尝试安装...")
        subprocess.run(
            [venv_python, "-m", "pip", "install", "-r", "requirements.txt"],
            cwd=script_dir
        )
    except FileNotFoundError as e:
        logger.error(f"[StartBackend] 虚拟环境Python解释器不存在: {e}", exc_info=True)
        print(f"❌ 虚拟环境Python解释器不存在: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"[StartBackend] 依赖检查未知错误: {e}", exc_info=True)
        print(f"❌ 依赖检查未知错误: {e}")
        sys.exit(1)

    # 启动后端
    print("\n" + "="*50)
    print("正在启动后端API服务...")
    print("="*50)
    print("服务地址: http://localhost:8600")
    print("API文档:  http://localhost:8600/docs")
    print("健康检查: http://localhost:8600/api/health")
    print("="*50 + "\n")

    try:
        # 使用PowerShell启动新窗口
        ps_command = (
            f'Start-Process powershell -ArgumentList '
            f'"-NoExit","-Command","cd \\"{script_dir}\\"; \\"{venv_python}\\" api/run.py" '
            f'-WindowStyle Normal'
        )
        subprocess.run(['powershell', '-Command', ps_command])
        print("[✓] 后端服务窗口已打开")

        # 等待服务启动
        print("[i] 等待服务启动...")
        time.sleep(3)

        # 检查服务是否运行
        import urllib.request
        try:
            urllib.request.urlopen('http://localhost:8600/api/health', timeout=5)
            print("[✓] 后端服务已就绪！")
        except urllib.error.URLError as e:
            logger.warning(f"[StartBackend] 健康检查失败 (服务可能仍在启动中): {e}")
            print("[!] 服务启动中，请稍后再检查...")
        except urllib.error.HTTPError as e:
            logger.error(f"[StartBackend] 健康检查HTTP错误: {e}", exc_info=True)
            print(f"❌ 健康检查HTTP错误: {e}")
        except Exception as e:
            logger.error(f"[StartBackend] 健康检查未知错误: {e}", exc_info=True)
            print(f"❌ 健康检查未知错误: {e}")

    except Exception as e:
        print(f"[x] 启动失败: {e}")
        print("\n尝试直接启动...")
        subprocess.run([venv_python, "api/run.py"], cwd=script_dir)

    input("\n按回车键退出...")

if __name__ == "__main__":
    main()
