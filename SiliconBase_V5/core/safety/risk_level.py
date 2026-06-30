#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""统一风险等级定义  # 模块功能概述

所有风险等级相关的枚举都应该从这里导入，避免多处定义导致的混乱。  # 设计目的

使用方式:  # 使用示例
    from core.safety.risk_level import RiskLevel  # 导入方式

    if risk >= RiskLevel.HIGH:  # 比较示例
        ...  # 处理逻辑

作者: Enum-Unifier  # 作者
日期: 2026-02-28  # 日期
"""  # 文档字符串结束

from enum import Enum  # 导入枚举基类


class RiskLevel(str, Enum):  # 风险等级枚举类（继承str和Enum）
    """统一风险等级枚举  # 类文档字符串

    继承str和Enum，可以直接与字符串比较，也可以使用.value获取字符串值。  # 特性说明

    支持两组风险等级定义：  # 支持的双体系
    1. 安全守卫级别 (SAFE/NOTICE/CONFIRM/BLOCK) - 用于安全守卫模块  # 体系1
    2. 策略级别 (LOW/MEDIUM/HIGH/CRITICAL) - 用于策略评估和行为识别  # 体系2

    两组级别通过numeric_value属性进行数值映射，实现兼容。  # 兼容机制
    """  # 文档字符串结束
    # 安全守卫级别  # 第一组：安全守卫级别
    SAFE = "safe"  # 安全
    NOTICE = "notice"  # 注意
    CONFIRM = "confirm"  # 需确认
    BLOCK = "block"  # 禁止

    # 策略级别（数值兼容）  # 第二组：策略级别
    LOW = "low"        # 对应数值 1，低风险
    MEDIUM = "medium"  # 对应数值 2，中风险
    HIGH = "high"      # 对应数值 3，高风险
    CRITICAL = "critical"  # 对应数值 4，极高风险

    def __lt__(self, other):  # 小于比较运算符
        """支持风险等级比较"""  # 方法文档字符串
        if isinstance(other, RiskLevel):  # 如果比较对象也是RiskLevel
            return self.numeric_value < other.numeric_value  # 比较数值
        return NotImplemented  # 不支持其他类型比较

    def __le__(self, other):  # 小于等于比较运算符
        return self == other or self < other  # 等于或小于

    def __gt__(self, other):  # 大于比较运算符
        return not self <= other  # 不大于等于即大于

    def __ge__(self, other):  # 大于等于比较运算符
        return not self < other  # 不小于即大于等于

    @property  # 属性装饰器
    def numeric_value(self) -> int:  # 数值映射属性
        """获取数值表示（兼容policy.py的整数值）"""  # 属性文档字符串
        mapping = {  # 枚举到数值的映射字典
            # 安全守卫级别映射  # 体系1映射
            RiskLevel.SAFE: 1,  # SAFE=1
            RiskLevel.NOTICE: 2,  # NOTICE=2
            RiskLevel.CONFIRM: 3,  # CONFIRM=3
            RiskLevel.BLOCK: 4,  # BLOCK=4
            # 策略级别映射  # 体系2映射
            RiskLevel.LOW: 1,  # LOW=1
            RiskLevel.MEDIUM: 2,  # MEDIUM=2
            RiskLevel.HIGH: 3,  # HIGH=3
            RiskLevel.CRITICAL: 4,  # CRITICAL=4
        }  # 映射结束
        return mapping.get(self, 2)  # 默认返回2（MEDIUM）

    @property  # 属性装饰器
    def display_name(self) -> str:  # 中文显示名称属性
        """获取中文显示名称"""  # 属性文档字符串
        mapping = {  # 枚举到中文的映射字典
            RiskLevel.SAFE: "安全",  # SAFE
            RiskLevel.NOTICE: "注意",  # NOTICE
            RiskLevel.CONFIRM: "需确认",  # CONFIRM
            RiskLevel.BLOCK: "禁止",  # BLOCK
            RiskLevel.LOW: "低风险",  # LOW
            RiskLevel.MEDIUM: "中风险",  # MEDIUM
            RiskLevel.HIGH: "高风险",  # HIGH
            RiskLevel.CRITICAL: "极高风险",  # CRITICAL
        }  # 映射结束
        return mapping.get(self, self.value)  # 默认返回原值


# 便捷映射：策略级别到安全守卫级别的转换  # 策略转守卫映射字典
STRATEGY_TO_GUARD_MAP = {  # 转换映射
    RiskLevel.LOW: RiskLevel.SAFE,  # LOW -> SAFE
    RiskLevel.MEDIUM: RiskLevel.NOTICE,  # MEDIUM -> NOTICE
    RiskLevel.HIGH: RiskLevel.CONFIRM,  # HIGH -> CONFIRM
    RiskLevel.CRITICAL: RiskLevel.BLOCK,  # CRITICAL -> BLOCK
}  # 映射结束

# 便捷映射：安全守卫级别到策略级别的转换  # 守卫转策略映射字典
GUARD_TO_STRATEGY_MAP = {  # 转换映射
    RiskLevel.SAFE: RiskLevel.LOW,  # SAFE -> LOW
    RiskLevel.NOTICE: RiskLevel.MEDIUM,  # NOTICE -> MEDIUM
    RiskLevel.CONFIRM: RiskLevel.HIGH,  # CONFIRM -> HIGH
    RiskLevel.BLOCK: RiskLevel.CRITICAL,  # BLOCK -> CRITICAL
}  # 映射结束


def to_guard_level(risk: RiskLevel) -> RiskLevel:  # 策略转守卫级别函数
    """将策略级别转换为安全守卫级别"""  # 函数文档字符串
    return STRATEGY_TO_GUARD_MAP.get(risk, risk)  # 查表转换，无映射则返回原值


def to_strategy_level(risk: RiskLevel) -> RiskLevel:  # 守卫转策略级别函数
    """将安全守卫级别转换为策略级别"""  # 函数文档字符串
    return GUARD_TO_STRATEGY_MAP.get(risk, risk)  # 查表转换，无映射则返回原值


# =============================================================================  # 分隔线
# 【文件总结】  # 总结区域标题
# =============================================================================  # 分隔线
# 文件角色：统一风险等级定义模块，解决多处定义导致的混乱问题  # 角色说明
# 设计背景：  # 背景说明
#   - 项目中同时存在两套风险等级体系  # 背景1
#   - 体系1（安全守卫）：SAFE/NOTICE/CONFIRM/BLOCK，用于安全控制  # 体系1
#   - 体系2（策略评估）：LOW/MEDIUM/HIGH/CRITICAL，用于行为分析  # 体系2
#   - 需要统一入口避免混淆和重复定义  # 统一需求
# 核心功能：  # 功能列表
#   1. 统一枚举定义 - 在一个地方定义所有风险等级  # 功能1
#   2. 双体系兼容 - 通过numeric_value实现两套体系的数值映射  # 功能2
#   3. 便捷转换 - 提供策略级别与安全守卫级别互转函数  # 功能3
#   4. 比较运算 - 支持< <= > >=等比较操作  # 功能4
#   5. 中文显示 - 提供display_name属性获取中文名称  # 功能5
# 关联文件：  # 关联说明
#   - core/safety_guard.py: 安全守卫（使用SAFE/NOTICE/CONFIRM/BLOCK）  # 关联1
#   - core/behavior_recognizer.py: 行为识别（使用LOW/MEDIUM/HIGH/CRITICAL）  # 关联2
#   - core/behavior_analyzer.py: 行为分析（引用风险等级）  # 关联3
# 达到效果：  # 效果说明
#   - 消除多处定义导致的类型混乱和比较错误  # 效果1
#   - 提供统一的导入入口，降低使用门槛  # 效果2
#   - 支持无缝的双体系转换  # 效果3
#   - 通过继承str可直接与字符串比较  # 效果4
# =============================================================================  # 分隔线结束
