#!/usr/bin/env python3
"""
未知元素发现与打标签模块
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
职责：当视觉系统发现不认识的东西时，自动截图，调用大模型识别，
      将结果存入向量记忆库。下次再遇到同类元素，直接从记忆库调取。

设计原则：
- 大脑与感官解耦：任何失败不得中断 AgentLoop 主循环
- 所有异步方法正确 await
- 所有异常显式日志，不得静默失败
"""

import asyncio
import base64
import hashlib
import json
import os
import re
import time
from collections import deque
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from core.logger import logger

# ═══════════════════════════════════════════════════════════════════════════════
# 【紧急手术】视觉未知元素发现总控开关 —— 默认关闭，防止启动即疯狂调用视觉模型
# ═══════════════════════════════════════════════════════════════════════════════
_vision_discovery_enabled = False

def enable_vision_discovery():
    """开启视觉未知元素自动发现与标注"""
    global _vision_discovery_enabled
    _vision_discovery_enabled = True
    logger.info("[VisionUnknownDiscovery] 视觉未知元素发现已开启")

def disable_vision_discovery():
    """关闭视觉未知元素自动发现与标注"""
    global _vision_discovery_enabled
    _vision_discovery_enabled = False
    logger.info("[VisionUnknownDiscovery] 视觉未知元素发现已关闭")

def is_vision_discovery_enabled() -> bool:
    """获取视觉未知元素发现开关状态"""
    return _vision_discovery_enabled


# ═══════════════════════════════════════════════════════════════════════════════
# 【P0修复】训练数据保存路径
# ═══════════════════════════════════════════════════════════════════════════════
_TRAINING_BASE_DIR = Path(__file__).parent.parent.parent / "training_data" / "ui_elements"
_TRAINING_IMAGES_DIR = _TRAINING_BASE_DIR / "images"
_TRAINING_FRAMES_DIR = _TRAINING_BASE_DIR / "frames"  # 【训练模式】完整截图保存目录
_TRAINING_LABELS_FILE = _TRAINING_BASE_DIR / "labels.jsonl"


# ═══════════════════════════════════════════════════════════════════════════════
# 【P0修复】视觉记忆索引：基于图像内容 hash 的本地快速召回
# ═══════════════════════════════════════════════════════════════════════════════
_VISUAL_MEMORY_INDEX: dict[str, dict[str, Any]] = {}
_VISUAL_MEMORY_LOADED = False

# ═══════════════════════════════════════════════════════════════════════════════
# 【V2新增】感知哈希视觉记忆索引（替代 md5，对压缩/偏移/悬停鲁棒）
# ═══════════════════════════════════════════════════════════════════════════════
_VISUAL_MEMORY_INDEX_PHASH: dict[str, dict[str, Any]] = {}

_PHASH_THRESHOLDS = {
    "button": 8,      # 按钮容忍悬停变色、高亮状态
    "icon": 3,        # 图标要求精确匹配
    "input": 6,       # 输入框容忍边框变化
    "text": 10,       # 文本标签对颜色/背景不敏感
    "default": 5,
}


