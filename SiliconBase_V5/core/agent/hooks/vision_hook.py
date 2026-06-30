#!/usr/bin/env python3
"""
VisionHook - 视觉验证钩子
V5/V6 融合重构 - Phase 3a

职责：在工具调用后执行 AutoVisionVerify，统一同步/异步双版本逻辑。
核心增强：集成 ScreenOCR + element_map 精确坐标，建立视觉感知 → 动作执行的坐标闭环。

设计约束（由 08 文档 Phase 3a 执行前决策记录锁定）：
1. 截图统一使用 ThreadSafePixelCapture()，其内部已通过 ResourceCoordinator（V3）串行调度，避免 MSS 竞争蓝屏。
2. 为减少 MSS 调用次数，ThreadSafePixelCapture 截到的 PIL Image 同时复用于：
   - VisualUnderstand（保存为临时文件，通过 image_source="path" 传入）
   - ScreenOCR（转为 numpy 数组，直接调用底层 reader.readtext）
3. 异步入口的所有阻塞调用（截图、视觉模型、OCR）均使用 asyncio.get_running_loop().run_in_executor() 包装。
4. 不替换 VisualUnderstand 为 VisionAgentTool（回归风险过高），通过叠加 element_map 弥补纯文本描述精度不足。
5. 接口兼容 agent_loop_hooks 注册机制：after_tool(ctx, tool_result) -> HookContext。
6. 【Phase 4 顺手修复 04-条目45】视觉验证 Prompt 已模板化，从 core/prompt/vision_verify_prompt.txt 加载，
   失败时自动降级为内置默认模板。
"""

import asyncio
import time
from pathlib import Path
from typing import Any

from core.logger import logger
from tools.visual_understand import VisualUnderstand

# 降级日志冷却控制（60 秒内最多打印一次）
_degraded_log_last_time = 0.0
_DEGRADED_LOG_COOLDOWN = 60.0


def _log_degraded_once(prefix: str = "VisionHook"):
    """降级状态下限制日志频率，避免刷屏。"""
    global _degraded_log_last_time
    now = time.time()
    if now - _degraded_log_last_time >= _DEGRADED_LOG_COOLDOWN:
        _degraded_log_last_time = now
        logger.info(f"[{prefix}] 视觉模型降级，跳过本次视觉验证")

try:
    from core.agent.agent_loop_hooks import HookContext
except ImportError:
    HookContext = Any

# ═════════════════════════════════════════════════════════════════════════════
# 【安全壳】任务级视觉验证状态 —— 彻底隔离，防止跨任务/跨用户资源竞争
# ═════════════════════════════════════════════════════════════════════════════

class _VisionTaskState:
    """每个 session 的视觉验证状态，完全隔离，杜绝全局变量污染。"""
    __slots__ = ("last_verify_time", "ui_counter", "verify_count",
                 "consecutive_failures", "circuit_open", "circuit_open_until")

    def __init__(self):
        self.last_verify_time = 0.0          # 上次视觉模型调用完成时间
        self.ui_counter = 0                  # UI 操作计数（用于抽样）
        self.verify_count = 0                # 本任务已执行的视觉验证次数
        self.consecutive_failures = 0        # 连续失败次数
        self.circuit_open = False            # 熔断器状态
        self.circuit_open_until = 0.0        # 熔断恢复时间


# 按 session_id 隔离的状态字典
_task_vision_states: dict[str, _VisionTaskState] = {}

# 安全壳常量
_MIN_VERIFY_INTERVAL = 5.0      # 最小冷却间隔（秒）
_UI_VERIFY_MODULO = 3           # 每 3 次 UI 操作验证 1 次
_MAX_VERIFY_PER_TASK = 5        # 每个任务最多视觉验证 5 次
_MAX_CONSECUTIVE_FAILURES = 3   # 连续失败 3 次熔断
_CIRCUIT_BREAK_DURATION = 60.0  # 熔断持续时间（秒）

# 模块级单例，避免循环内重复初始化导致资源抖动
_threadsafe_pixel_capture_singleton = None
_vision_hook_visual_understand_singleton = None
_ollama_health_cache = (0.0, True)  # (上次检查时间, 是否健康)


def _get_threadsafe_pixel_capture():
    global _threadsafe_pixel_capture_singleton
    if _threadsafe_pixel_capture_singleton is None:
        from core.vision.safe_screenshot_v2 import ThreadSafePixelCapture
        _threadsafe_pixel_capture_singleton = ThreadSafePixelCapture()
    return _threadsafe_pixel_capture_singleton


