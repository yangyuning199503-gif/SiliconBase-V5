#!/usr/bin/env python3
"""
SiliconBase V5 - PostgreSQL 启动/检查脚本
"""
import subprocess
import time


def print_banner():
    print("""
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║   SiliconBase V5 - PostgreSQL 启动器                     ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
""")

def check_postgres_service():
    """检查 PostgreSQL 服务状态"""
    try:
        result = subprocess.run(
            ['sc', 'query', 'PostgreSQL'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )
        if result.returncode == 0:
            if 'RUNNING' in result.stdout:
                return 'running'
            elif 'STOPPED' in result.stdout:
                return 'stopped'
        return 'not_installed'
    except Exception as e:
        print(f"[x] 检查服务失败: {e}")
        return 'error'

def start_postgres_service():
    """启动 PostgreSQL 服务"""
    print("[i] 正在启动 PostgreSQL 服务...")
    try:
        result = subprocess.run(
            ['net', 'start', 'PostgreSQL'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )
        if result.returncode == 0:
            print("[✓] PostgreSQL 服务已启动")
            return True
        else:
            print(f"[x] 启动失败: {result.stderr}")
            return False
    except Exception as e:
        print(f"[x] 启动出错: {e}")
        return False

def check_postgres_connection():
    """测试 PostgreSQL 连接"""
    import os
    password = os.environ.get('POSTGRES_PASSWORD', '')
    if not password:
        raise RuntimeError(
            "[StartPostgres] 错误: 未设置 POSTGRES_PASSWORD 环境变量。\n"
            "    请设置: set POSTGRES_PASSWORD=your_password"
        )

    print("[i] 测试数据库连接...")
    try:
        import psycopg2
        conn = psycopg2.connect(
            host='localhost',
            port=5432,
            database='siliconbase',
            user='postgres',
            password=password
        )
        cur = conn.cursor()
        cur.execute('SELECT version()')
        version = cur.fetchone()[0]
        cur.close()
        conn.close()
        print(f"[✓] 连接成功: {version}")
        return True
    except ImportError:
        print("[x] 缺少 psycopg2，请安装: pip install psycopg2-binary")
        return False
    except Exception as e:
        print(f"[x] 连接失败: {e}")
        return False

def main():
    print_banner()

    # 检查服务状态
    print("[i] 检查 PostgreSQL 服务状态...")
    status = check_postgres_service()

    if status == 'running':
        print("[✓] PostgreSQL 服务已在运行")
    elif status == 'stopped':
        print("[!] PostgreSQL 服务已停止，正在启动...")
        if not start_postgres_service():
            print("\n[x] 无法启动服务，请手动检查:")
            print("    1. 确认 PostgreSQL 已正确安装")
            print("    2. 检查服务名称是否正确 (默认: PostgreSQL)")
            print("    3. 尝试手动启动: net start PostgreSQL")
            input("\n按回车键退出...")
            return
    elif status == 'not_installed':
        print("[x] 未检测到 PostgreSQL 服务")
        print("    请确认 PostgreSQL 17 已安装并创建服务")
        print("    安装路径: C:\\Program Files\\PostgreSQL\\17\\")
        input("\n按回车键退出...")
        return
    else:
        print("[x] 无法确定服务状态")
        return

    # 等待服务完全启动
    print("[i] 等待服务初始化...")
    time.sleep(2)

    # 测试连接
    if check_postgres_connection():
        print("\n[✓] PostgreSQL 已就绪！")
        print("    主机: localhost:5432")
        print("    数据库: siliconbase")
        print("    用户: postgres")
    else:
        print("\n[!] 服务运行但连接失败，请检查:")
        print("    1. 数据库 'siliconbase' 是否已创建")
        print("    2. 密码是否正确 (环境变量 POSTGRES_PASSWORD)")
        print("    3. 端口 5432 是否被占用")

    input("\n按回车键退出...")

if __name__ == "__main__":
    main()
