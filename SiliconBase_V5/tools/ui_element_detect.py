#!/usr/bin/env python3
"""
原子工具：UI 元素检测
基于 Windows UI Automation API，获取屏幕上所有可交互元素的坐标、类型和名称。
不依赖 AI 模型，毫秒级返回，像素级精确。
"""

import os
import sys

from core.utils.error_codes import TOOL_EXECUTION_ERROR

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import threading

from core.logger import logger
from core.tool.base_tool import BaseTool
from core.utils.error_codes import INVALID_PARAMS, format_error

# 【线程保护】uiautomation COM 调用在多线程同时遍历 UI 树时可能冲突
_ui_detect_lock = threading.Lock()


class UIElementDetect(BaseTool):
    """UI 元素检测工具 - 获取窗口内所有控件的坐标和属性"""
    tool_id = "ui_element_detect"
    tool_owner = "system"
    name = "UI元素检测"
    description = (
        "检测当前屏幕或指定窗口中的所有UI元素（按钮、输入框、文本、菜单等），"
        "返回每个元素的名称、类型、坐标位置。支持按元素名称或类型筛选。"
        "与visual_understand配合使用：visual_understand描述'是什么'，此工具定位'在哪'。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "window_title": {
                "type": "string",
                "description": "窗口标题关键词（模糊匹配），为空则检测当前活动窗口"
            },
            "element_name": {
                "type": "string",
                "description": "按元素名称筛选（模糊匹配），为空则返回所有元素"
            },
            "element_type": {
                "type": "string",
                "description": "按控件类型筛选，如 Button、Edit、Text、MenuItem、ListItem 等，为空则返回所有类型"
            },
            "max_depth": {
                "type": "integer",
                "description": "遍历深度限制，默认5层，防止UI树过深导致卡顿",
                "default": 5
            },
            "include_invisible": {
                "type": "boolean",
                "description": "是否包含不可见元素，默认False只返回可见元素",
                "default": False
            }
        }
    }

    def _execute(self, **kwargs) -> dict:
        # 【线程保护】获取全局锁，防止多线程同时遍历 UI 树导致 COM 冲突或竞争
        acquired = _ui_detect_lock.acquire(timeout=30)
        if not acquired:
            return format_error(TOOL_EXECUTION_ERROR, detail="UI元素检测正忙，请稍后再试")
        try:
            return self._do_detect(**kwargs)
        finally:
            _ui_detect_lock.release()

    async def _execute_async(self, **kwargs) -> dict:
        """异步入口 - 桥接到线程池执行，避免阻塞事件循环"""
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._execute(**kwargs))

    def _do_detect(self, **kwargs) -> dict:
        try:
            import uiautomation as auto
        except ImportError:
            return format_error(
                INVALID_PARAMS,
                detail="uiautomation 库未安装，请运行: pip install uiautomation"
            )

        window_title = kwargs.get("window_title", "")
        element_name = kwargs.get("element_name", "")
        element_type = kwargs.get("element_type", "")
        max_depth = kwargs.get("max_depth", 5)
        include_invisible = kwargs.get("include_invisible", False)

        try:
            # 定位目标窗口
            if window_title:
                root = auto.WindowControl(searchDepth=1, Name=window_title)
                if not root.Exists(1, 0.5):
                    # 模糊匹配
                    root = None
                    for window in auto.GetRootControl().GetChildren():
                        if window.ControlType == auto.ControlType.WindowControl:
                            title = window.Name or ""
                            if window_title.lower() in title.lower():
                                root = window
                                break
                if root is None:
                    return {
                        "success": False,
                        "error_code": "WINDOW_NOT_FOUND",
                        "user_message": f"未找到标题包含 '{window_title}' 的窗口",
                        "data": None
                    }
            else:
                # 获取当前活动窗口
                root = auto.GetForegroundControl()
                if root is None:
                    root = auto.GetRootControl()

            target_title = root.Name if hasattr(root, 'Name') else "未知窗口"
            logger.info(f"[UIElementDetect] 检测窗口: '{target_title}', 深度: {max_depth}")

            elements = []
            seen = set()

            def walk(control, depth=0):
                if depth > max_depth:
                    return
                if control is None:
                    return

                try:
                    rect = control.BoundingRectangle
                    if rect is None or rect.width() <= 0 or rect.height() <= 0:
                        return

                    # 跳过不可见元素（除非用户要求）
                    if not include_invisible:
                        try:
                            if not control.IsVisible:
                                return
                        except Exception:
                            pass

                    ctrl_type = control.ControlTypeName or "Unknown"
                    name = (control.Name or "").strip()
                    auto_id = (control.AutomationId or "").strip()
                    class_name = (control.ClassName or "").strip()

                    # 筛选
                    if element_type and element_type.lower() not in ctrl_type.lower():
                        # 继续遍历子元素，因为父元素类型可能不匹配但子元素匹配
                        pass
                    elif element_name and element_name.lower() not in name.lower():
                        pass
                    else:
                        # 去重：用类型+名称+坐标作为唯一键
                        key = f"{ctrl_type}|{name}|{rect.left},{rect.top},{rect.right},{rect.bottom}"
                        if key not in seen:
                            seen.add(key)
                            elements.append({
                                "name": name,
                                "type": ctrl_type,
                                "automation_id": auto_id,
                                "class_name": class_name,
                                "rect": {
                                    "left": rect.left,
                                    "top": rect.top,
                                    "right": rect.right,
                                    "bottom": rect.bottom
                                },
                                "center": {
                                    "x": (rect.left + rect.right) // 2,
                                    "y": (rect.top + rect.bottom) // 2
                                },
                                "size": {
                                    "width": rect.width(),
                                    "height": rect.height()
                                },
                                "depth": depth,
                                "hwnd": control.NativeWindowHandle
                            })
                except Exception as e:
                    logger.debug(f"[UIElementDetect] 遍历控件异常: {e}")

                # 递归遍历子元素
                try:
                    children = control.GetChildren()
                    for child in children:
                        walk(child, depth + 1)
                except Exception:
                    pass

            walk(root)

            # 按深度排序（越浅层越重要）
            elements.sort(key=lambda x: (x["depth"], x["center"]["y"], x["center"]["x"]))

            # 生成人类可读的摘要
            summary_lines = [f"窗口: {target_title} | 共发现 {len(elements)} 个UI元素"]
            for el in elements[:30]:  # 只显示前30个，防止消息过长
                label = el["name"] or el["automation_id"] or el["type"]
                summary_lines.append(
                    f"  [{el['type']}] {label} -> 中心坐标({el['center']['x']}, {el['center']['y']})"
                )
            if len(elements) > 30:
                summary_lines.append(f"  ... 还有 {len(elements) - 30} 个元素未显示")

            summary = "\n".join(summary_lines)
            logger.info(f"[UIElementDetect] 发现 {len(elements)} 个元素")

            return {
                "success": True,
                "user_message": summary,
                "data": {
                    "window_title": target_title,
                    "element_count": len(elements),
                    "elements": elements,
                    "summary": summary
                }
            }

        except Exception as e:
            logger.error(f"[UIElementDetect] 检测失败: {e}", exc_info=True)
            return format_error(
                INVALID_PARAMS,
                detail=f"UI元素检测失败: {str(e) or '未知错误'}"
            )


# 兼容旧版本
UIElementDetectTool = UIElementDetect
