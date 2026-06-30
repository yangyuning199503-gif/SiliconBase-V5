# core/config/vision_validator.py
#!/usr/bin/env python3
"""
视觉配置验证增强模块

功能：
1. 添加模型名称验证（检查是否包含-vl）
2. 添加Ollama连通性检查
3. 添加模型能力检测
4. 添加友好错误提示
"""
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.config import config


class VisionModelStatus(Enum):
    """视觉模型状态"""
    UNKNOWN = "unknown"
    CONFIGURED = "configured"
    CONNECTED = "connected"
    MODEL_FOUND = "model_found"
    VALID = "valid"
    ERROR = "error"


@dataclass
class VisionValidationResult:
    """视觉配置验证结果"""
    valid: bool
    status: VisionModelStatus
    backend_name: str
    model_name: str
    ollama_url: str
    errors: list[str]
    warnings: list[str]
    suggestions: list[str]
    available_models: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "status": self.status.value,
            "backend_name": self.backend_name,
            "model_name": self.model_name,
            "ollama_url": self.ollama_url,
            "errors": self.errors,
            "warnings": self.warnings,
            "suggestions": self.suggestions,
            "available_models": self.available_models
        }

    def get_friendly_message(self) -> str:
        """生成用户友好的提示信息"""
        lines = []

        if self.valid:
            lines.append("✅ 视觉配置验证通过")
            lines.append(f"   后端: {self.backend_name}")
            lines.append(f"   模型: {self.model_name}")
        else:
            lines.append("⚠️ 视觉配置验证失败")

            if self.errors:
                lines.append("\n错误:")
                for err in self.errors:
                    lines.append(f"  ❌ {err}")

            if self.warnings:
                lines.append("\n警告:")
                for warn in self.warnings:
                    lines.append(f"  ⚠️ {warn}")

            if self.suggestions:
                lines.append("\n建议修复步骤:")
                for i, sug in enumerate(self.suggestions, 1):
                    lines.append(f"  {i}. {sug}")

            if self.available_models:
                lines.append("\n可用的视觉模型:")
                for model in self.available_models[:5]:
                    lines.append(f"  • {model}")

        return "\n".join(lines)


