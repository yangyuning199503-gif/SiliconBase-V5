# core/vision_user_notifier.py
#!/usr/bin/env python3
"""
视觉功能用户通知模块

功能：
1. 提供清晰的视觉功能状态提示
2. 生成修复指南
3. 支持多种通知方式（日志、API响应、前端消息）
"""
from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.logger import logger
from core.vision.vision_health_check import VisionHealthChecker, VisionHealthReport
from core.vision.vision_validator import VisionConfigValidator, VisionValidationResult


class NotificationLevel(Enum):
    """通知级别"""
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class VisionStatusMessage:
    """视觉状态消息"""
    level: NotificationLevel
    title: str
    message: str
    details: dict[str, Any]
    fix_steps: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "title": self.title,
            "message": self.message,
            "details": self.details,
            "fix_steps": self.fix_steps
        }

    def to_markdown(self) -> str:
        """转换为Markdown格式"""
        emoji = {
            NotificationLevel.INFO: "ℹ️",
            NotificationLevel.SUCCESS: "✅",
            NotificationLevel.WARNING: "⚠️",
            NotificationLevel.ERROR: "❌"
        }.get(self.level, "ℹ️")

        lines = [
            f"## {emoji} {self.title}",
            "",
            self.message,
            ""
        ]

        if self.fix_steps:
            lines.extend([
                "### 修复步骤:",
                ""
            ])
            for i, step in enumerate(self.fix_steps, 1):
                lines.append(f"{i}. {step}")
            lines.append("")

        return "\n".join(lines)


