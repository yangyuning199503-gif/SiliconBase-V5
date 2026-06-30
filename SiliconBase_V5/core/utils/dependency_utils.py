#!/usr/bin/env python3  # 指定Python解释器路径
# 声明UTF-8编码支持中文
"""依赖管理工具 - 统一处理可选依赖

该模块提供统一的依赖管理和回退机制，避免在多个文件中重复编写
try-except ImportError 代码。

示例:
    from core.dependency_utils import watchdog_dep, postgres_dep

    # 检查依赖是否可用
    if watchdog_dep.available:
        observer = watchdog_dep.get_class("Observer")()
    else:
        print("watchdog 不可用，使用文件轮询模式")

    # 获取模块属性
    RealDictCursor = postgres_dep.get("extras.RealDictCursor")
"""
import importlib  # 导入importlib模块，用于动态导入
import threading  # 导入线程模块
from functools import lru_cache  # 导入lru_cache装饰器


class OptionalDependency:  # 定义可选依赖包装器类
    """可选依赖包装器 - 统一处理可选依赖的导入和回退  # 类文档字符串

    Attributes:  # 属性说明
        module_name: 模块的导入名称  # 属性描述
        fallback_class: 依赖不可用时返回的替代类  # 属性描述
        _module: 缓存的模块对象  # 属性描述
        _available: 缓存的可用性状态  # 属性描述

    Example:  # 使用示例
        >>> redis_dep = OptionalDependency("redis")  # 创建包装器实例
        >>> redis_dep.available  # 检查可用性
        True
        >>> Redis = redis_dep.get_class("Redis")  # 获取Redis类
        >>> redis = Redis() if Redis else None  # 条件实例化
    """  # 类文档字符串结束

    def __init__(self, module_name: str, fallback_class: type | None = None):  # 初始化方法
        """初始化可选依赖  # 方法文档字符串

        Args:  # 参数说明
            module_name: 要导入的模块名称  # 参数描述
            fallback_class: 依赖不可用时返回的替代类  # 参数描述
        """  # 方法文档字符串结束
        self.module_name = module_name  # 存储模块名称
        self.fallback_class = fallback_class  # 存储回退类
        self._module = None  # 初始化模块缓存为None
        self._available = None  # 初始化可用性缓存为None

    @property  # 属性装饰器
    def available(self) -> bool:  # 定义可用性属性
        """检查依赖是否可用  # 属性文档字符串

        首次调用时会尝试导入模块并缓存结果。  # 缓存说明

        Returns:  # 返回值说明
            bool: 依赖可用返回 True，否则返回 False  # 返回类型
        """  # 属性文档字符串结束
        if self._available is None:  # 如果尚未检查
            try:  # 尝试导入
                self._module = importlib.import_module(self.module_name)  # 动态导入模块
                self._available = True  # 标记为可用
            except ImportError:  # 如果导入失败
                self._available = False  # 标记为不可用
        return self._available  # 返回可用性状态

    def get(self, attr_path: str, default=None):  # 定义获取属性方法
        """获取模块属性，不可用返回默认值  # 方法文档字符串

        支持点号分隔的路径，如 "extras.RealDictCursor"  # 路径格式说明

        Args:  # 参数说明
            attr_path: 属性路径，支持嵌套属性（如 "extras.RealDictCursor"）  # 参数描述
            default: 依赖不可用或属性不存在时返回的默认值  # 参数描述

        Returns:  # 返回值说明
            属性值或默认值  # 返回类型
        """  # 方法文档字符串结束
        if not self.available:  # 如果依赖不可用
            return default  # 直接返回默认值

        try:  # 尝试获取属性
            parts = attr_path.split('.')  # 按点号分割路径
            obj = self._module  # 从模块对象开始
            for part in parts:  # 遍历路径各部分
                obj = getattr(obj, part)  # 获取下一级属性
            return obj  # 返回最终属性
        except AttributeError:  # 如果属性不存在
            return default  # 返回默认值

    def get_class(self, class_name: str) -> type | None:  # 定义获取类方法
        """获取类，不可用返回 fallback_class  # 方法文档字符串

        Args:  # 参数说明
            class_name: 类名  # 参数描述

        Returns:  # 返回值说明
            类对象或 fallback_class  # 返回类型
        """  # 方法文档字符串结束
        cls = self.get(class_name)  # 尝试获取类
        return cls if cls else self.fallback_class  # 返回类或回退类


class FallbackRWLock:  # 定义读写锁回退实现类
    """读写锁回退实现 - 使用普通 RLock 模拟  # 类文档字符串

    当 readerwriterlock 模块不可用时使用。  # 使用场景
    不支持真正的读写分离，但提供兼容的接口。  # 功能限制
    """  # 类文档字符串结束

    def __init__(self):  # 初始化方法
        self._lock = threading.RLock()  # 创建可重入锁

    def gen_rlock(self):  # 定义生成读锁方法
        """生成读锁（实际是 RLock）"""  # 方法文档字符串
        return self._lock  # 返回锁对象（读锁和写锁相同）

    def gen_wlock(self):  # 定义生成写锁方法
        """生成写锁（实际是 RLock）"""  # 方法文档字符串
        return self._lock  # 返回锁对象（读锁和写锁相同）


