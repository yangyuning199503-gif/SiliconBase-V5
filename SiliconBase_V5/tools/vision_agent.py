#!/usr/bin/env python3
"""
统一视觉工具 - 硅基生命底座核心视觉能力 (V5 - 企业级稳定版)

功能：
1. 图像理解（描述、问答）- 支持 Qwen3-VL、GPT-4V、Claude 3 等
2. GUI 自动化（精确点击、输入坐标）- 支持 UI-TARS、GPT-4V 等

架构：
- 统一使用 AIProviderFactory 获取 Provider
- 支持多后端选择（ui-tars/qwen3-vl/gpt-4v/claude-3等）
- 标准化多模态消息格式（OpenAI格式）
- 完全配置化：后端配置从 config/global.yaml 读取，同时提供内置默认配置
- 通用插排架构：通过配置灵活扩展任意视觉模型后端

修复记录 (P0修复 - 2026-03-22):
- 修复空默认配置问题：添加 BUILTIN_DEFAULTS 内置默认配置
- 修复坐标转换错误：使用实际截图尺寸而非全局 SCREEN_SIZE
- 添加零静默失败机制：所有关键操作都有明确的错误处理

支持的Provider：
- ollama: Ollama本地模型（qwen3-vl, ui-tars等）
- openai: OpenAI API（gpt-4v, gpt-4o等）
- anthropic: Anthropic Claude（claude-3-opus, claude-3-sonnet等）
- azure_openai: Azure OpenAI服务
- 其他OpenAI兼容服务

作者: SiliconBase Team
"""

import asyncio
import base64
import io
import logging
import re
from pathlib import Path
from typing import Any

# 【配置集中化】导入配置模块
from core.config import config
from core.vision.safe_screenshot import safe_screenshot_to_pil

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
    SCREEN_SIZE = pyautogui.size()
except ImportError:
    PYAUTOGUI_AVAILABLE = False
    # 【配置集中化】从 config/vision.yaml 读取默认屏幕尺寸
    default_size = config.get("vision.default_screen_size", [1920, 1080])
    SCREEN_SIZE = tuple(default_size)

from core.base_tool import BaseTool
from core.config import config
from core.error_codes import INVALID_PARAMS, TOOL_EXECUTION_ERROR, format_error
from core.providers.ai_provider_factory import AIProviderFactory

logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    """配置错误异常 - 当缺少必要的配置项时抛出"""
    pass