class VisionUserNotifier:
    """视觉用户通知器"""

    def __init__(self):
        self.validator = VisionConfigValidator()
        self.health_checker = VisionHealthChecker()

    def get_full_status(self) -> VisionStatusMessage:
        """获取完整的视觉状态报告"""
        # 运行验证和健康检查
        validation = self.validator.validate()
        health = self.health_checker.run_full_check(auto_disable_on_failure=False)

        # 分析状态
        screenshot_ok = any(
            i.status.value in ["pass", "warn"]
            for i in health.items
            if i.name == "截图功能"
        )
        model_ok = validation.valid

        # 构建状态消息
        if screenshot_ok and model_ok:
            return self._build_success_message(validation, health)
        elif not screenshot_ok and not model_ok:
            return self._build_full_failure_message(validation, health)
        elif not screenshot_ok:
            return self._build_screenshot_failure_message(validation, health)
        else:
            return self._build_model_failure_message(validation, health)

    def _build_success_message(self, validation: VisionValidationResult,
                               health: VisionHealthReport) -> VisionStatusMessage:
        """构建成功消息"""
        return VisionStatusMessage(
            level=NotificationLevel.SUCCESS,
            title="视觉感知功能正常",
            message=f"""
✅ 截图功能: 正常
✅ 视觉模型: {validation.model_name}
📍 Ollama地址: {validation.ollama_url}
            """.strip(),
            details={
                "model": validation.model_name,
                "backend": validation.backend_name,
                "available_models": validation.available_models[:5]
            },
            fix_steps=[]
        )

    def _build_full_failure_message(self, validation: VisionValidationResult,
                                    health: VisionHealthReport) -> VisionStatusMessage:
        """构建完全失败消息"""
        details = []
        fix_steps = []

        # 截图问题
        screenshot_item = next((i for i in health.items if i.name == "截图功能"), None)
        if screenshot_item and screenshot_item.status.value == "fail":
            details.append(f"❌ 截图功能: {screenshot_item.message}")
            fix_steps.extend([
                "检查显示器是否正常连接",
                "如果是远程服务器，视觉功能可能不可用（这是正常的）",
                "确保运行用户有屏幕访问权限"
            ])

        # 模型问题
        if validation.errors:
            details.append(f"❌ 视觉模型: {validation.errors[0]}")

        if validation.model_name and validation.model_name not in validation.available_models:
            fix_steps.append(f"安装视觉模型: ollama pull {validation.model_name}")

        if any("无法连接到Ollama" in e for e in validation.errors):
            fix_steps.insert(0, "启动Ollama服务: ollama serve")

        # 提供替代方案
        fix_steps.extend([
            "",
            "💡 替代方案:",
            "- 视觉功能在服务器/远程环境中可禁用",
            "- 纯文本模式仍可正常使用所有对话功能",
            "- 如需视觉功能，请在有显示器的本地环境运行"
        ])

        return VisionStatusMessage(
            level=NotificationLevel.ERROR,
            title="视觉感知当前不可用",
            message="\n".join(details),
            details={
                "validation": validation.to_dict(),
                "health": health.to_dict()
            },
            fix_steps=fix_steps
        )

    def _build_screenshot_failure_message(self, validation: VisionValidationResult,
                                          health: VisionHealthReport) -> VisionStatusMessage:
        """构建仅截图失败消息"""
        screenshot_item = next((i for i in health.items if i.name == "截图功能"), None)

        return VisionStatusMessage(
            level=NotificationLevel.WARNING,
            title="截图功能不可用",
            message=f"""
⚠️ 截图功能: {screenshot_item.message if screenshot_item else "检测失败"}
✅ 视觉模型: {validation.model_name} (配置正确)

说明: 当前环境可能无法访问显示器（如远程服务器、容器等）
            """.strip(),
            details={
                "screenshot_error": screenshot_item.message if screenshot_item else "unknown",
                "model": validation.model_name
            },
            fix_steps=[
                "此问题在服务器环境中是正常的",
                "如需截图功能，请在有显示器的本地桌面环境运行",
                "其他功能（对话、记忆等）不受影响，可正常使用"
            ]
        )

    def _build_model_failure_message(self, validation: VisionValidationResult,
                                     health: VisionHealthReport) -> VisionStatusMessage:
        """构建仅模型失败消息"""
        fix_steps = []

        # 分析具体问题
        if validation.model_name:
            if not self.validator._is_vision_model(validation.model_name):
                fix_steps.append(
                    f"当前模型 '{validation.model_name}' 可能不支持视觉，建议更换为视觉模型"
                )
                fix_steps.append("推荐: qwen3-vl:8b 或 llava:13b")
            else:
                fix_steps.append(f"安装视觉模型: ollama pull {validation.model_name}")
        else:
            fix_steps.append("在 config/global.yaml 中配置 ai.vision.backends.{backend}.model")

        if any("无法连接到Ollama" in e for e in validation.errors):
            fix_steps.insert(0, "启动Ollama服务: ollama serve")

        # 显示可用模型
        vision_models = self.validator._find_vision_models(validation.available_models)
        if vision_models:
            fix_steps.append(f"已安装的视觉模型: {', '.join(vision_models[:3])}")

        return VisionStatusMessage(
            level=NotificationLevel.ERROR,
            title="视觉模型配置错误",
            message=f"""
✅ 截图功能: 正常
❌ 视觉模型: {validation.errors[0] if validation.errors else '配置错误'}

当前配置: {validation.model_name or '未配置'}
推荐模型: qwen3-vl:8b (或其他支持-vl后缀的模型)
            """.strip(),
            details={
                "model": validation.model_name,
                "errors": validation.errors,
                "available_models": validation.available_models
            },
            fix_steps=fix_steps
        )

    def notify_startup(self):
        """启动时通知"""
        status = self.get_full_status()

        # 根据级别使用不同的日志级别
        if status.level == NotificationLevel.SUCCESS:
            logger.info(f"[VisionNotifier] {status.title}\n{status.message}")
        elif status.level == NotificationLevel.WARNING:
            logger.warning(f"[VisionNotifier] {status.title}\n{status.message}")
        else:
            logger.error(f"[VisionNotifier] {status.title}\n{status.message}")

        if status.fix_steps:
            for step in status.fix_steps:
                if step.startswith("-") or step.startswith("💡"):
                    logger.info(f"[VisionNotifier] {step}")
                else:
                    logger.warning(f"[VisionNotifier]   {step}")

        return status

    def get_api_response(self) -> dict[str, Any]:
        """获取API响应格式的状态"""
        status = self.get_full_status()
        return {
            "vision_enabled": status.level in [NotificationLevel.SUCCESS, NotificationLevel.WARNING],
            "vision_available": status.level == NotificationLevel.SUCCESS,
            "status": status.to_dict()
        }

    def get_console_output(self) -> str:
        """获取控制台输出格式的状态"""
        status = self.get_full_status()

        lines = [
            "",
            "╔" + "═" * 48 + "╗",
            f"║ {status.title:<46} ║",
            "╠" + "═" * 48 + "╣",
        ]

        # 格式化消息内容
        for line in status.message.split('\n'):
            lines.append(f"║ {line.strip():<46} ║")

        if status.fix_steps:
            lines.append("╠" + "─" * 48 + "╣")
            lines.append(f"║ {'修复步骤:':<46} ║")
            for step in status.fix_steps:
                if step:  # 跳过空行
                    # 截断长行
                    display_step = step[:46] if len(step) <= 46 else step[:43] + "..."
                    lines.append(f"║ • {display_step:<44} ║")

        lines.append("╚" + "═" * 48 + "╝")
        lines.append("")

        return "\n".join(lines)


