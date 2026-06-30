"""
UI-TARS Provider

GUI自动化多模态模型适配器，复用tools/ui_tars.py的逻辑。
基于Ollama或其他兼容后端运行UI-TARS模型。

UI-TARS: 端到端GUI自动化模型，输入指令和截图，输出具体操作坐标。
参考: https://github.com/bytedance/UI-TARS

支持的模型:
- ui-tars:7b (推荐，平衡速度和精度)
- ui-tars:2b (轻量级)
- ui-tars:72b (高精度)
"""

import base64
import io
import logging
import re
from typing import Any

from core.ai_models.base import ModelConfig
from core.ai_models.exceptions import ModelLoadException, MultimodalException
from core.ai_models.providers.multimodal.base_multimodal_provider import BaseMultimodalProvider

logger = logging.getLogger(__name__)


class UITarsProvider(BaseMultimodalProvider):
    """
    UI-TARS GUI自动化模型适配器

    通过Ollama或其他AI Provider后端运行UI-TARS模型，
    实现端到端的GUI自动化操作。

    支持的动作类型:
    - click: 单击
    - left_double: 左键双击
    - right_single: 右键单击
    - drag: 拖拽
    - type: 输入文本
    - hotkey: 快捷键
    - scroll: 滚动
    - wait: 等待
    - finished: 任务完成
    - call_user: 请求用户协助

    配置示例:
        config = ModelConfig(
            provider="ui_tars",
            model_name="ui-tars:7b",
            base_url="http://localhost:11434",  # Ollama默认地址
            extra_params={
                "screen_size": [1920, 1080],  # 屏幕尺寸
                "temperature": 0.2,  # UI-TARS推荐低温度
                "max_tokens": 256
            }
        )
    """

    # 支持的动作类型
    ACTION_TYPES = [
        "click", "left_double", "right_single", "drag",
        "type", "hotkey", "scroll", "wait", "finished", "call_user"
    ]

    def __init__(self, config):
        """
        初始化UI-TARS Provider

        Args:
            config: ModelConfig配置对象
                - model_name: UI-TARS模型名称
                - base_url: Ollama服务地址
                - extra_params.screen_size: 屏幕尺寸 [宽, 高]
        """
        super().__init__(config)

        self._inner_provider = None
        self._screen_size = self.config.extra_params.get("screen_size", [1920, 1080])

        # UI-TARS推荐低温度
        self._temperature = self.config.extra_params.get("temperature", 0.2)
        self._max_tokens = self.config.extra_params.get("max_tokens", 256)

        logger.info(f"[{self.__class__.__name__}] Provider实例创建，屏幕尺寸: {self._screen_size}")

    async def initialize(self) -> bool:
        """
        异步初始化Provider

        初始化内部AI Provider（Ollama）。

        Returns:
            bool: 初始化是否成功

        Raises:
            ModelLoadException: 初始化失败时抛出
        """
        try:
            # 延迟导入OllamaProvider
            from core.ai_models.providers.llm.ollama_llm_provider import OllamaLLMProvider

            # 创建内部Provider配置
            inner_config = ModelConfig(
                provider="ollama",
                model_name=self.config.model_name or "ui-tars:7b",
                base_url=self.config.base_url or "http://localhost:11434",
                timeout=self.config.timeout
            )

            self._inner_provider = OllamaLLMProvider(inner_config)

            # 初始化内部Provider
            initialized = await self._inner_provider.initialize()

            if not initialized:
                raise ModelLoadException(
                    "Ollama Provider初始化失败",
                    provider=self.config.provider
                )

            # 检查模型是否可用
            available = await self._inner_provider.is_available()

            if not available:
                logger.warning(f"[{self.__class__.__name__}] Ollama服务可能不可用，请检查模型是否已拉取")

            logger.info(
                f"[{self.__class__.__name__}] 初始化成功, "
                f"模型: {inner_config.model_name}"
            )

            self._mark_initialized()
            return True

        except ImportError as e:
            logger.error(f"[{self.__class__.__name__}] 导入依赖失败: {e}")
            raise ModelLoadException(
                f"缺少必要依赖: {e}",
                provider=self.config.provider
            ) from e
        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] 初始化失败: {e}")
            raise ModelLoadException(
                f"UI-TARS初始化失败: {e}",
                provider=self.config.provider
            ) from e

    async def plan_gui_action(
        self,
        input_data: dict[str, Any],
        **kwargs
    ) -> dict[str, Any]:
        """
        规划GUI动作（UI-TARS核心功能）

        Args:
            input_data: 输入数据:
                - image: 截图（base64字符串或文件路径）
                - instruction: 操作指令
                - context: 可选，历史操作记录
            **kwargs:
                - temperature: 温度参数（覆盖默认）
                - max_tokens: 最大token数（覆盖默认）

        Returns:
            Dict: 动作规划结果
            {
                "thought": "思考过程（中文）",
                "action": "动作类型",
                "action_str": "原始动作字符串",
                "coordinates": [x, y],  # 相对坐标 0-1000
                "absolute_coord": [x, y],  # 绝对屏幕坐标
                "text": "输入的文本（type动作）",
                "key": "快捷键（hotkey动作）",
                "direction": "滚动方向（scroll动作）",
                "raw_response": "模型原始响应",
                "mode": "gui"
            }

        Raises:
            MultimodalException: 动作规划失败时抛出
        """
        if not self._inner_provider or not self._initialized:
            raise MultimodalException(
                "Provider未初始化",
                error_code="PROVIDER_NOT_INITIALIZED"
            )

        image = input_data.get("image")
        instruction = input_data.get("instruction")
        context = input_data.get("context", [])

        if not image or not instruction:
            raise ValueError("GUI动作规划需要image和instruction参数")

        try:
            # 加载图像
            image_b64 = self._load_image(image)

            # 构建UI-TARS格式prompt
            messages = self._build_messages(image_b64, instruction, context)

            # 获取参数
            temperature = kwargs.get("temperature", self._temperature)
            max_tokens = kwargs.get("max_tokens", self._max_tokens)

            # 调用内部Provider
            response = await self._inner_provider.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )

            if not response:
                raise MultimodalException(
                    "模型返回空响应",
                    error_code="EMPTY_RESPONSE"
                )

            # 解析UI-TARS输出格式
            parsed = self._parse_ui_tars_output(response)
            parsed["mode"] = "gui"

            logger.debug(f"[{self.__class__.__name__}] 动作规划成功: {parsed['action']}")
            return parsed

        except MultimodalException:
            raise
        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] 动作规划失败: {e}")
            raise MultimodalException(
                f"GUI动作规划失败: {e}",
                error_code="GUI_PLANNING_ERROR"
            ) from e

    async def describe_image(
        self,
        input_data: dict[str, Any],
        **kwargs
    ) -> dict[str, Any]:
        """
        描述图像内容

        使用UI-TARS模型描述图像（非GUI模式）。

        Args:
            input_data: 输入数据
            **kwargs: 额外参数

        Returns:
            Dict: 描述结果
        """
        image = input_data.get("image")
        instruction = input_data.get("instruction", "描述这张图片的内容")

        if not image:
            raise ValueError("图像描述需要image参数")

        try:
            # 加载图像
            image_b64 = self._load_image(image)

            # 构建描述专用prompt
            system_prompt = "You are a helpful assistant that describes images accurately and concisely."
            user_prompt = f"{instruction}\n\nPlease describe what you see in this image."

            messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": user_prompt,
                    "images": [image_b64]
                }
            ]

            # 调用模型
            response = await self._inner_provider.chat(
                messages=messages,
                temperature=kwargs.get("temperature", 0.7),
                max_tokens=kwargs.get("max_tokens", 512)
            )

            return {
                "description": response,
                "confidence": None,  # UI-TARS不返回置信度
                "raw_response": response,
                "mode": "describe"
            }

        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] 图像描述失败: {e}")
            raise MultimodalException(
                f"图像描述失败: {e}",
                error_code="IMAGE_DESCRIPTION_ERROR"
            ) from e

    def _build_messages(
        self,
        image_b64: str,
        instruction: str,
        context: list[dict] = None
    ) -> list[dict]:
        """
        构建UI-TARS格式消息

        UI-TARS使用特定的系统提示词格式，定义了动作空间和输出格式。

        Args:
            image_b64: base64编码的图像
            instruction: 用户指令
            context: 历史操作记录

        Returns:
            List[Dict]: 格式化的消息列表
        """
        # UI-TARS系统提示词
        system_prompt = """You are a GUI agent. You are given a task and your action history, with screenshots. You need to perform the next action to complete the task.

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
- Coordinates are 0-1000 relative to screen size."""

        # 构建动作历史
        action_history = "No previous actions."
        if context:
            history_lines = []
            for i, action in enumerate(context[-5:], 1):  # 最多显示最近5个动作
                history_lines.append(f"{i}. Thought: {action.get('thought', '')}\n   Action: {action.get('action_str', '')}")
            if history_lines:
                action_history = "\n".join(history_lines)

        system_prompt += f"\n\n## Action History\n{action_history}"

        # 用户提示词
        user_prompt = f"## User Instruction\n{instruction}\n\n## Response"

        return [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": user_prompt,
                "images": [image_b64]
            }
        ]

    def _parse_ui_tars_output(self, response: str) -> dict[str, Any]:
        """
        解析UI-TARS输出

        从UI-TARS的Thought/Action格式提取结构化信息。

        Args:
            response: 模型原始响应

        Returns:
            Dict: 解析后的动作信息
        """
        result = {
            "thought": "",
            "action": "unknown",
            "action_str": "",
            "coordinates": None,
            "absolute_coord": None,
            "text": None,
            "key": None,
            "direction": None,
            "raw_response": response
        }

        # 提取Thought
        thought_match = re.search(r'Thought:\s*(.+?)(?:\n|Action:)', response, re.DOTALL)
        if thought_match:
            result["thought"] = thought_match.group(1).strip()

        # 提取Action
        action_match = re.search(r'Action:\s*(.+?)(?:\n|$)', response, re.DOTALL)
        if action_match:
            action_str = action_match.group(1).strip()
            result["action_str"] = action_str

            # 解析动作类型和参数
            parsed_action = self._parse_action(action_str)
            result.update(parsed_action)

        return result

    def _parse_action(self, action_str: str) -> dict[str, Any]:
        """
        解析动作字符串

        Args:
            action_str: 动作字符串，如 "click(start_box='<|box_start|>(500,300)<|box_end|>')"

        Returns:
            Dict: 解析后的动作参数
        """
        result = {
            "action": "unknown",
            "coordinates": None,
            "absolute_coord": None,
            "text": None,
            "key": None,
            "direction": None
        }

        # click(start_box='<|box_start|>(x,y)<|box_end|>')
        click_match = re.search(
            r'click\(start_box=\'[<\|box_start\|>]*\((\d+),(\d+)\)[<\|box_end\|>]*\'\)',
            action_str
        )
        if click_match:
            result["action"] = "click"
            result["coordinates"] = [int(click_match.group(1)), int(click_match.group(2))]
            result["absolute_coord"] = self._relative_to_absolute_coord(result["coordinates"])
            return result

        # left_double(start_box='...')
        left_double_match = re.search(
            r'left_double\(start_box=\'[<\|box_start\|>]*\((\d+),(\d+)\)[<\|box_end\|>]*\'\)',
            action_str
        )
        if left_double_match:
            result["action"] = "left_double"
            result["coordinates"] = [int(left_double_match.group(1)), int(left_double_match.group(2))]
            result["absolute_coord"] = self._relative_to_absolute_coord(result["coordinates"])
            return result

        # right_single(start_box='...')
        right_single_match = re.search(
            r'right_single\(start_box=\'[<\|box_start\|>]*\((\d+),(\d+)\)[<\|box_end\|>]*\'\)',
            action_str
        )
        if right_single_match:
            result["action"] = "right_single"
            result["coordinates"] = [int(right_single_match.group(1)), int(right_single_match.group(2))]
            result["absolute_coord"] = self._relative_to_absolute_coord(result["coordinates"])
            return result

        # drag(start_box='...', end_box='...')
        drag_match = re.search(
            r'drag\(start_box=\'[<\|box_start\|>]*\((\d+),(\d+)\)[<\|box_end\|>]*\',\s*end_box=\'[<\|box_start\|>]*\((\d+),(\d+)\)[<\|box_end\|>]*\'\)',
            action_str
        )
        if drag_match:
            result["action"] = "drag"
            start_coord = [int(drag_match.group(1)), int(drag_match.group(2))]
            end_coord = [int(drag_match.group(3)), int(drag_match.group(4))]
            result["start_coord"] = start_coord
            result["end_coord"] = end_coord
            result["start_absolute_coord"] = self._relative_to_absolute_coord(start_coord)
            result["end_absolute_coord"] = self._relative_to_absolute_coord(end_coord)
            return result

        # type(content='...')
        type_match = re.search(r'type\(content=\'(.+?)\'\)', action_str)
        if type_match:
            result["action"] = "type"
            result["text"] = type_match.group(1)
            return result

        # hotkey(key='...')
        hotkey_match = re.search(r'hotkey\(key=\'(.+?)\'\)', action_str)
        if hotkey_match:
            result["action"] = "hotkey"
            result["key"] = hotkey_match.group(1)
            return result

        # scroll(start_box='...', direction='...')
        scroll_match = re.search(
            r'scroll\(start_box=\'[<\|box_start\|>]*\((\d+),(\d+)\)[<\|box_end\|>]*\',\s*direction=\'(\w+)\'\)',
            action_str
        )
        if scroll_match:
            result["action"] = "scroll"
            result["coordinates"] = [int(scroll_match.group(1)), int(scroll_match.group(2))]
            result["absolute_coord"] = self._relative_to_absolute_coord(result["coordinates"])
            result["direction"] = scroll_match.group(3)
            return result

        # wait()
        if 'wait()' in action_str:
            result["action"] = "wait"
            return result

        # finished()
        if 'finished()' in action_str:
            result["action"] = "finished"
            return result

        # call_user()
        if 'call_user()' in action_str:
            result["action"] = "call_user"
            return result

        return result

    def _relative_to_absolute_coord(self, rel_coord: list[int]) -> list[int]:
        """
        相对坐标转绝对坐标

        Args:
            rel_coord: 相对坐标 [x, y]，范围0-1000

        Returns:
            List[int]: 绝对屏幕坐标
        """
        screen_w, screen_h = self._screen_size
        x = round(rel_coord[0] / 1000 * screen_w)
        y = round(rel_coord[1] / 1000 * screen_h)
        return [x, y]

    async def health_check(self) -> dict[str, Any]:
        """
        健康检查

        Returns:
            Dict: 健康状态信息
        """
        if not self._initialized or not self._inner_provider:
            return {
                "healthy": False,
                "latency_ms": 0.0,
                "message": "Provider未初始化",
                "details": {"provider": self.config.provider}
            }

        # 检查内部Provider健康状态
        inner_health = await self._inner_provider.health_check()

        return {
            "healthy": inner_health.get("healthy", False),
            "latency_ms": inner_health.get("latency_ms", 0.0),
            "message": f"UI-TARS {inner_health.get('message', '未知状态')}",
            "details": {
                "provider": self.config.provider,
                "model": self.config.model_name,
                "screen_size": self._screen_size,
                "ollama_health": inner_health
            }
        }

    async def capture_screenshot(self) -> str | None:
        """
        捕获屏幕截图 - 【蓝屏修复】使用线程安全截图

        Returns:
            Optional[str]: base64编码的截图，失败返回None
        """
        try:
            # 【蓝屏修复】使用safe_screenshot替代mss
            from core.vision.safe_screenshot import safe_screenshot_to_pil
            img = safe_screenshot_to_pil(monitor=1)
            if img is None:
                logger.error(f"[{self.__class__.__name__}] 截图失败")
                return None

            # 压缩以加快传输
            img.thumbnail((1920, 1080))

            # 转为base64
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            return base64.b64encode(buffer.getvalue()).decode()

        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] 截图失败: {e}")
            return None