class VisionConfigValidator:
    """视觉配置验证器"""

    # 已知的视觉模型后缀/关键词
    VISION_MODEL_INDICATORS = [
        "-vl", "-vision", "vl-", "vision-",
        "llava", "bakllava", "moondream",
        "cogvlm", "qwen-vl", "glm-4v"
    ]

    # 推荐的视觉模型
    RECOMMENDED_VISION_MODELS = [
        "qwen3-vl:8b",
        "llava:13b",
        "llava:7b",
        "bakllava:latest",
        "moondream:latest"
    ]

    def __init__(self):
        self._last_result: VisionValidationResult | None = None

    def validate(self) -> VisionValidationResult:
        """执行完整的视觉配置验证"""
        errors = []
        warnings = []
        suggestions = []

        # 1. 获取视觉配置
        vision_config = config.get("ai", {}).get("vision", {})
        if not vision_config:
            errors.append("视觉配置缺失: ai.vision 未配置")
            return VisionValidationResult(
                valid=False,
                status=VisionModelStatus.ERROR,
                backend_name="",
                model_name="",
                ollama_url="",
                errors=errors,
                warnings=warnings,
                suggestions=["请在 config/global.yaml 中配置 ai.vision"],
                available_models=[]
            )

        # 2. 检查显式开关
        enabled = vision_config.get("enabled", True)
        if not enabled:
            return VisionValidationResult(
                valid=False,
                status=VisionModelStatus.ERROR,
                backend_name="",
                model_name="",
                ollama_url="",
                errors=["视觉功能已被显式禁用 (ai.vision.enabled = false)"],
                warnings=[],
                suggestions=["如需启用视觉，设置 ai.vision.enabled = true"],
                available_models=[]
            )

        # 3. 获取默认后端配置
        default_backend = vision_config.get("default_backend")
        if not default_backend:
            errors.append("未配置默认视觉后端 (ai.vision.default_backend)")
            suggestions.append("在 config/global.yaml 中设置 ai.vision.default_backend")

        backends = vision_config.get("backends", {})
        if default_backend not in backends:
            errors.append(f"默认后端 '{default_backend}' 未在 backends 中定义")
            suggestions.append(f"在 ai.vision.backends 中添加 '{default_backend}' 配置")

        backend_config = backends.get(default_backend, {})
        model_name = backend_config.get("model", "")
        ollama_url = self._get_ollama_url()

        # 4. 验证模型名称
        if not model_name:
            errors.append("未配置视觉模型名称")
            suggestions.append(f"设置 ai.vision.backends.{default_backend}.model")
        elif not self._is_vision_model(model_name):
            warnings.append(f"模型 '{model_name}' 可能不是视觉模型 (名称中未包含 -vl 或 vision 等标识)")
            suggestions.append(f"建议使用视觉专用模型，如: {', '.join(self.RECOMMENDED_VISION_MODELS[:3])}")

        # 5. 检查Ollama连通性
        connected, conn_msg, available_models = self._check_ollama_connection(ollama_url)

        if not connected:
            errors.append(f"无法连接到Ollama: {conn_msg}")
            suggestions.extend([
                "1. 检查Ollama服务是否已启动: ollama serve",
                f"2. 检查Ollama地址配置是否正确 (当前: {ollama_url})",
                "3. 如果Ollama在其他机器上，设置环境变量: OLLAMA_HOST=your_host"
            ])
        else:
            # 6. 检查模型是否存在
            if model_name and available_models:
                # 支持模糊匹配
                matching_models = self._find_matching_models(model_name, available_models)
                if matching_models:
                    if model_name not in available_models:
                        warnings.append(f"模型 '{model_name}' 完全匹配未找到，但找到相似模型: {', '.join(matching_models[:3])}")
                        suggestions.append(f"可能需要: ollama pull {model_name}")
                else:
                    errors.append(f"模型 '{model_name}' 在Ollama中未找到")
                    suggestions.append(f"运行: ollama pull {model_name}")

                    # 推荐可用的视觉模型
                    vision_models = self._find_vision_models(available_models)
                    if vision_models:
                        suggestions.append(f"已安装的视觉模型: {', '.join(vision_models[:3])}")

        # 7. 确定状态
        if errors:
            status = VisionModelStatus.ERROR
            valid = False
        elif warnings:
            status = VisionModelStatus.CONFIGURED
            valid = True
        elif connected:
            status = VisionModelStatus.VALID
            valid = True
        else:
            status = VisionModelStatus.UNKNOWN
            valid = False

        # 8. 如果没有错误但有警告，添加使用提示
        if not errors and model_name:
            suggestions.append(f"当前视觉模型: {model_name}")
            suggestions.append("如需更换模型，修改 config/global.yaml 后重启服务")

        result = VisionValidationResult(
            valid=valid,
            status=status,
            backend_name=default_backend or "unknown",
            model_name=model_name or "未配置",
            ollama_url=ollama_url,
            errors=errors,
            warnings=warnings,
            suggestions=suggestions,
            available_models=available_models
        )

        self._last_result = result
        return result

    def quick_check(self) -> tuple[bool, str]:
        """快速检查视觉配置是否可用"""
        result = self.validate()
        if result.valid:
            return True, f"视觉配置正常: {result.model_name}"
        else:
            return False, result.get_friendly_message()

    def _is_vision_model(self, model_name: str) -> bool:
        """检查模型名称是否为视觉模型"""
        model_lower = model_name.lower()
        return any(indicator in model_lower for indicator in self.VISION_MODEL_INDICATORS)

    def _get_ollama_url(self) -> str:
        """获取Ollama服务URL"""
        # 从配置获取
        ollama_config = config.get("ai", {}).get("ollama", {})
        if isinstance(ollama_config, dict):
            base_url = ollama_config.get("base_url", "")
            if base_url:
                return base_url

        # 从环境变量获取
        import os
        host = os.environ.get("OLLAMA_HOST", "localhost")
        port = os.environ.get("OLLAMA_PORT", "11434")
        return f"http://{host}:{port}"

    def _check_ollama_connection(self, url: str) -> tuple[bool, str, list[str]]:
        """检查Ollama连接状态"""
        try:
            req = urllib.request.Request(
                f"{url}/api/tags",
                method="GET",
                headers={"Accept": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode())
                    models = [m.get("name", "") for m in data.get("models", [])]
                    return True, "连接成功", models
                else:
                    return False, f"HTTP {resp.status}", []
        except urllib.error.HTTPError as e:
            return False, f"HTTP错误: {e.code}", []
        except urllib.error.URLError as e:
            return False, f"连接失败: {e.reason}", []
        except json.JSONDecodeError as e:
            return False, f"响应解析失败: {e}", []
        except Exception as e:
            return False, f"异常: {str(e)}", []

    def _find_matching_models(self, target: str, available: list[str]) -> list[str]:
        """查找匹配的模型（支持模糊匹配）"""
        target_lower = target.lower()
        matching = []

        for model in available:
            model_lower = model.lower()
            # 完全匹配
            if model_lower == target_lower:
                return [model]
            # 前缀匹配 (例如 qwen3-vl:8b 匹配 qwen3-vl)
            if model_lower.startswith(target_lower) or target_lower.startswith(model_lower) or target_lower in model_lower or model_lower in target_lower:
                matching.append(model)

        return matching

    def _find_vision_models(self, models: list[str]) -> list[str]:
        """从可用模型中找出视觉模型"""
        return [m for m in models if self._is_vision_model(m)]

    def get_recommended_fix(self) -> dict[str, str]:
        """获取推荐的修复方案"""
        result = self.validate()

        fix_commands = []
        config_changes = []

        # 如果模型不存在，添加pull命令
        if result.model_name and result.errors and "未找到" in str(result.errors):
            fix_commands.append(f"ollama pull {result.model_name}")

        # 如果不是视觉模型，建议更换
        if result.warnings and "可能不是视觉模型" in str(result.warnings):
            vision_models = self._find_vision_models(result.available_models)
            suggested = vision_models[0] if vision_models else self.RECOMMENDED_VISION_MODELS[0]
            config_changes.append(f"ai.vision.backends.{result.backend_name}.model = {suggested}")
            fix_commands.append(f"ollama pull {suggested}")

        # 如果连接失败
        if result.errors and "无法连接到Ollama" in str(result.errors):
            fix_commands.append("ollama serve")

        return {
            "commands": "\n".join(fix_commands) if fix_commands else "无",
            "config_changes": "\n".join(config_changes) if config_changes else "无",
            "full_message": result.get_friendly_message()
        }


# 全局验证器实例
vision_validator = VisionConfigValidator()


def get_vision_validator() -> VisionConfigValidator:
    """
    获取视觉配置验证器实例

    Returns:
        VisionConfigValidator: 视觉配置验证器实例
    """
    return vision_validator


def validate_vision_config() -> VisionValidationResult:
    """便捷函数：验证视觉配置"""
    return vision_validator.validate()


def check_vision_available() -> tuple[bool, str]:
    """便捷函数：检查视觉是否可用"""
    return vision_validator.quick_check()


def get_vision_fix_guide() -> str:
    """获取视觉问题修复指南"""
    result = vision_validator.validate()
    if result.valid:
        return "✅ 视觉配置正常，无需修复"
    return result.get_friendly_message()
