"""
多模态模型Provider基类

定义视觉+动作+推理多模态模型的通用接口
支持GUI自动化、图像理解、视觉问答等场景
"""

import logging
from abc import abstractmethod
from typing import Any

from core.ai_models.base import BaseModelProvider, ModelType

logger = logging.getLogger(__name__)


class BaseMultimodalProvider(BaseModelProvider):
    """
    多模态模型基类（视觉+动作+推理）

    支持处理图像输入并输出结构化结果的多模态模型。
    典型应用场景：
    - GUI自动化（UI-TARS风格）：分析截图输出点击/输入等动作
    - 图像理解：描述图像内容
    - 视觉问答：回答关于图像的问题

    子类需要实现:
    - plan_gui_action(): GUI动作规划
    - describe_image(): 图像描述

    Example:
        provider = UITarsProvider(config)
        await provider.initialize()

        # GUI动作规划
        result = await provider.invoke({
            "image": screenshot_b64,
            "instruction": "点击登录按钮",
            "mode": "gui"
        })

        # 图像描述
        result = await provider.invoke({
            "image": image_b64,
            "instruction": "描述这张图片",
            "mode": "describe"
        })
    """

    # 支持的模式
    SUPPORTED_MODES = ["gui", "describe", "qa"]

    def __init__(self, config):
        """
        初始化多模态Provider

        Args:
            config: ModelConfig配置对象
        """
        super().__init__(config)
        # 设置多模态专用能力
        self._capabilities.vision = True
        self._capabilities.function_calling = True
        self._capabilities.supports_temperature = True
        self._capabilities.supports_max_tokens = True
        self._capabilities.supports_system_prompt = True

        logger.info(f"[{self.__class__.__name__}] 多模态Provider实例创建")

    @property
    def model_type(self) -> ModelType:
        """
        返回模型类型

        Returns:
            ModelType.MULTIMODAL
        """
        return ModelType.MULTIMODAL

    async def invoke(
        self,
        input_data: dict[str, Any],
        **kwargs
    ) -> dict[str, Any]:
        """
        多模态调用 - 统一入口

        根据mode参数自动分发到相应的处理方法。

        Args:
            input_data: 输入数据字典，必须包含:
                - image: 图像数据（base64字符串或文件路径）
                - instruction: 指令文本
                - mode: 处理模式 (gui/describe/qa)
                - context: 可选，上下文历史
            **kwargs: 额外参数:
                - temperature: 温度参数
                - max_tokens: 最大输出token数

        Returns:
            Dict[str, Any]: 处理结果，格式取决于mode:

                gui模式:
                {
                    "thought": "思考过程",
                    "action": "动作类型",
                    "coordinates": [x, y] 或 [x1, y1, x2, y2],
                    "text": "输入文本（如果有）",
                    "raw_response": "原始响应"
                }

                describe/qa模式:
                {
                    "description": "图像描述或答案",
                    "confidence": 0.95,
                    "raw_response": "原始响应"
                }

        Raises:
            ValueError: 不支持的mode或缺少必需参数
            MultimodalException: 处理过程中发生错误

        Example:
            # GUI自动化
            result = await provider.invoke({
                "image": screenshot_b64,
                "instruction": "点击确定按钮",
                "mode": "gui"
            })

            # 图像描述
            result = await provider.invoke({
                "image": image_b64,
                "instruction": "描述画面内容",
                "mode": "describe"
            })
        """
        # 验证必需参数
        if not isinstance(input_data, dict):
            raise ValueError(f"input_data必须是字典，收到: {type(input_data).__name__}")

        image = input_data.get("image")
        instruction = input_data.get("instruction")
        mode = input_data.get("mode", "describe")

        if not image:
            raise ValueError("缺少必需参数: image")

        if not instruction:
            raise ValueError("缺少必需参数: instruction")

        if mode not in self.SUPPORTED_MODES:
            raise ValueError(f"不支持的模式: {mode}，支持的模式: {self.SUPPORTED_MODES}")

        logger.debug(f"[{self.__class__.__name__}] 多模态调用: mode={mode}, instruction={instruction[:50]}...")

        # 根据模式分发
        if mode == "gui":
            return await self.plan_gui_action(input_data, **kwargs)
        elif mode == "describe":
            return await self.describe_image(input_data, **kwargs)
        elif mode == "qa":
            return await self.answer_question(input_data, **kwargs)
        else:
            raise ValueError(f"不支持的模式: {mode}")

    @abstractmethod
    async def plan_gui_action(
        self,
        input_data: dict[str, Any],
        **kwargs
    ) -> dict[str, Any]:
        """
        规划GUI动作（UI-TARS风格）

        分析屏幕截图，根据指令输出具体的GUI操作。

        Args:
            input_data: 输入数据:
                - image: 截图（base64或路径）
                - instruction: 操作指令
                - context: 可选，历史操作记录
            **kwargs: 额外参数

        Returns:
            Dict: 动作规划结果
            {
                "thought": "思考过程文本",
                "action": "动作类型(click/type/drag/scroll/hotkey/wait/finished/...)",
                "coordinates": [x, y] 或 [x1, y1, x2, y2],  # 相对坐标0-1000
                "absolute_coord": [x, y],  # 绝对屏幕坐标（Provider转换）
                "text": "输入的文本（type动作）",
                "key": "快捷键组合（hotkey动作）",
                "direction": "滚动方向（scroll动作）",
                "raw_response": "模型原始响应"
            }

        Raises:
            MultimodalException: 动作规划失败时抛出

        Example:
            result = await provider.plan_gui_action({
                "image": screenshot_b64,
                "instruction": "在搜索框输入'hello'"
            })
            # result: {
            #     "thought": "我需要点击搜索框并输入文本",
            #     "action": "type",
            #     "coordinates": [500, 300],
            #     "text": "hello"
            # }
        """
        pass

    @abstractmethod
    async def describe_image(
        self,
        input_data: dict[str, Any],
        **kwargs
    ) -> dict[str, Any]:
        """
        描述图像内容

        分析图像并生成自然语言描述。

        Args:
            input_data: 输入数据:
                - image: 图像（base64或路径）
                - instruction: 描述指令/问题
            **kwargs: 额外参数

        Returns:
            Dict: 描述结果
            {
                "description": "图像描述文本",
                "details": {
                    "objects": ["对象列表"],
                    "scene": "场景类型"
                },
                "confidence": 0.95,
                "raw_response": "模型原始响应"
            }

        Raises:
            MultimodalException: 描述失败时抛出

        Example:
            result = await provider.describe_image({
                "image": image_b64,
                "instruction": "描述这张图片的内容"
            })
            # result: {
            #     "description": "图片显示了一个蓝色的登录界面...",
            #     "confidence": 0.92
            # }
        """
        pass

    async def answer_question(
        self,
        input_data: dict[str, Any],
        **kwargs
    ) -> dict[str, Any]:
        """
        视觉问答（可选实现）

        回答关于图像内容的具体问题。
        默认实现调用describe_image，子类可覆盖。

        Args:
            input_data: 输入数据
            **kwargs: 额外参数

        Returns:
            Dict: 答案结果
        """
        # 默认实现：使用describe_image
        result = await self.describe_image(input_data, **kwargs)
        result["mode"] = "qa"
        return result

    async def health_check(self) -> dict[str, Any]:
        """
        健康检查

        检查多模态服务是否可用。

        Returns:
            Dict: 健康状态信息
        """

        if not self._initialized:
            return {
                "healthy": False,
                "latency_ms": 0.0,
                "message": "Provider未初始化",
                "details": {"provider": self.config.provider}
            }

        # 多模态健康检查通常需要实际调用
        # 这里返回基础状态，具体Provider可覆盖
        return {
            "healthy": True,
            "latency_ms": 0.0,
            "message": "多模态服务已初始化",
            "details": {
                "provider": self.config.provider,
                "model": self.config.model_name,
                "vision_enabled": self._capabilities.vision
            }
        }

    async def is_available(self) -> bool:
        """
        检查Provider是否可用

        Returns:
            bool: 是否已初始化且可用
        """
        return self._initialized

    def _load_image(self, image: str | bytes) -> str:
        """
        加载并标准化图像

        支持多种输入格式，统一返回base64编码字符串。

        Args:
            image: 图像数据（base64字符串、文件路径、或bytes）

        Returns:
            str: base64编码的图像数据（不含data URI前缀）

        Raises:
            ValueError: 图像加载失败
        """
        import base64
        import os
        from pathlib import Path

        # 已经是base64字符串
        if isinstance(image, str):
            # 检查是否是文件路径
            if Path(image).exists() and os.path.isfile(image):
                # 从文件读取
                with open(image, 'rb') as f:
                    return base64.b64encode(f.read()).decode('utf-8')
            else:
                # 检查是否包含data URI前缀
                if ',' in image:
                    # 去除前缀如 "data:image/png;base64,"
                    return image.split(',', 1)[1]
                return image

        # bytes类型
        elif isinstance(image, bytes):
            return base64.b64encode(image).decode('utf-8')

        else:
            raise ValueError(f"不支持的图像类型: {type(image).__name__}")

    def _relative_to_absolute_coord(
        self,
        rel_coord: list[int],
        screen_size: tuple | None = None
    ) -> list[int]:
        """
        相对坐标转绝对坐标

        UI-TARS等模型输出0-1000的相对坐标，需要转换为屏幕绝对坐标。

        Args:
            rel_coord: 相对坐标 [x, y] 或 [x1, y1, x2, y2]
            screen_size: 屏幕尺寸 (width, height)，默认1920x1080

        Returns:
            List[int]: 绝对坐标
        """
        if screen_size is None:
            screen_size = (1920, 1080)

        screen_w, screen_h = screen_size

        if len(rel_coord) == 2:
            # 单点坐标
            x = round(rel_coord[0] / 1000 * screen_w)
            y = round(rel_coord[1] / 1000 * screen_h)
            return [x, y]
        elif len(rel_coord) == 4:
            # 区域坐标
            x1 = round(rel_coord[0] / 1000 * screen_w)
            y1 = round(rel_coord[1] / 1000 * screen_h)
            x2 = round(rel_coord[2] / 1000 * screen_w)
            y2 = round(rel_coord[3] / 1000 * screen_h)
            return [x1, y1, x2, y2]
        else:
            raise ValueError(f"不支持的坐标格式: {rel_coord}")
