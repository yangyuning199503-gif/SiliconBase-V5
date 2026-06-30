#!/usr/bin/env python3
"""
感知策略规划器（PerceptionPlanner）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
白皮书模块：纯策略计算，无 IO，不需要 async
职责：根据任务类型、轮次、历史决定感知策略
约束：零副作用，零状态修改，纯函数式决策
"""

from typing import Any

from core.vision.perception_strategy import PerceptionRequest, PerceptionStrategy


class PerceptionPlanner:
    """
    感知策略规划器——纯策略计算，无 IO，不需要 async

    决策规则（按优先级）：
    1. 纯对话/数学/推理任务 → NONE（不需要感知）
    2. 首轮且提到浏览器/网页/点击 → VISION_FULL
    3. 后续轮次且上轮工具为 mouse_click/keyboard_input → VISION_FULL
    4. 其他 → ENVIRONMENT（仅系统环境）
    """

    def plan(
        self,
        task_type: str,
        round_count: int,
        execution_history: list[dict[str, Any]],
        user_input: str
    ) -> PerceptionRequest:
        """
        规划感知策略

        Args:
            task_type: 任务类型（如 chat / file_operation / browser / coding）
            round_count: 当前轮次（从 0 开始）
            execution_history: 执行历史（工具调用记录）
            user_input: 用户原始输入

        Returns:
            PerceptionRequest: 不可变的感知请求对象
        """
        # 规则 1：纯对话/数学/推理任务不需要感知
        if task_type in ("chat", "math", "reasoning"):
            return PerceptionRequest(
                strategy=PerceptionStrategy.NONE,
                user_input=user_input
            )

        # 规则 2：首轮且提到浏览器/网页/点击/查看 → VISION_FULL
        vision_keywords = ("浏览器", "网页", "点击", "查看", "打开", "页面", "截图")
        if round_count == 0 and any(kw in user_input for kw in vision_keywords):
            return PerceptionRequest(
                strategy=PerceptionStrategy.VISION_FULL,
                user_input=user_input
            )

        # 规则 3：后续轮次且上轮工具为鼠标/键盘操作 → VISION_FULL
        if round_count > 0 and execution_history:
            last_tool = execution_history[-1].get("tool", "")
            if last_tool in ("mouse_click", "keyboard_input", "scroll", "drag"):
                return PerceptionRequest(
                    strategy=PerceptionStrategy.VISION_FULL,
                    user_input=user_input
                )

        # 规则 4：快速视觉检查（提到图片、颜色、位置等）
        quick_keywords = ("图片", "颜色", "位置", "图标", "按钮", "文字")
        if any(kw in user_input for kw in quick_keywords):
            return PerceptionRequest(
                strategy=PerceptionStrategy.VISION_QUICK,
                user_input=user_input
            )

        # 默认：仅环境感知
        return PerceptionRequest(
            strategy=PerceptionStrategy.ENVIRONMENT,
            user_input=user_input
        )
