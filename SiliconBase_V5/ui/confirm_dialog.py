#!/usr/bin/env python3
"""
用户确认弹窗（简单 tkinter，支持无图形界面时回退到控制台）
"""
import logging

logger = logging.getLogger(__name__)

def confirm_dialog(message: str, title: str = "确认操作") -> bool:
    """
    显示确认对话框（优先使用图形界面，失败时使用控制台输入）
    返回 True=确认, False=取消
    """
    # 尝试使用 tkinter
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        # 确保窗口正常弹出，可能需要调用 update
        root.update()
        result = messagebox.askyesno(title, message)
        root.destroy()
        return result
    except Exception as e:
        # 图形界面失败，回退到控制台
        logger.warning(f"图形确认对话框失败，回退到控制台: {e}")
        return _console_confirm(message, title)


def _console_confirm(message: str, title: str) -> bool:
    """控制台确认"""
    print(f"\n{title}")
    print(message)
    while True:
        try:
            choice = input("请确认 (y/n): ").strip().lower()
            if choice in ('y', 'yes', '是'):
                return True
            if choice in ('n', 'no', '否'):
                return False
            print("输入错误，请输入 y 或 n")
        except (KeyboardInterrupt, EOFError):
            # 用户中断，视为取消
            print("\n操作取消")
            return False
