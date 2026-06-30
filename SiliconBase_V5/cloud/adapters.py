"""
SiliconBase V5 云端组件适配器

提供云端部署环境下的组件适配，支持多种云服务商。
保留本地模式的向后兼容性。
"""

import json
import logging
import os
import re
from abc import ABC
from dataclasses import dataclass
from enum import Enum
from typing import Any, BinaryIO

# 配置日志
logger = logging.getLogger(__name__)

# 会话存储基础路径
SESSION_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data', 'sessions'))


def validate_id(id_str: str) -> bool:
    """验证ID格式安全 - 只允许字母数字下划线和中划线"""
    if not id_str:
        return False
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', id_str))


def validate_path_in_scope(final_path: str, base_path: str) -> bool:
    """验证最终路径在允许的范围内，防止路径遍历"""
    try:
        real_final = os.path.abspath(os.path.realpath(final_path))
        real_base = os.path.abspath(os.path.realpath(base_path))
        return real_final.startswith(real_base)
    except Exception:
        return False


class DeploymentMode(Enum):
    """部署模式枚举"""
    LOCAL = "local"
    CLOUD = "cloud"
    HYBRID = "hybrid"


class AIProvider(Enum):
    """AI 提供商枚举"""
    OPENAI = "openai"
    DASHSCOPE = "dashscope"
    WENXIN = "wenxin"
    ZHIPU = "zhipu"
    OLLAMA_CLOUD = "ollama_cloud"


class VoiceProvider(Enum):
    """语音服务提供商枚举"""
    ALIYUN = "aliyun"
    TENCENT = "tencent"
    AZURE = "azure"
    AWS = "aws"


class StorageBackend(Enum):
    """存储后端枚举"""
    LOCAL = "local"
    REDIS = "redis"
    MEMCACHED = "memcached"


class DatabaseType(Enum):
    """数据库类型枚举"""
    SQLITE = "sqlite"
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"


class FileStorageType(Enum):
    """文件存储类型枚举"""
    LOCAL = "local"
    OSS = "oss"
    S3 = "s3"
    COS = "cos"
    GCS = "gcs"
    AZURE_BLOB = "azure_blob"


# ============================================
# 配置数据类
# ============================================

@dataclass
class AIConfig:
    """AI 配置"""
    provider: str = "openai"
    api_key: str | None = None
    base_url: str | None = None
    model: str = "gpt-4"
    timeout: int = 60
    max_retries: int = 3

    @classmethod
    def from_env(cls, provider: str = "openai") -> "AIConfig":
        """从环境变量创建配置"""
        provider = provider.upper()
        return cls(
            provider=provider.lower(),
            api_key=os.getenv(f"{provider}_API_KEY"),
            base_url=os.getenv(f"{provider}_BASE_URL"),
            model=os.getenv(f"{provider}_MODEL", "gpt-4"),
            timeout=int(os.getenv(f"{provider}_TIMEOUT", "60")),
            max_retries=int(os.getenv(f"{provider}_MAX_RETRIES", "3"))
        )


@dataclass
class VoiceConfig:
    """语音配置"""
    provider: str = "aliyun"
    access_key_id: str | None = None
    access_key_secret: str | None = None
    app_key: str | None = None
    voice: str = "xiaoyun"
    format: str = "mp3"
    sample_rate: int = 16000

    @classmethod
    def from_env(cls, provider: str = "aliyun") -> "VoiceConfig":
        """从环境变量创建配置"""
        provider_upper = provider.upper()
        return cls(
            provider=provider,
            access_key_id=os.getenv(f"{provider_upper}_ACCESS_KEY_ID") or os.getenv("ALIYUN_ACCESS_KEY_ID"),
            access_key_secret=os.getenv(f"{provider_upper}_ACCESS_KEY_SECRET") or os.getenv("ALIYUN_ACCESS_KEY_SECRET"),
            app_key=os.getenv(f"{provider_upper}_APP_KEY") or os.getenv("ALIYUN_APP_KEY"),
            voice=os.getenv("VOICE_NAME", "xiaoyun"),
            format=os.getenv("VOICE_FORMAT", "mp3"),
            sample_rate=int(os.getenv("VOICE_SAMPLE_RATE", "16000"))
        )


