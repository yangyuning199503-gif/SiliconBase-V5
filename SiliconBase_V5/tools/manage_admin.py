#!/usr/bin/env python3
"""
SiliconBase V5 - 管理员密码管理工具
用于查看、重置、修改管理员密码
"""
import hashlib
import json
import os
import secrets
import string
import sys
from datetime import datetime
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 数据目录
DATA_DIR = Path(__file__).parent.parent / "data"
USERS_FILE = DATA_DIR / "users.json"
PASSWORD_FILE = DATA_DIR / ".initial_password.txt"


def generate_password(length=16):
    """生成随机密码"""
    alphabet = string.ascii_letters + string.digits
    while True:
        password = ''.join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in password)
                and any(c.isupper() for c in password)
                and any(c.isdigit() for c in password)):
            return password


def hash_password(password: str) -> str:
    """密码哈希"""
    return hashlib.sha256(password.encode()).hexdigest()


def show_current_password():
    """显示当前密码"""
    print("\n" + "=" * 50)
    print("当前管理员密码")
    print("=" * 50)

    if PASSWORD_FILE.exists():
        with open(PASSWORD_FILE, encoding='utf-8') as f:
            content = f.read()
            for line in content.split('\n'):
                if line.startswith('INITIAL_PASSWORD='):
                    password = line.split('=', 1)[1]
                    print("\n用户名: admin")
                    print(f"密码: {password}")
                    print(f"\n文件位置: {PASSWORD_FILE}")
                    return

    # 尝试从用户数据文件读取
    if USERS_FILE.exists():
        with open(USERS_FILE, encoding='utf-8') as f:
            users = json.load(f)
            if 'admin' in users:
                print("\n用户名: admin")
                print(f"密码哈希: {users['admin'].get('password_hash', 'N/A')[:20]}...")
                print("\n[提示] 初始密码文件已删除，请使用内存中的密码或重置")
                return

    print("\n[错误] 未找到密码信息，系统可能未初始化")


def reset_password():
    """重置密码 - 删除密码文件，下次启动生成新密码"""
    print("\n" + "=" * 50)
    print("重置管理员密码")
    print("=" * 50)

    confirm = input("\n确定要重置密码吗? 下次启动时会生成新密码 (Y/N): ")
    if confirm.upper() != 'Y':
        print("已取消")
        return

    # 删除密码文件
    if PASSWORD_FILE.exists():
        PASSWORD_FILE.unlink()
        print("\n[OK] 密码文件已删除")
    else:
        print("\n[提示] 密码文件不存在")

    print("\n[提示] 请重新启动系统，会自动生成新密码")


def change_password():
    """修改管理员密码"""
    print("\n" + "=" * 50)
    print("修改管理员密码")
    print("=" * 50)

    # 检查用户数据文件
    if not USERS_FILE.exists():
        print(f"\n[错误] 用户数据文件不存在: {USERS_FILE}")
        print("请先启动一次系统以初始化")
        return

    # 读取当前用户数据
    with open(USERS_FILE, encoding='utf-8') as f:
        users = json.load(f)

    if 'admin' not in users:
        print("\n[错误] admin 用户不存在")
        return

    # 输入新密码
    new_password = input("\n请输入新密码 (至少6位): ").strip()
    if len(new_password) < 6:
        print("[错误] 密码太短，至少需要6位")
        return

    confirm = input("请再次输入新密码: ").strip()
    if new_password != confirm:
        print("[错误] 两次输入的密码不一致")
        return

    # 更新密码
    users['admin']['password_hash'] = hash_password(new_password)
    users['admin']['require_password_change'] = False

    # 保存
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2, ensure_ascii=False)

    # 更新密码文件
    with open(PASSWORD_FILE, 'w', encoding='utf-8') as f:
        f.write("# SiliconBase V5 初始管理员密码\n")
        f.write(f"# 生成时间: {datetime.now().isoformat()}\n")
        f.write("# 此文件将在首次登录后自动删除\n")
        f.write("# [手动修改] 通过管理员工具修改\n\n")
        f.write("USERNAME=admin\n")
        f.write(f"INITIAL_PASSWORD={new_password}\n")
        f.write("REQUIRE_PASSWORD_CHANGE=false\n")

    print("\n[OK] 密码修改成功!")
    print("用户名: admin")
    print(f"新密码: {new_password}")


