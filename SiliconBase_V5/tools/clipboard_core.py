#!/usr/bin/env python3
"""
剪贴板核心功能模块
提取公共的剪贴板操作逻辑，供多个工具类复用
"""
import win32clipboard

from core.error_codes import CLIPBOARD_ERROR, format_error


def get_clipboard() -> dict:
    """
    获取剪贴板文本内容

    Returns:
        dict: 包含剪贴板文本的字典，或错误信息
    """
    try:
        win32clipboard.OpenClipboard()
        try:
            data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            return {
                "success": True,
                "error_code": None,
                "user_message": f"获取剪贴板内容成功 ({len(data)} 字符)",
                "data": {"text": data}
            }
        finally:
            win32clipboard.CloseClipboard()
    except Exception as e:
        return format_error(CLIPBOARD_ERROR, detail=str(e))


def set_clipboard(text: str) -> dict:
    """
    设置剪贴板文本内容

    Args:
        text: 要设置的文本内容

    Returns:
        dict: 操作结果字典
    """
    try:
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
            return {
                "success": True,
                "error_code": None,
                "user_message": f"剪贴板已设置 ({len(text)} 字符)",
                "data": {"text": text}
            }
        finally:
            win32clipboard.CloseClipboard()
    except Exception as e:
        return format_error(CLIPBOARD_ERROR, detail=str(e))


def clear_clipboard() -> dict:
    """
    清空剪贴板内容

    Returns:
        dict: 操作结果字典
    """
    try:
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            return {
                "success": True,
                "error_code": None,
                "user_message": "剪贴板已清空",
                "data": None
            }
        finally:
            win32clipboard.CloseClipboard()
    except Exception as e:
        return format_error(CLIPBOARD_ERROR, detail=str(e))
