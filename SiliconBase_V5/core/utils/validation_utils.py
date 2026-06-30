#!/usr/bin/env python3
"""
SiliconBase V5 — 返回值断言与验证工具

【核心原则】
- 禁止静默失败：任何无效返回必须抛出明确异常
- 无效返回 = 明确报错 + ERROR 日志
- 不允许 quietly return None / 空集合

使用场景：
- AI/LLM 调用后校验响应非空
- ModelBus 调用后校验返回结果
- 记忆查询后校验返回值
- 配置文件读取后校验字段存在
"""

from typing import Any


def assert_not_none(
    value: Any,
    message: str,
    logger=None,
    exc_cls=ValueError
) -> Any:
    """强制断言值非 None，否则抛异常并打 ERROR 日志

    Args:
        value: 待检查的值
        message: 断言失败时的错误消息
        logger: 可选的日志记录器，失败时输出 ERROR 日志
        exc_cls: 抛出的异常类，默认 ValueError

    Returns:
        value: 如果检查通过，原样返回

    Raises:
        exc_cls: 如果 value 为 None

    Example:
        >>> result = call_ai_model(...)
        >>> assert_not_none(result, "AI 模型返回 None", logger)
    """
    if value is None:
        if logger is not None:
            logger.error(f"[ASSERTION_FAILED] {message}")
        raise exc_cls(message)
    return value


def assert_not_empty(
    value: str | list | dict | bytes,
    message: str,
    logger=None,
    exc_cls=ValueError
) -> str | list | dict | bytes:
    """强制断言字符串/列表/字典/字节非空，否则抛异常并打 ERROR 日志

    Args:
        value: 待检查的值
        message: 断言失败时的错误消息
        logger: 可选的日志记录器，失败时输出 ERROR 日志
        exc_cls: 抛出的异常类，默认 ValueError

    Returns:
        value: 如果检查通过，原样返回

    Raises:
        exc_cls: 如果 value 为 None 或为空（长度为 0）

    Example:
        >>> content = ai_response.get("content")
        >>> assert_not_empty(content, "AI 返回空内容", logger)
    """
    if value is None or not value:
        if logger is not None:
            logger.error(f"[ASSERTION_FAILED] {message}")
        raise exc_cls(message)
    return value


def assert_isinstance(
    value: Any,
    expected_type: type,
    message: str,
    logger=None,
    exc_cls=TypeError
) -> Any:
    """强制断言值为指定类型，否则抛异常并打 ERROR 日志

    Args:
        value: 待检查的值
        expected_type: 期望的类型
        message: 断言失败时的错误消息
        logger: 可选的日志记录器
        exc_cls: 抛出的异常类，默认 TypeError

    Returns:
        value: 如果检查通过，原样返回

    Raises:
        exc_cls: 如果 value 不是 expected_type 的实例

    Example:
        >>> rule = get_hard_rule(...)
        >>> assert_isinstance(rule, dict, "规则必须是字典", logger)
    """
    if not isinstance(value, expected_type):
        actual = type(value).__name__
        expected = expected_type.__name__
        full_msg = f"{message} (实际类型: {actual}, 期望类型: {expected})"
        if logger is not None:
            logger.error(f"[ASSERTION_FAILED] {full_msg}")
        raise exc_cls(full_msg)
    return value


def assert_key_exists(
    data: dict,
    key: str,
    message: str | None = None,
    logger=None,
    exc_cls=KeyError
) -> Any:
    """强制断言字典中存在指定键，否则抛异常并打 ERROR 日志

    Args:
        data: 待检查的字典
        key: 必须存在的键
        message: 可选的自定义错误消息
        logger: 可选的日志记录器
        exc_cls: 抛出的异常类，默认 KeyError

    Returns:
        键对应的值

    Raises:
        exc_cls: 如果 key 不在 data 中

    Example:
        >>> response = {"chat_reply": "hello"}
        >>> content = assert_key_exists(response, "content", "AI 响应缺少 content 字段", logger)
    """
    if key not in data:
        msg = message or f"字典中缺少必需的键: '{key}'"
        if logger is not None:
            logger.error(f"[ASSERTION_FAILED] {msg}")
        raise exc_cls(msg)
    return data[key]


def assert_valid_index(
    seq: list | str,
    index: int,
    message: str | None = None,
    logger=None,
    exc_cls=IndexError
) -> Any:
    """强制断言索引在序列有效范围内，否则抛异常并打 ERROR 日志

    Args:
        seq: 列表或字符串
        index: 待检查的索引
        message: 可选的自定义错误消息
        logger: 可选的日志记录器
        exc_cls: 抛出的异常类，默认 IndexError

    Returns:
        索引对应的元素

    Raises:
        exc_cls: 如果索引越界
    """
    if index < 0 or index >= len(seq):
        msg = message or f"索引 {index} 超出范围 (序列长度: {len(seq)})"
        if logger is not None:
            logger.error(f"[ASSERTION_FAILED] {msg}")
        raise exc_cls(msg)
    return seq[index]


# =============================================================================
# AI/LLM 专用断言（语义更强，便于排查）
# =============================================================================

def assert_ai_response_valid(
    response: Any,
    logger=None,
    exc_cls=None
) -> Any:
    """断言 AI 响应有效（非 None、非空字符串、非空字典）

    这是 AI 调用后的首选校验函数，语义明确，日志统一。

    Args:
        response: AI 返回的原始响应
        logger: 可选的日志记录器
        exc_cls: 抛出的异常类，默认从 core.exceptions 导入 AIEmptyResponseError

    Returns:
        response: 如果检查通过，原样返回

    Raises:
        exc_cls: 如果响应无效
    """
    if exc_cls is None:
        try:
            from core.exceptions import AIEmptyResponseError
            exc_cls = AIEmptyResponseError
        except ImportError:
            exc_cls = ValueError

    if response is None:
        msg = "AI 返回 None，响应无效"
        if logger is not None:
            logger.error(f"[AI_ASSERT_FAILED] {msg}")
        raise exc_cls(msg)

    if isinstance(response, str) and not response.strip():
        msg = "AI 返回空字符串，响应无效"
        if logger is not None:
            logger.error(f"[AI_ASSERT_FAILED] {msg}")
        raise exc_cls(msg)

    if isinstance(response, (list, dict)) and not response:
        msg = f"AI 返回空 {type(response).__name__}，响应无效"
        if logger is not None:
            logger.error(f"[AI_ASSERT_FAILED] {msg}")
        raise exc_cls(msg)

    return response


def assert_model_bus_ready(
    bus: Any,
    logger=None,
    exc_cls=None
) -> Any:
    """断言 ModelBus 已初始化且非 None

    Args:
        bus: ModelBus 实例
        logger: 可选的日志记录器
        exc_cls: 抛出的异常类，默认从 core.exceptions 导入 ModelBusError

    Returns:
        bus: 如果检查通过，原样返回

    Raises:
        exc_cls: 如果 bus 为 None 或未初始化
    """
    if exc_cls is None:
        try:
            from core.exceptions import ModelBusError
            exc_cls = ModelBusError
        except ImportError:
            exc_cls = RuntimeError

    if bus is None:
        msg = "ModelBus 未初始化 (get_model_bus() 返回 None)"
        if logger is not None:
            logger.error(f"[MODEL_BUS_ASSERT_FAILED] {msg}")
        raise exc_cls(msg)

    if hasattr(bus, "_initialized") and not bus._initialized:
        msg = "ModelBus 实例存在但未完成初始化"
        if logger is not None:
            logger.error(f"[MODEL_BUS_ASSERT_FAILED] {msg}")
        raise exc_cls(msg)

    return bus
