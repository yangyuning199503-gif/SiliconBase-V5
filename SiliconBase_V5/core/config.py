#!/usr/bin/env python3                          # 指定Python3解释器执行此脚本
"""
配置中心 V5.1 - 单例，只读 YAML，支持多租户配置隔离
第十层基础设施：ConfigManager支持用户级配置覆盖

版本历史:
- 2026-02-21: 初始版本，支持热加载，增加回滚机制
- 2026-02-26: 增加多租户配置隔离，支持用户级配置覆盖
- 2026-03-09: 增加部署模式配置 (local/cloud/hybrid)
"""
import os  # 导入操作系统模块，用于环境变量和路径
import re  # 导入正则表达式模块，用于环境变量解析

try:
    from dotenv import load_dotenv
    # 在读取任何数据库相关环境变量之前，先尝试加载项目根目录的 .env。
    # 这保证了无论是通过 start_unified.py 启动，还是直接 import core.config，
    # 都能拿到用户本地配置的 PostgreSQL 密码等敏感信息。
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=False)
except Exception:
    pass

import json  # 导入JSON模块，用于用户配置存储
import logging  # 导入日志模块，用于记录日志
import threading  # 导入线程模块，用于线程锁
import time  # 导入时间模块，用于延时
from pathlib import Path  # 从pathlib导入Path，用于路径操作
from typing import Any

import yaml  # 导入YAML模块，用于配置文件解析

# 使用依赖管理工具处理可选依赖                   # 注释：依赖管理
from .utils.dependency_utils import rwlock_dep, watchdog_dep  # 导入依赖管理工具

# ========================================
# 部署模式配置
# ========================================
# 部署模式: local(本地) / cloud(云端) / hybrid(混合)
# 优先级: 环境变量 > 配置文件 > 默认值(local)
# 注意：实际部署模式通过 config.get_deploy_mode() 获取，支持动态配置
_VALID_DEPLOY_MODES = ["local", "cloud", "hybrid"]

# 模块级 DEPLOY_MODE（向后兼容）
# 实际使用时应调用 config.get_deploy_mode() 获取最新值
DEPLOY_MODE = os.getenv("DEPLOY_MODE", "local")
if DEPLOY_MODE not in _VALID_DEPLOY_MODES:
    import warnings
    warnings.warn(
        f"未知的部署模式 '{DEPLOY_MODE}'，使用默认的 'local' 模式。可选值: {', '.join(_VALID_DEPLOY_MODES)}",
        stacklevel=2,
    )
    DEPLOY_MODE = "local"



# SecurityWarning 定义（用于弱密码警告）
class SecurityWarning(UserWarning):
    """安全警告 - 使用弱密码或默认密码时发出"""
    pass

# 【企业级合规】导入核心异常类
try:
    from core.exceptions import ConfigError
except ImportError:
    # 如果exceptions模块不可用，定义本地ConfigError
    class ConfigError(Exception):
        """配置错误 - 配置加载/验证失败时抛出"""
        pass

# watchdog 依赖                                  # 注释：watchdog依赖处理
Observer = watchdog_dep.get_class("observers.Observer")   # 获取Observer类
FileSystemEventHandler = watchdog_dep.get("events.FileSystemEventHandler", object)   # 获取事件处理器基类
WATCHDOG_AVAILABLE = watchdog_dep.available      # 标记watchdog是否可用

# readerwriterlock 依赖                          # 注释：rwlock依赖处理
# P0-005修复: 确保rwlock永远不会为None             # 修复注释
rwlock = rwlock_dep.get("rwlock") if rwlock_dep.available else rwlock_dep.fallback_class   # 获取rwlock或回退类
if rwlock is None:                               # 如果rwlock仍为None
    rwlock = rwlock_dep.fallback_class           # 使用回退类

logger = logging.getLogger(__name__)             # 获取当前模块的日志记录器


class ConfigFileHandler(FileSystemEventHandler):   # 定义配置文件事件处理器类
    def __init__(self, config_instance):           # 初始化方法
        self.config = config_instance              # 保存配置实例引用

    def on_modified(self, event):                  # 文件修改回调方法
        if event.src_path.endswith('.yaml'):       # 如果修改的是yaml文件
            self.config.reload()                   # 触发配置热重载


class UserConfigStore:                             # 定义用户配置存储类
    """
    用户配置存储

    管理用户级配置，支持内存和文件存储
    """

    def __init__(self, storage_dir: str | None = None):   # 初始化方法
        """
        初始化用户配置存储

        Args:
            storage_dir: 用户配置存储目录
        """
        base_dir = Path(__file__).parent.parent    # 获取项目根目录
        self._storage_dir = Path(storage_dir) if storage_dir else base_dir / "data" / "user_configs"   # 设置存储目录
        self._storage_dir.mkdir(parents=True, exist_ok=True)   # 创建目录（如果不存在）

        # 内存缓存                                   # 注释：缓存机制
        self._cache: dict[str, dict[str, Any]] = {}   # 用户配置缓存字典
        self._cache_lock = threading.RLock()         # 缓存读写锁

        # 加载现有用户配置                           # 注释：初始化加载
        self._load_all_configs()                     # 加载所有用户配置

    def _get_user_file(self, user_id: str) -> Path:   # 定义获取用户文件路径的私有方法
        """获取用户配置文件路径"""                   # 方法文档字符串
        return self._storage_dir / f"{user_id}.json"   # 返回JSON文件路径

    def _load_all_configs(self):                   # 定义加载所有配置的私有方法
        """加载所有用户配置"""                       # 方法文档字符串
        for file_path in self._storage_dir.glob("*.json"):   # 遍历所有JSON文件
            user_id = file_path.stem                 # 从文件名获取用户ID
            try:                                     # 异常处理
                with open(file_path, encoding='utf-8') as f:   # 打开文件
                    self._cache[user_id] = json.load(f)   # 解析JSON并存入缓存
            except Exception as e:                   # 加载失败
                logger.warning(f"[UserConfigStore] 加载用户配置失败 {user_id}: {e}")   # 记录警告

    def get(self, user_id: str) -> dict[str, Any]:   # 定义获取用户配置的方法
        """获取用户配置"""                           # 方法文档字符串
        with self._cache_lock:                       # 获取缓存锁
            if user_id not in self._cache:           # 如果缓存中不存在
                # 尝试从文件加载                     # 注释：从文件加载
                file_path = self._get_user_file(user_id)   # 获取文件路径
                if file_path.exists():               # 如果文件存在
                    try:                             # 异常处理
                        with open(file_path, encoding='utf-8') as f:   # 打开文件
                            self._cache[user_id] = json.load(f)   # 加载到缓存
                    except Exception as e:           # 加载失败
                        logger.warning(f"[UserConfigStore] 加载用户配置失败 {user_id}: {e}")   # 记录警告
                        self._cache[user_id] = {}    # 设为空字典
                else:                                # 文件不存在
                    self._cache[user_id] = {}        # 设为空字典

            return self._cache[user_id].copy()       # 返回配置的副本

    def set(self, user_id: str, key: str, value: Any):   # 定义设置用户配置的方法
        """设置用户配置"""                           # 方法文档字符串
        with self._cache_lock:                       # 获取缓存锁
            if user_id not in self._cache:           # 如果用户不在缓存中
                self._cache[user_id] = {}            # 创建空配置

            # 支持点号分隔的嵌套键                   # 注释：嵌套键支持
            keys = key.split(".")                    # 按点分割键
            config = self._cache[user_id]            # 获取用户配置
            for k in keys[:-1]:                      # 遍历除最后一个外的键
                if k not in config or not isinstance(config[k], dict):   # 如果不存在或不是字典
                    config[k] = {}                   # 创建空字典
                config = config[k]                   # 进入下一层
            config[keys[-1]] = value                 # 设置最终值

            # 持久化到文件                           # 注释：持久化
            self._save_user_config(user_id)          # 保存到文件

    def delete(self, user_id: str, key: str):        # 定义删除用户配置项的方法
        """删除用户配置项"""                         # 方法文档字符串
        with self._cache_lock:                       # 获取缓存锁
            if user_id not in self._cache:           # 如果用户不在缓存中
                return                               # 直接返回

            keys = key.split(".")                    # 按点分割键
            config = self._cache[user_id]            # 获取用户配置
            for k in keys[:-1]:                      # 遍历除最后一个外的键
                if k not in config:                  # 如果不存在
                    return                           # 直接返回
                config = config[k]                   # 进入下一层

            if keys[-1] in config:                   # 如果最终键存在
                del config[keys[-1]]                 # 删除键
                self._save_user_config(user_id)      # 保存到文件

    def clear(self, user_id: str):                   # 定义清空用户配置的方法
        """清空用户配置"""                           # 方法文档字符串
        with self._cache_lock:                       # 获取缓存锁
            self._cache[user_id] = {}                # 清空缓存
            file_path = self._get_user_file(user_id)   # 获取文件路径
            if file_path.exists():                   # 如果文件存在
                file_path.unlink()                   # 删除文件

    def get_all_keys(self, user_id: str) -> list[str]:   # 定义获取所有配置键的方法
        """获取用户的所有配置键"""                   # 方法文档字符串
        config = self.get(user_id)                   # 获取用户配置
        keys = []                                    # 初始化键列表

        def collect_keys(d: dict, prefix: str = ""):   # 定义递归收集键的内部函数
            for k, v in d.items():                   # 遍历字典
                full_key = f"{prefix}.{k}" if prefix else k   # 构建完整键名
                if isinstance(v, dict):              # 如果值是字典
                    collect_keys(v, full_key)        # 递归收集
                else:                                # 不是字典
                    keys.append(full_key)            # 添加到列表

        collect_keys(config)                         # 开始收集
        return keys                                  # 返回键列表

    def _save_user_config(self, user_id: str):       # 定义保存用户配置的私有方法
        """保存用户配置到文件"""                     # 方法文档字符串
        file_path = self._get_user_file(user_id)     # 获取文件路径
        try:                                         # 异常处理
            with open(file_path, 'w', encoding='utf-8') as f:   # 打开文件写入
                json.dump(self._cache[user_id], f, ensure_ascii=False, indent=2)   # 保存为JSON
        except Exception as e:                       # 保存失败
            logger.error(f"[UserConfigStore] 保存用户配置失败 {user_id}: {e}")   # 记录错误