# 全局通知器实例
vision_notifier = VisionUserNotifier()


# 便捷函数
def get_vision_status() -> VisionStatusMessage:
    """获取视觉状态"""
    return vision_notifier.get_full_status()


def print_vision_status():
    """打印视觉状态到控制台"""
    print(vision_notifier.get_console_output())


def notify_vision_startup() -> VisionStatusMessage:
    """启动时通知视觉状态"""
    return vision_notifier.notify_startup()


def get_vision_api_status() -> dict[str, Any]:
    """获取API格式的视觉状态"""
    return vision_notifier.get_api_response()


# 预定义的消息模板
VISION_STATUS_MESSAGES = {
    "screenshot_fail": """
⚠️ 截图功能当前不可用

可能原因:
  • 当前环境为远程服务器/容器，无物理显示器
  • 用户权限不足，无法访问屏幕
  • X11/Wayland显示服务器未运行

建议:
  • 如果是在服务器上运行，这是正常现象，可忽略此警告
  • 视觉相关功能将被自动禁用
  • 其他功能（对话、记忆等）不受影响
""",
    "model_mismatch": """
⚠️ 视觉模型配置可能不正确

当前配置: {current_model}
问题: 模型名称不包含'-vl'，可能不支持视觉功能

建议:
  1. 更换为视觉模型，例如:
     ollama pull qwen3-vl:8b

  2. 修改 config/global.yaml:
     ai:
       vision:
         backends:
           ollama-vision:
             model: qwen3-vl:8b

  3. 重启服务
""",
    "model_not_found": """
❌ 视觉模型未安装

配置模型: {model_name}
状态: 在Ollama中未找到

修复步骤:
  1. 安装视觉模型:
     ollama pull {model_name}

  2. 验证安装:
     ollama list

  3. 重启SiliconBase服务

替代方案:
  • 使用已安装的视觉模型: {alternative_models}
""",
    "ollama_not_connected": """
❌ 无法连接到Ollama服务

请按以下步骤修复:

  1. 启动Ollama服务:
     ollama serve

  2. 如果Ollama在其他机器上，设置环境变量:
     export OLLAMA_HOST=your_host:11434

  3. 验证连接:
     curl http://localhost:11434/api/tags

  4. 重启SiliconBase服务
""",
    "all_good": """
✅ 视觉感知功能正常

截图功能: 正常
视觉模型: {model_name}
Ollama地址: {ollama_url}

所有视觉相关功能已就绪
"""
}


def format_vision_message(template_key: str, **kwargs) -> str:
    """格式化视觉状态消息"""
    template = VISION_STATUS_MESSAGES.get(template_key, "")
    return template.format(**kwargs)


# 全局通知器实例
vision_user_notifier = VisionUserNotifier()


def get_vision_user_notifier() -> VisionUserNotifier:
    """
    获取视觉用户通知器实例

    Returns:
        VisionUserNotifier: 视觉用户通知器实例
    """
    return vision_user_notifier
