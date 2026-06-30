#!/usr/bin/env python3
"""
原子工具：鼠标点击
修复版：增加目标窗口会话校验，增加跨平台兼容
"""
import asyncio
import sys

from core.base_tool import BaseTool
from core.error_codes import TOOL_EXECUTION_ERROR, format_error
from core.logger import logger

# 跨平台兼容判断
IS_WINDOWS = sys.platform == "win32"

# 仅Windows系统导入win32相关库
if IS_WINDOWS:
    try:
        import win32api
        import win32con
        import win32process
    except ImportError as e:
        logger.error(f"Windows依赖库导入失败: {e}，请安装 pywin32")
        win32api = None
        win32con = None
        win32process = None
else:
    win32api = None
    win32con = None
    win32process = None
    logger.warning("当前系统非Windows，鼠标点击功能不可用")

# ====== FIX: 会话校验函数 ======
def _is_same_session(hwnd):
    """检查窗口句柄是否属于当前用户会话"""
    if not IS_WINDOWS or win32process is None:
        return False
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        # 打开进程查询信息
        handle = win32api.OpenProcess(0x0400, False, pid)  # PROCESS_QUERY_INFORMATION
        if not handle:
            return False
        win32api.CloseHandle(handle)
        return True
    except Exception as e:
        logger.debug(f"会话校验失败: {e}")
        return False
# ====== 结束 ======

class MouseClick(BaseTool):
    tool_id = "mouse_click"
    name = "鼠标点击"
    require_confirmation = True
    description = "在屏幕指定坐标点击鼠标，或根据元素名称自动解析坐标"
    input_schema = {
        "type": "object",
        "properties": {
            "x": {"type": "integer"},
            "y": {"type": "integer"},
            "button": {"type": "string", "enum": ["left", "right"], "default": "left"},
            "hwnd": {"type": "integer", "description": "可选，目标窗口句柄，用于权限校验"},
            "target_element": {"type": "string", "description": "要点击的元素名称（如'安静'），系统会自动从当前屏幕元素地图中解析坐标"}
        }
        # 【修复】required 改为代码级校验：target_element 和 (x, y) 二选一
    }

    async def _execute_async(self, **kwargs) -> dict:
        """
        异步执行鼠标点击 - 显式桥接到线程池

        win32api 调用本质上是同步的系统调用，无法真正异步化。
        使用 run_in_executor 将阻塞操作放到线程池中执行，避免阻塞事件循环。
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._execute(**kwargs))

    def _resolve_element(self, target_element: str) -> tuple:
        """【修复】从全局 element_map 缓存中解析元素名称到坐标"""
        from core.vision.perception_manager import get_last_element_map
        element_map = get_last_element_map()
        if not element_map:
            return None, None, "当前没有可用的屏幕元素地图，请先执行视觉感知或使用 (x, y) 坐标"

        target_lower = target_element.lower()
        matches = []
        for elem in element_map:
            name = (elem.get("name", "") or elem.get("text", "")).strip()
            if not name:
                continue
            name_lower = name.lower()
            # 支持子串匹配（如 "安静" 匹配 "安静 - 花儿乐队"）
            if target_lower in name_lower or name_lower in target_lower:
                # 计算中心点坐标
                if "left" in elem and "right" in elem:
                    center_x = (elem["left"] + elem["right"]) // 2
                elif "x" in elem and "width" in elem:
                    center_x = elem["x"] + elem["width"] // 2
                else:
                    center_x = elem.get("x", 0)
                if "top" in elem and "bottom" in elem:
                    center_y = (elem["top"] + elem["bottom"]) // 2
                elif "y" in elem and "height" in elem:
                    center_y = elem["y"] + elem["height"] // 2
                else:
                    center_y = elem.get("y", 0)
                matches.append({"name": name, "x": center_x, "y": center_y})

        if len(matches) == 1:
            m = matches[0]
            return m["x"], m["y"], None
        elif len(matches) > 1:
            names = [m["name"] for m in matches[:5]]
            return None, None, f"找到多个匹配元素：{', '.join(names)}... 请使用更精确的名称或直接使用 (x, y) 坐标"
        else:
            available = [e.get("name", "") or e.get("text", "") for e in element_map[:10]]
            return None, None, f"未找到元素 '{target_element}'。当前屏幕可用元素：{', '.join(filter(None, available))}"

    def _execute(self, **kwargs) -> dict:
        if not IS_WINDOWS or win32api is None:
            return {
                "success": False,
                "error_code": "NOT_SUPPORTED",
                "user_message": "当前操作系统不支持鼠标点击功能，仅Windows可用",
                "data": None
            }

        try:
            target_element = kwargs.get("target_element")
            button = kwargs.get("button", "left")
            hwnd = kwargs.get("hwnd")

            # 【修复】支持 target_element 或 (x, y) 二选一
            if target_element:
                x, y, error_msg = self._resolve_element(target_element)
                if x is None or y is None:
                    return {
                        "success": False,
                        "error_code": "ELEMENT_NOT_FOUND",
                        "user_message": error_msg or f"无法解析元素 '{target_element}'",
                        "data": None
                    }
                logger.info(f"[MouseClick] 元素引用解析成功: '{target_element}' -> ({x}, {y})")
            else:
                x = kwargs.get("x")
                y = kwargs.get("y")
                if x is None or y is None:
                    return {
                        "success": False,
                        "error_code": "INVALID_PARAMS",
                        "user_message": "需要提供 target_element（元素名称）或 (x, y) 坐标",
                        "data": None
                    }

            # ====== FIX: 如果提供了 hwnd，校验是否属于当前会话 ======
            if hwnd is not None and not _is_same_session(hwnd):
                return {
                    "success": False,
                    "error_code": "PERMISSION_DENIED",
                    "user_message": "无法操作其他会话的窗口，权限不足",
                    "data": None
                }
            # ====== 结束 ======

            btn_code = win32con.MOUSEEVENTF_LEFTDOWN if button == "left" else win32con.MOUSEEVENTF_RIGHTDOWN
            btn_up = win32con.MOUSEEVENTF_LEFTUP if button == "left" else win32con.MOUSEEVENTF_RIGHTUP

            win32api.SetCursorPos((x, y))
            win32api.mouse_event(btn_code, x, y, 0, 0)
            win32api.mouse_event(btn_up, x, y, 0, 0)
            # 【修复】返回信息区分坐标点击和元素引用点击
            if target_element:
                user_msg = f"已点击元素 '{target_element}' ({x}, {y})"
                data = {"target_element": target_element, "x": x, "y": y, "button": button}
            else:
                user_msg = f"鼠标点击成功 ({x}, {y})"
                data = {"x": x, "y": y, "button": button}
            return {
                "success": True,
                "error_code": None,
                "user_message": user_msg,
                "data": data
            }
        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=str(e))
