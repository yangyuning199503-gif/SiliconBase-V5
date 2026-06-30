#!/usr/bin/env python3
"""
交易配置管理器 (TradingConfigManager)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
统一加载和管理三种交易模式的配置

支持:
- 全自动量化配置 (auto)
- AI辅助交易配置 (ai)
- 手动交易配置 (manual)

特性:
- 单例模式
- 用户隔离
- 配置验证
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from core.config import config as core_config
from core.logger import logger


class TradingMode(str, Enum):
    """交易模式枚举"""
    AUTO = "auto"
    AI = "ai"
    MANUAL = "manual"


class RiskProfile(str, Enum):
    """风险偏好枚举"""
    CONSERVATIVE = "conservative"  # 保守
    MODERATE = "moderate"          # 稳健
    AGGRESSIVE = "aggressive"      # 激进


@dataclass
class AutoTradingConfig:
    """全自动量化配置"""
    enabled: bool = True
    config_path_template: str = "config/trading/{user_id}/shadow.yml"
    runtime_dir_template: str = "core/btc_integration/engine/.runtime/{user_id}"
    default_strategy: str = "stage46_aggressive"
    default_symbols: list[str] = field(default_factory=lambda: ["BTC", "ETH"])
    default_leverage: int = 3
    demo_mode_default: bool = True

    def get_user_config_path(self, user_id: str) -> Path:
        """获取用户配置文件路径"""
        return Path(self.config_path_template.format(user_id=user_id))

    def get_user_runtime_dir(self, user_id: str) -> Path:
        """获取用户运行时目录"""
        return Path(self.runtime_dir_template.format(user_id=user_id))

    def validate(self, user_id: str) -> bool:
        """验证配置"""
        config_file = self.get_user_config_path(user_id)
        if not config_file.parent.exists():
            config_file.parent.mkdir(parents=True, exist_ok=True)
        return True


@dataclass
class AITradingConfig:
    """AI辅助交易配置"""
    enabled: bool = True
    ai_check_interval: int = 4  # AI检查间隔（周期数）
    default_symbols: list[str] = field(default_factory=lambda: ["BTC", "ETH"])
    default_risk_profile: RiskProfile = RiskProfile.MODERATE
    world_model_fallback: str = "hold"  # hold/allow/reduce
    world_model_threshold: float = 0.3
    auto_execute_default: bool = False  # 是否自动执行AI决策
    max_position_ratio: float = 0.5  # 最大持仓比例

    def validate(self) -> bool:
        """验证配置"""
        if self.ai_check_interval < 1:
            logger.warning("[AITradingConfig] ai_check_interval 必须 >= 1")
            return False
        if not 0 <= self.world_model_threshold <= 1:
            logger.warning("[AITradingConfig] world_model_threshold 必须在 0-1 之间")
            return False
        return True


@dataclass
class ManualTradingConfig:
    """手动交易配置"""
    enabled: bool = True
    websocket_port: int = 8602
    default_interval: str = "1h"
    supported_intervals: list[str] = field(default_factory=lambda: ["1m", "5m", "15m", "1h", "4h", "1d"])
    max_leverage: int = 100
    default_leverage: int = 1

    def validate(self) -> bool:
        """验证配置"""
        if self.default_interval not in self.supported_intervals:
            logger.warning(f"[ManualTradingConfig] default_interval {self.default_interval} 不支持")
            return False
        return True


@dataclass
class ExchangeConfig:
    """交易所配置"""
    okx_enabled: bool = True
    okx_testnet: bool = True
    binance_enabled: bool = False
    binance_testnet: bool = True
    default_exchange: str = "okx"


class TradingConfigManager:
    """
    交易配置管理器 - 单例

    统一管理三种交易模式的配置
    """

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if TradingConfigManager._initialized:
            return

        TradingConfigManager._initialized = True

        # 初始化配置对象
        self.auto_config = AutoTradingConfig()
        self.ai_config = AITradingConfig()
        self.manual_config = ManualTradingConfig()
        self.exchange_config = ExchangeConfig()

        # 配置缓存
        self._config_cache: dict[str, dict[str, Any]] = {}

        # 加载配置
        self._load_configs()

        logger.info("[TradingConfigManager] 配置加载完成")

    def _load_configs(self):
        """从主配置加载交易配置"""
        trading_cfg = core_config.get("trading", {})

        # 加载全自动量化配置
        auto_cfg = trading_cfg.get("auto", {})
        self.auto_config = AutoTradingConfig(
            enabled=auto_cfg.get("enabled", True),
            config_path_template=auto_cfg.get("config_path_template", "config/trading/{user_id}/shadow.yml"),
            runtime_dir_template=auto_cfg.get("runtime_dir_template", "core/btc_integration/engine/.runtime/{user_id}"),
            default_strategy=auto_cfg.get("default_strategy", "stage46_aggressive"),
            default_symbols=auto_cfg.get("default_symbols", ["BTC", "ETH"]),
            default_leverage=auto_cfg.get("default_leverage", 3),
            demo_mode_default=auto_cfg.get("demo_mode_default", True),
        )

        # 加载AI辅助配置
        ai_cfg = trading_cfg.get("ai", {})
        self.ai_config = AITradingConfig(
            enabled=ai_cfg.get("enabled", True),
            ai_check_interval=ai_cfg.get("ai_check_interval", 4),
            default_symbols=ai_cfg.get("default_symbols", ["BTC", "ETH"]),
            default_risk_profile=RiskProfile(ai_cfg.get("default_risk_profile", "moderate")),
            world_model_fallback=ai_cfg.get("world_model_fallback", "hold"),
            world_model_threshold=ai_cfg.get("world_model_threshold", 0.3),
            auto_execute_default=ai_cfg.get("auto_execute_default", False),
            max_position_ratio=ai_cfg.get("max_position_ratio", 0.5),
        )

        # 加载手动交易配置
        manual_cfg = trading_cfg.get("manual", {})
        self.manual_config = ManualTradingConfig(
            enabled=manual_cfg.get("enabled", True),
            websocket_port=manual_cfg.get("websocket_port", 8602),
            default_interval=manual_cfg.get("default_interval", "1h"),
            supported_intervals=manual_cfg.get("supported_intervals", ["1m", "5m", "15m", "1h", "4h", "1d"]),
            max_leverage=manual_cfg.get("max_leverage", 100),
            default_leverage=manual_cfg.get("default_leverage", 1),
        )

        # 加载交易所配置
        exchanges_cfg = trading_cfg.get("exchanges", {})
        okx_cfg = exchanges_cfg.get("okx", {})
        binance_cfg = exchanges_cfg.get("binance", {})
        self.exchange_config = ExchangeConfig(
            okx_enabled=okx_cfg.get("enabled", True),
            okx_testnet=okx_cfg.get("testnet", True),
            binance_enabled=binance_cfg.get("enabled", False),
            binance_testnet=binance_cfg.get("testnet", True),
            default_exchange=exchanges_cfg.get("default", "okx"),
        )

    def get_mode_config(self, mode: TradingMode) -> Any:
        """获取指定模式的配置"""
        if mode == TradingMode.AUTO:
            return self.auto_config
        elif mode == TradingMode.AI:
            return self.ai_config
        elif mode == TradingMode.MANUAL:
            return self.manual_config
        else:
            raise ValueError(f"未知的交易模式: {mode}")

    def get_user_config(self, user_id: str, mode: TradingMode) -> dict[str, Any]:
        """
        获取用户特定模式的配置

        优先从用户配置文件读取，如果不存在则使用默认配置
        """
        cache_key = f"{user_id}_{mode.value}"

        if cache_key in self._config_cache:
            return self._config_cache[cache_key]

        # 构建用户配置文件路径
        user_config_dir = Path(f"config/trading/{user_id}")
        user_config_file = user_config_dir / f"{mode.value}_config.yml"

        config_data = {}

        # 如果用户配置文件存在，加载它
        if user_config_file.exists():
            try:
                with open(user_config_file, encoding='utf-8') as f:
                    config_data = yaml.safe_load(f) or {}
                logger.info(f"[TradingConfigManager] 加载用户 {user_id} {mode.value} 配置")
            except Exception as e:
                logger.warning(f"[TradingConfigManager] 加载用户配置失败: {e}")

        # 合并默认配置
        if mode == TradingMode.AUTO:
            default_config = {
                "enabled": self.auto_config.enabled,
                "strategy": self.auto_config.default_strategy,
                "symbols": self.auto_config.default_symbols,
                "leverage": self.auto_config.default_leverage,
                "demo_mode": self.auto_config.demo_mode_default,
            }
        elif mode == TradingMode.AI:
            default_config = {
                "enabled": self.ai_config.enabled,
                "symbols": self.ai_config.default_symbols,
                "ai_check_interval": self.ai_config.ai_check_interval,
                "risk_profile": self.ai_config.default_risk_profile.value,
                "world_model_fallback": self.ai_config.world_model_fallback,
                "world_model_threshold": self.ai_config.world_model_threshold,
                "auto_execute": self.ai_config.auto_execute_default,
            }
        elif mode == TradingMode.MANUAL:
            default_config = {
                "enabled": self.manual_config.enabled,
                "interval": self.manual_config.default_interval,
                "leverage": self.manual_config.default_leverage,
            }
        else:
            default_config = {}

        # 用户配置覆盖默认配置
        merged_config = {**default_config, **config_data}

        # 缓存配置
        self._config_cache[cache_key] = merged_config

        return merged_config

    def save_user_config(self, user_id: str, mode: TradingMode, config_data: dict[str, Any]) -> bool:
        """
        保存用户特定模式的配置
        """
        try:
            user_config_dir = Path(f"config/trading/{user_id}")
            user_config_dir.mkdir(parents=True, exist_ok=True)

            user_config_file = user_config_dir / f"{mode.value}_config.yml"

            with open(user_config_file, 'w', encoding='utf-8') as f:
                yaml.dump(config_data, f, allow_unicode=True, default_flow_style=False)

            # 清除缓存
            cache_key = f"{user_id}_{mode.value}"
            if cache_key in self._config_cache:
                del self._config_cache[cache_key]

            logger.info(f"[TradingConfigManager] 保存用户 {user_id} {mode.value} 配置")
            return True

        except Exception as e:
            logger.error(f"[TradingConfigManager] 保存用户配置失败: {e}")
            return False

    def clear_cache(self, user_id: str | None = None):
        """
        清除配置缓存

        Args:
            user_id: 如果指定，只清除该用户的缓存；否则清除所有缓存
        """
        if user_id:
            keys_to_remove = [k for k in self._config_cache if k.startswith(f"{user_id}_")]
            for key in keys_to_remove:
                del self._config_cache[key]
        else:
            self._config_cache.clear()

    def validate_all(self) -> bool:
        """验证所有配置"""
        valid = True

        if not self.ai_config.validate():
            valid = False

        if not self.manual_config.validate():
            valid = False

        return valid


# 全局管理器实例
_trading_config_manager: TradingConfigManager | None = None


def get_trading_config_manager() -> TradingConfigManager:
    """获取交易配置管理器实例（懒加载）"""
    global _trading_config_manager
    if _trading_config_manager is None:
        _trading_config_manager = TradingConfigManager()
    return _trading_config_manager


# 便捷函数
def get_auto_trading_config() -> AutoTradingConfig:
    """获取全自动量化配置"""
    return get_trading_config_manager().auto_config


def get_ai_trading_config() -> AITradingConfig:
    """获取AI辅助交易配置"""
    return get_trading_config_manager().ai_config


def get_manual_trading_config() -> ManualTradingConfig:
    """获取手动交易配置"""
    return get_trading_config_manager().manual_config


def get_user_trading_config(user_id: str, mode: TradingMode) -> dict[str, Any]:
    """获取用户交易配置"""
    return get_trading_config_manager().get_user_config(user_id, mode)
