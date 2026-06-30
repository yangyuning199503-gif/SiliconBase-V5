#!/usr/bin/env python3
"""
用户操作录制器 (Operation Recorder)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

录制用户的操作步骤，支持鼠标、键盘、应用切换等操作。

功能：
1. 启动/停止录制
2. 记录操作序列
3. 添加操作注释
4. 生成结构化操作步骤
"""

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class OperationType(Enum):
    """操作类型枚举"""
    MOUSE_CLICK = "mouse_click"           # 鼠标点击
    MOUSE_MOVE = "mouse_move"             # 鼠标移动
    KEYBOARD_INPUT = "keyboard_input"     # 键盘输入
    KEYBOARD_HOTKEY = "keyboard_hotkey"   # 快捷键
    APP_SWITCH = "app_switch"             # 切换应用
    APP_OPEN = "app_open"                 # 打开应用
    SCROLL = "scroll"                     # 滚动
    WAIT = "wait"                         # 等待
    SCREENSHOT = "screenshot"             # 截图标记
    COMMENT = "comment"                   # 注释


@dataclass
class UserOperation:
    """
    用户操作记录

    Attributes:
        operation_id: 操作唯一ID
        operation_type: 操作类型
        timestamp: 操作时间戳
        params: 操作参数（坐标、文本等）
        screenshot_path: 操作时的截图路径
        comment: 用户注释
        duration: 操作耗时（秒）
    """
    operation_id: str
    operation_type: str
    timestamp: float
    params: dict[str, Any] = field(default_factory=dict)
    screenshot_path: str | None = None
    comment: str | None = None
    duration: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'UserOperation':
        """从字典创建"""
        return cls(**data)

    def describe(self) -> str:
        """生成人类可读的操作描述"""
        op_type = self.operation_type
        params = self.params

        descriptions = {
            OperationType.MOUSE_CLICK.value: lambda: f"点击 ({params.get('x')}, {params.get('y')})",
            OperationType.MOUSE_MOVE.value: lambda: f"移动到 ({params.get('x')}, {params.get('y')})",
            OperationType.KEYBOARD_INPUT.value: lambda: f"输入: {params.get('text', '')[:20]}...",
            OperationType.KEYBOARD_HOTKEY.value: lambda: f"快捷键: {'+'.join(params.get('keys', []))}",
            OperationType.APP_SWITCH.value: lambda: f"切换到: {params.get('app_name', '未知应用')}",
            OperationType.APP_OPEN.value: lambda: f"打开应用: {params.get('app_name', '未知应用')}",
            OperationType.SCROLL.value: lambda: f"滚动: {params.get('direction', 'down')} {params.get('amount', 3)}行",
            OperationType.WAIT.value: lambda: f"等待: {params.get('seconds', 1)}秒",
            OperationType.SCREENSHOT.value: lambda: "截图标记",
            OperationType.COMMENT.value: lambda: f"注释: {params.get('text', '')}",
        }

        return descriptions.get(op_type, lambda: f"未知操作: {op_type}")()