class Config:                                      # 定义配置中心类
    """
    配置中心 - 支持多租户配置隔离

    单例模式，支持热加载，用户级配置覆盖全局配置
    """

    _instance = None                               # 类属性：单例实例
    _lock = threading.Lock()                       # 类属性：单例锁
    _rw_lock = None                                # 类属性：读写锁（延迟初始化）

    # 默认用户ID                                   # 类属性注释
    DEFAULT_USER_ID = "default_user"               # 默认用户ID常量

    def __new__(cls):                              # 重写new方法实现单例
        if cls._instance is None:                  # 如果实例不存在
            with cls._lock:                        # 获取单例锁
                if cls._instance is None:          # 双重检查
                    cls._instance = super().__new__(cls)   # 创建实例
                    cls._instance._initialized = False   # 标记未初始化
        return cls._instance                       # 返回实例

    def __init__(self):                            # 初始化方法
        if self._initialized:                      # 如果已初始化
            return                                 # 直接返回
        self._initialized = True                   # 标记已初始化

        # 延迟初始化读写锁（避免导入时副作用）       # 注释：延迟初始化
        if Config._rw_lock is None:                # 如果读写锁未初始化
            if rwlock is not None and rwlock_dep.available:   # 如果rwlock可用
                Config._rw_lock = rwlock.RWLockWrite()   # 创建读写锁
            else:                                    # 不可用
                Config._rw_lock = rwlock_dep.fallback_class.RWLockWrite()   # 使用回退类

        self._config: dict[str, Any] = {}          # 实例属性：全局配置字典
        self._roles: dict[str, Any] = {}           # 实例属性：角色配置字典
        self._risk_map: dict[str, Any] = {}        # 实例属性：风险映射字典
        self._change_listeners: list = []          # 实例属性：配置变更监听器列表

        # 多租户配置支持                             # 注释：多租户支持
        self._user_config_store = UserConfigStore()   # 创建用户配置存储
        self._user_config_cache: dict[str, dict[str, Any]] = {}   # 用户配置缓存

        # 全局配置版本号（用于配置刷新冲突检测）     # 注释：版本号机制
        self._config_version = 0                     # 初始化版本号为0
        self._version_lock = threading.Lock()        # 【新增】版本号锁，保证线程安全

        # 【企业级合规】强制PostgreSQL配置验证      # 注释：企业合规
        self._validate_enterprise_database_config()   # 验证企业级数据库配置

        self._load_config()                          # 加载配置
        self._start_watch()                          # 启动文件监控

    def _load_config(self):                          # 定义加载配置的私有方法
        base_dir = Path(__file__).parent.parent      # 获取项目根目录
        global_path = base_dir / "config" / "global.yaml"   # 全局配置文件路径
        roles_path = base_dir / "config" / "roles.yaml"     # 角色配置文件路径
        risk_map_path = base_dir / "config" / "risk_map.yaml"   # 风险映射文件路径

        if global_path.exists():                     # 如果全局配置文件存在
            try:
                with open(global_path, encoding="utf-8") as f:   # 打开文件
                    raw_config = yaml.safe_load(f) or {}   # 解析YAML

                # 展开环境变量（新增）
                try:
                    self._config = self._expand_env_vars(raw_config)
                    logger.info("[Config] 全局配置加载完成，已展开环境变量")
                except Exception as e:
                    logger.error(f"[Config] 展开环境变量失败: {e}")
                    # 失败时使用原始配置，不中断启动
                    self._config = raw_config
                    logger.warning("[Config] 使用原始配置（未展开环境变量）")

            except yaml.YAMLError as e:
                logger.error(f"[Config] YAML解析错误: {e}")
                raise  # YAML错误是严重的，必须抛出
            except OSError as e:
                logger.error(f"[Config] 读取配置文件失败: {e}")
                raise  # IO错误必须抛出
        else:                                        # 文件不存在
            self._config = self._default_global_config()   # 使用默认配置
            os.makedirs(global_path.parent, exist_ok=True)   # 创建目录
            with open(global_path, "w", encoding="utf-8") as f:   # 创建文件
                yaml.dump(self._config, f, allow_unicode=True, indent=2)   # 写入默认配置

        # 【P0修复】加载 local.yaml 并合并到全局配置，local 优先级高于 global
        local_path = base_dir / "config" / "local.yaml"
        if local_path.exists():
            try:
                with open(local_path, encoding="utf-8") as f:
                    local_config = yaml.safe_load(f) or {}
                if local_config:
                    # 【P0-013修复】local.yaml 也需要展开环境变量占位符
                    local_config = self._expand_env_vars(local_config)
                    self._deep_merge(self._config, local_config)
                    logger.info("[Config] local.yaml 加载、展开环境变量并合并完成")
            except Exception as e:
                logger.warning(f"[Config] local.yaml 加载失败: {e}")

        if roles_path.exists():                      # 如果角色配置文件存在
            with open(roles_path, encoding="utf-8") as f:   # 打开文件
                self._roles = yaml.safe_load(f) or {}   # 解析YAML
        else:                                        # 文件不存在
            self._roles = self._default_roles_config()   # 使用默认配置
            os.makedirs(roles_path.parent, exist_ok=True)   # 创建目录
            with open(roles_path, "w", encoding="utf-8") as f:   # 创建文件
                yaml.dump(self._roles, f, allow_unicode=True, indent=2)   # 写入默认配置

        if risk_map_path.exists():                   # 如果风险映射文件存在
            with open(risk_map_path, encoding="utf-8") as f:   # 打开文件
                self._risk_map = yaml.safe_load(f) or {}   # 解析YAML
        else:                                        # 文件不存在
            self._risk_map = self._default_risk_map()   # 使用默认配置
            os.makedirs(risk_map_path.parent, exist_ok=True)   # 创建目录
            with open(risk_map_path, "w", encoding="utf-8") as f:   # 创建文件
                yaml.dump(self._risk_map, f, allow_unicode=True, indent=2)   # 写入默认配置

        # DB-001修复: PostgreSQL密码安全检查         # 注释：安全修复
        self._check_postgresql_password_security()   # 检查PostgreSQL密码安全

    def _validate_enterprise_database_config(self):
        """
        【企业级合规】验证PostgreSQL数据库配置

        企业级部署强制要求：
        1. 必须配置PostgreSQL数据库
        2. 禁止使用SQLite（GPL许可证风险）
        3. 无配置时明确报错，禁止静默降级

        Raises:
            ConfigError: 未配置PostgreSQL时抛出，阻止系统启动

        注意：开发/测试环境可设置环境变量 SILICONBASE_SKIP_PG_VALIDATION=1 跳过验证
        """
        # 【阶段0-止血】允许开发/测试环境跳过PG验证，避免缺依赖时系统完全无法启动
        if os.environ.get("SILICONBASE_SKIP_PG_VALIDATION", "").lower() in ("1", "true", "yes", "on"):
            logger.warning("[Enterprise] 跳过PostgreSQL配置验证（SILICONBASE_SKIP_PG_VALIDATION已设置）")
            return

        # 检查PostgreSQL URL配置（新格式）
        pg_url = os.environ.get("SILICONBASE_PG_URL")
        pg_password = os.environ.get("SILICONBASE_PG_PASSWORD")

        # 检查PostgreSQL独立配置项（旧格式兼容）
        pg_host = os.environ.get("POSTGRES_HOST")
        _ = os.environ.get("POSTGRES_PORT")
        pg_db = os.environ.get("POSTGRES_DB")
        pg_user = os.environ.get("POSTGRES_USER")
        env_pg_password = os.environ.get("POSTGRES_PASSWORD")

        # 判断是否有完整配置
        has_new_format = pg_url and pg_password
        has_old_format = pg_host and pg_db and pg_user and env_pg_password

        if not (has_new_format or has_old_format):
            # 【企业级合规】明确报错，禁止降级
            logger.error("=" * 70)
            logger.error("[Enterprise] ████████████████████████████████████████████████████")
            logger.error("[Enterprise] ██  企业级部署错误：未配置PostgreSQL数据库")
            logger.error("[Enterprise] ████████████████████████████████████████████████████")
            logger.error("[Enterprise]")
            logger.error("[Enterprise] 原因：企业级部署必须使用PostgreSQL数据库")
            logger.error("[Enterprise]       禁止使用SQLite（GPL许可证风险）")
            logger.error("[Enterprise]")
            logger.error("[Enterprise] 解决方案：请在.env文件中配置以下环境变量：")
            logger.error("[Enterprise]")
            logger.error("[Enterprise] 方式1（推荐）- 使用连接URL：")
            logger.error("[Enterprise]   SILICONBASE_PG_URL=postgresql://user:password@host:5432/dbname")
            logger.error("[Enterprise]   SILICONBASE_PG_PASSWORD=your_password")
            logger.error("[Enterprise]")
            logger.error("[Enterprise] 方式2 - 使用独立配置项：")
            logger.error("[Enterprise]   POSTGRES_HOST=localhost")
            logger.error("[Enterprise]   POSTGRES_PORT=5432")
            logger.error("[Enterprise]   POSTGRES_DB=siliconbase")
            logger.error("[Enterprise]   POSTGRES_USER=postgres")
            logger.error("[Enterprise]   POSTGRES_PASSWORD=your_password")
            logger.error("[Enterprise]")
            logger.error("[Enterprise] 参考模板：.env.enterprise.template")
            logger.error("=" * 70)

            raise ConfigError(
                "企业级部署必须配置PostgreSQL数据库。\n"
                "SQLite因GPL许可证风险被禁止。\n"
                "请配置环境变量：SILICONBASE_PG_URL, SILICONBASE_PG_PASSWORD\n"
                "或：POSTGRES_HOST, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD\n"
                "参考模板：.env.enterprise.template"
            )

        # 记录验证通过
        if has_new_format:
            logger.info("[Enterprise] PostgreSQL企业级配置验证通过（URL格式）")
        else:
            logger.info("[Enterprise] PostgreSQL企业级配置验证通过（独立配置项）")

    def _expand_env_vars(self, value):
        """
        展开 ${VAR:default} 或 ${VAR} 格式的环境变量

        支持格式:
        - ${VAR} -> 从环境变量读取，不存在返回空字符串
        - ${VAR:default} -> 从环境变量读取，不存在返回default

        Args:
            value: 需要展开的值（字符串、字典、列表）
        Returns:
            展开后的值（字符串类型会尝试自动转换为int/float/bool）
        Raises:
            TypeError: 当value类型不支持时
            re.error: 当正则表达式处理失败时
        """
        if isinstance(value, str):
            pattern = r'\$\{([^}:]+)(?::([^}]*))?\}'

            def replacer(match):
                var_name = match.group(1)
                default_val = match.group(2) if match.group(2) is not None else ''

                # 从环境变量读取
                env_val = os.environ.get(var_name)

                if env_val is not None:
                    logger.debug(f"[Config] 环境变量 {var_name}={env_val}")
                    return env_val
                else:
                    if default_val:
                        logger.debug(f"[Config] 环境变量 {var_name} 未设置，使用默认值: {default_val}")
                    else:
                        logger.warning(f"[Config] 环境变量 {var_name} 未设置且无默认值")
                    return default_val

            try:
                result = re.sub(pattern, replacer, value)
                # 尝试类型转换，修复类型丢失BUG
                return self._parse_env_value(result)
            except re.error as e:
                logger.error(f"[Config] 正则表达式错误: {e}, value={value}")
                raise  # 不静默，抛出异常

        elif isinstance(value, dict):
            # 递归处理字典
            result = {}
            for k, v in value.items():
                try:
                    result[k] = self._expand_env_vars(v)
                except (TypeError, re.error) as e:
                    logger.error(f"[Config] 处理字典项 {k} 失败: {e}")
                    raise  # 不静默，抛出异常
            return result

        elif isinstance(value, list):
            # 递归处理列表
            result = []
            for i, item in enumerate(value):
                try:
                    result.append(self._expand_env_vars(item))
                except (TypeError, re.error) as e:
                    logger.error(f"[Config] 处理列表项 [{i}] 失败: {e}")
                    raise  # 不静默，抛出异常
            return result

        else:
            # 其他类型原样返回
            return value

    def _check_postgresql_password_security(self):   # 定义检查PostgreSQL密码安全的私有方法
        """
        检查PostgreSQL密码安全配置

        【安全策略】
        - 优先从环境变量POSTGRES_PASSWORD获取密码
        - 禁止使用已知弱密码列表中的密码
        - 云端模式(SAAS=true)强制要求环境变量设置密码
        - 本地模式检测到默认密码时强制要求修改
        """
        # 【安全修复】定义已知弱密码黑名单
        WEAK_PASSWORDS = {
            "password", "123456", "admin", "root",
            "postgres", "postgresql", "default", "12345678", "qwerty",
            "password123", "admin123", "root123", "test", "test123"
        }

        # 获取PostgreSQL配置                         # 注释：获取配置
        pg_config = self._config.get("postgresql", {})   # 获取PostgreSQL配置
        config_password = pg_config.get("password", "")     # 获取配置文件中的密码

        # 【安全修复】优先从环境变量获取密码
        env_password = os.environ.get("POSTGRES_PASSWORD")
        if env_password:
            # 使用环境变量密码覆盖配置
            if "postgresql" not in self._config:
                self._config["postgresql"] = {}
            self._config["postgresql"]["password"] = env_password
            password = env_password
            logger.info("[SECURITY] PostgreSQL密码已从环境变量POSTGRES_PASSWORD加载")
        else:
            password = config_password

        # 检查是否为弱密码                         # 注释：弱密码检查
        is_weak_password = password in WEAK_PASSWORDS

        # 检查云端模式                               # 注释：云端模式检查
        is_saas_mode = os.environ.get("SAAS", "").lower() == "true"   # 检查SAAS模式

        if is_saas_mode:     # 云端模式安全策略
            if not env_password:     # 未设置环境变量
                logger.error("[SECURITY_ERROR] 云端部署模式(SAAS=true)必须使用环境变量POSTGRES_PASSWORD设置密码!")   # 记录错误
                raise ValueError(                          # 抛出异常
                    "云端部署模式下必须设置POSTGRES_PASSWORD环境变量。\n"
                    "请设置环境变量: export POSTGRES_PASSWORD=your_secure_password\n"
                    "注意: 密码长度必须至少12字符，且包含大小写字母、数字和特殊字符"
                )
            if is_weak_password:  # 使用弱密码
                logger.error("[SECURITY_ERROR] 云端部署模式禁止使用弱密码!")
                raise ValueError("云端部署模式必须使用强密码（至少12字符，包含大小写字母、数字和特殊字符）")
            # 密码强度验证
            if len(password) < 12:
                logger.error("[SECURITY_ERROR] 云端部署模式密码长度必须至少12字符!")
                raise ValueError("云端部署模式密码长度必须至少12字符")

        if is_weak_password:                      # 检测到弱密码
            # 【安全修复】本地模式也强制要求修改弱密码
            logger.error("[SECURITY_ERROR] 检测到使用弱密码或默认密码，存在严重安全风险!")
            logger.error("[SECURITY_ERROR] 请立即通过环境变量设置强密码: export POSTGRES_PASSWORD=your_secure_password")
            # 仅在非SAAS模式下发出警告，但仍强制要求修改
            if not is_saas_mode:
                import warnings
                warnings.warn(
                    "使用弱密码或默认密码存在安全风险! "
                    "请设置环境变量POSTGRES_PASSWORD使用强密码（至少12字符）",
                    SecurityWarning,
                    stacklevel=2
                )

    def _start_watch(self):                          # 定义启动文件监控的私有方法
        # P0-003修复: 检查watchdog是否可用           # 注释：可用性检查
        if not WATCHDOG_AVAILABLE:                   # 如果watchdog不可用
            logger.debug("[Config] watchdog不可用，跳过文件监控")   # 记录调试日志
            return                                   # 直接返回

        # 紧急修复: 检查Observer是否为None             # 注释：Observer检查
        if Observer is None:                         # 如果Observer为None
            logger.debug("[Config] Observer不可用，跳过文件监控")   # 记录调试日志
            return                                   # 直接返回

        config_dir = Path(__file__).parent.parent / "config"   # 获取配置目录
        event_handler = ConfigFileHandler(self)      # 创建事件处理器
        self._observer = Observer()                  # 创建Observer实例
        self._observer.schedule(event_handler, str(config_dir), recursive=False)   # 调度监控
        self._observer.start()                       # 启动监控
        threading.Thread(target=self._watch_loop, daemon=True).start()   # 启动监控线程

    def _watch_loop(self):                           # 定义监控循环的私有方法
        # DESIGN-NOTE: 配置文件监控守护线程，设计为长期运行   # 设计说明
        # 中断机制：1) 主进程退出时daemon线程自动终止 2) Observer异常时主动停止   # 中断说明
        # 安全退出：try-except捕获异常，停止observer并释放资源   # 安全退出说明
        try:                                         # 异常处理
            while True:                              # 无限循环
                time.sleep(1)                        # 每秒检查一次
        except Exception as e:                       # 捕获异常
            logger.error(f"Watch loop error: {e}")   # 记录错误
            self._observer.stop()                    # 停止Observer
        self._observer.join()                        # 等待Observer结束

    def reload(self):                                # 定义热重载方法
        """热重载配置，失败时回滚"""                 # 方法文档字符串
        logger.info("[Config] 配置热重载中...")      # 记录日志
        # 用于事件通知的配置副本                     # 注释：事件通知
        new_config = None                            # 初始化新配置

        with self._rw_lock.gen_wlock():              # 获取写锁
            # 备份旧配置                             # 注释：备份
            old_config = self._config.copy()         # 备份全局配置
            old_roles = self._roles.copy()           # 备份角色配置
            old_risk_map = self._risk_map.copy()     # 备份风险映射

            try:                                     # 尝试加载新配置
                self._load_config()                  # 加载配置
                # 可选的验证：检查必要字段是否存在     # 注释：验证
                if "ai" not in self._config:         # 如果缺少ai字段
                    raise ValueError("加载后的配置缺少 'ai' 字段，回滚")   # 抛出异常
                # 递增配置版本号（用于缓存刷新检测）     # 注释：版本号递增
                self._config_version += 1
                logger.info(f"[Config] 配置版本号已更新: {self._config_version}")
                print("所有配置已热加载")              # 打印信息
                # 复制新配置用于事件通知（在锁外触发）   # 注释：复制配置
                new_config = self._config.copy()     # 复制新配置
            except Exception as e:                   # 加载失败
                # 回滚                               # 注释：回滚
                self._config = old_config            # 恢复全局配置
                self._roles = old_roles              # 恢复角色配置
                self._risk_map = old_risk_map        # 恢复风险映射
                print(f"配置热加载失败，已回滚: {e}")   # 打印错误
                return                               # 返回

        # ====== 在锁外触发配置变更事件（避免死锁）======   # 注释：事件触发
        if new_config is not None:                   # 如果新配置加载成功
            try:                                     # 尝试触发事件
                from core.sync.event_bus import event_bus  # 延迟导入事件总线
                event_bus.emit("config_changed", new_config)   # 触发配置变更事件
            except Exception as e:                   # 触发失败
                logger.error(f"触发配置变更事件失败: {e}")   # 记录错误
            # 通知所有监听器                         # 注释：通知监听器
            self._notify_listeners()                 # 通知监听器
            # 【P0-016】配置变更时通知 FeatureManager 重新评估功能启停
            try:
                from core.feature_manager import feature_manager
                feature_manager.reload_from_config()
            except Exception as e:
                logger.error(f"[Config] 通知 FeatureManager 配置变更失败: {e}")
            # 刷新AI Provider（支持动态切换AI后端）   # 注释：刷新Provider
            self._refresh_ai_provider()              # 刷新AI Provider
        # ==================================           # 结束标记

    def _refresh_ai_provider(self):                  # 定义刷新AI Provider的私有方法
        """刷新AI Provider配置"""                    # 方法文档字符串
        try:                                         # 异常处理
            # 延迟导入避免循环依赖                   # 注释：延迟导入
            from core.providers.ai_provider_factory import AIProviderFactory  # 导入Provider工厂
            AIProviderFactory.refresh_provider()     # 刷新Provider
            logger.info("[Config] AI Provider已刷新")   # 记录日志
        except Exception as e:                       # 刷新失败
            logger.error(f"[Config] 刷新AI Provider失败: {e}")   # 记录错误

    def _notify_listeners(self):                     # 定义通知监听器的私有方法
        """通知所有监听器配置已变更"""                 # 方法文档字符串
        for listener in self._change_listeners:      # 遍历所有监听器
            try:                                     # 异常处理
                listener(self._config)               # 调用监听器
            except Exception as e:                   # 通知失败
                logger.error(f"[Config] 通知监听器失败: {e}")   # 记录错误

    def add_change_listener(self, callback):         # 定义添加监听器的方法
        """添加配置变更监听器"""                     # 方法文档字符串
        self._change_listeners.append(callback)      # 添加到列表

    def remove_change_listener(self, callback):      # 定义移除监听器的方法
        """移除配置变更监听器"""                     # 方法文档字符串
        if callback in self._change_listeners:       # 如果在列表中
            self._change_listeners.remove(callback)   # 移除

    # ========== 全局配置方法 ==========             # 注释：全局配置方法区域

    # 核心业务AI无权修改的受保护命名空间
    _PROTECTED_NAMESPACES = {"ai", "postgresql", "features", "trading", "agent", "safety"}

    def set(self, key: str, value: any, source: str = "system"):             # 定义设置配置项的方法
        """设置配置项（支持热重载）

        设置配置值，同时自动递增版本号。

        Args:
            key: 配置键（支持点号分隔的嵌套键）
            value: 配置值
            source: 调用方身份标识，"system" 为系统级，其他为业务AI/子代理等

        Returns:
            bool: 是否设置成功

        Raises:
            PermissionError: 业务AI/子代理尝试修改受保护的核心配置时
            Exception: 设置失败时抛出异常
        """
        # 【写权限锁】业务AI无权修改核心底座配置
        top_namespace = key.split(".")[0]
        if source != "system" and top_namespace in self._PROTECTED_NAMESPACES:
            logger.warning(f"[Config-Guard] 拒绝非系统来源 '{source}' 修改受保护配置: {key}")
            raise PermissionError(f"配置键 '{key}' 属于受保护命名空间 '{top_namespace}'，仅允许 system 来源修改")

        try:
            with self._rw_lock.gen_wlock():              # 获取写锁
                keys = key.split(".")                    # 按点分割键
                config = self._config                    # 获取配置
                for k in keys[:-1]:                      # 遍历除最后一个外的键
                    if k not in config:                  # 如果不存在
                        config[k] = {}                   # 创建空字典
                    config = config[k]                   # 进入下一层
                config[keys[-1]] = value                 # 设置值

            # 持久化到文件                             # 注释：持久化
            self._save_config()                          # 保存配置

            # 配置变更时自动更新版本号                   # 注释：版本号更新
            self.increment_version()                     # 增加配置版本号

            return True
        except Exception as e:
            logger.error(f"[Config] 设置配置失败 {key}: {e}", exc_info=True)
            raise

    def _save_config(self):                          # 定义保存配置的私有方法
        """保存配置到文件"""                         # 方法文档字符串
        try:                                         # 异常处理
            base_dir = Path(__file__).parent.parent   # 获取项目根目录
            global_path = base_dir / "config" / "global.yaml"   # 全局配置文件路径
            with open(global_path, "w", encoding="utf-8") as f:   # 打开文件
                yaml.dump(self._config, f, allow_unicode=True, indent=2)   # 保存YAML
            logger.info("[Config] 配置已保存到文件")   # 记录日志
        except Exception as e:                       # 保存失败
            logger.error(f"[Config] 保存配置失败: {e}")   # 记录错误
            raise                                      # 重新抛出异常，禁止静默失败

    def increment_version(self):                     # 定义增加版本号的方法
        """配置更新时调用，增加版本号

        用于配置刷新冲突检测，各模块可通过get_version()获取当前版本号
        并与本地缓存的版本号对比，检测配置是否已变更。

        此方法线程安全，使用内部锁保证版本号递增的原子性。
        """                                          # 方法文档字符串
        with self._version_lock:                     # 【新增】获取版本号锁，保证线程安全
            self._config_version += 1                # 版本号加1
            version = self._config_version           # 保存当前版本号用于日志
        logger.info(f"[Config] 配置版本号已递增到: {version}")   # 记录日志（在锁外）

    def get_version(self) -> int:                    # 定义获取版本号的方法
        """获取当前配置版本号

        获取当前配置的全局版本号，用于检测配置是否已变更。

        Returns:
            int: 当前配置版本号，每次配置更新后自动递增

        Examples:
            >>> config.get_version()
            5

        Note:
            此方法线程安全，使用内部锁保证读取的一致性。
        """                                          # 方法文档字符串
        with self._version_lock:                     # 【新增】获取版本号锁，保证线程安全
            return self._config_version              # 返回版本号

    def _key_to_env_var(self, key: str) -> str:      # 定义键转环境变量名的私有方法
        """
        将配置键转换为环境变量名

        转换规则:
        - 点号分隔转换为双下划线: "ai.default_model" -> "SILICONBASE_AI__DEFAULT_MODEL"
        - 统一大写

        Args:
            key: 配置键（支持点号分隔）

        Returns:
            环境变量名
        """
        return f"SILICONBASE_{key.upper().replace('.', '__')}"   # 转换并返回

    def _parse_env_value(self, value: str) -> Any:   # 定义解析环境变量值的私有方法
        """
        解析环境变量值为适当的Python类型

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
        """
        if not isinstance(value, str):               # 如果不是字符串
            return value                             # 直接返回

        # 尝试解析布尔值                             # 注释：布尔值解析
        lower_val = value.lower().strip()            # 转小写并去空白
        if lower_val in ('true', '1', 'yes', 'on'):   # 如果是真值
            return True                              # 返回True
        if lower_val in ('false', '0', 'no', 'off'):   # 如果是假值
            return False                             # 返回False

        # 尝试解析null                               # 注释：null解析
        if lower_val in ('null', 'none', ''):        # 如果是null
            return None                              # 返回None

        # 尝试解析数字                               # 注释：数字解析
        try:                                         # 异常处理
            # 尝试整数                               # 注释：整数
            if value.lstrip('-').isdigit():          # 如果是数字
                return int(value)                    # 返回整数
            # 尝试浮点数                             # 注释：浮点数
            if '.' in value and value.replace('.', '').replace('-', '').isdigit():   # 如果是浮点数
                return float(value)                  # 返回浮点数
        except ValueError:                           # 解析失败
            pass                                     # 继续

        # 尝试解析JSON（列表或字典）                   # 注释：JSON解析
        if (value.startswith('[') and value.endswith(']')) or \
           (value.startswith('{') and value.endswith('}')):   # 如果是JSON格式
            try:                                     # 异常处理
                return json.loads(value)             # 解析JSON
            except json.JSONDecodeError:             # 解析失败
                pass                                 # 继续

        # 默认返回字符串                             # 注释：默认字符串
        return value                                 # 返回字符串

    def _get_from_env(self, key: str) -> tuple[bool, Any]:   # 定义从环境变量获取的私有方法
        """
        从环境变量获取配置值

        Args:
            key: 配置键

        Returns:
            (是否找到, 值)
        """
        env_var = self._key_to_env_var(key)          # 转换为环境变量名
        value = os.environ.get(env_var)              # 获取环境变量

        if value is not None:                        # 如果找到
            return True, self._parse_env_value(value)   # 返回True和解析后的值

        # 也检查小写版本（向后兼容）                   # 注释：向后兼容
        env_var_lower = env_var.lower()              # 转小写
        value = os.environ.get(env_var_lower)        # 获取环境变量
        if value is not None:                        # 如果找到
            return True, self._parse_env_value(value)   # 返回True和解析后的值

        return False, None                           # 返回False和None

    def _get_from_global_config(self, key: str) -> tuple[bool, Any]:   # 定义从全局配置获取的私有方法
        """
        从全局配置获取值

        Args:
            key: 配置键（支持点号分隔）

        Returns:
            (是否找到, 值)
        """
        keys = key.split(".")                        # 按点分割键
        value = self._config                         # 获取配置

        for k in keys:                               # 遍历键
            if isinstance(value, dict):              # 如果是字典
                value = value.get(k)                 # 获取值
            else:                                    # 不是字典
                return False, None                   # 返回False和None

        if value is not None:                        # 如果找到
            return True, value                       # 返回True和值

        return False, None                           # 返回False和None

    def _get_from_user_config(self, user_id: str, key: str) -> tuple[bool, Any]:   # 定义从用户配置获取的私有方法
        """
        从用户配置获取值

        Args:
            user_id: 用户ID
            key: 配置键（支持点号分隔）

        Returns:
            (是否找到, 值)
        """
        user_config = self._user_config_store.get(user_id)   # 获取用户配置

        keys = key.split(".")                        # 按点分割键
        value = user_config                          # 获取配置

        for k in keys:                               # 遍历键
            if isinstance(value, dict):              # 如果是字典
                value = value.get(k)                 # 获取值
            else:                                    # 不是字典
                return False, None                   # 返回False和None

        if value is not None:                        # 如果找到
            return True, value                       # 返回True和值

        return False, None                           # 返回False和None

    def get(self, key: str, default=None, user_id: str = None):   # 定义统一配置获取入口
        """
        统一配置获取入口

        优先级: 环境变量 > 用户配置 > 全局配置 > 默认值

        ARCH-001修复: 统一配置获取方式，解决直接读环境变量和配置文件不一致的问题

        Args:
            key: 配置键（支持点号分隔，如 "ai.default_model"）
            default: 默认值，当所有来源都找不到时返回
            user_id: 用户ID，如果提供则检查用户级配置

        Returns:
            配置值

        Examples:
            >>> config.get("ai.default_model")
            'qwen3:8b'
            >>> config.get("ai.timeout", 30)
            30
            >>> config.get("voice.wake_words", user_id="user_123")
            ['你好元旦']

        环境变量格式:
            SILICONBASE_AI__DEFAULT_MODEL=qwen2.5:7b
            SILICONBASE_AI__TIMEOUT=60
            SILICONBASE_VOICE__WAKE_WORDS='["你好", "元旦"]'
        """
        with self._rw_lock.gen_rlock():              # 获取读锁
            # 1. 检查环境变量（最高优先级）             # 注释：步骤1
            found, value = self._get_from_env(key)   # 从环境变量获取
            if found:                                # 如果找到
                logger.debug(f"[Config] 从环境变量获取配置: {key} = {value}")   # 记录调试日志
                return value                         # 返回值

            # 2. 检查用户配置（如果提供了user_id）       # 注释：步骤2
            if user_id is not None:                  # 如果提供了用户ID
                found, value = self._get_from_user_config(user_id, key)   # 从用户配置获取
                if found:                            # 如果找到
                    logger.debug(f"[Config] 从用户配置获取: {key} = {value}")   # 记录调试日志
                    return value                     # 返回值

            # 3. 检查全局配置                          # 注释：步骤3
            found, value = self._get_from_global_config(key)   # 从全局配置获取
            if found:                                # 如果找到
                # P0-005: 向后兼容处理                 # 注释：向后兼容
                if key == "wake_word":               # 如果是旧版wake_word
                    wake_words = self.get("voice.wake_words")   # 获取新版wake_words
                    if wake_words is not None and isinstance(wake_words, list) and len(wake_words) > 0:   # 如果存在
                        import warnings  # 导入警告模块
                        warnings.warn(                # 发出弃用警告
                            "配置项 'wake_word' 已弃用，请使用 'voice.wake_words' 替代",
                            DeprecationWarning,
                            stacklevel=3
                        )
                        return wake_words[0]         # 返回第一个唤醒词
                elif key == "voice.wake_words":      # 如果是新版wake_words
                    old_wake_word = self._config.get("wake_word")   # 获取旧版wake_word
                    if old_wake_word is not None:    # 如果存在旧版
                        import warnings  # 导入警告模块
                        warnings.warn(                # 发出弃用警告
                            "配置项 'wake_word' 已弃用，请使用 'voice.wake_words'（列表格式）替代",
                            DeprecationWarning,
                            stacklevel=3
                        )
                        return [old_wake_word] if isinstance(old_wake_word, str) else old_wake_word   # 转换为列表
                return value                         # 返回值

            # P0-005: 向后兼容处理（在全局配置未找到时）   # 注释：向后兼容2
            if key == "wake_word":                   # 如果是旧版wake_word
                wake_words = self.get("voice.wake_words")   # 获取新版wake_words
                if wake_words is not None and isinstance(wake_words, list) and len(wake_words) > 0:   # 如果存在
                    import warnings  # 导入警告模块
                    warnings.warn(                    # 发出弃用警告
                        "配置项 'wake_word' 已弃用，请使用 'voice.wake_words' 替代",
                        DeprecationWarning,
                        stacklevel=3
                    )
                    return wake_words[0]             # 返回第一个唤醒词
            elif key == "voice.wake_words":          # 如果是新版wake_words
                old_wake_word = self._config.get("wake_word")   # 获取旧版wake_word
                if old_wake_word is not None:        # 如果存在旧版
                    import warnings  # 导入警告模块
                    warnings.warn(                    # 发出弃用警告
                        "配置项 'wake_word' 已弃用，请使用 'voice.wake_words'（列表格式）替代",
                        DeprecationWarning,
                        stacklevel=3
                    )
                    return [old_wake_word] if isinstance(old_wake_word, str) else old_wake_word   # 转换为列表

            # 4. 返回默认值                            # 注释：步骤4
            return default                           # 返回默认值

    def is_feature_enabled(self, feature_name: str) -> bool:
        """
        查询 Feature Flag 功能开关是否开启

        读取优先级：环境变量 > 配置文件 > 默认关闭
        环境变量格式：SILICONBASE_FEATURES__<FEATURE_NAME>=true

        Args:
            feature_name: 功能开关名称，如 "new_architecture", "v2_perception"

        Returns:
            bool: 开关是否开启

        Examples:
            >>> config.is_feature_enabled("v2_memory")
            False
            >>> config.is_feature_enabled("new_architecture")
            False
        """
        key = f"features.{feature_name}"
        value = self.get(key, default=False)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        return bool(value)

    def get_role_prompt(self, role: str, **kwargs) -> str:   # 定义获取角色提示词的方法
        with self._rw_lock.gen_rlock():              # 获取读锁
            role_data = self._roles.get(role, {})    # 获取角色数据
            if isinstance(role_data, str):           # 如果是字符串
                return role_data                     # 直接返回
            prompt = role_data.get("system_prompt", "")   # 获取系统提示词
            if not prompt:                           # 如果为空
                return ""                            # 返回空字符串
            try:                                     # 尝试格式化
                return prompt.format(**kwargs)       # 格式化并返回
            except Exception as e:                   # 格式化失败
                logger.error(f"Prompt format error: {e}")   # 记录错误
                return prompt                        # 返回原始提示词

    def get_risk_map(self) -> dict:                  # 定义获取风险映射的方法
        with self._rw_lock.gen_rlock():              # 获取读锁
            return self._risk_map.copy()             # 返回风险映射副本

    def get_voice_announce_config(self, key: str = None, default=None):
        """获取语音播报配置

        Args:
            key: 配置键（可选），如 "process.enabled", "priority.ai_output"
                  不传key则返回整个announce配置字典
            default: 默认值

        Returns:
            语音播报配置值或配置字典
        """
        with self._rw_lock.gen_rlock():
            announce_config = self.get("voice.announce", {})
            if key is None:
                return announce_config
            # 支持嵌套键，如 "process.enabled"
            keys = key.split(".")
            value = announce_config
            for k in keys:
                if isinstance(value, dict) and k in value:
                    value = value[k]
                else:
                    return default
            return value

    # ========== 多租户配置方法 ==========             # 注释：多租户配置方法区域

    def get_user_config(self, user_id: str, key: str, default=None):   # 定义获取用户级配置的方法
        """
        获取用户级配置（向后兼容方法）

        优先级: 环境变量 > 用户配置 > 全局配置 > 默认值

        ARCH-001: 此方法现在调用统一的 get() 方法，确保配置获取方式一致

        Args:
            user_id: 用户ID
            key: 配置键（支持点号分隔的嵌套键）
            default: 默认值

        Returns:
            配置值

        Examples:
            >>> config.get_user_config("user_123", "ai.default_model")
            'qwen3:8b'
        """
        # 使用统一的 get() 方法，传入 user_id          # 注释：统一调用
        return self.get(key, default=default, user_id=user_id)   # 调用get方法

    def set_user_config(self, user_id: str, key: str, value):   # 定义设置用户级配置的方法
        """
        设置用户级配置

        Args:
            user_id: 用户ID
            key: 配置键（支持点号分隔的嵌套键）
            value: 配置值
        """
        self._user_config_store.set(user_id, key, value)   # 设置用户配置
        logger.info(f"[Config] 用户 {user_id} 配置已更新: {key}")   # 记录日志

        # 触发用户配置变更事件                       # 注释：事件触发
        try:                                         # 异常处理
            from core.sync.event_bus import event_bus  # 延迟导入事件总线
            event_bus.emit("user_config_changed", {   # 触发用户配置变更事件
                "user_id": user_id,                  # 用户ID
                "key": key,                          # 键
                "value": value                       # 值
            })
        except Exception as e:                       # 触发失败
            logger.error(f"触发用户配置变更事件失败: {e}")   # 记录错误

    def delete_user_config(self, user_id: str, key: str):   # 定义删除用户级配置项的方法
        """
        删除用户级配置项

        Args:
            user_id: 用户ID
            key: 配置键
        """
        self._user_config_store.delete(user_id, key)   # 删除配置
        logger.info(f"[Config] 用户 {user_id} 配置已删除: {key}")   # 记录日志

    def clear_user_config(self, user_id: str):       # 定义清空用户级配置的方法
        """
        清空用户级配置

        Args:
            user_id: 用户ID
        """
        self._user_config_store.clear(user_id)       # 清空配置
        logger.info(f"[Config] 用户 {user_id} 配置已清空")   # 记录日志

    def reload_user_config(self, user_id: str):      # 定义热加载用户配置的方法
        """
        热加载用户配置

        从存储重新加载用户配置

        Args:
            user_id: 用户ID
        """
        # 清除缓存，下次获取时会重新加载               # 注释：清除缓存
        if user_id in self._user_config_cache:       # 如果在缓存中
            del self._user_config_cache[user_id]     # 删除缓存

        logger.info(f"[Config] 用户 {user_id} 配置已热加载")   # 记录日志

    def get_user_config_keys(self, user_id: str) -> list[str]:   # 定义获取用户所有配置键的方法
        """
        获取用户的所有配置键

        Args:
            user_id: 用户ID

        Returns:
            配置键列表
        """
        return self._user_config_store.get_all_keys(user_id)   # 获取所有键

    def get_user_all_configs(self, user_id: str) -> dict[str, Any]:   # 定义获取用户所有配置的方法
        """
        获取用户的所有配置

        Args:
            user_id: 用户ID

        Returns:
            用户配置字典
        """
        return self._user_config_store.get(user_id)   # 获取所有配置

    def get_deploy_mode(self) -> str:
        """
        获取部署模式

        优先级: 环境变量 > 配置文件 > 默认值(local)

        Returns:
            str: 部署模式 (local/cloud/hybrid)
        """
        # 1. 检查环境变量（最高优先级）
        env_mode = os.environ.get("DEPLOY_MODE")
        if env_mode and env_mode in _VALID_DEPLOY_MODES:
            return env_mode

        # 2. 检查配置文件
        config_mode = self.get("deploy_mode")
        if config_mode and config_mode in _VALID_DEPLOY_MODES:
            return config_mode

        # 3. 返回默认值
        return "local"

    def validate_vision_config(self) -> tuple[bool, str]:
        """
        验证视觉配置有效性

        Returns:
            (是否有效, 错误信息)
        """

        vision_config = self._config.get("ai", {}).get("vision", {})

        # 检查显式开关
        enabled = vision_config.get("enabled", True)
        if not enabled:
            logger.info("[Config] 视觉感知已显式禁用")
            return False, "视觉感知已禁用"

        # 检查默认后端
        default_backend = vision_config.get("default_backend")
        if not default_backend:
            logger.info("[Config] 视觉模型未配置: 缺少default_backend")
            return False, "缺少default_backend"

        backends = vision_config.get("backends", {})
        if default_backend not in backends:
            error_msg = f"默认后端'{default_backend}'未在backends中定义"
            logger.error(f"[Config] {error_msg}")
            return False, error_msg

        # 验证阈值范围
        threshold = self._config.get("vision.change_threshold", 5)
        if not isinstance(threshold, int):
            logger.warning("[Config] vision.change_threshold类型错误，使用默认值5")
            self._config["vision.change_threshold"] = 5
        elif not (1 <= threshold <= 20):
            logger.warning(f"[Config] vision.change_threshold={threshold}超出范围[1-20]，使用默认值5")
            self._config["vision.change_threshold"] = 5

        logger.info(f"[Config] 视觉配置验证通过: backend={default_backend}, threshold={threshold}")
        return True, ""

    def get_effective_config(self, user_id: str, key: str = None) -> Any:   # 定义获取生效配置的方法
        """
        获取生效的配置（用户级覆盖全局配置）

        Args:
            user_id: 用户ID
            key: 配置键，为None时返回所有生效配置

        Returns:
            生效的配置值或配置字典
        """
        if key:                                      # 如果指定了键
            return self.get_user_config(user_id, key)   # 获取用户配置

        # 合并全局配置和用户配置                       # 注释：合并配置
        with self._rw_lock.gen_rlock():              # 获取读锁
            effective_config = self._config.copy()   # 复制全局配置

        user_config = self._user_config_store.get(user_id)   # 获取用户配置
        self._deep_merge(effective_config, user_config)   # 深度合并

        return effective_config                      # 返回生效配置

    def _deep_merge(self, base: dict, override: dict):   # 定义深度合并字典的私有方法
        """深度合并字典"""                           # 方法文档字符串
        for key, value in override.items():          # 遍历覆盖字典
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):   # 如果都是字典
                self._deep_merge(base[key], value)   # 递归合并
            else:                                    # 否则
                base[key] = value                    # 直接覆盖

    def reset_user_config_to_default(self, user_id: str):   # 定义重置用户配置为默认值的方法
        """
        重置用户配置为默认值（清空用户级覆盖）

        Args:
            user_id: 用户ID
        """
        self._user_config_store.clear(user_id)       # 清空用户配置
        logger.info(f"[Config] 用户 {user_id} 配置已重置为默认值")   # 记录日志

    def get_user_config_summary(self, user_id: str) -> dict:   # 定义获取用户配置摘要的方法
        """
        获取用户配置摘要

        Args:
            user_id: 用户ID

        Returns:
            配置摘要字典
        """
        config_keys = self._user_config_store.get_all_keys(user_id)   # 获取所有键

        return {                                     # 返回摘要
            "user_id": user_id,                      # 用户ID
            "total_override_keys": len(config_keys),   # 覆盖键总数
            "override_keys": config_keys[:20],       # 覆盖键列表（最多20个）
            "has_custom_config": len(config_keys) > 0   # 是否有自定义配置
        }

    # ========== 用户级提示词模板覆盖方法 ==========

    def _get_user_prompt_dir(self, user_id: str) -> Path:
        """
        获取用户提示词存储目录

        Args:
            user_id: 用户ID

        Returns:
            用户提示词目录路径
        """
        base_dir = Path(__file__).parent.parent    # 获取项目根目录
        user_prompt_dir = base_dir / "data" / "user_prompts" / user_id / "modules"
        user_prompt_dir.mkdir(parents=True, exist_ok=True)   # 创建目录（如果不存在）
        return user_prompt_dir

    def get_user_prompt_module(self, user_id: str, module_id: str) -> str | None:
        """
        获取用户级提示词模块内容

        存储位置: data/user_prompts/{user_id}/modules/{module_id}.txt

        Args:
            user_id: 用户ID
            module_id: 模块ID

        Returns:
            用户级模块内容，如果不存在返回None

        Examples:
            >>> config.get_user_prompt_module("user_123", "identity")
            '用户自定义的身份定义内容...'
        """
        if not user_id or user_id == "default_user":
            return None

        try:
            user_prompt_dir = self._get_user_prompt_dir(user_id)
            module_file = user_prompt_dir / f"{module_id}.txt"

            if module_file.exists():
                with open(module_file, encoding='utf-8') as f:
                    content = f.read()
                logger.debug(f"[Config] 获取用户 {user_id} 的模块 {module_id} 内容成功")
                return content
            return None
        except Exception as e:
            logger.error(f"[Config] 获取用户提示词模块失败 {user_id}/{module_id}: {e}")
            return None

    def set_user_prompt_module(self, user_id: str, module_id: str, content: str) -> bool:
        """
        设置用户级提示词模块内容

        存储位置: data/user_prompts/{user_id}/modules/{module_id}.txt

        Args:
            user_id: 用户ID
            module_id: 模块ID
            content: 模块内容

        Returns:
            是否保存成功

        Examples:
            >>> config.set_user_prompt_module("user_123", "identity", "自定义内容...")
            True
        """
        if not user_id or user_id == "default_user":
            logger.warning("[Config] 无法为默认用户设置提示词模块")
            return False

        try:
            user_prompt_dir = self._get_user_prompt_dir(user_id)
            module_file = user_prompt_dir / f"{module_id}.txt"

            with open(module_file, 'w', encoding='utf-8') as f:
                f.write(content)

            logger.info(f"[Config] 用户 {user_id} 的模块 {module_id} 内容已保存")

            # 触发用户配置变更事件
            try:
                from core.sync.event_bus import event_bus  # 延迟导入事件总线
                event_bus.emit("user_prompt_module_changed", {
                    "user_id": user_id,
                    "module_id": module_id,
                    "action": "save"
                })
            except Exception as e:
                logger.error(f"触发用户提示词模块变更事件失败: {e}")

            return True
        except Exception as e:
            logger.error(f"[Config] 保存用户提示词模块失败 {user_id}/{module_id}: {e}")
            return False

    def delete_user_prompt_module(self, user_id: str, module_id: str) -> bool:
        """
        删除用户级提示词模块（恢复为全局默认）

        Args:
            user_id: 用户ID
            module_id: 模块ID

        Returns:
            是否删除成功
        """
        if not user_id or user_id == "default_user":
            return False

        try:
            user_prompt_dir = self._get_user_prompt_dir(user_id)
            module_file = user_prompt_dir / f"{module_id}.txt"

            if module_file.exists():
                module_file.unlink()
                logger.info(f"[Config] 用户 {user_id} 的模块 {module_id} 内容已删除")

                # 触发用户配置变更事件
                try:
                    from core.sync.event_bus import event_bus
                    event_bus.emit("user_prompt_module_changed", {
                        "user_id": user_id,
                        "module_id": module_id,
                        "action": "delete"
                    })
                except Exception as e:
                    logger.error(f"触发用户提示词模块变更事件失败: {e}")

                return True
            return False
        except Exception as e:
            logger.error(f"[Config] 删除用户提示词模块失败 {user_id}/{module_id}: {e}")
            return False

    def get_user_prompt_modules_list(self, user_id: str) -> list[str]:
        """
        获取用户所有自定义提示词模块ID列表

        Args:
            user_id: 用户ID

        Returns:
            模块ID列表
        """
        if not user_id or user_id == "default_user":
            return []

        try:
            user_prompt_dir = self._get_user_prompt_dir(user_id)
            if not user_prompt_dir.exists():
                return []

            modules = []
            for file_path in user_prompt_dir.glob("*.txt"):
                modules.append(file_path.stem)   # 去掉.txt后缀
            return modules
        except Exception as e:
            logger.error(f"[Config] 获取用户提示词模块列表失败 {user_id}: {e}")
            return []

    def clear_user_prompt_modules(self, user_id: str) -> bool:
        """
        清空用户所有自定义提示词模块

        Args:
            user_id: 用户ID

        Returns:
            是否清空成功
        """
        if not user_id or user_id == "default_user":
            return False

        try:
            user_prompt_dir = self._get_user_prompt_dir(user_id)
            if user_prompt_dir.exists():
                for file_path in user_prompt_dir.glob("*.txt"):
                    file_path.unlink()
                logger.info(f"[Config] 用户 {user_id} 的所有提示词模块已清空")
                return True
            return True  # 目录不存在也视为成功
        except Exception as e:
            logger.error(f"[Config] 清空用户提示词模块失败 {user_id}: {e}")
            return False

    # ========== 默认配置方法 ==========             # 注释：默认配置方法区域

    def _default_global_config(self) -> dict:        # 定义默认全局配置的私有方法
        return {                                     # 返回默认配置字典
            "scheme": "main",                        # 方案：main
            "deploy_mode": "full",                   # 部署模式：full
            "vector": {                              # 向量配置
                "embedding_model": "all-MiniLM-L6-v2",   # 嵌入模型
                "device": "cpu"                       # 设备：CPU
            },
            "evolution": {                           # 进化配置
                "enable_code_gen": True,             # 启用代码生成
                "require_user_approval": True,       # 需要用户批准
                "max_tool_generation_per_day": 5,    # 每天最大工具生成数
                "idle_threshold": 10                 # 空闲阈值
            },
            "task_orchestrator": {                   # 任务编排器配置
                "max_auto_tasks_per_hour": 20        # 每小时最大自动任务数
            },
            "heartbeat": {                           # 心跳配置
                "enabled": True,                     # 启用
                "interval": 0.1                      # 间隔0.1秒
            },
            "perception": {                          # 感知配置
                "process": {"enabled": True, "interval": 1},   # 进程感知
                "window": {"enabled": True, "interval": 1},    # 窗口感知
                "screen": {"enabled": False, "fps": 15, "ocr_enabled": False},   # 屏幕感知
                "global_view": {                     # 全局视图
                    "enabled": True,
                    "scan_on_startup": True,
                    "watch_directories": ["C:\\Program Files", "C:\\Program Files (x86)", "桌面", "开始菜单"]
                },
                "resource": {                        # 资源感知
                    "enabled": True,
                    "cpu_high_threshold": 80,        # CPU高阈值
                    "mem_high_threshold": 85,        # 内存高阈值
                    "low_memory_mode_threshold_mb": 8192   # 低内存模式阈值
                }
            },
            # DEPRECATED: wake_word 已弃用，请使用 voice.wake_words   # 弃用说明
            "wake_word": "元旦",                     # 保留向后兼容
            "task": {                                # 任务配置
                "max_concurrent": 1,                 # 最大并发数
                "default_timeout": 30,               # 默认超时
                "retry_count": 2,                    # 重试次数
                "interrupt_restore_timeout_hours": 24   # 中断恢复超时
            },
            "memory": {                              # 记忆配置
                "short_term_expire_hours": 1,        # 短期记忆过期时间
                "retrieval_top_k": 5,                # 检索TopK
                "encryption_enabled": False,         # 加密启用
                "backup_enabled": False,             # 备份启用
                "compression_enabled": True,         # 压缩启用
                "auto_cleanup": True                 # 自动清理
            },
            "voice": {                               # 语音配置
                "wake_words": ["硅基"],                 # 唤醒词列表（已修正为硅基）
                "model_path": "assets/models/vosk-model-cn-0.22",   # 模型路径
                "tts_engine": "piper",                 # TTS引擎
                "tts_speed": 1.0,                     # TTS语速倍率
                "tts_volume": 80,                     # TTS音量(0-100)
                "speaker_wav": None,                  # 说话人WAV
                "input_device_index": None,           # 输入设备索引
                "output_device_index": None,          # 输出设备索引
                "awake_timeout": 30,                  # 唤醒超时
                "ptt_timeout": 30,                    # PTT超时
                "wake_mode": "wake_word",             # 唤醒模式: wake_word / push_to_talk / both
                "announce_tools": True,               # 播报工具
                "control_words": {                    # 控制词
                    "pause": ["暂停", "停一下", "停止"],   # 暂停词
                    "resume": ["继续", "恢复"],          # 恢复词
                    "abort": ["结束任务", "关闭任务", "终止"]   # 中止词
                },
                "audio": {                            # 音频播放配置
                    "max_errors": 10,                 # 最大错误次数
                    "retry_interval_ms": 50,          # 重试间隔(毫秒)
                    "queue_timeout_ms": 100           # 队列获取超时(毫秒)
                },
                "announce": {                         # 语音播报配置（新增）
                    "enabled": True,                  # 总开关
                    "ai_output": True,                # AI原始输出播报（新增）
                    "process": {                      # 过程播报（可配置）
                        "enabled": True,              # 过程播报总开关
                        "thinking": True,             # "正在思考..."
                        "memory_query": True,         # "正在查询记忆..."
                        "tool_call": True,            # 工具调用播报
                        "task_status": True,          # 任务状态变化（暂停/恢复）
                        "min_interval": 5.0           # 最小播报间隔（秒）
                    },
                    "priority": {                     # 优先级配置
                        "ai_output": 0,               # AI输出最高（0=最高）
                        "tool_result": 1,             # 工具结果
                        "process": 2,                 # 过程播报最低
                        "interruptible": True         # 过程播报可被AI输出中断
                    }
                }
            },
            "mode": {                                # 模式配置
                "daily": {"interval": 30, "auto_think": True},   # 日常模式
                "focus": {"interval": 5, "auto_think": False},   # 专注模式
                "trading": {"interval": 10, "auto_think": False, "auto_trade": True}   # 交易模式
            },
            "auto_loop": {                           # 自动循环配置
                "enabled": False,                     # 启用状态
                "max_retries": 3,                     # 最大重试次数
                "blocked_risks": ["HIGH", "MEDIUM"],   # 阻塞的风险等级
                "task_timeout": 3600,                 # 任务超时
                "tasks": [                            # 任务列表
                    {"raw": "截屏保存到桌面", "risk": "LOW"},
                    {"raw": "备份当前项目", "risk": "MEDIUM"}
                ]
            },
            "ai": {                                  # AI配置
                # 【P0-014】统一为嵌套结构，与 local.yaml 对齐
                "ollama": {
                    "base_url": "http://localhost:11434",   # Ollama基础URL
                    "model": "qwen3:8b",                    # Ollama默认模型
                },
                "vision": {
                    "model": "qwen3-vl:2b",                 # 视觉模型
                },
                "executor": {
                    "model": "qwen3:8b",                    # 执行模型
                },
                "code": {
                    "model": "qwen3:8b",                    # 代码模型
                },
                "default_model": "qwen3:8b",              # 向后兼容：默认模型（顶层快捷访问）
                "timeout": 30,                            # 超时
                "temperature": 0.3,                       # 温度
                "reflector_temperature": 0.1,             # 反思温度
                "chat_temperature": 0.7,                  # 聊天温度
                "ark_api_key": "",                        # Ark API密钥
                "ark_model": "",                          # Ark模型
                "thinker_temperature": 0.3,               # 思考者温度
                "ark_base_url": "https://ark.cn-beijing.volces.com/api/v3"   # Ark基础URL
            },
            "postgresql": {                          # PostgreSQL配置
                "host": "localhost",                  # 主机
                "port": 5432,                         # 端口
                "database": "siliconbase",            # 数据库
                "user": "postgres",                   # 用户
                "password": "",                       # 密码（运行时从环境变量POSTGRES_PASSWORD读取）
                "min_connections": 10,                # 最小连接数（增加以应对高并发）
                "max_connections": 100                # 最大连接数（翻倍以应对全盘扫描）
            },
            "status_server": {                       # 状态服务器配置
                "host": "localhost",                  # 主机
                "port": 8600,                         # 端口
                "require_auth": False,                # 需要认证
                "token": ""                           # 令牌
            },
            "tools": {                               # 工具配置
                "auto_load": True,                    # 自动加载
                "watch_directory": "tools/",          # 监控目录
                "allow_dynamic_registration": True,   # 允许动态注册
                "require_confirmation": ["process_kill", "file_delete"],   # 需要确认的工具
                "tron_balance_updater": {             # Tron余额更新器
                    "excel_path": os.environ.get("TRON_EXCEL_PATH", ""),
                    "target_token": os.environ.get("TRON_TARGET_TOKEN", "TMacq4TDUw5q8NFBwmbY4RLXvzvG5JTkvi"),
                    "summary_sheet": os.environ.get("TRON_SUMMARY_SHEET", "合计"),
                    "delay": 0.2,
                    "retry": 2,
                    "api_key": os.environ.get("TRON_API_KEY", "")
                }
            },
            "security": {                            # 安全配置
                "deny_admin": True,                   # 拒绝管理员
                "allow_admin": False                  # 允许管理员
            },
            "logging": {                             # 日志配置
                "level": "INFO",                      # 级别
                "console_output": True,               # 控制台输出
                "file_output": False,                 # 文件输出
                "dir": "logs"                         # 目录
            },
            "enable": True,                          # 启用
            "binance": {                             # 币安配置
                "testnet_api_key": "",
                "testnet_api_secret": ""
            },
            "okx": {                                 # OKX配置
                "api_url": "https://www.okx.com",
                "demo_mode": True,
                "api_key": "",
                "api_secret": "",
                "passphrase": ""
            },
            "default_symbol": "BTCUSDT",             # 默认交易对
            "default_amount": 0.001,                 # 默认数量
            "risk_keywords": {                       # 风险关键词
                "HIGH": ["删除", "kill", "格式化", "rm -rf", "shutdown", "重启", "删除文件"],
                "MEDIUM": ["终止进程"],
                "LOW": ["写入", "修改", "移动", "复制", "重命名", "新建", "创建", "编辑", "读取", "查询", "查看", "打开", "列出", "截图", "ocr", "复制到剪贴板", "结束进程"]
            },
            "self_awareness": {                      # 自我意识配置
                "enabled": True,
                "express_interval": 300
            },
            "goal_system": {                         # 目标系统配置
                "enabled": True,
                "daily_goals": True
            },
            "moral_system": {                        # 道德系统配置
                "enabled": True,
                "strict_mode": True
            },
            "weak_connection": {                     # 弱连接配置
                "enabled": True,
                "probability": 0.3
            },
            "script_manager": {                      # 脚本管理器配置
                "enabled": True,
                "auto_discover": True
            },
            "daily_mode": {                          # 日常模式详细配置
                "random_thought_prob": 0.6,           # 随机思考概率
                "deep_thought_prob": 0.15,            # 深度思考概率
                "meditation_prob": 0.1,               # 冥想概率
                "self_check_prob": 0.08,              # 自检概率
                "random_script_prob": 0.05,           # 随机脚本概率
                "learn_prob": 0.02                    # 学习概率
            },
            "agent": {                               # Agent配置
                "max_steps": 20,                      # 最大步数
                "max_rounds": 15                      # 最大轮数
            },
            "global_view": {                         # 全局视图配置
                "max_scan_depth": 3,                  # 最大扫描深度
                "exclude_dirs": ["Windows", "Program Files", "Program Files (x86)"]   # 排除目录
            },
            "multi_tenant": {                        # 多租户配置
                "enabled": True,                      # 启用
                "max_users_per_instance": 1000,       # 每实例最大用户数
                "user_config_ttl_hours": 24,          # 用户配置TTL
                "isolation_level": "strict"           # 隔离级别：strict, relaxed
            }
        }

    def _default_roles_config(self) -> dict:         # 定义默认角色配置的私有方法
        return {                                     # 返回角色配置字典
            "analyst": """你现在是分析师。你的任务是分析用户的需求，拆解为可执行的步骤，输出结构化的执行计划。

  【核心规则】
  1. 你必须严格参考【用户历史对话记忆】里的内容，记住用户之前的问题和回答，当用户问之前的对话内容时，必须准确回答。
  2. 用户问"我刚刚问了你什么问题""我上一轮说了什么"这类问题时，直接从历史对话里提取用户上一轮的输入，准确回答，不要说你记不住。
  3. 用户问"我是第几次和你聊天"时，直接使用【对话统计】里的次数回答，不要编造内容。

  你的输出必须是一个严格的JSON对象，格式如下：
  {
    "action": "analysis",
    "steps": ["步骤1", "步骤2", "步骤3"],
    "thought": "你的分析思路"
  }

  要求：
  - 步骤必须具体、可执行，每个步骤对应一个工具调用。
  - 步骤数量控制在3-8步，不要过于繁琐。
  - 必须严格使用JSON格式，不要输出任何额外的解释和markdown标记。""",
            "decision_maker": """你现在是决策师。你的任务是根据分析师给出的步骤、当前环境以及已有的信息，选择要调用的具体工具和参数。

  【核心规则】
  1. 你必须严格参考【用户历史对话记忆】里的内容，记住用户之前的问题和你的回答，当用户问之前的对话内容时，必须准确回答。
  2. 用户问"我刚刚问了你什么问题""我上一轮说了什么"这类问题时，直接从历史对话里提取用户上一轮的输入，准确回答，不要说你记不住。
  3. 用户问"我是第几次和你聊天"时，直接使用【对话统计】里的次数回答，不要编造内容。

  **可用工具列表**（这是你唯一可以使用的工具，绝对不能虚构任何工具）：
  {tools_detailed}

  **重要限制**：
  - 你**只能**使用上面列表中列出的工具 `id`，不允许编造任何不在列表中的工具。
  - 每次输出**只能包含一个工具调用**，不能输出多个动作的数组。
  - 输出必须是一个**严格的 JSON 对象**，要么是 `{"action": "call_tool", "tool": "工具ID", "params": {...}}`，要么是 `{"action": "final_answer", "content": "回答内容"}`。
  - 工具名称必须与列表中的 `id` 完全一致（区分大小写）。
  - 参数名必须严格使用工具定义的键名，参数值必须符合参数要求（类型、枚举值等）。
  - **参数值必须有来源**：例如，调用 `mouse_click` 时，`x` 和 `y` 必须是从 `screen_ocr` 返回的坐标中计算出来的，不能随意编造。如果之前没有获取过坐标，必须先调用 `screen_ocr` 获取位置信息。
  - 如果某个工具需要 `hwnd`（窗口句柄），请确保已通过 `window_get` 等工具获取到有效的句柄值。
  - 如果工具的参数包含枚举值（如 `action` 只能取特定值），请严格使用枚举中列出的值，不要自创。

  **提示**：
  - 对于"找到输入框并点击"的需求，你应该先使用 `window_get` 定位窗口，然后使用 `screen_ocr` 获取窗口内的文本和位置，再使用 `mouse_click` 点击输入框。如果需要输入文本，使用 `keyboard_input`。如果需要回车发送，使用 `keyboard_input` 的 `keys: ["enter"]`。
  - 如果 `screen_ocr` 返回空，可以尝试使用 `window_rect` 获取窗口区域后，结合固定坐标点击（例如窗口中央），或使用 `window_focus` 激活窗口后发送 Tab 键切换焦点。
  - **操作原则**：
    - 在尝试点击或输入之前，应优先使用 `window_ocr` 或 `screen_ocr` 获取目标元素的位置坐标，然后使用 `mouse_click` 点击。
    - 如果没有坐标信息，不要凭空猜测，应调用 OCR 工具获取。
    - 对于"播放全部"这类需求，如果无法直接点击，可先调用 `window_ocr` 查找"播放全部"文本的位置，然后调用 `mouse_click` 点击。

  **正确示例**：
  - 用户说"打开计算器"，你应该输出：`{"action": "call_tool", "tool": "launch_app", "params": {"app_name": "calc"}}`
  - 用户说"点击屏幕上的'确定'按钮"，你应该输出：`{"action": "call_tool", "tool": "click_text", "params": {"text": "确定"}}`
  - 用户说"输入你好然后回车"，你应该先获取焦点窗口，然后输出：`{"action": "call_tool", "tool": "keyboard_input", "params": {"text": "你好"}}`，然后等待结果，再输出：`{"action": "call_tool", "tool": "keyboard_input", "params": {"keys": ["enter"]}}`

  现在，请根据分析师给出的步骤和当前环境，输出下一步要调用的工具（**仅一个 JSON 对象，不要数组**）。""",
            "executor": """你现在是执行监督员。你的任务是检查上一步工具执行的结果，判断任务是否完成，是否需要重试，是否需要调整步骤。

  【核心规则】
  1. 你必须严格参考【用户历史对话记忆】里的内容，记住用户之前的问题和回答，当用户问之前的对话内容时，必须准确回答。
  2. 用户问"我刚刚问了你什么问题""我上一轮说了什么"这类问题时，直接从历史对话里提取用户上一轮的输入，准确回答，不要说你记不住。
  3. 用户问"我是第几次和你聊天"时，直接使用【对话统计】里的次数回答，不要编造内容。

  你的输出必须是一个严格的JSON对象，格式只能是以下两种之一：
  1. 任务完成，输出最终答案：
  {
    "action": "final_answer",
    "content": "给用户的最终回答，简洁明了，符合用户需求"
  }

  2. 需要继续执行，输出下一步工具调用：
  {
    "action": "call_tool",
    "tool": "工具ID",
    "params": {"参数名": "参数值"}
  }

  要求：
  - 如果上一步工具执行成功，且所有步骤都已完成，必须输出 final_answer。
  - 如果上一步工具执行失败，必须分析失败原因，输出正确的重试工具调用，不要重复失败的操作。
  - 如果还有未完成的步骤，输出下一步要调用的工具。
  - 必须严格使用JSON格式，不要输出任何额外的解释和markdown标记。
  - 只能使用已有的工具ID，不能虚构工具。"""
        }

    def _default_risk_map(self) -> dict:             # 定义默认风险映射的私有方法
        return {                                     # 返回风险映射字典
            "file_delete": "HIGH",                   # 文件删除：高风险
            "process_kill": "HIGH",                  # 进程终止：高风险
            "vpn_connect": "HIGH",                   # VPN连接：高风险
            "vpn_check": "MEDIUM",                   # VPN检查：中风险
            "process_start": "MEDIUM",               # 进程启动：中风险
            "file_write": "MEDIUM",                  # 文件写入：中风险
            "file_move": "MEDIUM",                   # 文件移动：中风险
            "file_copy": "MEDIUM",                   # 文件复制：中风险
            "launch_app": "MEDIUM",                  # 启动应用：中风险
            "keyboard_input": "MEDIUM",              # 键盘输入：中风险
            "mouse_click": "MEDIUM",                 # 鼠标点击：中风险
            "window_focus": "MEDIUM",                # 窗口聚焦：中风险
            "window_action": "MEDIUM",               # 窗口操作：中风险
            "app_search": "MEDIUM",                  # 应用搜索：中风险
            "click_text": "MEDIUM",                  # 点击文本：中风险
            "file_read": "LOW",                      # 文件读取：低风险
            "file_list": "LOW",                      # 文件列表：低风险
            "window_get": "LOW",                     # 获取窗口：低风险
            "system_info": "LOW",                    # 系统信息：低风险
            "screenshot": "LOW",                     # 截图：低风险
            "screen_ocr": "LOW",                     # 屏幕OCR：低风险
            "clipboard_get": "LOW",                  # 获取剪贴板：低风险
            "clipboard_set": "LOW",                  # 设置剪贴板：低风险
            "web_open": "LOW",                       # 打开网页：低风险
            "web_search": "LOW",                     # 网页搜索：低风险
            "memory_add": "LOW",                     # 添加记忆：低风险
            "memory_update": "LOW",                  # 更新记忆：低风险
            "memory_search": "LOW",                  # 搜索记忆：低风险
            "code_generate": "LOW",                  # 代码生成：低风险
            "wait_for_window": "LOW",                # 等待窗口：低风险
            "window_rect": "LOW",                    # 窗口矩形：低风险
            "default": "MEDIUM"                      # 默认：中风险
        }