class FallbackRWLockFactory:  # 定义读写锁工厂回退实现类
    """读写锁工厂回退实现"""  # 类文档字符串

    @staticmethod  # 静态方法装饰器
    def RWLockFair():  # 定义公平读写锁工厂方法
        """公平读写锁 - 回退到普通锁"""  # 方法文档字符串
        return FallbackRWLock()  # 返回回退锁实例

    @staticmethod  # 静态方法装饰器
    def RWLockWrite():  # 定义写优先读写锁工厂方法
        """写优先读写锁 - 回退到普通锁"""  # 方法文档字符串
        return FallbackRWLock()  # 返回回退锁实例


# ═══════════════════════════════════════════════════════════════  # 分隔线注释
# 预定义常用可选依赖  # 模块分区说明
# ═══════════════════════════════════════════════════════════════  # 分隔线结束

# PostgreSQL 数据库支持  # 注释说明依赖用途
postgres_dep = OptionalDependency("psycopg2")  # 创建PostgreSQL依赖包装器

# Redis 缓存支持  # 注释说明依赖用途
redis_dep = OptionalDependency("redis")  # 创建Redis依赖包装器

# 文件系统监控（配置文件热加载）  # 注释说明依赖用途
watchdog_dep = OptionalDependency("watchdog")  # 创建watchdog依赖包装器

# 读写锁优化  # 注释说明依赖用途
rwlock_dep = OptionalDependency(  # 创建readerwriterlock依赖包装器
    "readerwriterlock",  # 模块名
    fallback_class=FallbackRWLockFactory  # 指定回退类
)  # rwlock_dep创建结束

# ChromaDB 向量数据库  # 注释说明依赖用途
chromadb_dep = OptionalDependency("chromadb")  # 创建ChromaDB依赖包装器

# OpenCV 图像处理  # 注释说明依赖用途
cv2_dep = OptionalDependency("cv2")  # 创建OpenCV依赖包装器

# NumPy 数值计算  # 注释说明依赖用途
numpy_dep = OptionalDependency("numpy")  # 创建NumPy依赖包装器

# PyTorch 深度学习框架  # 注释说明依赖用途
torch_dep = OptionalDependency("torch")  # 创建PyTorch依赖包装器

# Transformers 模型库  # 注释说明依赖用途
transformers_dep = OptionalDependency("transformers")  # 创建Transformers依赖包装器

# Sentence Transformers 文本嵌入  # 注释说明依赖用途
sentence_transformers_dep = OptionalDependency("sentence_transformers")  # 创建Sentence Transformers依赖包装器

# TTS 语音合成  # 注释说明依赖用途
tts_dep = OptionalDependency("TTS")  # 创建TTS依赖包装器

# Vosk 语音识别  # 注释说明依赖用途
vosk_dep = OptionalDependency("vosk")  # 创建Vosk依赖包装器

# SoundDevice 音频设备  # 注释说明依赖用途
sounddevice_dep = OptionalDependency("sounddevice")  # 创建SoundDevice依赖包装器

# WebSocket 支持  # 注释说明依赖用途
websockets_dep = OptionalDependency("websockets")  # 创建WebSockets依赖包装器

# FastAPI Web框架  # 注释说明依赖用途
fastapi_dep = OptionalDependency("fastapi")  # 创建FastAPI依赖包装器

# Uvicorn ASGI服务器  # 注释说明依赖用途
uvicorn_dep = OptionalDependency("uvicorn")  # 创建Uvicorn依赖包装器

# Streamlit Web UI  # 注释说明依赖用途
streamlit_dep = OptionalDependency("streamlit")  # 创建Streamlit依赖包装器

# Rich 终端美化  # 注释说明依赖用途
rich_dep = OptionalDependency("rich")  # 创建Rich依赖包装器


# ═══════════════════════════════════════════════════════════════  # 分隔线注释
# 便捷函数  # 模块分区说明
# ═══════════════════════════════════════════════════════════════  # 分隔线结束

def check_dependency(module_name: str) -> bool:  # 定义快速检查依赖函数
    """快速检查依赖是否可用  # 函数文档字符串

    Args:  # 参数说明
        module_name: 模块名称  # 参数描述

    Returns:  # 返回值说明
        bool: 依赖是否可用  # 返回类型

    Example:  # 使用示例
        >>> if check_dependency("redis"):  # 检查redis
        ...     import redis  # 安全导入
        ...     r = redis.Redis()  # 使用redis
    """  # 函数文档字符串结束
    try:  # 尝试导入
        importlib.import_module(module_name)  # 动态导入模块
        return True  # 返回可用
    except ImportError:  # 如果导入失败
        return False  # 返回不可用


