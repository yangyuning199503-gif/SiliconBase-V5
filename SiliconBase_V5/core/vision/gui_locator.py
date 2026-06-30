#!/usr/bin/env python3
"""
GUI 视觉定位接口 - 轻量GUI元素定位器

设计目标：
- 统一接口，让未来接入 Grounding DINO、ShowUI-2B 等模型时只需改内部实现
- 当前兜底：复用 RealtimeDetector 的三源（ONNX/OCR/UIA）结果做关键词匹配
- 后续替换：接入专用 GUI 定位模型（如 ShowUI-2B）

使用方式：
    from core.vision.gui_locator import get_gui_locator
    locator = get_gui_locator()
    result = await locator.locate(screenshot=None, description="搜索框")
    # -> {"bbox": [x1, y1, x2, y2], "confidence": 0.95, "model": "nanodet"} 或 None
"""

import asyncio
import base64
import io
import json
import time
from typing import Any

try:
    from core.vision.realtime_detector import _get_foreground_window_info
except ImportError:
    _get_foreground_window_info = None


class GUILocator:
    """
    统一 GUI 元素定位器

    当前实现（临时兜底）：
    - 调用 RealtimeDetector 的三源结果（ONNX/OCR/UIA）
    - 按 description 关键词在 UIA 和 OCR 结果中做模糊匹配
    - 返回匹配到的第一个元素的 bbox

    未来替换：
    - 接入 Grounding DINO / ShowUI-2B 等专用模型
    - 接口不变，内部替换为模型推理调用
    """

    def __init__(self):
        self._detector = None
        self._logger = None
        self._consecutive_locate_failures = 0

    def _get_logger(self):
        if self._logger is None:
            try:
                from core.logger import logger
                self._logger = logger
            except Exception:
                import logging
                self._logger = logging.getLogger("GUILocator")
        return self._logger

    async def health_check(self) -> bool:
        """
        检查底层视觉系统是否可用

        Returns:
            bool: True 表示 RealtimeDetector 可用
        """
        try:
            from core.vision.realtime_detector import RealtimeDetector
            # 尝试初始化（不保留实例，仅做可用性检查）
            test = RealtimeDetector()
            return test._onnx_initialized or True  # UIA/OCR 不依赖 ONNX 也能工作
        except Exception as e:
            self._get_logger().warning(f"[GUILocator] health_check 失败: {e}")
            return False

    async def locate(
        self,
        screenshot: bytes | None,
        description: str,
        user_id: str | None = None
    ) -> dict[str, Any] | None:
        """
        定位屏幕上的 GUI 元素

        Args:
            screenshot: 截图二进制数据（当前未使用，保留给未来模型）
            description: 需要定位的元素描述，如"搜索框"、"播放按钮"
            user_id: 用户ID，用于写入用户快照（可选，向后兼容）

        Returns:
            {
                "bbox": [x1, y1, x2, y2],
                "confidence": float,
                "model": str,
                "source": str,  # "uia" | "ocr" | "onnx"
                "matched_name": str,
            }
            或 None（未找到）
        """
        if not description:
            return None

        desc_lower = description.strip().lower()
        if not desc_lower:
            return None

        # 获取当前前台应用名（多处复用）
        _app_name = "unknown"
        try:
            if _get_foreground_window_info is not None:
                win_info = _get_foreground_window_info()
                _app_name = win_info.get("process", "unknown")
        except Exception as fg_err:
            self._get_logger().warning(f"[GUILocator] 获取前台窗口信息失败: {fg_err}")

        # ── 策略0：优先从 LabelCache 读取历史坐标 ──
        try:
            from core.vision.label_cache import get_label_cache
            cache = get_label_cache()
            cached_bbox = cache.get(_app_name, description)
            if cached_bbox:
                self._consecutive_locate_failures = 0
                self._get_logger().info(
                    f"[GUILocator] LabelCache 命中: '{description}' app={_app_name} -> {cached_bbox}"
                )
                return {
                    "bbox": cached_bbox,
                    "confidence": 0.98,
                    "model": "label_cache",
                    "source": "cache",
                    "matched_name": description,
                }
        except Exception as e:
            self._get_logger().debug(f"[GUILocator] LabelCache 读取失败: {e}")

        # ── 策略1：优先从 DialogueManager 的实时监控快照读取 ──
        try:

            from core.dialog.dialogue_manager import dialogue_manager
            dm = dialogue_manager
            if dm and hasattr(dm, '_user_task_snapshots'):
                # 找最近有数据的用户快照（不绑定特定user_id，兜底用）
                realtime_snap = None
                with dm._snapshot_lock:
                    for key, snap in dm._user_task_snapshots.items():
                        if key.endswith("_realtime") and snap:
                            realtime_snap = snap
                            break
                if realtime_snap:
                    result = self._match_in_snapshot(realtime_snap, desc_lower, description)
                    if result:
                        self._consecutive_locate_failures = 0
                        self._get_logger().info(
                            f"[GUILocator] 快照匹配成功: '{description}' -> {result['bbox']}"
                        )
                        # 写入 LabelCache
                        try:
                            from core.vision.label_cache import get_label_cache
                            cache = get_label_cache()
                            _app_name = realtime_snap.get("dominant_app", "unknown")
                            cache.set(_app_name, description, result["bbox"])
                        except Exception as ce:
                            self._get_logger().debug(f"[GUILocator] LabelCache 写入失败: {ce}")
                        return result
        except Exception as e:
            self._get_logger().debug(f"[GUILocator] 快照读取失败: {e}")

        # ── 策略2：临时创建 RealtimeDetector 做单帧检测 ──
        try:

            from core.vision.realtime_detector import RealtimeDetector

            detector = await RealtimeDetector.create_async()
            # 使用前台窗口截图（需要 DXGICapture）
            try:
                from core.vision.dxgi_capture import DXGICapture
                capture = DXGICapture()
                frame = capture.get_latest_frame()
                if frame is not None:
                    snap = await detector.detect(frame)
                    result = self._match_in_snapshot(snap, desc_lower, description)
                    if result:
                        self._consecutive_locate_failures = 0
                        self._get_logger().info(
                            f"[GUILocator] 实时检测匹配成功: '{description}' -> {result['bbox']}"
                        )
                        return result
            except Exception as cap_e:
                self._get_logger().debug(f"[GUILocator] 实时截图失败: {cap_e}")
        except Exception as e:
            self._get_logger().debug(f"[GUILocator] RealtimeDetector 调用失败: {e}")

        # ── 策略3：求助视觉大模型（qwen3-vl:8b）打标签 ──
        try:
            from core.vision.dxgi_capture import DXGICapture
            capture = DXGICapture()
            frame = capture.get_latest_frame()
            if frame is not None:
                vision_result = await self._ask_vision_for_tags(frame, description, _app_name)
                if vision_result and vision_result.get("bbox"):
                    bbox = vision_result["bbox"]
                    tag = vision_result.get("tag", description)
                    self._consecutive_locate_failures = 0
                    self._get_logger().info(
                        f"[GUILocator] L3 视觉模型命中: '{description}' app={_app_name} -> {bbox}"
                    )
                    # 写入 LabelCache
                    try:
                        from core.vision.label_cache import get_label_cache
                        cache = get_label_cache()
                        cache.set(_app_name, description, bbox)
                    except Exception as ce:
                        self._get_logger().debug(f"[GUILocator] LabelCache 写入失败: {ce}")

                    # 如果提供了 user_id，写入用户快照
                    if user_id:
                        try:
                            await self._write_to_snapshot(user_id, description, vision_result)
                        except Exception as se:
                            self._get_logger().debug(f"[GUILocator] 快照写入失败: {se}")

                    return {
                        "bbox": [int(b) for b in bbox],
                        "confidence": vision_result.get("confidence", 0.85),
                        "model": "qwen3-vl",
                        "source": "vision_llm",
                        "matched_name": tag,
                    }
        except Exception as e:
            self._get_logger().debug(f"[GUILocator] L3 视觉模型调用失败: {e}")

        self._consecutive_locate_failures += 1
        self._get_logger().warning(
            f"[GUILocator] 所有定位策略均失败: '{description}' app={_app_name} "
            f"(连续失败 {self._consecutive_locate_failures}/3)"
        )
        if self._consecutive_locate_failures >= 3:
            try:
                from core.sync.event_bus import event_bus as main_event_bus
                main_event_bus.emit("gui_locate_failed", {
                    "description": description,
                    "app_name": _app_name,
                    "consecutive_failures": self._consecutive_locate_failures,
                    "timestamp": time.time()
                })
            except Exception as bus_err:
                self._get_logger().warning(f"[GUILocator] 推送 gui_locate_failed 事件失败: {bus_err}")
        return None

    async def _ask_vision_for_tags(
        self,
        frame: Any,
        description: str,
        app_name: str
    ) -> dict[str, Any] | None:
        """
        调用视觉大模型对画面进行理解和打标签

        Args:
            frame: 当前画面帧（numpy ndarray）
            description: 需要定位的元素描述
            app_name: 当前应用名

        Returns:
            {'tag': '...', 'bbox': [x1, y1, x2, y2], 'description': '...', 'confidence': float}
            或 None
        """
        try:
            import numpy as np
            from PIL import Image

        except Exception as e:
            self._get_logger().debug(f"[GUILocator] L3 依赖导入失败: {e}")
            return None

        try:
            # 将 numpy 帧转为 base64 PNG（OpenCV 为 BGR，需转 RGB）
            if isinstance(frame, np.ndarray):
                import cv2
                pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            elif hasattr(frame, "convert"):
                pil_img = frame
            else:
                self._get_logger().debug("[GUILocator] L3 不支持的帧类型")
                return None

            buffer = io.BytesIO()
            pil_img.save(buffer, format="PNG")
            image_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
            buffer.close()
        except Exception as e:
            self._get_logger().debug(f"[GUILocator] L3 图像编码失败: {e}")
            return None

        prompt = (
            f"当前应用: {app_name}。"
            f"请在画面中定位元素：'{description}'。"
            f"返回严格 JSON 格式："
            f"{{'tag': '元素标签名', 'bbox': [x1, y1, x2, y2], 'description': '简短描述'}}"
            f"bbox 为像素坐标，如果找不到返回 {{'tag': null, 'bbox': null, 'description': '未找到'}}"
        )

        try:
            from core.vision.vision_processor import _get_visual_understand
            vision_tool = _get_visual_understand()
            if vision_tool is None:
                self._get_logger().debug("[GUILocator] L3 VisualUnderstand 单例不可用")
                return None
            # hard_timeout=60，给足时间
            result = await asyncio.wait_for(
                vision_tool._execute_async(image_source=image_b64, question=prompt),
                timeout=60
            )
        except asyncio.TimeoutError:
            self._get_logger().warning("[GUILocator] L3 视觉模型调用超时（60s）")
            return None
        except Exception as e:
            self._get_logger().debug(f"[GUILocator] L3 视觉模型请求失败: {e}")
            return None

        if not result or not result.get("success"):
            self._get_logger().debug(
                f"[GUILocator] L3 视觉模型返回失败: {result.get('error') if result else 'None'}"
            )
            return None

        # 解析视觉模型返回的文本
        data = result.get("data", {})
        text = data.get("description") or data.get("text") or data.get("answer") or ""
        if not text:
            self._get_logger().debug("[GUILocator] L3 视觉模型返回空文本")
            return None

        # 尝试从文本中提取 JSON
        parsed = self._parse_vision_json(text)
        if parsed and parsed.get("bbox"):
            parsed["confidence"] = 0.85
            return parsed

        return None

    def _parse_vision_json(self, text: str) -> dict[str, Any] | None:
        """从视觉模型返回的文本中解析 JSON"""
        if not text:
            return None

        # 先尝试直接解析整个文本
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and parsed.get("bbox"):
                return parsed
        except Exception:
            pass

        # 尝试从 markdown 代码块中提取
        import re
        code_block = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if code_block:
            try:
                parsed = json.loads(code_block.group(1))
                if isinstance(parsed, dict) and parsed.get("bbox"):
                    return parsed
            except Exception:
                pass

        # 尝试匹配最外层的花括号
        brace_match = re.search(r"\{[^{}]*\}", text)
        if brace_match:
            try:
                parsed = json.loads(brace_match.group(0))
                if isinstance(parsed, dict) and parsed.get("bbox"):
                    return parsed
            except Exception:
                pass

        return None

    async def _write_to_snapshot(
        self,
        user_id: str,
        description: str,
        result: dict[str, Any]
    ) -> None:
        """
        将定位结果写入用户任务快照

        Args:
            user_id: 用户ID
            description: 元素描述
            result: 定位结果字典，需包含 bbox、tag 等
        """
        try:

            from core.dialog.dialogue_manager import dialogue_manager
            dm = dialogue_manager
            if not dm or not hasattr(dm, '_user_task_snapshots'):
                return

            realtime_key = f"{user_id}_realtime"
            with dm._snapshot_lock:
                snapshot = dm._user_task_snapshots.get(realtime_key)
                if snapshot is None:
                    snapshot = {
                        "dominant_app": "unknown",
                        "objects": [],
                        "timestamp": time.time(),
                    }
                    dm._user_task_snapshots[realtime_key] = snapshot

                objects = snapshot.setdefault("objects", [])
                objects.append({
                    "source": "gui_locator",
                    "name": description,
                    "class": result.get("tag", description),
                    "bbox": [int(b) for b in result.get("bbox", [])],
                    "confidence": result.get("confidence", 0.85),
                    "description": result.get("description", ""),
                })
        except Exception as e:
            self._get_logger().debug(f"[GUILocator] 写入快照异常: {e}")

    def _match_in_snapshot(
        self,
        snapshot: dict[str, Any],
        desc_lower: str,
        original_desc: str
    ) -> dict[str, Any] | None:
        """
        在快照结果中按关键词匹配元素

        匹配优先级：UIA 控件 > OCR 文字 > ONNX 物体
        """
        if not snapshot:
            return None

        objects = snapshot.get("objects", [])
        if not objects:
            return None

        # 1. 优先匹配 UIA 控件（可交互元素最准）
        for obj in objects:
            if obj.get("source") != "uia":
                continue
            name = (obj.get("name", "") or "").strip()
            cls = (obj.get("class", "") or "").strip()
            if not name and not cls:
                continue
            name_lower = name.lower()
            cls_lower = cls.lower()
            # 子串双向匹配
            if desc_lower in name_lower or name_lower in desc_lower or \
               desc_lower in cls_lower or cls_lower in desc_lower:
                bbox = obj.get("bbox", [0, 0, 0, 0])
                return {
                    "bbox": [int(b) for b in bbox],
                    "confidence": obj.get("confidence", 0.85),
                    "model": "nanodet",
                    "source": "uia",
                    "matched_name": (cls + (f' "{name}"' if name else '')),
                }

        # 2. 其次匹配 OCR 文字
        for obj in objects:
            if obj.get("source") != "ocr":
                continue
            text = (obj.get("text", "") or "").strip()
            if not text:
                continue
            text_lower = text.lower()
            if desc_lower in text_lower or text_lower in desc_lower:
                bbox = obj.get("bbox", [0, 0, 0, 0])
                return {
                    "bbox": [int(b) for b in bbox],
                    "confidence": obj.get("confidence", 0.75),
                    "model": "nanodet",
                    "source": "ocr",
                    "matched_name": text,
                }

        # 3. 最后匹配 ONNX 物体
        for obj in objects:
            if obj.get("source") != "onnx":
                continue
            cls = (obj.get("class", "") or "").strip()
            if not cls:
                continue
            cls_lower = cls.lower()
            if desc_lower in cls_lower or cls_lower in desc_lower:
                bbox = obj.get("bbox", [0, 0, 0, 0])
                return {
                    "bbox": [int(b) for b in bbox],
                    "confidence": obj.get("confidence", 0.6),
                    "model": "nanodet",
                    "source": "onnx",
                    "matched_name": cls,
                }

        return None


# ── 全局单例 ──
_gui_locator_instance: GUILocator | None = None


def get_gui_locator() -> GUILocator:
    """获取 GUILocator 单例"""
    global _gui_locator_instance
    if _gui_locator_instance is None:
        _gui_locator_instance = GUILocator()
    return _gui_locator_instance