class VisionAgentTool(BaseTool):
    """
    统一视觉工具 - 支持多种视觉模型后端（通用插排架构）

    后端选项:
    - qwen3-vl: 通用视觉理解（Ollama本地）
    - ui-tars: GUI自动化（Ollama本地）
    - gpt-4v: OpenAI GPT-4 Vision
    - gpt-4o: OpenAI GPT-4o
    - claude-3: Anthropic Claude 3 系列
    - auto: 从配置读取默认后端

    配置方式：
    请在 config/global.yaml 的 ai.vision 部分配置后端：
    ```yaml
    ai:
      vision:
        default_backend: "qwen3-vl"
        backends:
          qwen3-vl:
            provider: "ollama"
            model: "qwen3-vl:2b"
            base_url: "http://localhost:11434"
            capabilities: ["description", "qa", "ocr"]
    ```

    示例:
    - 描述图片: vision_agent(image_source="screenshot", instruction="描述内容")
    - 点击按钮: vision_agent(instruction="点击登录按钮", backend="ui-tars", execute=True)
    - 使用GPT-4V: vision_agent(instruction="分析这张图表", backend="gpt-4v")
    """

    tool_id = "vision_agent"
    name = "视觉智能体"
    description = "统一的视觉能力：支持Ollama本地模型、OpenAI GPT-4V、Claude 3等多种视觉后端（完全配置化，带内置默认）"
    category = "🎵 媒体处理"

    input_schema = {
        "type": "object",
        "properties": {
            "instruction": {
                "type": "string",
                "description": "指令：描述/问答/操作（如'描述图片'、'点击登录按钮'）"
            },
            "image_source": {
                "type": "string",
                "enum": ["screenshot", "path", "base64"],
                "default": "screenshot",
                "description": "图片来源: screenshot(自动截图)/path(文件路径)/base64"
            },
            "image_path": {
                "type": "string",
                "description": "图片路径（当image_source=path时）"
            },
            "image_base64": {
                "type": "string",
                "description": "base64编码的图片（当image_source=base64时）"
            },
            "backend": {
                "type": "string",
                "enum": ["auto", "qwen3-vl", "ui-tars", "gpt-4v", "gpt-4o", "claude-3"],
                "default": "auto",
                "description": "使用的视觉后端: auto(从配置读取)/qwen3-vl/ui-tars/gpt-4v/gpt-4o/claude-3"
            },
            "execute": {
                "type": "boolean",
                "default": False,
                "description": "是否执行识别出的动作（仅GUI操作后端有效）"
            }
        },
        "required": ["instruction"]
    }

    # 后端提示词模板（保留用于各后端的特殊格式化需求）
    PROMPT_TEMPLATES = {
        "qwen3-vl": """你是一个视觉助手。请根据用户提供的图片，回答用户的问题或执行描述任务。
请用中文回答，尽可能详细准确。

用户指令: {instruction}

请描述图片内容:""",

        "gpt-4v": """You are a helpful visual assistant. Please analyze the image and respond to the user's request.

User instruction: {instruction}

Please provide a detailed response:""",

        "gpt-4o": """You are a helpful visual assistant. Please analyze the image and respond to the user's request.

User instruction: {instruction}

Please provide a detailed response:""",

        "claude-3": """You are Claude, an AI assistant made by Anthropic. Please analyze the image and help the user.

User request: {instruction}

Please provide your analysis:""",

        "ui-tars": """You are a GUI agent. You are given a task and your action history, with screenshots. You need to perform the next action to complete the task.

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
No previous actions.

## User Instruction
{instruction}

## Response"""
    }

    # [V5修复] 内置默认配置 - 【配置集中化】从 config/vision.yaml 读取
    # 优先从配置文件加载，如果配置不存在则使用以下硬编码默认值
    @property
    def BUILTIN_DEFAULTS(self) -> dict[str, Any]:
        """
        获取内置默认配置

        【配置集中化】优先从 config/vision.yaml 的 vision.builtin_defaults 读取
        如果配置不存在，使用代码中的默认值

        Returns:
            Dict[str, Any]: 视觉后端默认配置
        """
        # 尝试从配置文件读取
        config_defaults = config.get("vision.builtin_defaults", {})
        if config_defaults and isinstance(config_defaults, dict):
            logger.debug("[VisionAgent] 从配置文件加载内置默认配置")
            return config_defaults

        # 配置文件不存在或无效，使用代码默认值
        logger.debug("[VisionAgent] 使用代码内置默认配置")
        # 动态读取视觉模型，fallback 到 qwen3-vl:2b
        vision_model = config.get("ai.vision.model")
        if not vision_model:
            vision_model = config.get("ai.vision_model")
        if not vision_model:
            default_backend = config.get("ai.vision.default_backend", "ollama-vision")
            vision_model = config.get(f"ai.vision.backends.{default_backend}.model")
        if not vision_model:
            vision_model = "qwen3-vl:2b"
        return {
            "ollama-vision": {
                "provider": "ollama",
                "model": vision_model,
                "base_url": "http://localhost:11434",
                "capabilities": ["description", "qa", "ocr", "gui_action"],
                "supports_vision": True,
                "temperature": 0.2,
                "max_tokens": 512
            },
            "ui-tars": {
                "provider": "ollama",
                "model": "wtyoui/ui-tars:7b",
                "base_url": "http://localhost:11434",
                "capabilities": ["gui_action", "description"],
                "supports_vision": True,
                "temperature": 0.2,
                "max_tokens": 512
            }
        }

    # [V4] DEFAULT_BACKENDS 保留为空字典，向后兼容
    DEFAULT_BACKENDS = {}

    def __init__(self):
        super().__init__()
        self._backends = None
        self._provider_cache: dict[str, Any] = {}
        self._last_screenshot_size: tuple[int, int] | None = None  # [BUG FIX] 初始化为None，等待实际截图后更新

    def _get_backends(self) -> dict[str, Any]:
        """
        [V5修复] 获取视觉后端配置，优先使用自定义，其次使用内置默认

        【配置集中化】配置优先级：
        1. 用户自定义配置 (config.get("ai.vision.backends"))
        2. 配置文件中的内置默认 (config.get("vision.builtin_defaults"))
        3. 代码中的默认配置 (BUILTIN_DEFAULTS)

        Returns:
            后端配置字典
        """
        if self._backends is None:
            # 1. 尝试读取自定义配置
            custom_backends = config.get("ai.vision.backends", {})

            if custom_backends:
                logger.info(f"[VisionAgent] 使用自定义视觉配置，后端: {list(custom_backends.keys())}")
                self._backends = custom_backends
            else:
                # 2. 使用内置默认配置（从配置文件或代码）
                logger.info("[VisionAgent] 使用内置默认视觉配置")
                # BUILTIN_DEFAULTS 是 property，访问它会自动从配置文件读取
                self._backends = dict(self.BUILTIN_DEFAULTS)

        return self._backends

    def _select_backend(self, backend_hint: str | None, instruction: str) -> str:
        """
        选择后端类型

        Args:
            backend_hint: 用户指定的后端
            instruction: 用户指令（用于兼容保留，V4中不再用于自动检测）

        Returns:
            实际使用的后端名称
        """
        if backend_hint and backend_hint != "auto":
            return backend_hint
        return self._auto_select_backend(instruction)

    def _auto_select_backend(self, instruction: str) -> str:
        """
        [V5修复] 自动选择后端

        优先从配置读取默认后端，如果未配置则使用内置默认

        Args:
            instruction: 用户指令（兼容保留，不再使用）

        Returns:
            默认后端名称
        """
        # 1. 尝试从配置读取
        default_backend = config.get("ai.vision.default_backend")

        if default_backend:
            logger.debug(f"[VisionAgent] 使用配置的默认后端: {default_backend}")
            return default_backend

        # 2. 使用内置默认的第一个后端
        builtin_defaults = self.BUILTIN_DEFAULTS
        if builtin_defaults:
            first_backend = list(builtin_defaults.keys())[0]
            logger.debug(f"[VisionAgent] 使用内置默认后端: {first_backend}")
            return first_backend

        # 3. 没有任何可用配置
        raise ConfigurationError(
            "视觉模型后端未配置且无内置默认可用。"
            "请前往前端AI配置区配置视觉模型，"
            "或在 config/global.yaml 中添加 ai.vision.backends 配置。"
        )

    def _get_provider_for_backend(self, backend: str, backend_config: dict) -> Any:
        """
        获取或创建指定后端的Provider实例

        Args:
            backend: 后端名称
            backend_config: 后端配置

        Returns:
            Provider实例
        """
        cache_key = f"{backend}:{backend_config.get('provider')}:{backend_config.get('model')}"

        if cache_key not in self._provider_cache:
            provider_type = backend_config.get("provider", "ollama")

            # 构建Provider配置
            provider_config = {
                "base_url": backend_config.get("base_url", "http://localhost:11434"),
                "model": backend_config.get("model"),
                "timeout": backend_config.get("timeout", 60),
                "retry_times": backend_config.get("retry_times", 2)
            }

            # 如果需要API key，从配置或环境变量获取
            if backend_config.get("requires_api_key"):
                api_key = backend_config.get("api_key") or config.get(f"ai.vision.{backend}.api_key")
                if api_key:
                    provider_config["api_key"] = api_key

            try:
                provider = AIProviderFactory.create_provider(provider_type, **provider_config)
                self._provider_cache[cache_key] = provider
                logger.debug(f"[VisionAgent] 创建Provider: {provider_type}/{backend_config.get('model')}")
            except Exception as e:
                error_msg = f"创建Provider失败 ({provider_type}): {e}"
                logger.error(f"[VisionAgent] {error_msg}")
                raise ValueError(error_msg) from e

        return self._provider_cache[cache_key]

    def _check_vision_support(self, provider: Any, backend_config: dict) -> bool:
        """
        检查Provider是否支持视觉能力

        Args:
            provider: Provider实例
            backend_config: 后端配置

        Returns:
            是否支持视觉
        """
        # 1. 从配置直接检查
        if backend_config.get("supports_vision") is not None:
            return backend_config.get("supports_vision")

        # 2. 检查Provider是否有能力检测方法
        if hasattr(provider, "supports_vision"):
            return provider.supports_vision()

        # 3. 默认假设支持（对于已知Provider）
        known_vision_providers = ["ollama", "openai", "anthropic", "azure_openai"]
        provider_type = backend_config.get("provider", "ollama")
        return provider_type in known_vision_providers

    def _execute(self, **kwargs) -> dict:
        """
        执行视觉任务

        流程：
        1. 解析参数
        2. 选择backend
        3. 获取图片
        4. 调用Provider
        5. 解析响应
        6. 执行动作（如果需要）
        """
        instruction = kwargs.get("instruction")
        image_source = kwargs.get("image_source", "screenshot")
        backend = kwargs.get("backend", "auto")
        execute = kwargs.get("execute", False)

        if not instruction:
            return format_error(INVALID_PARAMS, detail="缺少必需参数: instruction")

        try:
            # 1. 选择后端
            selected_backend = self._select_backend(backend, instruction)
            logger.info(f"[VisionAgent] 使用后端: {selected_backend}")

            # 2. 获取后端配置
            backends = self._get_backends()
            if selected_backend not in backends:
                available = list(backends.keys())
                error_msg = f"未知的视觉后端: {selected_backend}。可用: {available}"
                logger.error(f"[VisionAgent] {error_msg}")
                return format_error(INVALID_PARAMS, detail=error_msg)

            backend_config = backends[selected_backend]

            # 3. 获取图片
            image_b64 = self._get_image(image_source, kwargs)
            if not image_b64:
                return format_error(TOOL_EXECUTION_ERROR, detail="无法获取图片")

            # 4. 获取Provider
            try:
                provider = self._get_provider_for_backend(selected_backend, backend_config)
            except ValueError as e:
                return format_error(TOOL_EXECUTION_ERROR, detail=str(e))

            # 5. 检查视觉支持
            if not self._check_vision_support(provider, backend_config):
                error_msg = f"后端 {selected_backend} 不支持视觉能力"
                logger.error(f"[VisionAgent] {error_msg}")
                return format_error(TOOL_EXECUTION_ERROR, detail=error_msg)

            # 6. 调用视觉模型
            result = self._call_vision_model(
                provider=provider,
                image_b64=image_b64,
                instruction=instruction,
                backend=selected_backend,
                backend_config=backend_config
            )

            if not result:
                return format_error(TOOL_EXECUTION_ERROR,
                                  detail=f"{selected_backend} 模型调用失败")

            # 7. 如果是 GUI 操作且需要执行
            if selected_backend == "ui-tars" and execute:
                execution_result = self._execute_action(result.get("action", {}))
                result["execution"] = execution_result

            # 8. 构建用户友好的返回消息
            if selected_backend == "ui-tars":
                user_msg = f"思考: {result.get('thought', '')}\n动作: {result.get('action_str', '')}"
            else:
                user_msg = result.get("description", result.get("raw", "")[:200])

            return {
                "success": True,
                "error_code": None,
                "user_message": user_msg,
                "data": {
                    "backend": selected_backend,
                    "provider": backend_config.get("provider"),
                    **result
                }
            }

        except ConfigurationError as e:
            # [V5] 配置错误友好提示
            logger.error(f"[VisionAgent] 配置错误: {e}")
            return format_error(INVALID_PARAMS, detail=str(e))
        except Exception as e:
            error_msg = f"视觉工具执行错误: {str(e)}"
            logger.exception(f"[VisionAgent] {error_msg}")
            return format_error(TOOL_EXECUTION_ERROR, detail=error_msg)

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        """
        异步执行入口 - 直接复用同步 _execute，在线程池中执行避免阻塞事件循环。

        Phase 4 改造：提供原生 async 接口，避免 AsyncToolGateway 桥接降级。
        """
        try:
            return await asyncio.to_thread(self._execute, **kwargs)
        except Exception as e:
            error_msg = f"视觉工具异步执行错误: {str(e)}"
            logger.exception(f"[VisionAgent] {error_msg}")
            return format_error(TOOL_EXECUTION_ERROR, detail=error_msg)

    def _get_image(self, source: str, params: dict) -> str | None:
        """获取图片并转为 base64"""
        if source == "screenshot":
            return self._capture_screenshot()
        elif source == "path":
            path = params.get("image_path")
            if path and Path(path).exists():
                with open(path, "rb") as f:
                    return base64.b64encode(f.read()).decode()
            logger.error(f"[VisionAgent] 图片路径不存在: {path}")
            return None
        elif source == "base64":
            return params.get("image_base64")
        return None

    def _capture_screenshot(self) -> str:
        """截取屏幕并记录尺寸 - 【蓝屏修复】使用线程安全截图"""
        import gc
        # 【蓝屏修复】使用safe_screenshot替代mss
        img = safe_screenshot_to_pil(monitor=1)
        if img is None:
            raise RuntimeError("截图失败")

        try:
            # 记录实际截图尺寸（用于坐标转换）
            self._last_screenshot_size = img.size
            logger.debug(f"[VisionAgent] 截图尺寸: {self._last_screenshot_size[0]}x{self._last_screenshot_size[1]}")

            # 压缩 - 【配置集中化】从配置文件读取压缩尺寸
            compression_size = config.get("vision.screenshot_compression", [1920, 1080])
            img.thumbnail(tuple(compression_size))

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

    def _build_vision_messages(self, image_b64: str, prompt: str,
                               provider_type: str) -> list[dict]:
        """
        构建标准的多模态消息格式

        使用OpenAI标准格式：
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "..."},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
            ]
        }

        Args:
            image_b64: base64编码的图片
            prompt: 文本提示词
            provider_type: Provider类型（用于特殊处理）

        Returns:
            标准格式的消息列表
        """
        # 构建标准OpenAI格式的多模态消息
        # 所有Provider在各自的实现中会处理格式转换
        return [{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": prompt
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{image_b64}"
                    }
                }
            ]
        }]

    def _call_vision_model(self, provider: Any, image_b64: str,
                          instruction: str, backend: str,
                          backend_config: dict) -> dict | None:
        """
        统一的视觉模型调用接口

        Args:
            provider: Provider实例
            image_b64: base64编码的图片
            instruction: 用户指令
            backend: 后端名称
            backend_config: 后端配置

        Returns:
            解析后的响应字典
        """
        # 1. 获取提示词
        prompt_template = self.PROMPT_TEMPLATES.get(backend,
                                                     self.PROMPT_TEMPLATES.get("qwen3-vl"))
        prompt = prompt_template.format(instruction=instruction)

        # 2. 获取Provider类型
        provider_type = backend_config.get("provider", "ollama")

        # 3. 构建标准消息
        messages = self._build_vision_messages(image_b64, prompt, provider_type)

        # 4. 调用Provider
        try:
            response = provider.chat(
                messages=messages,
                temperature=backend_config.get("temperature", 0.2),
                max_tokens=backend_config.get("max_tokens", 512),
                model=backend_config.get("model")  # 允许覆盖模型
            )

            if response is None:
                logger.error("[VisionAgent] Provider返回空响应")
                return None

            # 5. 根据后端解析响应
            if backend == "ui-tars":
                return self._parse_ui_tars_response(response)
            else:
                return self._parse_general_response(response, backend)

        except Exception as e:
            error_msg = f"Provider调用失败: {e}"
            logger.error(f"[VisionAgent] {error_msg}")
            raise RuntimeError(error_msg) from e

    def _parse_general_response(self, text: str, backend: str) -> dict:
        """
        解析通用视觉响应

        Args:
            text: 模型返回的文本
            backend: 后端名称

        Returns:
            解析后的字典
        """
        return {
            "description": text.strip(),
            "raw": text,
            "backend": backend
        }

    def _parse_ui_tars_response(self, text: str) -> dict:
        """
        解析 UI-TARS 响应

        Args:
            text: 模型返回的文本

        Returns:
            包含thought, action_str, action的字典
        """
        # 提取 Thought
        thought_match = re.search(r'Thought:\s*(.+?)(?:\n|Action:)', text, re.DOTALL)
        thought = thought_match.group(1).strip() if thought_match else ""

        # 提取 Action
        action_match = re.search(r'Action:\s*(.+?)(?:\n|$)', text, re.DOTALL)
        action_str = action_match.group(1).strip() if action_match else text.strip()

        # 解析动作 - 传入实际截图尺寸
        action = self._parse_action(action_str, self._last_screenshot_size)

        return {
            "thought": thought,
            "action_str": action_str,
            "action": action,
            "raw": text
        }

    def _parse_action(self, action_str: str, screenshot_size: tuple[int, int] | None = None) -> dict:
        """
        [V5修复] 解析 UI-TARS 动作

        使用实际截图尺寸进行坐标转换，而非全局 SCREEN_SIZE

        Args:
            action_str: 动作字符串
            screenshot_size: 实际截图尺寸 (width, height)，为None时使用上次截图尺寸或默认值

        Returns:
            动作字典
        """
        # [BUG FIX] 处理None情况：优先使用传入的尺寸，其次使用上次保存的尺寸，最后使用配置默认值
        if screenshot_size is None:
            default_size = config.get("vision.default_screen_size", [1920, 1080])
            screenshot_size = self._last_screenshot_size or tuple(default_size)
        img_width, img_height = screenshot_size

        # click(start_box='<|box_start|>(x,y)<|box_end|>')
        click_match = re.search(
            r'click\(start_box=\'<\|box_start\|>\((\d+),(\d+)\)<\|box_end\|>\'\)',
            action_str
        )
        if click_match:
            x_rel, y_rel = int(click_match.group(1)), int(click_match.group(2))
            # [V5修复] 使用实际截图尺寸进行坐标转换
            x_abs = round(x_rel / 1000 * img_width)
            y_abs = round(y_rel / 1000 * img_height)

            logger.debug(f"[VisionAgent] 坐标转换: 相对({x_rel}, {y_rel}) -> 绝对({x_abs}, {y_abs})，截图尺寸: {img_width}x{img_height}")

            return {
                "type": "click",
                "relative_coord": [x_rel, y_rel],
                "absolute_coord": [x_abs, y_abs],
                "screenshot_size": screenshot_size  # 记录用于调试
            }

        # left_double(start_box='<|box_start|>(x,y)<|box_end|>')
        left_double_match = re.search(
            r'left_double\(start_box=\'<\|box_start\|>\((\d+),(\d+)\)<\|box_end\|>\'\)',
            action_str
        )
        if left_double_match:
            x_rel, y_rel = int(left_double_match.group(1)), int(left_double_match.group(2))
            x_abs = round(x_rel / 1000 * img_width)
            y_abs = round(y_rel / 1000 * img_height)
            return {
                "type": "left_double",
                "relative_coord": [x_rel, y_rel],
                "absolute_coord": [x_abs, y_abs],
                "screenshot_size": screenshot_size
            }

        # right_single(start_box='<|box_start|>(x,y)<|box_end|>')
        right_single_match = re.search(
            r'right_single\(start_box=\'<\|box_start\|>\((\d+),(\d+)\)<\|box_end\|>\'\)',
            action_str
        )
        if right_single_match:
            x_rel, y_rel = int(right_single_match.group(1)), int(right_single_match.group(2))
            x_abs = round(x_rel / 1000 * img_width)
            y_abs = round(y_rel / 1000 * img_height)
            return {
                "type": "right_single",
                "relative_coord": [x_rel, y_rel],
                "absolute_coord": [x_abs, y_abs],
                "screenshot_size": screenshot_size
            }

        # drag(start_box='<|box_start|>(x1,y1)<|box_end|>', end_box='<|box_start|>(x2,y2)<|box_end|>')
        drag_match = re.search(
            r'drag\(start_box=\'<\|box_start\|>\((\d+),(\d+)\)<\|box_end\|>\',\s*end_box=\'<\|box_start\|>\((\d+),(\d+)\)<\|box_end\|>\'\)',
            action_str
        )
        if drag_match:
            x1_rel, y1_rel = int(drag_match.group(1)), int(drag_match.group(2))
            x2_rel, y2_rel = int(drag_match.group(3)), int(drag_match.group(4))
            x1_abs = round(x1_rel / 1000 * img_width)
            y1_abs = round(y1_rel / 1000 * img_height)
            x2_abs = round(x2_rel / 1000 * img_width)
            y2_abs = round(y2_rel / 1000 * img_height)
            return {
                "type": "drag",
                "start_relative": [x1_rel, y1_rel],
                "start_absolute": [x1_abs, y1_abs],
                "end_relative": [x2_rel, y2_rel],
                "end_absolute": [x2_abs, y2_abs],
                "screenshot_size": screenshot_size
            }

        # scroll(start_box='<|box_start|>(x,y)<|box_end|>', direction='...')
        scroll_match = re.search(
            r'scroll\(start_box=\'<\|box_start\|>\((\d+),(\d+)\)<\|box_end\|>\',\s*direction=\'(.+?)\'\)',
            action_str
        )
        if scroll_match:
            x_rel, y_rel = int(scroll_match.group(1)), int(scroll_match.group(2))
            direction = scroll_match.group(3)
            x_abs = round(x_rel / 1000 * img_width)
            y_abs = round(y_rel / 1000 * img_height)
            return {
                "type": "scroll",
                "relative_coord": [x_rel, y_rel],
                "absolute_coord": [x_abs, y_abs],
                "direction": direction,
                "screenshot_size": screenshot_size
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

        # 其他动作...
        if 'wait()' in action_str:
            return {"type": "wait"}
        if 'finished()' in action_str:
            return {"type": "finished"}
        if 'call_user()' in action_str:
            return {"type": "call_user"}

        return {"type": "unknown", "raw": action_str}

    def _execute_action(self, action: dict) -> dict:
        """
        执行 GUI 动作

        Args:
            action: 动作字典

        Returns:
            执行结果
        """
        if not PYAUTOGUI_AVAILABLE:
            return {"status": "error", "message": "pyautogui 未安装"}

        action_type = action.get("type")

        try:
            if action_type == "click":
                x, y = action["absolute_coord"]
                pyautogui.click(x, y)
                logger.info(f"[VisionAgent] 执行点击: ({x}, {y})")
                return {"status": "success", "action": f"点击 ({x}, {y})"}

            elif action_type == "left_double":
                x, y = action["absolute_coord"]
                pyautogui.doubleClick(x, y)
                logger.info(f"[VisionAgent] 执行双击: ({x}, {y})")
                return {"status": "success", "action": f"双击 ({x}, {y})"}

            elif action_type == "right_single":
                x, y = action["absolute_coord"]
                pyautogui.rightClick(x, y)
                logger.info(f"[VisionAgent] 执行右键: ({x}, {y})")
                return {"status": "success", "action": f"右键 ({x}, {y})"}

            elif action_type == "drag":
                x1, y1 = action["start_absolute"]
                x2, y2 = action["end_absolute"]
                pyautogui.moveTo(x1, y1)
                pyautogui.dragTo(x2, y2)
                logger.info(f"[VisionAgent] 执行拖拽: ({x1}, {y1}) -> ({x2}, {y2})")
                return {"status": "success", "action": f"拖拽 ({x1}, {y1}) -> ({x2}, {y2})"}

            elif action_type == "scroll":
                x, y = action["absolute_coord"]
                direction = action.get("direction", "down")
                scroll_amount = 3 if direction in ["down", "right"] else -3
                pyautogui.moveTo(x, y)
                if direction in ["down", "up"]:
                    pyautogui.scroll(scroll_amount * 100, x, y)
                else:
                    pyautogui.hscroll(scroll_amount * 100, x, y)
                logger.info(f"[VisionAgent] 执行滚动: 方向={direction}, 位置=({x}, {y})")
                return {"status": "success", "action": f"滚动 {direction} 在 ({x}, {y})"}

            elif action_type == "type":
                content = action["content"]
                pyautogui.typewrite(content)
                logger.info(f"[VisionAgent] 执行输入: {content[:20]}...")
                return {"status": "success", "action": f"输入: {content[:20]}..."}

            elif action_type == "hotkey":
                keys = action["key"].split('+')
                pyautogui.hotkey(*keys)
                logger.info(f"[VisionAgent] 执行快捷键: {'+'.join(keys)}")
                return {"status": "success", "action": f"快捷键: {'+'.join(keys)}"}

            elif action_type == "wait":
                logger.info("[VisionAgent] 执行等待")
                return {"status": "success", "action": "等待"}

            elif action_type == "finished":
                logger.info("[VisionAgent] 任务完成")
                return {"status": "success", "action": "任务完成"}

            elif action_type == "call_user":
                logger.info("[VisionAgent] 请求用户协助")
                return {"status": "success", "action": "请求用户协助"}

            return {"status": "skipped", "message": f"未支持的动作: {action_type}"}

        except Exception as e:
            error_msg = f"执行动作失败: {e}"
            logger.error(f"[VisionAgent] {error_msg}")
            return {"status": "error", "message": error_msg}

    def get_available_backends(self) -> list[dict[str, Any]]:
        """
        获取所有可用的视觉后端列表

        Returns:
            后端信息列表
        """
        try:
            backends = self._get_backends()
        except ConfigurationError:
            # [V5] 配置未设置时返回空列表
            return []

        result = []
        for name, config_item in backends.items():
            result.append({
                "name": name,
                "provider": config_item.get("provider"),
                "model": config_item.get("model"),
                "capabilities": config_item.get("capabilities", []),
                "supports_vision": config_item.get("supports_vision", True)
            })

        return result

    def clear_provider_cache(self):
        """清除Provider缓存（配置变更时调用）"""
        self._provider_cache.clear()
        self._backends = None
        logger.info("[VisionAgent] Provider缓存已清除")


# 实例化 - ToolManager 自动注册
tool = VisionAgentTool()
