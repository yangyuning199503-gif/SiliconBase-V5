#!/usr/bin/env python3
"""
交易所配置管理
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
管理用户的交易所API配置，支持OKX和币安

特性:
- 配置加密存储
- 多交易所支持
- 模拟盘/实盘切换
- 配置验证

作者: SiliconBase Team
日期: 2026-04-09
"""

import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum

from core.config import config
from core.logger import logger

# 加密依赖
try:
    from cryptography.fernet import Fernet
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    logger.warning("[ExchangeConfig] 加密模块不可用，API Key将以明文存储")


class ExchangeType(str, Enum):
    """交易所类型"""
    OKX = "okx"
    BINANCE = "binance"


class TradingMode(str, Enum):
    """交易模式"""
    DEMO = "demo"      # 模拟盘
    LIVE = "live"      # 实盘


@dataclass
class ExchangeConfig:
    """交易所配置"""
    id: str                                  # 配置ID
    user_id: str                             # 用户ID
    exchange: ExchangeType                   # 交易所类型
    name: str                                # 配置名称（用户自定义）
    mode: TradingMode                        # 交易模式

    # API凭证（加密存储）
    api_key: str = ""
    api_secret: str = ""
    passphrase: str = ""                     # OKX需要

    # 额外配置
    base_url: str = ""                       # 自定义API地址（可选）
    testnet: bool = True                     # 是否使用测试网

    # 元数据
    is_active: bool = True                   # 是否启用
    is_validated: bool = False               # 是否已通过验证
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_used_at: float | None = None

    @property
    def exchange_type(self):
        """兼容 api_bridge.py 的属性别名"""
        return self.exchange

    @property
    def trading_mode(self):
        """兼容 api_bridge.py 的属性别名"""
        return self.mode

    def _get_exchange_str(self) -> str:
        """获取交易所字符串（兼容枚举和字符串）"""
        if isinstance(self.exchange, str):
            return self.exchange
        return self.exchange.value if hasattr(self.exchange, 'value') else str(self.exchange)

    def _get_mode_str(self) -> str:
        """获取交易模式字符串（兼容枚举和字符串）"""
        if isinstance(self.mode, str):
            return self.mode
        return self.mode.value if hasattr(self.mode, 'value') else str(self.mode)

    def to_dict(self, decrypt: bool = False) -> dict:
        """转换为字典"""
        data = asdict(self)
        # 兼容枚举和字符串
        data['exchange'] = self._get_exchange_str()
        data['mode'] = self._get_mode_str()
        # 敏感字段只在解密时返回
        if not decrypt:
            data['api_key'] = '***' if self.api_key else ''
            data['api_secret'] = '***' if self.api_secret else ''
            data['passphrase'] = '***' if self.passphrase else ''
        return data

    def to_safe_dict(self) -> dict:
        """转换为安全字典（不含敏感信息）"""
        return {
            'id': self.id,
            'name': self.name,
            'exchange': self._get_exchange_str(),
            'mode': self._get_mode_str(),
            'is_active': self.is_active,
            'is_validated': self.is_validated,
            'testnet': self.testnet,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }


class ConfigEncryption:
    """配置加密工具"""

    def __init__(self):
        self._cipher = None
        self._init_cipher()

    def _init_cipher(self):
        """初始化加密器"""
        if not CRYPTO_AVAILABLE:
            return

        try:
            # 使用环境变量或配置文件中的密钥
            secret_key = config.get("security.encryption_key", "")

            # 【P3修复】如果配置系统未返回密钥，尝试直接从环境变量读取（兼容多种命名）
            if not secret_key:
                import os
                secret_key = os.environ.get("SILICONBASE_SECURITY__ENCRYPTION_KEY", "")
            if not secret_key:
                import os
                secret_key = os.environ.get("SECURITY_ENCRYPTION_KEY", "")

            if not secret_key:
                raise RuntimeError(
                    "[ExchangeConfig] security.encryption_key 未配置。"
                    "请在 .env 中设置 SILICONBASE_SECURITY__ENCRYPTION_KEY 或 SECURITY_ENCRYPTION_KEY，"
                    "否则交易所配置将在重启后无法解密。"
                )
            logger.info("[ExchangeConfig] 使用固定加密密钥初始化")

            # 确保密钥格式正确
            if isinstance(secret_key, str):
                secret_key = secret_key.encode()

            self._cipher = Fernet(secret_key)

        except Exception as e:
            logger.error(f"[ExchangeConfig] 初始化加密器失败: {e}")
            self._cipher = None

    def encrypt(self, data: str) -> str:
        """加密数据"""
        if not CRYPTO_AVAILABLE or not self._cipher:
            raise RuntimeError("加密模块不可用，无法安全存储API密钥")

        try:
            encrypted = self._cipher.encrypt(data.encode())
            return f"enc:{encrypted.decode()}"
        except Exception as e:
            logger.error(f"[ExchangeConfig] 加密失败: {e}")
            raise RuntimeError(f"加密失败: {e}") from e

    def decrypt(self, data: str) -> str:
        """解密数据"""
        if not data:
            return ""

        if data.startswith("plain:"):
            return data[6:]

        if not CRYPTO_AVAILABLE or not self._cipher:
            logger.warning("[ExchangeConfig] 无法解密，加密模块不可用")
            return ""

        try:
            if data.startswith("enc:"):
                data = data[4:]
            decrypted = self._cipher.decrypt(data.encode())
            return decrypted.decode()
        except Exception as e:
            logger.error(f"[ExchangeConfig] 解密失败: {e}", exc_info=True)
            return ""


