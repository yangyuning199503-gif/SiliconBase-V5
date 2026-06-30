#!/usr/bin/env python3
"""
演示学习器 (Demonstration Learner)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

将用户录制的操作转换为结构化的可执行流程。

功能：
1. 分析录制数据
2. 提取关键操作步骤
3. 生成可执行的Procedure
4. 识别可参数化的变量
"""

import re
from dataclasses import dataclass
from typing import Any

from .operation_recorder import OperationType, UserOperation
from .procedure_library import Procedure, ProcedureStep


@dataclass
class ExtractedParameter:
    """提取的参数"""
    name: str
    value: str
    position: int  # 在操作中的位置
    context: str   # 上下文描述


class DemonstrationLearner:
    """
    演示学习器

    分析用户录制的操作，生成结构化的执行流程。
    """

    # 常见可参数化模式
    PARAMETER_PATTERNS = {
        "destination": ["去(.+?)", "到(.+?)", "目的地(.+?)"],
        "date": [r"(\d{4}-\d{2}-\d{2})", r"(\d{2}月\d{2}日)"],
        "time": [r"(\d{2}:\d{2})", r"(\d{2}点)"],
        "amount": [r"(\d+)元", r"(\d+)块"],
        "keyword": ["搜索(.+?)", "查找(.+?)"],
    }

    def __init__(self):
        self._tool_mapping = {
            OperationType.MOUSE_CLICK.value: "mouse_click",
            OperationType.MOUSE_MOVE.value: "mouse_move",
            OperationType.KEYBOARD_INPUT.value: "keyboard_input",
            OperationType.KEYBOARD_HOTKEY.value: "keyboard_hotkey",
            OperationType.APP_OPEN.value: "launch_app",
            OperationType.APP_SWITCH.value: "window_action",
            OperationType.SCROLL.value: "scroll",
            OperationType.WAIT.value: "wait",
        }

    def learn_from_recording(
        self,
        operations: list[UserOperation],
        task_description: str,
        context: dict[str, Any] | None = None
    ) -> Procedure:
        """
        从录制中学习流程

        Args:
            operations: 录制的操作列表
            task_description: 任务描述
            context: 上下文信息

        Returns:
            学习到的Procedure
        """
        if not operations:
            raise ValueError("操作列表为空")

        # 1. 清理和过滤操作
        cleaned_ops = self._clean_operations(operations)

        # 2. 提取可参数化的值
        parameters = self._extract_parameters(cleaned_ops, task_description)

        # 3. 转换为流程步骤
        steps = self._convert_to_steps(cleaned_ops, parameters)

        # 4. 生成意图关键词
        intent = self._generate_intent(task_description)

        # 5. 创建Procedure
        procedure = Procedure(
            procedure_id="",
            name=self._generate_name(task_description),
            intent=intent,
            description=task_description,
            steps=steps,
            parameters={p.name: p.value for p in parameters},
            tags=self._generate_tags(cleaned_ops, task_description),
            source_recording_id=context.get("recording_id") if context else None
        )

        return procedure

    def _clean_operations(self, operations: list[UserOperation]) -> list[UserOperation]:
        """清理操作列表（去重、过滤无效操作）"""
        cleaned = []
        last_op_type = None

        for op in operations:
            # 跳过纯注释
            if op.operation_type == OperationType.COMMENT.value:
                continue

            # 合并连续的相同类型操作（如连续鼠标移动）
            if op.operation_type == last_op_type == OperationType.MOUSE_MOVE.value:
                # 只保留最后一个鼠标移动
                if cleaned:
                    cleaned[-1] = op
                continue

            cleaned.append(op)
            last_op_type = op.operation_type

        return cleaned

    def _extract_parameters(
        self,
        operations: list[UserOperation],
        task_description: str
    ) -> list[ExtractedParameter]:
        """提取可参数化的值"""
        parameters = []

        # 从任务描述中提取
        for param_name, patterns in self.PARAMETER_PATTERNS.items():
            for pattern in patterns:
                matches = re.findall(pattern, task_description)
                for match in matches:
                    parameters.append(ExtractedParameter(
                        name=param_name,
                        value=match,
                        position=-1,
                        context="task_description"
                    ))

        # 从输入操作中提取可能的参数
        for i, op in enumerate(operations):
            if op.operation_type == OperationType.KEYBOARD_INPUT.value:
                text = op.params.get("text", "")
                # 如果是较长的文本，可能是可参数化的
                if len(text) > 2 and not text.isdigit():
                    # 检查是否包含常见地点、时间等
                    param_name = self._guess_parameter_type(text)
                    if param_name:
                        parameters.append(ExtractedParameter(
                            name=param_name,
                            value=text,
                            position=i,
                            context=f"keyboard_input at step {i}"
                        ))

        return parameters

    def _guess_parameter_type(self, text: str) -> str | None:
        """猜测参数类型"""
        # 简单启发式规则
        if any(city in text for city in ["上海", "北京", "广州", "深圳", "杭州"]):
            return "destination"
        if re.match(r"\d{4}-\d{2}-\d{2}", text):
            return "date"
        if "机票" in text or "酒店" in text:
            return "keyword"
        return None

    def _convert_to_steps(
        self,
        operations: list[UserOperation],
        parameters: list[ExtractedParameter]
    ) -> list[ProcedureStep]:
        """将操作转换为流程步骤"""
        steps = []
        param_values = {p.value: f"{{{p.name}}}" for p in parameters}

        step_number = 1
        for op in operations:
            # 获取对应的工具名
            tool_name = self._tool_mapping.get(op.operation_type)
            if not tool_name:
                continue

            # 转换参数，将具体值替换为参数占位符
            tool_params = self._convert_params(op.params, param_values)

            # 生成步骤描述
            description = self._generate_step_description(op, tool_params)

            step = ProcedureStep(
                step_id=f"step_{step_number}",
                step_number=step_number,
                description=description,
                tool_name=tool_name,
                tool_params=tool_params,
                expected_result=None,  # 可以后续补充
                retry_count=1,
                timeout=30,
                fallback_step=None
            )

            steps.append(step)
            step_number += 1

        return steps

    def _convert_params(
        self,
        params: dict[str, Any],
        param_values: dict[str, str]
    ) -> dict[str, Any]:
        """转换参数，替换为占位符"""
        converted = {}
        for key, value in params.items():
            if isinstance(value, str):
                # 尝试替换为参数占位符
                for param_val, placeholder in param_values.items():
                    if param_val in value:
                        value = value.replace(param_val, placeholder)
                        break
                converted[key] = value
            else:
                converted[key] = value
        return converted

    def _generate_step_description(
        self,
        operation: UserOperation,
        tool_params: dict[str, Any]
    ) -> str:
        """生成步骤描述"""
        op_type = operation.operation_type

        descriptions = {
            OperationType.MOUSE_CLICK.value:
                f"点击屏幕坐标 ({tool_params.get('x', '?')}, {tool_params.get('y', '?')})",
            OperationType.KEYBOARD_INPUT.value:
                f"输入文本: {tool_params.get('text', '')[:30]}",
            OperationType.KEYBOARD_HOTKEY.value:
                f"按下快捷键: {'+'.join(tool_params.get('keys', []))}",
            OperationType.APP_OPEN.value:
                f"打开应用: {tool_params.get('app_name', '未知应用')}",
            OperationType.APP_SWITCH.value:
                f"切换到应用: {tool_params.get('app_name', '未知应用')}",
            OperationType.SCROLL.value:
                f"向{tool_params.get('direction', '下')}滚动 {tool_params.get('amount', 3)} 行",
            OperationType.WAIT.value:
                f"等待 {tool_params.get('seconds', 1)} 秒",
        }

        return descriptions.get(op_type, f"执行操作: {op_type}")

    def _generate_intent(self, task_description: str) -> str:
        """生成意图关键词"""
        # 简单的意图提取
        task_lower = task_description.lower()

        # 常见意图映射
        intent_keywords = {
            "机票": "book_flight",
            "酒店": "book_hotel",
            "火车票": "book_train",
            "打车": "call_taxi",
            "外卖": "order_food",
            "购物": "online_shopping",
            "搜索": "web_search",
            "打开": "open_app",
            "播放": "play_media",
            "设置": "system_setting",
        }

        for keyword, intent in intent_keywords.items():
            if keyword in task_lower:
                return intent

        # 默认意图
        return "general_task"

    def _generate_name(self, task_description: str) -> str:
        """生成流程名称"""
        # 取前20个字符作为名称
        name = task_description.strip()
        if len(name) > 20:
            name = name[:20] + "..."
        return f"操作流程: {name}"

    def _generate_tags(
        self,
        operations: list[UserOperation],
        task_description: str
    ) -> list[str]:
        """生成标签"""
        tags = []

        # 根据操作类型添加标签
        op_types = {op.operation_type for op in operations}

        if OperationType.APP_OPEN.value in op_types or OperationType.APP_SWITCH.value in op_types:
            tags.append("app_operation")

        if OperationType.MOUSE_CLICK.value in op_types or OperationType.KEYBOARD_INPUT.value in op_types:
            tags.append("ui_interaction")

        if OperationType.KEYBOARD_INPUT.value in op_types:
            tags.append("text_input")

        # 根据任务描述添加标签
        task_lower = task_description.lower()
        if any(word in task_lower for word in ["买", "订", "预定", "购买"]):
            tags.append("purchase")

        if any(word in task_lower for word in ["搜索", "查找", "查"]):
            tags.append("search")

        if any(word in task_lower for word in ["打开", "启动"]):
            tags.append("launch")

        return tags

    def analyze_procedure(self, procedure: Procedure) -> dict[str, Any]:
        """
        分析流程，提供优化建议

        Returns:
            分析报告
        """
        analysis = {
            "total_steps": len(procedure.steps),
            "estimated_duration": sum(step.timeout for step in procedure.steps),
            "tool_usage": {},
            "optimization_suggestions": [],
            "risk_points": [],
        }

        # 统计工具使用
        for step in procedure.steps:
            tool = step.tool_name
            analysis["tool_usage"][tool] = analysis["tool_usage"].get(tool, 0) + 1

        # 生成优化建议
        if len(procedure.steps) > 10:
            analysis["optimization_suggestions"].append(
                "流程步骤较多，考虑拆分为子流程"
            )

        # 检查是否有等待步骤
        wait_steps = [s for s in procedure.steps if s.tool_name == "wait"]
        if wait_steps:
            total_wait = sum(s.tool_params.get("seconds", 1) for s in wait_steps)
            analysis["optimization_suggestions"].append(
                f"包含 {len(wait_steps)} 个等待步骤，总计 {total_wait} 秒，可以尝试优化"
            )

        # 风险点
        if not procedure.steps:
            analysis["risk_points"].append("流程为空")

        if not any(s.tool_name in ["pixel_capture", "screen_ocr"] for s in procedure.steps):
            analysis["risk_points"].append("没有屏幕检查步骤，可能无法确认操作结果")

        return analysis


# 全局实例
_learner_instance: DemonstrationLearner | None = None

def get_demonstration_learner() -> DemonstrationLearner:
    """获取全局演示学习器实例"""
    global _learner_instance
    if _learner_instance is None:
        _learner_instance = DemonstrationLearner()
    return _learner_instance
