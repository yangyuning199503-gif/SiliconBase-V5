#!/usr/bin/env python3
"""
TokenBudgetManager 集成模块 - SiliconBase V5 Week 2
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
功能：
  ✓ 将TokenBudgetManager集成到AgentLoop的上下文构建流程
  ✓ 支持16项信息分类的预算分配
  ✓ 零静默失败原则（所有异常明确记录）
  ✓ 性能监控和统计

集成点：
  1. 上下文构建时应用Token预算
  2. 16项信息预算分配
  3. 错误处理和fallback机制
"""

import time
from dataclasses import dataclass, field
from typing import Any

from core.logger import logger

# 导入TokenBudgetManager（实际在 core/cost/ 目录）
try:
    from core.cost.token_budget_manager import TokenBudgetManager, TokenBudgetResult, TokenCalculator
    TOKEN_BUDGET_AVAILABLE = True
except ImportError as e:
    logger.error(f"[TokenBudgetIntegration] TokenBudgetManager导入失败: {e}")
    TOKEN_BUDGET_AVAILABLE = False
    TokenBudgetManager = None
    TokenBudgetResult = None
    TokenCalculator = None


# =============================================================================
# 16项信息预算分类映射
# =============================================================================

BUDGET_CATEGORIES = {
    # 常驻基底（永不截断）
    "permanent_basement": "常驻基底",

    # 基础设定类(3项)
    "system_prompt": "基础设定",
    "three_views": "基础设定",
    "life_status": "基础设定",

    # 感知输入类(2项)
    "perception_context": "感知输入",
    "vision_analysis": "感知输入",

    # 记忆经验类(4项)
    "memory_l1_l5": "记忆经验",
    "reflection": "记忆经验",
    "experience_injection": "记忆经验",
    "execution_history": "记忆经验",

    # 认知辅助类(4项)
    "world_model": "认知辅助",
    "exploration": "认知辅助",
    "prompt_layer": "认知辅助",
    "reasoning_framework": "认知辅助",

    # 任务管理类(1项)
    "phase_anchor": "任务管理",

    # 个性化类(1项)
    "user_preference": "个性化",

    # 弱连接类(1项)
    "weak_connection": "弱连接",
}

# 类别优先级（用于预算不足时的取舍）
CATEGORY_PRIORITY = {
    "基础设定": 1,    # 最高优先级
    "感知输入": 2,
    "任务管理": 3,
    "记忆经验": 4,
    "认知辅助": 5,
    "个性化": 6,
    "弱连接": 7,      # 最低优先级
}


@dataclass
class BudgetAllocationReport:
    """预算分配报告"""
    category: str
    original_length: int
    budget: int
    truncated_length: int
    was_truncated: bool
    processing_time_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "original_length": self.original_length,
            "budget": self.budget,
            "truncated_length": self.truncated_length,
            "was_truncated": self.was_truncated,
            "processing_time_ms": self.processing_time_ms
        }


@dataclass
class ContextBudgetReport:
    """上下文预算整体报告"""
    total_original_tokens: int = 0
    total_truncated_tokens: int = 0
    total_budget: int = 0
    allocations: list[BudgetAllocationReport] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    processing_time_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_original_tokens": self.total_original_tokens,
            "total_truncated_tokens": self.total_truncated_tokens,
            "total_budget": self.total_budget,
            "allocations": [a.to_dict() for a in self.allocations],
            "errors": self.errors,
            "processing_time_ms": self.processing_time_ms
        }


