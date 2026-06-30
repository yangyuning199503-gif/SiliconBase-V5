#!/usr/bin/env python3
"""
train_ui_model.py —— UI 元素训练数据预处理脚本
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
职责：在训练轻量 UI 检测模型之前，清理 training_data/ui_elements/ 中的垃圾图片。

过滤规则：
    1. 低纹理/空白区域（拉普拉斯方差 < 50）
    2. 标签含文字（"文字"/"文本"/"text"）
    3. 尺寸畸形（宽/高 < 20px，或宽高比 > 10 或 < 0.1）

输出：
    - 覆盖更新 labels.jsonl（只保留合格记录）
    - rejected/ 目录下存放被过滤的图片（不永久删除，便于人工复核）

用法：
    python train_ui_model.py
"""

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np

# ═══════════════════════════════════════════════════════════════════════════════
# 路径配置
# ═══════════════════════════════════════════════════════════════════════════════
_BASE_DIR = Path(__file__).parent
_TRAINING_DIR = _BASE_DIR / "training_data" / "ui_elements"
_IMAGES_DIR = _TRAINING_DIR / "images"
_LABELS_FILE = _TRAINING_DIR / "labels.jsonl"
_REJECTED_DIR = _TRAINING_DIR / "rejected"

# 拉普拉斯方差阈值：低于此值视为纯色/低纹理空白
_LAPLACIAN_VAR_THRESHOLD = 50

# 尺寸过滤阈值
_MIN_SIZE_PX = 20
_MAX_ASPECT_RATIO = 10.0
_MIN_ASPECT_RATIO = 0.1

# 文字标签关键词（大小写不敏感）
_TEXT_KEYWORDS = ["文字", "文本", "text"]

# 错误/降级信息关键词（视觉模型返回的错误信息被当标签存下）
_ERROR_KEYWORDS = [
    "降级", "无法获取", "错误", "error", "failed",
    "不可用", "请依赖", "视觉模型",
]


def _ensure_dirs() -> None:
    """确保必要目录存在。"""
    _IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    _REJECTED_DIR.mkdir(parents=True, exist_ok=True)


def _is_text_label(label: str) -> bool:
    """判断标签是否为文字类。"""
    if not label:
        return False
    lower = label.lower()
    return any(kw in lower for kw in _TEXT_KEYWORDS)


def _is_error_label(label: str) -> bool:
    """判断标签是否为视觉模型降级/错误信息。"""
    if not label:
        return False
    lower = label.lower()
    return any(kw in lower for kw in _ERROR_KEYWORDS)


def _check_texture(image: np.ndarray) -> tuple[bool, float]:
    """
    检查图片纹理是否足够丰富。
    返回 (是否低纹理, 拉普拉斯方差值)。
    """
    if image is None or image.size == 0:
        return True, 0.0
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    return lap_var < _LAPLACIAN_VAR_THRESHOLD, lap_var


def _check_geometry(image: np.ndarray) -> tuple[bool, str]:
    """
    检查图片尺寸是否畸形。
    返回 (是否畸形, 原因描述)。
    """
    if image is None or image.size == 0:
        return True, "图像为空"
    h, w = image.shape[:2]
    if w < _MIN_SIZE_PX or h < _MIN_SIZE_PX:
        return True, f"尺寸过小({w}x{h})"
    aspect = w / max(h, 1)
    if aspect > _MAX_ASPECT_RATIO:
        return True, f"宽高比过大({aspect:.2f})"
    if aspect < _MIN_ASPECT_RATIO:
        return True, f"宽高比过小({aspect:.2f})"
    return False, ""


def _move_to_rejected(image_path: Path, reason: str) -> None:
    """将被过滤的图片移到 rejected/ 目录。"""
    dest = _REJECTED_DIR / image_path.name
    # 若同名文件已存在，加序号后缀
    if dest.exists():
        stem = image_path.stem
        suffix = image_path.suffix
        for idx in range(1, 9999):
            dest = _REJECTED_DIR / f"{stem}_{idx}{suffix}"
            if not dest.exists():
                break
    try:
        shutil.move(str(image_path), str(dest))
    except Exception as e:
        print(f"[WARN] 移动文件失败: {image_path} -> {dest}: {e}")


