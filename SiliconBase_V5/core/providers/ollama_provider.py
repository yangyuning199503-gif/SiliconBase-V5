#!/usr/bin/env python3
"""
Ollama Provider - 本地模型支持
【2026-03-11 紧急修复版】修复AI返回空内容问题
"""

import asyncio
import contextlib
import json
import threading
import time
from typing import Any

import aiohttp
import requests

from core.logger import logger

from .base import (
    AIProvider,
    ProviderCapabilities,
    ProviderConfigError,
    ProviderNotAvailableError,
    VisionCapabilityMixin,
)


class ProviderOutputTruncatedError(ProviderNotAvailableError):
    """模型输出被 max_tokens / num_predict 截断，需要上层增加 token 限制后重试。"""
    pass


class OllamaProvider(AIProvider, VisionCapabilityMixin):
    """Ollama后端实现 - 兼容原有ai_client，支持视觉能力"""

    # 【P0-锁分离】按模型类型分锁：文本锁和视觉锁分离，避免视觉调用阻塞文本调用
    _text_lock = threading.Lock()
    _vision_lock = threading.Lock()

    # 【P0-事件循环修复】不再使用类级 asyncio.Lock，因为 asyncio.Lock 会绑定到创建它的事件循环。
    # 改为复用同步锁，通过 asyncio.to_thread 获取，避免跨事件循环冲突。

    # 支持视觉的模型列表
    VISION_MODELS = [
        "qwen3-vl", "qwen2-vl", "qwen-vl",
        "llava", "llava-next", "llama3.2-vision",
        "bakllava", "moondream"
    ]

    @classmethod
    def _is_vision_model(cls, model_name: str | None = None) -> bool:
        """根据模型名称判断是否属于视觉模型，统一使用 VISION_MODELS 列表判定"""
        if not model_name:
            return False
        model_lower = model_name.lower()
        return any(vm in model_lower for vm in cls.VISION_MODELS)

    @classmethod
    def _get_lock_for_model(cls, model_name: str | None = None) -> threading.Lock:
        """根据模型名称返回对应的锁：视觉模型用 _vision_lock，其他用 _text_lock"""
        if cls._is_vision_model(model_name):
            return cls._vision_lock
        return cls._text_lock

    async def _acquire_ollama_lock(self, model_name: str | None = None, timeout: float = 120.0):
        """在线程池中获取同步锁，不阻塞事件循环"""
        import functools
        lock = self._get_lock_for_model(model_name)
        acquired = await asyncio.to_thread(
            functools.partial(lock.acquire, timeout=timeout)
        )
        if not acquired:
            raise ProviderNotAvailableError("获取 Ollama 调用锁超时")
        return lock

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get("base_url", "http://localhost:11434").rstrip('/')
        self.model = config.get("model", "qwen3:8b")
        self.timeout = config.get("timeout", 120)
        self.retry_times = config.get("retry_times", 2)

        valid, error = self.validate_config()
        if not valid:
            raise ProviderConfigError(error)

        # 显存协调器集成
        try:
            from core.ai.model_coordinator import ModelType, get_model_coordinator
            self.coordinator = get_model_coordinator()
            # 根据模型类型判断
            model_lower = self.model.lower()
            if any(vm in model_lower for vm in self.VISION_MODELS):
                self.model_type = ModelType.VISION
            else:
                self.model_type = ModelType.TEXT
        except ImportError:
            self.coordinator = None
            self.model_type = None

    def get_capabilities(self) -> ProviderCapabilities:
        """返回Ollama Provider的能力声明"""
        # 检查当前模型是否支持视觉
        model_lower = self.model.lower()
        has_vision = any(vm in model_lower for vm in self.VISION_MODELS)

        return ProviderCapabilities(
            streaming=True,
            vision=has_vision,  # 根据模型决定是否支持视觉
            function_calling=False,
            max_context_length=32768
        )

    def validate_config(self) -> tuple[bool, str]:
        if not self.base_url:
            return False, "base_url不能为空"
        if not self.model:
            return False, "model不能为空"
        return True, ""

    def _diagnose_error(self, status_code: int, model_name: str) -> str:
        """诊断错误原因并返回友好的错误信息"""
        # 首先检查Ollama服务是否运行
        service_running = self.is_available()

        if not service_running:
            return (
                f"无法连接到 Ollama 服务 ({self.base_url})。\n"
                f"可能的原因：\n"
                f"1. Ollama 未启动，请运行: ollama serve\n"
                f"2. 配置的 base_url 不正确\n"
                f"3. 防火墙或网络问题"
            )

        # 服务运行中，获取可用模型
        try:
            available_models = self.get_model_list()
        except Exception as e:
            logger.warning(f"[OllamaProvider] 获取模型列表失败: {e}")
            available_models = []

        if status_code == 404:
            if available_models:
                model_list = ", ".join(available_models[:10])
                if len(available_models) > 10:
                    model_list += f" 等共 {len(available_models)} 个模型"
                return (
                    f"模型 '{model_name}' 不存在于 Ollama 中。\n"
                    f"可用模型: {model_list}\n"
                    f"\n解决方法：\n"
                    f"1. 安装该模型: ollama pull {model_name}\n"
                    f"2. 或在前端配置中选择其他可用模型"
                )
            else:
                return (
                    f"模型 '{model_name}' 不存在，且无法获取模型列表。\n"
                    f"解决方法：运行 'ollama pull {model_name}' 安装模型"
                )

        return f"Ollama 返回错误 (HTTP {status_code})"

    def generate(self, prompt: str, **kwargs) -> str | None:
        """单次生成 - 同样使用协调器"""
        # 复用chat的逻辑，自动获得协调器支持
        return self.chat([{"role": "user", "content": prompt}], **kwargs)

    def chat(self, messages: list[dict[str, str]], **kwargs) -> str | None:
        # 【P0-锁分离】根据模型类型获取对应锁，文本和视觉可并行
        model = kwargs.get("model", self.model)
        lock = self._get_lock_for_model(model)
        lock_type = "vision" if lock is self._vision_lock else "text"
        acquired = lock.acquire(timeout=120)
        if not acquired:
            logger.warning(f"[OllamaProvider] 获取{lock_type}锁超时，可能是前一个请求卡死")
            raise ProviderNotAvailableError("Ollama 正忙，前一个请求未结束，请稍后重试")

        try:
            # 显存协调：调用前请求加载（按当前调用模型动态计算类型）
            model_type = None
            if self.coordinator:
                try:
                    from core.ai.model_coordinator import ModelType
                    model_type = ModelType.VISION if self._is_vision_model(model) else ModelType.TEXT
                    print(f"[OllamaProvider] 请求显存协调: {model_type.value}")
                    self.coordinator.mark_active(model_type)
                except Exception as e:
                    print(f"[WARN] 显存协调失败: {e}")

            try:
                return self._do_chat(messages, **kwargs)
            finally:
                # 显存协调：调用完成后标记空闲
                if self.coordinator and model_type:
                    try:
                        self.coordinator.mark_idle(model_type)
                        print(f"[OllamaProvider] 显存释放: {model_type.value}")
                    except Exception as e:
                        print(f"[WARN] 显存释放标记失败: {e}")
        finally:
            lock.release()
            # 【P1-修复】视觉模型调用后只做短暂冷却，不再清空 CUDA 缓存。
            # 清空缓存会把文本模型也挤出显存，导致后续文本调用必须重新加载模型。
            if self._is_vision_model(model):
                time.sleep(0.5)
                logger.debug("[OllamaProvider] 视觉模型调用后冷却完成")

    async def chat_async(self, messages: list[dict[str, str]], **kwargs) -> str | None:
        """异步多轮对话 —— Phase 4 原生异步实现

        使用 aiohttp 直接发送异步 HTTP 请求，彻底消除 asyncio.to_thread 桥接。
        """
        _chat_start = time.time()
        logger.info(f"[TRACE] OllamaProvider.chat_async: 进入 | ts={_chat_start:.3f}")
        # 【P0-锁分离】根据模型类型获取对应锁，文本和视觉可并行
        model = kwargs.get("model", self.model)
        lock_type = "vision" if self._is_vision_model(model) else "text"
        _lock_wait_start = time.time()
        logger.info(f"[TRACE] OllamaProvider.chat_async: 获取{lock_type}锁前 | ts={_lock_wait_start:.3f}")
        _acquired_lock = await self._acquire_ollama_lock(model_name=model, timeout=120.0)
        _lock_wait_elapsed = time.time() - _lock_wait_start
        if _lock_wait_elapsed > 0.5:
            logger.warning(
                f"[TRACE] OllamaProvider: 等待{lock_type}锁 {_lock_wait_elapsed:.3f}s, "
                f"model={model}"
            )
        logger.info(
            f"[TRACE] OllamaProvider: chat_async 获得{lock_type}锁, "
            f"model={model}, ts={time.time():.3f}"
        )
        # 显存协调：调用前请求加载（按当前调用模型动态计算类型）
        model_type = None
        try:
            if self.coordinator:
                try:
                    from core.ai.model_coordinator import ModelType
                    model_type = ModelType.VISION if self._is_vision_model(model) else ModelType.TEXT
                    print(f"[OllamaProvider] 请求显存协调 (async): {model_type.value}")
                    self.coordinator.mark_active(model_type)
                except Exception as e:
                    print(f"[WARN] 显存协调失败 (async): {e}")

            return await self._do_chat_async(messages, **kwargs)
        finally:
            # 释放同步锁
            with contextlib.suppress(RuntimeError):
                _acquired_lock.release()  # 锁未被当前线程持有，忽略
            # 显存协调：调用完成后标记空闲
            if self.coordinator and model_type:
                try:
                    self.coordinator.mark_idle(model_type)
                    print(f"[OllamaProvider] 显存释放 (async): {model_type.value}")
                except Exception as e:
                    print(f"[WARN] 显存释放标记失败 (async): {e}")

            _chat_elapsed = time.time() - _chat_start
            logger.info(f"[TRACE] OllamaProvider.chat_async: 退出 | elapsed={_chat_elapsed:.3f}s")
            # 【P1-修复】视觉模型调用后只做短暂冷却，不再清空 CUDA 缓存。
            # 清空缓存会把文本模型也挤出显存，导致后续文本调用必须重新加载模型。
            # 12G 显存足以同时保持 qwen3:8b + qwen3-vl:2b，keep_alive 会负责维持。
            if self._is_vision_model(model):
                await asyncio.sleep(0.5)
                logger.debug("[OllamaProvider] 视觉模型调用后冷却完成")

    @staticmethod
    def _normalize_messages_for_ollama(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        将 OpenAI 兼容的视觉消息格式转换为 Ollama 原生 /api/chat 格式。

        Ollama /api/chat 要求：
        - messages[*].content 必须是字符串
        - 图片放在 messages[*].images 字段（base64 数组）

        如果传入的是 OpenAI 格式（content 为数组，包含 type=image_url），
        则提取文本和图片并转换，避免 400 错误。
        """
        normalized = []
        for msg in messages:
            if not isinstance(msg, dict):
                normalized.append(msg)
                continue

            content = msg.get("content")
            images = list(msg.get("images", []))

            if isinstance(content, list):
                text_parts = []
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    item_type = item.get("type")
                    if item_type == "text":
                        text_parts.append(str(item.get("text", "")))
                    elif item_type == "image_url":
                        image_url = item.get("image_url", {})
                        url = image_url.get("url", "") if isinstance(image_url, dict) else str(image_url)
                        if url.startswith("data:image") and ";base64," in url:
                            images.append(url.split(";base64,", 1)[1])
                        elif url:
                            # 非 data URL 的远程图片 Ollama 原生不支持，留空并记录警告
                            logger.warning(
                                f"[OllamaProvider] 忽略不支持的远程图片 URL: {url[:80]}..."
                            )
                content = "\n".join(text_parts)
            elif content is None:
                content = ""

            new_msg = {
                "role": msg.get("role", "user"),
                "content": content,
            }
            if images:
                new_msg["images"] = images
            normalized.append(new_msg)

        return normalized

    def _do_chat(self, messages: list[dict[str, str]], **kwargs) -> str | None:
        """
        【2026-03-11 紧急修复】修复AI返回空内容问题

        修复内容：
        1. 添加详细的请求/响应调试日志
        2. 检查Ollama响应中的done字段和错误信息
        3. 对qwen3系列模型优化参数
        4. 当响应为空时记录原始响应用于诊断
        5. 改进重试逻辑，处理临时性空响应
        """
        url = f"{self.base_url}/api/chat"
        model = kwargs.get("model", self.model)

        # 【P0修复】防御性转换：把 OpenAI 视觉格式转成 Ollama 原生格式
        messages = self._normalize_messages_for_ollama(messages)

        # 【修复】qwen3系列模型特殊处理：优化参数
        model_lower = model.lower()
        is_qwen3 = "qwen3" in model_lower

        # 【修复】构建payload，针对qwen3优化
        options = {
            "temperature": kwargs.get("temperature", 0.2),
            "num_predict": kwargs.get("max_tokens", 1024),  # 【P1修复】交易决策JSON需要更长输出
            "top_p": kwargs.get("top_p", 0.5),
            "top_k": kwargs.get("top_k", 20),
            "repeat_penalty": kwargs.get("repeat_penalty", 1.2),
        }

        # 【修复】qwen3系列模型需要调整参数（仅在没有显式传入时作为默认兜底）
        if is_qwen3:
            # qwen3对temperature更敏感，使用更保守的值
            options["temperature"] = max(0.1, min(options.get("temperature", 0.2), 0.8))
            # 增加num_predict确保有输出
            options["num_predict"] = max(options.get("num_predict", 256), 256)
            # 禁用一些可能导致空回复的选项；仅当用户没有显式传入 stop 时才覆盖
            if "stop" not in kwargs:
                options["stop"] = []

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": options
        }

        # 【关键修复】Qwen3 系列默认开启 thinking，小输出窗口下 thinking token 会占满预算导致空内容
        if is_qwen3:
            payload["think"] = False

        # 【P1-修复】所有模型都设置 keep_alive，避免文本/视觉模型在 GPU 上来回切换
        try:
            from core.config import config as _core_config
            keep_alive_seconds = _core_config.get("ollama.keep_alive_seconds", 1800)
        except Exception:
            keep_alive_seconds = 1800
        payload["keep_alive"] = keep_alive_seconds

        # 【调试日志】记录请求详情
        logger.debug(f"[OllamaProvider] 请求URL: {url}")
        logger.debug(f"[OllamaProvider] 请求模型: {model}")
        logger.debug(f"[OllamaProvider] 请求参数: {json.dumps(options, ensure_ascii=False)}")
        logger.debug(f"[OllamaProvider] 消息数量: {len(messages)}")

        last_error = None

        for attempt in range(self.retry_times + 1):
            try:
                # 【修复】增加连接超时时间，避免qwen3加载时的超时
                connect_timeout = 10 if attempt == 0 else 5

                # 【P0调试】只在首次尝试打印 Payload 摘要，避免重试时日志爆炸
                if attempt == 0:
                    content_preview = ""
                    if messages:
                        last_content = messages[-1].get("content", "")
                        content_preview = last_content[:200].replace("\n", " ") + "..." if len(last_content) > 200 else last_content.replace("\n", " ")
                    logger.info(
                        f"[OllamaProvider] 请求模型={model}, "
                        f"消息数={len(messages)}, "
                        f"最后消息预览={content_preview!r}"
                    )
                logger.debug(f"[OllamaProvider] 完整Payload: {json.dumps(payload, ensure_ascii=False)}")

                resp = requests.post(url, json=payload, timeout=(connect_timeout, self.timeout))

                # 处理HTTP错误
                if resp.status_code >= 400:
                    error_detail = self._diagnose_error(resp.status_code, model)
                    self._set_error(error_detail)
                    raise ProviderNotAvailableError(error_detail)

                resp.raise_for_status()

                # 【修复乱码问题】确保响应使用UTF-8编码
                resp.encoding = 'utf-8'

                # 【调试】记录原始响应文本
                raw_text = resp.text
                logger.debug(f"[OllamaProvider] 原始响应长度: {len(raw_text)}")

                try:
                    data = resp.json()
                except json.JSONDecodeError as e:
                    logger.error(f"[OllamaProvider] JSON解析失败: {e}")
                    logger.error(f"[OllamaProvider] 原始响应: {raw_text[:1000]}")
                    last_error = f"响应JSON解析失败: {e}"
                    continue

                # 【调试】记录完整响应结构
                logger.debug(f"[OllamaProvider] 响应数据结构: {list(data.keys())}")

                # 【修复】检查Ollama响应中的错误字段
                if "error" in data:
                    error_msg = data["error"]
                    logger.error(f"[OllamaProvider] Ollama返回错误: {error_msg}")
                    last_error = f"Ollama错误: {error_msg}"
                    if attempt < self.retry_times:
                        time.sleep(1.0 * (attempt + 1))
                        continue
                    raise ProviderNotAvailableError(f"Ollama错误: {error_msg}")

                # 【修复】检查done字段，确保生成已完成
                done = data.get("done", True)
                if not done:
                    logger.warning("[OllamaProvider] 响应标记为未完成 (done=false)")

                # 【修复】提取内容，增加更多的容错处理
                message_obj = data.get("message")
                if message_obj is None:
                    logger.error("[OllamaProvider] 响应中缺少message字段")
                    logger.error(f"[OllamaProvider] 完整响应: {json.dumps(data, ensure_ascii=False)[:1000]}")
                    last_error = "响应格式错误：缺少message字段"
                    if attempt < self.retry_times:
                        time.sleep(1.0 * (attempt + 1))
                        continue
                    return None

                content = message_obj.get("content")
                thinking = message_obj.get("thinking") or ""
                thinking = thinking.strip() if isinstance(thinking, str) else ""

                # 【调试】记录content类型和值
                logger.debug(f"[OllamaProvider] content类型: {type(content)}")
                logger.debug(f"[OllamaProvider] content值: {repr(content) if content else 'None/Empty'}")

                # 【修复】处理内容为空的情况
                if content is None:
                    logger.error("[OllamaProvider] message.content为None")
                    logger.error(f"[OllamaProvider] message对象: {json.dumps(message_obj, ensure_ascii=False)[:500]}")
                    last_error = "响应内容为空(None)"
                    if attempt < self.retry_times:
                        time.sleep(1.0 * (attempt + 1))
                        continue
                    return None

                # 【修复】处理内容为字符串的情况
                if isinstance(content, str):
                    content = content.strip()
                    if not content:
                        logger.warning("[OllamaProvider] 响应内容为空字符串")
                        # 【P0修复】Qwen3等思考模型可能把回复放在 thinking 字段
                        if thinking:
                            logger.info(f"[OllamaProvider] 从thinking字段提取内容（长度 {len(thinking)}）")
                            content = thinking
                        elif "response" in data and data["response"]:
                            content = data["response"].strip()
                            logger.info("[OllamaProvider] 从response字段提取内容")
                        else:
                            last_error = "响应内容为空字符串"
                            if attempt < self.retry_times:
                                time.sleep(1.0 * (attempt + 1))
                                continue
                            return None
                    elif thinking and all(ch == '\ufffd' or ch.isspace() for ch in content):
                        # 内容全是乱码（替换字符/空白）时，尝试使用 thinking
                        logger.warning("[OllamaProvider] 响应content为乱码，尝试使用thinking字段")
                        content = thinking
                elif isinstance(content, bytes):
                    content = content.decode('utf-8', errors='replace').strip()
                else:
                    content = str(content).strip()

                # 【调试】记录成功提取的内容
                logger.info(f"[OllamaProvider] AI原始响应: {content[:500]}")
                return content

            except requests.exceptions.Timeout as e:
                last_error = f"AI响应超时（{self.timeout}秒），模型可能正在思考或负载过高，请稍后重试"
                logger.warning(f"[OllamaProvider] 超时 (尝试 {attempt + 1}/{self.retry_times + 1}): {e}")
            except requests.exceptions.ConnectionError as e:
                last_error = f"连接错误: {e}"
                logger.warning(f"[OllamaProvider] 连接失败 (尝试 {attempt + 1})")
            except ProviderNotAvailableError:
                raise  # 直接抛出已诊断的错误
            except Exception as e:
                last_error = f"未知错误: {e}"
                logger.error(f"[OllamaProvider] 错误: {e}", exc_info=True)

            if attempt < self.retry_times:
                sleep_time = 1.0 * (attempt + 1)
                logger.info(f"[OllamaProvider] 等待{sleep_time}秒后重试...")
                time.sleep(sleep_time)

        # 最终失败，给出综合诊断
        final_error = self._diagnose_error(0, model) if not self.is_available() else f"调用Ollama失败: {last_error}"
        self._set_error(final_error)
        raise ProviderNotAvailableError(final_error)

    async def _ensure_model_loaded_async(self, model: str) -> bool:
        """【P1修复】检查Ollama是否已加载目标模型，未加载则等待

        调用 /api/ps 获取已加载模型列表，如果目标模型不在列表中，
        说明模型可能正在加载或未被加载，返回False让上层等待后重试。
        """
        try:
            client_timeout = aiohttp.ClientTimeout(connect=2, total=5)
            async with aiohttp.ClientSession(timeout=client_timeout) as session, session.get(f"{self.base_url}/api/ps") as resp:
                    if resp.status != 200:
                        logger.debug("[OllamaProvider] /api/ps 不可用，跳过模型加载检查")
                        return True  # 降级：跳过检查
                    data = await resp.json()
                    loaded_models = [m.get("name", "") for m in data.get("models", [])]
                    # 精确匹配模型名（兼容带 tag 与不带 tag 的命名）
                    for loaded in loaded_models:
                        if loaded == model or loaded.startswith(model + ":"):
                            return True
                    logger.warning(
                        f"[OllamaProvider] 模型 {model} 尚未加载到GPU，"
                        f"已加载模型: {loaded_models}"
                    )
                    return False
        except Exception as e:
            logger.debug(f"[OllamaProvider] 模型加载检查失败，降级跳过: {e}")
            return True  # 降级：跳过检查

    async def _do_chat_async(self, messages: list[dict[str, str]], **kwargs) -> str | None:
        """
        【Phase 4 原生异步】修复AI返回空内容问题

        与 _do_chat 逻辑完全一致，但使用 aiohttp 实现原生异步 HTTP，
        彻底消除 run_in_executor / asyncio.to_thread 桥接。

        【P0修复】空响应处理增强：
        - content为None或空字符串时统一走重试逻辑
        - 重试耗尽后记录ERROR日志，返回None

        【P1修复】模型预热检查：
        - 每次请求前调用/api/ps检查模型加载状态
        - 模型未加载时等待5秒后重试
        """
        url = f"{self.base_url}/api/chat"
        model = kwargs.get("model", self.model)

        # 【P0修复】防御性转换：把 OpenAI 视觉格式转成 Ollama 原生格式
        messages = self._normalize_messages_for_ollama(messages)

        # 【修复】qwen3系列模型特殊处理：优化参数
        model_lower = model.lower()
        is_qwen3 = "qwen3" in model_lower

        # 【修复】构建payload，针对qwen3优化
        options = {
            "temperature": kwargs.get("temperature", 0.2),
            "num_predict": kwargs.get("max_tokens", 1024),
            "top_p": kwargs.get("top_p", 0.5),
            "top_k": kwargs.get("top_k", 20),
            "repeat_penalty": kwargs.get("repeat_penalty", 1.2),
        }

        # 【修复】qwen3系列模型需要调整参数（仅在没有显式传入时作为默认兜底）
        if is_qwen3:
            options["temperature"] = max(0.1, min(options.get("temperature", 0.2), 0.8))
            options["num_predict"] = max(options.get("num_predict", 256), 256)
            if "stop" not in kwargs:
                options["stop"] = []

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": options
        }

        # 【关键修复】Qwen3 系列默认开启 thinking，小输出窗口下 thinking token 会占满预算导致空内容
        if is_qwen3:
            payload["think"] = False

        # 【P1-修复】所有模型都设置 keep_alive，避免文本/视觉模型在 GPU 上来回切换
        # 默认保持 30 分钟，可通过配置 ollama.keep_alive_seconds 调整
        try:
            from core.config import config as _core_config
            keep_alive_seconds = _core_config.get("ollama.keep_alive_seconds", 1800)
        except Exception:
            keep_alive_seconds = 1800
        payload["keep_alive"] = keep_alive_seconds

        logger.debug(f"[OllamaProvider] 异步请求URL: {url}")
        logger.debug(f"[OllamaProvider] 异步请求模型: {model}")
        logger.debug(f"[OllamaProvider] 异步请求参数: {json.dumps(options, ensure_ascii=False)}")
        logger.debug(f"[OllamaProvider] 异步消息数量: {len(messages)}")

        last_error = None

        for attempt in range(self.retry_times + 1):
            try:
                connect_timeout = 10 if attempt == 0 else 5

                if attempt == 0:
                    content_preview = ""
                    if messages:
                        last_content = messages[-1].get("content", "")
                        content_preview = last_content[:200].replace("\n", " ") + "..." if len(last_content) > 200 else last_content.replace("\n", " ")
                    logger.info(
                        f"[OllamaProvider] 异步请求模型={model}, "
                        f"消息数={len(messages)}, "
                        f"最后消息预览={content_preview!r}"
                    )
                logger.debug(f"[OllamaProvider] 异步完整Payload: {json.dumps(payload, ensure_ascii=False)}")

                # 【P1修复】模型预热检查：确保模型已加载到GPU
                if attempt == 0:
                    model_loaded = await self._ensure_model_loaded_async(model)
                    if not model_loaded:
                        last_error = f"模型 {model} 尚未加载到GPU"
                        logger.warning(
                            "[OllamaProvider] 模型未加载，等待5秒后重试..."
                        )
                        await asyncio.sleep(5)
                        # 不continue，继续尝试请求（模型可能在加载中）

                client_timeout = aiohttp.ClientTimeout(connect=connect_timeout, total=self.timeout)

                _post_start = time.time()
                logger.info(
                    f"[TRACE] OllamaProvider: session.post 开始, "
                    f"model={model}, timeout={self.timeout}, ts={_post_start:.3f}"
                )
                async with aiohttp.ClientSession(timeout=client_timeout) as session, session.post(url, json=payload) as resp:
                        _post_elapsed = time.time() - _post_start
                        logger.info(
                            f"[TRACE] OllamaProvider: session.post 首字节, "
                            f"model={model}, status={resp.status}, elapsed={_post_elapsed:.3f}s"
                        )
                        # 处理HTTP错误
                        if resp.status >= 400:
                            error_detail = await self._diagnose_error_async(resp.status, model)
                            self._set_error(error_detail)
                            raise ProviderNotAvailableError(error_detail)

                        # 获取响应文本
                        raw_text = await resp.text()
                        logger.debug(f"[OllamaProvider] 异步原始响应长度: {len(raw_text)}")

                        try:
                            data = await resp.json()
                        except Exception as e:
                            logger.error(f"[OllamaProvider] 异步JSON解析失败: {e}")
                            logger.error(f"[OllamaProvider] 异步原始响应: {raw_text[:1000]}")
                            last_error = f"响应JSON解析失败: {e}"
                            continue

                        logger.debug(f"[OllamaProvider] 异步响应数据结构: {list(data.keys())}")

                        if "error" in data:
                            error_msg = data["error"]
                            logger.error(f"[OllamaProvider] Ollama返回错误: {error_msg}")
                            last_error = f"Ollama错误: {error_msg}"
                            if attempt < self.retry_times:
                                await asyncio.sleep(1.0 * (attempt + 1))
                                continue
                            raise ProviderNotAvailableError(f"Ollama错误: {error_msg}")

                        done = data.get("done", True)
                        if not done:
                            logger.warning("[OllamaProvider] 异步响应标记为未完成 (done=false)")

                        # 【P0修复】增强空响应诊断日志
                        eval_count = data.get("eval_count", -1)
                        done_reason = data.get("done_reason", "unknown")
                        load_duration = data.get("load_duration", 0)

                        message_obj = data.get("message")
                        if message_obj is None:
                            logger.error(
                                f"[OllamaProvider] 异步响应中缺少message字段，"
                                f"eval_count={eval_count}, done_reason={done_reason}, "
                                f"load_duration={load_duration}ms"
                            )
                            logger.error(f"[OllamaProvider] 异步完整响应: {json.dumps(data, ensure_ascii=False)[:1000]}")
                            last_error = "响应格式错误：缺少message字段"
                            if attempt < self.retry_times:
                                await asyncio.sleep(1.0 * (attempt + 1))
                                continue
                            logger.error(f"[OllamaProvider] 异步空响应，所有{self.retry_times + 1}次重试已耗尽")
                            return None

                        content = message_obj.get("content")
                        thinking = message_obj.get("thinking") or ""
                        thinking = thinking.strip() if isinstance(thinking, str) else ""

                        logger.debug(f"[OllamaProvider] 异步content类型: {type(content)}")
                        logger.debug(f"[OllamaProvider] 异步content值: {repr(content) if content else 'None/Empty'}")

                        if content is None:
                            logger.error(
                                f"[OllamaProvider] 异步message.content为None，"
                                f"eval_count={eval_count}, done_reason={done_reason}"
                            )
                            logger.error(f"[OllamaProvider] 异步message对象: {json.dumps(message_obj, ensure_ascii=False)[:500]}")
                            last_error = "响应内容为空(None)"
                            if attempt < self.retry_times:
                                await asyncio.sleep(1.0 * (attempt + 1))
                                continue
                            logger.error(f"[OllamaProvider] 异步空响应(None)，所有{self.retry_times + 1}次重试已耗尽")
                            return None

                        if isinstance(content, str):
                            content = content.strip()
                            if not content:
                                logger.warning(
                                    f"[OllamaProvider] 异步响应内容为空字符串，"
                                    f"eval_count={eval_count}, done_reason={done_reason}, "
                                    f"load_duration={load_duration}ms"
                                )
                                # 【P0修复】Qwen3等思考模型可能把回复放在 thinking 字段
                                if thinking:
                                    logger.info(f"[OllamaProvider] 异步从thinking字段提取内容（长度 {len(thinking)}）")
                                    content = thinking
                                # 【P0修复】区分输出截断与真正空响应
                                elif done_reason == "length":
                                    logger.warning(
                                        "[OllamaProvider] 视觉模型输出超长被截断 (done_reason=length)，"
                                        "建议增加 max_tokens"
                                    )
                                    raise ProviderOutputTruncatedError(
                                        f"视觉模型输出被截断，eval_count={eval_count}"
                                    )
                                # 【修复】检查是否有其他字段包含内容
                                elif "response" in data and data["response"]:
                                    content = data["response"].strip()
                                    logger.info("[OllamaProvider] 异步从response字段提取内容")
                                else:
                                    last_error = "响应内容为空字符串"
                                    if attempt < self.retry_times:
                                        await asyncio.sleep(1.0 * (attempt + 1))
                                        continue
                                    logger.error(f"[OllamaProvider] 异步空响应(空字符串)，所有{self.retry_times + 1}次重试已耗尽")
                                    return None
                            elif thinking and all(ch == '\ufffd' or ch.isspace() for ch in content):
                                # 内容全是乱码（替换字符/空白）时，尝试使用 thinking
                                logger.warning("[OllamaProvider] 异步响应content为乱码，尝试使用thinking字段")
                                content = thinking
                        elif isinstance(content, bytes):
                            content = content.decode('utf-8', errors='replace').strip()
                        else:
                            content = str(content).strip()

                        _total_elapsed = time.time() - _post_start
                        logger.info(
                            f"[TRACE] OllamaProvider: session.post 完成, "
                            f"model={model}, total_elapsed={_total_elapsed:.3f}s, "
                            f"content_len={len(content)}, load_duration={load_duration}ms"
                        )
                        logger.info(f"[OllamaProvider] 异步AI原始响应: {content[:500]}")
                        return content

            except asyncio.TimeoutError as e:
                last_error = f"AI响应超时（{self.timeout}秒），模型可能正在思考或负载过高，请稍后重试"
                logger.warning(f"[OllamaProvider] 异步超时 (尝试 {attempt + 1}/{self.retry_times + 1}): {e}")
            except aiohttp.ClientConnectionError as e:
                last_error = f"连接错误: {e}"
                logger.warning(f"[OllamaProvider] 异步连接失败 (尝试 {attempt + 1})")
            except ProviderNotAvailableError:
                raise
            except Exception as e:
                last_error = f"未知错误: {e}"
                logger.error(f"[OllamaProvider] 异步错误: {e}", exc_info=True)

            if attempt < self.retry_times:
                sleep_time = 1.0 * (attempt + 1)
                logger.info(f"[OllamaProvider] 异步等待{sleep_time}秒后重试...")
                await asyncio.sleep(sleep_time)

        # 最终失败，给出综合诊断
        is_svc_available = await self.is_available_async()
        final_error = await self._diagnose_error_async(0, model) if not is_svc_available else f"调用Ollama失败: {last_error}"
        self._set_error(final_error)
        raise ProviderNotAvailableError(final_error)

    async def _diagnose_error_async(self, status_code: int, model_name: str) -> str:
        """诊断错误原因并返回友好的错误信息（异步版本）"""
        service_running = await self.is_available_async()

        if not service_running:
            return (
                f"无法连接到 Ollama 服务 ({self.base_url})。\n"
                f"可能的原因：\n"
                f"1. Ollama 未启动，请运行: ollama serve\n"
                f"2. 配置的 base_url 不正确\n"
                f"3. 防火墙或网络问题"
            )

        try:
            available_models = await self.get_model_list_async()
        except Exception as e:
            logger.warning(f"[OllamaProvider] 异步获取模型列表失败: {e}")
            available_models = []

        if status_code == 404:
            if available_models:
                model_list = ", ".join(available_models[:10])
                if len(available_models) > 10:
                    model_list += f" 等共 {len(available_models)} 个模型"
                return (
                    f"模型 '{model_name}' 不存在于 Ollama 中。\n"
                    f"可用模型: {model_list}\n"
                    f"\n解决方法：\n"
                    f"1. 安装该模型: ollama pull {model_name}\n"
                    f"2. 或在前端配置中选择其他可用模型"
                )
            else:
                return (
                    f"模型 '{model_name}' 不存在，且无法获取模型列表。\n"
                    f"解决方法：运行 'ollama pull {model_name}' 安装模型"
                )

        return f"Ollama 返回错误 (HTTP {status_code})"

    def is_available(self) -> bool:
        # 【修复】增加超时时间到2秒，避免模型加载期间误判为不可用
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=2)
            return resp.status_code == 200
        except Exception as e:
            logger.debug(f"[OllamaProvider] 服务可用性检查失败: {e}")
            return False

    async def is_available_async(self) -> bool:
        """异步检查Ollama服务是否可用"""
        try:
            client_timeout = aiohttp.ClientTimeout(connect=2, total=5)
            async with aiohttp.ClientSession(timeout=client_timeout) as session, session.get(f"{self.base_url}/api/tags") as resp:
                return resp.status == 200
        except Exception as e:
            logger.debug(f"[OllamaProvider] 异步服务可用性检查失败: {e}")
            return False

    def get_model_list(self) -> list[str]:
        # 使用短超时，避免阻塞API
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=2)
            resp.raise_for_status()
            data = resp.json()
            models = [m.get("name") for m in data.get("models", [])]
            if models:
                return models
        except Exception as e:
            logger.warning(f"[OllamaProvider] 获取模型列表失败: {e}")

        # 返回常用默认模型，避免前端等待，并支持用户自定义输入
        return [
            # Qwen3系列（推荐）
            "qwen3:8b", "qwen3:4b", "qwen3:14b", "qwen3:32b",
            # Qwen2.5系列
            "qwen2.5:7b", "qwen2.5:14b", "qwen2.5:32b", "qwen2.5:72b",
            # 视觉模型
            "qwen3-vl:8b", "qwen2-vl:7b", "llava:13b", "llava:7b", "llama3.2-vision",
            # Llama系列
            "llama3.1:8b", "llama3.2:3b", "llama3:8b",
            # 代码模型
            "qwen2.5-coder:7b", "qwen2.5-coder:14b", "deepseek-coder:6.7b",
            # 其他常用模型
            "phi4", "gemma2:9b", "mistral:7b", "codellama:7b"
        ]

    async def get_model_list_async(self) -> list[str]:
        """异步获取可用模型列表"""
        try:
            client_timeout = aiohttp.ClientTimeout(connect=2, total=5)
            async with aiohttp.ClientSession(timeout=client_timeout) as session, session.get(f"{self.base_url}/api/tags") as resp:
                if resp.status != 200:
                    logger.warning(f"[OllamaProvider] 异步获取模型列表返回非200: {resp.status}")
                    return self._get_default_model_list()
                data = await resp.json()
                models = [m.get("name") for m in data.get("models", [])]
                if models:
                    return models
        except Exception as e:
            logger.warning(f"[OllamaProvider] 异步获取模型列表失败: {e}")

        return self._get_default_model_list()

    def _get_default_model_list(self) -> list[str]:
        """返回默认模型列表"""
        return [
            # Qwen3系列（推荐）
            "qwen3:8b", "qwen3:4b", "qwen3:14b", "qwen3:32b",
            # Qwen2.5系列
            "qwen2.5:7b", "qwen2.5:14b", "qwen2.5:32b", "qwen2.5:72b",
            # 视觉模型
            "qwen3-vl:8b", "qwen2-vl:7b", "llava:13b", "llava:7b", "llama3.2-vision",
            # Llama系列
            "llama3.1:8b", "llama3.2:3b", "llama3:8b",
            # 代码模型
            "qwen2.5-coder:7b", "qwen2.5-coder:14b", "deepseek-coder:6.7b",
            # 其他常用模型
            "phi4", "gemma2:9b", "mistral:7b", "codellama:7b"
        ]

    def get_config(self) -> dict[str, Any]:
        return {
            "provider": "ollama",
            "base_url": self.base_url,
            "model": self.model,
            "timeout": self.timeout,
            "vision_capable": self.get_capabilities().vision,
        }

    # ========== 视觉能力特定方法 ==========

    def prepare_vision_messages(self, text: str, image_b64: str, mime_type: str = "image/jpeg") -> list[dict]:
        """
        为Ollama准备支持视觉的messages格式

        Ollama使用OpenAI兼容的视觉格式：
        {
            "role": "user",
            "content": "描述图片",
            "images": ["base64_encoded_image"]
        }
        """
        return [{
            "role": "user",
            "content": text,
            "images": [image_b64]
        }]