class TokenBudgetIntegration:
    """
    Token预算集成器

    职责：
    1. 管理TokenBudgetManager的生命周期
    2. 为AgentLoop提供预算控制接口
    3. 收集统计信息
    """

    _instance = None
    _lock = False

    def __init__(self):
        """初始化（请使用get_instance()）"""
        if not TokenBudgetIntegration._lock:
            raise RuntimeError("请使用TokenBudgetIntegration.get_instance()")

        self._budget_manager: TokenBudgetManager | None = None
        self._enabled = TOKEN_BUDGET_AVAILABLE
        self._stats = {
            "total_allocations": 0,
            "total_truncations": 0,
            "total_errors": 0,
            "total_processing_time_ms": 0
        }

        if self._enabled:
            try:
                self._budget_manager = TokenBudgetManager.get_instance()
                logger.info("[TokenBudgetIntegration] TokenBudgetManager初始化成功")
            except Exception as e:
                logger.error(f"[TokenBudgetIntegration] TokenBudgetManager初始化失败: {e}")
                self._enabled = False
                self._stats["total_errors"] += 1

    @classmethod
    def get_instance(cls) -> 'TokenBudgetIntegration':
        """获取单例实例"""
        if cls._instance is None:
            cls._lock = True
            try:
                cls._instance = cls()
            finally:
                cls._lock = False
        return cls._instance

    def is_enabled(self) -> bool:
        """检查预算控制是否启用"""
        return self._enabled and self._budget_manager is not None

    def allocate_budget(
        self,
        category_key: str,
        content: str,
        model: str = "default"
    ) -> tuple[str, BudgetAllocationReport | None]:
        """
        为指定类别的内容分配预算

        Args:
            category_key: 16项信息中的键名（如"memory_l1_l5"）
            content: 原始内容
            model: 模型名称

        Returns:
            Tuple[处理后的内容, 分配报告]

        零静默失败原则:
            - 预算管理器失败时返回原始内容
            - 所有错误记录ERROR日志
        """
        start_time = time.time()

        # 参数校验
        if content is None:
            logger.error(f"[TokenBudgetIntegration] content为None，类别: {category_key}")
            return "", None

        if not isinstance(content, str):
            try:
                content = str(content)
            except Exception as e:
                logger.error(f"[TokenBudgetIntegration] content转字符串失败: {e}")
                return "", None

        if not content:
            return "", None

        # 如果预算管理不可用，直接返回原始内容
        if not self.is_enabled():
            return content, None

        # 获取类别名称
        category = BUDGET_CATEGORIES.get(category_key, "预留")

        try:
            # 调用TokenBudgetManager计算token数（仅用于统计，不截断）
            result = self._budget_manager.allocate_budget(category, content, model)

            processing_time = (time.time() - start_time) * 1000

            # 构建报告（截断已禁用，始终返回原始内容）
            report = BudgetAllocationReport(
                category=category,
                original_length=result.original_tokens,
                budget=result.budget,
                truncated_length=result.original_tokens,
                was_truncated=False,
                processing_time_ms=processing_time
            )

            # 更新统计
            self._stats["total_allocations"] += 1
            self._stats["total_processing_time_ms"] += processing_time

            logger.debug(
                f"[TokenBudgetIntegration] {category}: {result.original_tokens} tokens "
                f"(截断已禁用)"
            )
            return content, report

        except Exception as e:
            logger.error(
                f"[TokenBudgetIntegration] 预算分配失败: {e}, "
                f"类别: {category_key}",
                exc_info=True
            )
            self._stats["total_errors"] += 1
            # 零静默失败：返回原始内容
            return content, None

    def build_context_with_budget(
        self,
        context_components: dict[str, str],
        model: str = "default"
    ) -> tuple[str, ContextBudgetReport]:
        """
        构建带预算控制的完整上下文

        Args:
            context_components: 16项信息组件字典
                键名为BUDGET_CATEGORIES中的key
                值为对应的内容字符串
            model: 模型名称

        Returns:
            Tuple[完整上下文, 预算报告]
        """
        start_time = time.time()
        report = ContextBudgetReport()

        if not self.is_enabled():
            # 预算管理不可用，简单拼接
            full_context = "\n\n".join(
                content for content in context_components.values() if content
            )
            report.errors.append("TokenBudgetManager不可用，未应用预算控制")
            return full_context, report

        processed_parts = []
        total_budget = 0

        # 按优先级排序组件
        sorted_components = sorted(
            context_components.items(),
            key=lambda x: CATEGORY_PRIORITY.get(
                BUDGET_CATEGORIES.get(x[0], "预留"), 99
            )
        )

        for key, content in sorted_components:
            if not content:
                continue

            try:
                processed_content, allocation_report = self.allocate_budget(
                    key, content, model
                )

                if processed_content:
                    processed_parts.append(processed_content)

                if allocation_report:
                    report.allocations.append(allocation_report)
                    report.total_original_tokens += allocation_report.original_length
                    report.total_truncated_tokens += allocation_report.truncated_length
                    total_budget += allocation_report.budget

            except Exception as e:
                error_msg = f"处理组件 {key} 失败: {e}"
                logger.error(f"[TokenBudgetIntegration] {error_msg}")
                report.errors.append(error_msg)
                # 零静默失败：使用原始内容
                processed_parts.append(content)

        # 组装最终上下文
        full_context = "\n\n".join(processed_parts)

        # 验证总Token数
        try:
            total_tokens = self._budget_manager.calculator.count_tokens(
                full_context, model
            )
            logger.info(f"[TokenBudgetIntegration] 总上下文Token数: {total_tokens}")
        except Exception as e:
            logger.error(f"[TokenBudgetIntegration] 总Token数计算失败: {e}")

        report.total_budget = total_budget
        report.processing_time_ms = (time.time() - start_time) * 1000

        return full_context, report

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        return self._stats.copy()

    def reset_stats(self) -> None:
        """重置统计信息"""
        self._stats = {
            "total_allocations": 0,
            "total_truncations": 0,
            "total_errors": 0,
            "total_processing_time_ms": 0
        }
        logger.info("[TokenBudgetIntegration] 统计信息已重置")


