#!/usr/bin/env python3
"""
原子工具：视觉理解（基于Provider Factory）
使用配置的AI Provider统一处理文本+视觉

优势：
- 支持多后端（Ollama/OpenAI/Anthropic等）
- 通用插排架构，不依赖硬编码模型列表
- 中文理解更好
- 工具调用能力保留
"""

import asyncio
import base64
import io
import threading
import time

from core.base_tool import BaseTool
from core.config import config
from core.error_codes import INVALID_PARAMS, TOOL_EXECUTION_ERROR, format_error
from core.providers.ollama_provider import ProviderOutputTruncatedError

# 视觉模型调用超时配置（秒）
# 【关键修复】层级超时策略：视觉推理 > 截图 > 网络请求
VISION_MODEL_TIMEOUT = 45      # 视觉模型推理超时（必须 > ToolManager 工具超时）
SCREENSHOT_TIMEOUT = 10        # 截图操作超时
PROVIDER_TIMEOUT = 120         # Provider 底层超时（【修复】从 60 提高到 120，容纳模型切换）
VISION_CALL_TIMEOUT = 60       # 单次视觉模型调用硬超时，防止坏模型拖垮整个任务
VISION_MAX_RETRIES = 1         # 最大重试次数

# 【GPU保护】全局并发控制：同时只允许1个视觉模型调用在GPU上运行（防止显存堆积）
_vision_gpu_semaphore = threading.Semaphore(1)

# 【Phase 4 异步化】异步GPU并发锁，用于原生异步路径
# 【紧急手术】延迟初始化，防止模块导入时绑定到错误的事件循环
_vision_gpu_async_semaphore = None

def _ensure_async_semaphore():
    """获取或重建绑定到当前事件循环的 GPU 并发锁"""
    global _vision_gpu_async_semaphore
    try:
        loop = asyncio.get_running_loop()
        if _vision_gpu_async_semaphore is None or getattr(_vision_gpu_async_semaphore, '_loop', None) is not loop:
            _vision_gpu_async_semaphore = asyncio.Semaphore(1)
    except RuntimeError:
        _vision_gpu_async_semaphore = asyncio.Semaphore(1)
    return _vision_gpu_async_semaphore

# 【GPU保护】显存检查阈值：使用率超过此值时跳过视觉模型调用
VISION_GPU_MEMORY_THRESHOLD = 85  # 百分比

# 【修复】_execute_async 入口降级日志冷却（60秒）
_execute_degraded_log_until = 0


def _check_gpu_memory_for_vision() -> tuple:
    """检查GPU显存，如果不足则拒绝视觉模型调用"""
    try:
        import torch
        if torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                allocated = torch.cuda.memory_allocated(i) / 1024**3
                total = torch.cuda.get_device_properties(i).total_memory / 1024**3
                usage_percent = (allocated / total) * 100 if total > 0 else 0
                if usage_percent > VISION_GPU_MEMORY_THRESHOLD:
                    msg = f"GPU{i}显存使用率{usage_percent:.1f}%过高，跳过视觉模型调用"
                    return False, msg
    except Exception:
        pass
    return True, None

# 【关键修复】子进程安全标志 - 防止子进程被终止时资源泄漏
_import_signal = False
if __name__ != "__main__":
    try:
        import signal
        import sys
        _import_signal = True
    except ImportError:
        pass


