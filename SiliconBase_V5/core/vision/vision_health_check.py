# core/vision_health_check.py
#!/usr/bin/env python3
"""
视觉健康自检模块

功能：
1. 测试截图功能
2. 测试视觉模型连通性
3. 报告自检结果
4. 如果不通过，禁用视觉并提示
"""
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from core.config import config
from core.logger import logger
from core.vision.vision_validator import VisionConfigValidator


class HealthCheckStatus(Enum):
    """健康检查状态"""
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class HealthCheckItem:
    """健康检查项"""
    name: str
    status: HealthCheckStatus
    message: str
    duration_ms: float
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "duration_ms": round(self.duration_ms, 2),
            "details": self.details
        }


@dataclass
class VisionHealthReport:
    """视觉健康报告"""
    timestamp: str
    overall_status: HealthCheckStatus
    items: list[HealthCheckItem]
    summary: str
    recommendations: list[str]
    auto_disable_recommended: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "overall_status": self.overall_status.value,
            "items": [item.to_dict() for item in self.items],
            "summary": self.summary,
            "recommendations": self.recommendations,
            "auto_disable_recommended": self.auto_disable_recommended
        }

    def get_friendly_report(self) -> str:
        """生成用户友好的报告"""
        lines = [
            "=" * 50,
            "🔍 视觉感知健康自检报告",
            "=" * 50,
            f"时间: {self.timestamp}",
            f"总状态: {self._get_status_emoji(self.overall_status)} {self.overall_status.value.upper()}",
            "",
            "详细检查结果:",
            "-" * 50
        ]

        for item in self.items:
            emoji = self._get_status_emoji(item.status)
            lines.append(f"{emoji} {item.name}: {item.message}")
            if item.duration_ms > 0:
                lines.append(f"   耗时: {item.duration_ms:.1f}ms")

        lines.extend([
            "-" * 50,
            "",
            "📋 摘要:",
            self.summary
        ])

        if self.recommendations:
            lines.extend([
                "",
                "💡 建议:",
                *[f"  • {rec}" for rec in self.recommendations]
            ])

        if self.auto_disable_recommended:
            lines.extend([
                "",
                "⚠️ 警告: 建议禁用视觉功能以避免错误",
                "   系统已自动禁用视觉感知功能"
            ])

        lines.append("=" * 50)
        return "\n".join(lines)

    def _get_status_emoji(self, status: HealthCheckStatus) -> str:
        return {
            HealthCheckStatus.PASS: "✅",
            HealthCheckStatus.WARN: "⚠️",
            HealthCheckStatus.FAIL: "❌",
            HealthCheckStatus.SKIP: "⏭️"
        }.get(status, "❓")