@lru_cache(maxsize=128)  # LRU缓存装饰器，最多缓存128个结果
def get_dependency_info(module_name: str) -> dict:  # 定义获取依赖信息函数
    """获取依赖信息（带缓存）  # 函数文档字符串

    Args:  # 参数说明
        module_name: 模块名称  # 参数描述

    Returns:  # 返回值说明
        包含依赖信息的字典  # 返回类型
    """  # 函数文档字符串结束
    dep = OptionalDependency(module_name)  # 创建包装器实例
    return {  # 返回依赖信息字典
        "module_name": module_name,  # 模块名称
        "available": dep.available,  # 可用性状态
        "module": dep._module if dep.available else None  # 模块对象（如果可用）
    }  # 字典返回结束


# ═══════════════════════════════════════════════════════════════  # 分隔线注释
# 向后兼容导出（用于平滑迁移）  # 模块分区说明
# ═══════════════════════════════════════════════════════════════  # 分隔线结束

# 这些导出允许旧代码在导入时使用新机制  # 注释说明用途
# 逐步替换后，这些导出可能会被移除  # 注释说明未来计划

__all__ = [  # 定义模块公开接口
    # 核心类  # 注释标记核心类
    "OptionalDependency",  # 导出OptionalDependency类
    "FallbackRWLock",  # 导出FallbackRWLock类
    "FallbackRWLockFactory",  # 导出FallbackRWLockFactory类

    # 预定义依赖  # 注释标记预定义依赖
    "postgres_dep",  # 导出postgres_dep
    "redis_dep",  # 导出redis_dep
    "watchdog_dep",  # 导出watchdog_dep
    "rwlock_dep",  # 导出rwlock_dep
    "chromadb_dep",  # 导出chromadb_dep
    "cv2_dep",  # 导出cv2_dep
    "numpy_dep",  # 导出numpy_dep
    "torch_dep",  # 导出torch_dep
    "transformers_dep",  # 导出transformers_dep
    "sentence_transformers_dep",  # 导出sentence_transformers_dep
    "tts_dep",  # 导出tts_dep
    "vosk_dep",  # 导出vosk_dep
    "sounddevice_dep",  # 导出sounddevice_dep
    "websockets_dep",  # 导出websockets_dep
    "fastapi_dep",  # 导出fastapi_dep
    "uvicorn_dep",  # 导出uvicorn_dep
    "streamlit_dep",  # 导出streamlit_dep
    "rich_dep",  # 导出rich_dep

    # 便捷函数  # 注释标记便捷函数
    "check_dependency",  # 导出check_dependency函数
    "get_dependency_info",  # 导出get_dependency_info函数
]  # __all__列表结束


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"依赖管理工具"，提供统一的可选依赖处理机制，
# 避免在多个文件中重复编写try-except ImportError代码，实现优雅的依赖缺失降级。
#
# 【设计特点】
# 1. 包装器模式：OptionalDependency类统一封装依赖的导入和回退逻辑
# 2. 延迟加载：依赖在首次访问时才尝试导入，避免启动时加载不必要的模块
# 3. 结果缓存：导入结果缓存，避免重复尝试导入
# 4. 属性路径：支持点号分隔的嵌套属性路径（如"extras.RealDictCursor"）
# 5. 回退机制：支持指定fallback_class，在依赖不可用时提供替代实现
# 6. 读写锁回退：提供FallbackRWLock，在readerwriterlock不可用时使用RLock替代
#
# 【关联文件】
# - core/config.py               : 使用rwlock_dep处理读写锁
# - core/memory.py               : 使用chromadb_dep处理向量数据库
# - perception/screen_capture.py : 使用cv2_dep处理图像
# - voice/*.py                   : 使用tts_dep、vosk_dep处理语音
# - api/*.py                     : 使用fastapi_dep、uvicorn_dep
#
# 【核心功能效果】
# 1. 优雅降级：依赖缺失时不会崩溃，而是使用回退方案或禁用相关功能
# 2. 代码复用：避免各模块重复编写try-except导入代码
# 3. 配置灵活：用户可以根据需要安装可选依赖，扩展系统功能
# 4. 性能优化：lru_cache缓存依赖检查结果，避免重复导入尝试
# 5. 开发友好：清晰的依赖定义，便于了解系统各功能所需依赖
#
# 【使用示例】
# from core.dependency_utils import postgres_dep, check_dependency
#
# # 检查依赖是否可用
# if postgres_dep.available:
#     conn = postgres_dep.get("connect")("dbname=test")
#
# # 获取类，如果不存在返回None
# RealDictCursor = postgres_dep.get("extras.RealDictCursor")
#
# # 快速检查
# if check_dependency("numpy"):
#     import numpy as np
# =============================================================================
