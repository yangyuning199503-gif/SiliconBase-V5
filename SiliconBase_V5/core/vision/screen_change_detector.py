#!/usr/bin/env python3
"""
屏幕变化检测模块 - SiliconBase V5
使用dHash算法实现高效的屏幕变化检测

特点:
- 单次检测耗时: ~1-2ms
- 无需额外依赖(PIL+numpy已内置)
- 可配置敏感度阈值
"""

import threading
import time

import numpy as np
from PIL import Image

from core.logger import logger


class ScreenChangeDetector:
    """
    屏幕变化检测器 - 基于dHash (Difference Hash)

    用于检测屏幕内容是否发生变化，避免不必要的视觉模型调用
    """

    def __init__(self, threshold: int = 5, min_interval: float = 0.5):
        """
        初始化检测器

        Args:
            threshold: 变化阈值，默认5 (汉明距离大于此值认为有变化)
                      高敏感=2-3, 正常=5, 低敏感=10
            min_interval: 最小检测间隔（秒），防止快速连续触发
        """
        # 验证阈值
        if not isinstance(threshold, int):
            error_msg = "[ScreenChangeDetector] threshold必须是整数"
            logger.error(error_msg)
            raise TypeError(error_msg)
        if not (1 <= threshold <= 20):
            error_msg = "[ScreenChangeDetector] threshold必须在1-20之间"
            logger.error(error_msg)
            raise ValueError(error_msg)

        self.threshold = threshold
        self.min_interval = min_interval
        self.last_hash: int | None = None
        self.last_check_time: float = 0
        self._consecutive_changes: int = 0  # 连续变化计数
        self._lock = threading.Lock()  # 【蓝屏修复】保护共享状态

    def compute_dhash(self, image: Image.Image) -> int:
        """
        计算图像的dHash值

        Args:
            image: PIL Image对象

        Returns:
            64位整数哈希值
        """
        # 1. 转换为灰度图
        gray = image.convert('L')

        # 2. 缩放到 (9, 8) - 加1列是为了计算水平梯度
        resized = gray.resize((9, 8), Image.Resampling.LANCZOS)

        # 3. 转换为numpy数组加速计算
        pixels = np.array(resized)

        # 4. 计算差异哈希 (行方向比较相邻像素)
        diff = pixels[:, 1:] >= pixels[:, :-1]

        # 5. 将布尔数组转换为64位整数
        hash_value = 0
        for bit in diff.flat:
            hash_value = (hash_value << 1) | int(bit)

        return hash_value

    def hamming_distance(self, hash1: int, hash2: int) -> int:
        """
        计算两个哈希值的汉明距离

        Args:
            hash1: 第一个哈希值
            hash2: 第二个哈希值

        Returns:
            不同位的数量 (0-64)
        """
        return bin(hash1 ^ hash2).count('1')

    def has_changed(self, image: Image.Image) -> bool:
        """
        检测屏幕是否变化，带频率限制

        Args:
            image: PIL Image对象 (截图)

        Returns:
            True: 检测到变化 (需要调用视觉模型)
            False: 未检测到变化 (可使用缓存)
        """
        # 【蓝屏修复】整个状态读写加锁，防止多线程同时修改导致检测逻辑混乱
        with self._lock:
            current_time = time.time()

            # 频率限制
            if current_time - self.last_check_time < self.min_interval:
                logger.debug("[ScreenChangeDetector] 检测频率过高，跳过")
                return False

            # 连续变化检测（防止屏幕动画导致频繁触发）
            if self._consecutive_changes > 10:
                logger.warning(f"[ScreenChangeDetector] 连续{self._consecutive_changes}次变化，可能为动画/视频，降低敏感度")
                # 临时提高阈值
                temp_threshold = min(self.threshold * 2, 20)
            else:
                temp_threshold = self.threshold

            # 计算hash（图像计算在锁外执行，减少锁持有时间）
            try:
                current_hash = self.compute_dhash(image)
            except Exception as e:
                error_msg = f"[ScreenChangeDetector] hash计算失败: {e}"
                logger.error(error_msg)
                raise RuntimeError(error_msg) from e

            # 首次检测
            if self.last_hash is None:
                self.last_hash = current_hash
                self.last_check_time = current_time
                self._consecutive_changes = 1
                return True

            # 计算距离
            distance = self.hamming_distance(self.last_hash, current_hash)
            is_changed = distance > temp_threshold

            if is_changed:
                self._consecutive_changes += 1
                self.last_hash = current_hash
                self.last_check_time = current_time
                logger.debug(f"[ScreenChangeDetector] 检测到变化: distance={distance}")
            else:
                self._consecutive_changes = 0

            return is_changed

    def reset(self):
        """重置检测器状态"""
        with self._lock:
            self.last_hash = None
            self.last_check_time = 0
            self._consecutive_changes = 0


# 便捷函数
def create_default_detector() -> ScreenChangeDetector:
    """创建默认配置的检测器"""
    return ScreenChangeDetector(threshold=5)