class VisionHealthChecker:
    """视觉健康检查器"""

    def __init__(self):
        self.validator = VisionConfigValidator()
        self._last_report: VisionHealthReport | None = None

    def run_full_check(self, auto_disable_on_failure: bool = True) -> VisionHealthReport:
        """运行完整的健康检查"""
        start_time = time.time()
        items: list[HealthCheckItem] = []

        logger.info("[VisionHealthCheck] 开始视觉健康自检...")

        # 1. 配置检查
        items.append(self._check_config())

        # 2. 截图功能检查
        items.append(self._check_screenshot())

        # 3. Ollama连接检查
        items.append(self._check_ollama_connection())

        # 4. 视觉模型检查
        items.append(self._check_vision_model())

        # 5. 端到端测试（可选）
        items.append(self._check_end_to_end())

        # 计算总体状态
        overall_status = self._calculate_overall_status(items)

        # 生成摘要和建议
        summary = self._generate_summary(items)
        recommendations = self._generate_recommendations(items)

        # 判断是否需要自动禁用
        auto_disable_recommended = (
            overall_status == HealthCheckStatus.FAIL and
            auto_disable_on_failure
        )

        # 如果需要，自动禁用视觉
        if auto_disable_recommended:
            self._disable_vision(items)

        report = VisionHealthReport(
            timestamp=datetime.now().isoformat(),
            overall_status=overall_status,
            items=items,
            summary=summary,
            recommendations=recommendations,
            auto_disable_recommended=auto_disable_recommended
        )

        self._last_report = report

        duration = (time.time() - start_time) * 1000
        logger.info(f"[VisionHealthCheck] 自检完成，耗时 {duration:.1f}ms，状态: {overall_status.value}")

        return report

    def _check_config(self) -> HealthCheckItem:
        """检查视觉配置"""
        start = time.time()

        try:
            result = self.validator.validate()
            duration = (time.time() - start) * 1000

            if result.valid and not result.warnings:
                return HealthCheckItem(
                    name="配置验证",
                    status=HealthCheckStatus.PASS,
                    message=f"配置正确: {result.model_name}",
                    duration_ms=duration,
                    details={"model": result.model_name, "backend": result.backend_name}
                )
            elif result.valid:
                return HealthCheckItem(
                    name="配置验证",
                    status=HealthCheckStatus.WARN,
                    message=f"配置可用但有警告: {', '.join(result.warnings[:2])}",
                    duration_ms=duration,
                    details={"warnings": result.warnings}
                )
            else:
                return HealthCheckItem(
                    name="配置验证",
                    status=HealthCheckStatus.FAIL,
                    message=f"配置错误: {', '.join(result.errors[:2])}",
                    duration_ms=duration,
                    details={"errors": result.errors}
                )
        except Exception as e:
            duration = (time.time() - start) * 1000
            return HealthCheckItem(
                name="配置验证",
                status=HealthCheckStatus.FAIL,
                message=f"检查异常: {str(e)}",
                duration_ms=duration,
                details={"exception": str(e)}
            )

    def _check_screenshot(self) -> HealthCheckItem:
        """检查截图功能"""
        start = time.time()

        try:
            # 尝试导入并测试截图
            from tools.pixel_capture_enhanced import PixelCaptureEnhanced

            capture = PixelCaptureEnhanced()

            # 获取状态
            status = capture.get_status()
            duration = (time.time() - start) * 1000

            if status.get("available"):
                return HealthCheckItem(
                    name="截图功能",
                    status=HealthCheckStatus.PASS,
                    message=f"截图可用 ({status.get('monitors', 0)} 个显示器)",
                    duration_ms=duration,
                    details=status
                )
            else:
                mock_mode = status.get("mock_mode", False)
                if mock_mode:
                    return HealthCheckItem(
                        name="截图功能",
                        status=HealthCheckStatus.WARN,
                        message=f"截图处于模拟模式: {status.get('error', '未知原因')}",
                        duration_ms=duration,
                        details=status
                    )
                return HealthCheckItem(
                    name="截图功能",
                    status=HealthCheckStatus.FAIL,
                    message=f"截图不可用: {status.get('error', '权限或显示器问题')}",
                    duration_ms=duration,
                    details=status
                )
        except ImportError as e:
            duration = (time.time() - start) * 1000
            return HealthCheckItem(
                name="截图功能",
                status=HealthCheckStatus.FAIL,
                message=f"无法导入截图模块: {e}",
                duration_ms=duration
            )
        except Exception as e:
            duration = (time.time() - start) * 1000
            return HealthCheckItem(
                name="截图功能",
                status=HealthCheckStatus.FAIL,
                message=f"截图检查异常: {str(e)}",
                duration_ms=duration,
                details={"exception": str(e)}
            )

    def _check_ollama_connection(self) -> HealthCheckItem:
        """检查Ollama连接"""
        start = time.time()

        try:
            import urllib.request

            ollama_url = self._get_ollama_url()
            req = urllib.request.Request(
                f"{ollama_url}/api/tags",
                method="GET"
            )

            with urllib.request.urlopen(req, timeout=5) as resp:
                duration = (time.time() - start) * 1000

                if resp.status == 200:
                    import json
                    data = json.loads(resp.read().decode())
                    models = [m.get("name", "") for m in data.get("models", [])]

                    return HealthCheckItem(
                        name="Ollama连接",
                        status=HealthCheckStatus.PASS,
                        message=f"连接正常 ({len(models)} 个模型)",
                        duration_ms=duration,
                        details={"url": ollama_url, "models_count": len(models)}
                    )
                else:
                    return HealthCheckItem(
                        name="Ollama连接",
                        status=HealthCheckStatus.FAIL,
                        message=f"HTTP错误: {resp.status}",
                        duration_ms=duration
                    )
        except Exception as e:
            duration = (time.time() - start) * 1000
            return HealthCheckItem(
                name="Ollama连接",
                status=HealthCheckStatus.FAIL,
                message=f"连接失败: {str(e)}",
                duration_ms=duration,
                details={"url": self._get_ollama_url()}
            )

    def _check_vision_model(self) -> HealthCheckItem:
        """检查视觉模型"""
        start = time.time()

        try:
            result = self.validator.validate()
            duration = (time.time() - start) * 1000

            if not result.model_name:
                return HealthCheckItem(
                    name="视觉模型",
                    status=HealthCheckStatus.FAIL,
                    message="未配置视觉模型",
                    duration_ms=duration
                )

            # 检查模型是否在可用列表中
            if result.model_name in result.available_models:
                return HealthCheckItem(
                    name="视觉模型",
                    status=HealthCheckStatus.PASS,
                    message=f"模型可用: {result.model_name}",
                    duration_ms=duration
                )

            # 检查是否有匹配的模型
            matching = self.validator._find_matching_models(result.model_name, result.available_models)
            if matching:
                return HealthCheckItem(
                    name="视觉模型",
                    status=HealthCheckStatus.WARN,
                    message=f"精确匹配未找到，但找到相似模型: {matching[0]}",
                    duration_ms=duration,
                    details={"configured": result.model_name, "matching": matching}
                )

            return HealthCheckItem(
                name="视觉模型",
                status=HealthCheckStatus.FAIL,
                message=f"模型未安装: {result.model_name}",
                duration_ms=duration,
                details={"available_models": result.available_models[:5]}
            )

        except Exception as e:
            duration = (time.time() - start) * 1000
            return HealthCheckItem(
                name="视觉模型",
                status=HealthCheckStatus.FAIL,
                message=f"检查异常: {str(e)}",
                duration_ms=duration
            )

    def _check_end_to_end(self) -> HealthCheckItem:
        """端到端测试"""
        start = time.time()

        # 简化版端到端测试，仅在实际需要时执行完整测试
        # 这里只做快速检查

        duration = (time.time() - start) * 1000

        # 检查是否需要跳过（前面检查都通过才做）
        # 这里简单返回跳过状态，实际使用时可以添加完整测试
        return HealthCheckItem(
            name="端到端测试",
            status=HealthCheckStatus.SKIP,
            message="快速自检跳过详细端到端测试",
            duration_ms=duration,
            details={"note": "运行时按需执行完整测试"}
        )

    def _calculate_overall_status(self, items: list[HealthCheckItem]) -> HealthCheckStatus:
        """计算总体状态"""
        statuses = [item.status for item in items]

        if any(s == HealthCheckStatus.FAIL for s in statuses):
            return HealthCheckStatus.FAIL
        if any(s == HealthCheckStatus.WARN for s in statuses):
            return HealthCheckStatus.WARN
        if all(s == HealthCheckStatus.SKIP for s in statuses):
            return HealthCheckStatus.SKIP
        return HealthCheckStatus.PASS

    def _generate_summary(self, items: list[HealthCheckItem]) -> str:
        """生成摘要"""
        passed = sum(1 for i in items if i.status == HealthCheckStatus.PASS)
        warned = sum(1 for i in items if i.status == HealthCheckStatus.WARN)
        failed = sum(1 for i in items if i.status == HealthCheckStatus.FAIL)
        skipped = sum(1 for i in items if i.status == HealthCheckStatus.SKIP)

        parts = []
        if passed:
            parts.append(f"{passed}项通过")
        if warned:
            parts.append(f"{warned}项警告")
        if failed:
            parts.append(f"{failed}项失败")
        if skipped:
            parts.append(f"{skipped}项跳过")

        return f"共检查{len(items)}项: {', '.join(parts)}"

    def _generate_recommendations(self, items: list[HealthCheckItem]) -> list[str]:
        """生成建议"""
        recommendations = []

        for item in items:
            if item.status == HealthCheckStatus.FAIL:
                if item.name == "Ollama连接":
                    recommendations.append("启动Ollama服务: ollama serve")
                elif item.name == "视觉模型":
                    model = item.details.get("configured", "your-model")
                    recommendations.append(f"安装视觉模型: ollama pull {model}")
                elif item.name == "截图功能":
                    recommendations.append("检查显示器连接和权限设置")
            elif item.status == HealthCheckStatus.WARN and item.name == "视觉模型":
                matching = item.details.get("matching", [])
                if matching:
                    recommendations.append(f"考虑使用已安装模型: {matching[0]}")

        return recommendations

    def _disable_vision(self, items: list[HealthCheckItem]):
        """自动禁用视觉功能"""
        try:
            logger.warning("[VisionHealthCheck] 自动禁用视觉功能...")

            # 通过配置系统禁用视觉
            config.set("ai.vision.enabled", False)

            # 记录原因
            failed_items = [i.name for i in items if i.status == HealthCheckStatus.FAIL]
            logger.warning(f"[VisionHealthCheck] 视觉已禁用，失败项: {failed_items}")

        except Exception as e:
            logger.error(f"[VisionHealthCheck] 禁用视觉失败: {e}")

    def _get_ollama_url(self) -> str:
        """获取Ollama URL"""
        ollama_config = config.get("ai", {}).get("ollama", {})
        if isinstance(ollama_config, dict) and ollama_config.get("base_url"):
            return ollama_config["base_url"]
        return "http://localhost:11434"

    def get_last_report(self) -> VisionHealthReport | None:
        """获取上次检查报告"""
        return self._last_report


# 全局检查器实例
vision_health_checker = VisionHealthChecker()


def get_vision_health_check() -> VisionHealthChecker:
    """
    获取视觉健康检查器实例

    Returns:
        VisionHealthChecker: 视觉健康检查器实例
    """
    return vision_health_checker


def run_vision_health_check(auto_disable_on_failure: bool = True) -> VisionHealthReport:
    """便捷函数：运行视觉健康检查"""
    return vision_health_checker.run_full_check(auto_disable_on_failure)


def quick_vision_check() -> tuple[bool, str]:
    """快速检查视觉是否健康"""
    report = vision_health_checker.run_full_check(auto_disable_on_failure=False)

    if report.overall_status == HealthCheckStatus.PASS:
        return True, "视觉功能正常"
    elif report.overall_status == HealthCheckStatus.WARN:
        return True, f"视觉功能可用但有警告: {report.recommendations[0] if report.recommendations else '请检查配置'}"
    else:
        return False, f"视觉功能不可用: {report.recommendations[0] if report.recommendations else '请检查配置'}"