class VisualUnderstand(BaseTool):
    """
    视觉理解工具 - 基于Provider Factory（多后端支持，通用插排架构）
    """
    tool_id = "visual_understand"
    name = "视觉理解"
    description = "使用AI Provider理解图像内容（支持多后端：Ollama/OpenAI/Anthropic等）"

    # 【P0修复】Ollama视觉模型连续失败计数器，超过阈值则降级到纯文本描述
    _vision_failure_count = 0
    _VISION_FAILURE_THRESHOLD = 5
    _VISION_COOLDOWN_SECONDS = 2
    _degraded_warning_logged = False
    _degraded_until = 0           # 【修复】降级冷却结束时间戳（秒）
    _degraded_lock = threading.Lock()  # 【P0修复】保护降级状态的线程锁

    input_schema = {
        "type": "object",
        "properties": {
            "image_source": {
                "type": "string",
                "description": "图片来源：'screenshot'（截图）、'path'（文件路径）"
            },
            "question": {
                "type": "string",
                "default": "描述这张图片的内容",
                "description": "关于图像的问题"
            },
            "image_path": {
                "type": "string",
                "description": "图片路径（当image_source为path时）"
            }
        },
        "required": ["image_source"]
    }

    # 【已废弃】硬编码VISION_MODELS字典已删除
    # 原VISION_MODELS用于硬编码各Provider支持的vision模型列表
    # 现为通用插排架构，不再维护硬编码列表，由配置决定使用哪个模型

    @property
    def MODEL(self):
        """
        从配置读取视觉模型（增强版，支持多路径兼容）

        优先级：
        1. ai.vision.model                    # 标准路径
        2. ai.vision_model                    # 根级兼容（global.yaml第32行）
        3. ai.vision.backends.<default>.model # backends配置
        4. model_name                         # 根级兼容（global.yaml第125行）
        5. ai.config.model                    # 最后回退（带警告）

        Raises:
            Exception: 如果所有路径都未配置
        """
        from core.logger import logger

        # 1. 标准路径
        model = config.get("ai.vision.model")
        if model:
            logger.info(f"[VisualUnderstand] 使用视觉模型 (ai.vision.model): {model}")
            return model

        # 2. 根级兼容路径（ai.vision_model）
        model = config.get("ai.vision_model")
        if model:
            logger.info(f"[VisualUnderstand] 使用视觉模型 (ai.vision_model): {model}")
            return model

        # 3. 从backends配置读取
        default_backend = config.get("ai.vision.default_backend", "ollama-vision")
        model = config.get(f"ai.vision.backends.{default_backend}.model")
        if model:
            logger.info(f"[VisualUnderstand] 使用视觉模型 (backends.{default_backend}): {model}")
            return model

        # 4. 根级model_name（global.yaml第125行）
        model = config.get("model_name")
        if model and "vl" in model.lower():
            logger.info(f"[VisualUnderstand] 使用视觉模型 (model_name): {model}")
            return model

        # 5. 不再回退到文本模型（修复04-条目20：向非VL模型发送图片的BUG）
        raise Exception(
            "视觉模型未配置。请在 config/global.yaml 中设置:\n"
            "  ai:\n"
            "    vision:\n"
            "      model: qwen3-vl:2b"
        )

    def _capture_screenshot(self) -> str:
        """截图并转为base64 - 【蓝屏修复】使用线程安全截图"""
        import gc

        from core.vision.safe_screenshot import safe_screenshot_to_pil

        img = safe_screenshot_to_pil(monitor=1)
        if img is None:
            raise RuntimeError("截图失败")

        # 【P0修复】图像完整性验证：尺寸必须合法
        if img.width <= 0 or img.height <= 0 or img.width > 10000 or img.height > 10000:
            img.close()
            del img
            gc.collect()
            raise RuntimeError(f"截图尺寸异常: {img.width}x{img.height}")

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        result = base64.b64encode(buffer.getvalue()).decode()

        # 【P0修复】显式释放图像资源
        img.close()
        del img
        buffer.close()
        del buffer
        gc.collect()
        return result

    def _load_image(self, path: str) -> str:
        """加载图片并转为base64"""
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()

    def _resize_image_b64(self, image_b64: str, max_size: int = 448) -> str:
        """
        将 base64 图像缩放到模型可承受的分辨率。

        【P0修复】qwen3-vl:2b 等轻量视觉模型的上下文窗口仅4096，
        大图（>448px）产生的视觉token会塞满整个窗口导致输出被截断。
        448px = 32×32 patches（patch_size=14），视觉token约512个，
        给文本输出保留足够空间。必须在送入模型前缩放图像。

        Args:
            image_b64: Base64编码的图像
            max_size: 最长边像素上限（默认448，适配2B级视觉模型4096上下文窗口）

        Returns:
            缩放后的 base64 图像
        """
        import io

        from PIL import Image

        from core.logger import logger

        img_bytes = base64.b64decode(image_b64)
        img = Image.open(io.BytesIO(img_bytes))

        # 新增最小目标尺寸
        min_size = 224

        if img.width < min_size and img.height < min_size:
            # 小图只放大到 224，不是 672
            ratio = min_size / max(img.width, img.height)
            new_width = int(img.width * ratio)
            new_height = int(img.height * ratio)
            img = img.resize((new_width, new_height), Image.LANCZOS)
            logger.info(
                f"[VisualUnderstand] 图像放大: {img.width}x{img.height} → "
                f"{new_width}x{new_height}，小图不过度放大"
            )
        elif img.width > max_size or img.height > max_size:
            ratio = min(max_size / img.width, max_size / img.height)
            new_width = int(img.width * ratio)
            new_height = int(img.height * ratio)
            img = img.resize((new_width, new_height), Image.LANCZOS)
            logger.info(
                f"[VisualUnderstand] 图像缩放: {img.width}x{img.height} → "
                f"{new_width}x{new_height}，避免视觉token超出上下文窗口"
            )

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        result = base64.b64encode(buffer.getvalue()).decode()
        img.close()
        buffer.close()
        return result

    def _build_vision_messages(self, provider_type: str, image_b64: str, question: str, model: str = None) -> list:
        """
        根据Provider类型构建vision消息格式

        Args:
            provider_type: Provider类型（ollama/openai/anthropic等）
            image_b64: Base64编码的图像
            question: 用户问题
            model: 模型名称（用于Qwen3系列自动关闭thinking模式）

        Returns:
            格式化的messages数组
        """
        provider_type = provider_type.lower()

        # 【关键修复】Qwen3 系列模型默认开启 thinking，小 num_predict 下 thinking token 会占满输出预算，
        # 导致 content 为空。在 prompt 中加入 /no_think 可强制关闭 thinking。
        model_lower = (model or "").lower()
        if "qwen3" in model_lower and not question.lstrip().startswith("/no_think"):
            question = "/no_think " + question

        if provider_type == "ollama":
            # Ollama原生格式：使用images字段
            return [
                {
                    "role": "user",
                    "content": question,
                    "images": [image_b64]
                }
            ]
        else:
            # OpenAI标准格式（适用于OpenAI、Anthropic、Azure OpenAI、各类兼容服务）
            return [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": question
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_b64}"
                            }
                        }
                    ]
                }
            ]

    def _create_vision_provider(self):
        """根据配置创建视觉 Provider，避免硬编码 Ollama 与 base_url。"""
        from core.logger import logger
        from core.providers.ai_provider_factory import AIProviderFactory

        default_backend = config.get("ai.vision.default_backend", "ollama-vision")
        backend_config = config.get(f"ai.vision.backends.{default_backend}", {}) or {}

        # 从配置读取 provider 类型，默认 ollama
        provider_type = backend_config.get("provider", "ollama").lower()
        provider_config = dict(backend_config)
        provider_config.setdefault("model", self.MODEL)
        provider_config.setdefault("timeout", PROVIDER_TIMEOUT)
        provider_config.setdefault("retry_times", 0)

        logger.info(
            f"[VisualUnderstand] 创建视觉 Provider: type={provider_type}, "
            f"model={provider_config.get('model')}, "
            f"base_url={provider_config.get('base_url', 'default')}"
        )
        return AIProviderFactory.create_provider(provider_type, **provider_config), provider_type

    async def _execute_async(self, **kwargs) -> dict:
        """
        异步执行视觉理解 - 原生异步实现

        关键改造：
        1. 图像获取（截图/文件读取）通过 run_in_executor 桥接
        2. 视觉模型调用优先使用 provider.chat_async() 实现真异步
        3. 【GPU保护】显存检查 + 全局并发锁，防止GPU显存堆积卡死
        """
        from core.logger import logger

        # 【修复】统一入口降级检查：即使调用方绕过 is_degraded()，也在此处短路
        if VisualUnderstand.is_degraded():
            global _execute_degraded_log_until
            now = time.time()
            if now >= _execute_degraded_log_until:
                logger.warning("[VisualUnderstand] 入口降级检查触发，跳过视觉模型调用")
                _execute_degraded_log_until = now + 60
            return {
                "success": True,
                "error_code": None,
                "user_message": "视觉模型暂时不可用，使用系统感知数据替代",
                "data": {
                    "description": "[视觉模型已降级] 当前无法获取视觉分析，请依赖OCR和UI自动化数据执行操作。",
                    "model": self.MODEL,
                    "provider": "degraded",
                    "degraded": True
                }
            }

        # 【修复】参数校验前置，避免无效请求占用全局视觉锁
        image_source = kwargs.get("image_source")
        question = kwargs.get("question", "描述这张图片的内容")
        image_path = kwargs.get("image_path")

        if image_source == "path" and not image_path:
            return format_error(INVALID_PARAMS, detail="image_path 不能为空")

        # 【P0修复】获取当前事件循环，供 run_in_executor 使用
        loop = asyncio.get_running_loop()

        # 【GPU保护】显存不足时直接跳过
        gpu_ok, gpu_msg = _check_gpu_memory_for_vision()
        if not gpu_ok:
            logger.warning(f"[VisualUnderstand] {gpu_msg}")
            return {"success": False, "error_code": "GPU_MEMORY_LOW", "user_message": gpu_msg, "data": None}

        # 【修复】在获取全局锁之前创建 Provider 并进行模型预热，避免持锁等待
        try:
            vision_provider, provider_type = self._create_vision_provider()
        except Exception as e:
            logger.exception(f"[VisualUnderstand] 创建视觉 Provider 失败: {e}")
            return format_error(TOOL_EXECUTION_ERROR, detail=f"视觉 Provider 初始化失败: {e}")

        model = self.MODEL
        if self._is_ollama_provider(vision_provider):
            await self._prewarm_ollama_model_async(vision_provider, model)

        # 获取图像（同步操作，用 run_in_executor 桥接）
        try:
            if image_source == "screenshot":
                image_b64 = await loop.run_in_executor(None, self._capture_screenshot)
            elif image_source == "path":
                image_b64 = await loop.run_in_executor(None, self._load_image, image_path)
            else:
                # 假设是 base64
                image_b64 = image_source
        except Exception as e:
            logger.exception(f"[VisualUnderstand] 获取图像失败: {e}")
            return format_error(TOOL_EXECUTION_ERROR, detail=f"获取图像失败: {e}")

        # 【GPU保护】获取异步全局并发锁（Phase 4 原生异步，消除 run_in_executor）
        acquired = False
        try:
            sem = _ensure_async_semaphore()
            await asyncio.wait_for(sem.acquire(), timeout=VISION_MODEL_TIMEOUT)
            acquired = True
        except asyncio.TimeoutError:
            logger.warning("[VisualUnderstand] 异步视觉模型调用超时：无法获取GPU并发锁")
            return {"success": False, "error_code": "VISION_BUSY", "user_message": "视觉模型正忙，请稍后再试", "data": None}

        if acquired:
            try:
                # 调用异步视觉模型
                return await self._call_vision_model_async(vision_provider, provider_type, image_b64, question)
            finally:
                _vision_gpu_async_semaphore.release() if _vision_gpu_async_semaphore else None

    @staticmethod
    def _is_ollama_provider(provider) -> bool:
        """判断 Provider 是否为 OllamaProvider（用于预热检查）"""
        try:
            from core.providers.ollama_provider import OllamaProvider
            return isinstance(provider, OllamaProvider)
        except Exception:
            return False

    @staticmethod
    async def _prewarm_ollama_model_async(vision_provider, model: str):
        """在锁外检查 Ollama 模型是否已加载，未加载则等待预热。"""
        from core.logger import logger
        if not (hasattr(vision_provider, '_ensure_model_loaded_async') and callable(vision_provider._ensure_model_loaded_async)):
            return
        try:
            model_loaded = await vision_provider._ensure_model_loaded_async(model)
            if not model_loaded:
                logger.info(f"[VisualUnderstand] 视觉模型 {model} 未加载，正在请求加载...")
                await asyncio.sleep(10)
        except Exception as e:
            logger.debug(f"[VisualUnderstand] 模型加载检查失败，继续尝试调用: {e}")

    def _get_vision_max_tokens(self, model: str, image_b64: str = "") -> int:
        """根据模型上下文窗口和图像大小返回合理的视觉生成 token 上限。"""
        model_lower = model.lower()
        is_qwen3_vl_2b = "qwen3-vl" in model_lower and "2b" in model_lower

        # 根据图像 base64 长度估算视觉 token（base64 每 4 字符 ≈ 3 字节，压缩后约 0.75 倍）
        # 这是一个粗略估算，用于判断图像是否复杂
        img_size_factor = 1.0
        if image_b64:
            img_len = len(image_b64)
            if img_len > 500_000:  # 大图
                img_size_factor = 1.3
            elif img_len < 50_000:  # 小图
                img_size_factor = 0.8

        if is_qwen3_vl_2b:
            # 2B 模型窗口约 4096；给输出留 2048 tokens
            return int(2048 * img_size_factor)
        elif "qwen3-vl" in model_lower:
            return int(4096 * img_size_factor)
        elif "qwen2-vl" in model_lower or "qwen-vl" in model_lower:
            return int(2048 * img_size_factor)
        else:
            # 保守默认，避免超出轻量模型窗口
            return int(4096 * img_size_factor)

    def _get_resize_max_size(self, model: str) -> int:
        """根据模型能力返回图像缩放后的最长边上限。"""
        model_lower = model.lower()
        if "qwen3-vl" in model_lower and "2b" in model_lower:
            # 2B 模型上下文窗口极小，必须压到 336px 才能给输出留空间
            return 336
        elif "qwen3-vl" in model_lower:
            return 448
        elif "qwen2-vl" in model_lower or "qwen-vl" in model_lower:
            return 672
        else:
            # 默认保守值
            return 448

    async def _call_vision_model_async(self, vision_provider, provider_type: str, image_b64: str, question: str) -> dict:
        """异步调用视觉模型 - 【P0修复】增加失败计数、降级策略、资源清理"""
        import gc

        from core.logger import logger

        model = self.MODEL

        # 【P0修复】如果连续失败超过阈值，降级到纯文本描述，不再调用视觉模型
        with VisualUnderstand._degraded_lock:
            failure_count = VisualUnderstand._vision_failure_count
            degraded_logged = VisualUnderstand._degraded_warning_logged
        if failure_count >= VisualUnderstand._VISION_FAILURE_THRESHOLD:
            if not degraded_logged:
                logger.warning(f"[VisualUnderstand] 视觉模型已连续失败{failure_count}次，进入降级模式")
                with VisualUnderstand._degraded_lock:
                    VisualUnderstand._degraded_warning_logged = True
            return {
                "success": True,
                "error_code": None,
                "user_message": "视觉模型暂时不可用，使用系统感知数据替代",
                "data": {
                    "description": "[视觉模型已降级] 当前无法获取视觉分析，请依赖OCR和UI自动化数据执行操作。",
                    "model": model,
                    "provider": "degraded",
                    "degraded": True
                }
            }

        # 【P0修复】图像base64完整性验证
        if not image_b64 or len(image_b64) < 100:
            logger.error("[VisualUnderstand] 图像base64数据异常，长度不足")
            VisualUnderstand._record_failure()
            return format_error(TOOL_EXECUTION_ERROR, detail="图像数据异常或损坏")

        messages = None
        call_succeeded = False

        try:
            # 【P0修复】4K截图视觉token会塞满2B模型上下文窗口，必须在构建消息前缩放
            # 【P1-修复】按模型能力动态选择缩放尺寸，避免小模型被大图塞满
            resize_max_size = self._get_resize_max_size(model)
            image_b64 = self._resize_image_b64(image_b64, max_size=resize_max_size)

            messages = self._build_vision_messages(provider_type, image_b64, question, model=model)

            # 【Phase 4 关键改造】优先使用 chat_async
            # 【P0修复】按模型上下文动态限制 max_tokens
            vision_max_tokens = self._get_vision_max_tokens(model, image_b64=image_b64)

            async def _vision_chat_with_timeout(max_tokens: int):
                if hasattr(vision_provider, 'chat_async') and callable(vision_provider.chat_async):
                    return await asyncio.wait_for(
                        vision_provider.chat_async(
                            messages, model=model, max_tokens=max_tokens, timeout=PROVIDER_TIMEOUT
                        ),
                        timeout=VISION_CALL_TIMEOUT
                    )
                else:
                    # 降级：桥接到同步 chat
                    loop = asyncio.get_running_loop()
                    return await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            lambda: vision_provider.chat(
                                messages, model=model, max_tokens=max_tokens, timeout=PROVIDER_TIMEOUT
                            )
                        ),
                        timeout=VISION_CALL_TIMEOUT
                    )

            response = await _vision_chat_with_timeout(vision_max_tokens)

            if response and self._response_is_valid(response):
                logger.info(f"[VisualUnderstand] 异步视觉模型调用成功，响应长度={len(response)}")
                # 【P0修复】调用成功，重置失败计数和降级日志标记
                VisualUnderstand._record_success()
                if not VisualUnderstand.is_degraded():
                    logger.info("[VisualUnderstand] 视觉模型恢复，退出降级模式")
                call_succeeded = True
                return {
                    "success": True,
                    "error_code": None,
                    "user_message": f"视觉理解完成: {response[:100]}...",
                    "data": {
                        "description": response,
                        "model": model,
                        "provider": provider_type
                    }
                }
            else:
                reason = "模型返回空响应" if not response else "模型返回无效乱码"
                logger.warning(f"[VisualUnderstand] 异步调用模型返回无效响应: {reason}")
                VisualUnderstand._record_failure()
                return format_error(TOOL_EXECUTION_ERROR, detail=reason)
        except ProviderOutputTruncatedError as e:
            # 【P0修复】区分输出截断与真正失败
            model_lower = model.lower()
            logger.info("[VisualUnderstand] 视觉模型输出截断，增加 max_tokens 重试")
            try:
                # 重试时使用更合理的 token 上限（2B 窗口 4096，其他模型可更大）
                retry_max_tokens = self._get_vision_max_tokens(model) * 2
                model_lower = model.lower()
                max_allowed = 4096 if "qwen3-vl" in model_lower and "2b" in model_lower else 8192
                if retry_max_tokens > max_allowed:
                    retry_max_tokens = max_allowed
                response = await _vision_chat_with_timeout(retry_max_tokens)
                if response and self._response_is_valid(response):
                    logger.info(f"[VisualUnderstand] 增加 max_tokens 重试成功，响应长度={len(response)}")
                    VisualUnderstand._record_success()
                    if not VisualUnderstand.is_degraded():
                        logger.info("[VisualUnderstand] 视觉模型恢复，退出降级模式")
                    call_succeeded = True
                    return {
                        "success": True,
                        "error_code": None,
                        "user_message": f"视觉理解完成: {response[:100]}...",
                        "data": {
                            "description": response,
                            "model": model,
                            "provider": provider_type
                        }
                    }
                else:
                    logger.warning("[VisualUnderstand] 增加 max_tokens 后仍返回空响应")
                    VisualUnderstand._record_failure()
                    return format_error(TOOL_EXECUTION_ERROR, detail="模型返回空响应")
            except Exception as retry_err:
                logger.exception(
                    f"[VisualUnderstand] 增加 max_tokens 重试异常"
                    f"（原始截断异常: {e}）"
                )
                VisualUnderstand._record_failure()
                return format_error(TOOL_EXECUTION_ERROR, detail=f"视觉理解异常: {retry_err}")
        except Exception as e:
            logger.exception("[VisualUnderstand] 异步视觉模型调用异常")
            VisualUnderstand._record_failure()
            return format_error(TOOL_EXECUTION_ERROR, detail=f"视觉理解异常: {e}")
        finally:
            # 【P0修复】强制垃圾回收；成功时跳过冷却，仅在失败/异常时冷却
            gc.collect()
            if not call_succeeded:
                await asyncio.sleep(VisualUnderstand._VISION_COOLDOWN_SECONDS)

    @staticmethod
    def _response_is_valid(response: str) -> bool:
        """检查模型返回是否有效（非空且不全为替换字符/空白）"""
        if not response:
            return False
        return any(ch not in ('\ufffd',) and not ch.isspace() for ch in response)

    @classmethod
    def _record_failure(cls):
        """【P0修复】线程安全地记录一次失败"""
        with cls._degraded_lock:
            cls._vision_failure_count += 1

    @classmethod
    def _record_success(cls):
        """【P0修复】线程安全地记录一次成功并重置降级状态"""
        with cls._degraded_lock:
            cls._vision_failure_count = 0
            cls._degraded_until = 0
            if cls._degraded_warning_logged:
                cls._degraded_warning_logged = False

    @classmethod
    def is_degraded(cls) -> bool:
        """查询视觉模型是否处于降级状态，供外部调用方短路判断。"""
        import time
        with cls._degraded_lock:
            # 【修复】降级冷却自动恢复：若冷却期已过，重置失败计数
            if cls._vision_failure_count >= cls._VISION_FAILURE_THRESHOLD:
                now = time.time()
                if cls._degraded_until == 0:
                    cls._degraded_until = now + 120
                if now >= cls._degraded_until:
                    from core.logger import logger
                    logger.info("[VisualUnderstand] 视觉模型降级冷却期结束，尝试恢复调用")
                    cls._vision_failure_count = 0
                    cls._degraded_warning_logged = False
                    cls._degraded_until = 0
                    return False
                return True
            return False

    def _setup_subprocess_handlers(self):
        """
        【关键修复】设置子进程信号处理
        确保子进程被终止时能清理资源
        """
        if _import_signal:
            try:
                # 设置终止信号处理
                def signal_handler(signum, frame):
                    from core.logger import logger
                    logger.warning(f"[VisualUnderstand] 子进程收到终止信号 {signum}，正在清理资源")
                    sys.exit(1)

                signal.signal(signal.SIGTERM, signal_handler)
                signal.signal(signal.SIGINT, signal_handler)
            except Exception:
                pass  # Windows可能不支持某些信号

