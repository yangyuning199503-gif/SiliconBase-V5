#!/usr/bin/env python3
"""
示例插件 - SiliconBase V5 插件系统
这是一个完整的插件示例，展示了如何创建自定义工具
"""

from core.base_tool import BaseTool
from core.logger import logger

# ========== 插件元信息 ==========
PLUGIN_NAME = "示例插件"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "演示插件系统功能的示例插件"
PLUGIN_AUTHOR = "SiliconBase Team"


# ========== 生命周期钩子 ==========
def on_load():
    """插件加载时调用"""
    logger.info(f"[Plugin] {PLUGIN_NAME} v{PLUGIN_VERSION} 已加载")


def on_unload():
    """插件卸载时调用"""
    logger.info(f"[Plugin] {PLUGIN_NAME} 已卸载")


# ========== 自定义工具 ==========
class ExampleCalculatorTool(BaseTool):
    """
    示例计算器工具
    支持基本的加减乘除运算
    """

    tool_id = "example_calculator"
    name = "示例计算器"
    description = "执行基本数学运算（加减乘除）"
    version = "1.0.0"

    input_schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["add", "subtract", "multiply", "divide"],
                "description": "运算类型: add(加), subtract(减), multiply(乘), divide(除)"
            },
            "a": {
                "type": "number",
                "description": "第一个数字"
            },
            "b": {
                "type": "number",
                "description": "第二个数字"
            }
        },
        "required": ["operation", "a", "b"]
    }

    def run(self, operation: str, a: float, b: float) -> dict:
        """执行计算"""
        try:
            if operation == "add":
                result = a + b
                symbol = "+"
            elif operation == "subtract":
                result = a - b
                symbol = "-"
            elif operation == "multiply":
                result = a * b
                symbol = "*"
            elif operation == "divide":
                if b == 0:
                    return {
                        "success": False,
                        "error_code": "DIVISION_BY_ZERO",
                        "user_message": "除数不能为零",
                        "data": None
                    }
                result = a / b
                symbol = "/"
            else:
                return {
                    "success": False,
                    "error_code": "INVALID_OPERATION",
                    "user_message": f"不支持的运算: {operation}",
                    "data": None
                }

            logger.info(f"[ExampleCalculator] {a} {symbol} {b} = {result}")

            return {
                "success": True,
                "error_code": None,
                "user_message": f"计算结果: {a} {symbol} {b} = {result}",
                "data": {
                    "operation": operation,
                    "a": a,
                    "b": b,
                    "result": result,
                    "expression": f"{a} {symbol} {b} = {result}"
                }
            }

        except Exception as e:
            logger.error(f"[ExampleCalculator] 计算失败: {e}")
            return {
                "success": False,
                "error_code": "CALCULATION_ERROR",
                "user_message": f"计算错误: {str(e)}",
                "data": None
            }


class ExampleGreetingTool(BaseTool):
    """
    示例问候工具
    根据时间返回不同的问候语
    """

    tool_id = "example_greeting"
    name = "智能问候"
    description = "根据当前时间返回合适的问候语"
    version = "1.0.0"

    input_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "用户名称（可选）"
            }
        },
        "required": []
    }

    def run(self, name: str = "") -> dict:
        """生成问候语"""
        import datetime

        hour = datetime.datetime.now().hour

        if 5 <= hour < 12:
            greeting = "早上好"
        elif 12 <= hour < 18:
            greeting = "下午好"
        elif 18 <= hour < 22:
            greeting = "晚上好"
        else:
            greeting = "夜深了，注意休息"

        message = f"{greeting}，{name}！" if name else f"{greeting}！"

        return {
            "success": True,
            "error_code": None,
            "user_message": message,
            "data": {
                "greeting": greeting,
                "name": name,
                "hour": hour,
                "full_message": message
            }
        }


# ========== 插件结束 ==========
# 当插件被加载时，上述工具会自动注册到 tool_manager
