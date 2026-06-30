"""
多源融合实时检测模块

设计原则：
- ONNX 通用物体检测（快，~15ms）—— 物理世界物体、游戏角色等
- EasyOCR 文本检测（中，~100ms GPU）—— 读取屏幕上的所有文字、数字
- UIAutomation 控件检测（中，~80ms）—— 获取所有可交互 UI 元素（按钮、输入框等）

三种检测源的结果统一格式输出，带 source 字段区分来源。
OCR 和 UIA 有频率缓存（2秒），避免阻塞 33ms 主循环。

许可证安全栈：
- ONNX Runtime: MIT
- EasyOCR: MIT
- OpenCV: Apache 2.0
- NanoDet/替代模型: Apache 2.0
- UIAutomation: Windows 原生 API
"""

import asyncio
import ctypes
import threading
import time
import warnings
from pathlib import Path
from typing import Any

try:
    import cv2
except ImportError:
    cv2 = None  # type: ignore[assignment,misc]

import numpy as np

# 屏蔽 ONNX Runtime CUDA 回退的 Python UserWarning
warnings.filterwarnings("ignore", message=".*Specified provider.*not in available.*")


# ═══════════════════════════════════════════════════════════════════
# 前台窗口信息（无外部依赖）
# ═══════════════════════════════════════════════════════════════════

def _get_foreground_window_info() -> dict[str, str]:
    """获取当前前台窗口信息（Windows）"""
    result = {"title": "", "process": "unknown", "pid": "0"}
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if hwnd:
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                result["title"] = buf.value
            pid = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            result["pid"] = str(pid.value)
            try:
                import psutil
                proc = psutil.Process(pid.value)
                result["process"] = proc.name()
            except Exception:
                pass
    except Exception:
        pass
    return result


# ═══════════════════════════════════════════════════════════════════
# 多源融合实时检测器
# ═══════════════════════════════════════════════════════════════════

