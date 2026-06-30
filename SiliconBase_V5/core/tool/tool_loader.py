#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
工具加载器 - SiliconBase V5 插排架构  # 模块功能概述：条件加载工具的插排架构实现

支持条件加载工具，根据功能开关动态注册工具。  # 核心功能：基于功能开关的条件加载
提供优雅降级和依赖检查。  # 附加功能：降级策略和依赖管理

示例:  # 使用示例
    from core.tool.tool_loader import tool_loader  # 导入工具加载器

    # 加载所有工具  # 加载全部
    tool_loader.load_all()  # 调用加载方法

    # 条件加载（自动检查功能开关）  # 条件加载
    tool_loader.load_conditional("embedding", ["memory_search", "semantic_search"])  # 加载指定功能关联的工具
"""  # 文档字符串结束

import importlib  # 导入动态导入模块
import inspect  # 导入检查模块
from dataclasses import dataclass  # 从dataclasses导入数据类装饰器
from pathlib import Path  # 从pathlib导入Path类

from core.feature_manager import is_feature_enabled  # 导入功能管理器和检查函数
from core.logger import logger  # 从日志模块导入日志记录器
from core.tool.base_tool import BaseTool  # 从基类模块导入BaseTool
from core.tool.tool_manager import tool_manager  # 从工具管理器导入tool_manager
from core.utils.dependency_checker import DependencyStatus, dependency_checker  # 导入依赖检查器


@dataclass  # 数据类装饰器
class ToolRegistration:  # 定义工具注册信息数据类
    """工具注册信息"""
    tool_class: type[BaseTool]  # 工具类（继承自BaseTool的类）
    feature_id: str | None = None  # 关联的功能ID，用于条件加载
    dependencies: list[str] = None  # 额外依赖列表，如第三方库
    fallback_tool: type[BaseTool] | None = None  # 降级工具类（主工具不可用时使用）
    enabled: bool = True  # 是否启用


class ToolLoader:  # 定义工具加载器类
    """
    工具加载器

    根据功能开关条件加载工具，支持降级策略。
    """

    def __init__(self):  # 初始化方法
        self._registrations: dict[str, ToolRegistration] = {}  # 工具注册信息字典
        self._loaded_tools: dict[str, BaseTool] = {}  # 已加载工具字典
        self._fallback_tools: dict[str, BaseTool] = {}  # 降级工具字典
        self._tools_dir = Path(__file__).parent.parent / "tools"  # 工具目录路径

    def register(  # 注册工具的方法
            self,
            tool_class: type[BaseTool],  # 工具类
            feature_id: str | None = None,  # 关联功能ID
            dependencies: list[str] = None,  # 额外依赖
            fallback_tool: type[BaseTool] | None = None  # 降级工具类
    ):
        """
        注册工具

        Args:  # 参数说明
            tool_class: 工具类  # 继承BaseTool的类
            feature_id: 关联的功能ID  # 功能开关标识
            dependencies: 额外依赖列表  # 第三方依赖
            fallback_tool: 降级工具类（主工具不可用时使用）  # 降级方案
        """
        tool_id = tool_class.tool_id  # 获取工具ID

        self._registrations[tool_id] = ToolRegistration(  # 创建注册信息
            tool_class=tool_class,  # 工具类
            feature_id=feature_id,  # 功能ID
            dependencies=dependencies or [],  # 依赖（默认为空列表）
            fallback_tool=fallback_tool,  # 降级工具
            enabled=True  # 启用
        )

        logger.debug(f"[ToolLoader] 注册工具: {tool_id}")  # 记录调试日志

    def check_tool_available(self, tool_id: str) -> bool:  # 检查工具是否可用的方法
        """
        检查工具是否可用

        Args:  # 参数说明
            tool_id: 工具ID  # 要检查的工具

        Returns:  # 返回值
            bool: 是否可用  # True表示可用
        """
        reg = self._registrations.get(tool_id)  # 获取注册信息
        if reg is None:  # 如果未注册
            return False  # 不可用

        # 检查功能开关
        if reg.feature_id and not is_feature_enabled(reg.feature_id):  # 如果功能未启用
            return False  # 不可用

        # 检查依赖
        for dep in reg.dependencies:  # 遍历依赖
            status = dependency_checker.check_dependency(dep)  # 检查依赖状态
            if status != DependencyStatus.AVAILABLE:  # 如果依赖不可用
                return False  # 工具不可用

        return True  # 所有检查通过，可用

    def load_tool(self, tool_id: str) -> BaseTool | None:  # 加载单个工具的方法
        """
        加载单个工具

        Args:  # 参数说明
            tool_id: 工具ID  # 要加载的工具

        Returns:  # 返回值
            工具实例或None  # 成功返回实例，失败返回None
        """
        reg = self._registrations.get(tool_id)  # 获取注册信息
        if reg is None:  # 如果未注册
            logger.warning(f"[ToolLoader] 未注册的工具: {tool_id}")  # 记录警告
            return None

        # 检查是否已加载
        if tool_id in self._loaded_tools:  # 如果已在已加载字典中
            return self._loaded_tools[tool_id]  # 返回已加载的实例

        # 检查可用性
        if not self.check_tool_available(tool_id):  # 如果不可用
            # 尝试使用降级工具
            if reg.fallback_tool:  # 如果有降级工具
                logger.info(f"[ToolLoader] 使用降级工具: {tool_id}")  # 记录信息
                try:  # 尝试加载降级工具
                    fallback = reg.fallback_tool()  # 创建降级工具实例
                    self._fallback_tools[tool_id] = fallback  # 存入降级工具字典
                    return fallback  # 返回降级工具实例
                except Exception as e:  # 捕获异常
                    logger.error(f"[ToolLoader] 降级工具加载失败: {e}")  # 记录错误

            logger.warning(f"[ToolLoader] 工具不可用: {tool_id}")  # 记录警告
            return None  # 返回None

        # 加载主工具
        try:  # 尝试加载
            tool = reg.tool_class()  # 创建工具实例
            self._loaded_tools[tool_id] = tool  # 存入已加载字典

            # 注册到tool_manager
            tool_manager.register_tool(  # 调用工具管理器注册
                name=tool_id,  # 工具名称
                func=tool.run,  # 工具执行函数
                description=tool.description  # 工具描述
            )

            logger.info(f"[ToolLoader] 加载工具: {tool_id}")  # 记录信息
            return tool  # 返回工具实例

        except Exception as e:  # 捕获异常
            logger.error(f"[ToolLoader] 加载工具失败 {tool_id}: {e}")  # 记录错误
            return None  # 返回None

    def unload_tool(self, tool_id: str) -> bool:  # 卸载工具的方法
        """
        卸载工具

        Args:  # 参数说明
            tool_id: 工具ID  # 要卸载的工具

        Returns:  # 返回值
            bool: 是否成功  # True表示成功
        """
        if tool_id in self._loaded_tools:  # 如果在已加载字典中
            del self._loaded_tools[tool_id]  # 删除
            tool_manager.unregister_tool(tool_id)  # 从工具管理器注销
            logger.info(f"[ToolLoader] 卸载工具: {tool_id}")  # 记录信息
            return True

        if tool_id in self._fallback_tools:  # 如果在降级工具字典中
            del self._fallback_tools[tool_id]  # 删除
            return True

        return False  # 未找到工具

    def load_conditional(self, feature_id: str, tool_ids: list[str]):  # 条件加载工具的方法
        """
        条件加载工具

        仅在功能启用时加载指定工具。

        Args:  # 参数说明
            feature_id: 功能ID  # 关联的功能开关
            tool_ids: 工具ID列表  # 要加载的工具列表
        """
        if not is_feature_enabled(feature_id):  # 如果功能未启用
            logger.info(f"[ToolLoader] 功能未启用，跳过加载: {feature_id}")  # 记录信息
            return

        for tool_id in tool_ids:  # 遍历工具ID列表
            self.load_tool(tool_id)  # 加载工具

    def load_all(self):  # 加载所有可用工具的方法
        """
        加载所有可用工具

        自动根据功能开关和依赖条件加载工具。
        """
        logger.info("[ToolLoader] 开始加载工具...")  # 记录信息

        loaded = 0  # 成功计数
        skipped = 0  # 跳过计数
        failed = 0  # 失败计数

        for tool_id, _reg in self._registrations.items():  # 遍历所有注册
            tool = self.load_tool(tool_id)  # 加载工具

            if tool:  # 如果加载成功
                loaded += 1  # 成功计数加1
            elif not self.check_tool_available(tool_id):  # 如果因不可用而失败
                skipped += 1  # 跳过计数加1
            else:  # 其他失败原因
                failed += 1  # 失败计数加1

        # 加载文件系统中的工具（不依赖feature_manager的传统工具）
        file_loaded = self._load_from_filesystem()  # 从文件系统加载

        # 加载 BTC 交易工具（避免循环导入，延迟加载）
        btc_loaded = self._load_btc_trading_tools()

        logger.info(  # 记录统计信息
            f"[ToolLoader] 工具加载完成: "
            f"成功={loaded}, 跳过={skipped}, 失败={failed}, 文件系统={file_loaded}, BTC={btc_loaded}"
        )

    def _load_from_filesystem(self) -> int:  # 从文件系统加载工具的私有方法
        """
        从文件系统加载工具

        Returns:  # 返回值
            加载的工具数量  # 成功加载的工具数
        """
        loaded = 0  # 计数器

        if not self._tools_dir.exists():  # 如果工具目录不存在
            return 0  # 返回0

        for file_path in self._tools_dir.glob("*.py"):  # 遍历所有.py文件
            if file_path.name.startswith("_"):  # 跳过下划线开头的文件
                continue

            try:  # 异常捕获
                # 动态导入模块
                spec = importlib.util.spec_from_file_location(  # 创建模块规范
                    file_path.stem,  # 模块名
                    file_path  # 文件路径
                )
                if spec is None or spec.loader is None:  # 如果规范无效
                    continue  # 跳过

                module = importlib.util.module_from_spec(spec)  # 从规范创建模块

                # 检查是否有功能守卫
                if hasattr(module, "REQUIRED_FEATURE"):  # 如果有REQUIRED_FEATURE属性
                    feature_id = module.REQUIRED_FEATURE  # 获取功能ID
                    if not is_feature_enabled(feature_id):  # 如果功能未启用
                        logger.debug(  # 记录调试日志
                            f"[ToolLoader] 跳过 {file_path.name}, "
                            f"需要功能: {feature_id}"
                        )
                        continue  # 跳过

                # 执行模块
                spec.loader.exec_module(module)  # 执行模块代码

                # 查找工具类
                for _name, obj in inspect.getmembers(module):  # 遍历模块成员
                    if (  # 检查是否为有效的工具类
                            inspect.isclass(obj) and  # 是类
                            issubclass(obj, BaseTool) and  # 继承BaseTool
                            obj is not BaseTool and  # 不是BaseTool本身
                            hasattr(obj, "tool_id") and  # 有tool_id属性
                            obj.tool_id not in self._registrations  # 如果未注册
                    ):
                        self.register(obj)  # 注册
                        if self.load_tool(obj.tool_id):  # 加载工具
                            loaded += 1  # 计数加1

            except Exception as e:  # 捕获异常
                logger.warning(f"[ToolLoader] 加载工具文件失败 {file_path}: {e}")  # 记录警告

        return loaded  # 返回加载数量

    def _load_btc_trading_tools(self) -> int:
        """
        加载 BTC 交易工具

        延迟加载以避免循环导入问题。
        在 tool_manager 完全初始化后调用。

        Returns:
            成功加载的工具数量
        """
        # 检查功能是否启用
        if not is_feature_enabled("btc_trading"):
            logger.debug("[ToolLoader] BTC交易功能未启用，跳过加载")
            return 0

        loaded = 0

        try:
            # 导入所有 BTC 工具类
            from tools.btc_trading.base_tools import (
                BTCAccountInfo,
                BTCMarketOverview,
                BTCPriceQuery,
                BTCTechnicalAnalysis,
            )
            from tools.btc_trading.risk_tools import (
                BTCCheckRecovery,
                BTCEmergencyStop,
                BTCIntervention,
                BTCRecoverTrading,
                BTCRiskCheck,
            )
            from tools.btc_trading.strategy_tools import BTCRiskAssessment, BTCStrategyExplain, BTCStrategySelector
            from tools.btc_trading.trading_tools import (
                BTCConfirmTrade,
                BTCExecuteTrade,
                BTCGenerateReport,
                BTCGetProcessStatus,
                BTCLaunchAutopilot,
                BTCMonitorTrading,
                BTCStopAutopilot,
            )

            # 定义所有要注册的工具
            btc_tools = [
                # Phase 1: 基础查询
                (BTCPriceQuery, "btc_trading"),
                (BTCMarketOverview, "btc_trading"),
                (BTCTechnicalAnalysis, "btc_trading"),
                (BTCAccountInfo, "btc_trading"),
                # Phase 2: 策略工具
                (BTCStrategySelector, "btc_trading"),
                (BTCStrategyExplain, "btc_trading"),
                (BTCRiskAssessment, "btc_trading"),
                # Phase 3: 交易执行
                (BTCLaunchAutopilot, "btc_trading"),
                (BTCGetProcessStatus, "btc_trading"),
                (BTCStopAutopilot, "btc_trading"),
                (BTCMonitorTrading, "btc_trading"),
                (BTCGenerateReport, "btc_trading"),
                (BTCConfirmTrade, "btc_trading"),
                (BTCExecuteTrade, "btc_trading"),
                # Phase 4: 风控工具
                (BTCRiskCheck, "btc_trading"),
                (BTCEmergencyStop, "btc_trading"),
                (BTCIntervention, "btc_trading"),
                (BTCCheckRecovery, "btc_trading"),
                (BTCRecoverTrading, "btc_trading"),
            ]

            # 注册并加载每个工具
            for tool_class, feature_id in btc_tools:
                try:
                    # 检查是否已注册
                    if tool_class.tool_id in self._registrations:
                        continue

                    # 注册工具
                    self.register(tool_class, feature_id=feature_id)

                    # 加载工具
                    if self.load_tool(tool_class.tool_id):
                        loaded += 1
                        logger.debug(f"[ToolLoader] 加载BTC工具: {tool_class.tool_id}")
                except Exception as e:
                    logger.warning(f"[ToolLoader] 加载BTC工具失败 {tool_class.tool_id}: {e}")

            if loaded > 0:
                logger.info(f"[ToolLoader] BTC交易工具加载完成: {loaded}个")

        except ImportError as e:
            logger.debug(f"[ToolLoader] BTC工具模块未找到: {e}")
        except Exception as e:
            logger.warning(f"[ToolLoader] 加载BTC交易工具失败: {e}")

        return loaded

    def get_tool_status(self, tool_id: str) -> dict:  # 获取工具状态的方法
        """
        获取工具状态

        Args:  # 参数说明
            tool_id: 工具ID  # 目标工具

        Returns:  # 返回值
            状态字典  # 包含注册、加载、可用等状态
        """
        reg = self._registrations.get(tool_id)  # 获取注册信息
        if reg is None:  # 如果未注册
            return {"registered": False}  # 返回未注册状态

        loaded = tool_id in self._loaded_tools  # 检查是否已加载
        fallback = tool_id in self._fallback_tools  # 检查是否是降级工具
        available = self.check_tool_available(tool_id)  # 检查是否可用

        # 检查功能状态
        feature_enabled = True
        if reg.feature_id:  # 如果有功能ID
            feature_enabled = is_feature_enabled(reg.feature_id)  # 检查功能状态

        # 检查依赖状态
        missing_deps = []  # 缺失依赖列表
        for dep in reg.dependencies:  # 遍历依赖
            status = dependency_checker.check_dependency(dep)  # 检查依赖
            if status != DependencyStatus.AVAILABLE:  # 如果不可用
                missing_deps.append(dep)  # 添加到缺失列表

        return {  # 返回状态字典
            "registered": True,  # 已注册
            "loaded": loaded,  # 是否已加载
            "fallback": fallback,  # 是否使用降级工具
            "available": available,  # 是否可用
            "feature_id": reg.feature_id,  # 功能ID
            "feature_enabled": feature_enabled,  # 功能是否启用
            "dependencies": reg.dependencies,  # 依赖列表
            "missing_deps": missing_deps,  # 缺失依赖
            "can_load": feature_enabled and len(missing_deps) == 0  # 是否可以加载
        }

    def get_all_status(self) -> dict[str, dict]:  # 获取所有工具状态的方法
        """
        获取所有工具状态

        Returns:  # 返回值
            工具状态字典  # 工具ID到状态的映射
        """
        return {
            tool_id: self.get_tool_status(tool_id)  # 获取每个工具的状态
            for tool_id in self._registrations  # 遍历所有注册
        }

    def refresh(self):  # 刷新工具加载状态的方法
        """
        刷新工具加载状态

        根据最新的功能开关重新加载工具。
        """
        logger.info("[ToolLoader] 刷新工具状态...")  # 记录信息

        # 卸载不可用的工具
        for tool_id in list(self._loaded_tools.keys()):  # 遍历已加载工具
            if not self.check_tool_available(tool_id):  # 如果不再可用
                self.unload_tool(tool_id)  # 卸载

        # 加载新可用的工具
        for tool_id, _reg in self._registrations.items():  # 遍历所有注册
            if tool_id not in self._loaded_tools and self.check_tool_available(tool_id):  # 如果未加载且现在可用
                self.load_tool(tool_id)  # 加载


# 全局实例
tool_loader = ToolLoader()  # 创建工具加载器全局实例


# ═══════════════════════════════════════════════════════════════
# 装饰器
# ═══════════════════════════════════════════════════════════════

def feature_tool(feature_id: str, dependencies: list[str] = None):  # 功能工具装饰器
    """
    功能工具装饰器

    标记工具依赖的功能和依赖。

    示例:
        @feature_tool("embedding", dependencies=["sentence-transformers"])
        class SemanticSearchTool(BaseTool):
            tool_id = "semantic_search"
            ...
    """

    def decorator(tool_class: type[BaseTool]):  # 装饰器函数
        tool_loader.register(  # 注册工具
            tool_class,
            feature_id=feature_id,
            dependencies=dependencies
        )
        return tool_class  # 返回工具类

    return decorator


def fallback_tool(primary_tool_id: str):  # 降级工具装饰器
    """
    降级工具装饰器

    标记工具作为其他工具的降级版本。

    示例:
        @fallback_tool("semantic_search")
        class KeywordSearchTool(BaseTool):
            tool_id = "keyword_search_fallback"
            ...
    """

    def decorator(tool_class: type[BaseTool]):  # 装饰器函数
        # 更新主工具的降级设置
        reg = tool_loader._registrations.get(primary_tool_id)  # 获取主工具注册
        if reg:  # 如果找到
            reg.fallback_tool = tool_class  # 设置降级工具
        return tool_class  # 返回工具类

    return decorator


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════

def load_tools():  # 加载所有工具的便捷函数
    """加载所有工具"""
    tool_loader.load_all()  # 调用加载器方法


def is_tool_available(tool_id: str) -> bool:  # 检查工具是否可用的便捷函数
    """检查工具是否可用"""
    return tool_loader.check_tool_available(tool_id)  # 调用加载器方法


def get_tool(tool_id: str) -> BaseTool | None:  # 获取工具实例的便捷函数
    """获取工具实例"""
    # 先尝试加载
    if tool_id not in tool_loader._loaded_tools:  # 如果未加载
        return tool_loader.load_tool(tool_id)  # 加载工具
    return tool_loader._loaded_tools.get(tool_id)  # 返回已加载的工具

# ═══════════════════════════════════════════════════════════════════════════════
# 【文件总结】
# ═══════════════════════════════════════════════════════════════════════════════
#
# 【文件角色】
# 本文件(tool_loader.py)是SiliconBase V5工具系统的"插排架构"核心实现。
# 它提供了基于功能开关的条件加载机制，支持工具的热插拔、降级策略和依赖检查，
# 使工具系统具有高度的灵活性和可扩展性。
#
# 【在系统中的位置】
# - 位于: SiliconBase_V5/core/tool_loader.py
# - 上游调用: system_init.py（系统初始化时加载工具）
# - 下游使用: tools/目录下的具体工具类
#
# 【关联文件】
# 1. core/tool_manager.py - 工具管理器，负责工具的注册和调用
# 2. core/base_tool.py - 工具基类定义
# 3. core/feature_manager.py - 功能管理器，提供功能开关检查
# 4. core/utils/dependency_checker.py - 依赖检查器，检查第三方依赖
# 5. core/logger.py - 日志记录器
# 6. tools/*.py - 具体工具实现
#
# 【核心功能】
# 1. 条件加载: 基于feature_manager的功能开关决定是否加载工具
# 2. 依赖检查: 检查工具所需的第三方库是否可用
# 3. 降级策略: 主工具不可用时自动使用降级版本
# 4. 动态注册: 支持装饰器方式注册工具
# 5. 状态监控: 提供工具状态查询和统计
# 6. 热刷新: 支持运行时根据功能开关变化动态加载/卸载工具
#
# 【装饰器】
# 1. @feature_tool(feature_id, dependencies): 标记工具依赖的功能和第三方库
# 2. @fallback_tool(primary_tool_id): 标记降级工具
#
# 【达到的效果】
# 1. 模块化: 工具可以独立开发、独立部署
# 2. 条件加载: 根据配置动态启用/禁用功能
# 3. 优雅降级: 高级功能不可用时自动切换到基础版本
# 4. 依赖管理: 自动检查和处理第三方依赖
# 5. 零配置: 自动发现tools目录下的工具文件
#
# 【使用示例】
#   # 使用装饰器注册工具
#   @feature_tool("embedding", dependencies=["sentence-transformers"])
#   class SemanticSearchTool(BaseTool):
#       tool_id = "semantic_search"
#       ...
#
#   # 加载所有工具
#   tool_loader.load_all()
#
#   # 检查工具状态
#   status = tool_loader.get_tool_status("semantic_search")
#
# ═══════════════════════════════════════════════════════════════════════════════