class ExchangeConfigManager:
    """
    交易所配置管理器

    负责用户交易所配置的CRUD操作
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # 存储: user_id -> list[ExchangeConfig]
        self._configs: dict[str, list[ExchangeConfig]] = {}

        # 加密工具
        self._encryption = ConfigEncryption()

        # 持久化路径
        self._storage_path = config.get("trading.config_storage_path", "data/exchange_configs.json")

        # 加载已有配置
        self._load_configs()

        logger.info("[ExchangeConfigManager] 初始化完成")

    def _load_configs(self):
        """从文件加载配置"""
        import os
        if not os.path.exists(self._storage_path):
            return

        try:
            with open(self._storage_path, encoding='utf-8') as f:
                data = json.load(f)

            decryption_failed = False
            for user_id, configs in data.items():
                self._configs[user_id] = []
                for cfg_data in configs:
                    original_api_key = cfg_data.get('api_key', '')
                    original_api_secret = cfg_data.get('api_secret', '')
                    original_passphrase = cfg_data.get('passphrase', '')

                    # 解密敏感字段
                    cfg_data['api_key'] = self._encryption.decrypt(original_api_key)
                    cfg_data['api_secret'] = self._encryption.decrypt(original_api_secret)
                    cfg_data['passphrase'] = self._encryption.decrypt(original_passphrase)

                    # 检测解密失败：原始为加密值但解密后为空
                    if (
                        (original_api_key.startswith("enc:") and not cfg_data['api_key'])
                        or (original_api_secret.startswith("enc:") and not cfg_data['api_secret'])
                        or (original_passphrase.startswith("enc:") and not cfg_data['passphrase'])
                    ):
                        decryption_failed = True

                    # 将字符串转换为枚举（dataclass 不会自动转换）
                    exchange_raw = cfg_data.get('exchange', 'okx')
                    if isinstance(exchange_raw, str):
                        try:
                            cfg_data['exchange'] = ExchangeType(exchange_raw)
                        except ValueError:
                            cfg_data['exchange'] = ExchangeType.OKX

                    mode_raw = cfg_data.get('mode', 'demo')
                    if isinstance(mode_raw, str):
                        try:
                            cfg_data['mode'] = TradingMode(mode_raw)
                        except ValueError:
                            cfg_data['mode'] = TradingMode.DEMO

                    config_obj = ExchangeConfig(**cfg_data)
                    self._configs[user_id].append(config_obj)

            logger.info(f"[ExchangeConfigManager] 已加载 {len(self._configs)} 个用户的配置")

            if decryption_failed:
                logger.warning(
                    "[ExchangeConfig] 已存储的交易所配置无法解密，可能是密钥已变更。"
                    "请通过前端重新配置交易所密钥。"
                )

        except Exception as e:
            logger.error(f"[ExchangeConfigManager] 加载配置失败: {e}")

    def _save_configs(self):
        """保存配置到文件"""
        import os
        try:
            os.makedirs(os.path.dirname(self._storage_path), exist_ok=True)

            data = {}
            for user_id, configs in self._configs.items():
                data[user_id] = []
                for cfg in configs:
                    cfg_dict = asdict(cfg)
                    # 加密敏感字段
                    cfg_dict['api_key'] = self._encryption.encrypt(cfg.api_key)
                    cfg_dict['api_secret'] = self._encryption.encrypt(cfg.api_secret)
                    cfg_dict['passphrase'] = self._encryption.encrypt(cfg.passphrase)
                    data[user_id].append(cfg_dict)

            with open(self._storage_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            logger.debug("[ExchangeConfigManager] 配置已保存")

        except Exception as e:
            logger.error(f"[ExchangeConfigManager] 保存配置失败: {e}")

    def create_config(
        self,
        user_id: str,
        exchange: ExchangeType,
        name: str,
        mode: TradingMode,
        api_key: str,
        api_secret: str,
        passphrase: str = "",
        **kwargs
    ) -> ExchangeConfig:
        """创建新配置"""
        import uuid

        config_id = str(uuid.uuid4())[:8]

        cfg = ExchangeConfig(
            id=config_id,
            user_id=user_id,
            exchange=exchange,
            name=name,
            mode=mode,
            api_key=api_key,
            api_secret=api_secret,
            passphrase=passphrase,
            **kwargs
        )

        if user_id not in self._configs:
            self._configs[user_id] = []

        self._configs[user_id].append(cfg)
        self._save_configs()

        logger.info(f"[ExchangeConfigManager] [user={user_id}] 创建配置: {name} ({exchange.value})")
        return cfg

    def update_config(
        self,
        user_id: str,
        config_id: str,
        **updates
    ) -> ExchangeConfig | None:
        """更新配置"""
        cfg = self.get_config(user_id, config_id)
        if not cfg:
            return None

        # 更新字段
        for key, value in updates.items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)

        cfg.updated_at = time.time()
        self._save_configs()

        logger.info(f"[ExchangeConfigManager] [user={user_id}] 更新配置: {config_id}")
        return cfg

    def delete_config(self, user_id: str, config_id: str) -> bool:
        """删除配置"""
        if user_id not in self._configs:
            return False

        original_len = len(self._configs[user_id])
        self._configs[user_id] = [c for c in self._configs[user_id] if c.id != config_id]

        if len(self._configs[user_id]) < original_len:
            self._save_configs()
            logger.info(f"[ExchangeConfigManager] [user={user_id}] 删除配置: {config_id}")
            return True

        return False

    def get_config(self, user_id: str, config_id: str) -> ExchangeConfig | None:
        """获取单个配置"""
        if user_id not in self._configs:
            return None

        for cfg in self._configs[user_id]:
            if cfg.id == config_id:
                return cfg

        return None

    def get_user_configs(self, user_id: str) -> list[ExchangeConfig]:
        """获取用户所有配置"""
        return self._configs.get(user_id, [])

    def get_active_config(self, user_id: str, exchange: ExchangeType) -> ExchangeConfig | None:
        """获取用户的活跃配置"""
        configs = self.get_user_configs(user_id)
        for cfg in configs:
            if cfg.exchange == exchange and cfg.is_active and cfg.is_validated:
                return cfg
        return None

    def decrypt_for_use(self, config: ExchangeConfig) -> ExchangeConfig:
        """
        解密配置供交易模块使用。
        由于 _load_configs 已在加载时解密到内存，此处主要做兼容性透传，
        同时确保 api_bridge.py 所需属性（exchange_type / trading_mode）可用。
        """
        return config

    def validate_config(self, user_id: str, config_id: str) -> dict:
        """
        验证配置是否有效

        返回: { valid: bool, message: str }
        """
        cfg = self.get_config(user_id, config_id)
        if not cfg:
            return {"valid": False, "message": "配置不存在"}

        # 检查必要字段
        if not cfg.api_key or not cfg.api_secret:
            return {"valid": False, "message": "API Key 和 Secret 不能为空"}

        # OKX 需要 passphrase
        if cfg.exchange == ExchangeType.OKX and not cfg.passphrase:
            return {"valid": False, "message": "OKX 需要 Passphrase"}

        # TODO: 实际连接交易所验证
        # 这里先返回成功，后续可以添加真实验证
        cfg.is_validated = True
        cfg.updated_at = time.time()
        self._save_configs()

        return {"valid": True, "message": "配置验证成功"}

    def get_default_mode(self, user_id: str) -> TradingMode:
        """获取用户的默认交易模式"""
        configs = self.get_user_configs(user_id)

        # 如果有实盘配置且已验证，返回实盘
        for cfg in configs:
            if cfg.mode == TradingMode.LIVE and cfg.is_validated and cfg.is_active:
                return TradingMode.LIVE

        # 否则返回模拟盘
        return TradingMode.DEMO


# 全局实例
def get_exchange_config_manager() -> ExchangeConfigManager:
    """获取交易所配置管理器实例"""
    return ExchangeConfigManager()
