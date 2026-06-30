#!/usr/bin/env python3
"""
vision_candidate_extractor.py —— 边缘检测 + 轮廓提取模块
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【第二阶段 · 类人视觉感知内核】

职责：使用纯 OpenCV 规则（无新模型依赖），从原始像素中找出那些
      UIA 和 OCR 无法识别的纯图形 UI 元素（如图标、无字按钮、滑块等）。

这是模拟人眼"先发现这里有东西"的关键一步：
    1. 转灰度、高斯去噪
    2. Canny 边缘检测 → 找像素亮度变化剧烈处
    3. cv2.findContours() → 连接边缘为闭合轮廓
    4. 形态过滤（面积、宽高比、尺寸）
    5. 去重合并

设计原则：
    - 纯 OpenCV 规则，零额外模型依赖
    - 与 UIA/OCR 候选框合并，不重复检测已有语义元素
    - 轻量快速，可在 33ms 帧循环中运行
"""

import logging
from typing import Any

import numpy as np

logger = logging.getLogger("VisionCandidateExtractor")


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


def extract_contour_candidates(frame: np.ndarray, ocr_boxes: list[list[float]] | None = None) -> list[dict[str, Any]]:
    """
    从桌面截图中提取纯图形 UI 元素的候选框。

    流程：
        1. 转灰度 → 高斯去噪（5x5）
        2. Canny 边缘检测（threshold1=50, threshold2=150）
        3. cv2.findContours() 提取外部轮廓
        4. 形态过滤：
           - 面积 < 100 → 过滤噪点
           - 宽 < 8 或 高 < 8 → 过滤过小
           - 宽高比 < 0.05 或 > 20 → 过滤极端条形
           - 接近全屏 → 过滤窗口外框
        5. 返回候选框列表

    Args:
        frame: BGR 格式的桌面截图 (H, W, 3)

    Returns:
        候选框列表，每项格式：
        {
            "class": "contour",
            "bbox": [x1, y1, x2, y2],   # 像素坐标
            "source": "contour",
            "area": float,              # 轮廓面积
            "confidence": 0.6,          # 轮廓无语义置信度，给中等值
        }
    """
    logger.info(f"[CT-FIX-ENTRY] extract_contour_candidates 被调用, frame_shape={frame.shape}")
    try:
        import cv2
    except ImportError:
        logger.warning("[VisionCandidateExtractor] OpenCV 未安装，跳过轮廓提取")
        return []

    candidates: list[dict[str, Any]] = []

    try:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, threshold1=50, threshold2=150)
        contours, _ = cv2.findContours(
            edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        img_h, img_w = frame.shape[:2]

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 100:          # 过滤微小噪点
                continue

            x, y, w, h = cv2.boundingRect(cnt)
            if w < 8 or h < 8:      # 过滤过小的
                continue

            aspect_ratio = w / max(h, 1)
            if aspect_ratio < 0.05 or aspect_ratio > 20:  # 过滤极端条形
                continue

            # 过滤全屏或接近全屏的轮廓（通常是窗口外框）
            if w > img_w * 0.9 and h > img_h * 0.9:
                continue

            candidates.append({
                "class": "contour",
                "bbox": [float(x), float(y), float(x + w), float(y + h)],
                "center": [float(x + w // 2), float(y + h // 2)],
                "sub_image": frame[y:y+h, x:x+w].copy(),
                "source": "contour",
                "area": float(area),
                "confidence": 0.6,
            })

        # 去重：基于 IoU，保留面积较大的框
        if len(candidates) > 1:
            candidates.sort(key=lambda c: c["area"], reverse=True)
            kept: list[dict[str, Any]] = []
            for c in candidates:
                x1, y1, x2, y2 = c["bbox"]
                c_area = (x2 - x1) * (y2 - y1)
                overlap = False
                for k in kept:
                    kx1, ky1, kx2, ky2 = k["bbox"]
                    inter_x1 = max(x1, kx1)
                    inter_y1 = max(y1, ky1)
                    inter_x2 = min(x2, kx2)
                    inter_y2 = min(y2, ky2)
                    inter_w = max(0, inter_x2 - inter_x1)
                    inter_h = max(0, inter_y2 - inter_y1)
                    inter_area = inter_w * inter_h
                    union_area = c_area + (kx2 - kx1) * (ky2 - ky1) - inter_area
                    if union_area > 0 and inter_area / union_area > 0.5:
                        overlap = True
                        break
                if not overlap:
                    kept.append(c)
            candidates = kept

        # ── 新增过滤阶段 ──────────────────────────────────────────
        total_before = len(candidates)
        filtered: list[dict[str, Any]] = []
        text_filtered = 0
        texture_filtered = 0

        for c in candidates:
            bbox = c["bbox"]
            sub_image = c.get("sub_image")

            # 规则1：排除文字区域（与 OCR 框 IoU > 0.3）
            if ocr_boxes:
                skip = False
                for ocr_box in ocr_boxes:
                    if _iou(bbox, ocr_box) > 0.3:
                        skip = True
                        text_filtered += 1
                        break
                if skip:
                    continue

            # 规则2：排除低纹理/空白区域（拉普拉斯方差 < 50）
            if sub_image is not None and sub_image.size > 0:
                gray_sub = (
                    cv2.cvtColor(sub_image, cv2.COLOR_BGR2GRAY)
                    if len(sub_image.shape) == 3
                    else sub_image
                )
                lap_var = cv2.Laplacian(gray_sub, cv2.CV_64F).var()
                if lap_var < 50:
                    texture_filtered += 1
                    continue

            filtered.append(c)

        candidates = filtered

        # 可视化过滤报告 ──────────────────────────────────────────
        text_filtered + texture_filtered
        kept = len(candidates)
        bar_len = 20
        kept_bar = int(kept / max(total_before, 1) * bar_len)
        filt_bar = bar_len - kept_bar
        bar = "█" * kept_bar + "░" * filt_bar

        report_lines = [
            "",
            "┌─────────────────────────────────────────────────────────┐",
            "│  [CT-FIX] 候选框质量过滤报告                              │",
            f"│  {bar}  {kept}/{total_before} 保留                          │",
            "├─────────────────────────────────────────────────────────┤",
            f"│  输入总数      : {total_before:>5}                                │",
            f"│  └─ 文字过滤   : {text_filtered:>5}  (OCR IoU>0.3)                │",
            f"│  └─ 低纹理过滤 : {texture_filtered:>5}  (Laplacian var<50)        │",
            f"│  最终输出      : {kept:>5}                                │",
            f"│  字段列表      : {list(candidates[0].keys()) if candidates else '无'}  │",
            "└─────────────────────────────────────────────────────────┘",
        ]
        logger.warning("\n".join(report_lines))

        logger.debug(
            f"[VisionCandidateExtractor] 轮廓提取完成: {len(candidates)} 个候选框"
        )

    except Exception as e:
        logger.warning(
            f"[VisionCandidateExtractor] 轮廓提取失败: {e}",
            exc_info=True,
        )
        logger.warning(f"[CT-FIX-ERROR] 轮廓提取异常, candidates_len={len(candidates)}")

    return candidates