def set_fixed_password():
    """设置固定密码（开发测试用）

    安全修复说明：
    - 不再使用硬编码密码 admin123
    - 优先从环境变量 SILICONBASE_ADMIN_PASSWORD 读取
    - 环境变量未设置时自动生成随机强密码
    """
    print("\n" + "=" * 50)
    print("设置固定密码 (安全版本)")
    print("=" * 50)

    # 从环境变量读取密码，未设置则生成随机密码
    env_password = os.environ.get("SILICONBASE_ADMIN_PASSWORD")

    if env_password:
        print("\n[信息] 已从环境变量 SILICONBASE_ADMIN_PASSWORD 读取密码")
        fixed_password = env_password
        # 验证密码强度
        if len(fixed_password) < 8:
            print("[警告] 环境变量中的密码长度不足8位，建议设置更强的密码")
            confirm = input("是否继续使用此弱密码? (Y/N): ")
            if confirm.upper() != 'Y':
                print("已取消")
                return
    else:
        # 自动生成随机强密码
        fixed_password = generate_password(length=16)
        print("\n[信息] 环境变量 SILICONBASE_ADMIN_PASSWORD 未设置")
        print("[信息] 已自动生成随机强密码")

    print(f"\n将要设置的密码: {fixed_password}")
    confirm = input("\n确定要设置此密码吗? (Y/N): ")
    if confirm.upper() != 'Y':
        print("已取消")
        return

    try:
        # 确保数据目录存在
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        # 创建/更新用户数据
        users = {}
        if USERS_FILE.exists():
            try:
                with open(USERS_FILE, encoding='utf-8') as f:
                    users = json.load(f)
            except json.JSONDecodeError as e:
                print(f"[警告] 用户数据文件解析失败: {e}，将创建新文件")
                users = {}
            except OSError as e:
                print(f"[警告] 无法读取用户数据文件: {e}，将创建新文件")
                users = {}

        # 设置密码（来自环境变量或随机生成）
        users['admin'] = {
            "user_id": "user_admin",
            "username": "admin",
            "password_hash": hash_password(fixed_password),
            "email": "admin@siliconbase.local",
            "created_at": 0,
            "is_active": True,
            "roles": ["admin", "user"],
            "require_password_change": False
        }

        # 保存用户数据
        try:
            with open(USERS_FILE, 'w', encoding='utf-8') as f:
                json.dump(users, f, indent=2, ensure_ascii=False)
        except OSError as e:
            print(f"[错误] 无法写入用户数据文件: {e}")
            return

        # 更新密码文件
        try:
            from datetime import datetime
            with open(PASSWORD_FILE, 'w', encoding='utf-8') as f:
                f.write("# SiliconBase V5 初始管理员密码\n")
                f.write(f"# 生成时间: {datetime.now().isoformat()}\n")
                f.write(f"# 来源: {'环境变量' if env_password else '自动生成'}\n")
                f.write("# [安全提示] 生产环境请使用强密码并及时修改\n\n")
                f.write("USERNAME=admin\n")
                f.write(f"INITIAL_PASSWORD={fixed_password}\n")
                f.write("REQUIRE_PASSWORD_CHANGE=false\n")
        except OSError as e:
            print(f"[错误] 无法写入密码文件: {e}")
            return

        print("\n[OK] 密码设置成功!")
        print("用户名: admin")
        print(f"密码: {fixed_password}")

        if env_password:
            print("\n[信息] 密码来源: 环境变量 SILICONBASE_ADMIN_PASSWORD")
        else:
            print("\n[信息] 密码来源: 自动生成（16位随机强密码）")
            print("[提示] 如需使用自定义密码，请设置环境变量:")
            print("       set SILICONBASE_ADMIN_PASSWORD=YourStrongPassword")

        print("\n[安全警告] 生产环境请:")
        print("  1. 使用强密码（至少12位，包含大小写字母、数字和特殊字符）")
        print("  2. 定期更换密码")
        print(f"  3. 妥善保管密码文件: {PASSWORD_FILE}")

    except Exception as e:
        print(f"\n[错误] 设置密码时发生未知错误: {e}")
        return


def main():
    """主函数"""
    print("\n" + "=" * 50)
    print("SiliconBase V5 - 管理员密码管理工具")
    print("=" * 50)
    print("\n[1] 查看当前管理员密码")
    print("[2] 重置密码 (下次启动生成新密码)")
    print("[3] 修改管理员密码 (自定义)")
    print("[4] 设置固定密码 (开发测试，支持环境变量)")
    print("[Q] 退出")

    choice = input("\n请选择操作: ").strip()

    if choice == '1':
        show_current_password()
    elif choice == '2':
        reset_password()
    elif choice == '3':
        change_password()
    elif choice == '4':
        set_fixed_password()
    elif choice.upper() == 'Q':
        print("\n退出")
        return
    else:
        print("\n[错误] 无效选择")

    print()


if __name__ == "__main__":
    main()
