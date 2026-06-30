#!/usr/bin/env python3
"""
条件评估统一接口（V1.0 + V1.1 增强层）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

三维度集成策略：
- AI维度: 支持复杂条件表达式（比较、逻辑、in操作）
- 用户维度: 自动识别条件复杂度，零配置
- 项目维度: 100%向后兼容，安全沙箱

使用场景:
    # 工作流条件分支
    if evaluate_condition("status == 'success' and count > 5", context):
        go_to_next_step()

    # 复杂条件
    if evaluate_condition("user_type in ['admin', 'vip']", context):
        enable_advanced_features()
"""

from typing import Any


# 延迟导入
def _get_logger():
    try:
        from core.logger import logger
        return logger
    except ImportError:
        import logging
        return logging.getLogger('condition_evaluator_fallback')


# 尝试导入增强模块
try:
    from .condition_evaluator_enhanced import SafeConditionEvaluator
    _ENHANCED_AVAILABLE = True
except ImportError:
    _ENHANCED_AVAILABLE = False


def evaluate_condition(expression: str, context: dict[str, Any]) -> bool:
    """
    统一条件评估接口

    【三维度设计】
    1. AI维度: 自动检测条件复杂度，复杂表达式使用 AST 解析
    2. 用户维度: 零配置，失败自动降级到简单相等
    3. 项目维度: API 完全兼容原有实现

    Args:
        expression: 条件表达式
            - 简单: "status == 'success'"
            - 复杂: "status == 'success' and count > 5"
            - 包含: "user_type in ['admin', 'vip']"
        context: 变量上下文

    Returns:
        bool: 评估结果，失败返回 False
    """
    logger = _get_logger()

    # 空保护
    if not expression:
        logger.warning("[ConditionEvaluator] 表达式为空")
        return False

    if not context:
        logger.debug("[ConditionEvaluator] 上下文为空")

    # 检测是否为复杂表达式
    is_complex = any(op in expression for op in [
        'and', 'or', 'not', 'in', '>', '<', '>=', '<=', '!=',
        '+', '-', '*', '/'
    ])

    # 【AI维度】复杂表达式使用 V1.1 增强
    if is_complex and _ENHANCED_AVAILABLE:
        try:
            evaluator = SafeConditionEvaluator()
            result = evaluator.evaluate(expression, context)

            if result.success:
                logger.debug(
                    f"[ConditionEvaluator] V1.1 评估成功 "
                    f"(type={result.condition_type.value}, value={result.value})"
                )
                return result.value
            else:
                logger.debug(f"[ConditionEvaluator] V1.1 失败: {result.error}")

        except Exception as e:
            logger.debug(f"[ConditionEvaluator] V1.1 异常，降级: {e}")

    # 【项目维度】V1.0 基础评估（完全兼容）
    return _evaluate_simple(expression, context)


def _evaluate_simple(expression: str, context: dict[str, Any]) -> bool:
    """
    V1.0 基础条件评估（简单相等）

    与原有实现完全一致，保证兼容性。
    """
    expression = expression.strip()

    # 尝试解析为 "key == value" 格式
    if '==' in expression:
        parts = expression.split('==', 1)
        if len(parts) == 2:
            key = parts[0].strip()
            expected_value = parts[1].strip().strip("'\"")

            actual_value = context.get(key)
            return str(actual_value) == expected_value

    # 直接作为键名取值
    value = context.get(expression)
    return bool(value)


def evaluate_condition_safe(expression: str, context: dict[str, Any], default: bool = False) -> bool:
    """
    安全评估条件（带默认值）

    Args:
        expression: 条件表达式
        context: 变量上下文
        default: 失败时的默认值

    Returns:
        bool: 评估结果或默认值
    """
    try:
        return evaluate_condition(expression, context)
    except Exception:
        return default


__all__ = [
    'evaluate_condition',
    'evaluate_condition_safe',
]