@dataclass
class RedisConfig:
    """Redis 配置"""
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str | None = None
    ssl: bool = False
    connection_pool_size: int = 20
    socket_timeout: int = 5

    @classmethod
    def from_env(cls) -> "RedisConfig":
        """从环境变量创建配置"""
        return cls(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")),
            password=os.getenv("REDIS_PASSWORD"),
            ssl=os.getenv("REDIS_SSL", "false").lower() == "true",
            connection_pool_size=int(os.getenv("REDIS_POOL_SIZE", "20")),
            socket_timeout=int(os.getenv("REDIS_SOCKET_TIMEOUT", "5"))
        )


@dataclass
class PostgreSQLConfig:
    """PostgreSQL 配置"""
    host: str = "localhost"
    port: int = 5432
    database: str = "siliconbase"
    user: str = "siliconbase"
    password: str | None = None
    ssl_mode: str = "require"
    connection_pool_size: int = 20

    @classmethod
    def from_env(cls) -> "PostgreSQLConfig":
        """从环境变量创建配置"""
        # 支持 DATABASE_URL 标准格式
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            # 简化的 URL 解析
            return cls(
                host=os.getenv("PGHOST", "localhost"),
                port=int(os.getenv("PGPORT", "5432")),
                database=os.getenv("PGDATABASE", "siliconbase"),
                user=os.getenv("PGUSER", "siliconbase"),
                password=os.getenv("PGPASSWORD"),
                ssl_mode=os.getenv("PGSSLMODE", "require"),
                connection_pool_size=int(os.getenv("PG_POOL_SIZE", "20"))
            )

        return cls(
            host=os.getenv("PGHOST", "localhost"),
            port=int(os.getenv("PGPORT", "5432")),
            database=os.getenv("PGDATABASE", "siliconbase"),
            user=os.getenv("PGUSER", "siliconbase"),
            password=os.getenv("PGPASSWORD"),
            ssl_mode=os.getenv("PGSSLMODE", "require"),
            connection_pool_size=int(os.getenv("PG_POOL_SIZE", "20"))
        )


@dataclass
class OSSConfig:
    """阿里云 OSS 配置"""
    endpoint: str | None = None
    bucket: str | None = None
    access_key_id: str | None = None
    access_key_secret: str | None = None
    region: str = "cn-hangzhou"
    internal: bool = False
    cdn_domain: str | None = None

    @classmethod
    def from_env(cls) -> "OSSConfig":
        """从环境变量创建配置"""
        return cls(
            endpoint=os.getenv("OSS_ENDPOINT"),
            bucket=os.getenv("OSS_BUCKET"),
            access_key_id=os.getenv("OSS_ACCESS_KEY_ID") or os.getenv("ALIYUN_ACCESS_KEY_ID"),
            access_key_secret=os.getenv("OSS_ACCESS_KEY_SECRET") or os.getenv("ALIYUN_ACCESS_KEY_SECRET"),
            region=os.getenv("OSS_REGION", "cn-hangzhou"),
            internal=os.getenv("OSS_INTERNAL", "false").lower() == "true",
            cdn_domain=os.getenv("OSS_CDN_DOMAIN")
        )


@dataclass
class S3Config:
    """AWS S3 配置"""
    bucket: str | None = None
    access_key_id: str | None = None
    secret_access_key: str | None = None
    region: str = "us-east-1"
    endpoint: str | None = None
    cdn_domain: str | None = None

    @classmethod
    def from_env(cls) -> "S3Config":
        """从环境变量创建配置"""
        return cls(
            bucket=os.getenv("S3_BUCKET"),
            access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region=os.getenv("AWS_REGION", "us-east-1"),
            endpoint=os.getenv("S3_ENDPOINT"),
            cdn_domain=os.getenv("S3_CDN_DOMAIN")
        )


# ============================================
# 云端适配器基类
# ============================================

class BaseAdapter(ABC):  # noqa: B024
    """适配器基类（暂未声明抽象方法，保留扩展接口）"""

    def __init__(self):
        self.mode = self._detect_mode()

    def _detect_mode(self) -> DeploymentMode:
        """检测部署模式"""
        mode = os.getenv("DEPLOYMENT_MODE", "local").lower()
        try:
            return DeploymentMode(mode)
        except ValueError:
            return DeploymentMode.LOCAL

    def is_cloud_mode(self) -> bool:
        """是否为云端模式"""
        return self.mode in (DeploymentMode.CLOUD, DeploymentMode.HYBRID)

    def is_local_mode(self) -> bool:
        """是否为本地模式"""
        return self.mode == DeploymentMode.LOCAL


