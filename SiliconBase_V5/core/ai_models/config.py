"""
ModelBus配置模块

提供统一的配置管理和加载功能
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .base import ModelConfig, ModelType
from .exceptions import ConfigurationException

logger = logging.getLogger(__name__)


@dataclass
class SlotConfig:
    """槽位配置数据类"""
    slot_id: str
    model_type: ModelType
    provider_type: str
    model_name: str
    base_url: str | None = None
    api_key: str | None = None
    timeout: int = 120
    max_retries: int = 2
    enabled: bool = True
    priority: int = 0
    fallback_slots: list[str] = field(default_factory=list)
    extra_params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """验证配置"""
        if not self.slot_id:
            error_msg = "SlotConfig.slot_id 不能为空"
            logger.error(f"[SlotConfig] 验证失败: {error_msg}")
            raise ConfigurationException(error_msg, "slot_id")

        if not self.provider_type:
            error_msg = "SlotConfig.provider_type 不能为空"
            logger.error(f"[SlotConfig] 验证失败: slot_id={self.slot_id}, error={error_msg}")
            raise ConfigurationException(error_msg, "provider_type")

        if not self.model_name:
            error_msg = "SlotConfig.model_name 不能为空"
            logger.error(f"[SlotConfig] 验证失败: slot_id={self.slot_id}, error={error_msg}")
            raise ConfigurationException(error_msg, "model_name")

        if self.timeout <= 0:
            error_msg = f"SlotConfig.timeout 必须大于0, 当前值: {self.timeout}"
            logger.error(f"[SlotConfig] 验证失败: slot_id={self.slot_id}, error={error_msg}")
            raise ConfigurationException(error_msg, "timeout", self.timeout)

    def to_model_config(self) -> ModelConfig:
        """转换为ModelConfig"""
        return ModelConfig(
            provider=self.provider_type,
            model_name=self.model_name,
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=self.timeout,
            max_retries=self.max_retries,
            extra_params=self.extra_params
        )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "slot_id": self.slot_id,
            "model_type": self.model_type.name if isinstance(self.model_type, ModelType) else self.model_type,
            "provider_type": self.provider_type,
            "model_name": self.model_name,
            "base_url": self.base_url,
            "api_key": "***" if self.api_key else None,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "enabled": self.enabled,
            "priority": self.priority,
            "fallback_slots": self.fallback_slots,
            "extra_params": self.extra_params
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SlotConfig":
        """从字典创建"""
        # 处理model_type
        model_type = data.get("model_type")
        if isinstance(model_type, str):
            try:
                model_type = ModelType[model_type.upper()]
            except KeyError as _exc:
                error_msg = f"未知的ModelType: {model_type}"
                logger.error(f"[SlotConfig] 解析失败: {error_msg}")
                raise ConfigurationException(error_msg, "model_type", model_type) from _exc

        return cls(
            slot_id=data["slot_id"],
            model_type=model_type,
            provider_type=data["provider_type"],
            model_name=data["model_name"],
            base_url=data.get("base_url"),
            api_key=data.get("api_key"),
            timeout=data.get("timeout", 120),
            max_retries=data.get("max_retries", 2),
            enabled=data.get("enabled", True),
            priority=data.get("priority", 0),
            fallback_slots=data.get("fallback_slots", []),
            extra_params=data.get("extra_params", {})
        )


@dataclass
class BusConfig:
    """ModelBus全局配置"""
    default_timeout: int = 120
    max_concurrent_requests: int = 100
    enable_metrics: bool = True
    enable_circuit_breaker: bool = True
    circuit_failure_threshold: int = 5
    circuit_recovery_timeout: int = 60
    log_level: str = "INFO"
    slots: list[SlotConfig] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "default_timeout": self.default_timeout,
            "max_concurrent_requests": self.max_concurrent_requests,
            "enable_metrics": self.enable_metrics,
            "enable_circuit_breaker": self.enable_circuit_breaker,
            "circuit_failure_threshold": self.circuit_failure_threshold,
            "circuit_recovery_timeout": self.circuit_recovery_timeout,
            "log_level": self.log_level,
            "slots": [s.to_dict() for s in self.slots]
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BusConfig":
        """从字典创建"""
        slots_data = data.get("slots", [])
        slots = []
        for slot_data in slots_data:
            try:
                slots.append(SlotConfig.from_dict(slot_data))
            except ConfigurationException as e:
                logger.error(f"[BusConfig] 跳过无效槽位配置: {e.message}")
                continue

        return cls(
            default_timeout=data.get("default_timeout", 120),
            max_concurrent_requests=data.get("max_concurrent_requests", 100),
            enable_metrics=data.get("enable_metrics", True),
            enable_circuit_breaker=data.get("enable_circuit_breaker", True),
            circuit_failure_threshold=data.get("circuit_failure_threshold", 5),
            circuit_recovery_timeout=data.get("circuit_recovery_timeout", 60),
            log_level=data.get("log_level", "INFO"),
            slots=slots
        )


class ConfigLoader:
    """配置加载器"""

    @staticmethod
    def load_from_file(file_path: str | Path) -> BusConfig:
        """
        从文件加载配置

        Args:
            file_path: 配置文件路径

        Returns:
            BusConfig: 加载的配置

        Raises:
            ConfigurationException: 加载失败时抛出
        """
        file_path = Path(file_path)

        if not file_path.exists():
            error_msg = f"配置文件不存在: {file_path}"
            logger.error(f"[ConfigLoader] {error_msg}")
            raise ConfigurationException(error_msg, "file_path", str(file_path))

        try:
            with open(file_path, encoding="utf-8") as f:
                if file_path.suffix in [".yaml", ".yml"]:
                    data = yaml.safe_load(f)
                elif file_path.suffix == ".json":
                    data = json.load(f)
                else:
                    error_msg = f"不支持的配置文件格式: {file_path.suffix}"
                    logger.error(f"[ConfigLoader] {error_msg}")
                    raise ConfigurationException(error_msg, "file_path", str(file_path))

            config = BusConfig.from_dict(data)
            logger.info(f"[ConfigLoader] 配置加载成功: {file_path}")
            return config

        except Exception as e:
            error_msg = f"配置文件解析失败: {e}"
            logger.error(f"[ConfigLoader] {error_msg}")
            raise ConfigurationException(error_msg, "file_path", str(file_path)) from e

    @staticmethod
    def save_to_file(config: BusConfig, file_path: str | Path):
        """
        保存配置到文件

        Args:
            config: 要保存的配置
            file_path: 目标文件路径

        Raises:
            ConfigurationException: 保存失败时抛出
        """
        file_path = Path(file_path)

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)

            with open(file_path, "w", encoding="utf-8") as f:
                if file_path.suffix in [".yaml", ".yml"]:
                    yaml.dump(config.to_dict(), f, allow_unicode=True, default_flow_style=False)
                elif file_path.suffix == ".json":
                    json.dump(config.to_dict(), f, indent=2, ensure_ascii=False)
                else:
                    error_msg = f"不支持的配置文件格式: {file_path.suffix}"
                    logger.error(f"[ConfigLoader] {error_msg}")
                    raise ConfigurationException(error_msg, "file_path", str(file_path))

            logger.info(f"[ConfigLoader] 配置保存成功: {file_path}")

        except Exception as e:
            error_msg = f"配置保存失败: {e}"
            logger.error(f"[ConfigLoader] {error_msg}")
            raise ConfigurationException(error_msg, "file_path", str(file_path)) from e
