#!/usr/bin/env python3
"""
ProtectedSpeakQueue - 受保护的播报队列

解决播报夹断问题的核心组件：
1. 支持标记播报项为 protected（受保护）
2. 中断时跳过受保护项
3. 清空队列时保留受保护项
4. 优先级机制保护受保护项

作者: Phase 1 Week 1 任务2
"""
import queue
import threading
import time
from dataclasses import dataclass, field

from core.logger import logger


@dataclass(order=True)
class SpeakItem:
    """播报项数据结构"""
    priority: int  # 优先级（数字越小优先级越高）
    timestamp: float = field(compare=True)  # 时间戳（用于排序）
    text: str = field(compare=False)  # 播报文本
    wait: bool = field(compare=False, default=True)  # 是否等待
    protected: bool = field(compare=False, default=False)  # 是否受保护
    item_id: str = field(compare=False, default="")  # 唯一标识

    def __post_init__(self):
        if not self.item_id:
            self.item_id = f"{self.timestamp:.6f}_{id(self)}"


class ProtectedSpeakQueue:
    """
    受保护的播报队列

    特性：
    - 支持优先级队列
    - 支持受保护标记
    - 中断时保护受保护项
    - 清空时保留受保护项
    """

    def __init__(self):
        self._queue = queue.PriorityQueue()
        self._current_item: SpeakItem | None = None
        self._lock = threading.RLock()
        self._sequence = 0  # 序列号用于保证同优先级下的顺序

    def enqueue(self, text: str, wait: bool = True, priority: int = 0,
                protected: bool = False) -> SpeakItem:
        """
        添加播报项到队列

        Args:
            text: 播报文本
            wait: 是否等待播报完成
            priority: 优先级（数字越小优先级越高，0=普通，1=系统，2=紧急）
            protected: 是否受保护（受保护项不会被中断或清空）

        Returns:
            SpeakItem: 创建的播报项
        """
        with self._lock:
            self._sequence += 1
            # 优先级取反，因为PriorityQueue是小根堆（数字小的先出）
            # 我们希望 priority=2（紧急）> priority=1（系统）> priority=0（普通）
            queue_priority = -priority

            item = SpeakItem(
                priority=queue_priority,
                timestamp=time.time() + self._sequence * 1e-9,  # 添加微小偏移保证顺序
                text=text,
                wait=wait,
                protected=protected
            )

            self._queue.put((queue_priority, item.timestamp, item))

            if protected:
                logger.debug(f"[ProtectedQueue] 添加受保护播报项: {text[:30]}..., priority={priority}")
            else:
                logger.debug(f"[ProtectedQueue] 添加普通播报项: {text[:30]}..., priority={priority}")

            return item

    def get(self, timeout: float | None = None) -> SpeakItem | None:
        """
        获取队列中的下一个播报项

        Args:
            timeout: 超时时间（秒），None表示无限等待

        Returns:
            SpeakItem 或 None（如果超时或队列关闭）
        """
        try:
            priority, timestamp, item = self._queue.get(timeout=timeout)
            with self._lock:
                self._current_item = item
            return item
        except queue.Empty:
            return None

    def get_nowait(self) -> SpeakItem | None:
        """非阻塞获取播报项"""
        try:
            priority, timestamp, item = self._queue.get_nowait()
            with self._lock:
                self._current_item = item
            return item
        except queue.Empty:
            return None

    def task_done(self):
        """标记当前任务完成"""
        self._queue.task_done()
        with self._lock:
            self._current_item = None

    def put_stop_signal(self):
        """放入停止信号（None）"""
        self._queue.put((0, 0, None))

    @property
    def current_item(self) -> SpeakItem | None:
        """获取当前正在播报的项"""
        with self._lock:
            return self._current_item

    def set_current_item(self, item: SpeakItem | None):
        """设置当前播报项"""
        with self._lock:
            self._current_item = item

    def interrupt(self, only_unprotected: bool = True) -> tuple[bool, str]:
        """
        尝试中断当前播报

        Args:
            only_unprotected: 是否只中断未受保护的播报

        Returns:
            Tuple[是否成功中断, 状态消息]
        """
        with self._lock:
            current = self._current_item

            if current is None:
                return True, "当前没有在播报"

            if current.protected and only_unprotected:
                logger.warning(f"[ProtectedQueue] 播报项受保护，拒绝中断: {current.text[:30]}...")
                return False, f"播报项受保护: {current.text[:30]}..."

            logger.info(f"[ProtectedQueue] 执行中断，播报项: {current.text[:30]}...")
            return True, f"已中断: {current.text[:30]}..."

    def stop_speaking(self, clear_unprotected_only: bool = True) -> tuple[int, int]:
        """
        停止播报并清空队列

        Args:
            clear_unprotected_only: 是否只清空未受保护项

        Returns:
            Tuple[清空的项数, 保留的项数]
        """
        with self._lock:
            cleared_count = 0
            protected_count = 0
            protected_items: list[tuple] = []

            try:
                # 检查当前播报项是否受保护
                current = self._current_item
                if current and current.protected and clear_unprotected_only:
                    logger.warning(f"[ProtectedQueue] 当前播报受保护，保留: {current.text[:30]}...")

                # 遍历队列
                while not self._queue.empty():
                    try:
                        item_tuple = self._queue.get_nowait()

                        # 跳过停止信号
                        if item_tuple[2] is None:
                            protected_items.append(item_tuple)
                            continue

                        priority, timestamp, item = item_tuple

                        if clear_unprotected_only and item.protected:
                            # 保留受保护项
                            protected_items.append(item_tuple)
                            protected_count += 1
                            logger.debug(f"[ProtectedQueue] 保留受保护项: {item.text[:30]}...")
                        else:
                            # 清空该项
                            cleared_count += 1
                            logger.debug(f"[ProtectedQueue] 清空项: {item.text[:30]}...")

                    except queue.Empty:
                        break
                    except Exception as e:
                        logger.error(f"[ProtectedQueue] 清空队列时异常: {e}", exc_info=True)
                        break

                # 恢复受保护项到队列
                for item_tuple in protected_items:
                    self._queue.put(item_tuple)

                if cleared_count > 0 or protected_count > 0:
                    logger.info(f"[ProtectedQueue] 队列已处理: 清空 {cleared_count} 项, 保留 {protected_count} 项")

                return cleared_count, protected_count

            except Exception as e:
                logger.error(f"[ProtectedQueue] stop_speaking 失败: {e}", exc_info=True)
                return 0, 0

    def get_all_items(self) -> list[SpeakItem]:
        """获取队列中所有项（调试用）"""
        items = []
        with self._lock:
            # 临时列表存储所有项
            temp_items = []
            while not self._queue.empty():
                try:
                    item_tuple = self._queue.get_nowait()
                    if item_tuple[2] is not None:  # 跳过停止信号
                        temp_items.append(item_tuple)
                        items.append(item_tuple[2])
                except queue.Empty:
                    break

            # 恢复所有项到队列
            for item_tuple in temp_items:
                self._queue.put(item_tuple)

        return items

    def empty(self) -> bool:
        """检查队列是否为空"""
        return self._queue.empty()

    def qsize(self) -> int:
        """获取队列大小"""
        return self._queue.qsize()

    def join(self):
        """等待所有任务完成"""
        self._queue.join()


# 【已清理】SpeakQueueAdapter 已移除（2026-06-04）
# 原用于平滑迁移旧 queue.Queue 接口，现无调用方，已删除。
