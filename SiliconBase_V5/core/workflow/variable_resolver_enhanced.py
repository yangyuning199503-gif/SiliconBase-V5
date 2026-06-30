#!/usr/bin/env python3
"""
变量解析器增强（V1.1）- JSONPath 支持
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

三维度设计：
1. AI维度: 支持复杂路径访问（数组索引、通配符）
2. 用户维度: 自动识别路径类型，零配置
3. 项目维度: 100%向后兼容，降级到点分隔

支持的语法：
- 点分隔: "step.result.data" (V1.0)
- 数组索引: "step.items[0].name"
- 多索引: "step.items[0,2].value"
- 切片: "step.items[1:3].name"
- 通配符: "step.items[*].name"
- 过滤: "step.items[?status=='active'].name"
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


# 延迟导入
def _get_logger():
    try:
        from core.logger import logger
        return logger
    except ImportError:
        import logging
        return logging.getLogger('variable_resolver')


class PathType(Enum):
    """路径类型"""
    SIMPLE_DOT = "simple_dot"       # 简单点分隔
    ARRAY_INDEX = "array_index"     # 数组索引
    SLICE = "slice"                 # 切片
    WILDCARD = "wildcard"           # 通配符
    FILTER = "filter"               # 过滤表达式


@dataclass
class ResolveResult:
    """解析结果"""
    value: Any
    path_type: PathType
    success: bool
    error: str | None = None


class VariableResolverEnhanced:
    """
    增强变量解析器（V1.1）

    【单例模式】全局唯一实例
    【线程安全】无状态，可并发
    """

    _instance: Optional['VariableResolverEnhanced'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True

        # 正则表达式模式
        self._patterns = {
            'array_index': re.compile(r'^(\w+)\[(\d+)\]$'),
            'multi_index': re.compile(r'^(\w+)\[(\d+(?:,\d+)*)\]$'),
            'slice': re.compile(r'^(\w+)\[(\d*):(\d*)\]$'),
            'wildcard': re.compile(r'^(\w+)\[\*\]$'),
            'filter': re.compile(r"^(\w+)\[\?(.+?)\]$"),
        }

        _get_logger().info("[VariableResolverEnhanced] V1.1 初始化完成")

    def resolve(self, path: str, data: dict[str, Any]) -> ResolveResult:
        """
        解析变量路径

        【规则遵守】
        - 空保护: path/data 为空时返回错误结果
        - 自动降级: 复杂路径失败时降级到简单路径

        Args:
            path: 变量路径（如 "step.result" 或 "step.items[0].name"）
            data: 数据源字典

        Returns:
            ResolveResult: 包含值、路径类型、成功状态
        """
        logger = _get_logger()

        # 空保护
        if not path:
            return ResolveResult(
                value=None,
                path_type=PathType.SIMPLE_DOT,
                success=False,
                error="路径为空"
            )

        if not data or not isinstance(data, dict):
            return ResolveResult(
                value=None,
                path_type=PathType.SIMPLE_DOT,
                success=False,
                error="数据源为空或非字典"
            )

        try:
            # 检测路径类型
            path_type = self._detect_path_type(path)

            # 根据类型解析
            if path_type == PathType.SIMPLE_DOT:
                value = self._resolve_simple(path, data)
            elif path_type == PathType.ARRAY_INDEX:
                value = self._resolve_array_index(path, data)
            elif path_type == PathType.SLICE:
                value = self._resolve_slice(path, data)
            elif path_type == PathType.WILDCARD:
                value = self._resolve_wildcard(path, data)
            elif path_type == PathType.FILTER:
                value = self._resolve_filter(path, data)
            else:
                value = None

            return ResolveResult(
                value=value,
                path_type=path_type,
                success=value is not None
            )

        except Exception as e:
            logger.warning(f"[VariableResolver] 解析失败 '{path}': {e}")
            # 降级到简单路径
            try:
                value = self._resolve_simple(path, data)
                return ResolveResult(
                    value=value,
                    path_type=PathType.SIMPLE_DOT,
                    success=value is not None,
                    error=f"增强解析失败，降级到简单路径: {e}"
                )
            except Exception:
                return ResolveResult(
                    value=None,
                    path_type=PathType.SIMPLE_DOT,
                    success=False,
                    error=str(e)
                )

    def _detect_path_type(self, path: str) -> PathType:
        """检测路径类型"""
        # 检查是否包含数组访问语法
        if '[' not in path:
            return PathType.SIMPLE_DOT

        # 检查切片
        if re.search(r'\[\d*:\d*\]', path):
            return PathType.SLICE

        # 检查通配符
        if '[*]' in path:
            return PathType.WILDCARD

        # 检查过滤
        if '[?' in path:
            return PathType.FILTER

        # 检查多索引
        if re.search(r'\[\d+(?:,\d+)+\]', path):
            return PathType.ARRAY_INDEX

        # 简单数组索引
        if re.search(r'\[\d+\]', path):
            return PathType.ARRAY_INDEX

        return PathType.SIMPLE_DOT

    def _resolve_simple(self, path: str, data: dict[str, Any]) -> Any:
        """解析简单点分隔路径"""
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

    def _resolve_array_index(self, path: str, data: dict[str, Any]) -> Any:
        """解析数组索引路径"""
        # 示例: "items[0].name" 或 "items[0,2]"
        pattern = r'(\w+)\[(\d+(?:,\d+)*)\](?:\.(.*))?'
        match = re.match(pattern, path)

        if not match:
            return None

        field = match.group(1)
        indices_str = match.group(2)
        rest_path = match.group(3)

        # 获取数组
        array = data.get(field) if isinstance(data, dict) else None
        if not isinstance(array, list):
            return None

        # 解析索引
        indices = [int(x.strip()) for x in indices_str.split(',')]

        # 获取指定元素
        results = []
        for idx in indices:
            if 0 <= idx < len(array):
                item = array[idx]
                if rest_path:
                    # 递归解析剩余路径
                    item = self._resolve_simple(rest_path, item) if isinstance(item, dict) else None
                results.append(item)

        return results[0] if len(results) == 1 else results

    def _resolve_slice(self, path: str, data: dict[str, Any]) -> Any:
        """解析切片路径"""
        # 示例: "items[1:3].name"
        pattern = r'(\w+)\[(\d*):(\d*)\](?:\.(.*))?'
        match = re.match(pattern, path)

        if not match:
            return None

        field = match.group(1)
        start = int(match.group(2)) if match.group(2) else 0
        end = int(match.group(3)) if match.group(3) else None
        rest_path = match.group(4)

        # 获取数组
        array = data.get(field) if isinstance(data, dict) else None
        if not isinstance(array, list):
            return None

        # 切片
        sliced = array[start:end]

        # 递归解析剩余路径
        if rest_path:
            return [self._resolve_simple(rest_path, item) if isinstance(item, dict) else item
                    for item in sliced]

        return sliced

    def _resolve_wildcard(self, path: str, data: dict[str, Any]) -> Any:
        """解析通配符路径"""
        # 示例: "items[*].name"
        pattern = r'(\w+)\[\*\](?:\.(.*))?'
        match = re.match(pattern, path)

        if not match:
            return None

        field = match.group(1)
        rest_path = match.group(2)

        # 获取数组
        array = data.get(field) if isinstance(data, dict) else None
        if not isinstance(array, list):
            return None

        # 应用到所有元素
        if rest_path:
            return [self._resolve_simple(rest_path, item) if isinstance(item, dict) else item
                    for item in array]

        return array

    def _resolve_filter(self, path: str, data: dict[str, Any]) -> Any:
        """解析过滤路径（简化版）"""
        # 示例: "items[?status=='active'].name"
        pattern = r"(\w+)\[\?(.+?)\](?:\.(.*))?"
        match = re.match(pattern, path)

        if not match:
            return None

        field = match.group(1)
        filter_expr = match.group(2)
        rest_path = match.group(3)

        # 获取数组
        array = data.get(field) if isinstance(data, dict) else None
        if not isinstance(array, list):
            return None

        # 简单过滤解析（支持 == 和 !=）
        # 示例: status=='active' 或 type!='error'
        filtered = []

        if '==' in filter_expr:
            key, val = filter_expr.split('==', 1)
            key = key.strip()
            val = val.strip().strip("'\"")
            filtered = [item for item in array
                       if isinstance(item, dict) and item.get(key) == val]
        elif '!=' in filter_expr:
            key, val = filter_expr.split('!=', 1)
            key = key.strip()
            val = val.strip().strip("'\"")
            filtered = [item for item in array
                       if isinstance(item, dict) and item.get(key) != val]

        # 递归解析剩余路径
        if rest_path:
            return [self._resolve_simple(rest_path, item) if isinstance(item, dict) else item
                    for item in filtered]

        return filtered


# =============================================================================
# 便捷函数
# =============================================================================

_resolver: VariableResolverEnhanced | None = None


def get_resolver() -> VariableResolverEnhanced:
    """获取解析器单例"""
    global _resolver
    if _resolver is None:
        _resolver = VariableResolverEnhanced()
    return _resolver


def resolve_variable(path: str, data: dict[str, Any]) -> Any:
    """
    解析变量路径便捷函数

    【规则遵守】
    - 返回值: Any（可能为 None）
    - 降级: 增强失败自动降级到简单路径

    Args:
        path: 变量路径
        data: 数据源

    Returns:
        解析后的值，失败返回 None
    """
    resolver = get_resolver()
    result = resolver.resolve(path, data)
    return result.value if result.success else None


def resolve_variable_safe(path: str, data: dict[str, Any], default: Any = None) -> Any:
    """
    安全解析变量路径

    Args:
        path: 变量路径
        data: 数据源
        default: 失败时的默认值

    Returns:
        解析后的值，失败返回 default
    """
    resolver = get_resolver()
    result = resolver.resolve(path, data)
    return result.value if result.success else default


__all__ = [
    'VariableResolverEnhanced',
    'ResolveResult',
    'PathType',
    'resolve_variable',
    'resolve_variable_safe',
    'get_resolver',
]