class IconRecognize(BaseTool):
    """
    图标识别工具 - 基于视觉理解的图标定位
    """
    tool_id = "icon_recognize"
    name = "图标识别"
    description = "识别屏幕上的图标（视觉理解+模板匹配双保险）"
    input_schema = {
        "type": "object",
        "properties": {
            "icon_name": {
                "type": "string",
                "description": "图标名称（如'微信','设置'）"
            },
            "use_template": {
                "type": "boolean",
                "default": True,
                "description": "是否优先使用模板匹配（更精确）"
            }
        },
        "required": ["icon_name"]
    }

    async def _execute_async(self, **kwargs) -> dict:
        """异步执行图标识别"""
        icon_name = kwargs.get("icon_name")
        use_template = kwargs.get("use_template", True)

        # 方案1：模板匹配（如果存在模板，更精确）
        if use_template:
            from core.tool_manager import tool_manager
            match_tool = tool_manager.get_tool("template_match")

            if match_tool:
                template_path = f"templates/{icon_name}.png"
                result = match_tool.run(
                    template_path=template_path,
                    threshold=0.75
                )
                if result.get("success"):
                    return {
                        "success": True,
                        "data": {
                            "method": "template_match",
                            "icon": icon_name,
                            "position": result["data"]["best_match"]["center"],
                            "confidence": result["data"]["best_match"]["confidence"]
                        }
                    }

        # 方案2：视觉理解
        from core.tool_manager import tool_manager
        visual_tool = tool_manager.get_tool("visual_understand")

        if visual_tool:
            question = f"在屏幕上找到'{icon_name}'图标或按钮，告诉我它的中心坐标（格式：x=数字, y=数字）"
            result = await visual_tool.run_async(
                image_source="screenshot",
                question=question
            )
            return result

        return format_error(
            TOOL_EXECUTION_ERROR,
            detail=f"无法识别图标: {icon_name}"
        )

    def _execute(self, **kwargs) -> dict:
        """同步桥接到异步实现"""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            future = asyncio.run_coroutine_threadsafe(self._execute_async(**kwargs), loop)
            return future.result(timeout=60)
        except RuntimeError:
            return asyncio.run(self._execute_async(**kwargs))
