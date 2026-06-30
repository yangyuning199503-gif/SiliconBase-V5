#!/usr/bin/env python3
"""
UI-TARS 工具 - 硅基生命底座集成
端到端 GUI 自动化工具，输入指令，输出精确动作坐标

模型: UI-TARS (通过AI Provider Factory动态获取，支持配置指定)
作者: ByteDance (开源 Apache 2.0)
集成: SiliconBase V5
"""

import asyncio
import base64
import io
from pathlib import Path

from core.vision.safe_screenshot import safe_screenshot_to_pil

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

from core.base_tool import BaseTool
from core.config import config
from core.error_codes import TOOL_EXECUTION_ERROR, TOOL_NOT_FOUND, format_error


class UITarsTool(BaseTool):
    """
    UI-TARS 视觉控制器 - 精确 GUI 操作工具

    功能：输入自然语言指令，AI 分析截图并输出具体操作（点击、输入等）

    示例：
    - instruction: "点击右上角的设置按钮"
    - 返回: {action: "click", coordinate: [920, 45]}

    与 visual_understand 的区别：
    - visual_understand: 描述图像内容（认知）
    - ui_tars: 输出具体操作坐标（执行）

    配置项：
    - ai.vision.model: 通用视觉模型配置
    - ai.ui_tars.model: UI-TARS专用模型配置（优先级更高）
    """

    tool_id = "ui_tars"
    name = "UI-TARS 视觉控制"
    description = "精确控制 GUI：输入自然语言指令，AI 输出点击/输入等具体操作坐标（端到端视觉模型）"
    category = "🎵 媒体处理"  # 归类到媒体处理，与 screenshot/visual_understand 同类

    input_schema = {
        "type": "object",
        "properties": {
            "instruction": {
                "type": "string",
                "description": "操作指令，如'点击登录按钮'、'在搜索框输入hello'"
            },
            "execute": {
                "type": "boolean",
                "default": False,
                "description": "是否立即执行识别出的动作（默认只返回动作，不执行）"
            },
            "screenshot_path": {
                "type": "string",
                "description": "可选：指定截图路径，不提供则自动截图"
            }
        },
        "required": ["instruction"]
    }

    # 超时配置
    TIMEOUT = 30

    def __init__(self):
        super().__init__()
        self._screen_size = None
        self._provider = None

    def _get_model(self) -> str:
        """
        获取UI-TARS模型配置

        配置优先级：
        1. ai.ui_tars.model - UI-TARS专用配置
        2. ai.vision.model - 通用视觉模型配置

        Returns:
            模型名称

        Raises:
            ValueError: 当没有配置模型时抛出
        """
        # 优先读取 UI-TARS 专用配置，其次使用通用 vision 模型配置
        model = config.get("ai.ui_tars.model") or config.get("ai.vision.model")

        if not model:
            raise ValueError(
                "未配置UI-TARS模型。请在配置中设置 ai.ui_tars.model 或 ai.vision.model。\n"
                "示例（global.yaml）:\n"
                "  ai:\n"
                "    vision:\n"
                "      model: qwen2.5-vl:7b\n"
                "    # 或UI-TARS专用配置:\n"
                "    ui_tars:\n"
                "      model: ui-tars:7b"
            )

        return model

    def _get_provider(self):
        """获取当前配置的AI Provider（延迟加载）"""
        if self._provider is None:
            from core.providers.ai_provider_factory import AIProviderFactory
            self._provider = AIProviderFactory.get_current_provider()
        return self._provider

    def _get_provider_type(self) -> str:
        """获取当前Provider类型"""
        provider = self._get_provider()
        provider_config = provider.get_config()
        return provider_config.get("provider", "unknown")

    def _execute(self, **kwargs) -> dict:
        """
        执行 UI-TARS 视觉控制

        Args:
            instruction: 操作指令
            execute: 是否立即执行（默认 False）
            screenshot_path: 可选截图路径

        Returns:
            {
                "success": True,
                "data": {
                    "thought": "AI 的思考过程",
                    "action_str": "原始动作字符串",
                    "action": {
                        "type": "click/type/hotkey/...",
                        "coordinate": [x, y],  # 相对坐标 0-1000
                        "absolute_coord": [x, y],  # 绝对屏幕坐标
                        ...
                    }
                }
            }
        """
        instruction = kwargs.get("instruction")
        execute = kwargs.get("execute", False)
        screenshot_path = kwargs.get("screenshot_path")

        # 参数检查
        if not instruction:
            return format_error(TOOL_NOT_FOUND, detail="缺少必需参数: instruction")

        try:
            # 1. 获取截图
            if screenshot_path and Path(screenshot_path).exists():
                screenshot_b64 = self._load_screenshot(screenshot_path)
            else:
                screenshot_b64 = self._capture_screenshot()

            if not screenshot_b64:
                return format_error(TOOL_EXECUTION_ERROR, detail="截图失败，请检查 mss 是否安装")

            # 2. 调用 UI-TARS 模型
            result = self._call_model(screenshot_b64, instruction)

            if not result:
                return format_error(TOOL_EXECUTION_ERROR, detail="模型调用失败，请检查AI Provider配置")

            # 3. 可选：执行动作
            if execute and result.get("action") and result["action"].get("type") != "unknown":
                execution_result = self._execute_action(result["action"])
                result["execution"] = execution_result

            return {
                "success": True,
                "error_code": None,
                "user_message": f"🎯 {result['thought']}\n🖱️ 动作: {result['action_str']}",
                "data": result
            }

        except ValueError as e:
            # 配置错误
            return format_error(TOOL_EXECUTION_ERROR, detail=f"配置错误: {str(e)}")
        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"UI-TARS 执行错误: {str(e)}")

    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)

    def _capture_screenshot(self) -> str:
        """截取屏幕并转为 base64 - 【蓝屏修复】使用线程安全截图"""
        import gc
        # 【蓝屏修复】使用safe_screenshot替代mss
        img = safe_screenshot_to_pil(monitor=1)
        if img is None:
            raise RuntimeError("截图失败")

        try:
            # 压缩以加快传输（可选）
            img.thumbnail((1920, 1080))  # 限制最大尺寸

            # 转为 base64
            buffer = io.BytesIO()
            try:
                img.save(buffer, format="PNG")
                return base64.b64encode(buffer.getvalue()).decode()
            finally:
                buffer.close()
        finally:
            img.close()
            del img
            gc.collect()

    def _load_screenshot(self, path: str) -> str:
        """加载已有截图"""
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()

    def _get_screen_size(self):
        """获取屏幕尺寸"""
        if self._screen_size is None:
            if PYAUTOGUI_AVAILABLE:
                self._screen_size = pyautogui.size()
            else:
                # 默认值
                self._screen_size = (1920, 1080)
        return self._screen_size

    def _build_messages(self, screenshot_b64: str, instruction: str, provider_type: str) -> list:
        """
        构建消息列表，根据Provider类型使用不同的图片格式

        Args:
            screenshot_b64: Base64编码的截图
            instruction: 用户指令
            provider_type: Provider类型 (ollama/openai/anthropic等)

        Returns:
            格式化的消息列表
        """
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(instruction)

        # Ollama 格式：使用 images 字段
        if provider_type == "ollama":
            return [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_prompt,
                    "images": [screenshot_b64]
                }
            ]

        # OpenAI / OpenAI兼容 / Anthropic 格式：使用 content 数组
        else:
            return [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": user_prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{screenshot_b64}"
                            }
                        }
                    ]
                }
            ]

    def _call_model(self, screenshot_b64: str, instruction: str) -> dict:
        """
        调用 UI-TARS 模型
        使用AI Provider Factory获取当前provider，支持多种后端
        模型从配置中读取，支持 ai.ui_tars.model 或 ai.vision.model
        """
        try:
            # 获取模型配置（必须配置，否则抛出异常）
            model = self._get_model()

            provider = self._get_provider()
            provider_type = self._get_provider_type()

            # 检查provider是否可用
            if not provider.is_available():
                raise Exception(f"AI Provider不可用: {provider_type}")

            # 构建消息 - 根据Provider类型使用不同的图片格式
            messages = self._build_messages(screenshot_b64, instruction, provider_type)

            # 调用Provider，传递模型参数
            response = provider.chat(
                messages=messages,
                temperature=0.2,      # UI-TARS 推荐低温度
                max_tokens=256,       # 限制输出长度
                model=model           # 从配置读取的模型
            )

            if response is None:
                return None

            return self._parse_response(response)

        except ValueError:
            # 配置错误，重新抛出
            raise
        except Exception as e:
            print(f"[UI-TARS] 模型调用错误: {e}")
            return None

    def _build_system_prompt(self) -> str:
        """构建 UI-TARS 系统提示词"""
        return """You are a GUI agent. You are given a task and your action history, with screenshots. You need to perform the next action to complete the task.

## Output Format
```
Thought: ...
Action: ...
```

## Action Space
click(start_box='<|box_start|>(x1,y1)<|box_end|>')
left_double(start_box='<|box_start|>(x1,y1)<|box_end|>')
right_single(start_box='<|box_start|>(x1,y1)<|box_end|>')
drag(start_box='<|box_start|>(x1,y1)<|box_end|>', end_box='<|box_start|>(x2,y2)<|box_end|>')
hotkey(key='')
type(content='')
scroll(start_box='<|box_start|>(x1,y1)<|box_end|>', direction='down or up or right or left')
wait()
finished()
call_user()

## Note
- Use Chinese in `Thought` part.
- Summarize your next action in one sentence in `Thought` part.
- Coordinates are 0-1000 relative to screen size.

## Action History
No previous actions."""

    def _build_user_prompt(self, instruction: str) -> str:
        """构建 UI-TARS 用户提示词"""
        return f"""## User Instruction
{instruction}

## Response"""

    def _parse_response(self, text: str) -> dict:
        """解析 UI-TARS 响应"""
        import re

        # 提取 Thought
        thought_match = re.search(r'Thought:\s*(.+?)(?:\n|Action:)', text, re.DOTALL)
        thought = thought_match.group(1).strip() if thought_match else ""

        # 提取 Action
        action_match = re.search(r'Action:\s*(.+?)(?:\n|$)', text, re.DOTALL)
        action_str = action_match.group(1).strip() if action_match else text.strip()

        # 解析具体动作
        action = self._parse_action(action_str)

        return {
            "thought": thought,
            "action_str": action_str,
            "action": action,
            "raw": text
        }

    def _parse_action(self, action_str: str) -> dict:
        """解析动作字符串为结构化数据"""
        import re

        screen_w, screen_h = self._get_screen_size()

        # click(start_box='<|box_start|>(x,y)<|box_end|>')
        click_match = re.search(
            r'click\(start_box=\'<\|box_start\|>\((\d+),(\d+)\)<\|box_end\|>\'\)',
            action_str
        )
        if click_match:
            x_rel, y_rel = int(click_match.group(1)), int(click_match.group(2))
            x_abs = round(x_rel / 1000 * screen_w)
            y_abs = round(y_rel / 1000 * screen_h)
            return {
                "type": "click",
                "relative_coord": [x_rel, y_rel],
                "absolute_coord": [x_abs, y_abs]
            }

        # left_double(start_box='...')
        left_double_match = re.search(
            r'left_double\(start_box=\'<\|box_start\|>\((\d+),(\d+)\)<\|box_end\|>\'\)',
            action_str
        )
        if left_double_match:
            x_rel, y_rel = int(left_double_match.group(1)), int(left_double_match.group(2))
            x_abs = round(x_rel / 1000 * screen_w)
            y_abs = round(y_rel / 1000 * screen_h)
            return {
                "type": "left_double",
                "relative_coord": [x_rel, y_rel],
                "absolute_coord": [x_abs, y_abs]
            }

        # right_single(start_box='...')
        right_single_match = re.search(
            r'right_single\(start_box=\'<\|box_start\|>\((\d+),(\d+)\)<\|box_end\|>\'\)',
            action_str
        )
        if right_single_match:
            x_rel, y_rel = int(right_single_match.group(1)), int(right_single_match.group(2))
            x_abs = round(x_rel / 1000 * screen_w)
            y_abs = round(y_rel / 1000 * screen_h)
            return {
                "type": "right_single",
                "relative_coord": [x_rel, y_rel],
                "absolute_coord": [x_abs, y_abs]
            }

        # drag(start_box='...', end_box='...')
        drag_match = re.search(
            r'drag\(start_box=\'<\|box_start\|>\((\d+),(\d+)\)<\|box_end\|>\',\s*end_box=\'<\|box_start\|>\((\d+),(\d+)\)<\|box_end\|>\'\)',
            action_str
        )
        if drag_match:
            x1_rel, y1_rel = int(drag_match.group(1)), int(drag_match.group(2))
            x2_rel, y2_rel = int(drag_match.group(3)), int(drag_match.group(4))
            x1_abs = round(x1_rel / 1000 * screen_w)
            y1_abs = round(y1_rel / 1000 * screen_h)
            x2_abs = round(x2_rel / 1000 * screen_w)
            y2_abs = round(y2_rel / 1000 * screen_h)
            return {
                "type": "drag",
                "start_relative_coord": [x1_rel, y1_rel],
                "start_absolute_coord": [x1_abs, y1_abs],
                "end_relative_coord": [x2_rel, y2_rel],
                "end_absolute_coord": [x2_abs, y2_abs]
            }

        # type(content='...')
        type_match = re.search(r'type\(content=\'(.+?)\'\)', action_str)
        if type_match:
            return {
                "type": "type",
                "content": type_match.group(1)
            }

        # hotkey(key='...')
        hotkey_match = re.search(r'hotkey\(key=\'(.+?)\'\)', action_str)
        if hotkey_match:
            return {
                "type": "hotkey",
                "key": hotkey_match.group(1)
            }

        # scroll(...)
        scroll_match = re.search(
            r'scroll\(start_box=\'<\|box_start\|>\((\d+),(\d+)\)<\|box_end\|>\',\s*direction=\'(\w+)\'\)',
            action_str
        )
        if scroll_match:
            x_rel, y_rel = int(scroll_match.group(1)), int(scroll_match.group(2))
            x_abs = round(x_rel / 1000 * screen_w)
            y_abs = round(y_rel / 1000 * screen_h)
            return {
                "type": "scroll",
                "direction": scroll_match.group(3),
                "relative_coord": [x_rel, y_rel],
                "absolute_coord": [x_abs, y_abs]
            }

        # wait()
        if 'wait()' in action_str:
            return {"type": "wait"}

        # finished()
        if 'finished()' in action_str:
            return {"type": "finished"}

        # call_user()
        if 'call_user()' in action_str:
            return {"type": "call_user"}

        return {"type": "unknown", "raw": action_str}

    def _execute_action(self, action: dict) -> dict:
        """执行动作（使用 pyautogui）"""
        if not PYAUTOGUI_AVAILABLE:
            return {"status": "error", "message": "pyautogui 未安装，无法执行动作"}

        action_type = action.get("type")

        try:
            if action_type == "click":
                x, y = action["absolute_coord"]
                pyautogui.click(x, y)
                return {"status": "success", "message": f"点击 ({x}, {y})"}

            elif action_type == "left_double":
                x, y = action["absolute_coord"]
                pyautogui.doubleClick(x, y)
                return {"status": "success", "message": f"左键双击 ({x}, {y})"}

            elif action_type == "right_single":
                x, y = action["absolute_coord"]
                pyautogui.rightClick(x, y)
                return {"status": "success", "message": f"右键单击 ({x}, {y})"}

            elif action_type == "drag":
                x1, y1 = action["start_absolute_coord"]
                x2, y2 = action["end_absolute_coord"]
                pyautogui.moveTo(x1, y1)
                pyautogui.dragTo(x2, y2)
                return {"status": "success", "message": f"从 ({x1}, {y1}) 拖拽到 ({x2}, {y2})"}

            elif action_type == "type":
                content = action["content"]
                pyautogui.typewrite(content)
                return {"status": "success", "message": f"输入: {content}"}

            elif action_type == "hotkey":
                keys = action["key"].split('+')
                pyautogui.hotkey(*keys)
                return {"status": "success", "message": f"快捷键: {'+'.join(keys)}"}

            elif action_type == "scroll":
                x, y = action["absolute_coord"]
                direction = action["direction"]
                pyautogui.moveTo(x, y)

                scroll_amount = 300 if direction in ["down", "up"] else 300
                if direction in ["down", "right"]:
                    scroll_amount = -scroll_amount

                if direction in ["up", "down"]:
                    pyautogui.scroll(scroll_amount)
                else:
                    pyautogui.hscroll(scroll_amount)

                return {"status": "success", "message": f"在 ({x}, {y}) 向 {direction} 滚动"}

            elif action_type == "wait":
                import time
                time.sleep(5)
                return {"status": "success", "message": "等待 5 秒"}

            elif action_type == "finished":
                return {"status": "success", "message": "任务已完成"}

            elif action_type == "call_user":
                return {"status": "success", "message": "请求用户协助"}

            else:
                return {"status": "skipped", "message": f"未实现的动作类型: {action_type}"}

        except Exception as e:
            return {"status": "error", "message": str(e)}


# 实例化 - ToolManager 会自动发现并注册
tool = UITarsTool()
