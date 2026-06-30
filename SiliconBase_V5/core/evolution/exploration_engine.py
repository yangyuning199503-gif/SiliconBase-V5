#!/usr/bin/env python3
"""
探索引擎 - 任务探索和学习系统
"""

import threading
import time
from dataclasses import dataclass, field
from enum import Enum

from core.logger import logger


class TaskStage(Enum):
    """任务阶段 - 与agent_loop.py期望的值保持一致"""
    UNKNOWN = "unknown"           # 未知任务（新任务）
    KNOWN = "known"               # 已知任务
    MASTERED = "mastered"         # 已掌握任务
    INITIAL = "initial"           # 初始阶段
    EXPLORING = "exploring"       # 探索中
    EXECUTING = "executing"       # 执行中
    VERIFYING = "verifying"       # 验证中
    COMPLETED = "completed"       # 已完成
    FAILED = "failed"             # 失败


@dataclass
class TaskProfile:
    """任务画像"""
    task_type: str
    complexity: int = 5           # 复杂度 1-10
    estimated_time: int = 60      # 预估时间(秒)
    required_tools: list[str] = field(default_factory=list)
    common_patterns: list[str] = field(default_factory=list)
    attempt_count: int = 0        # 执行次数（agent_loop.py需要）


class ExplorationEngine:
    """探索引擎 - 单例模式"""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        self._profiles: dict[str, TaskProfile] = {}
        self._exploration_history: list[dict] = []
        logger.info("探索引擎初始化完成")

    def explore_task(self, task_description: str, task_type: str | None = None) -> dict:
        """探索任务"""
        exploration_id = f"expl_{int(time.time() * 1000)}"

        detected_type = task_type or self._detect_task_type(task_description)
        profile = self._get_or_create_profile(detected_type)

        exploration_result = {
            'exploration_id': exploration_id,
            'task_type': detected_type,
            'stage': TaskStage.EXPLORING.value,
            'profile': {
                'complexity': profile.complexity,
                'estimated_time': profile.estimated_time,
                'required_tools': profile.required_tools
            },
            'suggestions': self._generate_suggestions(detected_type, task_description),
            'timestamp': time.time()
        }

        self._exploration_history.append(exploration_result)
        logger.info(f"任务探索完成 [{exploration_id}]: 类型={detected_type}")
        return exploration_result

    def _detect_task_type(self, task_description: str) -> str:
        """检测任务类型"""
        task_lower = task_description.lower()

        if any(kw in task_lower for kw in ['文件', 'folder', 'directory', 'path']):
            return 'file_operation'
        elif any(kw in task_lower for kw in ['搜索', 'search', 'find', 'query']):
            return 'search'
        elif any(kw in task_lower for kw in ['代码', 'code', 'program', 'script']):
            return 'coding'
        elif any(kw in task_lower for kw in ['分析', 'analyze', 'analysis']):
            return 'analysis'
        else:
            return 'general'

    def _get_or_create_profile(self, task_type: str) -> TaskProfile:
        """获取或创建任务画像"""
        if task_type not in self._profiles:
            self._profiles[task_type] = TaskProfile(
                task_type=task_type,
                complexity=5,
                estimated_time=60,
                required_tools=[],
                common_patterns=[]
            )
        return self._profiles[task_type]

    def _generate_suggestions(self, task_type: str, task_description: str) -> list[str]:
        """生成执行建议"""
        suggestions = []

        if task_type == 'file_operation':
            suggestions.append("检查文件路径是否存在")
            suggestions.append("确认文件权限")
        elif task_type == 'search':
            suggestions.append("明确搜索范围和条件")
            suggestions.append("考虑使用索引加速")
        elif task_type == 'coding':
            suggestions.append("先理解需求再编写代码")
            suggestions.append("添加必要的错误处理")
        else:
            suggestions.append("分解任务为更小步骤")
            suggestions.append("验证每个步骤的结果")

        return suggestions

    def update_profile(self, task_type: str, execution_result: dict):
        """更新任务画像"""
        profile = self._get_or_create_profile(task_type)

        execution_time = execution_result.get('execution_time', 60)
        success = execution_result.get('success', False)

        # 调整预估时间
        profile.estimated_time = int((profile.estimated_time + execution_time) / 2)

        # 根据结果调整复杂度
        if success and execution_time < profile.estimated_time:
            profile.complexity = max(1, profile.complexity - 1)
        elif not success:
            profile.complexity = min(10, profile.complexity + 1)

        logger.debug(f"更新任务画像 [{task_type}]: 复杂度={profile.complexity}")

    def get_exploration_context(self, task_type: str) -> dict:
        """获取探索上下文"""
        profile = self._get_or_create_profile(task_type)
        return {
            'task_type': task_type,
            'complexity': profile.complexity,
            'estimated_time': profile.estimated_time,
            'required_tools': profile.required_tools,
            'patterns': profile.common_patterns
        }

    def get_task_stage(self, user_instruction: str) -> tuple:
        """获取任务阶段和画像

        Args:
            user_instruction: 用户指令

        Returns:
            tuple: (TaskStage, TaskProfile) 任务阶段和任务画像
        """
        try:
            if not user_instruction or not user_instruction.strip():
                logger.warning("[ExplorationEngine] get_task_stage 用户指令为空，返回默认阶段")
                return TaskStage.UNKNOWN, self._get_or_create_profile('general')

            task_type = self._detect_task_type(user_instruction)
            profile = self._get_or_create_profile(task_type)

            # 根据任务类型判断阶段（与agent_loop.py期望的unknown/known/mastered保持一致）
            # 简单启发式：通用类型为未知，特定类型为已知
            if task_type == 'general':
                stage = TaskStage.UNKNOWN
            elif profile.attempt_count > 5:
                stage = TaskStage.MASTERED
            else:
                stage = TaskStage.KNOWN

            logger.info(f"[ExplorationEngine] 任务阶段: {task_type} -> {stage.value}")
            return stage, profile
        except Exception as e:
            logger.error(f"[ExplorationEngine] get_task_stage 失败: {e}")
            raise

    def start_exploration(self, user_instruction: str, session_id: str) -> dict:
        """开始探索任务

        Args:
            user_instruction: 用户指令
            session_id: 会话ID

        Returns:
            Dict: 探索上下文
        """
        try:
            if not user_instruction:
                logger.error("[ExplorationEngine] start_exploration 用户指令为空")
                raise ValueError("用户指令不能为空")
            if not session_id:
                logger.error("[ExplorationEngine] start_exploration 会话ID为空")
                raise ValueError("会话ID不能为空")

            context = self.explore_task(user_instruction)
            context['session_id'] = session_id
            logger.info(f"[ExplorationEngine] 开始探索: session_id={session_id}")
            return context
        except Exception as e:
            logger.error(f"[ExplorationEngine] start_exploration 失败: {e}")
            raise

    def continue_exploration(self, session_id: str, result: dict) -> dict:
        """继续探索任务

        Args:
            session_id: 会话ID
            result: 上一轮执行结果

        Returns:
            Dict: 更新的探索上下文
        """
        try:
            if not session_id:
                logger.error("[ExplorationEngine] continue_exploration 会话ID为空")
                raise ValueError("会话ID不能为空")

            logger.info(f"[ExplorationEngine] 继续探索: session_id={session_id}")
            return {
                'status': 'completed',
                'result': result,
                'session_id': session_id
            }
        except Exception as e:
            logger.error(f"[ExplorationEngine] continue_exploration 失败: {e}")
            raise

    def get_prompt_enhancement(self, user_instruction: str, round_num: int) -> str:
        """获取提示增强

        Args:
            user_instruction: 用户指令
            round_num: 当前轮次

        Returns:
            str: 增强提示文本
        """
        try:
            if not user_instruction:
                logger.error("[ExplorationEngine] get_prompt_enhancement 用户指令为空")
                return ""
            if round_num < 0:
                logger.error(f"[ExplorationEngine] get_prompt_enhancement 轮次无效: {round_num}")
                return ""

            enhancement = f"[探索增强] 第{round_num}轮优化建议：请基于之前的执行结果继续优化"
            logger.debug(f"[ExplorationEngine] 生成提示增强: 轮次={round_num}")
            return enhancement
        except Exception as e:
            logger.error(f"[ExplorationEngine] get_prompt_enhancement 失败: {e}")
            raise


def get_exploration_engine() -> ExplorationEngine:
    """获取探索引擎实例"""
    return ExplorationEngine()


def get_task_stage(task_id: str) -> TaskStage:
    """获取任务阶段"""
    return TaskStage.EXECUTING


def get_exploration_context(task_type: str) -> dict:
    """获取探索上下文"""
    engine = get_exploration_engine()
    return engine.get_exploration_context(task_type)


# 向后兼容
try:
    _exploration_engine = get_exploration_engine()
except Exception as e:
    logger.error(f"创建exploration_engine实例失败: {e}")
    _exploration_engine = None
