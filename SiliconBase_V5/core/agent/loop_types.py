#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
循环控制类型定义 - 基础数据结构  # 模块功能概述：定义Agent循环控制的基础数据类型
解耦 agent_loop 和 loop_controller 的循环导入  # 设计目的：解决模块间的循环导入问题
"""  # 文档字符串结束

import time  # 导入时间模块
from dataclasses import dataclass, field  # 从dataclasses导入数据类装饰器和字段函数
from typing import Any  # 从typing模块导入类型注解

try:
    from core.exceptions import MemorySystemError  # 统一异常根类
except ImportError:
    class MemorySystemError(Exception):
        """Fallback when core.exceptions is not available"""
        pass


@dataclass  # 数据类装饰器
class LoopState:  # 定义循环状态类，跟踪Agent循环的执行状态
    """循环状态跟踪"""  # 类文档字符串
    round_count: int = 0  # 当前执行轮次计数，默认为0
    max_rounds: int = 15  # 最大允许轮次，默认为15轮，防止无限循环
    consecutive_errors: int = 0  # 连续错误次数，用于检测执行异常
    last_tool_success: bool = True  # 上次工具调用是否成功，默认为True
    context_switches: int = 0  # 上下文切换次数，用于监控循环复杂度
    processed_tool_calls: dict[str, Any] = field(default_factory=dict)  # 【P0修复】已处理工具调用缓存，key=tool_call_id

    # 【P1】长任务中断恢复相关字段
    paused: bool = False  # 当前轮次是否处于暂停状态
    pause_count: int = 0  # 累计暂停次数，防止无限暂停循环
    original_task_id: str | None = None  # 恢复任务时指向原始任务ID
    resumed_from_checkpoint: bool = False  # 是否从快照恢复

    # 【P1修复】单步工具成功后强制结束循环，避免AI重复调用
    force_final_answer: bool = False

    def increment_round(self) -> bool:  # 增加轮次并检查是否允许继续执行的方法
        """增加轮次，返回是否允许继续执行

        修复说明 (P0-010):
        原逻辑: `return self.round_count < self.max_rounds` 会先递增再比较，
               导致执行 max_rounds+1 轮（第 max_rounds 次调用返回 True，
               第 max_rounds+1 次调用才返回 False）

        新逻辑: `return self.round_count <= self.max_rounds` 确保只执行 max_rounds 轮
               - 第 1~max_rounds 次调用: 返回 True，允许执行
               - 第 max_rounds+1 次调用: 返回 False，停止循环

        示例 (max_rounds=10):
        - 调用1: round_count=1, 返回 True  (执行第1轮)
        - ...
        - 调用10: round_count=10, 返回 True (执行第10轮)
        - 调用11: round_count=11, 返回 False (停止，不执行第11轮)
        """
        self.round_count += 1  # 轮次计数加1
        return self.round_count <= self.max_rounds  # 检查是否未超过最大轮次限制

    def record_error(self):  # 记录错误的方法
        """记录错误"""  # 方法文档字符串
        self.consecutive_errors += 1  # 连续错误计数加1

    def record_success(self):  # 记录成功的方法
        """记录成功"""  # 方法文档字符串
        self.consecutive_errors = 0  # 重置连续错误计数为0
        self.last_tool_success = True  # 设置上次工具调用成功标志


@dataclass  # 数据类装饰器
class ProgressTracker:  # 定义进度跟踪器类，用于跟踪任务执行进度
    """进度跟踪器"""  # 类文档字符串
    milestones: list[str] = field(default_factory=list)  # 里程碑列表，记录重要节点，默认为空列表
    current_step: int = 0  # 当前步骤序号，默认为0
    total_steps: int = 0  # 总步骤数，默认为0
    start_time: float = field(default_factory=time.time)  # 开始时间，默认为当前时间戳

    def add_milestone(self, description: str):  # 添加里程碑的方法
        """添加里程碑"""  # 方法文档字符串
        self.milestones.append(description)  # 将描述添加到里程碑列表
        self.current_step += 1  # 当前步骤加1

    def set_total_steps(self, total: int):  # 设置总步骤数的方法
        """设置总步骤数"""  # 方法文档字符串
        self.total_steps = total  # 设置总步骤数

    def get_progress_percent(self) -> float:  # 获取进度百分比的方法
        """获取进度百分比"""  # 方法文档字符串
        if self.total_steps == 0:  # 如果总步骤为0（防止除零错误）
            return 0.0  # 返回0%
        return (self.current_step / self.total_steps) * 100  # 计算并返回百分比

    def get_elapsed_time(self) -> float:  # 获取已用时间的方法
        """获取已用时间"""  # 方法文档字符串
        return time.time() - self.start_time  # 返回当前时间与开始时间的差值（秒）


class SmartLoopController:  # 定义智能循环控制器类，负责控制Agent循环的执行
    """智能循环控制器"""  # 类文档字符串

    def __init__(self):  # 初始化方法
        self.max_stagnation_rounds = 3  # 最大停滞轮次，超过则认为循环停滞
        self.stagnation_keywords = ["重复", "相同", "无效", "错误"]  # 停滞检测关键词列表

    def check_should_continue(self, loop_state: LoopState,
                              execution_history: list[dict],
                              last_response: str) -> tuple[bool, str]:  # 检查是否应该继续循环的方法
        """
        检查是否应该继续循环

        Returns:  # 返回值说明
            (should_continue: bool, reason: str)  # 返回元组：(是否继续，原因说明)
        """
        # 检查轮次限制
        if loop_state.round_count >= loop_state.max_rounds:  # 如果已达到最大轮次
            return False, "达到最大循环轮次限制"  # 返回False和停止原因

        # 检查连续错误
        if loop_state.consecutive_errors >= 3:  # 如果连续错误达到3次
            return False, "连续错误次数过多"  # 返回False和停止原因

        # 检查停滞（简单实现：检查响应是否重复）
        if execution_history and len(execution_history) >= 2:  # 如果有至少2条执行历史
            last_two = execution_history[-2:]  # 获取最近两次执行记录
            if self._is_stagnant(last_two, last_response):  # 检查是否停滞
                return False, "检测到执行停滞"  # 返回False和停止原因

        return True, ""  # 允许继续执行，原因为空

    def _is_stagnant(self, last_two: list[dict], last_response: str) -> bool:  # 检查是否停滞的私有方法
        """检查是否停滞"""  # 方法文档字符串
        if len(last_two) < 2:  # 如果执行记录少于2条
            return False  # 不足以判断停滞，返回False

        # 检查是否连续执行相同工具且失败
        if (last_two[0].get("tool") == last_two[1].get("tool") and  # 如果两次调用相同工具
            not last_two[1].get("success", False)):  # 且最后一次失败
            return True  # 判定为停滞

        # 检查响应是否包含停滞关键词
        return any(keyword in last_response for keyword in self.stagnation_keywords)  # 未检测到停滞

# ═══════════════════════════════════════════════════════════════════════════════
# 【文件总结】
# ═══════════════════════════════════════════════════════════════════════════════
#
# 【文件角色】
# 本文件(loop_types.py)是SiliconBase V5核心模块中的循环控制类型定义文件。
# 它定义了Agent主循环所需的基础数据结构和控制逻辑，专门用于解耦agent_loop.py
# 和loop_controller.py之间的循环导入问题。
#
# 【在系统中的位置】
# - 位于: SiliconBase_V5/core/loop_types.py
# - 设计目的: 解决模块间的循环依赖问题，作为基础类型被多个模块共享
# - 调用方: agent_loop.py、loop_controller.py等
#
# 【关联文件】
# 1. core/agent_loop.py - Agent主循环模块，使用LoopState和SmartLoopController
# 2. core/loop_controller.py - 循环控制器，从本模块导入类型（V6后主要从此导入）
#
# 【核心功能】
# 1. LoopState: 循环状态跟踪
#    - 跟踪当前执行轮次
#    - 限制最大轮次（防止无限循环）
#    - 记录连续错误次数
#    - 跟踪工具调用成功率
#
# 2. ProgressTracker: 进度跟踪器
#    - 记录执行里程碑
#    - 计算进度百分比
#    - 跟踪已用时间
#
# 3. SmartLoopController: 智能循环控制器
#    - 判断是否应继续循环
#    - 检测执行停滞（重复工具调用、错误响应等）
#    - 提供多种停止条件（轮次限制、错误限制、停滞检测）
#
# 【达到的效果】
# 1. 解耦设计: 通过将基础类型抽离到单独文件，解决模块间的循环导入问题
# 2. 循环安全: 通过max_rounds限制防止Agent无限循环
# 3. 错误处理: 通过consecutive_errors检测连续失败并优雅退出
# 4. 停滞检测: 识别重复执行和无效响应，避免浪费时间
# 5. 进度可视化: 通过ProgressTracker提供任务进度反馈
# 6. 模块化: 清晰的类型定义便于测试和维护
#
# 【使用示例】
#   from core.agent.loop_types import LoopState, SmartLoopController
#
#   loop_state = LoopState(max_rounds=10)  # 创建循环状态，最大10轮
#   controller = SmartLoopController()  # 创建智能控制器
#
#   while True:
#       should_continue, reason = controller.check_should_continue(
#           loop_state, execution_history, last_response
#       )
#       if not should_continue:
#           break
#       loop_state.increment_round()
#
# ═══════════════════════════════════════════════════════════════════════════════


# =============================================================================
# 【功能恢复 P0-P1】集成之前拆分但未使用的功能
# 这些类用于在agent_loop中调用之前拆分出来的功能
# =============================================================================

class FeatureRecoveryIntegration:
    """
    功能恢复集成器

    管理所有之前拆分但未使用的功能的调用
    """

    def __init__(self):
        self.task_count = 0
        self.config = self._load_config()

    def _load_config(self) -> dict:
        """从配置加载功能开关"""
        try:
            from core.config import config
            return config.get("feature_recovery", {})
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(
                f"[SILENT_FAILURE_BLOCKED] 配置加载失败: {e}",
                exc_info=True
            )
            return {}

    # ========== 1. 记忆晋升系统 (P0) ==========
    def should_run_promotion(self, round_count: int) -> bool:
        """检查是否应该运行记忆晋升评估"""
        promo_config = self.config.get("memory_promotion", {})
        if not promo_config.get("enabled", False):
            return False
        interval = promo_config.get("interval", 10)
        return round_count > 0 and round_count % interval == 0

    async def run_memory_promotion(self, user_id: str) -> dict:
        """运行记忆晋升评估"""
        try:
            from core.memory.memory_promotion import promotion_engine
            promo_config = self.config.get("memory_promotion", {})
            dry_run = promo_config.get("dry_run", False)

            report = await promotion_engine.evaluate_and_promote(user_id, dry_run=dry_run)

            if report.get("total_promoted", 0) > 0:
                import logging
                logging.getLogger(__name__).info(
                    f"[记忆晋升] L2→L3: {report.get('l2_to_l3', 0)}, "
                    f"L3→L4: {report.get('l3_to_l4', 0)}, 用户: {user_id[:8]}..."
                )

            return report

        except Exception as e:
            import logging
            logger_instance = logging.getLogger(__name__)
            logger_instance.error(f"[SILENT_FAILURE_BLOCKED] [记忆晋升] 评估异常: {e}", exc_info=True)
            raise MemorySystemError(f"记忆晋升评估失败: {e}") from e

    # ========== 2. 多维度反思 (P1) ==========
    def should_run_multi_dimension(self, task_score: int, task_success: bool) -> bool:
        """检查是否应该运行多维度反思"""
        reflection_config = self.config.get("reflection", {})
        multi_config = reflection_config.get("multi_dimension", {})

        if not multi_config.get("enabled", False):
            return False
        if not task_success:
            return False

        min_score = multi_config.get("min_task_score", 80)
        return task_score >= min_score

    async def run_multi_dimension_reflection(
        self,
        task_description: str,
        execution_history: list[str],
        user_id: str
    ) -> Any | None:
        """运行多维度反思"""
        try:
            from core.reflector import reflector
            reflection_config = self.config.get("reflection", {})
            multi_config = reflection_config.get("multi_dimension", {})
            dimensions = multi_config.get("dimensions",
                ["efficiency", "safety", "experience", "learning"])

            reflection = await reflector.reflect_multi_dimension(
                task_description=task_description,
                execution_history=execution_history,
                dimensions=dimensions
            )

            if reflection and hasattr(reflection, 'confidence') and reflection.confidence > 0.7:
                import logging
                logging.getLogger(__name__).info(
                    f"[多维度反思] 效率:{reflection.metadata.get('efficiency_score')} "
                    f"安全:{reflection.metadata.get('safety_score')} "
                    f"体验:{reflection.metadata.get('experience_score')}"
                )

            return reflection

        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"[多维度反思] 跳过: {e}")
            return None

    # ========== 3. 预测性反思 (P1) ==========
    def should_run_predictive(self, tool_name: str) -> bool:
        """检查是否应该运行预测性反思"""
        reflection_config = self.config.get("reflection", {})
        pred_config = reflection_config.get("predictive", {})

        if not pred_config.get("enabled", False):
            return False

        high_risk_tools = pred_config.get("high_risk_tools",
            ["delete_file", "modify_system", "execute_shell"])
        return tool_name in high_risk_tools

    def run_predictive_reflection(
        self,
        tool_name: str,
        tool_params: dict,
        user_intent: str
    ) -> Any | None:
        """运行预测性反思"""
        try:
            import asyncio

            from core.reflector import reflector
            loop = asyncio.get_event_loop()
            prediction = asyncio.run_coroutine_threadsafe(
                reflector.reflect_before_action(
                    action_description=f"使用工具 {tool_name}",
                    context={"user_intent": user_intent, "tool_params": tool_params}
                ),
                loop
            ).result()

            if prediction and hasattr(prediction, 'confidence') and prediction.confidence > 0.8:
                risk_level = prediction.metadata.get("risk_level", "low")
                if risk_level in ["high", "critical"]:
                    import logging
                    logging.getLogger(__name__).warning(
                        f"[预测性反思] 检测到高风险操作: {prediction.suggestion}"
                    )

            return prediction

        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"[预测性反思] 跳过: {e}")
            return None

    # ========== 4. 反思质量评估 (P0) ==========
    def should_assess_reflection_quality(self) -> bool:
        """检查是否应该评估反思质量"""
        reflection_config = self.config.get("reflection", {})
        quality_config = reflection_config.get("quality_assessment", {})
        return quality_config.get("enabled", False)

    def assess_reflection_quality(self, reflection: Any) -> float:
        """评估反思质量"""
        try:
            from core.reflector import reflector
            reflection_config = self.config.get("reflection", {})
            quality_config = reflection_config.get("quality_assessment", {})
            quality_config.get("min_score", 0.3)

            if hasattr(reflector, 'assess_reflection_quality'):
                score = reflector.assess_reflection_quality(reflection)
                return score
            return 1.0  # 默认通过

        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"[反思质量] 评估失败: {e}")
            return 1.0  # 失败时默认通过

    # ========== 5. 视觉健康检查 (P0) ==========
    def run_vision_health_check(self) -> dict:
        """运行视觉健康检查"""
        try:
            from core.vision.vision_health_check import vision_health_checker
            vision_config = self.config.get("vision", {})
            health_config = vision_config.get("health_check", {})

            if not health_config.get("enabled", False):
                return {}

            auto_disable = health_config.get("auto_disable_on_failure", True)
            report = vision_health_checker.run_full_check(auto_disable_on_failure=auto_disable)

            import logging
            if report.status.value == "fail":
                logging.getLogger(__name__).warning(f"[视觉健康] 检查失败: {report.summary}")
            else:
                logging.getLogger(__name__).info(f"[视觉健康] 检查通过: {report.summary}")

            return {"status": report.status.value, "summary": report.summary}

        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"[视觉健康] 检查异常: {e}")
            return {}

    # ========== 6. MCTS规划 (P1) ==========
    def should_use_mcts_planning(self, task_complexity: float) -> bool:
        """检查是否应该使用MCTS规划"""
        world_model_config = self.config.get("world_model", {})
        mcts_config = world_model_config.get("mcts_planning", {})

        if not mcts_config.get("enabled", False):
            return False

        min_complexity = mcts_config.get("min_task_complexity", 0.7)
        return task_complexity >= min_complexity

    async def run_mcts_planning(
        self,
        goal: str,
        available_tools: list[str]
    ) -> list[dict] | None:
        """运行MCTS规划"""
        try:
            from core.world_model import get_world_model
            world_model_config = self.config.get("world_model", {})
            mcts_config = world_model_config.get("mcts_planning", {})

            world_model = get_world_model()

            plan = await world_model.mcts_plan(
                goal=goal,
                available_tools=available_tools,
                max_depth=mcts_config.get("max_depth", 5),
                simulations=mcts_config.get("simulations", 50)
            )

            if plan and len(plan) > 0:
                import logging
                logging.getLogger(__name__).info(f"[MCTS规划] 生成{len(plan)}步计划")
                return plan

        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"[MCTS规划] 失败: {e}")

        return None

    # ========== 计数器递增 ==========
    def increment_task_count(self):
        """递增任务计数"""
        self.task_count += 1


# ════════════════════════════════════════════════════════════════════════════
# 【文件结束】loop_types.py
# ════════════════════════════════════════════════════════════════════════════
