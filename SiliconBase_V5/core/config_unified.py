#!/usr/bin/env python3
"""
后端 UnifiedConfig 配置管理器 V2.0

统一配置管理器，支持：
1. 从YAML和环境变量加载配置
2. 深度合并配置（环境变量优先级 > YAML）
3. 单例模式
4. 静默失败阻断 - 任何配置错误必须抛出异常

【静默失败阻断规则】
- 配置文件读取失败必须报错，不能使用默认值静默继续
- 环境变量解析错误必须报错，不能静默跳过
- 服务配置获取失败必须报错，不能返回None

版本历史:
- 2026-03-13: 初始版本，实现核心配置管理功能
"""

import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

# 导入现有异常类
from core.exceptions import ConfigError

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# ConfigurationError 异常类（继承自 ConfigError）
# ═══════════════════════════════════════════════════════════════

class ConfigurationError(ConfigError):
    """配置错误 - 配置加载/验证失败时抛出

    【异常处理铁律】
    - ❌ 禁止静默返回None
    - ✅ 必须 logger.error("[SILENT_FAILURE_BLOCKED] ...") + raise ConfigurationError
    """
    pass


# ═══════════════════════════════════════════════════════════════
# ServiceConfig Dataclass
# ═══════════════════════════════════════════════════════════════

@dataclass
class ServiceConfig:
    """服务配置数据类

    Attributes:
        host: 服务主机地址
        port: 服务端口号
        scheme: 协议方案 (http/https)
        timeout: 超时时间（秒）
        extra: 额外配置参数
    """
    host: str
    port: int
    scheme: str = "http"
    timeout: int = 30
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """初始化后验证"""
        if not isinstance(self.host, str) or not self.host:
            raise ConfigurationError(f"服务host必须是有效的字符串，当前值: {self.host}")
        if not isinstance(self.port, int) or self.port < 1 or self.port > 65535:
            raise ConfigurationError(f"服务port必须是1-65535的整数，当前值: {self.port}")
        if self.scheme not in ("http", "https"):
            raise ConfigurationError(f"服务scheme必须是http或https，当前值: {self.scheme}")

    @property
    def base_url(self) -> str:
        """获取完整的基础URL"""
        return f"{self.scheme}://{self.host}:{self.port}"

    def __str__(self) -> str:
        return f"ServiceConfig({self.base_url}, timeout={self.timeout}s)"


# ═══════════════════════════════════════════════════════════════
# UnifiedConfig 单例类
# ═══════════════════════════════════════════════════════════════