# 创建全局单例实例                               # 注释：创建全局单例
config = Config()                                # 创建Config全局单例


# =============================================================================
# 【文件总结性注释】
# =============================================================================
#
# 【文件角色】
# core/config.py 是 SiliconBase V5 项目的 "配置中心" 模块，位于 core 目录下。
# 它是整个系统的配置管理基础设施（第十层基础设施）。
#
# 核心定位：
#   - 全局配置的单例管理器
#   - 支持多租户配置隔离（用户级配置覆盖全局配置）
#   - 支持配置文件热重载
#   - 支持环境变量覆盖配置
#
# 主要职责：
#   1. 配置加载：从YAML文件加载全局配置、角色配置、风险映射
#   2. 配置存储：管理用户级配置的存储和检索
#   3. 配置获取：提供统一的配置获取接口（支持优先级）
#   4. 热重载：监控配置文件变化，自动热重载
#   5. 多租户：支持用户级配置隔离
#
# -----------------------------------------------------------------------------
#
# 【类结构】
#
# 1. ConfigFileHandler：
#    - 继承自 watchdog 的 FileSystemEventHandler
#    - 监控配置文件变化，触发热重载
#
# 2. UserConfigStore：
#    - 管理用户级配置的存储和检索
#    - 支持内存缓存和文件持久化
#    - 存储位置：data/user_configs/{user_id}.json
#
# 3. Config（主类）：
#    - 单例模式实现
#    - 支持读写锁（RWLock）保护并发访问
#    - 配置优先级：环境变量 > 用户配置 > 全局配置 > 默认值
#
# -----------------------------------------------------------------------------
#
# 【关联文件】
#
# 1. 依赖的模块（本文件导入）：
#    - core.dependency_utils
#      * 提供 watchdog_dep 和 rwlock_dep 依赖管理
#      * 处理可选依赖的可用性检查
#
# 2. 依赖方（使用本文件）：
#    - 几乎所有其他模块都通过 from core.config import config 使用
#    - core.ai_config: 获取AI相关配置
#    - core.api_handlers: 获取API配置
#    - core.auto_loop: 获取自动循环配置
#    - core.agent_loop: 获取Agent配置
#
# -----------------------------------------------------------------------------
#
# 【配置优先级】
#
# 配置获取的优先级（从高到低）：
#   1. 环境变量（SILICONBASE_XXX）
#   2. 用户级配置（user_configs/{user_id}.json）
#   3. 全局配置（config/global.yaml）
#   4. 默认值
#
# 环境变量格式：
#   - 点号转换为双下划线：ai.default_model -> SILICONBASE_AI__DEFAULT_MODEL
#   - 统一大写
#   - 支持布尔、整数、浮点数、JSON列表/字典
#
# -----------------------------------------------------------------------------
#
# 【配置分类】
#
# 1. 全局配置（global.yaml）：
#    - ai: AI模型、温度、超时等
#    - voice: 语音唤醒词、TTS引擎等
#    - memory: 记忆过期、加密、备份等
#    - postgresql: 数据库连接配置
#    - tools: 工具自动加载、确认列表等
#    - security: 安全策略
#    - logging: 日志级别、输出等
#
# 2. 角色配置（roles.yaml）：
#    - analyst: 分析师角色提示词
#    - decision_maker: 决策师角色提示词
#    - executor: 执行监督员角色提示词
#
# 3. 风险映射（risk_map.yaml）：
#    - 工具ID到风险等级的映射
#    - HIGH/MEDIUM/LOW 三级风险
#
# 4. 用户配置（user_configs/{user_id}.json）：
#    - 用户级配置覆盖
#    - 支持任意配置项覆盖
#
# -----------------------------------------------------------------------------
#
# 【达到的效果】
#
# 1. 集中管理：
#    - 所有配置集中在一处管理
#    - 统一的配置获取接口
#    - 支持点号分隔的嵌套键
#
# 2. 热重载：
#    - 配置文件修改后自动重载
#    - 失败时自动回滚
#    - 触发配置变更事件
#
# 3. 多租户隔离：
#    - 每个用户有独立的配置空间
#    - 用户配置覆盖全局配置
#    - 配置持久化到JSON文件
#
# 4. 环境变量支持：
#    - 支持通过环境变量覆盖配置
#    - 自动类型解析（bool/int/float/JSON）
#    - 便于容器化部署
#
# 5. 安全性：
#    - PostgreSQL密码安全检查
#    - 云端模式强制要求环境变量设置密码
#    - 读写锁保护并发访问
#
# -----------------------------------------------------------------------------
#
# 【使用示例】
#
# 1. 获取配置：
#    from core.config import config
#    model = config.get("ai.default_model", "qwen3:8b")
#    timeout = config.get("ai.timeout", 30)
#
# 2. 获取用户配置：
#    wake_words = config.get("voice.wake_words", user_id="user_123")
#
# 3. 设置配置：
#    config.set("ai.default_model", "gpt-4")
#
# 4. 设置用户配置：
#    config.set_user_config("user_123", "voice.wake_words", ["你好"])
#
# 5. 监听配置变更：
#    def on_config_changed(new_config):
#        print("配置已变更")
#    config.add_change_listener(on_config_changed)
#
# 6. 热重载：
#    config.reload()
#
# -----------------------------------------------------------------------------
#
# 【注意事项】
#
# 1. 单例模式：
#    - 全局使用同一个 config 实例
#    - 通过 from core.config import config 导入
#
# 2. 线程安全：
#    - 使用读写锁保护配置访问
#    - 读操作使用读锁，写操作使用写锁
#
# 3. 环境变量：
#    - 优先级最高
#    - 适合敏感信息（密码、API密钥）
#    - 适合容器化部署
#
# 4. 用户配置：
#    - 存储在 data/user_configs/ 目录
#    - JSON格式，便于手动编辑
#    - 支持嵌套键
#
# 5. 向后兼容：
#    - wake_word -> voice.wake_words
#    - 自动转换并发出警告
#
# =============================================================================