# =============================================================================
# 便捷函数
# =============================================================================

def get_token_budget_integration() -> TokenBudgetIntegration:
    """获取TokenBudgetIntegration单例"""
    return TokenBudgetIntegration.get_instance()


def allocate_component_budget(
    component_key: str,
    content: str,
    model: str = "default"
) -> tuple[str, BudgetAllocationReport | None]:
    """
    便捷函数：为单个组件分配预算

    Args:
        component_key: 组件键名
        content: 内容
        model: 模型名称

    Returns:
        Tuple[处理后的内容, 分配报告]
    """
    integration = get_token_budget_integration()
    return integration.allocate_budget(component_key, content, model)


def build_context_with_budget(
    context_components: dict[str, str],
    model: str = "default"
) -> tuple[str, ContextBudgetReport]:
    """
    便捷函数：构建带预算控制的上下文

    Args:
        context_components: 上下文组件字典
        model: 模型名称

    Returns:
        Tuple[完整上下文, 预算报告]
    """
    integration = get_token_budget_integration()
    return integration.build_context_with_budget(context_components, model)


# =============================================================================
# AgentLoop专用集成函数
# =============================================================================

def prepare_context_components(
    smart_context: dict[str, str],
    perception_context: str,
    three_views_prompt: str,
    memory_context: str,
    exploration_enhancement: str,
    layer_prompt: str,
    reflection_context: str,
    vision_description: str,
    life_state_context: str,
    user_preference_context: str,
    weak_connection_context: str,
    world_model_section: str,
    phase_context: str,
    execution_history: list[dict],
    **kwargs
) -> dict[str, str]:
    """
    准备16项信息组件字典

    这个函数将AgentLoop中的各种上下文内容映射到16项分类中

    Args:
        smart_context: 智能提示词引擎生成的上下文
        perception_context: 感知上下文
        three_views_prompt: 三观提示词
        memory_context: 记忆上下文
        exploration_enhancement: 探索增强
        layer_prompt: 层级提示词
        reflection_context: 反思上下文
        vision_description: 视觉描述
        life_state_context: 生命体征上下文
        user_preference_context: 用户偏好上下文
        weak_connection_context: 弱连接上下文
        world_model_section: 世界模型预测
        phase_context: 阶段锚点上下文
        execution_history: 执行历史
        **kwargs: 其他可选组件

    Returns:
        16项信息组件字典
    """
    components = {}

    # 基础设定类(3项)
    components["system_prompt"] = smart_context.get("system_prompt", "")
    components["three_views"] = three_views_prompt
    components["life_status"] = life_state_context

    # 感知输入类(2项)
    components["perception_context"] = perception_context
    components["vision_analysis"] = vision_description

    # 记忆经验类(4项)
    components["memory_l1_l5"] = memory_context
    components["reflection"] = reflection_context
    components["experience_injection"] = kwargs.get("experience_context", "")

    # 执行历史摘要
    if execution_history:
        from core.prompt.context_builder import context_compressor
        _max_hist_len = 20
        _hist_slice = execution_history[-_max_hist_len:] if len(execution_history) > _max_hist_len else execution_history
        exec_summary = context_compressor._summarize_execution(_hist_slice)
        components["execution_history"] = f"[执行摘要] {exec_summary}"
    else:
        components["execution_history"] = ""

    # 认知辅助类(4项)
    components["world_model"] = world_model_section
    components["exploration"] = exploration_enhancement
    components["prompt_layer"] = layer_prompt
    components["reasoning_framework"] = smart_context.get("reasoning_framework", "")

    # 任务管理类(1项)
    components["phase_anchor"] = phase_context

    # 个性化类(1项)
    components["user_preference"] = user_preference_context

    # 弱连接类(1项)
    components["weak_connection"] = weak_connection_context

    return components


