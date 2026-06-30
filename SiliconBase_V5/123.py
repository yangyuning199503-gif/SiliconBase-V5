#!/usr/bin/env python3
"""
硅基底座 V5.0 代码一键导出工具（最终修复版）
解决：路径错误、终端乱码、time模块未导入、权限删除失败问题
新增：排除models\vosk-model-cn-0.22目录
"""
import contextlib
import os
import shutil
import time  # 🔥 新增：导入time模块，解决NameError
from pathlib import Path

# ===================== 自动识别项目路径（无需手动修改）=====================
PROJECT_ROOT = str(Path(__file__).parent.resolve())
# =================================================================

# 桌面路径（自动适配所有Windows用户）
DESKTOP_PATH = os.path.join(os.path.expanduser("~"), "Desktop")
EXPORT_TXT = os.path.join(DESKTOP_PATH, "SiliconBase_V5_代码全量导出.txt")
EXPORT_DIR = os.path.join(DESKTOP_PATH, "SiliconBase_V5_导出目录")

# 要导出的文件类型（包含所有核心格式）
SUPPORT_EXT = (".py", )
# 要排除的无用目录/文件（避免冗余）
EXCLUDE_DIRS = ("__pycache__", "logs", "temp", ".git", "generated", "models", ".venv", "checkpoints", ".md", "data", "docs")
EXCLUDE_FILES = ("__init__.py",)

# 强制设置终端编码为UTF-8，彻底解决乱码
os.environ["PYTHONIOENCODING"] = "utf-8"
with contextlib.suppress(Exception):
    os.system("chcp 65001 >nul 2>&1")


def export_code_to_txt():
    """导出所有代码文件内容到桌面TXT（带文件路径标识）"""
    with open(EXPORT_TXT, "w", encoding="utf-8") as f:
        f.write("========== 硅基底座 V5.0 代码全量导出 ==========\n")
        f.write(f"导出时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}\n")
        f.write(f"项目根路径：{PROJECT_ROOT}\n\n")

        for root, dirs, files in os.walk(PROJECT_ROOT):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

            for file in files:
                if file.endswith(SUPPORT_EXT) and file not in EXCLUDE_FILES:
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, PROJECT_ROOT)

                    f.write(f"\n{'=' * 80}\n")
                    f.write(f"📄 文件路径：{rel_path}\n")
                    f.write(f"{'=' * 80}\n")

                    try:
                        with open(file_path, encoding="utf-8") as fp:
                            content = fp.read()
                            f.write(content)
                    except Exception as e:
                        f.write(f"【读取失败】：{str(e)}")
                    f.write(f"\n{'=' * 80}\n")


def copy_project_to_desktop():
    """复制整个项目目录到桌面备份（可选，防止导出遗漏）"""
    import stat
    # ========== 修复权限问题 ==========
    def remove_readonly(func, path, _):
        os.chmod(path, stat.S_IWRITE)
        func(path)

    if os.path.exists(EXPORT_DIR):
        # 用权限兼容方式删除，解决 WinError 5
        shutil.rmtree(EXPORT_DIR, onerror=remove_readonly)
    # =================================

    try:
        shutil.copytree(
            PROJECT_ROOT,
            EXPORT_DIR,
            ignore=shutil.ignore_patterns(*EXCLUDE_DIRS, *EXCLUDE_FILES)
        )
    except Exception as e:
        print(f"⚠️ 目录备份失败：{e}")


if __name__ == "__main__":
    if not os.path.exists(PROJECT_ROOT):
        print(f"❌ 错误：项目路径不存在！当前识别路径：{PROJECT_ROOT}")
        input("按任意键退出...")
        exit(1)

    print("📝 正在导出代码到桌面 TXT 文件...")
    export_code_to_txt()

    print("📂 正在备份项目目录到桌面...")
    copy_project_to_desktop()

    print("\n✅ 导出完成！")
    print(f"📄 代码汇总文件：{EXPORT_TXT}")
    print(f"📁 项目备份目录：{EXPORT_DIR}")
    input("按任意键退出...")
