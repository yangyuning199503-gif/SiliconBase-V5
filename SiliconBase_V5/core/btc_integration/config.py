#!/usr/bin/env python3
"""
BTC 交易配置管理

设计原则:
    1. 复用 btc_system_v1 的 YAML 配置
    2. 提供统一的 Python 接口
    3. 支持环境变量覆盖
    4. 配置变更热加载
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class BTCTradingConfig:
    """
    BTC 交易配置类

    属性:
        btc_system_path: btc_system_v1 的根目录
        exchange: 交易所 (okx/binance)
        demo_mode: 是否为模拟盘
        symbols: 交易的代币列表
        api_key: API Key（从环境变量读取）
        api_secret: API Secret（从环境变量读取）
        api_passphrase: API Passphrase（从环境变量读取）
        max_position_size: 最大仓位（USDT）
        max_leverage: 最大杠杆
        stop_loss_pct: 止损百分比
        risk_per_trade: 单笔交易风险
    """

    # 路径配置
    btc_system_path: str = "F:/btc_system_v1"

    # 交易所配置
    exchange: str = "okx"
    demo_mode: bool = True

    # 交易标的
    symbols: list[str] = field(default_factory=lambda: ["BTC", "ETH", "SOL"])

    # API 配置（默认从环境变量读取）
    api_key: str = ""
    api_secret: str = ""
    api_passphrase: str = ""

    # 风控配置
    max_position_size: float = 1000.0  # USDT
    max_leverage: int = 5
    stop_loss_pct: float = 3.0  # 3%
    take_profit_pct: float = 6.0  # 6%
    risk_per_trade: float = 1.0  # 账户的 1%
    max_daily_loss: float = 5.0  # 账户的 5%

    # 策略配置
    default_strategy: str = "stage46_aggressive"
    strategies: list[str] = field(default_factory=lambda: [
        "stage46_aggressive",      # 趋势跟踪
        "stage64_mean_reversion",  # 均值回归
        "stage138_anchor",         # 支撑阻力
    ])

    # 运行配置
    runtime_dir: str = ".runtime"
    log_level: str = "INFO"

    def __post_init__(self):
        """初始化后处理：从环境变量加载 API Key"""
        self._load_from_env()
        self._validate()

    def _load_from_env(self):
        """从环境变量加载敏感配置"""
        prefix = "OKX_" if not self.demo_mode else "OKX_DEMO_"

        self.api_key = os.environ.get(f"{prefix}API_KEY", self.api_key)
        self.api_secret = os.environ.get(f"{prefix}API_SECRET", self.api_secret)
        self.api_passphrase = os.environ.get(f"{prefix}API_PASSPHRASE", self.api_passphrase)

    def _validate(self):
        """验证配置有效性"""
        # 验证路径
        btc_path = Path(self.btc_system_path)
        if not btc_path.exists():
            raise ValueError(f"btc_system 路径不存在: {self.btc_system_path}")

        # 验证交易所
        valid_exchanges = ["okx", "binance"]
        if self.exchange not in valid_exchanges:
            raise ValueError(f"不支持的交易所: {self.exchange}")

        # 验证风控参数
        if self.max_leverage > 20:
            raise ValueError("杠杆倍数不能超过 20x")

        if self.stop_loss_pct <= 0 or self.stop_loss_pct > 50:
            raise ValueError("止损百分比必须在 0-50% 之间")

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "btc_system_path": self.btc_system_path,
            "exchange": self.exchange,
            "demo_mode": self.demo_mode,
            "symbols": self.symbols,
            "max_position_size": self.max_position_size,
            "max_leverage": self.max_leverage,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "risk_per_trade": self.risk_per_trade,
            "max_daily_loss": self.max_daily_loss,
            "default_strategy": self.default_strategy,
            "strategies": self.strategies,
            "log_level": self.log_level,
            # API Key 不导出到字典（安全）
            "api_configured": bool(self.api_key and self.api_secret)
        }

    @classmethod
    def from_btc_system_yaml(cls, yaml_path: str | None = None) -> "BTCTradingConfig":
        """
        从 btc_system 的 YAML 配置加载

        Args:
            yaml_path: shadow.yml 的路径，默认使用 btc_system_path/shadow.yml

        Returns:
            BTCTradingConfig 实例
        """
        if yaml_path is None:
            yaml_path = "F:/btc_system_v1/shadow.yml"

        yaml_file = Path(yaml_path)
        if not yaml_file.exists():
            # 返回默认配置
            return cls()

        with open(yaml_file, encoding='utf-8') as f:
            btc_config = yaml.safe_load(f) or {}

        shadow = btc_config.get("shadow", {})

        # 提取配置
        config = cls(
            btc_system_path=str(yaml_file.parent),
            exchange=shadow.get("exchange", "okx"),
            demo_mode=shadow.get("demo", True),
            symbols=list(shadow.get("contracts", {}).keys()) or ["BTC", "ETH"],
            max_leverage=shadow.get("account", {}).get("leverage", 5),
        )

        return config

    def is_api_configured(self) -> bool:
        """检查是否配置了 API Key"""
        return bool(self.api_key and self.api_secret)

    def get_symbol_contract(self, symbol: str) -> str:
        """获取交易对的合约名称"""
        symbol = symbol.upper()
        if self.exchange == "okx":
            return f"{symbol}-USDT-SWAP"
        elif self.exchange == "binance":
            return f"{symbol}USDT"
        return f"{symbol}-USDT"


# 全局配置实例
_btc_config: BTCTradingConfig | None = None


def get_btc_config() -> BTCTradingConfig:
    """
    获取 BTC 配置单例

    Returns:
        BTCTradingConfig 实例
    """
    global _btc_config
    if _btc_config is None:
        try:
            _btc_config = BTCTradingConfig.from_btc_system_yaml()
        except Exception:
            _btc_config = BTCTradingConfig()
    return _btc_config


def reload_btc_config() -> BTCTradingConfig:
    """重新加载配置"""
    global _btc_config
    _btc_config = None
    return get_btc_config()