def compute_phash(img: np.ndarray) -> str:
    """计算感知哈希：aHash(8x8均值) + dHash(8x9差异)"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img

    # aHash: 8x8 均值哈希
    small = cv2.resize(gray, (8, 8), interpolation=cv2.INTER_AREA)
    avg = small.mean()
    a_hash = ''.join(['1' if p >= avg else '0' for p in small.flatten()])

    # dHash: 8x9 横向差异哈希
    small_d = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    d_hash = ''.join([
        '1' if small_d[r, c] < small_d[r, c+1] else '0'
        for r in range(8) for c in range(8)
    ])

    return f"{a_hash}_{d_hash}"


def hamming_distance(hash1: str, hash2: str) -> int:
    """计算两个感知哈希的汉明距离（仅比较 aHash 部分，64bit）"""
    h1, h2 = hash1.split('_')[0], hash2.split('_')[0]
    return sum(c1 != c2 for c1, c2 in zip(h1, h2, strict=False))


def _get_phash_threshold(element_type: str, has_text: bool = False) -> int:
    """按元素类型获取动态感知哈希阈值"""
    if has_text:
        return 8
    return _PHASH_THRESHOLDS.get(element_type, _PHASH_THRESHOLDS["default"])


def _get_visual_memory_key_phash(sub_image: np.ndarray, bbox: list[float]) -> str:
    """生成感知哈希 key：phash + 宽高比（二次校验用）"""
    phash = compute_phash(sub_image)
    w = int(bbox[2] - bbox[0]) if len(bbox) >= 4 else 0
    h = int(bbox[3] - bbox[1]) if len(bbox) >= 4 else 0
    aspect_ratio = round(w / h, 2) if h > 0 else 0.0
    return f"{phash}_{aspect_ratio}"



def _ensure_training_dirs() -> None:
    """确保训练数据目录存在。"""
    _TRAINING_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    _TRAINING_FRAMES_DIR.mkdir(parents=True, exist_ok=True)


def _try_load_visual_memory() -> None:
    """
    从 labels.jsonl 加载已有标注到内存索引。
    key 为图像 md5 前 12 位 + 尺寸指纹，实现"见过即认识"。
    """
    global _VISUAL_MEMORY_LOADED, _VISUAL_MEMORY_INDEX
    if _VISUAL_MEMORY_LOADED:
        return
    if not _TRAINING_LABELS_FILE.exists():
        _VISUAL_MEMORY_LOADED = True
        return
    try:
        loaded = 0
        with open(_TRAINING_LABELS_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    element_id = record.get("element_id", "")
                    if element_id:
                        # element_id 格式: elem_{bbox_key}_{img_hash}
                        parts = element_id.split("_")
                        if len(parts) >= 3:
                            img_hash = parts[-1]
                            h = record.get("bbox", [0, 0, 0, 0])
                            size_key = f"{int(h[2]-h[0])}x{int(h[3]-h[1])}" if len(h) >= 4 else "unknown"
                            mem_key = f"{img_hash}_{size_key}"
                            _VISUAL_MEMORY_INDEX[mem_key] = {
                                "label": {
                                    "element_type": record.get("label", "未知元素"),
                                    "function": record.get("sub_label", "未知功能"),
                                    "interaction": record.get("description", "click"),
                                },
                                "timestamp": record.get("timestamp", 0),
                            }
                            loaded += 1
                except Exception:
                    continue
        logger.info(f"[VisionUnknownDiscovery] 视觉记忆索引加载完成: {loaded} 条")
    except Exception as e:
        logger.warning(f"[VisionUnknownDiscovery] 加载视觉记忆索引失败: {e}")
    finally:
        _VISUAL_MEMORY_LOADED = True


def _get_visual_memory_key(sub_image: np.ndarray, bbox: list[float]) -> str:
    """生成子图的内容指纹 key。"""
    img_hash = hashlib.md5(sub_image.tobytes()).hexdigest()[:12]
    w = int(bbox[2] - bbox[0]) if len(bbox) >= 4 else 0
    h = int(bbox[3] - bbox[1]) if len(bbox) >= 4 else 0
    return f"{img_hash}_{w}x{h}"


def _sanitize_filename(text: str) -> str:
    """将文本转换为合法文件名（保留中英文、数字、下划线，过滤PUA/全角/隐形字符）。"""
    if not text:
        return "unknown"
    text = str(text)
    # 步骤1：删除绝对不允许的字符（控制字符、零宽字符、PUA私有区、全角空格）
    text = re.sub(
        r'[\u0000-\u001F\u007F-\u009F'
        r'\u200B-\u200F\uFEFF\u2060'
        r'\uE000-\uF8FF'
        r'\u3000]+',
        '', text
    )
    # 步骤2：只保留安全字符（ASCII字母数字下划线 + CJK基本区 + CJK扩展A区）
    sanitized = re.sub(r'[^0-9A-Za-z_\u4E00-\u9FFF\u3400-\u4DBF]+', '_', text).strip('_')
    # 步骤3：压缩连续下划线
    sanitized = re.sub(r'_+', '_', sanitized)
    return sanitized[:50] or "unknown"


def _save_training_sample(
    sub_image: np.ndarray,
    label: dict[str, str],
    obj: dict[str, Any],
    idx: int,
    context: dict[str, str] | None = None,
    frame_path: str | None = None,
) -> None:
    """
    将未知元素子图和标签保存为训练数据。

    【训练模式】如果提供了 frame_path（完整截图路径），将其复制到训练目录，
    并在 labels.jsonl 中记录，供后续导出 YOLO 训练集使用。

    失败时记录 error 但不抛出异常，不中断主流程。
    """
    try:
        _ensure_training_dirs()
        timestamp_ms = int(time.time() * 1000)
        bbox_key = _get_bbox_key(obj.get("bbox", [0, 0, 0, 0]))
        img_hash = hashlib.md5(sub_image.tobytes()).hexdigest()[:12]
        element_id = f"elem_{bbox_key}_{img_hash}"
        sanitized_label = _sanitize_filename(label.get("element_type", "unknown"))
        filename = f"{timestamp_ms}_{element_id}_{sanitized_label}.png"
        filepath = _TRAINING_IMAGES_DIR / filename

        # 去重：同一 element_id + label 组合已存在则跳过
        pattern = f"*_{element_id}_{sanitized_label}.png"
        if list(_TRAINING_IMAGES_DIR.glob(pattern)):
            logger.debug(f"[VisionUnknownDiscovery] 训练样本已存在，跳过: {filename}")
            return

        # 【P0修复】OpenCV imwrite 在 Windows 上对 Unicode 路径支持不完善，
        # 改用 imencode + tofile，确保 Unicode 路径正确写入。
        success, encoded = cv2.imencode('.png', sub_image)
        if not success:
            raise RuntimeError("PNG 编码失败")
        encoded.tofile(str(filepath))

        # 【训练模式】复制完整截图到训练目录
        saved_frame_path = None
        if frame_path and os.path.exists(frame_path):
            try:
                frame_filename = f"{timestamp_ms}_{element_id}_frame.png"
                frame_dest = _TRAINING_FRAMES_DIR / frame_filename
                import shutil
                shutil.copy2(frame_path, str(frame_dest))
                saved_frame_path = str(frame_dest.relative_to(_TRAINING_BASE_DIR))
            except Exception as e:
                logger.warning(f"[VisionUnknownDiscovery] 复制完整截图失败: {e}")

        ctx = context or {}
        record = {
            "image": str(filepath.relative_to(_TRAINING_BASE_DIR)),
            "label": label.get("element_type", "unknown"),
            "sub_label": label.get("function", ""),
            "description": label.get("interaction", ""),
            "source": obj.get("source", "unknown"),
            "confidence": obj.get("confidence", 0.0),
            "timestamp": timestamp_ms,
            "element_id": element_id,
            "bbox": obj.get("bbox", []),
            # 【训练模式】完整截图路径
            "frame_path": saved_frame_path,
            # 【P1修复】场景关联字段
            "app_name": ctx.get("app_name", ""),
            "window_title": ctx.get("window_title", ""),
            "page_state": ctx.get("page_state", ""),
        }

        with open(_TRAINING_LABELS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        # 【P0修复】同步写入视觉记忆索引，实现即时召回
        mem_key = _get_visual_memory_key(sub_image, obj.get("bbox", [0, 0, 0, 0]))
        _VISUAL_MEMORY_INDEX[mem_key] = {
            "label": label,
            "timestamp": timestamp_ms,
        }

        # 【V2新增】同步写入感知哈希索引，对压缩/偏移/悬停鲁棒
        try:
            phash_key = _get_visual_memory_key_phash(sub_image, obj.get("bbox", [0, 0, 0, 0]))
            _VISUAL_MEMORY_INDEX_PHASH[phash_key] = {
                "label": label,
                "timestamp": timestamp_ms,
            }
        except Exception:
            pass

        logger.info(f"[VisionUnknownDiscovery] 训练样本已保存: {filename}")
    except Exception as e:
        logger.error(f"[VisionUnknownDiscovery] 保存训练数据失败: {e}", exc_info=False)

# 视觉理解工具（大视觉模型入口）
try:
    from tools.visual_understand import VisualUnderstand
    _visual_understand_tool = VisualUnderstand()
except ImportError as e:
    logger.warning(f"[VisionUnknownDiscovery] VisualUnderstand 导入失败: {e}")
    _visual_understand_tool = None

# 【P0修复】降级跳过日志冷却，防止刷屏
_last_degraded_skip_log_time = 0
DEGRADED_SKIP_LOG_INTERVAL = 60

# 【修复】跨帧去重缓存：{bbox_key: timestamp}
_CROSS_FRAME_CACHE: dict[str, float] = {}
_CROSS_FRAME_CACHE_TTL = 30

# 【P1修复】降级缓存队列：视觉模型降级时暂存未知元素，恢复后批量重试
# 每个元素存储 {"obj": dict, "image_b64": str}
_DEGRADED_BUFFER: deque = deque(maxlen=50)
_DEGRADED_BUFFER_MAX_PER_FRAME = 5  # 每帧最多处理积压数


# ── 已知 UIA 控件类型：这些不需要 AI 重新标注 ──
_KNOWN_UIA_CONTROL_TYPES = {
    "Button", "Edit", "ComboBox", "ListItem", "Hyperlink",
    "MenuItem", "TabItem", "TreeItem", "CheckBox", "RadioButton",
    "Slider", "Spinner", "ToolBar", "StatusBar", "ScrollBar",
    "ProgressBar", "DataItem", "SplitButton", "ToggleButton",
    "List", "Menu", "Tab", "Tree", "Table",
}

# ── 模糊/容器 UIA 类型：通常没有明确交互语义，需要标注 ──
_AMBIGUOUS_UIA_TYPES = {
    "Pane", "Group", "Unknown", "Custom", "Document",
    "Window", "TitleBar", "Separator", "Thumb",
}


def _get_bbox_key(bbox: list[float]) -> str:
    """将 bbox 量化为 20px 网格的稳定 key。"""
    if not bbox or len(bbox) < 4:
        return "unknown"
    x1, y1, x2, y2 = bbox
    return f"{int(x1) // 20}_{int(y1) // 20}_{int(x2) // 20}_{int(y2) // 20}"


def _iou(box_a: list[float], box_b: list[float]) -> float:
    """计算两个 bbox [x1,y1,x2,y2] 的 IoU。"""
    x1 = max(box_a[0], box_b[0])
    y1 = max(box_a[1], box_b[1])
    x2 = min(box_a[2], box_b[2])
    y2 = min(box_a[3], box_b[3])
    inter_w = max(0, x2 - x1)
    inter_h = max(0, y2 - y1)
    inter_area = inter_w * inter_h
    area_a = (box_a[2] - box_a[0]) * (box_a[3] - box_a[1])
    area_b = (box_b[2] - box_b[0]) * (box_b[3] - box_b[1])
    union_area = area_a + area_b - inter_area
    return inter_area / union_area if union_area > 0 else 0.0


def _dedup_same_frame(objects: list[dict[str, Any]], iou_thresh: float = 0.5) -> list[dict[str, Any]]:
    """同帧 IoU 去重，小框优先保留（内部元素优先于父容器）。"""
    # 【P0修复】先过滤掉面积过大的框（>屏幕50%），避免全屏窗口框吞没内部元素
    filtered = []
    try:
        import ctypes
        screen_area = ctypes.windll.user32.GetSystemMetrics(0) * ctypes.windll.user32.GetSystemMetrics(1)
    except Exception:
        screen_area = 1920 * 1080

    for obj in objects:
        bbox = obj.get("bbox", [])
        if len(bbox) == 4:
            area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
            if area > screen_area * 0.5:
                continue  # 跳过覆盖超过半屏的容器框
        filtered.append(obj)

    # 【P0修复】改为按面积从小到大排序（小框优先保留）
    sorted_objs = sorted(
        filtered,
        key=lambda o: (
            (o.get("bbox", [0, 0, 0, 0])[2] - o.get("bbox", [0, 0, 0, 0])[0]) *
            (o.get("bbox", [0, 0, 0, 0])[3] - o.get("bbox", [0, 0, 0, 0])[1])
        ),
    )
    kept: list[dict[str, Any]] = []
    for obj in sorted_objs:
        bbox = obj.get("bbox")
        if not bbox or len(bbox) < 4:
            continue
        overlap = False
        for k in kept:
            kbbox = k.get("bbox")
            if kbbox and len(kbbox) >= 4 and _iou(bbox, kbbox) > iou_thresh:
                overlap = True
                break
        if not overlap:
            kept.append(obj)
    return kept


def _clean_cross_frame_cache(now: float) -> None:
    """清理跨帧缓存中已过期的条目。"""
    global _CROSS_FRAME_CACHE
    expired = [k for k, ts in _CROSS_FRAME_CACHE.items() if now - ts > _CROSS_FRAME_CACHE_TTL]
    for k in expired:
        del _CROSS_FRAME_CACHE[k]


def _encode_frame_to_base64(frame: np.ndarray) -> str:
    """将 OpenCV 帧编码为 base64 字符串（JPEG，质量85%）。"""
    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 85]
    success, buffer = cv2.imencode(".jpg", frame, encode_param)
    if not success:
        raise RuntimeError("JPEG 编码失败")
    return base64.b64encode(buffer).decode("utf-8")


def _check_sub_image_quality(sub_image: np.ndarray) -> tuple:
    """
    【P1修复】子图质量检查，过滤模糊图和纯色块。

    Returns:
        (passed: bool, reason: str)
    """
    if sub_image.size == 0:
        return False, "空图像"
    h, w = sub_image.shape[:2]
    # 【修复】Ollama qwen3-vl SmartResize panic：图片维度 < 32 会崩溃
    if h < 32 or w < 32:
        return False, f"尺寸过小({w}x{h})，低于Ollama安全阈值32px"

    gray = cv2.cvtColor(sub_image, cv2.COLOR_BGR2GRAY) if len(sub_image.shape) == 3 else sub_image

    # 拉普拉斯方差：检查模糊度
    lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    if lap_var < 30:
        return False, f"过于模糊(Lap_var={lap_var:.1f})"

    # 颜色标准差：排除纯色块
    if len(sub_image.shape) == 3:
        std = np.std(sub_image)
        if std < 8:
            return False, f"接近纯色(std={std:.1f})"

    return True, ""


def _is_unknown_element(obj: dict[str, Any]) -> bool:
    """
    判断一个视觉对象是否为"未知元素"。

    【P0修复】按检测来源和控件类型精细区分：
    - UIA：有明确交互类型的控件（Button/Edit/MenuItem 等）→ 已知，跳过
            模糊容器类型（Pane/Group/Unknown）→ 可能未知
    - OCR：纯文本标签，不是交互元素 → 跳过，不标注
    - ONNX：confidence 高说明是 80 类 COCO 日常物体 → 按 confidence 判断
    - contour：轮廓元素 → 检查面积和置信度，过滤噪点
    """
    source = obj.get("source", "")
    class_name = obj.get("class", "")

    if source == "uia":
        ctrl_type = class_name or obj.get("control_type", "")
        # 【P0修复】过滤覆盖面积过大的顶层容器（根窗口/全屏Pane）
        bbox = obj.get("bbox", [])
        if len(bbox) == 4:
            area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
            try:
                import ctypes
                screen_w = ctypes.windll.user32.GetSystemMetrics(0)
                screen_h = ctypes.windll.user32.GetSystemMetrics(1)
            except Exception:
                screen_w, screen_h = 1920, 1080
            if area > screen_w * screen_h * 0.75:
                return False  # 覆盖超过75%屏幕面积的框不是UI元素
        # 明确可交互控件：已经认识，不需要 AI 重标
        if ctrl_type in _KNOWN_UIA_CONTROL_TYPES:
            return False
        # 模糊容器：可能是未知自定义控件
        if ctrl_type in _AMBIGUOUS_UIA_TYPES:
            return True
        # 有名字的控件，通常也有明确语义
        return not obj.get("name", "").strip()

    if source == "ocr":
        # OCR 文本是标签/描述，不是交互元素本身
        # 除非文字很短（如"确定"/"取消"）且 confidence 高，否则不视为未知 UI 元素
        text = obj.get("text", obj.get("name", "")).strip()
        return text in ("确定", "取消", "提交", "保存", "关闭", "OK", "Cancel", "Save", "Close")  # 短文本按钮需要标注其交互方式

    if source == "onnx":
        confidence = obj.get("confidence", 0.0)
        return confidence < 0.7

    if class_name == "contour" or source == "contour":
        area = obj.get("area", 0)
        confidence = obj.get("confidence", 0.0)
        # 过滤过小轮廓和过低置信度
        return not (area < 500 or confidence < 0.5)

    # 默认兜底：未知
    return True


def _crop_region(frame: np.ndarray, bbox: list[float]) -> np.ndarray:
    """
    从帧中按 bbox 裁剪子图。
    bbox 格式: [x1, y1, x2, y2]（浮点或整数像素坐标）
    """
    h, w = frame.shape[:2]
    x1 = max(0, int(bbox[0]))
    y1 = max(0, int(bbox[1]))
    x2 = min(w, int(bbox[2]))
    y2 = min(h, int(bbox[3]))

    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"非法 bbox: {bbox}")

    return frame[y1:y2, x1:x2]


async def _try_recall_from_memory(
    obj: dict[str, Any],
    sub_image: np.ndarray,
    app_name: str = "",
) -> dict[str, str] | None:
    """
    【P0修复】标注前先查记忆库，避免重复调用 AI。

    召回优先级：
    1. 本地视觉记忆索引（图像内容 hash，最快）
    2. LabelCache（同应用 + 元素描述）
    3. 向量记忆库（语义相似度）

    Returns:
        已知的 label dict 或 None
    """
    bbox = obj.get("bbox", [0, 0, 0, 0])

    # 1. 【V2新增】感知哈希视觉记忆索引（优先，对像素级变化鲁棒）
    try:
        current_phash = compute_phash(sub_image)
        current_ratio = round(
            (bbox[2] - bbox[0]) / (bbox[3] - bbox[1]), 2
        ) if len(bbox) >= 4 and bbox[3] > bbox[1] else 0.0
        element_type = (obj.get("class", "") or obj.get("source", "default")).lower()
        has_text = bool(obj.get("text", obj.get("name", "")).strip())
        threshold = _get_phash_threshold(element_type, has_text)

        best_match = None
        best_dist = 999

        for phash_key, cached in _VISUAL_MEMORY_INDEX_PHASH.items():
            try:
                stored_phash, stored_ratio_str = phash_key.rsplit('_', 1)
                stored_ratio = float(stored_ratio_str)
                dist = hamming_distance(current_phash, stored_phash)
                ratio_diff = abs(current_ratio - stored_ratio) / max(current_ratio, stored_ratio, 0.01)

                if dist <= threshold and ratio_diff < 0.2 and dist < best_dist:
                    best_dist = dist
                    best_match = cached
            except Exception:
                continue

        if best_match:
            label = best_match.get("label")
            logger.info(
                f"[VisionUnknownDiscovery] 感知哈希命中(Hamming={best_dist}): "
                f"{label.get('element_type', '?')}"
            )
            return label
    except Exception as e:
        logger.debug(f"[VisionUnknownDiscovery] 感知哈希召回失败: {e}")

    # 2. 本地 md5 视觉记忆索引（兼容旧数据）
    mem_key = _get_visual_memory_key(sub_image, bbox)
    cached = _VISUAL_MEMORY_INDEX.get(mem_key)
    if cached:
        label = cached.get("label")
        logger.info(
            f"[VisionUnknownDiscovery] md5 视觉记忆索引命中: "
            f"{label.get('element_type', '?')}"
        )
        return label

    # 3. LabelCache：同应用 + 元素名称/描述
    try:
        from core.vision.label_cache import get_label_cache
        cache = get_label_cache()
        # 尝试用 UIA 的 name 或 class 做描述查询
        desc = obj.get("name", obj.get("text", obj.get("class", ""))).strip()
        if desc and app_name:
            hit = cache.get_full(app_name, desc)
            if hit:
                logger.info(
                    f"[VisionUnknownDiscovery] LabelCache 命中: app={app_name}, desc={desc}"
                )
                return {
                    "element_type": hit.get("description", desc) or desc,
                    "function": hit.get("description", ""),
                    "interaction": hit.get("tags", ["click"])[0] if hit.get("tags") else "click",
                }
    except Exception as e:
        logger.debug(f"[VisionUnknownDiscovery] LabelCache 查询失败: {e}")

    # 3. 向量记忆库：语义相似度查询
    try:
        from core.vision.vision_element_knowledge import query_ui_knowledge
        features = (
            f"UI元素: {obj.get('class', '未知')} "
            f"名称: {obj.get('name', obj.get('text', ''))} "
            f"来源: {obj.get('source', 'unknown')}"
        )
        results = await query_ui_knowledge(features=features, limit=3)
        for r in results:
            sim = r.get("similarity", 0.0)
            if sim > 0.85:
                logger.info(
                    f"[VisionUnknownDiscovery] 向量记忆库命中(sim={sim:.2f}): "
                    f"{r.get('element_type', '?')}"
                )
                return {
                    "element_type": r.get("element_type", "未知元素"),
                    "function": r.get("function", "未知功能"),
                    "interaction": r.get("interaction", "click"),
                }
    except Exception as e:
        logger.debug(f"[VisionUnknownDiscovery] 向量记忆库查询失败: {e}")

    return None


async def _call_vision_model_for_label(
    image_b64: str,
    context: dict[str, str] | None = None,
) -> dict[str, str] | None:
    """
    调用大视觉模型对裁剪后的子图进行识别。

    Args:
        image_b64: base64 编码的子图
        context: 场景上下文，包含 app_name/window_title/page_state

    Returns:
        结构化标签 dict
    """
    if _visual_understand_tool is None:
        logger.warning("[VisionUnknownDiscovery] VisualUnderstand 不可用，跳过标注")
        return None

    # 【修复】prompt 极简统一，避免塞满 2B 模型上下文窗口
    ctx = context or {}
    app_hint = ctx.get("app_name", "")
    # 只用应用名做最简短的上下文提示，不用 window_title/page_state（过长且含调试信息）
    prefix = f"[{app_hint}] " if app_hint and app_hint != "unknown" else ""

    question = (
        f"{prefix}Identify this UI element. Output ONLY a JSON object with keys: "
        'element_type, function, interaction. No extra text.'
    )

    try:
        result = await _visual_understand_tool._execute_async(
            image_source=image_b64,
            question=question,
        )

        if not result or not result.get("success"):
            err = result.get("error_code") if result else "空结果"
            logger.debug(f"[VisionUnknownDiscovery] 视觉模型调用失败: {err}")
            return None

        data = result.get("data", {})
        description = data.get("description", "")

        if data.get("degraded") is True:
            return None

        _error_keywords = ["降级", "无法获取", "错误", "Error", "failed", "不可用", "请依赖"]
        if description and any(kw in description for kw in _error_keywords):
            logger.warning(
                f"[VisionUnknownDiscovery] 视觉模型返回错误信息，跳过标注: {description[:60]}"
            )
            return None

        json_str = _extract_json_block(description)
        if json_str:
            parsed = json.loads(json_str)
            element_type = str(parsed.get("element_type", "未知元素")).replace("\n", " ").replace("\r", " ").strip()[:30]
            function_desc = str(parsed.get("function", "未知功能")).replace("\n", " ").replace("\r", " ").strip()[:50]
            interaction = str(parsed.get("interaction", "click")).replace("\n", " ").replace("\r", " ").strip()[:20]
            return {
                "element_type": element_type,
                "function": function_desc,
                "interaction": interaction,
                # 【字段兼容】同时包含训练数据格式的字段名，确保与 labels.jsonl 互通
                "label": element_type,
                "sub_label": function_desc,
                "description": interaction,
            }

        logger.debug(f"[VisionUnknownDiscovery] 无法解析 JSON，降级为纯文本: {description[:80]}")
        description_clean = (description or "").replace("\n", " ").replace("\r", " ").strip()
        element_type = description_clean[:30] or "未知元素"
        return {
            "element_type": element_type,
            "function": "需进一步确认",
            "interaction": "click",
            # 【字段兼容】同时包含训练数据格式的字段名
            "label": element_type,
            "sub_label": "需进一步确认",
            "description": "click",
        }

    except asyncio.TimeoutError:
        logger.warning("[VisionUnknownDiscovery] 视觉模型调用超时")
        return None
    except Exception as e:
        logger.error(f"[VisionUnknownDiscovery] 视觉模型调用异常: {e}", exc_info=True)
        return None


def _extract_json_block(text: str) -> str | None:
    """从文本中提取第一个 JSON 对象块。"""
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return None


async def discover_and_label_unknowns(
    vision_packet: dict[str, Any],
    original_frame: np.ndarray | None = None,
    frame_path: str | None = None,
    user_id: str = "default",
    context: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """
    主入口：从 VisionInfoPacket 中筛选未知元素，调用大模型打标签。

    Args:
        vision_packet: detect() 返回的字典，含 "objects", "timestamp", ...
        original_frame: 原始帧（numpy BGR 图像）。若未提供，尝试截图获取。
        frame_path: 【训练模式】完整截图的文件路径。训练模式下优先使用，避免二次截图。
        user_id: 用户标识。
        context: 场景上下文，如 {"app_name": "chrome.exe", "window_title": "...", "page_state": "..."}

    Returns:
        被打上标签的未知元素列表，每个元素附加 "ai_label" 字段。
    """
    discovered: list[dict[str, Any]] = []
    ctx = context or {}

    # 【紧急手术】总控开关检查
    if not _vision_discovery_enabled:
        logger.debug("[VisionUnknownDiscovery] 视觉发现已关闭，跳过本帧")
        return discovered

    # 加载视觉记忆索引（延迟加载）
    _try_load_visual_memory()

    objects = vision_packet.get("objects", [])
    if not objects:
        return discovered

    # 筛选未知元素
    unknown_objects = [obj for obj in objects if _is_unknown_element(obj)]
    if not unknown_objects:
        return discovered

    # 降级短路
    if _visual_understand_tool is not None and _visual_understand_tool.is_degraded():
        global _last_degraded_skip_log_time
        now = time.time()
        if now - _last_degraded_skip_log_time >= DEGRADED_SKIP_LOG_INTERVAL:
            logger.warning(
                f"[VisionUnknownDiscovery] 视觉模型降级中，本帧 {len(unknown_objects)} 个未知元素暂存到降级缓冲区"
            )
            _last_degraded_skip_log_time = now

        # 【P0修复】降级时始终缓存（不依赖 original_frame）
        buffered_count = 0
        for obj in unknown_objects[:_DEGRADED_BUFFER_MAX_PER_FRAME]:
            try:
                bbox = obj.get("bbox")
                if bbox and len(bbox) >= 4:
                    _DEGRADED_BUFFER.append({
                        "obj": obj,
                        "image_b64": None,  # 标记为待截图，恢复后现场截取
                    })
                    buffered_count += 1
            except Exception:
                pass
        if buffered_count > 0:
            logger.info(f"[VisionUnknownDiscovery] 降级缓冲：已缓存 {buffered_count} 个元素")
        return discovered

    MAX_LABELS_PER_FRAME = 10
    if len(unknown_objects) > MAX_LABELS_PER_FRAME:
        unknown_objects = sorted(unknown_objects, key=lambda o: o.get("confidence", 1.0))[:MAX_LABELS_PER_FRAME]

    unknown_objects = _dedup_same_frame(unknown_objects, iou_thresh=0.5)

    now = time.time()
    _clean_cross_frame_cache(now)

    logger.info(
        f"[VisionUnknownDiscovery] 检测到 {len(unknown_objects)} 个未知元素，"
        f"启动大模型标注流程 (user={user_id})"
    )

    frame = original_frame
    # 【训练模式】优先使用 frame_path 指向的完整截图，避免二次截图
    if frame is None and frame_path and os.path.exists(frame_path):
        try:
            frame = cv2.imread(frame_path)
            if frame is not None:
                logger.debug(f"[VisionUnknownDiscovery] 使用训练模式截图: {frame_path}")
        except Exception as e:
            logger.warning(f"[VisionUnknownDiscovery] 读取训练截图失败: {e}")

    if frame is None:
        # 【修复】截图前校验：窗口是否仍然是同一个
        try:
            from core.vision.realtime_detector import _get_foreground_window_info
            win_info = _get_foreground_window_info()
            current_app = win_info.get("process", "unknown")
            expected_app = vision_packet.get("dominant_app", "")

            # 窗口不一致 → 跳过
            if expected_app and current_app != expected_app:
                logger.warning(f"[VisionUnknownDiscovery] 窗口已切换 {expected_app}→{current_app}，跳过")
                return []
        except Exception:
            pass

        # 数据太旧 → 跳过（bbox 可能已经过期）
        packet_age = time.time() - vision_packet.get("timestamp", time.time())
        if packet_age > 2.0:
            logger.warning(f"[VisionUnknownDiscovery] 视觉数据已过期 {packet_age:.1f}s，跳过")
            return []

        try:
            from core.vision.safe_screenshot import safe_screenshot_to_numpy
            frame = await asyncio.to_thread(safe_screenshot_to_numpy)
        except Exception as e:
            logger.error(f"[VisionUnknownDiscovery] 截图获取失败: {e}")
            return discovered

    if frame is None or frame.size == 0:
        logger.warning("[VisionUnknownDiscovery] 原始帧为空，无法裁剪")
        return discovered

    # 处理降级缓冲区
    buffered_discovered = []
    if _DEGRADED_BUFFER and (_visual_understand_tool is None or not _visual_understand_tool.is_degraded()):
        backlog_to_process = []
        while _DEGRADED_BUFFER and len(backlog_to_process) < _DEGRADED_BUFFER_MAX_PER_FRAME:
            backlog_to_process.append(_DEGRADED_BUFFER.popleft())

        if backlog_to_process:
            logger.info(
                f"[VisionUnknownDiscovery] 降级恢复，处理缓冲区 {len(backlog_to_process)} 个积压元素"
            )
            for idx, item in enumerate(backlog_to_process):
                try:
                    # 【P0修复】恢复时现场截图（针对降级时未截取的元素）
                    if item.get("image_b64") is None:
                        frame = original_frame
                        if frame is None:
                            try:
                                from core.vision.safe_screenshot import safe_screenshot_to_numpy
                                frame = await asyncio.to_thread(safe_screenshot_to_numpy)
                            except Exception:
                                pass
                        if frame is not None and frame.size > 0:
                            bbox = item["obj"].get("bbox")
                            if bbox and len(bbox) >= 4:
                                sub_image = _crop_region(frame, bbox)
                                if sub_image.size > 0:
                                    item["image_b64"] = _encode_frame_to_base64(sub_image)
                        if item.get("image_b64") is None:
                            continue  # 截图失败，跳过此项

                    label = await _call_vision_model_for_label(item["image_b64"], context=ctx)
                    if label:
                        enriched = {
                            **item["obj"],
                            "ai_label": label,
                            "discovered_at": time.time(),
                            "discovered_by": "vision_unknown_discovery",
                        }
                        buffered_discovered.append(enriched)
                        logger.info(
                            f"[VisionUnknownDiscovery] 积压元素 #{idx + 1} 标注成功: "
                            f"{label['element_type']} | 功能: {label['function']}"
                        )
                except Exception as e:
                    logger.error(
                        f"[VisionUnknownDiscovery] 处理积压元素 #{idx + 1} 异常: {e}",
                        exc_info=False,
                    )

        discovered.extend(buffered_discovered)

    # 逐个处理当前帧未知元素
    for idx, obj in enumerate(unknown_objects):
        bbox = obj.get("bbox")
        if not bbox or len(bbox) < 4:
            continue

        bbox_key = _get_bbox_key(bbox)
        if bbox_key in _CROSS_FRAME_CACHE:
            logger.debug(f"[VisionUnknownDiscovery] 跨帧缓存命中，跳过: {bbox_key}")
            continue

        try:
            sub_image = _crop_region(frame, bbox)
            if sub_image.size == 0:
                continue

            # 【P1修复】子图质量检查
            passed, reason = _check_sub_image_quality(sub_image)
            if not passed:
                logger.debug(f"[VisionUnknownDiscovery] 子图质量检查未通过，跳过: {reason}")
                continue

            # 【P0修复】标注前先查记忆库
            recalled_label = await _try_recall_from_memory(
                obj, sub_image, app_name=ctx.get("app_name", "")
            )
            if recalled_label:
                enriched = {
                    **obj,
                    "ai_label": recalled_label,
                    "discovered_at": time.time(),
                    "discovered_by": "vision_unknown_discovery",
                    "recalled_from": "memory",
                }
                discovered.append(enriched)
                _CROSS_FRAME_CACHE[bbox_key] = time.time()
                logger.info(
                    f"[VisionUnknownDiscovery] 元素 #{idx + 1} 记忆召回成功: "
                    f"{recalled_label['element_type']} | 功能: {recalled_label['function']}"
                )
                continue

            image_b64 = _encode_frame_to_base64(sub_image)
            label = await _call_vision_model_for_label(image_b64, context=ctx)

            if label:
                _save_training_sample(sub_image, label, obj, idx, context=ctx, frame_path=frame_path)

                # 【P0修复】写入 LabelCache，供同应用定位复用
                try:
                    from core.vision.label_cache import get_label_cache
                    cache = get_label_cache()
                    app_name = ctx.get("app_name", "unknown")
                    desc = label.get("element_type", "unknown")
                    if app_name and desc:
                        cache.set_with_tags(
                            app_name=app_name,
                            description=desc,
                            bbox=[int(v) for v in bbox],
                            tags=[label.get("interaction", "click"), obj.get("source", "unknown")],
                            tag_description=label.get("function", ""),
                            source=obj.get("source", "unknown"),
                        )
                except Exception as e:
                    logger.debug(f"[VisionUnknownDiscovery] LabelCache 写入失败: {e}")

                _CROSS_FRAME_CACHE[bbox_key] = time.time()

                enriched = {
                    **obj,
                    "ai_label": label,
                    "discovered_at": time.time(),
                    "discovered_by": "vision_unknown_discovery",
                }
                discovered.append(enriched)
                logger.info(
                    f"[VisionUnknownDiscovery] 元素 #{idx + 1} 标注成功: "
                    f"{label['element_type']} | 功能: {label['function']}"
                )
            else:
                logger.debug(f"[VisionUnknownDiscovery] 元素 #{idx + 1} 标注失败，跳过")

        except Exception as e:
            logger.error(
                f"[VisionUnknownDiscovery] 处理未知元素 #{idx + 1} 异常: {e}",
                exc_info=False,
            )
            continue

    logger.info(
        f"[VisionUnknownDiscovery] 本次标注完成: {len(discovered)}/{len(unknown_objects)} 成功"
    )
    return discovered
