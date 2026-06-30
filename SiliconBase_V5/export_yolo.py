#!/usr/bin/env python3
"""
export_yolo.py —— 从收集的 UI 元素训练数据导出 YOLO 格式数据集
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

用途：
    将 training_data/ui_elements/ 中的 labels.jsonl + 完整截图
    转换为 YOLOv5/YOLOv8 训练格式，用于训练自定义 ONNX 检测模型。

输出结构：
    yolo_dataset/
    ├── images/
    │   └── train/          # 完整截图（复制）
    ├── labels/
    │   └── train/          # YOLO 标注文件（.txt）
    ├── classes.txt         # 类别映射表
    └── dataset.yaml        # YOLO 配置文件

YOLO 标注格式（每行一个目标）：
    class_id x_center y_center width height
    （所有值相对于图像宽高的 0-1 归一化值）

用法：
    python export_yolo.py
"""

import json
import shutil
from collections import Counter
from pathlib import Path

import cv2

# ═══════════════════════════════════════════════════════════════════════════════
# 路径配置
# ═══════════════════════════════════════════════════════════════════════════════
_BASE_DIR = Path(__file__).parent
_TRAINING_DIR = _BASE_DIR / "training_data" / "ui_elements"
_LABELS_FILE = _TRAINING_DIR / "labels.jsonl"
_OUTPUT_DIR = _BASE_DIR / "yolo_dataset"

# 屏幕分辨率（训练数据来源的截图尺寸）
_SCREEN_W = 3840
_SCREEN_H = 2160


def _ensure_output_dirs() -> None:
    """确保输出目录存在。"""
    (_OUTPUT_DIR / "images" / "train").mkdir(parents=True, exist_ok=True)
    (_OUTPUT_DIR / "labels" / "train").mkdir(parents=True, exist_ok=True)


