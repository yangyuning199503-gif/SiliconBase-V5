#!/usr/bin/env python3
"""
应用截图工具修复

此脚本将原始 pixel_capture.py 替换为增强版本
"""
import shutil
import sys
from pathlib import Path


def apply_fix():
    """应用截图工具修复"""
    tools_dir = Path(__file__).parent

    original_file = tools_dir / "pixel_capture.py"
    enhanced_file = tools_dir / "pixel_capture_enhanced.py"
    backup_file = tools_dir / "pixel_capture.py.bak"

    print("=" * 50)
    print("🔧 应用截图工具修复")
    print("=" * 50)

    # 检查文件是否存在
    if not original_file.exists():
        print(f"❌ 错误: 找不到原始文件 {original_file}")
        return False

    if not enhanced_file.exists():
        print(f"❌ 错误: 找不到增强版本 {enhanced_file}")
        return False

    try:
        # 1. 创建备份
        if not backup_file.exists():
            print(f"📦 创建备份: {backup_file}")
            shutil.copy2(original_file, backup_file)
        else:
            print(f"📦 备份已存在: {backup_file}")

        # 2. 替换文件
        print("📝 替换为增强版本...")
        shutil.copy2(enhanced_file, original_file)

        print("✅ 截图工具修复已应用")
        print("\n修复内容:")
        print("  • 添加显示器自动检测")
        print("  • 添加详细错误日志")
        print("  • 添加多显示器支持")
        print("  • 添加权限检查")
        print("  • 添加降级策略（模拟截图用于测试）")

        print("\n如需回滚，运行:")
        print(f"  python {Path(__file__).parent / 'rollback_pixel_capture.py'}")

        return True

    except Exception as e:
        print(f"❌ 应用修复失败: {e}")
        return False


def rollback_fix():
    """回滚截图工具修复"""
    tools_dir = Path(__file__).parent

    original_file = tools_dir / "pixel_capture.py"
    backup_file = tools_dir / "pixel_capture.py.bak"

    print("=" * 50)
    print("🔄 回滚截图工具修复")
    print("=" * 50)

    if not backup_file.exists():
        print(f"❌ 错误: 找不到备份文件 {backup_file}")
        return False

    try:
        print("📦 从备份恢复...")
        shutil.copy2(backup_file, original_file)

        # 可选：删除备份
        # backup_file.unlink()

        print("✅ 截图工具已回滚到原始版本")
        return True

    except Exception as e:
        print(f"❌ 回滚失败: {e}")
        return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="截图工具修复管理")
    parser.add_argument("--rollback", action="store_true", help="回滚修复")

    args = parser.parse_args()

    success = rollback_fix() if args.rollback else apply_fix()

    sys.exit(0 if success else 1)