# ============================================
# AI 适配器
# ============================================

class CloudAIAdapter(BaseAdapter):
    """
    云端 AI 适配器

    本地模式：使用本地 Ollama
    云端模式：使用云端 API（OpenAI、DashScope 等）
    """

    def __init__(self, config: AIConfig | None = None):
        super().__init__()
        self.config = config or AIConfig.from_env()
        self._client = None

    def _get_client(self):
        """获取 AI 客户端（延迟初始化）"""
        if self._client is None:
            self._client = self._create_client()
        return self._client

    def _create_client(self):
        """创建 AI 客户端"""
        if self.is_local_mode():
            # 本地模式使用 Ollama
            try:
                import ollama
                return ollama
            except ImportError:
                logger.warning("Ollama not installed, falling back to cloud")

        # 云端模式或 fallback
        provider = self.config.provider

        if provider == AIProvider.OPENAI.value:
            try:
                from openai import OpenAI
                return OpenAI(
                    api_key=self.config.api_key,
                    base_url=self.config.base_url,
                    timeout=self.config.timeout,
                    max_retries=self.config.max_retries
                )
            except ImportError:
                logger.error("openai package not installed")
                return None

        elif provider == AIProvider.DASHSCOPE.value:
            # 阿里云 DashScope
            try:
                import dashscope
                dashscope.api_key = self.config.api_key
                return dashscope
            except ImportError:
                logger.error("dashscope package not installed")
                return None

        # TODO: 其他提供商的实现
        return None

    def chat(self, messages: list[dict[str, str]], **kwargs) -> dict[str, Any]:
        """
        聊天接口

        Args:
            messages: 消息列表，格式 [{"role": "user", "content": "..."}, ...]
            **kwargs: 额外参数

        Returns:
            响应字典
        """
        client = self._get_client()
        if client is None:
            return {"error": "AI client not available"}

        if self.is_local_mode():
            # 本地 Ollama 调用
            try:
                response = client.chat(
                    model=kwargs.get("model", "llama2"),
                    messages=messages
                )
                return {
                    "content": response["message"]["content"],
                    "model": response.get("model"),
                    "usage": response.get("usage", {})
                }
            except Exception as e:
                logger.error(f"Local AI error: {e}")
                return {"error": str(e)}

        # 云端 API 调用
        try:
            if self.config.provider == AIProvider.OPENAI.value:
                response = client.chat.completions.create(
                    model=kwargs.get("model", self.config.model),
                    messages=messages,
                    temperature=kwargs.get("temperature", 0.7),
                    max_tokens=kwargs.get("max_tokens", 2000)
                )
                return {
                    "content": response.choices[0].message.content,
                    "model": response.model,
                    "usage": {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens
                    }
                }

            elif self.config.provider == AIProvider.DASHSCOPE.value:
                # DashScope 调用
                pass  # TODO: 实现 DashScope 调用

        except Exception as e:
            logger.error(f"Cloud AI error: {e}")
            return {"error": str(e)}

        return {"error": "Provider not implemented"}

    def embed(self, text: str, **kwargs) -> list[float]:
        """
        获取文本嵌入向量

        Args:
            text: 输入文本
            **kwargs: 额外参数

        Returns:
            嵌入向量
        """
        client = self._get_client()
        if client is None:
            return []

        # TODO: 实现嵌入接口
        return []


# ============================================
# 语音适配器
# ============================================