def _collect_records() -> tuple[list[dict], set[str]]:
    """
    读取 labels.jsonl，收集有完整截图的记录和唯一标签。

    Returns:
        (valid_records, unique_labels)
    """
    records = []
    if not _LABELS_FILE.exists():
        print(f"❌ 标签文件不存在: {_LABELS_FILE}")
        return [], set()

    with open(_LABELS_FILE, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            records.append(rec)

    # 只保留有 frame_path 的记录（训练模式开启后才会保存完整截图）
    valid = [r for r in records if r.get("frame_path")]

    # 统计标签
    labels = [r["label"] for r in valid]
    label_counts = Counter(labels)

    print(f"📊 总记录: {len(records)} | 有完整截图: {len(valid)} | 唯一标签: {len(label_counts)}")
    print("   标签分布:")
    for lbl, cnt in label_counts.most_common():
        print(f"     - {lbl}: {cnt}")

    return valid, set(labels)


def _build_class_map(unique_labels: set[str]) -> dict[str, int]:
    """为每个唯一标签分配 class_id（按字母序）。"""
    sorted_labels = sorted(unique_labels)
    return {lbl: idx for idx, lbl in enumerate(sorted_labels)}


def _bbox_to_yolo(bbox: list[float], img_w: int, img_h: int) -> tuple[float, float, float, float]:
    """
    将绝对坐标 bbox [x1, y1, x2, y2] 转换为 YOLO 格式。

    Returns:
        (x_center, y_center, width, height) — 均为 0-1 归一化值
    """
    x1, y1, x2, y2 = bbox
    w = x2 - x1
    h = y2 - y1
    cx = x1 + w / 2
    cy = y1 + h / 2

    # 归一化
    x_center = cx / img_w
    y_center = cy / img_h
    width = w / img_w
    height = h / img_h

    # 裁剪到 [0, 1]
    x_center = max(0.0, min(1.0, x_center))
    y_center = max(0.0, min(1.0, y_center))
    width = max(0.0, min(1.0, width))
    height = max(0.0, min(1.0, height))

    return x_center, y_center, width, height


def _export_dataset(records: list[dict], class_map: dict[str, int]) -> int:
    """
    导出 YOLO 数据集。

    按 frame_path 分组，同一帧的多个 bbox 合并到一个 .txt 文件。

    Returns:
        导出的图片数量
    """
    # 按 frame_path 分组
    frames: dict[str, list[dict]] = {}
    for rec in records:
        fp = rec.get("frame_path")
        if not fp:
            continue
        frames.setdefault(fp, []).append(rec)

    exported = 0
    for frame_rel_path, frame_records in frames.items():
        frame_full_path = _TRAINING_DIR / frame_rel_path
        if not frame_full_path.exists():
            print(f"⚠️ 截图不存在，跳过: {frame_rel_path}")
            continue

        # 读取图片获取实际尺寸
        img = cv2.imread(str(frame_full_path))
        if img is None:
            print(f"⚠️ 无法读取截图: {frame_rel_path}")
            continue
        img_h, img_w = img.shape[:2]

        # 生成输出文件名
        stem = Path(frame_rel_path).stem
        out_img_path = _OUTPUT_DIR / "images" / "train" / f"{stem}.png"
        out_label_path = _OUTPUT_DIR / "labels" / "train" / f"{stem}.txt"

        # 复制图片
        shutil.copy2(str(frame_full_path), str(out_img_path))

        # 生成 YOLO 标注
        lines = []
        for rec in frame_records:
            label = rec.get("label", "unknown")
            class_id = class_map.get(label, 0)
            bbox = rec.get("bbox", [0, 0, 0, 0])
            if len(bbox) < 4:
                continue
            xc, yc, w, h = _bbox_to_yolo(bbox, img_w, img_h)
            lines.append(f"{class_id} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}")

        with open(out_label_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        exported += 1

    return exported


def _write_class_file(class_map: dict[str, int]) -> None:
    """生成 classes.txt。"""
    sorted_labels = sorted(class_map.items(), key=lambda x: x[1])
    with open(_OUTPUT_DIR / "classes.txt", "w", encoding="utf-8") as f:
        for label, _idx in sorted_labels:
            f.write(f"{label}\n")
    print(f"📝 已生成 classes.txt ({len(sorted_labels)} 个类别)")


def _write_yaml_file(class_map: dict[str, int]) -> None:
    """生成 YOLO dataset.yaml。"""
    names = {idx: label for label, idx in class_map.items()}
    yaml_content = f"""# YOLO Dataset Config — Auto-generated by export_yolo.py
path: {_OUTPUT_DIR.resolve()}
train: images/train
val: images/train  # 小规模数据集，train/val 共用

nc: {len(class_map)}
names:
{chr(10).join(f'  {idx}: {name}' for idx, name in sorted(names.items()))}
"""
    with open(_OUTPUT_DIR / "dataset.yaml", "w", encoding="utf-8") as f:
        f.write(yaml_content)
    print("📝 已生成 dataset.yaml")


def main():
    print("═" * 70)
    print("🚀 YOLO 数据集导出工具")
    print("═" * 70)

    _ensure_output_dirs()

    # 1. 收集记录
    records, unique_labels = _collect_records()
    if not records:
        print("\n❌ 没有可用的训练数据。请确认：")
        print("   1. features.onnx_training_mode.enabled 已设为 true")
        print("   2. 系统已运行一段时间，积累了带完整截图的未知元素")
        return

    # 2. 构建类别映射
    class_map = _build_class_map(unique_labels)

    # 3. 导出数据集
    exported = _export_dataset(records, class_map)

    # 4. 生成配置文件
    _write_class_file(class_map)
    _write_yaml_file(class_map)

    print("\n" + "═" * 70)
    print(f"✅ 导出完成: {exported} 张图片 | {len(class_map)} 个类别")
    print(f"📁 输出目录: {_OUTPUT_DIR.resolve()}")
    print("═" * 70)
    print("\n下一步：")
    print("   1. 检查 yolo_dataset/images/train/ 中的图片和标注")
    print(f"   2. 使用 ultralytics 训练: yolo detect train data={_OUTPUT_DIR / 'dataset.yaml'} model=nanodet-plus-m_416.yaml")
    print("   3. 导出 ONNX: yolo export model=best.pt format=onnx")


if __name__ == "__main__":
    main()
