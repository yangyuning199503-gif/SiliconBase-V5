"""
ModelBus配置验证模块

提供配置验证和数据校验功能
"""

import logging
import re
from collections.abc import Callable
from typing import Any

from .base import ModelConfig, ModelType
from .config import SlotConfig
from .exceptions import ValidationException

logger = logging.getLogger(__name__)


class FieldValidator:
    """字段验证器"""

    @staticmethod
    def validate_required(value: Any, field_name: str) -> None:
        """验证必填字段"""
        if value is None or (isinstance(value, str) and not value.strip()):
            error_msg = f"字段 '{field_name}' 为必填项"
            logger.error(f"[FieldValidator] 验证失败: {error_msg}")
            raise ValidationException(error_msg, field_name, value)

    @staticmethod
    def validate_string(value: Any, field_name: str, min_length: int = 1, max_length: int | None = None) -> str:
        """验证字符串"""
        if not isinstance(value, str):
            error_msg = f"字段 '{field_name}' 必须是字符串类型"
            logger.error(f"[FieldValidator] 验证失败: {error_msg}, 实际类型: {type(value).__name__}")
            raise ValidationException(error_msg, field_name, value)

        if len(value) < min_length:
            error_msg = f"字段 '{field_name}' 长度不能小于 {min_length}"
            logger.error(f"[FieldValidator] 验证失败: {error_msg}")
            raise ValidationException(error_msg, field_name, value)

        if max_length is not None and len(value) > max_length:
            error_msg = f"字段 '{field_name}' 长度不能大于 {max_length}"
            logger.error(f"[FieldValidator] 验证失败: {error_msg}")
            raise ValidationException(error_msg, field_name, value)

        return value

    @staticmethod
    def validate_int(
        value: Any,
        field_name: str,
        min_value: int | None = None,
        max_value: int | None = None
    ) -> int:
        """验证整数"""
        if not isinstance(value, int) or isinstance(value, bool):
            error_msg = f"字段 '{field_name}' 必须是整数类型"
            logger.error(f"[FieldValidator] 验证失败: {error_msg}, 实际类型: {type(value).__name__}")
            raise ValidationException(error_msg, field_name, value)

        if min_value is not None and value < min_value:
            error_msg = f"字段 '{field_name}' 不能小于 {min_value}"
            logger.error(f"[FieldValidator] 验证失败: {error_msg}")
            raise ValidationException(error_msg, field_name, value)

        if max_value is not None and value > max_value:
            error_msg = f"字段 '{field_name}' 不能大于 {max_value}"
            logger.error(f"[FieldValidator] 验证失败: {error_msg}")
            raise ValidationException(error_msg, field_name, value)

        return value

    @staticmethod
    def validate_float(
        value: Any,
        field_name: str,
        min_value: float | None = None,
        max_value: float | None = None
    ) -> float:
        """验证浮点数"""
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            error_msg = f"字段 '{field_name}' 必须是数字类型"
            logger.error(f"[FieldValidator] 验证失败: {error_msg}, 实际类型: {type(value).__name__}")
            raise ValidationException(error_msg, field_name, value)

        value = float(value)

        if min_value is not None and value < min_value:
            error_msg = f"字段 '{field_name}' 不能小于 {min_value}"
            logger.error(f"[FieldValidator] 验证失败: {error_msg}")
            raise ValidationException(error_msg, field_name, value)

        if max_value is not None and value > max_value:
            error_msg = f"字段 '{field_name}' 不能大于 {max_value}"
            logger.error(f"[FieldValidator] 验证失败: {error_msg}")
            raise ValidationException(error_msg, field_name, value)

        return value

    @staticmethod
    def validate_url(value: str | None, field_name: str, required: bool = False) -> str | None:
        """验证URL"""
        if value is None or value == "":
            if required:
                error_msg = f"字段 '{field_name}' 为必填项"
                logger.error(f"[FieldValidator] 验证失败: {error_msg}")
                raise ValidationException(error_msg, field_name, value)
            return None

        # 简单的URL验证模式
        url_pattern = re.compile(
            r'^https?://'  # http:// or https://
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain
            r'localhost|'  # localhost
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ip
            r'(?::\d+)?'  # optional port
            r'(?:/?|[/?]\S+)$', re.IGNORECASE)

        if not url_pattern.match(value):
            error_msg = f"字段 '{field_name}' 必须是有效的URL格式"
            logger.error(f"[FieldValidator] 验证失败: {error_msg}, 值: {value}")
            raise ValidationException(error_msg, field_name, value)

        return value

    @staticmethod
    def validate_enum(value: Any, field_name: str, enum_class: type[ModelType]) -> Any:
        """验证枚举值"""
        if isinstance(value, enum_class):
            return value

        if isinstance(value, str):
            try:
                return enum_class[value.upper()]
            except KeyError as _exc:
                valid_values = [e.name for e in enum_class]
                error_msg = f"字段 '{field_name}' 必须是以下值之一: {valid_values}"
                logger.error(f"[FieldValidator] 验证失败: {error_msg}, 值: {value}")
                raise ValidationException(error_msg, field_name, value) from _exc

        error_msg = f"字段 '{field_name}' 类型无效"
        logger.error(f"[FieldValidator] 验证失败: {error_msg}, 类型: {type(value).__name__}")
        raise ValidationException(error_msg, field_name, value)

    @staticmethod
    def validate_list(value: Any, field_name: str, item_validator: Callable | None = None) -> list:
        """验证列表"""
        if not isinstance(value, list):
            error_msg = f"字段 '{field_name}' 必须是列表类型"
            logger.error(f"[FieldValidator] 验证失败: {error_msg}, 类型: {type(value).__name__}")
            raise ValidationException(error_msg, field_name, value)

        if item_validator:
            validated_items = []
            for i, item in enumerate(value):
                try:
                    validated_items.append(item_validator(item))
                except ValidationException as e:
                    error_msg = f"字段 '{field_name}[{i}]' 验证失败: {e.message}"
                    logger.error(f"[FieldValidator] {error_msg}")
                    raise ValidationException(error_msg, f"{field_name}[{i}]", item) from e
            return validated_items

        return value


