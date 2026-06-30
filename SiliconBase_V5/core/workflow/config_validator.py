"""
子代理配置验证器

提供配置验证、环境变量覆盖和热重载支持
"""

import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ValidationRule:
    """配置验证规则"""
    key: str
    expected_type: type
    default: Any
    min_value: int | float | None = None
    max_value: int | float | None = None
    allowed_values: list[Any] | None = None


class SubAgentConfigValidator:
    """
    子代理配置验证器

    功能：
    1. 验证配置项的类型和范围
    2. 支持环境变量覆盖（如 SILICONBASE_WORKFLOW__SUBAGENT__EXECUTION__TIMEOUT）
    3. 提供默认值
    4. 支持热重载
    """

    # 环境变量前缀
    ENV_PREFIX = "SILICONBASE_"

    # 验证规则定义
    VALIDATION_RULES: list[ValidationRule] = [
        # 执行控制
        ValidationRule(
            key="workflow.subagent.execution.timeout",
            expected_type=int,
            default=300,
            min_value=10,
            max_value=3600
        ),
        ValidationRule(
            key="workflow.subagent.execution.max_retries",
            expected_type=int,
            default=2,
            min_value=0,
            max_value=5
        ),
        ValidationRule(
            key="workflow.subagent.execution.retry_delay",
            expected_type=int,
            default=5,
            min_value=1,
            max_value=300
        ),
        # 流式输出控制
        ValidationRule(
            key="workflow.subagent.streaming.enabled",
            expected_type=bool,
            default=True
        ),
        ValidationRule(
            key="workflow.subagent.streaming.buffer_size",
            expected_type=int,
            default=10,
            min_value=1,
            max_value=1000
        ),
        ValidationRule(
            key="workflow.subagent.streaming.heartbeat_interval",
            expected_type=int,
            default=5,
            min_value=1,
            max_value=300
        ),
        # AI自动验收
        ValidationRule(
            key="workflow.subagent.verification.enabled",
            expected_type=bool,
            default=True
        ),
        ValidationRule(
            key="workflow.subagent.verification.ai_confidence_threshold",
            expected_type=float,
            default=0.9,
            min_value=0.0,
            max_value=1.0
        ),
        ValidationRule(
            key="workflow.subagent.verification.human_review_threshold",
            expected_type=float,
            default=0.7,
            min_value=0.0,
            max_value=1.0
        ),
        ValidationRule(
            key="workflow.subagent.verification.max_verification_time",
            expected_type=int,
            default=60,
            min_value=10,
            max_value=600
        ),
        # 上下文搬运
        ValidationRule(
            key="workflow.subagent.context.memory_query_limit",
            expected_type=int,
            default=5,
            min_value=1,
            max_value=50
        ),
        ValidationRule(
            key="workflow.subagent.context.memory_min_importance",
            expected_type=float,
            default=0.5,
            min_value=0.0,
            max_value=1.0
        ),
        ValidationRule(
            key="workflow.subagent.context.perception_on_critical",
            expected_type=bool,
            default=True
        ),
        ValidationRule(
            key="workflow.subagent.context.history_patterns_limit",
            expected_type=int,
            default=3,
            min_value=1,
            max_value=20
        ),
        # 检查点增强
        ValidationRule(
            key="workflow.subagent.checkpoint.save_memory_anchors",
            expected_type=bool,
            default=True
        ),
        ValidationRule(
            key="workflow.subagent.checkpoint.save_perception_history",
            expected_type=bool,
            default=True
        ),
        ValidationRule(
            key="workflow.subagent.checkpoint.related_memories_limit",
            expected_type=int,
            default=5,
            min_value=1,
            max_value=50
        ),
    ]

    def __init__(self, config_loader: Any | None = None):
        """
        初始化验证器

        Args:
            config_loader: 配置加载器，如果为None则使用系统默认
        """
        self._config_loader = config_loader
        self._cached_config: dict[str, Any] | None = None
        self._last_env_hash: str | None = None

    def _get_env_key(self, config_key: str) -> str:
        """
        将配置键转换为环境变量键

        Args:
            config_key: 配置键，如 "workflow.subagent.execution.timeout"

        Returns:
            环境变量键，如 "SILICONBASE_WORKFLOW__SUBAGENT__EXECUTION__TIMEOUT"
        """
        # 将点分隔的键转换为双下划线分隔
        env_key = config_key.replace(".", "__").upper()
        return f"{self.ENV_PREFIX}{env_key}"

    def _parse_env_value(self, value: str, expected_type: type) -> Any:
        """
        解析环境变量值为正确的类型

        Args:
            value: 环境变量值
            expected_type: 期望的类型

        Returns:
            转换后的值
        """
        if expected_type is bool:
            # 处理布尔值
            if value.lower() in ('true', '1', 'yes', 'on', 'enabled'):
                return True
            elif value.lower() in ('false', '0', 'no', 'off', 'disabled'):
                return False
            else:
                raise ValueError(f"无法解析布尔值: {value}")
        elif expected_type is int:
            return int(value)
        elif expected_type is float:
            return float(value)
        elif expected_type is str:
            return value
        else:
            return value

    def _check_env_override(self, key: str, expected_type: type, default: Any) -> Any:
        """
        检查并获取环境变量覆盖值

        Args:
            key: 配置键
            expected_type: 期望的类型
            default: 默认值

        Returns:
            环境变量值或默认值
        """
        env_key = self._get_env_key(key)
        env_value = os.getenv(env_key)

        if env_value is not None:
            try:
                parsed = self._parse_env_value(env_value, expected_type)
                logger.debug(f"环境变量覆盖: {key} = {parsed} (来自 {env_key})")
                return parsed
            except (ValueError, TypeError) as e:
                logger.warning(f"环境变量 {env_key} 值无效: {env_value}, 使用默认值. 错误: {e}")
                return default

        return default

    def _get_nested_value(self, config: dict[str, Any], key: str) -> Any:
        """
        从嵌套字典中获取值

        Args:
            config: 配置字典
            key: 点分隔的键

        Returns:
            配置值，如果不存在返回None
        """
        parts = key.split(".")
        current = config

        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None

        return current

    def _compute_env_hash(self) -> str:
        """
        计算环境变量哈希（用于检测变化）

        Returns:
            环境变量哈希值
        """
        env_vars = []
        for rule in self.VALIDATION_RULES:
            env_key = self._get_env_key(rule.key)
            value = os.getenv(env_key)
            if value is not None:
                env_vars.append(f"{env_key}={value}")
        return str(hash(tuple(sorted(env_vars))))

    def needs_reload(self) -> bool:
        """
        检查是否需要重新加载配置（热重载检测）

        Returns:
            如果环境变量变化返回True
        """
        current_hash = self._compute_env_hash()
        return current_hash != self._last_env_hash

    def validate(
        self,
        config: dict[str, Any] | None = None,
        apply_defaults: bool = True
    ) -> tuple[bool, list[str], dict[str, Any]]:
        """
        验证配置

        Args:
            config: 配置字典，如果为None则使用默认配置
            apply_defaults: 是否应用默认值填充缺失项

        Returns:
            (是否有效, 错误列表, 处理后的配置)
        """
        errors: list[str] = []
        result_config: dict[str, Any] = {}

        if config is None:
            config = {}

        for rule in self.VALIDATION_RULES:
            # 1. 尝试从配置获取
            value = self._get_nested_value(config, rule.key)

            # 2. 尝试环境变量覆盖
            env_value = self._check_env_override(rule.key, rule.expected_type, rule.default)
            if env_value != rule.default:  # 环境变量有覆盖
                value = env_value

            # 3. 如果没有值，使用默认值
            if value is None:
                if apply_defaults:
                    value = rule.default
                else:
                    errors.append(f"缺少必需配置项: {rule.key}")
                    continue

            # 4. 类型检查
            if not isinstance(value, rule.expected_type):
                # 尝试类型转换
                try:
                    if rule.expected_type is bool:
                        value = value.lower() in ('true', '1', 'yes', 'on') if isinstance(value, str) else bool(value)
                    elif rule.expected_type is int:
                        value = int(value)
                    elif rule.expected_type is float:
                        value = float(value)
                    else:
                        errors.append(
                            f"{rule.key} 类型错误，期望 {rule.expected_type.__name__}，"
                            f"实际 {type(value).__name__}"
                        )
                        continue
                except (ValueError, TypeError):
                    errors.append(
                        f"{rule.key} 类型错误，期望 {rule.expected_type.__name__}，"
                        f"实际 {type(value).__name__}"
                    )
                    continue

            # 5. 范围检查
            if rule.min_value is not None and value < rule.min_value:
                errors.append(f"{rule.key} ({value}) 不能小于 {rule.min_value}")
                continue
            if rule.max_value is not None and value > rule.max_value:
                errors.append(f"{rule.key} ({value}) 不能大于 {rule.max_value}")
                continue

            # 6. 允许值检查
            if rule.allowed_values is not None and value not in rule.allowed_values:
                errors.append(
                    f"{rule.key} ({value}) 不在允许值列表中: {rule.allowed_values}"
                )
                continue

            # 7. 构建结果配置
            self._set_nested_value(result_config, rule.key, value)

        # 更新缓存
        self._cached_config = result_config
        self._last_env_hash = self._compute_env_hash()

        is_valid = len(errors) == 0
        return is_valid, errors, result_config

    def _set_nested_value(self, config: dict[str, Any], key: str, value: Any) -> None:
        """
        在嵌套字典中设置值

        Args:
            config: 配置字典
            key: 点分隔的键
            value: 要设置的值
        """
        parts = key.split(".")
        current = config

        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]

        current[parts[-1]] = value

    def get_config(
        self,
        config: dict[str, Any] | None = None,
        force_reload: bool = False
    ) -> dict[str, Any]:
        """
        获取验证后的配置（支持热重载）

        Args:
            config: 原始配置字典
            force_reload: 强制重新加载

        Returns:
            验证后的配置字典
        """
        if force_reload or self.needs_reload() or self._cached_config is None:
            is_valid, errors, validated_config = self.validate(config)

            if not is_valid:
                logger.warning(f"配置验证失败: {errors}")
                # 返回包含默认值的配置
                _, _, validated_config = self.validate(None, apply_defaults=True)

            self._cached_config = validated_config
            self._last_env_hash = self._compute_env_hash()

        return self._cached_config.copy()

    def get_value(
        self,
        key: str,
        config: dict[str, Any] | None = None,
        default: Any = None
    ) -> Any:
        """
        获取单个配置值

        Args:
            key: 配置键
            config: 原始配置字典
            default: 如果未找到配置时的默认值

        Returns:
            配置值
        """
        validated_config = self.get_config(config)
        return self._get_nested_value(validated_config, key) or default

    @classmethod
    def get_all_defaults(cls) -> dict[str, Any]:
        """
        获取所有配置的默认值

        Returns:
            包含所有默认值的配置字典
        """
        defaults: dict[str, Any] = {}
        validator = cls()

        for rule in cls.VALIDATION_RULES:
            validator._set_nested_value(defaults, rule.key, rule.default)

        return defaults


# 便捷函数
def get_subagent_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    获取子代理配置

    Args:
        config: 原始配置字典

    Returns:
        验证后的配置字典
    """
    validator = SubAgentConfigValidator()
    return validator.get_config(config)


def validate_subagent_config(
    config: dict[str, Any] | None = None
) -> tuple[bool, list[str], dict[str, Any]]:
    """
    验证子代理配置

    Args:
        config: 配置字典

    Returns:
        (是否有效, 错误列表, 处理后的配置)
    """
    validator = SubAgentConfigValidator()
    return validator.validate(config)