class CloudVoiceAdapter(BaseAdapter):
    """
    云端语音适配器

    本地模式：本地 TTS 播放
    云端模式：调用云端语音合成 API，返回音频 URL
    """

    def __init__(self, config: VoiceConfig | None = None):
        super().__init__()
        self.config = config or VoiceConfig.from_env()
        self._client = None

    def speak(self, text: str, **kwargs) -> str | dict[str, Any]:
        """
        语音合成

        本地模式：播放音频并返回状态
        云端模式：生成语音并返回可访问的 URL

        Args:
            text: 要合成的文本
            **kwargs: 额外参数

        Returns:
            云端模式：音频 URL
            本地模式：播放结果状态
        """
        if self.is_local_mode():
            return self._local_speak(text, **kwargs)
        return self._cloud_speak(text, **kwargs)

    def _local_speak(self, text: str, **kwargs) -> dict[str, Any]:
        """本地语音播放"""
        try:
            # 尝试使用本地 TTS
            import pyttsx3
            engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()
            return {"status": "success", "mode": "local"}
        except Exception as e:
            logger.error(f"Local TTS error: {e}")
            return {"error": str(e), "mode": "local"}

    def _cloud_speak(self, text: str, **kwargs) -> str:
        """
        云端语音合成

        调用阿里云/腾讯云/Azure 语音合成 API，
        上传音频到 OSS/S3，返回可访问的 URL
        """
        provider = self.config.provider

        try:
            if provider == VoiceProvider.ALIYUN.value:
                return self._aliyun_speech(text, **kwargs)
            elif provider == VoiceProvider.TENCENT.value:
                return self._tencent_speech(text, **kwargs)
            elif provider == VoiceProvider.AZURE.value:
                return self._azure_speech(text, **kwargs)
            elif provider == VoiceProvider.AWS.value:
                return self._aws_speech(text, **kwargs)
            else:
                logger.warning(f"Unknown voice provider: {provider}")
                return ""
        except Exception as e:
            logger.error(f"Cloud speech synthesis error: {e}")
            return ""

    def _aliyun_speech(self, text: str, **kwargs) -> str:
        """阿里云语音合成"""
        # TODO: 实现阿里云语音合成
        # 1. 调用阿里云语音合成 API
        # 2. 上传音频到 OSS
        # 3. 返回可访问的 URL
        logger.info(f"Aliyun speech synthesis for: {text[:50]}...")
        return "https://example.com/audio.mp3"  # 占位

    def _tencent_speech(self, text: str, **kwargs) -> str:
        """腾讯云语音合成"""
        # TODO: 实现腾讯云语音合成
        logger.info(f"Tencent speech synthesis for: {text[:50]}...")
        return "https://example.com/audio.mp3"  # 占位

    def _azure_speech(self, text: str, **kwargs) -> str:
        """Azure 语音合成"""
        # TODO: 实现 Azure 语音合成
        logger.info(f"Azure speech synthesis for: {text[:50]}...")
        return "https://example.com/audio.mp3"  # 占位

    def _aws_speech(self, text: str, **kwargs) -> str:
        """AWS Polly 语音合成"""
        # TODO: 实现 AWS Polly
        logger.info(f"AWS Polly synthesis for: {text[:50]}...")
        return "https://example.com/audio.mp3"  # 占位


# ============================================
# 存储适配器
# ============================================

