#!/usr/bin/env python3
"""
截图管理器 - 自动保存和清理截图

功能：
1. 自动保存截图到指定目录
2. 限制最大截图数量（默认保留最近50张）
3. 限制总存储大小（默认最大100MB）
4. 自动清理过期截图（默认保留最近24小时）

作者: SiliconBase Team
"""

import asyncio
import glob
import os
import time
from datetime import datetime
from pathlib import Path

from core.logger import logger


class ScreenshotManager:
    """截图管理器 - 处理截图的保存、命名和清理"""

    # 默认配置
    DEFAULT_MAX_COUNT = 50          # 最大保留截图数量
    DEFAULT_MAX_SIZE_MB = 100       # 最大存储空间（MB）
    DEFAULT_MAX_AGE_HOURS = 24      # 最大保留时间（小时）
    DEFAULT_SCREENSHOT_DIR = "data/screenshots"  # 默认保存路径

    def __init__(
        self,
        screenshot_dir: str | None = None,
        max_count: int = None,
        max_size_mb: int = None,
        max_age_hours: int = None
    ):
        """
        初始化截图管理器

        优先从配置文件读取参数，如果没有配置则使用默认值。

        Args:
            screenshot_dir: 截图保存目录
            max_count: 最大保留截图数量
            max_size_mb: 最大存储空间（MB）
            max_age_hours: 最大保留时间（小时）
        """
        # 尝试从配置读取
        try:
            from core.config import config
            config_screenshot = config.get("screenshot", {})
        except Exception:
            config_screenshot = {}

        # 使用传入参数 > 配置参数 > 默认值的优先级
        self.screenshot_dir = Path(
            screenshot_dir or
            config_screenshot.get("dir") or
            self.DEFAULT_SCREENSHOT_DIR
        )
        self.max_count = (
            max_count if max_count is not None else
            config_screenshot.get("max_count") or
            self.DEFAULT_MAX_COUNT
        )
        self.max_size_mb = (
            max_size_mb if max_size_mb is not None else
            config_screenshot.get("max_size_mb") or
            self.DEFAULT_MAX_SIZE_MB
        )
        self.max_age_hours = (
            max_age_hours if max_age_hours is not None else
            config_screenshot.get("max_age_hours") or
            self.DEFAULT_MAX_AGE_HOURS
        )

        # 确保目录存在
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"[ScreenshotManager] 初始化完成: {self.screenshot_dir}")
        logger.info(f"[ScreenshotManager] 限制: 最多{self.max_count}张, {self.max_size_mb}MB, 保留{self.max_age_hours}小时")

    def get_screenshot_path(self, prefix: str = "screenshot") -> Path:
        """
        生成截图保存路径

        Args:
            prefix: 文件名前缀

        Returns:
            Path: 完整的保存路径
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = f"{prefix}_{timestamp}.png"
        return self.screenshot_dir / filename

    def get_auto_verify_path(self) -> Path:
        """获取自动验证截图的保存路径"""
        return self.get_screenshot_path("verify")

    def cleanup_old_screenshots(self) -> dict:
        """
        清理旧截图

        清理策略（按优先级）：
        1. 删除超过最大保留时间的截图
        2. 如果数量超过限制，删除最旧的
        3. 如果总大小超过限制，删除最旧的直到满足

        Returns:
            dict: 清理统计信息
        """
        stats = {
            "deleted_by_age": 0,
            "deleted_by_count": 0,
            "deleted_by_size": 0,
            "total_freed_mb": 0.0
        }

        try:
            # 获取所有截图文件
            screenshot_pattern = str(self.screenshot_dir / "*.png")
            screenshots = glob.glob(screenshot_pattern)

            if not screenshots:
                return stats

            # 按修改时间排序（最旧的在前）
            screenshots_with_time = []
            for path in screenshots:
                try:
                    mtime = os.path.getmtime(path)
                    size = os.path.getsize(path)
                    screenshots_with_time.append((path, mtime, size))
                except OSError:
                    continue

            screenshots_with_time.sort(key=lambda x: x[1])

            # 1. 删除超过保留时间的截图
            current_time = time.time()
            max_age_seconds = self.max_age_hours * 3600

            remaining = []
            for path, mtime, size in screenshots_with_time:
                age_seconds = current_time - mtime
                if age_seconds > max_age_seconds:
                    try:
                        os.remove(path)
                        stats["deleted_by_age"] += 1
                        stats["total_freed_mb"] += size / (1024 * 1024)
                        logger.debug(f"[ScreenshotManager] 删除过期截图: {Path(path).name}")
                    except OSError:
                        remaining.append((path, mtime, size))
                else:
                    remaining.append((path, mtime, size))

            # 2. 如果数量超过限制，删除最旧的
            while len(remaining) > self.max_count:
                path, mtime, size = remaining.pop(0)  # 取出最旧的
                try:
                    os.remove(path)
                    stats["deleted_by_count"] += 1
                    stats["total_freed_mb"] += size / (1024 * 1024)
                    logger.debug(f"[ScreenshotManager] 删除超出数量限制的截图: {Path(path).name}")
                except OSError:
                    pass

            # 3. 如果总大小超过限制，删除最旧的
            total_size_mb = sum(s for _, _, s in remaining) / (1024 * 1024)
            while total_size_mb > self.max_size_mb and remaining:
                path, mtime, size = remaining.pop(0)  # 取出最旧的
                try:
                    os.remove(path)
                    stats["deleted_by_size"] += 1
                    stats["total_freed_mb"] += size / (1024 * 1024)
                    total_size_mb -= size / (1024 * 1024)
                    logger.debug(f"[ScreenshotManager] 删除超出大小限制的截图: {Path(path).name}")
                except OSError:
                    pass

            total_deleted = stats["deleted_by_age"] + stats["deleted_by_count"] + stats["deleted_by_size"]
            if total_deleted > 0:
                logger.info(
                    f"[ScreenshotManager] 清理完成: 删除{total_deleted}张截图 "
                    f"(过期:{stats['deleted_by_age']}, 超数:{stats['deleted_by_count']}, 超大:{stats['deleted_by_size']}), "
                    f"释放{stats['total_freed_mb']:.2f}MB"
                )

            return stats

        except Exception as e:
            logger.error(f"[ScreenshotManager] 清理截图失败: {e}")
            return stats

    async def cleanup_old_screenshots_async(self) -> dict:
        """
        异步清理旧截图。
        文件系统操作无原生 async 支持，统一在管理器内部用 to_thread 包裹，
        调用方直接 await 即可，无需重复写 asyncio.to_thread。
        """
        return await asyncio.to_thread(self.cleanup_old_screenshots)

    def get_screenshot_stats(self) -> dict:
        """
        获取截图统计信息

        Returns:
            dict: 统计信息
        """
        try:
            screenshot_pattern = str(self.screenshot_dir / "*.png")
            screenshots = glob.glob(screenshot_pattern)

            total_count = len(screenshots)
            total_size_mb = sum(os.path.getsize(s) for s in screenshots) / (1024 * 1024)

            # 按前缀统计
            verify_count = len([s for s in screenshots if "verify" in s])
            manual_count = len([s for s in screenshots if "screenshot" in s and "verify" not in s])

            return {
                "total_count": total_count,
                "total_size_mb": round(total_size_mb, 2),
                "verify_count": verify_count,
                "manual_count": manual_count,
                "screenshot_dir": str(self.screenshot_dir),
                "limits": {
                    "max_count": self.max_count,
                    "max_size_mb": self.max_size_mb,
                    "max_age_hours": self.max_age_hours
                }
            }
        except Exception as e:
            logger.error(f"[ScreenshotManager] 获取统计失败: {e}")
            return {}


# 全局实例
_screenshot_manager = None

def get_screenshot_manager() -> ScreenshotManager:
    """获取截图管理器单例"""
    global _screenshot_manager
    if _screenshot_manager is None:
        _screenshot_manager = ScreenshotManager()
    return _screenshot_manager


def save_screenshot_with_cleanup(image_data: bytes, prefix: str = "screenshot") -> str:
    """
    保存截图并触发清理

    Args:
        image_data: PNG图像数据
        prefix: 文件名前缀

    Returns:
        str: 保存的文件路径
    """
    manager = get_screenshot_manager()

    # 先清理旧截图
    manager.cleanup_old_screenshots()

    # 生成保存路径
    save_path = manager.get_screenshot_path(prefix)

    # 保存截图
    with open(save_path, "wb") as f:
        f.write(image_data)

    logger.debug(f"[ScreenshotManager] 截图已保存: {save_path}")
    return str(save_path)