class ConfigValidator:
    """配置验证器"""

    @staticmethod
    def validate_model_config(config: ModelConfig) -> None:
        """验证模型配置"""
        logger.debug(f"[ConfigValidator] 验证ModelConfig: provider={config.provider}")

        # 验证必填字段
        FieldValidator.validate_required(config.provider, "provider")
        FieldValidator.validate_string(config.provider, "provider", min_length=1, max_length=100)

        FieldValidator.validate_required(config.model_name, "model_name")
        FieldValidator.validate_string(config.model_name, "model_name", min_length=1, max_length=200)

        # 验证数值字段
        FieldValidator.validate_int(config.timeout, "timeout", min_value=1, max_value=3600)
        FieldValidator.validate_int(config.max_retries, "max_retries", min_value=0, max_value=10)

        # 验证URL（如果提供）
        if config.base_url:
            FieldValidator.validate_url(config.base_url, "base_url")

        logger.debug("[ConfigValidator] ModelConfig验证通过")

    @staticmethod
    def validate_slot_config(config: SlotConfig) -> None:
        """验证槽位配置"""
        logger.debug(f"[ConfigValidator] 验证SlotConfig: slot_id={config.slot_id}")

        # 验证必填字段
        FieldValidator.validate_required(config.slot_id, "slot_id")
        FieldValidator.validate_string(config.slot_id, "slot_id", min_length=1, max_length=100)

        FieldValidator.validate_required(config.provider_type, "provider_type")
        FieldValidator.validate_string(config.provider_type, "provider_type", min_length=1, max_length=100)

        FieldValidator.validate_required(config.model_name, "model_name")
        FieldValidator.validate_string(config.model_name, "model_name", min_length=1, max_length=200)

        # 验证model_type
        FieldValidator.validate_enum(config.model_type, "model_type", ModelType)

        # 验证数值字段
        FieldValidator.validate_int(config.timeout, "timeout", min_value=1, max_value=3600)
        FieldValidator.validate_int(config.max_retries, "max_retries", min_value=0, max_value=10)
        FieldValidator.validate_int(config.priority, "priority", min_value=0, max_value=1000)

        # 验证URL
        if config.base_url:
            FieldValidator.validate_url(config.base_url, "base_url")

        # 验证fallback_slots
        if config.fallback_slots:
            FieldValidator.validate_list(
                config.fallback_slots,
                "fallback_slots",
                lambda x: FieldValidator.validate_string(x, "fallback_slot_id", min_length=1)
            )

        logger.debug("[ConfigValidator] SlotConfig验证通过")

    @staticmethod
    def validate_slot_id(slot_id: str) -> None:
        """验证槽位ID格式"""
        FieldValidator.validate_required(slot_id, "slot_id")
        FieldValidator.validate_string(slot_id, "slot_id", min_length=1, max_length=100)

        # 检查槽位ID格式（只允许字母、数字、下划线和连字符）
        if not re.match(r'^[a-zA-Z0-9_-]+$', slot_id):
            error_msg = f"槽位ID只能包含字母、数字、下划线和连字符: {slot_id}"
            logger.error(f"[ConfigValidator] 验证失败: {error_msg}")
            raise ValidationException(error_msg, "slot_id", slot_id)

    @staticmethod
    def validate_provider_type(provider_type: str) -> None:
        """验证Provider类型"""
        FieldValidator.validate_required(provider_type, "provider_type")
        FieldValidator.validate_string(provider_type, "provider_type", min_length=1, max_length=100)


class InputValidator:
    """输入验证器"""

    @staticmethod
    def validate_invoke_input(input_data: Any) -> None:
        """验证调用输入数据"""
        if input_data is None:
            error_msg = "调用输入数据不能为None"
            logger.error(f"[InputValidator] 验证失败: {error_msg}")
            raise ValidationException(error_msg, "input_data")

        if isinstance(input_data, str):
            if not input_data.strip():
                error_msg = "调用输入字符串不能为空"
                logger.error(f"[InputValidator] 验证失败: {error_msg}")
                raise ValidationException(error_msg, "input_data")
        elif isinstance(input_data, dict):
            if not input_data:
                error_msg = "调用输入字典不能为空"
                logger.error(f"[InputValidator] 验证失败: {error_msg}")
                raise ValidationException(error_msg, "input_data")
        elif isinstance(input_data, list):
            if not input_data:
                error_msg = "调用输入列表不能为空"
                logger.error(f"[InputValidator] 验证失败: {error_msg}")
                raise ValidationException(error_msg, "input_data")
        else:
            error_msg = f"不支持的输入类型: {type(input_data).__name__}"
            logger.error(f"[InputValidator] 验证失败: {error_msg}")
            raise ValidationException(error_msg, "input_data", input_data)