class OperationRecorder:
    """
    用户操作录制器

    录制用户的操作序列，支持自动捕获和手动添加。
    """

    def __init__(self):
        self.recording_id: str | None = None
        self.operations: list[UserOperation] = []
        self.is_recording: bool = False
        self.start_time: float | None = None
        self._last_operation_time: float | None = None
        self._screenshot_dir: Path = Path("data/recordings")
        self._screenshot_dir.mkdir(parents=True, exist_ok=True)

        # 回调函数
        self._on_operation_added: Callable[[UserOperation], None] | None = None
        self._on_recording_started: Callable[[], None] | None = None
        self._on_recording_stopped: Callable[[list[UserOperation]], None] | None = None

    def register_callbacks(
        self,
        on_operation_added: Callable[[UserOperation], None] | None = None,
        on_recording_started: Callable[[], None] | None = None,
        on_recording_stopped: Callable[[list[UserOperation]], None] | None = None
    ):
        """注册回调函数"""
        self._on_operation_added = on_operation_added
        self._on_recording_started = on_recording_started
        self._on_recording_stopped = on_recording_stopped

    def start_recording(self, context: dict[str, Any] | None = None) -> str:
        """
        开始录制

        Args:
            context: 录制上下文（任务描述、用户需求等）

        Returns:
            recording_id: 录制会话ID
        """
        self.recording_id = f"rec_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        self.operations = []
        self.is_recording = True
        self.start_time = time.time()
        self._last_operation_time = self.start_time

        # 添加初始上下文注释
        if context:
            self.add_comment(f"录制开始 - 任务: {context.get('task', '未知任务')}")

        if self._on_recording_started:
            self._on_recording_started()

        return self.recording_id

    def stop_recording(self) -> list[UserOperation]:
        """
        停止录制

        Returns:
            录制的操作列表
        """
        if not self.is_recording:
            return []

        self.is_recording = False
        self.add_comment("录制结束")

        if self._on_recording_stopped:
            self._on_recording_stopped(self.operations)

        return self.operations.copy()

    def add_operation(
        self,
        operation_type: OperationType,
        params: dict[str, Any],
        screenshot: bool | None = True,
        comment: str | None = None
    ) -> UserOperation:
        """
        添加操作记录

        Args:
            operation_type: 操作类型
            params: 操作参数
            screenshot: 是否截图
            comment: 操作注释

        Returns:
            创建的操作记录
        """
        if not self.is_recording:
            return None

        current_time = time.time()
        duration = current_time - (self._last_operation_time or current_time)

        # 截图
        screenshot_path = None
        if screenshot:
            screenshot_path = self._capture_screenshot()

        operation = UserOperation(
            operation_id=f"op_{len(self.operations)}_{uuid.uuid4().hex[:6]}",
            operation_type=operation_type.value,
            timestamp=current_time,
            params=params,
            screenshot_path=screenshot_path,
            comment=comment,
            duration=round(duration, 3)
        )

        self.operations.append(operation)
        self._last_operation_time = current_time

        if self._on_operation_added:
            self._on_operation_added(operation)

        return operation

    def add_comment(self, text: str) -> UserOperation:
        """添加注释"""
        return self.add_operation(
            OperationType.COMMENT,
            {"text": text},
            screenshot=False
        )

    def add_screenshot_marker(self, description: str = "") -> UserOperation:
        """添加截图标记"""
        return self.add_operation(
            OperationType.SCREENSHOT,
            {"description": description},
            screenshot=True
        )

    def _capture_screenshot(self) -> str | None:
        """捕获屏幕截图 - 【蓝屏修复】使用线程安全截图"""
        try:
            from core.vision.safe_screenshot import safe_screenshot_to_pil

            filename = f"{self.recording_id}_{len(self.operations)}.png"
            filepath = self._screenshot_dir / filename

            # 【蓝屏修复】使用safe_screenshot替代mss
            img = safe_screenshot_to_pil(monitor=0)  # monitor=0 所有屏幕
            if img is None:
                print("[OperationRecorder] 截图失败")
                return None

            img.save(str(filepath))
            return str(filepath)
        except Exception as e:
            print(f"[OperationRecorder] 截图失败: {e}")
            return None

    def get_operations(self) -> list[UserOperation]:
        """获取所有操作记录"""
        return self.operations.copy()

    def get_summary(self) -> dict[str, Any]:
        """获取录制摘要"""
        if not self.operations:
            return {}

        operation_counts = {}
        for op in self.operations:
            op_type = op.operation_type
            operation_counts[op_type] = operation_counts.get(op_type, 0) + 1

        total_duration = self.operations[-1].timestamp - self.operations[0].timestamp if len(self.operations) > 1 else 0

        return {
            "recording_id": self.recording_id,
            "total_operations": len(self.operations),
            "operation_counts": operation_counts,
            "total_duration": round(total_duration, 2),
            "start_time": datetime.fromtimestamp(self.operations[0].timestamp).isoformat() if self.operations else None,
        }

    def export_to_json(self, filepath: str | None = None) -> str:
        """
        导出录制数据到JSON

        Args:
            filepath: 导出文件路径，默认自动生成

        Returns:
            文件路径
        """
        if filepath is None:
            filepath = self._screenshot_dir / f"{self.recording_id}.json"

        data = {
            "recording_id": self.recording_id,
            "start_time": self.start_time,
            "operations": [op.to_dict() for op in self.operations],
            "summary": self.get_summary()
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return str(filepath)

    def clear(self):
        """清除录制数据"""
        self.operations = []
        self.recording_id = None
        self.is_recording = False
        self.start_time = None
        self._last_operation_time = None


# 全局实例
_recorder_instance: OperationRecorder | None = None

def get_operation_recorder() -> OperationRecorder:
    """获取全局操作录制器实例"""
    global _recorder_instance
    if _recorder_instance is None:
        _recorder_instance = OperationRecorder()
    return _recorder_instance
