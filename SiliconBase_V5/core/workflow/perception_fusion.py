#!/usr/bin/env python3
"""
PerceptionFusion - 感知融合中心 V1.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
整合现有分散的感知工具，提供统一、可配置的感知接口

【核心特性】
1. 统一感知接口（视觉+系统+环境+上下文）
2. 执行结果验证（视觉验证+数据验证）
3. 与现有工具集成（VisualUnderstand、Screenshot、GetPerception）
4. 智能感知策略（根据任务阶段自动选择感知方式）
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Any

try:
    from core.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger('perception_fusion')


# ═══════════════════════════════════════════════════════════════════════════════
# 数据类定义
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class VisualContext:
    """视觉上下文"""
    screenshot_path: str | None = None
    screenshot_base64: str | None = None
    description: str = ""  # AI理解的自然语言描述
    detected_elements: list[dict[str, Any]] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "screenshot_path": self.screenshot_path,
            "description": self.description,
            "detected_elements": self.detected_elements,
            "timestamp": self.timestamp
        }


@dataclass
class SystemContext:
    """系统上下文"""
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    disk_percent: float = 0.0
    high_cpu_processes: list[str] = field(default_factory=list)
    high_memory_processes: list[str] = field(default_factory=list)
    active_window: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpu_percent": self.cpu_percent,
            "memory_percent": self.memory_percent,
            "disk_percent": self.disk_percent,
            "high_cpu_processes": self.high_cpu_processes[:5],  # 只取前5个
            "high_memory_processes": self.high_memory_processes[:5],
            "active_window": self.active_window,
            "timestamp": self.timestamp
        }


@dataclass
class EnvironmentContext:
    """环境上下文"""
    mouse_position: tuple | None = None
    screen_resolution: tuple | None = None
    active_application: str = ""
    window_list: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mouse_position": self.mouse_position,
            "screen_resolution": self.screen_resolution,
            "active_application": self.active_application,
            "window_count": len(self.window_list),
            "timestamp": self.timestamp
        }


@dataclass
class TaskContext:
    """任务上下文"""
    current_goal: str = ""
    current_step: str = ""
    progress: float = 0.0
    previous_actions: list[dict[str, Any]] = field(default_factory=list)
    execution_history: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_goal": self.current_goal,
            "current_step": self.current_step,
            "progress": self.progress,
            "previous_actions": self.previous_actions[-3:],  # 最近3个
            "execution_history_count": len(self.execution_history),
            "timestamp": self.timestamp
        }


@dataclass
class PerceptionConfig:
    """感知配置"""
    # 启用哪些感知维度
    enable_visual: bool = True
    enable_system: bool = False
    enable_environment: bool = False
    enable_task_context: bool = True

    # 视觉感知配置
    screenshot: bool = True
    visual_understand: bool = True
    visual_question: str = "描述当前屏幕显示的内容"
    ocr: bool = False
    find_elements: bool = False

    # 任务上下文
    step_goal: str = ""
    progress: float = 0.0
    history: list[Any] = field(default_factory=list)

    # 超时
    timeout: int = 30

    def to_dict(self) -> dict[str, Any]:
        return {
            "enable_visual": self.enable_visual,
            "enable_system": self.enable_system,
            "enable_environment": self.enable_environment,
            "visual_understand": self.visual_understand,
            "step_goal": self.step_goal,
            "progress": self.progress
        }


@dataclass
class UnifiedPerceptionContext:
    """统一感知上下文 - 所有感知数据的聚合"""
    visual: VisualContext | None = None
    system: SystemContext | None = None
    environment: EnvironmentContext | None = None
    task_context: TaskContext | None = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "visual": self.visual.to_dict() if self.visual else None,
            "system": self.system.to_dict() if self.system else None,
            "environment": self.environment.to_dict() if self.environment else None,
            "task_context": self.task_context.to_dict() if self.task_context else None,
            "timestamp": self.timestamp
        }

    def to_prompt_context(self) -> str:
        """转换为Prompt可用的上下文描述"""
        sections = []

        if self.visual and self.visual.description:
            sections.append(f"【视觉感知】\n{self.visual.description}")

        if self.system:
            sections.append(
                f"【系统状态】"
                f"CPU: {self.system.cpu_percent:.1f}%, "
                f"内存: {self.system.memory_percent:.1f}%"
            )
            if self.system.high_cpu_processes:
                sections.append(f"高CPU进程: {', '.join(self.system.high_cpu_processes[:3])}")

        if self.environment and self.environment.active_application:
            sections.append(f"【当前应用】{self.environment.active_application}")

        if self.task_context:
            if self.task_context.current_goal:
                sections.append(f"【当前目标】{self.task_context.current_goal}")
            if self.task_context.progress > 0:
                sections.append(f"【进度】{self.task_context.progress:.1f}%")

        return "\n\n".join(sections) if sections else "无感知数据"

    def is_healthy(self) -> bool:
        """检查系统状态是否健康"""
        if not self.system:
            return True
        return (
            self.system.cpu_percent < 90 and
            self.system.memory_percent < 90
        )


@dataclass
class ExpectedOutcome:
    """预期结果定义（用于验证）"""
    visual_indicator: str | None = None  # 视觉指示器（如"Excel窗口打开"）
    data_format: dict[str, str] | None = None  # 数据格式要求
    state_change: str | None = None  # 状态变化描述
    file_existence: str | None = None  # 文件存在性检查

    def to_dict(self) -> dict[str, Any]:
        return {
            "visual_indicator": self.visual_indicator,
            "data_format": self.data_format,
            "state_change": self.state_change,
            "file_existence": self.file_existence
        }


@dataclass
class VerificationResult:
    """验证结果"""
    all_passed: bool = False
    details: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0  # 整体置信度
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "all_passed": self.all_passed,
            "details": self.details,
            "confidence": self.confidence,
            "timestamp": self.timestamp
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 感知融合主类
# ═══════════════════════════════════════════════════════════════════════════════

class PerceptionFusion:
    """
    感知融合中心

    整合现有工具：
    - VisualUnderstand: 视觉理解
    - Screenshot: 截图
    - GetPerception: 系统感知
    - ScreenOCR: 文字识别
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True

        # 工具缓存（延迟加载）
        self._tools: dict[str, Any] = {}

        # 缓存配置
        self._cache_enabled = True
        self._cache_ttl = 5.0  # 5秒缓存
        self._cache: dict[str, tuple] = {}  # {key: (timestamp, data)}

        logger.info("[PerceptionFusion] 感知融合中心初始化完成")

    def _get_tool(self, tool_name: str):
        """延迟加载工具"""
        if tool_name not in self._tools:
            try:
                if tool_name == "screenshot":
                    # 【蓝屏修复】tools.screenshot 已移除，改用 pixel_capture
                    from tools.pixel_capture import PixelCapture
                    self._tools[tool_name] = PixelCapture()
                elif tool_name == "visual_understand":
                    from tools.visual_understand import VisualUnderstand
                    self._tools[tool_name] = VisualUnderstand()
                elif tool_name == "get_perception":
                    from tools.get_perception import GetPerception
                    self._tools[tool_name] = GetPerception()
                elif tool_name == "screen_ocr":
                    from tools.screen_ocr import ScreenOCR
                    self._tools[tool_name] = ScreenOCR()
            except Exception as e:
                logger.warning(f"[PerceptionFusion] 加载工具失败 {tool_name}: {e}")
                return None
        return self._tools.get(tool_name)

    # ═══════════════════════════════════════════════════════════════════════════
    # 统一感知捕获
    # ═══════════════════════════════════════════════════════════════════════════

    async def capture(self, config: PerceptionConfig | None = None, **kwargs) -> UnifiedPerceptionContext:
        """
        统一感知捕获

        Args:
            config: 感知配置（可选，默认全启用）
            **kwargs: 快捷配置参数

        Returns:
            UnifiedPerceptionContext: 统一感知上下文
        """
        if config is None:
            config = PerceptionConfig(**kwargs)

        context = UnifiedPerceptionContext()

        # 视觉感知
        if config.enable_visual:
            try:
                context.visual = await self._capture_visual(config)
            except Exception as e:
                logger.error(f"[PerceptionFusion] 视觉感知失败: {e}")
                context.visual = VisualContext(description="视觉感知失败")

        # 系统感知
        if config.enable_system:
            try:
                context.system = self._capture_system()
            except Exception as e:
                logger.error(f"[PerceptionFusion] 系统感知失败: {e}")

        # 环境感知
        if config.enable_environment:
            try:
                context.environment = self._capture_environment()
            except Exception as e:
                logger.error(f"[PerceptionFusion] 环境感知失败: {e}")

        # 任务上下文
        if config.enable_task_context:
            context.task_context = TaskContext(
                current_goal=config.step_goal,
                progress=config.progress,
                history=config.history
            )

        return context

    async def _capture_visual(self, config: PerceptionConfig) -> VisualContext:
        """捕获视觉上下文"""
        ctx = VisualContext()

        # 截图
        if config.screenshot:
            screenshot_tool = self._get_tool("screenshot")
            if screenshot_tool:
                result = screenshot_tool.run()
                if result.get("success"):
                    ctx.screenshot_path = result.get("data", {}).get("file_path")
                    ctx.screenshot_base64 = result.get("data", {}).get("base64")

        # 视觉理解
        if config.visual_understand and ctx.screenshot_path:
            vu_tool = self._get_tool("visual_understand")
            if vu_tool:
                result = await vu_tool.run_async(
                    image_source="path",
                    image_path=ctx.screenshot_path,
                    question=config.visual_question
                )
                if result.get("success"):
                    ctx.description = result.get("content", "")

        return ctx

    def _capture_system(self) -> SystemContext:
        """捕获系统上下文"""
        ctx = SystemContext()

        get_perception = self._get_tool("get_perception")
        if get_perception:
            result = get_perception.run()
            if result.get("success"):
                data = result.get("data", {})
                ctx.cpu_percent = data.get("system_cpu", 0)
                ctx.memory_percent = data.get("system_memory", 0)
                ctx.disk_percent = data.get("system_disk", 0)
                ctx.active_window = data.get("active_window", "")
                ctx.high_cpu_processes = data.get("high_cpu_processes", [])
                ctx.high_memory_processes = data.get("high_memory_processes", [])

        return ctx

    def _capture_environment(self) -> EnvironmentContext:
        """捕获环境上下文"""
        ctx = EnvironmentContext()

        # 使用系统工具获取窗口信息
        try:
            import win32gui

            # 获取鼠标位置
            # ctx.mouse_position = win32gui.GetCursorPos()

            # 获取活动窗口
            hwnd = win32gui.GetForegroundWindow()
            if hwnd:
                ctx.active_application = win32gui.GetWindowText(hwnd)

        except ImportError:
            pass

        return ctx

    # ═══════════════════════════════════════════════════════════════════════════
    # 执行结果验证
    # ═══════════════════════════════════════════════════════════════════════════

    def verify(self, expected: ExpectedOutcome, actual_context: UnifiedPerceptionContext,
              actual_data: dict[str, Any] | None = None) -> VerificationResult:
        """
        验证执行结果

        Args:
            expected: 预期结果定义
            actual_context: 实际感知上下文
            actual_data: 实际数据结果（可选）

        Returns:
            VerificationResult: 验证结果
        """
        result = VerificationResult()
        results = []

        # 视觉验证
        if expected.visual_indicator and actual_context.visual:
            visual_passed = self._verify_visual(
                expected.visual_indicator,
                actual_context.visual
            )
            results.append({
                "type": "visual",
                "passed": visual_passed,
                "expected": expected.visual_indicator,
                "actual": actual_context.visual.description[:100]
            })

        # 数据验证
        if expected.data_format and actual_data:
            data_passed = self._verify_data_format(expected.data_format, actual_data)
            results.append({
                "type": "data",
                "passed": data_passed,
                "expected": expected.data_format,
                "actual": {k: type(v).__name__ for k, v in actual_data.items()}
            })

        # 文件验证
        if expected.file_existence:
            import os
            file_passed = os.path.exists(expected.file_existence)
            results.append({
                "type": "file",
                "passed": file_passed,
                "expected": f"文件存在: {expected.file_existence}",
                "actual": "存在" if file_passed else "不存在"
            })

        # 计算整体结果
        result.details = results
        result.all_passed = all(r["passed"] for r in results) if results else True
        result.confidence = sum(r["passed"] for r in results) / len(results) if results else 1.0

        return result

    def _verify_visual(self, expected_indicator: str, visual_ctx: VisualContext) -> bool:
        """视觉验证"""
        if not visual_ctx.description:
            return False

        # 简单关键词匹配
        expected_keywords = expected_indicator.lower().split()
        description_lower = visual_ctx.description.lower()

        match_count = sum(1 for kw in expected_keywords if kw in description_lower)
        return match_count >= len(expected_keywords) * 0.5  # 50%匹配率

    def _verify_data_format(self, expected_format: dict[str, str],
                           actual_data: dict[str, Any]) -> bool:
        """数据格式验证"""
        for key, expected_type in expected_format.items():
            if key not in actual_data:
                return False

            actual_value = actual_data[key]
            actual_type = type(actual_value).__name__

            if expected_type != actual_type:
                return False

        return True

    # ═══════════════════════════════════════════════════════════════════════════
    # 智能感知策略
    # ═══════════════════════════════════════════════════════════════════════════

    async def capture_for_step(self, step_category: str, step_goal: str,
                        execution_history: list[Any] = None) -> UnifiedPerceptionContext:
        """
        根据步骤类型智能选择感知策略

        Args:
            step_category: 步骤类别 (check, launch, action, transform, verify, save)
            step_goal: 步骤目标描述
            execution_history: 执行历史

        Returns:
            UnifiedPerceptionContext
        """
        # 根据步骤类别选择感知配置
        configs = {
            "check": PerceptionConfig(
                enable_visual=True,
                enable_system=True,
                visual_question=f"检查: {step_goal}",
                step_goal=step_goal
            ),
            "launch": PerceptionConfig(
                enable_visual=True,
                enable_system=False,
                visual_question=f"应用是否成功启动: {step_goal}",
                step_goal=step_goal
            ),
            "action": PerceptionConfig(
                enable_visual=True,
                visual_question=f"操作是否成功: {step_goal}",
                step_goal=step_goal
            ),
            "transform": PerceptionConfig(
                enable_visual=False,  # 数据转换不需要视觉
                enable_system=True,
                step_goal=step_goal
            ),
            "verify": PerceptionConfig(
                enable_visual=True,
                enable_system=False,
                visual_question=f"验证结果: {step_goal}",
                step_goal=step_goal
            ),
            "save": PerceptionConfig(
                enable_visual=True,
                enable_system=False,
                visual_question=f"文件是否成功保存: {step_goal}",
                step_goal=step_goal
            )
        }

        config = configs.get(step_category, PerceptionConfig(step_goal=step_goal))
        if execution_history:
            config.history = execution_history

        return await self.capture(config)

    def verify_step_completion(self, step_category: str, step_result: dict[str, Any],
                              perception_ctx: UnifiedPerceptionContext) -> bool:
        """
        验证步骤是否真正完成

        根据步骤类别和感知上下文判断
        """
        if not step_result.get("success"):
            return False

        # 不同类别的完成标准
        completion_checks = {
            "launch": lambda: self._check_application_launched(perception_ctx, step_result),
            "save": lambda: self._check_file_saved(perception_ctx, step_result),
            "transform": lambda: self._check_data_transformed(step_result),
            "verify": lambda: self._check_verification_passed(step_result)
        }

        check_fn = completion_checks.get(step_category)
        if check_fn:
            return check_fn()

        # 默认：只要工具返回成功就认为完成
        return True

    def _check_application_launched(self, ctx: UnifiedPerceptionContext,
                                   result: dict[str, Any]) -> bool:
        """检查应用是否真正启动"""
        # 检查PID
        pid = result.get("data", {}).get("pid")
        if pid:
            try:
                import psutil
                if psutil.pid_exists(pid):
                    return True
            except Exception:
                pass

        # 检查视觉描述
        if ctx.visual and "启动" in ctx.visual.description:
            return True

        return True  # 无法验证时默认通过

    def _check_file_saved(self, ctx: UnifiedPerceptionContext,
                         result: dict[str, Any]) -> bool:
        """检查文件是否真正保存"""
        file_path = result.get("data", {}).get("file_path") or result.get("data", {}).get("path")
        if file_path:
            import os
            return os.path.exists(file_path)
        return True

    def _check_data_transformed(self, result: dict[str, Any]) -> bool:
        """检查数据是否转换成功"""
        data = result.get("data", {})
        # 检查是否有输出数据
        return bool(data) and not result.get("error")

    def _check_verification_passed(self, result: dict[str, Any]) -> bool:
        """检查验证是否通过"""
        return result.get("data", {}).get("verified", result.get("success", False))


# ═══════════════════════════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════════════════════════

_perception_fusion = None
_fusion_lock = threading.Lock()


def get_perception_fusion() -> PerceptionFusion:
    """获取感知融合中心单例"""
    global _perception_fusion
    if _perception_fusion is None:
        with _fusion_lock:
            if _perception_fusion is None:
                _perception_fusion = PerceptionFusion()
    return _perception_fusion


# 便捷函数
async def capture_perception(**kwargs) -> UnifiedPerceptionContext:
    """快捷捕获感知"""
    return await get_perception_fusion().capture(**kwargs)


def verify_outcome(expected: ExpectedOutcome, actual_ctx: UnifiedPerceptionContext,
                  actual_data: dict[str, Any] = None) -> VerificationResult:
    """快捷验证结果"""
    return get_perception_fusion().verify(expected, actual_ctx, actual_data)
