"""
SiliconBase Cloud API 配置文件

包含所有可配置参数，支持从环境变量读取
"""

import logging
import os
import secrets

# 配置模块日志记录器
logger = logging.getLogger(__name__)


class APIConfig:
    """API 配置类"""

    # 服务配置
    HOST: str = os.getenv("SILICONBASE_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("SILICONBASE_PORT", "8600"))
    DEBUG: bool = os.getenv("SILICONBASE_DEBUG", "false").lower() == "true"

    # 安全配置
    # [SECURITY_FIX_2026-03-29] JWT密钥安全强化修复
    # 修复原因：原代码使用硬编码默认密钥，存在严重安全隐患
    # 修复策略：强制环境变量读取，零静默失败原则
    # 开发环境：自动生成临时密钥并警告
    # 生产环境：强制要求设置密钥，否则拒绝启动

    # 步骤1: 尝试从环境变量读取密钥
    _secret_from_env: str | None = os.getenv("SILICONBASE_SECRET_KEY")

    if not _secret_from_env:
        # 步骤2: 未设置密钥时的处理逻辑
        # 检测当前运行环境
        _current_env: str = os.getenv("SILICONBASE_ENV", "development")

        if _current_env == "development":
            # 开发环境：生成临时密钥并记录警告
            # 注意：临时密钥在重启后会失效，仅用于开发测试
            SECRET_KEY: str = secrets.token_urlsafe(32)
            logger.warning(
                "[Config] 使用临时JWT密钥，重启后失效。"
                "请在.env中设置SILICONBASE_SECRET_KEY以确保会话连续性"
            )
        else:
            # 生产环境：强制报错，拒绝启动（零静默失败原则）
            raise ValueError(
                "[SILICONBASE_SECURITY_ERROR] 生产环境必须设置 SILICONBASE_SECRET_KEY 环境变量!\n"
                "生成命令: python -c \"import secrets; print(secrets.token_urlsafe(32))\"\n"
                "当前密钥强度不足，系统拒绝启动以保障安全。"
            )
    else:
        # 步骤3: 验证密钥强度（最小长度32字符）
        if len(_secret_from_env) < 32:
            raise ValueError(
                f"[SILICONBASE_SECURITY_ERROR] JWT密钥强度不足"
                f"（当前{len(_secret_from_env)}字符，要求至少32字符）"
            )
        # 密钥强度验证通过，使用环境变量值
        SECRET_KEY: str = _secret_from_env
    API_KEY_HEADER: str = "X-API-Key"
    TOKEN_EXPIRE_HOURS: int = int(os.getenv("SILICONBASE_TOKEN_EXPIRE_HOURS", "24"))

    # CORS 配置
    CORS_ORIGINS: list = os.getenv("SILICONBASE_CORS_ORIGINS", "*").split(",")
    CORS_ALLOW_CREDENTIALS: bool = True

    # 会话配置
    SESSION_TIMEOUT_HOURS: int = int(os.getenv("SILICONBASE_SESSION_TIMEOUT", "24"))
    MAX_SESSIONS_PER_USER: int = int(os.getenv("SILICONBASE_MAX_SESSIONS", "10"))
    MAX_MESSAGE_HISTORY: int = int(os.getenv("SILICONBASE_MAX_HISTORY", "100"))

    # WebSocket 配置
    WS_HEARTBEAT_INTERVAL: int = int(os.getenv("SILICONBASE_WS_HEARTBEAT", "30"))
    MAX_CONNECTIONS_PER_USER: int = int(os.getenv("SILICONBASE_MAX_CONNECTIONS", "5"))

    # AI 配置
    DEFAULT_MODEL: str = os.getenv("SILICONBASE_DEFAULT_MODEL", "default")
    DEFAULT_TEMPERATURE: float = float(os.getenv("SILICONBASE_DEFAULT_TEMP", "0.7"))
    DEFAULT_MAX_TOKENS: int = int(os.getenv("SILICONBASE_DEFAULT_MAX_TOKENS", "2048"))

    # 限流配置
    RATE_LIMIT_ENABLED: bool = os.getenv("SILICONBASE_RATE_LIMIT", "true").lower() == "true"
    RATE_LIMIT_REQUESTS: int = int(os.getenv("SILICONBASE_RATE_LIMIT_REQUESTS", "60"))
    RATE_LIMIT_WINDOW: int = int(os.getenv("SILICONBASE_RATE_LIMIT_WINDOW", "60"))

    # 日志配置
    LOG_LEVEL: str = os.getenv("SILICONBASE_LOG_LEVEL", "info")
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


# 全局配置实例
config = APIConfig()


def load_config_from_file(filepath: str) -> None:
    """从配置文件加载配置"""
    import json

    if os.path.exists(filepath):
        with open(filepath, encoding='utf-8') as f:
            data = json.load(f)
            for key, value in data.items():
                if hasattr(config, key):
                    setattr(config, key, value)