class CloudStorageAdapter(BaseAdapter):
    """
    云端存储适配器

    支持 Redis、Memcached 等云端存储
    替代本地文件存储
    """

    def __init__(self, backend: str = "redis", config: Any | None = None):
        super().__init__()
        self.backend = backend
        self.config = config or RedisConfig.from_env()
        self._client = None

    def _get_client(self):
        """获取存储客户端（延迟初始化）"""
        if self._client is None:
            self._client = self._create_client()
        return self._client

    def _create_client(self):
        """创建存储客户端"""
        if self.backend == StorageBackend.REDIS.value:
            try:
                import redis
                return redis.Redis(
                    host=self.config.host,
                    port=self.config.port,
                    db=self.config.db,
                    password=self.config.password,
                    ssl=self.config.ssl,
                    decode_responses=True,
                    socket_connect_timeout=self.config.socket_timeout
                )
            except ImportError:
                logger.error("redis package not installed")
                return None

        elif self.backend == StorageBackend.MEMCACHED.value:
            try:
                from pymemcache.client.base import Client
                # 解析服务器地址
                servers = os.getenv("MEMCACHED_SERVERS", "localhost:11211").split(",")
                if len(servers) == 1:
                    host, port = servers[0].split(":")
                    return Client((host, int(port)))
                # TODO: 集群模式
                return None
            except ImportError:
                logger.error("pymemcache package not installed")
                return None

        return None

    def save_session(self, user_id: str, session_id: str, data: dict[str, Any], ttl: int = 3600) -> bool:
        """
        保存会话数据

        Args:
            user_id: 用户 ID
            session_id: 会话 ID
            data: 会话数据
            ttl: 过期时间（秒）

        Returns:
            是否保存成功
        """
        if self.is_local_mode():
            # 本地模式使用文件存储
            return self._local_save_session(user_id, session_id, data)

        client = self._get_client()
        if client is None:
            return False

        key = f"session:{user_id}:{session_id}"
        try:
            value = json.dumps(data)
            client.setex(key, ttl, value)
            return True
        except Exception as e:
            logger.error(f"Save session error: {e}")
            return False

    def load_session(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        """
        加载会话数据

        Args:
            user_id: 用户 ID
            session_id: 会话 ID

        Returns:
            会话数据或 None
        """
        if self.is_local_mode():
            return self._local_load_session(user_id, session_id)

        client = self._get_client()
        if client is None:
            return None

        key = f"session:{user_id}:{session_id}"
        try:
            value = client.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.error(f"Load session error: {e}")
            return None

    def delete_session(self, user_id: str, session_id: str) -> bool:
        """删除会话数据"""
        if self.is_local_mode():
            return self._local_delete_session(user_id, session_id)

        client = self._get_client()
        if client is None:
            return False

        key = f"session:{user_id}:{session_id}"
        try:
            client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Delete session error: {e}")
            return False

    def _local_save_session(self, user_id: str, session_id: str, data: dict[str, Any]) -> bool:
        """本地文件存储会话"""
        import json
        import os

        # 安全验证：验证ID格式
        if not validate_id(user_id) or not validate_id(session_id):
            logger.error("Invalid user_id or session_id format")
            return False

        session_dir = os.path.join(SESSION_BASE_DIR, user_id)

        # 安全验证：验证路径在允许范围内
        if not validate_path_in_scope(session_dir, SESSION_BASE_DIR):
            logger.error(f"Path traversal detected in user_id: {user_id}")
            return False

        os.makedirs(session_dir, exist_ok=True)

        session_file = os.path.join(session_dir, f"{session_id}.json")

        # 安全验证：验证最终文件路径
        if not validate_path_in_scope(session_file, SESSION_BASE_DIR):
            logger.error(f"Path traversal detected in session_id: {session_id}")
            return False
        try:
            with open(session_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"Local save session error: {e}")
            return False

    def _local_load_session(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        """本地文件加载会话"""
        import json
        import os

        # 安全验证：验证ID格式
        if not validate_id(user_id) or not validate_id(session_id):
            logger.error("Invalid user_id or session_id format")
            return None

        session_file = os.path.join(SESSION_BASE_DIR, user_id, f"{session_id}.json")

        # 安全验证：验证最终文件路径
        if not validate_path_in_scope(session_file, SESSION_BASE_DIR):
            logger.error("Path traversal detected")
            return None
        if not os.path.exists(session_file):
            return None

        try:
            with open(session_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Local load session error: {e}")
            return None

    def _local_delete_session(self, user_id: str, session_id: str) -> bool:
        """本地文件删除会话"""
        import os

        # 安全验证：验证ID格式
        if not validate_id(user_id) or not validate_id(session_id):
            logger.error("Invalid user_id or session_id format")
            return False

        session_file = os.path.join(SESSION_BASE_DIR, user_id, f"{session_id}.json")

        # 安全验证：验证最终文件路径
        if not validate_path_in_scope(session_file, SESSION_BASE_DIR):
            logger.error("Path traversal detected")
            return False
        if os.path.exists(session_file):
            try:
                os.remove(session_file)
                return True
            except Exception as e:
                logger.error(f"Local delete session error: {e}")
                return False
        return True

    # 通用键值操作
    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """设置键值"""
        client = self._get_client()
        if client is None:
            return False

        try:
            value_json = json.dumps(value)
            if ttl:
                client.setex(key, ttl, value_json)
            else:
                client.set(key, value_json)
            return True
        except Exception as e:
            logger.error(f"Set error: {e}")
            return False

    def get(self, key: str) -> Any | None:
        """获取键值"""
        client = self._get_client()
        if client is None:
            return None

        try:
            value = client.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.error(f"Get error: {e}")
            return None

    def delete(self, key: str) -> bool:
        """删除键"""
        client = self._get_client()
        if client is None:
            return False

        try:
            client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Delete error: {e}")
            return False


# ============================================
# 数据库适配器
# ============================================

class CloudDatabaseAdapter(BaseAdapter):
    """
    云端数据库适配器

    支持 PostgreSQL、MySQL 等云端数据库
    替代本地 SQLite
    """

    def __init__(self, db_type: str = "postgresql", config: Any | None = None):
        super().__init__()
        self.db_type = db_type
        self.config = config or PostgreSQLConfig.from_env()
        self._engine = None
        self._session_factory = None

    def _get_engine(self):
        """获取数据库引擎（延迟初始化）"""
        if self._engine is None:
            self._engine = self._create_engine()
        return self._engine

    def _create_engine(self):
        """创建数据库引擎"""
        try:
            from sqlalchemy import create_engine

            if self.db_type == DatabaseType.POSTGRESQL.value:
                conn_string = self._build_postgres_connection_string()
            elif self.db_type == DatabaseType.MYSQL.value:
                conn_string = self._build_mysql_connection_string()
            else:
                # SQLite
                conn_string = "sqlite:///siliconbase.db"

            return create_engine(
                conn_string,
                pool_size=self.config.connection_pool_size if hasattr(self.config, 'connection_pool_size') else 5,
                max_overflow=10,
                pool_timeout=30
            )
        except ImportError:
            logger.error("sqlalchemy not installed")
            return None
        except Exception as e:
            logger.error(f"Create engine error: {e}")
            return None

    def _build_postgres_connection_string(self) -> str:
        """构建 PostgreSQL 连接字符串"""
        cfg = self.config
        if hasattr(cfg, 'password') and cfg.password:
            return f"postgresql://{cfg.user}:{cfg.password}@{cfg.host}:{cfg.port}/{cfg.database}"
        return f"postgresql://{cfg.user}@{cfg.host}:{cfg.port}/{cfg.database}"

    def _build_mysql_connection_string(self) -> str:
        """构建 MySQL 连接字符串"""
        # TODO: 实现 MySQL 连接字符串构建
        return ""

    def initialize_tables(self) -> bool:
        """初始化数据库表"""
        engine = self._get_engine()
        if engine is None:
            return False

        try:
            # TODO: 创建表结构
            # from sqlalchemy import MetaData, Table, Column, String, DateTime, JSON
            # metadata = MetaData()
            # ... 定义表结构
            # metadata.create_all(engine)
            logger.info("Database tables initialized")
            return True
        except Exception as e:
            logger.error(f"Initialize tables error: {e}")
            return False

    def execute(self, query: str, params: dict | None = None) -> Any:
        """执行 SQL 查询"""
        engine = self._get_engine()
        if engine is None:
            return None

        try:
            from sqlalchemy import text
            with engine.connect() as conn:
                result = conn.execute(text(query), params or {})
                conn.commit()
                return result
        except Exception as e:
            logger.error(f"Execute error: {e}")
            return None

    def fetch_one(self, query: str, params: dict | None = None) -> dict | None:
        """查询单条记录"""
        engine = self._get_engine()
        if engine is None:
            return None

        try:
            from sqlalchemy import text
            with engine.connect() as conn:
                result = conn.execute(text(query), params or {})
                row = result.fetchone()
                if row:
                    return dict(row._mapping)
                return None
        except Exception as e:
            logger.error(f"Fetch one error: {e}")
            return None

    def fetch_all(self, query: str, params: dict | None = None) -> list[dict]:
        """查询多条记录"""
        engine = self._get_engine()
        if engine is None:
            return []

        try:
            from sqlalchemy import text
            with engine.connect() as conn:
                result = conn.execute(text(query), params or {})
                return [dict(row._mapping) for row in result]
        except Exception as e:
            logger.error(f"Fetch all error: {e}")
            return []

    # Memory 接口兼容
    def save_memory(self, user_id: str, memory_type: str, content: dict[str, Any]) -> bool:
        """保存记忆"""
        # TODO: 实现记忆保存
        pass

    def load_memories(self, user_id: str, memory_type: str | None = None) -> list[dict[str, Any]]:
        """加载记忆"""
        # TODO: 实现记忆加载
        return []

    def delete_memory(self, user_id: str, memory_id: str) -> bool:
        """删除记忆"""
        # TODO: 实现记忆删除
        pass


# ============================================
# 文件存储适配器
# ============================================

class CloudFileStorageAdapter(BaseAdapter):
    """
    云端文件存储适配器

    支持 OSS、S3、COS、GCS、Azure Blob 等
    替代本地文件存储
    """

    def __init__(self, storage_type: str = "oss", config: Any | None = None):
        super().__init__()
        self.storage_type = storage_type
        self.config = config
        self._client = None
        self._bucket = None

    def _get_client(self):
        """获取存储客户端（延迟初始化）"""
        if self._client is None:
            self._client = self._create_client()
        return self._client

    def _create_client(self):
        """创建存储客户端"""
        if self.storage_type == FileStorageType.OSS.value:
            return self._create_oss_client()
        elif self.storage_type == FileStorageType.S3.value:
            return self._create_s3_client()
        elif self.storage_type == FileStorageType.COS.value:
            return self._create_cos_client()
        return None

    def _create_oss_client(self):
        """创建 OSS 客户端"""
        try:
            import oss2
            config = self.config or OSSConfig.from_env()
            auth = oss2.Auth(config.access_key_id, config.access_key_secret)
            endpoint = config.endpoint
            if config.internal and "-internal" not in endpoint:
                endpoint = endpoint.replace(".aliyuncs.com", "-internal.aliyuncs.com")
            bucket = oss2.Bucket(auth, endpoint, config.bucket)
            return bucket
        except ImportError:
            logger.error("oss2 package not installed")
            return None

    def _create_s3_client(self):
        """创建 S3 客户端"""
        try:
            import boto3
            config = self.config or S3Config.from_env()
            client = boto3.client(
                "s3",
                aws_access_key_id=config.access_key_id,
                aws_secret_access_key=config.secret_access_key,
                region_name=config.region,
                endpoint_url=config.endpoint
            )
            return client
        except ImportError:
            logger.error("boto3 package not installed")
            return None

    def _create_cos_client(self):
        """创建 COS 客户端"""
        try:
            from qcloud_cos import CosConfig, CosS3Client
            config = self.config  # TODO: COS 配置类
            cos_config = CosConfig(
                Region=config.region,
                SecretId=config.secret_id,
                SecretKey=config.secret_key
            )
            return CosS3Client(cos_config)
        except ImportError:
            logger.error("qcloud_cos package not installed")
            return None

    def upload(self, key: str, data: bytes | BinaryIO | str, **kwargs) -> str | None:
        """
        上传文件

        Args:
            key: 文件键名
            data: 文件数据
            **kwargs: 额外参数

        Returns:
            文件访问 URL
        """
        if self.is_local_mode():
            return self._local_upload(key, data)

        client = self._get_client()
        if client is None:
            return None

        try:
            if self.storage_type == FileStorageType.OSS.value:
                client.put_object(key, data)
                return self._get_oss_url(key)
            elif self.storage_type == FileStorageType.S3.value:
                bucket = self.config.bucket if self.config else os.getenv("S3_BUCKET")
                client.put_object(Bucket=bucket, Key=key, Body=data)
                return self._get_s3_url(key)
        except Exception as e:
            logger.error(f"Upload error: {e}")
            return None

    def download(self, key: str) -> bytes | None:
        """
        下载文件

        Args:
            key: 文件键名

        Returns:
            文件数据
        """
        if self.is_local_mode():
            return self._local_download(key)

        client = self._get_client()
        if client is None:
            return None

        try:
            if self.storage_type == FileStorageType.OSS.value:
                result = client.get_object(key)
                return result.read()
            elif self.storage_type == FileStorageType.S3.value:
                bucket = self.config.bucket if self.config else os.getenv("S3_BUCKET")
                result = client.get_object(Bucket=bucket, Key=key)
                return result["Body"].read()
        except Exception as e:
            logger.error(f"Download error: {e}")
            return None

    def delete(self, key: str) -> bool:
        """删除文件"""
        if self.is_local_mode():
            return self._local_delete(key)

        client = self._get_client()
        if client is None:
            return False

        try:
            if self.storage_type == FileStorageType.OSS.value:
                client.delete_object(key)
            elif self.storage_type == FileStorageType.S3.value:
                bucket = self.config.bucket if self.config else os.getenv("S3_BUCKET")
                client.delete_object(Bucket=bucket, Key=key)
            return True
        except Exception as e:
            logger.error(f"Delete error: {e}")
            return False

    def exists(self, key: str) -> bool:
        """检查文件是否存在"""
        if self.is_local_mode():
            return self._local_exists(key)

        client = self._get_client()
        if client is None:
            return False

        try:
            if self.storage_type == FileStorageType.OSS.value:
                return client.object_exists(key)
            elif self.storage_type == FileStorageType.S3.value:
                bucket = self.config.bucket if self.config else os.getenv("S3_BUCKET")
                client.head_object(Bucket=bucket, Key=key)
                return True
        except Exception:
            return False

    def _get_oss_url(self, key: str) -> str:
        """获取 OSS 文件 URL"""
        config = self.config or OSSConfig.from_env()
        if config.cdn_domain:
            return f"https://{config.cdn_domain}/{key}"
        return f"https://{config.bucket}.{config.endpoint}/{key}"

    def _get_s3_url(self, key: str) -> str:
        """获取 S3 文件 URL"""
        config = self.config or S3Config.from_env()
        if config.cdn_domain:
            return f"https://{config.cdn_domain}/{key}"
        if config.endpoint:
            return f"{config.endpoint}/{config.bucket}/{key}"
        return f"https://{config.bucket}.s3.{config.region}.amazonaws.com/{key}"

    def _local_upload(self, key: str, data: bytes | BinaryIO | str) -> str:
        """本地文件上传"""
        import os

        upload_dir = os.path.join("data", "uploads")
        os.makedirs(upload_dir, exist_ok=True)

        file_path = os.path.join(upload_dir, key)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        if isinstance(data, str):
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(data)
        else:
            with open(file_path, "wb") as f:
                if isinstance(data, bytes):
                    f.write(data)
                else:
                    f.write(data.read())

        return f"file://{os.path.abspath(file_path)}"

    def _local_download(self, key: str) -> bytes | None:
        """本地文件下载"""
        import os

        file_path = os.path.join("data", "uploads", key)
        if not os.path.exists(file_path):
            return None

        with open(file_path, "rb") as f:
            return f.read()

    def _local_delete(self, key: str) -> bool:
        """本地文件删除"""
        import os

        file_path = os.path.join("data", "uploads", key)
        if os.path.exists(file_path):
            os.remove(file_path)
            return True
        return False

    def _local_exists(self, key: str) -> bool:
        """本地文件存在检查"""
        import os
        return os.path.exists(os.path.join("data", "uploads", key))


# ============================================
# 适配器工厂
# ============================================

class AdapterFactory:
    """适配器工厂 - 根据部署模式创建合适的适配器"""

    @staticmethod
    def create_ai_adapter(config: AIConfig | None = None) -> CloudAIAdapter:
        """创建 AI 适配器"""
        return CloudAIAdapter(config)

    @staticmethod
    def create_voice_adapter(config: VoiceConfig | None = None) -> CloudVoiceAdapter:
        """创建语音适配器"""
        return CloudVoiceAdapter(config)

    @staticmethod
    def create_storage_adapter(
        backend: str = "redis",
        config: Any | None = None
    ) -> CloudStorageAdapter:
        """创建存储适配器"""
        return CloudStorageAdapter(backend, config)

    @staticmethod
    def create_database_adapter(
        db_type: str = "postgresql",
        config: Any | None = None
    ) -> CloudDatabaseAdapter:
        """创建数据库适配器"""
        return CloudDatabaseAdapter(db_type, config)

    @staticmethod
    def create_file_storage_adapter(
        storage_type: str = "oss",
        config: Any | None = None
    ) -> CloudFileStorageAdapter:
        """创建文件存储适配器"""
        return CloudFileStorageAdapter(storage_type, config)


# ============================================
# 便捷函数
# ============================================

def get_deployment_mode() -> DeploymentMode:
    """获取当前部署模式"""
    mode = os.getenv("DEPLOYMENT_MODE", "local").lower()
    try:
        return DeploymentMode(mode)
    except ValueError:
        return DeploymentMode.LOCAL


def is_cloud_deployment() -> bool:
    """检查是否为云端部署"""
    return get_deployment_mode() in (DeploymentMode.CLOUD, DeploymentMode.HYBRID)


def create_default_adapters() -> dict[str, BaseAdapter]:
    """创建默认适配器集合"""
    factory = AdapterFactory()
    return {
        "ai": factory.create_ai_adapter(),
        "voice": factory.create_voice_adapter(),
        "storage": factory.create_storage_adapter(),
        "database": factory.create_database_adapter(),
        "files": factory.create_file_storage_adapter()
    }