def main() -> int:
    """主入口。"""
    _ensure_dirs()

    if not _LABELS_FILE.exists():
        print(f"[ERROR] 标签文件不存在: {_LABELS_FILE}")
        return 1

    # 读取所有记录
    records: list[dict[str, Any]] = []
    with open(_LABELS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[WARN] JSON 解析失败，跳过: {e}")

    total_before = len(records)
    if total_before == 0:
        print("[INFO] 没有记录需要处理。")
        return 0

    kept_records: list[dict[str, Any]] = []
    rejected_count = 0
    stats = {
        "low_texture": 0,
        "text_label": 0,
        "error_label": 0,
        "bad_geometry": 0,
        "read_error": 0,
    }

    print(f"[INFO] 开始清理训练数据，共 {total_before} 条记录 ...")

    for idx, record in enumerate(records, start=1):
        rel_path = record.get("image", "")
        if not rel_path:
            print(f"[WARN] 记录 #{idx} 缺少 image 字段，跳过")
            continue

        image_path = _TRAINING_DIR / rel_path
        label = record.get("label", "")
        reject_reason = None

        # 规则2a：标签含文字
        if _is_text_label(label):
            reject_reason = f"文字标签({label})"
            stats["text_label"] += 1

        # 规则2b：标签为错误/降级信息
        if reject_reason is None and _is_error_label(label):
            reject_reason = f"错误标签({label})"
            stats["error_label"] += 1

        # 读取图片（如果前面没拒绝）
        # 【P0修复】cv2.imread 在 Windows 上对 Unicode 路径支持不完善，
        # 改用 np.fromfile + cv2.imdecode，确保中文路径正常读取。
        image = None
        if reject_reason is None:
            try:
                img_bytes = np.fromfile(str(image_path), dtype=np.uint8)
                image = cv2.imdecode(img_bytes, cv2.IMREAD_UNCHANGED)
            except Exception:
                image = None
            if image is None:
                reject_reason = "读取失败"
                stats["read_error"] += 1

        # 规则1：低纹理
        if reject_reason is None:
            is_low, lap_var = _check_texture(image)
            if is_low:
                reject_reason = f"低纹理(方差={lap_var:.1f})"
                stats["low_texture"] += 1

        # 规则3：尺寸畸形
        if reject_reason is None:
            is_bad, geo_reason = _check_geometry(image)
            if is_bad:
                reject_reason = geo_reason
                stats["bad_geometry"] += 1

        # 执行过滤
        if reject_reason:
            rejected_count += 1
            print(f"[REJECTED] #{idx}: {reject_reason} -> {image_path.name}")
            if image_path.exists():
                _move_to_rejected(image_path, reject_reason)
            continue

        # 保留
        kept_records.append(record)

    # 写回 labels.jsonl（覆盖）
    with open(_LABELS_FILE, "w", encoding="utf-8") as f:
        for rec in kept_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    total_after = len(kept_records)
    print("\n" + "=" * 50)
    print("清理完成")
    print(f"  清理前: {total_before} 张")
    print(f"  清理后: {total_after} 张")
    print(f"  过滤掉: {rejected_count} 张")
    print(f"    - 低纹理:   {stats['low_texture']}")
    print(f"    - 文字标签: {stats['text_label']}")
    print(f"    - 错误标签: {stats['error_label']}")
    print(f"    - 尺寸畸形: {stats['bad_geometry']}")
    print(f"    - 读取失败: {stats['read_error']}")
    print(f"  rejected 目录: {_REJECTED_DIR}")
    print("=" * 50)

    return 0


if __name__ == "__main__":
    sys.exit(main())
