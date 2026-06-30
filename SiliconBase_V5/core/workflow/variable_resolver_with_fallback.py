#!/usr/bin/env python3
"""
变量解析统一接口（V1.0 + V1.1 增强层）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

三维度集成策略：
- AI维度: 自动识别路径类型，智能解析
- 用户维度: 零配置，自动降级
- 项目维度: 100%向后兼容

使用场景:
    # 工作流变量解析
    value = resolve_variable("step.items[0].name", execution_context)

    # 支持复杂路径
    values = resolve_variable("step.items[*].status", execution_context)
"""

from typing import Any


# 延迟导入
def _get_logger():
    try:
        from core.logger import logger
        return logger
    except ImportError:
        import logging
        return logging.getLogger('variable_resolver_fallback')


# 尝试导入增强模块
try:
    from .variable_resolver_enhanced import VariableResolverEnhanced
    _ENHANCED_AVAILABLE = True
except ImportError:
    _ENHANCED_AVAILABLE = False


def resolve_variable(path: str, data: dict[str, Any]) -> Any:
    """
    统一变量解析接口

    【三维度设计】
    1. AI维度: 自动检测路径类型（简单/数组/切片/通配符）
    2. 用户维度: 零配置，失败自动降级
    3. 项目维度: API 完全兼容原有实现

    Args:
        path: 变量路径
            - 简单: "step.result"
            - 数组: "step.items[0].name"
            - 切片: "step.items[1:3]"
            - 通配: "step.items[*].status"
        data: 数据源字典

    Returns:
        解析后的值，失败返回 None
    """
    logger = _get_logger()

    # 空保护
    if not path:
        logger.warning("[VariableResolver] 路径为空")
        return None

    if not data:
        logger.warning("[VariableResolver] 数据源为空")
        return None

    # 检测是否为复杂路径（包含数组访问语法）
    is_complex_path = '[' in path or ']' in path

    # 【AI维度】复杂路径使用 V1.1 增强
    if is_complex_path and _ENHANCED_AVAILABLE:
        try:
            resolver = VariableResolverEnhanced()
            result = resolver.resolve(path, data)

            if result.success:
                logger.debug(
                    f"[VariableResolver] V1.1 解析成功 "
                    f"(path={path}, type={result.path_type.value})"
                )
                return result.value
            else:
                logger.debug(f"[VariableResolver] V1.1 失败: {result.error}")

        except Exception as e:
            logger.debug(f"[VariableResolver] V1.1 异常，降级: {e}")

    # 【项目维度】V1.0 基础解析（完全兼容原有实现）
    return _resolve_simple(path, data)


def _resolve_simple(path: str, data: dict[str, Any]) -> Any:
    """
    V1.0 基础解析（点分隔路径）

    与原有实现完全一致，保证兼容性。
    """
    parts = path.split('.')
    value = data

    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None

        if value is None:
            return None

    return value


def resolve_variable_safe(path: str, data: dict[str, Any], default: Any = None) -> Any:
    """
    安全解析变量（带默认值）

    Args:
        path: 变量路径
        data: 数据源
        default: 失败时的默认值

    Returns:
        解析后的值或默认值
    """
    result = resolve_variable(path, data)
    return result if result is not None else default


__all__ = [
    'resolve_variable',
    'resolve_variable_safe',
]
