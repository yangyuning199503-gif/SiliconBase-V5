#!/usr/bin/env python3
"""
TaskContextIntegrator - 任务上下文整合器（Week 4功能整合）

整合世界模型(WorldModel)和阶段锚点(PhaseAnchor)，
提供统一的任务上下文构建接口，遵循零静默失败原则。

核心功能：
1. 整合世界模型预测和阶段锚点历史
2. 构建完整的任务上下文提示词
3. 预测行动后果和风险评估
4. 支持多阶段任务状态追踪
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.exceptions import AgentExecutionError
from core.logger import logger


class TaskPhase(Enum):
    """任务阶段枚举"""
    INIT = "init"                    # 初始化
    PERCEPTION = "perception"        # 感知
    UNDERSTANDING = "understanding"  # 理解
    PLANNING = "planning"            # 规划
    EXECUTION = "execution"          # 执行
    REFLECTION = "reflection"        # 反思
    COMPLETION = "completion"        # 完成


@dataclass
class TaskContext:
    """完整任务上下文"""
    # 阶段锚点信息
    completed_phases: list[str] = field(default_factory=list)
    current_phase: str = ""
    anchor_summary: str = ""

    # 世界模型预测
    prediction_text: str = ""
    success_probability: float = 0.0
    risk_level: str = "unknown"
    suggested_action: str = ""

    # 综合上下文
    full_context: str = ""
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "completed_phases": self.completed_phases,
            "current_phase": self.current_phase,
            "anchor_summary": self.anchor_summary,
            "prediction_text": self.prediction_text,
            "success_probability": self.success_probability,
            "risk_level": self.risk_level,
            "suggested_action": self.suggested_action,
            "full_context": self.full_context,
            "timestamp": self.timestamp
        }


class TaskContextIntegrator:
    """
    任务上下文整合器

    整合世界模型的预测能力和阶段锚点的历史记录，
    为AI提供全面的任务执行上下文。

    设计原则：
    1. 延迟导入避免循环依赖
    2. 零静默失败 - 构建失败时抛出明确异常
    3. 渐进式构建 - 部分组件失败时提供降级结果
    4. 统一输出 - 标准化的TaskContext结构

    使用示例：
        integrator = TaskContextIntegrator()

        # 构建完整上下文
        context = integrator.build_context(task_state)

        # 获取预测建议
        prediction = integrator.predict_next_step(task_state, proposed_actions)

        # 保存阶段锚点
        integrator.save_phase_anchor("execution", execution_data)
    """

    def __init__(self, user_id: str = "default", session_id: str = ""):
        """
        初始化任务上下文整合器

        Args:
            user_id: 用户ID
            session_id: 会话ID
        """
        self.user_id = user_id
        self.session_id = session_id
        self._phase_anchor_manager = None
        self._world_model = None
        self._initialized = False

        logger.info(f"[TaskContextIntegrator] 初始化完成，用户: {user_id}")

    def _lazy_init(self):
        """延迟初始化"""
        if self._initialized:
            return

        try:
            from core.memory.phase_anchor import get_phase_anchor_manager
            from core.world_model.world_model import get_world_model

            self._phase_anchor_manager = get_phase_anchor_manager()
            self._world_model = get_world_model()
            self._initialized = True

            logger.debug("[TaskContextIntegrator] 延迟初始化完成")
        except Exception as e:
            logger.error(f"[TaskContextIntegrator] 初始化失败: {e}")
            raise AgentExecutionError(f"任务上下文整合器初始化失败: {e}") from e

    def build_context(self, task_state: dict[str, Any],
                     proposed_actions: list[dict[str, Any]] = None) -> TaskContext:
        """
        整合世界模型和阶段锚点，构建完整任务上下文

        Args:
            task_state: 当前任务状态，包含：
                - goal: 任务目标
                - current_phase: 当前阶段
                - execution_history: 执行历史
                - perception: 当前感知状态
            proposed_actions: 提议的行动列表（用于世界模型预测）

        Returns:
            TaskContext: 完整的任务上下文

        Raises:
            AgentExecutionError: 构建失败时抛出
        """
        self._lazy_init()

        context = TaskContext(timestamp=time.time())

        try:
            # ===== 1. 获取阶段锚点信息 =====
            anchor_data = self._get_phase_anchor_summary()
            context.completed_phases = anchor_data.get("completed_phases", [])
            context.anchor_summary = anchor_data.get("summary", "")
            context.current_phase = task_state.get("current_phase", "unknown")

        except Exception as e:
            logger.warning(f"[TaskContextIntegrator] 获取阶段锚点失败: {e}")
            context.anchor_summary = "【阶段信息暂不可用】"

        try:
            # ===== 2. 获取世界模型预测 =====
            if proposed_actions:
                prediction_data = self._get_world_model_prediction(
                    task_state, proposed_actions
                )
                context.prediction_text = prediction_data.get("text", "")
                context.success_probability = prediction_data.get("success_probability", 0.0)
                context.risk_level = prediction_data.get("risk_level", "unknown")
                context.suggested_action = prediction_data.get("suggested_action", "")
            else:
                context.prediction_text = "【未提供行动，跳过预测】"

        except Exception as e:
            logger.warning(f"[TaskContextIntegrator] 获取世界模型预测失败: {e}")
            context.prediction_text = "【世界模型预测暂不可用】"

        # ===== 3. 构建完整上下文 =====
        context.full_context = self._format_full_context(context, task_state)

        logger.debug(f"[TaskContextIntegrator] 上下文构建完成，"
                    f"阶段: {len(context.completed_phases)}个, "
                    f"风险: {context.risk_level}")

        return context

    def _get_phase_anchor_summary(self) -> dict[str, Any]:
        """获取阶段锚点摘要"""
        try:
            # 获取用户最近的锚点
            recent_anchors = self._phase_anchor_manager.get_recent_by_user(
                user_id=self.user_id,
                limit=10
            )

            if not recent_anchors:
                return {
                    "completed_phases": [],
                    "summary": "【暂无阶段历史】"
                }

            # 提取阶段信息
            phases = []
            phase_details = []

            for anchor in recent_anchors:
                phase = anchor.get("phase", "unknown")
                phases.append(phase)

                # 格式化阶段信息
                timestamp = anchor.get("timestamp", 0)
                time_str = time.strftime("%H:%M:%S", time.localtime(timestamp))
                phase_details.append(f"  [{time_str}] {phase}")

            # 生成摘要
            summary_lines = [
                "【阶段执行历史】",
                f"已执行阶段数: {len(phases)}",
                f"阶段序列: {' -> '.join(phases[-5:])}"  # 最近5个阶段
            ]

            if phase_details:
                summary_lines.extend(["", "详细记录:"])
                summary_lines.extend(phase_details[:5])  # 最近5条

            return {
                "completed_phases": phases,
                "summary": "\n".join(summary_lines)
            }

        except Exception as e:
            logger.error(f"[TaskContextIntegrator] 获取阶段锚点摘要失败: {e}")
            return {
                "completed_phases": [],
                "summary": f"【阶段信息获取失败: {e}】"
            }

    async def _get_world_model_prediction(self, task_state: dict[str, Any],
                                    proposed_actions: list[dict[str, Any]]) -> dict[str, Any]:
        """获取世界模型预测"""
        try:
            # 构建当前状态
            current_state = self._build_world_model_state(task_state)

            # 获取预测结果
            prediction_result = await self._world_model.predict_action_outcomes(
                current_state=current_state,
                proposed_actions=proposed_actions
            )

            # 解析预测结果
            predictions = prediction_result.get("predictions", [])
            overall_risk = prediction_result.get("overall_risk", 0.5)
            best_index = prediction_result.get("best_action_index", -1)

            # 格式化预测文本
            lines = ["【世界模型预测】"]

            if predictions:
                for i, pred in enumerate(predictions[:3], 1):  # 最多显示3个
                    tool_id = pred.get("tool_id", "unknown")
                    success_prob = pred.get("success_prob", 0) * 100
                    risk = pred.get("risk", 0) * 100
                    recommendation = pred.get("recommendation", "")

                    lines.append(f"\n方案{i}: {tool_id}")
                    lines.append(f"  成功率: {success_prob:.0f}%")
                    lines.append(f"  风险: {risk:.0f}%")
                    lines.append(f"  建议: {recommendation}")

                # 标记最佳方案
                if best_index >= 0 and best_index < len(predictions):
                    best = predictions[best_index]
                    lines.append(f"\n⭐ 推荐方案: {best.get('tool_id', '')}")
            else:
                lines.append("【暂无预测数据】")

            # 风险评估
            if overall_risk > 0.7:
                risk_level = "high"
                lines.append("\n🚨 高风险警告：当前行动风险较高，建议谨慎")
            elif overall_risk > 0.4:
                risk_level = "medium"
                lines.append("\n⚠️ 中等风险：需注意操作细节")
            else:
                risk_level = "low"
                lines.append("\n✅ 风险可控")

            # 计算整体成功率
            avg_success = sum(p.get("success_prob", 0.5) for p in predictions) / len(predictions) if predictions else 0.5

            return {
                "text": "\n".join(lines),
                "success_probability": avg_success,
                "risk_level": risk_level,
                "suggested_action": predictions[best_index].get("tool_id", "") if best_index >= 0 else ""
            }

        except Exception as e:
            logger.error(f"[TaskContextIntegrator] 世界模型预测失败: {e}")
            return {
                "text": f"【世界模型预测失败: {e}】",
                "success_probability": 0.5,
                "risk_level": "unknown",
                "suggested_action": ""
            }

    def _build_world_model_state(self, task_state: dict[str, Any]) -> dict[str, Any]:
        """从任务状态构建世界模型状态"""
        return {
            "task_context": {
                "goal": task_state.get("goal", ""),
                "current_phase": task_state.get("current_phase", ""),
                "attempt_count": len(task_state.get("execution_history", []))
            },
            "execution_history": task_state.get("execution_history", []),
            "current_tool": task_state.get("current_tool"),
            "recent_results": [h.get("success", False) for h in task_state.get("execution_history", [])[-5:]]
        }

    def _format_full_context(self, context: TaskContext,
                            task_state: dict[str, Any]) -> str:
        """格式化完整上下文"""
        lines = [
            "╔══════════════════════════════════════════════════════════════╗",
            "║                    【任务上下文】                             ║",
            "╚══════════════════════════════════════════════════════════════╝",
            "",
            f"【任务目标】 {task_state.get('goal', '未设定')}",
            f"【当前阶段】 {context.current_phase}",
            ""
        ]

        # 阶段历史
        if context.anchor_summary:
            lines.extend([
                context.anchor_summary,
                ""
            ])

        # 世界模型预测
        if context.prediction_text:
            lines.extend([
                context.prediction_text,
                ""
            ])

        # 执行指导
        lines.extend([
            "┌─────────────────────────────────────────────────────────────┐",
            "│ 【执行指导】                                                  │",
            "└─────────────────────────────────────────────────────────────┘"
        ])

        if context.risk_level == "high":
            lines.append("⚠️ 当前预测风险较高，建议：")
            lines.append("   1. 先验证再执行")
            lines.append("   2. 考虑请求用户确认")
            lines.append("   3. 准备回滚方案")
        elif context.suggested_action:
            lines.append(f"💡 世界模型推荐行动: {context.suggested_action}")
            lines.append(f"   预期成功率: {context.success_probability*100:.0f}%")
        else:
            lines.append("💡 基于历史经验自主决策")

        return "\n".join(lines)

    async def save_phase_anchor(self, phase: str, data: dict[str, Any],
                         anchor_id: str | None = None) -> str:
        """
        保存阶段锚点（异步版本）

        Args:
            phase: 阶段名称
            data: 阶段数据
            anchor_id: 可选的锚点ID

        Returns:
            锚点ID
        """
        self._lazy_init()

        try:
            anchor_id = await self._phase_anchor_manager.save(
                phase=phase,
                data=data,
                user_id=self.user_id,
                session_id=self.session_id,
                anchor_id=anchor_id
            )
            logger.debug(f"[TaskContextIntegrator] 保存阶段锚点: {anchor_id}, 阶段: {phase}")
            return anchor_id
        except Exception as e:
            logger.error(f"[TaskContextIntegrator] 保存阶段锚点失败: {e}")
            raise AgentExecutionError(f"保存阶段锚点失败: {e}") from e

    def predict_next_step(self, task_state: dict[str, Any],
                         available_tools: list[str]) -> dict[str, Any]:
        """
        预测下一步最优行动

        Args:
            task_state: 当前任务状态
            available_tools: 可用工具列表

        Returns:
            预测结果
        """
        self._lazy_init()

        try:
            current_state = self._build_world_model_state(task_state)

            suggestion = self._world_model.suggest_action(
                current_state=current_state,
                available_tools=available_tools
            )

            if suggestion:
                return {
                    "has_suggestion": True,
                    "type": suggestion.get("type", "unknown"),
                    "best_action": suggestion.get("best_action"),
                    "score": suggestion.get("score", 0),
                    "reason": suggestion.get("reason", ""),
                    "action_sequence": suggestion.get("action_sequence", [])
                }
            else:
                return {
                    "has_suggestion": False,
                    "reason": "数据不足，无法提供建议"
                }

        except Exception as e:
            logger.error(f"[TaskContextIntegrator] 预测下一步失败: {e}")
            return {
                "has_suggestion": False,
                "error": str(e)
            }

    async def mcts_plan(self, task_state: dict[str, Any],
                  goal: str = None,
                  iterations: int = 100) -> dict[str, Any]:
        """
        使用MCTS规划最优路径

        Args:
            task_state: 当前任务状态
            goal: 目标描述
            iterations: MCTS模拟次数

        Returns:
            规划结果
        """
        self._lazy_init()

        try:
            current_state = self._build_world_model_state(task_state)

            plan_result = await self._world_model.mcts_plan(
                current_state=current_state,
                goal=goal or task_state.get("goal", ""),
                iterations=iterations
            )

            return plan_result

        except Exception as e:
            logger.error(f"[TaskContextIntegrator] MCTS规划失败: {e}")
            return {
                "optimal_path": [],
                "path_description": f"规划失败: {e}",
                "expected_success": 0.5,
                "total_risk": 0.5
            }

    def get_stats(self) -> dict[str, Any]:
        """获取整合器统计信息"""
        self._lazy_init()

        try:
            # 获取阶段锚点统计
            recent_anchors = self._phase_anchor_manager.get_recent_by_user(
                user_id=self.user_id,
                limit=1
            )
            anchor_count = len(recent_anchors) if recent_anchors else 0

            # 获取世界模型统计
            wm_stats = self._world_model.get_stats() if hasattr(self._world_model, 'get_stats') else {}

            return {
                "user_id": self.user_id,
                "session_id": self.session_id,
                "initialized": self._initialized,
                "phase_anchors": {
                    "recent_count": anchor_count
                },
                "world_model": wm_stats
            }
        except Exception as e:
            logger.error(f"[TaskContextIntegrator] 获取统计信息失败: {e}")
            return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# 全局实例和便捷函数
# ═══════════════════════════════════════════════════════════════════════════════

_task_context_integrator_instance: TaskContextIntegrator | None = None


def get_task_context_integrator(user_id: str = "default",
                                session_id: str = "") -> TaskContextIntegrator:
    """获取任务上下文整合器全局实例"""
    global _task_context_integrator_instance
    if _task_context_integrator_instance is None:
        _task_context_integrator_instance = TaskContextIntegrator(
            user_id=user_id,
            session_id=session_id
        )
    return _task_context_integrator_instance


def build_task_context(task_state: dict[str, Any],
                      proposed_actions: list[dict[str, Any]] = None,
                      user_id: str = "default") -> str:
    """
    便捷函数：构建任务上下文

    Args:
        task_state: 任务状态
        proposed_actions: 提议的行动
        user_id: 用户ID

    Returns:
        格式化的上下文文本
    """
    integrator = get_task_context_integrator(user_id)
    context = integrator.build_context(task_state, proposed_actions)
    return context.full_context


async def save_phase(phase: str, data: dict[str, Any],
               user_id: str = "default",
               session_id: str = "") -> str:
    """
    便捷函数：保存阶段锚点（异步版本）

    Args:
        phase: 阶段名称
        data: 阶段数据
        user_id: 用户ID
        session_id: 会话ID

    Returns:
        锚点ID
    """
    integrator = get_task_context_integrator(user_id, session_id)
    return await integrator.save_phase_anchor(phase, data)


# ═══════════════════════════════════════════════════════════════════════════════
# 文件总结
# ═══════════════════════════════════════════════════════════════════════════════
#
# 【文件角色】
# TaskContextIntegrator是Week 4功能整合的核心组件之一，统一整合世界模型和阶段锚点，
# 为系统提供完整的任务上下文构建能力。
#
# 【核心功能】
# 1. 阶段历史追踪：通过阶段锚点获取任务执行历史
# 2. 行动预测：基于世界模型预测行动后果
# 3. 风险评估：量化当前行动的风险等级
# 4. MCTS规划：使用蒙特卡洛树搜索规划最优路径
# 5. 统一上下文：整合所有信息为结构化提示词
#
# 【设计特点】
# 1. 延迟初始化：避免循环依赖
# 2. 渐进式构建：部分失败时提供降级结果
# 3. 完整输出：TaskContext包含所有上下文信息
# 4. 便捷函数：提供简单易用的全局函数
#
# 【使用场景】
# 1. AgentLoop每轮开始时调用build_context()
# 2. 任务阶段切换时调用save_phase_anchor()
# 3. 多方案决策时调用predict_next_step()
# 4. 复杂任务规划时调用mcts_plan()
#
# ═══════════════════════════════════════════════════════════════════════════════