# =============================================================================
# 测试代码
# =============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("TokenBudgetIntegration 测试")
    print("=" * 60)

    # 获取集成器实例
    integration = get_token_budget_integration()

    print(f"\n1. TokenBudgetManager可用: {integration.is_enabled()}")

    # 测试单组件预算分配
    print("\n2. 测试单组件预算分配:")
    test_content = "【记忆上下文】\n" + "这是一条测试记忆。\n" * 50
    processed, report = allocate_component_budget("memory_l1_l5", test_content)
    if report:
        print(f"   类别: {report.category}")
        print(f"   原始Token: {report.original_length}")
        print(f"   预算: {report.budget}")
        print(f"   截断后Token: {report.truncated_length}")
        print(f"   是否截断: {report.was_truncated}")
        print(f"   处理时间: {report.processing_time_ms:.2f}ms")

    # 测试完整上下文构建
    print("\n3. 测试完整上下文构建:")
    components = {
        "system_prompt": "你是SiliconBase V5智能助手。",
        "three_views": "【三观提示词】诚实、尊重、安全",
        "memory_l1_l5": "【记忆上下文】\n" + "L1短期记忆...\n" * 20,
        "reflection": "【反思结果】之前的操作很成功。",
        "reasoning_framework": "【推理框架】请按步骤思考...",
    }

    full_context, full_report = build_context_with_budget(components)
    print(f"   总原始Token: {full_report.total_original_tokens}")
    print(f"   总截断Token: {full_report.total_truncated_tokens}")
    print(f"   总预算: {full_report.total_budget}")
    print(f"   分配数: {len(full_report.allocations)}")
    print(f"   错误数: {len(full_report.errors)}")
    print(f"   总处理时间: {full_report.processing_time_ms:.2f}ms")

    # 显示统计
    print("\n4. 统计信息:")
    stats = integration.get_stats()
    print(f"   总分配次数: {stats['total_allocations']}")
    print(f"   总截断次数: {stats['total_truncations']}")
    print(f"   总错误次数: {stats['total_errors']}")

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
