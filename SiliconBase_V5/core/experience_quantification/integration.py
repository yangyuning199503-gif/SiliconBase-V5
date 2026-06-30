#!/usr/bin/env python3
"""
经验注入与效果量化集成层
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
将经验注入器V3与效果量化系统无缝集成

核心功能:
1. 自动A/B测试分组
2. 自动效果追踪
3. 实时统计更新
4. 智能淘汰建议

Author: Agent-6 Experience Optimizer
Version: 1.0.0
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class ExperienceInjectorWithQuantification:
    """
    带效果量化的经验注入器

    将 ExperienceInjectorV3 与效果量化系统集成，实现：
    - 自动A/B测试分组
    - 自动追踪经验使用效果
    - 实时统计更新

    Usage:
        injector = ExperienceInjectorWithQuantification()

        # 注入经验（自动处理A/B分组）
        result = injector.inject_with_tracking(
            task="编写Python函数",
            base_prompt="你是一个Python专家...",
            context={"task_type": "code"}
        )

        # result.use_experience 指示是否使用经验注入
        # result.task_id 用于后续追踪

        # 任务完成后记录结果
        injector.record_outcome(
            task_id=result.task_id,
            success=True,
            execution_time_ms=5000
        )
    """

    def __init__(
        self,
        enable_ab_test: bool = True,
        enable_tracking: bool = True,
        ab_test_ratio: float = 0.5
    ):
        """
        初始化集成注入器

        Args:
            enable_ab_test: 是否启用A/B测试
            enable_tracking: 是否启用效果追踪
            ab_test_ratio: A/B测试中A组比例
        """
        self.enable_ab_test = enable_ab_test
        self.enable_tracking = enable_tracking

        # 延迟导入避免循环依赖
        self._injector_v3 = None
        self._ab_framework = None
        self._effectiveness_tracker = None
        self._purge_engine = None

        self._ab_test_ratio = ab_test_ratio

        logger.info(f"[ExperienceInjectorWithQuantification] 初始化完成 "
                   f"(ab_test={enable_ab_test}, tracking={enable_tracking})")

    @property
    def injector_v3(self):
        """获取V3注入器实例"""
        if self._injector_v3 is None:
            from core.evolution.experience_injector import get_experience_injector_v3
            self._injector_v3 = get_experience_injector_v3(enable_tracking=False)
        return self._injector_v3

    @property
    def ab_framework(self):
        """获取A/B测试框架实例"""
        if self._ab_framework is None:
            from .ab_test_framework import get_ab_test_framework
            self._ab_framework = get_ab_test_framework()
        return self._ab_framework

    @property
    def effectiveness_tracker(self):
        """获取效果追踪器实例"""
        if self._effectiveness_tracker is None:
            from .experience_effectiveness_tracker import get_effectiveness_tracker
            self._effectiveness_tracker = get_effectiveness_tracker()
        return self._effectiveness_tracker

    @property
    def purge_engine(self):
        """获取淘汰引擎实例"""
        if self._purge_engine is None:
            from .auto_purge_engine import get_auto_purge_engine
            self._purge_engine = get_auto_purge_engine(dry_run=True)
        return self._purge_engine

    async def inject_with_tracking(
        self,
        task: str,
        base_prompt: str,
        context: dict[str, Any] | None = None,
        user_id: str = "default",
        force_use_experience: bool | None = None
    ) -> 'InjectionResult':
        """
        注入经验并启用追踪

        Args:
            task: 任务描述
            base_prompt: 基础提示词
            context: 上下文信息
            user_id: 用户ID
            force_use_experience: 强制指定是否使用经验（覆盖A/B测试）

        Returns:
            InjectionResult 包含注入结果和追踪信息
        """
        task_type = context.get('task_type', 'general') if context else 'general'

        # 1. A/B测试分组
        if force_use_experience is not None:
            use_experience = force_use_experience
            task_id = f"forced_{int(time.time() * 1000)}"
        elif self.enable_ab_test:
            from .ab_test_framework import ABTestGroup
            group, task_id = self.ab_framework.assign_group(task, task_type, user_id, context)
            use_experience = (group == ABTestGroup.TREATMENT)
        else:
            use_experience = True
            task_id = f"no_ab_{int(time.time() * 1000)}"

        # 2. 执行注入
        if use_experience:
            enhanced_prompt, tracking_ids = await self.injector_v3.inject(
                task=task,
                base_prompt=base_prompt,
                context=context,
                user_id=user_id
            )

            # 3. 记录经验使用
            if self.enable_tracking and tracking_ids:
                self.effectiveness_tracker.track_batch_usage(
                    experience_ids=tracking_ids,
                    task_id=task_id,
                    task_type=task_type,
                    user_id=user_id
                )
        else:
            # B组：不使用经验注入
            enhanced_prompt = base_prompt + "\n\n【经验库】本次任务不使用历史经验（A/B测试对照组）。"
            tracking_ids = []

        # 4. 记录任务开始
        if self.enable_ab_test:
            self.ab_framework.record_start(task_id)

        return InjectionResult(
            task_id=task_id,
            use_experience=use_experience,
            enhanced_prompt=enhanced_prompt,
            experience_ids=tracking_ids,
            task_type=task_type
        )

    def record_outcome(
        self,
        task_id: str,
        success: bool,
        execution_time_ms: int | None = None,
        api_calls_count: int | None = None,
        user_satisfaction: int | None = None,
        user_feedback: str | None = None
    ):
        """
        记录任务执行结果

        Args:
            task_id: 任务ID（来自 inject_with_tracking 返回结果）
            success: 是否成功
            execution_time_ms: 执行耗时
            api_calls_count: API调用次数
            user_satisfaction: 用户满意度（1-10）
            user_feedback: 用户反馈文本
        """
        # 1. 更新A/B测试记录
        if self.enable_ab_test and task_id.startswith("forced_") is False:
            self.ab_framework.record_outcome(
                task_id=task_id,
                success=success,
                execution_time_ms=execution_time_ms,
                api_calls_count=api_calls_count,
                user_satisfaction=user_satisfaction,
                user_feedback=user_feedback
            )

        # 2. 更新效果追踪
        if self.enable_tracking:
            self.effectiveness_tracker.track_outcome(
                task_id=task_id,
                success=success,
                execution_time_ms=execution_time_ms,
                satisfaction=user_satisfaction
            )

        logger.debug(f"[ExperienceInjectorWithQuantification] 记录任务 {task_id[:8]} 结果: success={success}")

    def get_injection_decision(
        self,
        task: str,
        task_type: str = "general",
        user_id: str = "default"
    ) -> tuple[bool, str]:
        """
        仅获取是否使用经验的决策（不执行注入）

        Returns:
            (use_experience, task_id)
        """
        if not self.enable_ab_test:
            return True, f"no_ab_{int(time.time() * 1000)}"

        from .ab_test_framework import ABTestGroup
        group, task_id = self.ab_framework.assign_group(task, task_type, user_id)
        return group == ABTestGroup.TREATMENT, task_id

    async def get_quantification_report(self) -> dict[str, Any]:
        """获取完整量化报告"""
        report: dict[str, Any] = {
            "generated_at": time.time(),
            "ab_test_enabled": self.enable_ab_test,
            "tracking_enabled": self.enable_tracking
        }

        # A/B测试报告
        if self.enable_ab_test:
            report["ab_test"] = self.ab_framework.get_comparison_report()

        # 效果追踪统计
        if self.enable_tracking:
            report["effectiveness"] = {
                "global_stats": self.effectiveness_tracker.get_global_stats(),
                "top_experiences": self.effectiveness_tracker.get_effectiveness_leaderboard(limit=10)
            }

        # 淘汰建议
        candidates = await self.purge_engine.scan_candidates()
        report["purge_candidates"] = {
            "count": len(candidates),
            "high_priority": len([c for c in candidates if c.priority >= 4])
        }

        return report


class InjectionResult:
    """注入结果"""

    def __init__(
        self,
        task_id: str,
        use_experience: bool,
        enhanced_prompt: str,
        experience_ids: list[str],
        task_type: str
    ):
        self.task_id = task_id
        self.use_experience = use_experience
        self.enhanced_prompt = enhanced_prompt
        self.experience_ids = experience_ids
        self.task_type = task_type

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "use_experience": self.use_experience,
            "experience_count": len(self.experience_ids),
            "experience_ids": self.experience_ids,
            "task_type": self.task_type
        }


# ═══════════════════════════════════════════════════════════════════
# 便捷函数和全局实例
# ═══════════════════════════════════════════════════════════════════

_integrated_injector: ExperienceInjectorWithQuantification | None = None


def get_integrated_injector(
    enable_ab_test: bool = True,
    enable_tracking: bool = True,
    refresh: bool = False
) -> ExperienceInjectorWithQuantification:
    """获取集成注入器全局实例"""
    global _integrated_injector
    if _integrated_injector is None or refresh:
        _integrated_injector = ExperienceInjectorWithQuantification(
            enable_ab_test=enable_ab_test,
            enable_tracking=enable_tracking
        )
    return _integrated_injector


async def inject_experience_quantified(
    task: str,
    base_prompt: str,
    context: dict[str, Any] | None = None,
    user_id: str = "default"
) -> InjectionResult:
    """
    便捷函数：执行带量化的经验注入

    自动处理A/B分组和效果追踪
    """
    injector = get_integrated_injector()
    return await injector.inject_with_tracking(task, base_prompt, context, user_id)


def record_task_outcome(
    task_id: str,
    success: bool,
    execution_time_ms: int | None = None,
    user_satisfaction: int | None = None
):
    """
    便捷函数：记录任务结果

    更新A/B测试和效果追踪数据
    """
    injector = get_integrated_injector()
    injector.record_outcome(
        task_id=task_id,
        success=success,
        execution_time_ms=execution_time_ms,
        user_satisfaction=user_satisfaction
    )