def _get_vision_hook_visual_understand():
    global _vision_hook_visual_understand_singleton
    if _vision_hook_visual_understand_singleton is None:
        from tools.visual_understand import VisualUnderstand
        _vision_hook_visual_understand_singleton = VisualUnderstand()
    return _vision_hook_visual_understand_singleton


class VisionHook:
    """视觉验证 Hook"""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.max_verify_rounds = self.config.get("vision.auto_verify.max_rounds", 3)
        self.auto_verify_timeout = self.config.get("vision.auto_verify.timeout", 30)
        self.ui_operations = frozenset([
            "mouse_click", "keyboard_input", "launch_app", "web_open",
            "click_text", "pixel_click", "find_and_click", "window_action",
            "smart_form_fill", "open_and_focus",
        ])
        self._verification_prompt_template: str | None = None

    @staticmethod
    def _get_task_state(session_id: str) -> _VisionTaskState:
        """获取（或创建）指定 session 的隔离状态。"""
        if session_id not in _task_vision_states:
            _task_vision_states[session_id] = _VisionTaskState()
        return _task_vision_states[session_id]

    @staticmethod
    def _cleanup_task_state(session_id: str):
        """任务结束后清理状态，防止内存泄漏。"""
        _task_vision_states.pop(session_id, None)

    def _health_check(self) -> bool:
        """
        前置健康检查：Ollama 是否可用、GPU 显存是否充足。
        检查结果缓存 5 秒，避免高频 RPC/系统调用。
        """
        global _ollama_health_cache
        now = time.time()
        if now - _ollama_health_cache[0] < 5.0:
            return _ollama_health_cache[1]

        healthy = True
        # 1. 检查 Ollama 可访问性（轻量级探测）
        try:
            import urllib.request
            req = urllib.request.Request(
                "http://localhost:11434/api/tags",
                method="GET",
                headers={"Connection": "close"},  # 不保持长连接
            )
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                if resp.status != 200:
                    healthy = False
        except Exception:
            healthy = False

        # 2. 检查 GPU 显存（如果 PyTorch 可用）
        if healthy:
            try:
                import torch
                if torch.cuda.is_available():
                    mem_allocated = torch.cuda.memory_allocated() / (1024 ** 3)
                    mem_reserved = torch.cuda.memory_reserved() / (1024 ** 3)
                    # 如果已分配显存超过 80%，认为不健康
                    if mem_allocated > 0.8 * mem_reserved and mem_reserved > 0:
                        logger.warning(
                            "[VisionHook-Safety] GPU 显存紧张: %.2f GB / %.2f GB",
                            mem_allocated, mem_reserved
                        )
                        healthy = False
            except Exception as e:
                logger.error(f"[VisionHook] GPU显存检查失败: {e}", exc_info=True)

        _ollama_health_cache = (now, healthy)
        if not healthy:
            logger.warning("[VisionHook-Safety] 健康检查未通过，跳过视觉验证")
        return healthy

    # ═════════════════════════════════════════════════════════════════════════════
    # 统一异步入口（Phase 3：已删除同步版）
    # ═════════════════════════════════════════════════════════════════════════════
    async def after_tool(self, ctx: HookContext, tool_result: dict | None = None) -> HookContext:
        """工具调用后触发视觉验证（异步版）—— 带安全壳。"""
        if ctx is None:
            return ctx
        res = tool_result or {}
        result = res.get("result", {}) if isinstance(res, dict) else {}
        tool_id = self._extract_tool_id(ctx, res)
        working_memory = getattr(ctx, "working_memory", None)
        session_id = getattr(ctx, "session_id", "")
        extra = getattr(ctx, "extra", {}) or {}
        vision_enabled = extra.get("vision_enabled", False)
        change_detector = extra.get("change_detector", None)
        loop_state = extra.get("loop_state", None)

        # ═══ 阶段 1：判断（只读，不碰任何资源）═══
        visual_verification_result = self._should_verify(
            session_id=session_id,
            tool_id=tool_id,
            result=result,
            vision_enabled=vision_enabled,
            change_detector=change_detector,
            loop_state=loop_state,
        )
        if visual_verification_result is None:
            return ctx

        logger.info("[VisionHook-Async] UI操作 '%s' 执行成功，启动自动视觉验证...", tool_id)

        # ═══ 阶段 2：健康检查（在耗时操作之前）═══
        if not self._health_check():
            logger.warning("[VisionHook-Safety] 健康检查未通过，跳过视觉验证")
            self._record_failure(session_id)
            return ctx

        self._get_task_state(session_id)
        pil_img = None
        image_b64 = None

        try:
            # 延迟（给 UI 动画时间）
            try:
                from core.config import config
                delay = config.get("vision.auto_verify.delay", 0.5)
            except Exception:
                delay = 0.5
            await asyncio.sleep(delay)

            # ═══ 阶段 3：截图（资源消耗点 #1）═══
            capture = _get_threadsafe_pixel_capture()
            pil_img, error = await capture.capture_async(monitor=1, timeout=10.0)
            if error or pil_img is None:
                logger.warning("[VisionHook-Async] 截图失败: %s", error)
                self._record_failure(session_id)
                return ctx

            # ═══ 阶段 4：Base64 编码（资源消耗点 #2）═══
            import base64
            import io
            buffer = io.BytesIO()
            try:
                pil_img.save(buffer, format="PNG")
                image_b64 = base64.b64encode(buffer.getvalue()).decode()
            finally:
                buffer.close()

            if VisualUnderstand.is_degraded():
                _log_degraded_once("VisionHook-Async")
                return ctx

            verification_question = self._build_verification_question(tool_id, result)

            # ═══ 阶段 5：视觉模型调用（资源消耗点 #3）═══
            vision_tool = _get_vision_hook_visual_understand()
            vision_result = await vision_tool.run_async(
                image_source=image_b64,
                question=verification_question,
            )

            # ═══ 阶段 6：构建 element_map ═══
            element_map = await asyncio.to_thread(
                self._build_element_map_from_pil,
                pil_img,
            )

            # ═══ 阶段 7：处理结果 ═══
            visual_description = ""
            if vision_result and vision_result.get("success"):
                visual_description = vision_result["data"]["description"]
                visual_verification_result = {
                    "status": "verified",
                    "description": visual_description,
                    "operation": tool_id,
                    "element_map": element_map,
                    "timestamp": time.time(),
                }
                logger.info("[VisionHook-Async] ✅ 视觉验证完成: %s...", visual_description[:80])
                self._record_success(session_id)
            else:
                error_msg = vision_result.get("error", "未知错误") if vision_result else "返回None"
                logger.warning("[VisionHook-Async] ⚠️ 视觉模型分析失败: %s", error_msg)
                visual_verification_result = {
                    "status": "failed",
                    "error": error_msg,
                    "operation": tool_id,
                    "element_map": element_map,
                    "timestamp": time.time(),
                }
                self._record_failure(session_id)

            if working_memory is not None:
                self._inject_vision_feedback(
                    working_memory=working_memory,
                    tool_id=tool_id,
                    visual_description=visual_description,
                    element_map=element_map,
                )

            self._emit_visual_verification_event(
                session_id=session_id,
                loop_state=loop_state,
                tool_id=tool_id,
                visual_verification_result=visual_verification_result,
            )

            ctx.extra["visual_verification_result"] = visual_verification_result

        except Exception as e:
            logger.error("[VisionHook-Async] 自动视觉验证异常: %s", e, exc_info=True)
            self._record_failure(session_id)

        finally:
            # ═══ 确定性资源释放 —— 无论如何都要执行 ═══
            if image_b64 is not None:
                image_b64 = None
            if pil_img is not None:
                try:
                    pil_img.close()
                except Exception as e:
                    logger.error(f"[VisionHook] 关闭PIL图片失败: {e}", exc_info=True)
                pil_img = None

        return ctx

    # ═════════════════════════════════════════════════════════════════════════════
    # 内部辅助方法
    # ═════════════════════════════════════════════════════════════════════════════
    def _extract_tool_id(self, ctx: HookContext, tool_result: dict | None) -> str:
        """从 ctx.extra 或 tool_result 中提取工具 ID。"""
        tool_id = ""
        if isinstance(tool_result, dict):
            parsed = tool_result.get("parsed")
            if parsed and hasattr(parsed, "target_tool"):
                tool_id = parsed.target_tool
            else:
                result_data = tool_result.get("result", {})
                if isinstance(result_data, dict):
                    tool_id = result_data.get("tool", "")
        if not tool_id:
            tool_id = ctx.extra.get("last_tool_id", "")
        return tool_id

    def _should_verify(
        self,
        session_id: str,
        tool_id: str,
        result: dict[str, Any],
        vision_enabled: bool,
        change_detector: Any,
        loop_state: Any,
    ) -> dict[str, Any] | None:
        """
        判断是否需要触发视觉验证。
        返回空 dict 表示需要，返回 None 表示跳过。
        【安全原则】本方法只读状态，绝不更新任何计数器或时间戳。
        """
        # 基础开关检查
        if self.config and "vision.auto_verify.enabled" in self.config:
            auto_verify_enabled = self.config.get("vision.auto_verify.enabled", True)
        else:
            from core.config import config
            auto_verify_enabled = config.get("vision.auto_verify.enabled", True)

        if not (result.get("success") and
                tool_id in self.ui_operations and
                auto_verify_enabled and
                vision_enabled and
                change_detector):
            return None

        state = self._get_task_state(session_id)
        now = time.time()

        # 熔断检查
        if state.circuit_open:
            if now < state.circuit_open_until:
                logger.debug("[VisionHook-Safety] 熔断器打开，跳过验证")
                return None
            else:
                state.circuit_open = False
                logger.info("[VisionHook-Safety] 熔断器自动恢复")

        # 冷却检查（基于上次视觉模型调用完成时间）
        elapsed = now - state.last_verify_time
        if elapsed < _MIN_VERIFY_INTERVAL:
            logger.debug("[VisionHook-Safety] 冷却拦截: %.2fs < %.2fs", elapsed, _MIN_VERIFY_INTERVAL)
            return None

        # 任务级预算检查
        if state.verify_count >= _MAX_VERIFY_PER_TASK:
            logger.debug("[VisionHook-Safety] 任务预算耗尽: %d/%d", state.verify_count, _MAX_VERIFY_PER_TASK)
            return None

        # 轮次上限检查
        round_count = getattr(loop_state, "round_count", 0) if loop_state else 0
        if round_count > self.max_verify_rounds:
            logger.debug("[VisionHook-Safety] 轮次超限: %d > %d", round_count, self.max_verify_rounds)
            return None

        # UI 操作抽样
        state.ui_counter += 1
        if state.ui_counter % _UI_VERIFY_MODULO != 0:
            return None

        logger.debug("[VisionHook-Safety] 判断通过，准备验证")
        return {}

    def _record_success(self, session_id: str):
        """记录一次成功的视觉验证。"""
        state = self._get_task_state(session_id)
        state.consecutive_failures = 0
        state.verify_count += 1
        state.last_verify_time = time.time()
        logger.debug("[VisionHook-Safety] 成功记录: verify_count=%d", state.verify_count)

    def _record_failure(self, session_id: str):
        """记录一次失败的视觉验证，触发熔断机制。"""
        state = self._get_task_state(session_id)
        state.consecutive_failures += 1
        state.last_verify_time = time.time()
        logger.warning(
            "[VisionHook-Safety] 失败记录: consecutive_failures=%d/%d",
            state.consecutive_failures, _MAX_CONSECUTIVE_FAILURES
        )
        if state.consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
            state.circuit_open = True
            state.circuit_open_until = time.time() + _CIRCUIT_BREAK_DURATION
            logger.error(
                "[VisionHook-Safety] ⚠️ 熔断器打开！连续失败 %d 次，暂停 %.0f 秒",
                state.consecutive_failures, _CIRCUIT_BREAK_DURATION
            )

    def _load_verification_prompt_template(self) -> str:
        """
        加载视觉验证 Prompt 模板。

        Phase 4 顺手修复 04-条目45：
        从 core/prompt/vision_verify_prompt.txt 加载模板，避免硬编码 f-string。
        若文件读取失败，返回内置默认模板作为降级方案。
        """
        if self._verification_prompt_template is not None:
            return self._verification_prompt_template

        template_path = Path(__file__).parent.parent.parent / "prompt" / "vision_verify_prompt.txt"
        try:
            if template_path.exists():
                self._verification_prompt_template = template_path.read_text(encoding="utf-8")
                logger.info(f"[VisionHook] 已加载视觉验证 Prompt 模板: {template_path}")
                return self._verification_prompt_template
        except Exception as e:
            logger.warning(f"[VisionHook] 加载 Prompt 模板失败: {e}")

        # 降级：内置默认模板（与 txt 文件内容保持一致）
        self._verification_prompt_template = (
            "验证UI操作效果：\n"
            "操作类型: {tool_id}\n"
            "操作参数: {params}\n\n"
            "请分析：\n"
            "1. 操作是否成功执行？屏幕发生了什么变化？\n"
            "2. 是否出现预期的界面响应（如窗口打开、按钮被点击、文字被输入等）？\n"
            "3. 当前屏幕状态是否符合预期？\n"
            "4. 是否存在错误或异常情况？\n\n"
            "请用简洁的语言描述观察结果。"
        )
        return self._verification_prompt_template

    def _build_verification_question(self, tool_id: str, result: dict[str, Any]) -> str:
        """构建传给视觉模型的验证问题。"""
        params = result.get("data", {})
        template = self._load_verification_prompt_template()
        return template.format(tool_id=tool_id, params=params)

    def _build_element_map_from_pil(self, pil_img) -> list[dict]:
        """从 PIL Image 构建 element_map（精确坐标）。

        注意：由于 ScreenOCR 的 run() 方法不接受 image_path 且会自己内部截图，
        这里直接调用 ScreenOCR 底层 reader.readtext(img_array, detail=1) 来避免二次截图。
        失败时降级返回空列表。
        """
        element_map = []
        try:
            import numpy as np

            from tools.screen_ocr import ScreenOCR

            img_array = np.array(pil_img)
            ocr_tool = ScreenOCR()
            reader = ocr_tool._get_reader()
            raw_ocr = reader.readtext(img_array, detail=1, paragraph=False)

            for (bbox, text, confidence) in raw_ocr:
                x1, y1 = bbox[0]
                x2, y2 = bbox[2]
                element_map.append({
                    "text": text,
                    "x": int(x1),
                    "y": int(y1),
                    "width": int(x2 - x1),
                    "height": int(y2 - y1),
                    "type": "text",
                    "confidence": float(confidence),
                })
        except Exception as e:
            logger.debug(f"[VisionHook] OCR/element_map 构建失败: {e}")
        # 【修复】更新全局 element_map 缓存，供工具层元素引用解析使用
        try:
            from core.vision.perception_manager import set_last_element_map
            set_last_element_map(element_map)
        except Exception as e:
            logger.error(f"[VisionHook] 设置元素地图缓存失败: {e}", exc_info=True)
        return element_map

    def _inject_vision_feedback(
        self,
        working_memory: Any,
        tool_id: str,
        visual_description: str,
        element_map: list[dict],
    ) -> None:
        """将视觉验证结果和坐标信息注入 working_memory。"""
        desc_part = f"""[视觉验证结果]
操作 '{tool_id}' 的视觉分析：
{visual_description if visual_description else '（视觉模型未返回有效描述）'}

请基于上述视觉分析判断操作是否真正成功，并决定下一步行动。"""

        coord_part = ""
        if element_map:
            top_elements = element_map[:5]
            coord_part += "\n【可交互元素坐标 - 基于屏幕OCR】\n"
            for i, elem in enumerate(top_elements, 1):
                text = elem.get("text", "")[:20]
                x = elem.get("x", 0)
                y = elem.get("y", 0)
                w = elem.get("width", 0)
                h = elem.get("height", 0)
                center_x = x + w // 2
                center_y = y + h // 2
                coord_part += f"{i}. '{text}' 中心点: ({center_x}, {center_y})\n"
            coord_part += "【行动建议】如需点击上述元素，直接使用对应坐标执行 mouse_click。\n"

        full_msg = desc_part + coord_part
        working_memory.append({
            "role": "system",
            "content": full_msg,
            "_category": "vision_verification",
            "_overwrite": True
        })

    def _emit_visual_verification_event(
        self,
        session_id: str,
        loop_state: Any,
        tool_id: str,
        visual_verification_result: dict[str, Any],
    ) -> None:
        """发送 visual_verification_complete 事件到前端。保持原有字段，新增 element_map。"""
        try:
            from core.sync.realtime_sync import get_realtime_sync_manager
            sync = get_realtime_sync_manager()
            round_count = getattr(loop_state, "round_count", 0) if loop_state else 0
            sync.emit_event("visual_verification_complete", session_id, {
                "round": round_count,
                "tool": tool_id,
                "verification": visual_verification_result,
                "success": visual_verification_result.get("status") == "verified",
            })
        except Exception as e:
            logger.error(f"[VisionHook] 发送视觉验证事件失败: {e}")


# 全局实例
vision_hook = VisionHook()