class RealtimeDetector:
    """
    多源融合实时检测器

    同时输出三类检测结果：
    - onnx:  通用物体（人、手机、键盘、笔记本等）
    - ocr:   文本区域（金币数字、血量、聊天文字等）
    - uia:   UI 控件（按钮、输入框、菜单、链接等）
    """

    DEFAULT_MODEL_PATH = "assets/models/nanodet-plus-m_416.onnx"
    TEXT_DETECT_INTERVAL = 2.0   # OCR 最少间隔（秒）
    UIA_DETECT_INTERVAL = 2.0    # UIAutomation 最少间隔（秒）

    @classmethod
    async def create_async(cls, model_path: str | None = None, enable_ocr: bool = True,
                           enable_uia: bool = True, ocr_gpu: bool = True):
        """异步构造 RealtimeDetector（将阻塞的 ONNX 初始化移到线程池）"""
        import asyncio
        return await asyncio.to_thread(cls, model_path, enable_ocr, enable_uia, ocr_gpu)

    def __init__(
        self,
        model_path: str | None = None,
        enable_ocr: bool = True,
        enable_uia: bool = True,
        ocr_gpu: bool = True,
    ):
        """
        Args:
            model_path: ONNX 模型路径
            enable_ocr: 是否启用 EasyOCR 文本检测
            enable_uia: 是否启用 UIAutomation 控件检测
            ocr_gpu: EasyOCR 是否使用 GPU（需要 CUDA + PyTorch）
        """
        self.model_path = model_path or self.DEFAULT_MODEL_PATH
        self._enable_ocr = enable_ocr
        self._enable_uia = enable_uia
        self._ocr_gpu = ocr_gpu
        self._logger = None
        # 【P0修复】EasyOCR 初始化重试控制
        self._ocr_init_retry_count = 0
        self._ocr_init_max_retries = 3
        self._ocr_init_retry_interval = 30
        self._ocr_init_next_retry_time = 0.0

        # ONNX
        self._session = None
        self._input_name = None
        self._input_shape = None
        self._onnx_initialized = False
        self._init_onnx()

        # EasyOCR（延迟初始化）
        self._ocr_reader = None
        self._ocr_lock = threading.Lock()
        self._last_text_time = 0.0
        self._last_text_result: list[dict[str, Any]] = []

        # UIAutomation
        self._uia_lock = threading.Lock()
        self._last_ui_time = 0.0
        self._last_ui_result: list[dict[str, Any]] = []

    def _get_logger(self):
        if self._logger is None:
            try:
                from core.logger import logger
                self._logger = logger
            except Exception:
                import logging
                self._logger = logging.getLogger("RealtimeDetector")
        return self._logger

    # ───────────────────────────────────────────────────────────────
    # ONNX 通用物体检测
    # ───────────────────────────────────────────────────────────────

    def _init_onnx(self):
        """加载 ONNX 模型"""
        try:
            import os

            import onnxruntime as ort
            if not os.path.exists(self.model_path):
                self._get_logger().warning(
                    f"[RealtimeDetector] ONNX 模型不存在: {self.model_path}"
                )
                return
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
            sess_options = ort.SessionOptions()
            sess_options.log_severity_level = 3  # 3 = ERROR, 屏蔽 WARNING/INFO C++ 日志
            self._session = ort.InferenceSession(
                self.model_path, sess_options, providers=providers
            )
            self._input_name = self._session.get_inputs()[0].name
            self._input_shape = self._session.get_inputs()[0].shape
            self._onnx_initialized = True
            self._get_logger().info(
                f"[RealtimeDetector] ONNX 加载成功: {self.model_path}, "
                f"输入形状: {self._input_shape}"
            )
        except Exception as e:
            self._get_logger().warning(
                f"[RealtimeDetector] ONNX 初始化失败: {e}"
            )
            self._session = None

    def _preprocess(self, frame: np.ndarray) -> np.ndarray | None:
        """
        ONNX 预处理
        - NanoDet: 直接 resize 到模型输入尺寸
        - YOLO: 使用 letterbox（保持长宽比，灰色填充）
        """
        try:
            import cv2
            if self._input_shape and len(self._input_shape) >= 3:
                h = int(self._input_shape[-2]) if self._input_shape[-2] else 640
                w = int(self._input_shape[-1]) if self._input_shape[-1] else 640
            else:
                h, w = 640, 640

            img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img_h, img_w = img.shape[:2]

            # 判断是否是 YOLO 系列（输入 640x640 视为 YOLO）
            is_yolo = (h == 640 and w == 640)

            if is_yolo:
                # YOLO letterbox: 保持长宽比，左上角对齐，右侧/底部灰色填充
                scale = min(w / img_w, h / img_h)
                new_w = int(img_w * scale)
                new_h = int(img_h * scale)
                resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
                canvas = np.full((h, w, 3), 114, dtype=np.uint8)  # 灰色填充
                canvas[:new_h, :new_w] = resized
                img = canvas.astype(np.float32) / 255.0
                # 记录缩放参数，供后处理还原坐标
                self._last_scale = scale
                self._last_pad = (0, 0)  # 左上角对齐，无 padding 偏移
            else:
                # NanoDet: 直接 resize
                img = cv2.resize(img, (w, h))
                img = img.astype(np.float32) / 255.0
                self._last_scale = None
                self._last_pad = None

            img = np.transpose(img, (2, 0, 1))
            img = np.expand_dims(img, axis=0)
            return img
        except Exception as e:
            self._get_logger().warning(f"[RealtimeDetector] 预处理失败: {e}")
            return None

    def _postprocess_onnx(
        self, outputs: Any, original_shape: tuple
    ) -> tuple[list[dict[str, Any]], str, str]:
        """
        ONNX 后处理 —— 兼容 NanoDet [N,6] 和 YOLO [1,8400,85] 两种格式
        → objects, layout_summary, dominant_app
        """
        objects: list[dict[str, Any]] = []
        layout_summary = "检测到画面元素"
        dominant_app = "unknown"

        # 前台窗口信息
        try:
            win_info = _get_foreground_window_info()
            dominant_app = win_info.get("process", "unknown")
            title = win_info.get("title", "")
            if title:
                layout_summary = f"当前前台窗口：{title}（{dominant_app}）"
        except Exception:
            pass

        try:
            if not isinstance(outputs, (list, tuple)) or len(outputs) == 0:
                layout_summary += "，模型输出为空"
                return objects, layout_summary, dominant_app

            det_out = outputs[0]
            if not isinstance(det_out, np.ndarray):
                layout_summary += "，模型输出格式异常"
                return objects, layout_summary, dominant_app

            # ── 格式判断 ──
            if det_out.ndim == 2 and det_out.shape[-1] == 6:
                # NanoDet 格式: [N, 6] → [x1, y1, x2, y2, score, class_id]
                objects = self._postprocess_nanodet(det_out)
            elif det_out.ndim == 3 and det_out.shape[-1] == 85:
                # YOLO 格式: [1, 8400, 85] → 需要解码 + NMS
                objects = self._postprocess_yolo(det_out, original_shape)
            else:
                layout_summary += f"，未知输出形状 {det_out.shape}"

        except Exception as e:
            self._get_logger().debug(f"[RealtimeDetector] ONNX 后处理解析失败: {e}")

        if not objects:
            layout_summary += "，未检测到显著目标"
        return objects, layout_summary, dominant_app

    def _postprocess_nanodet(self, det_out: np.ndarray) -> list[dict[str, Any]]:
        """解析 NanoDet 风格输出 [N, 6]"""
        objects: list[dict[str, Any]] = []
        for row in det_out:
            if len(row) < 6:
                continue
            score = float(row[4])
            if score < 0.3:
                continue
            cls_id = int(row[5])
            objects.append({
                "class": self._class_id_to_name(cls_id),
                "bbox": [float(row[0]), float(row[1]), float(row[2]), float(row[3])],
                "confidence": round(score, 2),
                "source": "onnx",
            })
        return objects

    def _postprocess_yolo(
        self, det_out: np.ndarray, original_shape: tuple
    ) -> list[dict[str, Any]]:
        """解析 YOLO 风格输出 [1, 8400, 85] → 解码 + NMS"""
        predictions = det_out[0]  # [8400, 85]
        conf_thresh = 0.5   # YOLO COCO 预训练在桌面场景上提高 threshold 减少误检
        nms_thresh = 0.5

        # 1. 生成 grid 和 stride
        strides = [8, 16, 32]
        grids = []
        expanded_strides = []
        for stride in strides:
            h = 640 // stride
            w = 640 // stride
            yv, xv = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
            grid = np.stack((xv, yv), 2).reshape(-1, 2)
            grids.append(grid)
            expanded_strides.append(np.full((grid.shape[0], 1), stride))
        grids = np.concatenate(grids, axis=0)           # [8400, 2]
        expanded_strides = np.concatenate(expanded_strides, axis=0)  # [8400, 1]

        # 2. sigmoid
        def sigmoid(x):
            return 1.0 / (1.0 + np.exp(-x))

        bbox_preds = sigmoid(predictions[:, :4])       # [8400, 4]
        obj_preds = sigmoid(predictions[:, 4:5])       # [8400, 1]
        cls_preds = sigmoid(predictions[:, 5:])        # [8400, 80]

        # 3. 解码 bbox
        cx = (grids[:, 0:1] + bbox_preds[:, 0:1]) * expanded_strides
        cy = (grids[:, 1:2] + bbox_preds[:, 1:2]) * expanded_strides
        w = np.exp(np.clip(bbox_preds[:, 2:3], -10, 10)) * expanded_strides
        h = np.exp(np.clip(bbox_preds[:, 3:4], -10, 10)) * expanded_strides
        x1 = cx - w / 2
        y1 = cy - h / 2
        x2 = cx + w / 2
        y2 = cy + h / 2

        # 4. 计算 score 和 class
        # 【修复】部分 YOLO ONNX 导出模型的 objectness 恒为 0.5（无区分度），
        # 此时退化为直接用 cls_score 作为最终置信度
        raw_obj_mean = obj_preds.mean()
        # objectness 无区分度时忽略它，否则使用 objectness * cls_score
        scores = cls_preds if abs(raw_obj_mean - 0.5) < 0.01 else obj_preds * cls_preds  # [8400, 80]
        max_scores = scores.max(axis=1)                         # [8400]
        class_ids = scores.argmax(axis=1)                       # [8400]

        # 5. 过滤低置信度
        mask = max_scores > conf_thresh
        if not mask.any():
            return []
        x1, y1, x2, y2 = x1[mask], y1[mask], x2[mask], y2[mask]
        max_scores = max_scores[mask]
        class_ids = class_ids[mask]

        # 6. 还原 letterbox 并缩放到原图尺寸
        if self._last_scale is not None:
            # 左上角对齐 letterbox：直接除以缩放比例
            x1 /= self._last_scale
            y1 /= self._last_scale
            x2 /= self._last_scale
            y2 /= self._last_scale
        else:
            orig_h, orig_w = original_shape[:2]
            scale_x = orig_w / 640.0
            scale_y = orig_h / 640.0
            x1 *= scale_x
            x2 *= scale_x
            y1 *= scale_y
            y2 *= scale_y

        # 7. NMS
        boxes = np.concatenate([x1, y1, x2, y2], axis=1)  # [N, 4]
        keep = self._nms(boxes, max_scores, nms_thresh)
        if len(keep) == 0:
            return []

        objects: list[dict[str, Any]] = []
        for i in keep:
            objects.append({
                "class": self._class_id_to_name(int(class_ids[i])),
                "bbox": [
                    float(x1[i]), float(y1[i]),
                    float(x2[i]), float(y2[i])
                ],
                "confidence": round(float(max_scores[i]), 2),
                "source": "onnx",
            })
        return objects

    @staticmethod
    def _nms(
        boxes: np.ndarray, scores: np.ndarray, thresh: float
    ) -> list[int]:
        """纯 numpy NMS 实现"""
        x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
        areas = (x2 - x1 + 1) * (y2 - y1 + 1)
        order = scores.argsort()[::-1]
        keep = []
        while order.size > 0:
            i = order[0]
            keep.append(int(i))
            if order.size == 1:
                break
            xx1 = np.maximum(x1[i], x1[order[1:]])
            yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]])
            yy2 = np.minimum(y2[i], y2[order[1:]])
            w = np.maximum(0.0, xx2 - xx1 + 1)
            h = np.maximum(0.0, yy2 - yy1 + 1)
            inter = w * h
            iou = inter / (areas[i] + areas[order[1:]] - inter)
            inds = np.where(iou <= thresh)[0]
            order = order[inds + 1]
        return keep

    @staticmethod
    def _class_id_to_name(cls_id: int) -> str:
        """COCO 类别映射（桌面场景常用类优先）"""
        coco_names = {
            0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 4: "airplane",
            5: "bus", 6: "train", 7: "truck", 8: "boat", 9: "traffic light",
            10: "fire hydrant", 11: "stop sign", 12: "parking meter", 13: "bench",
            14: "bird", 15: "cat", 16: "dog", 17: "horse", 18: "sheep", 19: "cow",
            24: "backpack", 25: "umbrella", 26: "handbag", 27: "tie", 28: "suitcase",
            32: "sports ball", 37: "sports ball", 38: "kite", 39: "baseball bat",
            40: "baseball glove", 41: "skateboard", 42: "surfboard", 43: "tennis racket",
            44: "bottle", 46: "wine glass", 47: "cup", 48: "fork", 49: "knife",
            50: "spoon", 51: "bowl", 52: "banana", 53: "apple", 54: "sandwich",
            55: "orange", 56: "broccoli", 57: "carrot", 58: "hot dog", 59: "pizza",
            60: "donut", 61: "cake", 62: "chair", 63: "couch", 64: "potted plant",
            65: "bed", 67: "dining table", 70: "toilet", 72: "tv", 73: "laptop",
            74: "mouse", 75: "remote", 76: "keyboard", 77: "cell phone",
            78: "microwave", 79: "oven", 80: "toaster", 81: "sink",
            82: "refrigerator", 84: "book", 85: "clock", 86: "vase",
            87: "scissors", 88: "teddy bear", 89: "hair drier", 90: "toothbrush",
        }
        return coco_names.get(cls_id, f"object_{cls_id}")

    # ───────────────────────────────────────────────────────────────
    # EasyOCR 文本检测
    # ───────────────────────────────────────────────────────────────

    async def _ensure_ocr(self):
        """延迟初始化 EasyOCR reader（异步线程安全，带重试）"""
        if self._ocr_reader is not None:
            return True
        # 已达最大重试次数，永久禁用
        if self._ocr_init_retry_count >= self._ocr_init_max_retries:
            return False
        # 冷却期内，跳过
        if time.time() < self._ocr_init_next_retry_time:
            return False
        try:
            import easyocr
            import torch

            # 【PyTorch 2.7 兼容修复】
            # EasyOCR 内部调用 torch.load(..., map_location=device) 加载模型权重。
            # PyTorch 2.7 默认 mmap=True，权重以懒加载方式映射，后续 .to(device) 时
            # 会触发 "Cannot copy out of meta tensor" 错误。
            # 此处临时 patch torch.load 强制 mmap=False，等 EasyOCR 初始化完成后恢复。
            _orig_torch_load = torch.load
            def _safe_torch_load(*args, **kwargs):
                kwargs.setdefault("mmap", False)
                return _orig_torch_load(*args, **kwargs)
            torch.load = _safe_torch_load

            try:
                self._ocr_reader = await asyncio.to_thread(
                    easyocr.Reader,
                    ["ch_sim", "en"],
                    gpu=self._ocr_gpu,
                    verbose=False,
                )
            finally:
                torch.load = _orig_torch_load
            # 成功，重置重试计数
            self._ocr_init_retry_count = 0
            self._ocr_init_next_retry_time = 0.0
            self._get_logger().info(
                "\n".join([
                    "",
                    "┌────────────────────────────────────────┐",
                    "│  [OCR] ✅ EasyOCR 初始化成功            │",
                    f"│  语言: ch_sim + en   GPU: {str(self._ocr_gpu):>5}        │",
                    "└────────────────────────────────────────┘",
                ])
            )
            return True
        except Exception as e:
            self._ocr_init_retry_count += 1
            self._ocr_init_next_retry_time = time.time() + self._ocr_init_retry_interval
            if self._ocr_init_retry_count >= self._ocr_init_max_retries:
                self._get_logger().error(
                    f"[OCR] EasyOCR 初始化永久失败（{self._ocr_init_retry_count}/"
                    f"{self._ocr_init_max_retries}），文字过滤功能已禁用。原因: {str(e)}"
                )
                self._enable_ocr = False
            else:
                self._get_logger().info(
                    f"[OCR] EasyOCR 初始化失败，将在 {self._ocr_init_retry_interval} 秒后重试 "
                    f"（第 {self._ocr_init_retry_count}/{self._ocr_init_max_retries} 次）。"
                    f"原因: {str(e)}"
                )
            return False

    async def _detect_text(self, frame: np.ndarray) -> list[dict[str, Any]]:
        """
        EasyOCR 检测屏幕文本（异步线程安全）
        受频率缓存控制，避免每帧都跑（GPU 也要 ~50-200ms）
        """
        if not self._enable_ocr:
            return []

        now = time.time()
        with self._ocr_lock:
            if now - self._last_text_time < self.TEXT_DETECT_INTERVAL:
                return self._last_text_result

        if not await self._ensure_ocr():
            return []

        try:
            results = await asyncio.to_thread(self._ocr_reader.readtext, frame)
            parsed: list[dict[str, Any]] = []
            for r in results:
                # r = ([[x1,y1],[x2,y1],[x2,y2],[x1,y2]], text, confidence)
                bbox_quad, text, conf = r
                xs = [p[0] for p in bbox_quad]
                ys = [p[1] for p in bbox_quad]
                x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
                parsed.append({
                    "class": "text",
                    "bbox": [float(x1), float(y1), float(x2), float(y2)],
                    "text": text,
                    "confidence": round(float(conf), 2),
                    "source": "ocr",
                })

            with self._ocr_lock:
                self._last_text_time = now
                self._last_text_result = parsed
            return parsed
        except Exception as e:
            self._get_logger().warning(f"[RealtimeDetector] OCR 检测异常: {e}")
            return []

    # ───────────────────────────────────────────────────────────────
    # UIAutomation 控件检测
    # ───────────────────────────────────────────────────────────────

    async def _detect_ui_controls(self) -> list[dict[str, Any]]:
        """
        UIAutomation 获取前台窗口控件树（异步线程安全）
        受频率缓存控制，限制遍历深度避免卡顿
        """
        if not self._enable_uia:
            return []

        now = time.time()
        with self._uia_lock:
            if now - self._last_ui_time < self.UIA_DETECT_INTERVAL:
                return self._last_ui_result

        try:
            import uiautomation as uia
            foreground = await asyncio.to_thread(uia.GetForegroundControl)
            if foreground is None:
                return []

            parsed: list[dict[str, Any]] = []
            await asyncio.to_thread(self._walk_uia_tree, foreground, parsed, 3, 0)

            with self._uia_lock:
                self._last_ui_time = now
                self._last_ui_result = parsed
            return parsed
        except Exception as e:
            self._get_logger().warning(f"[RealtimeDetector] UIA 检测异常: {e}")
            return []

    def _walk_uia_tree(
        self,
        control,
        results: list[dict[str, Any]],
        max_depth: int,
        current_depth: int,
    ):
        """递归遍历 UIAutomation 控件树"""
        if current_depth > max_depth:
            return
        try:
            rect = control.BoundingRectangle
            if rect and rect.width() > 2 and rect.height() > 2:
                name = control.Name or ""
                ctrl_type = control.ControlTypeName or "Unknown"
                # 只保留有意义的控件：有名字、或可交互类型
                if name or ctrl_type in (
                    "Button", "Edit", "ComboBox", "ListItem",
                    "Hyperlink", "MenuItem", "TabItem", "TreeItem",
                ):
                    results.append({
                        "class": ctrl_type,
                        "bbox": [
                            float(rect.left), float(rect.top),
                            float(rect.right), float(rect.bottom)
                        ],
                        "name": name,
                        "automation_id": control.AutomationId or "",
                        "source": "uia",
                    })
        except Exception:
            pass

        if current_depth < max_depth:
            try:
                for child in control.GetChildren():
                    self._walk_uia_tree(child, results, max_depth, current_depth + 1)
            except Exception:
                pass

    # ───────────────────────────────────────────────────────────────
    # 【P2新增】边缘检测 + 轮廓提取
    # ───────────────────────────────────────────────────────────────

    async def _extract_contours(
        self, frame: np.ndarray, ocr_boxes: list[list[float]] | None = None
    ) -> list[dict[str, Any]]:
        """
        【P2-类人视觉感知】边缘检测 + 轮廓提取（异步线程安全）
        找出 UIA/OCR 无法识别的纯图形 UI 元素（如图标、无字按钮）。
        """
        self._get_logger().warning(f"[RealtimeDetector] _extract_contours 被调用, frame_shape={frame.shape}")
        try:
            from core.vision.vision_candidate_extractor import extract_contour_candidates
            return await asyncio.to_thread(extract_contour_candidates, frame, ocr_boxes)
        except Exception as e:
            self._get_logger().warning(f"[RealtimeDetector] 轮廓提取失败: {e}", exc_info=True)
            return []

    # ───────────────────────────────────────────────────────────────
    # 主入口：合并四源结果（ONNX + OCR + UIA + Contour）
    # ───────────────────────────────────────────────────────────────

    def _run_onnx_sync(self, frame: np.ndarray):
        """ONNX 推理同步包装（供 to_thread 调用）"""
        input_tensor = self._preprocess(frame)
        if input_tensor is None:
            return None, "预处理失败", "unknown"
        outputs = self._session.run(None, {self._input_name: input_tensor})
        onnx_objs, layout_summary, dominant_app = self._postprocess_onnx(
            outputs, frame.shape[:2]
        )
        return onnx_objs, layout_summary, dominant_app

    async def detect(self, frame: np.ndarray) -> dict[str, Any]:
        """
        对单帧画面执行多源融合检测（全异步线程安全）

        Returns:
            {
                "timestamp": float,
                "objects": List[Dict],   # 统一格式，带 "source" 字段
                "dominant_app": str,
                "layout_summary": str,
                "frame_path": str,       # 【训练模式】完整截图路径（可选）
            }
        """
        timestamp = time.time()
        all_objects: list[dict[str, Any]] = []

        # 【训练模式】ONNX 训练模式下保存完整帧，供未知元素标注使用
        frame_path = None
        try:
            from core.config import config
            if config.get("features.onnx_training_mode.enabled", False):
                frames_dir = Path(__file__).parent.parent.parent / "data" / "frames"
                frames_dir.mkdir(parents=True, exist_ok=True)
                # 保留最近 200 张帧，防止磁盘爆炸
                existing = sorted(frames_dir.glob("*.png"), key=lambda p: p.stat().st_mtime)
                for old in existing[:-199]:
                    old.unlink(missing_ok=True)
                frame_path = str(frames_dir / f"frame_{int(timestamp*1000)}.png")
                await asyncio.to_thread(cv2.imwrite, frame_path, frame)
        except Exception:
            pass  # 训练模式保存失败不影响主流程

        # 1. ONNX 通用物体检测（每帧必跑，丢线程池保事件循环）
        if self._onnx_initialized and self._session is not None:
            try:
                onnx_result = await asyncio.to_thread(self._run_onnx_sync, frame)
                if onnx_result[0] is not None:
                    onnx_objs, layout_summary, dominant_app = onnx_result
                    all_objects.extend(onnx_objs)
                else:
                    layout_summary = onnx_result[1]
                    dominant_app = onnx_result[2]
            except Exception as e:
                self._get_logger().warning(f"[RealtimeDetector] ONNX 推理异常: {e}")
                layout_summary = f"ONNX 推理异常: {str(e)[:50]}"
                dominant_app = "unknown"
        else:
            # ONNX 未加载，只返回窗口信息
            win_info = _get_foreground_window_info()
            dominant_app = win_info.get("process", "unknown")
            title = win_info.get("title", "")
            layout_summary = (
                f"当前前台窗口：{title}（{dominant_app}）"
                if title else f"当前前台应用：{dominant_app}"
            )

        # 2. EasyOCR 文本检测（频率缓存，异步线程安全）
        ocr_objs = await self._detect_text(frame)
        all_objects.extend(ocr_objs)

        # 3. UIAutomation 控件检测（频率缓存，异步线程安全）
        uia_objs = await self._detect_ui_controls()
        all_objects.extend(uia_objs)

        # 4. 【P2新增】轮廓提取（边缘检测 + findContours，异步线程安全）
        #    找出 UIA/OCR 无法识别的纯图形 UI 元素
        ocr_boxes = [obj["bbox"] for obj in ocr_objs if "bbox" in obj]
        contour_objs = await self._extract_contours(frame, ocr_boxes)
        all_objects.extend(contour_objs)

        # 构造 layout_summary 增强描述
        source_counts = {}
        for obj in all_objects:
            src = obj.get("source", "unknown")
            source_counts[src] = source_counts.get(src, 0) + 1

        extra_parts = []
        if source_counts.get("ocr", 0) > 0:
            extra_parts.append(f"发现 {source_counts['ocr']} 处文本")
        if source_counts.get("uia", 0) > 0:
            extra_parts.append(f"发现 {source_counts['uia']} 个 UI 控件")
        if extra_parts:
            layout_summary += "；" + "，".join(extra_parts)

        return {
            "timestamp": timestamp,
            "objects": all_objects,
            "dominant_app": dominant_app,
            "layout_summary": layout_summary,
            "frame_path": frame_path,
        }