class UnifiedConfig:
    """统一配置管理器 - 单例模式

    配置优先级：环境变量 > YAML配置文件 > 默认值

    【使用示例】
    >>> config = UnifiedConfig()
    >>> service = config.get_service("postgresql")
    >>> timeout = config.get_timeout("api")
    >>> cors_origins = config.get_cors_origins()
    """

    _instance: Optional['UnifiedConfig'] = None
    _lock = threading.Lock()
    _initialized: bool = False

    def __new__(cls) -> 'UnifiedConfig':
        """实现单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化配置管理器"""
        # 防止重复初始化
        if self._initialized:
            return

        with self._lock:
            if self._initialized:
                return

            self._config: dict[str, Any] = {}
            self._config_file_path: Path | None = None
            self._config_mtime: float = 0.0

            # 加载配置
            self._load_config()

            self._initialized = True

    def _get_project_root(self) -> Path:
        """获取项目根目录"""
        return Path(__file__).parent.parent

    def _find_config_file(self) -> Path:
        """查找配置文件路径

        查找顺序:
        1. 环境变量 SILICONBASE_CONFIG_PATH
        2. 项目根目录下的 config/unified.yaml
        3. 项目根目录下的 config/global.yaml

        Returns:
            配置文件路径

        Raises:
            ConfigurationError: 找不到配置文件
        """
        # 1. 检查环境变量
        env_path = os.environ.get("SILICONBASE_CONFIG_PATH")
        if env_path:
            config_path = Path(env_path)
            if config_path.exists():
                logger.info(f"[UnifiedConfig] 从环境变量加载配置文件: {config_path}")
                return config_path
            else:
                logger.error(f"[SILENT_FAILURE_BLOCKED] 环境变量指定的配置文件不存在: {env_path}")
                raise ConfigurationError(f"环境变量指定的配置文件不存在: {env_path}")

        # 2. 检查项目根目录下的 config/unified.yaml
        project_root = self._get_project_root()
        unified_path = project_root / "config" / "unified.yaml"
        if unified_path.exists():
            logger.info(f"[UnifiedConfig] 找到配置文件: {unified_path}")
            return unified_path

        # 3. 检查项目根目录下的 config/global.yaml
        global_path = project_root / "config" / "global.yaml"
        if global_path.exists():
            logger.info(f"[UnifiedConfig] 找到配置文件: {global_path}")
            return global_path

        # 配置文件未找到 - 禁止静默失败
        logger.error("[SILENT_FAILURE_BLOCKED] 未找到任何配置文件")
        logger.error(f"  查找路径: {unified_path}")
        logger.error(f"  查找路径: {global_path}")
        raise ConfigurationError(
            "未找到配置文件。请确保以下文件之一存在:\n"
            f"  - {unified_path}\n"
            f"  - {global_path}\n"
            "或通过环境变量 SILICONBASE_CONFIG_PATH 指定配置文件路径"
        )

    def _load_yaml_config(self, config_path: Path) -> dict[str, Any]:
        """从YAML文件加载配置

        Args:
            config_path: YAML配置文件路径

        Returns:
            配置字典

        Raises:
            ConfigurationError: 配置文件读取或解析失败
        """
        try:
            with open(config_path, encoding='utf-8') as f:
                content = f.read()
        except FileNotFoundError as _exc:
            logger.error(f"[SILENT_FAILURE_BLOCKED] 配置文件不存在: {config_path}")
            raise ConfigurationError(f"配置文件不存在: {config_path}") from _exc
        except PermissionError as _exc:
            logger.error(f"[SILENT_FAILURE_BLOCKED] 无权限读取配置文件: {config_path}")
            raise ConfigurationError(f"无权限读取配置文件: {config_path}") from _exc
        except OSError as e:
            logger.error(f"[SILENT_FAILURE_BLOCKED] 读取配置文件IO错误: {config_path}, 错误: {e}")
            raise ConfigurationError(f"读取配置文件IO错误: {config_path}, 错误: {e}") from e

        # 解析YAML
        try:
            config = yaml.safe_load(content)
        except yaml.YAMLError as e:
            logger.error(f"[SILENT_FAILURE_BLOCKED] YAML解析错误: {config_path}, 错误: {e}")
            raise ConfigurationError(f"YAML解析错误: {config_path}, 错误: {e}") from e

        if config is None:
            # 空文件返回空字典
            config = {}
        elif not isinstance(config, dict):
            logger.error(f"[SILENT_FAILURE_BLOCKED] 配置文件根必须是字典类型，当前类型: {type(config).__name__}")
            raise ConfigurationError(f"配置文件根必须是字典类型，当前类型: {type(config).__name__}")

        # 记录文件修改时间用于热重载
        self._config_mtime = config_path.stat().st_mtime
        self._config_file_path = config_path

        logger.info(f"[UnifiedConfig] 成功加载配置文件: {config_path}")
        return config

    def _key_to_env_var(self, key: str) -> str:
        """将配置键转换为环境变量名

        转换规则:
        - 点号分隔转换为双下划线: "services.postgresql.host" -> "SILICONBASE_SERVICES__POSTGRESQL__HOST"
        - 统一大写

        Args:
            key: 配置键（支持点号分隔）

        Returns:
            环境变量名
        """
        return f"SILICONBASE_{key.upper().replace('.', '__')}"

    def _parse_env_value(self, value: str) -> Any:
        """解析环境变量值为适当的Python类型

        支持类型:
        - bool: "true", "false", "1", "0", "yes", "no"
        - int: 纯数字
        - float: 包含小数点的数字
        - list: JSON数组格式
        - dict: JSON对象格式
        - str: 其他

        Args:
            value: 环境变量字符串值

        Returns:
            解析后的值

        Raises:
            ConfigurationError: 环境变量解析失败
        """
        if not isinstance(value, str):
            return value

        # 尝试解析布尔值
        lower_val = value.lower().strip()
        if lower_val in ('true', '1', 'yes', 'on'):
            return True
        if lower_val in ('false', '0', 'no', 'off'):
            return False

        # 尝试解析null
        if lower_val in ('null', 'none', ''):
            return None

        # 尝试解析数字
        try:
            # 尝试整数
            if value.lstrip('-').isdigit():
                return int(value)
            # 尝试浮点数
            if '.' in value and value.replace('.', '').replace('-', '').isdigit():
                return float(value)
        except ValueError:
            pass

        # 尝试解析JSON（列表或字典）
        if (value.startswith('[') and value.endswith(']')) or \
           (value.startswith('{') and value.endswith('}')):
            try:
                import json
                return json.loads(value)
            except json.JSONDecodeError as e:
                logger.error(f"[SILENT_FAILURE_BLOCKED] 环境变量JSON解析失败: {value}, 错误: {e}")
                raise ConfigurationError(f"环境变量JSON解析失败: {value}, 错误: {e}") from e

        # 默认返回字符串
        return value

    def _get_from_env(self, key: str) -> tuple[bool, Any]:
        """从环境变量获取配置值

        Args:
            key: 配置键

        Returns:
            (是否找到, 值)
        """
        env_var = self._key_to_env_var(key)
        value = os.environ.get(env_var)

        if value is not None:
            try:
                parsed_value = self._parse_env_value(value)
                logger.debug(f"[UnifiedConfig] 从环境变量获取: {env_var} = {parsed_value}")
                return True, parsed_value
            except ConfigurationError:
                # 向上传播解析错误
                raise

        return False, None

    def _set_nested_value(self, config: dict[str, Any], key: str, value: Any) -> None:
        """在嵌套字典中设置值

        Args:
            config: 配置字典
            key: 点号分隔的键
            value: 要设置的值
        """
        keys = key.split('.')
        current = config
        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]
        current[keys[-1]] = value

    def _get_nested_value(self, config: dict[str, Any], key: str) -> tuple[bool, Any]:
        """从嵌套字典获取值

        Args:
            config: 配置字典
            key: 点号分隔的键

        Returns:
            (是否找到, 值)
        """
        keys = key.split('.')
        current = config

        for k in keys:
            if isinstance(current, dict) and k in current:
                current = current[k]
            else:
                return False, None

        return True, current

    def _apply_env_overrides(self, config: dict[str, Any]) -> dict[str, Any]:
        """应用环境变量覆盖

        扫描所有以 SILICONBASE_ 开头的环境变量，
        将其转换为配置键并覆盖到配置中。

        Args:
            config: 原始配置

        Returns:
            合并后的配置
        """
        result = config.copy()

        for env_name, env_value in os.environ.items():
            if env_name.startswith("SILICONBASE_") and env_name != "SILICONBASE_CONFIG_PATH":
                # 转换环境变量名为配置键
                # SILICONBASE_SERVICES__POSTGRESQL__HOST -> services.postgresql.host
                key = env_name[12:].lower().replace('__', '.')

                try:
                    parsed_value = self._parse_env_value(env_value)
                    self._set_nested_value(result, key, parsed_value)
                    logger.debug(f"[UnifiedConfig] 环境变量覆盖: {key} = {parsed_value}")
                except ConfigurationError:
                    # 向上传播解析错误
                    raise

        return result

    def _load_config(self) -> None:
        """加载配置

        加载顺序:
        1. 从YAML文件加载基础配置
        2. 应用环境变量覆盖

        Raises:
            ConfigurationError: 配置加载失败
        """
        try:
            # 1. 查找并加载YAML配置
            config_path = self._find_config_file()
            yaml_config = self._load_yaml_config(config_path)

            # 2. 应用环境变量覆盖
            self._config = self._apply_env_overrides(yaml_config)

            logger.info("[UnifiedConfig] 配置加载完成，环境变量优先级已应用")

        except ConfigurationError:
            # 向上传播配置错误
            raise
        except Exception as e:
            logger.error(f"[SILENT_FAILURE_BLOCKED] 配置加载失败: {e}")
            raise ConfigurationError(f"配置加载失败: {e}") from e

    def reload(self) -> None:
        """重新加载配置"""
        logger.info("[UnifiedConfig] 重新加载配置...")
        with self._lock:
            self._config = {}
            self._load_config()
        logger.info("[UnifiedConfig] 配置重新加载完成")

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值

        优先级: 环境变量 > YAML配置 > 默认值

        Args:
            key: 配置键（支持点号分隔，如 "services.postgresql.host"）
            default: 默认值，当找不到配置时返回

        Returns:
            配置值
        """
        # 1. 检查环境变量
        found, value = self._get_from_env(key)
        if found:
            return value

        # 2. 检查YAML配置
        found, value = self._get_nested_value(self._config, key)
        if found:
            return value

        # 3. 返回默认值
        return default

    def get_required(self, key: str) -> Any:
        """获取必需的配置值

        如果配置不存在，抛出 ConfigurationError

        Args:
            key: 配置键

        Returns:
            配置值

        Raises:
            ConfigurationError: 配置不存在
        """
        # 1. 检查环境变量
        found, value = self._get_from_env(key)
        if found:
            return value

        # 2. 检查YAML配置
        found, value = self._get_nested_value(self._config, key)
        if found:
            return value

        # 配置不存在 - 禁止静默失败
        logger.error(f"[SILENT_FAILURE_BLOCKED] 必需的配置项不存在: {key}")
        raise ConfigurationError(f"必需的配置项不存在: {key}")

    def get_service(self, name: str) -> ServiceConfig:
        """获取服务配置

        Args:
            name: 服务名称，如 "postgresql", "redis", "api" 等

        Returns:
            ServiceConfig 服务配置对象

        Raises:
            ConfigurationError: 服务配置不存在或无效
        """
        service_key = f"services.{name}"

        # 获取服务配置字典
        found, svc = self._get_nested_value(self._config, service_key)

        if not found:
            # 检查环境变量
            env_found, env_svc = self._get_from_env(service_key)
            if env_found and isinstance(env_svc, dict):
                svc = env_svc
            else:
                logger.error(f"[SILENT_FAILURE_BLOCKED] 服务配置未找到: {name}")
                raise ConfigurationError(f"服务配置未找到: {name}")

        if not isinstance(svc, dict):
            logger.error(f"[SILENT_FAILURE_BLOCKED] 服务 {name} 配置必须是字典类型，当前类型: {type(svc).__name__}")
            raise ConfigurationError(f"服务 {name} 配置必须是字典类型，当前类型: {type(svc).__name__}")

        # 获取host（必需）
        host = svc.get("host")
        if not host:
            # 检查环境变量
            env_host = os.environ.get(f"{name.upper()}_HOST")
            if env_host:
                host = env_host
            else:
                logger.error(f"[SILENT_FAILURE_BLOCKED] 服务 {name} 缺少host配置")
                raise ConfigurationError(f"服务 {name} 缺少host配置")

        # 获取port（必需）
        port = svc.get("port")
        if port is None:
            # 检查环境变量
            env_port = os.environ.get(f"{name.upper()}_PORT")
            if env_port:
                try:
                    port = int(env_port)
                except ValueError as _exc:
                    logger.error(f"[SILENT_FAILURE_BLOCKED] 服务 {name} 的环境变量端口无效: {env_port}")
                    raise ConfigurationError(f"服务 {name} 的环境变量端口无效: {env_port}") from _exc
            else:
                logger.error(f"[SILENT_FAILURE_BLOCKED] 服务 {name} 缺少port配置")
                raise ConfigurationError(f"服务 {name} 缺少port配置")

        if not isinstance(port, int) or port < 1 or port > 65535:
            logger.error(f"[SILENT_FAILURE_BLOCKED] 服务 {name} 的port必须是1-65535的整数，当前值: {port}")
            raise ConfigurationError(f"服务 {name} 的port必须是1-65535的整数，当前值: {port}")

        # 获取scheme（可选，默认http）
        scheme = svc.get("scheme", "http")
        if not isinstance(scheme, str) or scheme not in ("http", "https"):
            logger.error(f"[SILENT_FAILURE_BLOCKED] 服务 {name} 的scheme必须是http或https，当前值: {scheme}")
            raise ConfigurationError(f"服务 {name} 的scheme必须是http或https，当前值: {scheme}")

        # 获取timeout（可选，默认30）
        timeout = svc.get("timeout", 30)
        try:
            timeout = int(timeout)
        except (ValueError, TypeError) as _exc:
            logger.error(f"[SILENT_FAILURE_BLOCKED] 服务 {name} 的timeout必须是整数，当前值: {timeout}")
            raise ConfigurationError(f"服务 {name} 的timeout必须是整数，当前值: {timeout}") from _exc

        # 获取额外配置
        extra = {k: v for k, v in svc.items() if k not in ("host", "port", "scheme", "timeout")}

        return ServiceConfig(
            host=host,
            port=port,
            scheme=scheme,
            timeout=timeout,
            extra=extra
        )

    def get_timeout(self, category: str = "default") -> int:
        """获取超时配置

        Args:
            category: 超时类别，如 "default", "api", "db", "ai" 等

        Returns:
            超时时间（秒）

        Raises:
            ConfigurationError: 超时配置无效
        """
        timeout_key = f"timeouts.{category}"

        # 获取超时值
        found, timeout = self._get_nested_value(self._config, timeout_key)

        if not found:
            # 检查环境变量
            env_timeout = os.environ.get(f"TIMEOUT_{category.upper()}")
            if env_timeout:
                try:
                    timeout = int(env_timeout)
                    logger.debug(f"[UnifiedConfig] 从环境变量获取超时: {category} = {timeout}")
                except ValueError as _exc:
                    logger.error(f"[SILENT_FAILURE_BLOCKED] 超时配置 {category} 的环境变量值无效: {env_timeout}")
                    raise ConfigurationError(f"超时配置 {category} 的环境变量值无效: {env_timeout}") from _exc
            else:
                # 使用默认超时
                default_timeouts = {
                    "default": 30,
                    "api": 60,
                    "db": 30,
                    "ai": 120,
                    "cache": 5
                }
                timeout = default_timeouts.get(category, 30)
                logger.debug(f"[UnifiedConfig] 使用默认超时: {category} = {timeout}")

        # 验证超时值
        try:
            timeout = int(timeout)
        except (ValueError, TypeError) as _exc:
            logger.error(f"[SILENT_FAILURE_BLOCKED] 超时配置 {category} 必须是整数，当前值: {timeout}")
            raise ConfigurationError(f"超时配置 {category} 必须是整数，当前值: {timeout}") from _exc

        if timeout < 1:
            logger.error(f"[SILENT_FAILURE_BLOCKED] 超时配置 {category} 必须大于0，当前值: {timeout}")
            raise ConfigurationError(f"超时配置 {category} 必须大于0，当前值: {timeout}")

        if timeout > 3600:
            logger.error(f"[SILENT_FAILURE_BLOCKED] 超时配置 {category} 不能超过3600秒，当前值: {timeout}")
            raise ConfigurationError(f"超时配置 {category} 不能超过3600秒，当前值: {timeout}")

        return timeout

    def get_cors_origins(self) -> list[str]:
        """获取CORS配置

        Returns:
            CORS允许的源列表

        Raises:
            ConfigurationError: CORS配置无效
        """
        cors_key = "cors.origins"

        found, origins = self._get_nested_value(self._config, cors_key)

        if not found:
            # 检查环境变量
            env_origins = os.environ.get("CORS_ORIGINS")
            if env_origins:
                try:
                    import json
                    origins = json.loads(env_origins)
                except json.JSONDecodeError:
                    # 尝试按逗号分割
                    origins = [o.strip() for o in env_origins.split(',') if o.strip()]

        if origins is None:
            # 默认允许所有
            logger.debug("[UnifiedConfig] 使用默认CORS配置: ['*']")
            return ["*"]

        # 验证类型
        if isinstance(origins, str):
            origins = [origins]

        if not isinstance(origins, list):
            logger.error(f"[SILENT_FAILURE_BLOCKED] CORS origins必须是列表，当前类型: {type(origins).__name__}")
            raise ConfigurationError(f"CORS origins必须是列表，当前类型: {type(origins).__name__}")

        # 验证每个origin
        validated_origins = []
        for origin in origins:
            if not isinstance(origin, str):
                logger.error(f"[SILENT_FAILURE_BLOCKED] CORS origin必须是字符串，当前值: {origin}")
                raise ConfigurationError(f"CORS origin必须是字符串，当前值: {origin}")
            validated_origins.append(origin)

        return validated_origins

    def get_database_url(self, db_name: str = "default") -> str:
        """获取数据库连接URL

        Args:
            db_name: 数据库配置名称

        Returns:
            数据库连接URL

        Raises:
            ConfigurationError: 数据库配置无效
        """
        db_key = f"databases.{db_name}"

        found, db_config = self._get_nested_value(self._config, db_key)

        if not found and (db_name == "default" or db_name == "postgresql"):
            # 尝试从服务配置获取postgresql
            try:
                svc = self.get_service("postgresql")
                db_config = {
                    "host": svc.host,
                    "port": svc.port,
                    "database": svc.extra.get("database", "siliconbase"),
                    "user": svc.extra.get("user", "postgres"),
                    "password": svc.extra.get("password", "")
                }
            except ConfigurationError:
                pass

        if not db_config or not isinstance(db_config, dict):
            logger.error(f"[SILENT_FAILURE_BLOCKED] 数据库配置未找到: {db_name}")
            raise ConfigurationError(f"数据库配置未找到: {db_name}")

        # 获取必需字段
        host = db_config.get("host")
        port = db_config.get("port")
        database = db_config.get("database")
        user = db_config.get("user")
        password = db_config.get("password")

        if not all([host, port, database, user]):
            missing = []
            if not host:
                missing.append("host")
            if not port:
                missing.append("port")
            if not database:
                missing.append("database")
            if not user:
                missing.append("user")
            logger.error(f"[SILENT_FAILURE_BLOCKED] 数据库配置 {db_name} 缺少字段: {', '.join(missing)}")
            raise ConfigurationError(f"数据库配置 {db_name} 缺少字段: {', '.join(missing)}")

        # 构建连接URL
        password_part = f":{password}" if password else ""
        return f"postgresql://{user}{password_part}@{host}:{port}/{database}"

    def get_all_config(self) -> dict[str, Any]:
        """获取所有配置（用于调试）

        Returns:
            完整的配置字典（深拷贝）
        """
        import copy
        return copy.deepcopy(self._config)

    def is_config_changed(self) -> bool:
        """检查配置文件是否已修改

        Returns:
            配置文件是否已修改
        """
        if self._config_file_path is None:
            return False

        try:
            current_mtime = self._config_file_path.stat().st_mtime
            return current_mtime > self._config_mtime
        except OSError:
            return False


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════

def get_unified_config() -> UnifiedConfig:
    """获取统一配置管理器实例

    Returns:
        UnifiedConfig 实例
    """
    return UnifiedConfig()


# 全局单例实例（延迟初始化）
_unified_config: UnifiedConfig | None = None

def get_config() -> UnifiedConfig:
    """获取全局配置实例

    Returns:
        UnifiedConfig 实例
    """
    global _unified_config
    if _unified_config is None:
        _unified_config = UnifiedConfig()
    return _unified_config


# ═══════════════════════════════════════════════════════════════
# 【文件总结性注释】
# ═══════════════════════════════════════════════════════════════
#
# 【文件角色】
# core/config_unified.py 是 SiliconBase V5 项目的 "统一配置管理器" 模块。
# 它提供了一种更简洁、更严格的方式来管理后端服务配置。
#
# 核心定位：
#   - 统一配置管理
#   - 环境变量优先级支持
#   - 静默失败阻断
#
# 主要职责：
#   1. 配置加载：从YAML文件加载配置，支持环境变量覆盖
#   2. 服务配置管理：提供类型安全的服务配置获取
#   3. 超时配置管理：统一管理各类超时设置
#   4. CORS配置管理：管理跨域配置
#
# 【静默失败阻断机制】
#
# 所有配置获取方法都遵循以下原则：
#   - 配置文件读取失败 -> ConfigurationError + ERROR日志
#   - 环境变量解析失败 -> ConfigurationError + ERROR日志
#   - 服务配置获取失败 -> ConfigurationError + ERROR日志
#   - 任何无效返回 -> ConfigurationError + ERROR日志
#
# 【配置优先级】
#
# 配置获取的优先级（从高到低）：
#   1. 环境变量（SILICONBASE_XXX）
#   2. YAML配置文件（config/unified.yaml 或 config/global.yaml）
#   3. 默认值（仅限非关键配置）
#
# 【使用示例】
#
# 1. 获取服务配置：
#    from core.config_unified import UnifiedConfig
#    config = UnifiedConfig()
#    pg_service = config.get_service("postgresql")
#    print(pg_service.base_url)  # http://localhost:5432
#
# 2. 获取超时配置：
#    timeout = config.get_timeout("api")  # 默认60秒
#
# 3. 获取CORS配置：
#    origins = config.get_cors_origins()  # ["http://localhost:3000"]
#
# 4. 获取数据库URL：
#    db_url = config.get_database_url()
#
# 5. 使用便捷函数：
#    from core.config_unified import get_config
#    config = get_config()
#
# =============================================================================
