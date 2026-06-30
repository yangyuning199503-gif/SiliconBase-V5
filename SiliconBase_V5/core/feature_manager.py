#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""
功能管理器 - SiliconBase V5 插排架构核心

提供功能开关管理、状态监控、动态启用/禁用功能。
支持运行时配置变更和功能降级。

示例:
    from core.feature_manager import feature_manager

    # 检查功能是否启用
    if feature_manager.is_enabled("voice"):
        # 使用语音功能
        pass

    # 获取功能状态
    status = feature_manager.get_status("vision")
    print(f"视觉功能: {status['state']}")

    # 启用功能
    feature_manager.enable("advanced_nlp")
"""

import json  # 导入JSON处理模块
import os  # 导入操作系统接口模块
import threading  # 导入线程模块
from abc import ABC, abstractmethod  # 从abc导入抽象基类和抽象方法装饰器
from dataclasses import asdict, dataclass, field  # 从dataclasses导入数据类相关
from enum import Enum  # 从enum导入枚举类和自动值
from pathlib import Path  # 从pathlib导入路径类
from typing import Any, Optional  # 导入类型注解工具

from core.config import config  # 从core.config导入配置管理器
from core.logger import logger  # 从core.logger导入日志记录器
from core.sync.event_bus import event_bus  # 从core.event_bus导入事件总线


class FeatureState(Enum):  # 定义功能状态枚举类
    """功能状态枚举"""  # 类文档字符串：描述功能的各种状态
    UNKNOWN = "unknown"           # 未知状态：尚未检查的状态
    DISABLED = "disabled"         # 用户禁用：被用户手动禁用
    PENDING = "pending"           # 等待检查：等待可用性检查
    CHECKING = "checking"         # 检查中：正在进行可用性检查
    AVAILABLE = "available"       # 可用但未初始化：依赖满足但未初始化
    INITIALIZING = "initializing" # 初始化中：正在进行初始化
    RUNNING = "running"           # 正常运行：功能已启用且正常运行
    ERROR = "error"               # 运行错误：初始化或运行中出现错误
    DEGRADED = "degraded"         # 降级运行：功能可用但性能受限
    MISSING_DEPS = "missing_deps" # 缺少依赖：必要依赖未满足


class FeatureCategory(Enum):  # 定义功能分类枚举类
    """功能分类"""  # 类文档字符串：描述功能的分类
    CORE = "core"                 # 核心功能：系统必需的基础功能
    PERCEPTION = "perception"     # 感知功能：语音/视觉等感知能力
    COGNITION = "cognition"       # 认知功能：AI/NLP等认知能力
    MEMORY = "memory"             # 记忆功能：记忆存储和检索
    CONSCIOUSNESS = "consciousness"  # 意识功能：自主意识和进化引擎
    EXTENSION = "extension"       # 扩展功能：可选的扩展模块


class AppStatus(Enum):
    """全局应用状态枚举（供启动流程和休眠模块使用）"""
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"


@dataclass  # 使用数据类装饰器
class DependencyInfo:  # 定义依赖信息数据类
    """依赖信息"""  # 类文档字符串：描述依赖的详细信息
    name: str  # 依赖名称
    type: str  # 依赖类型：pip, service, model_file, binary
    required: bool = False  # 是否必需：是否为必需依赖
    feature: str | None = None  # 关联功能：该依赖属于哪个功能
    description: str | None = None  # 描述：依赖说明
    status: str = "unknown"  # 状态：available, missing, optional
    version: str | None = None  # 版本：已安装版本号
    install_cmd: str | None = None  # 安装命令：安装此依赖的命令
    pip_package: str | None = None  # pip包名：用于一键安装
    download_url: str | None = None  # 下载链接：依赖下载地址
    size: str | None = None  # 大小：依赖包大小
    message: str | None = None  # 消息：额外信息或提示


@dataclass  # 使用数据类装饰器
class FeatureInfo:  # 定义功能信息数据类
    """功能信息数据类"""  # 类文档字符串：描述功能的元信息
    id: str  # 功能ID：唯一标识符
    name: str  # 功能名称：显示名称
    description: str  # 功能描述：详细说明
    category: FeatureCategory  # 功能分类：所属类别
    enabled: bool = False  # 是否启用：用户是否启用此功能
    state: FeatureState = FeatureState.UNKNOWN  # 当前状态：功能运行状态
    available: bool = False  # 是否可用：依赖是否满足
    configurable: bool = True  # 是否可配置：是否支持配置变更
    requires_restart: bool = False  # 是否需要重启：配置变更后是否需要重启
    error_message: str | None = None  # 错误消息：错误时显示的信息
    sub_features: list['FeatureInfo'] = field(default_factory=list)  # 子功能列表
    dependencies: list[DependencyInfo] = field(default_factory=list)  # 依赖列表
    config: dict[str, Any] = field(default_factory=dict)  # 配置字典
    metadata: dict[str, Any] = field(default_factory=dict)  # 元数据字典

    def to_dict(self) -> dict[str, Any]:  # 定义转换为字典的方法
        """转换为字典"""  # 方法文档字符串
        result = asdict(self)  # 使用asdict将数据类转为字典
        result['category'] = self.category.value  # 将枚举转为字符串值
        result['state'] = self.state.value  # 将状态枚举转为字符串值
        return result  # 返回转换后的字典


class BaseFeature(ABC):  # 定义功能抽象基类
    """
    功能基类  # 类文档字符串标题

    所有功能模块应继承此类，实现必要的方法。  # 类说明
    """  # 类文档字符串结束

    # 功能标识 (必须唯一)
    feature_id: str = ""  # 类属性：功能唯一标识符

    # 功能显示名称
    name: str = ""  # 类属性：功能的显示名称

    # 功能描述
    description: str = ""  # 类属性：功能的详细描述

    # 功能分类
    category: FeatureCategory = FeatureCategory.EXTENSION  # 类属性：默认扩展分类

    # 是否可配置
    configurable: bool = True  # 类属性：默认可配置

    # 修改后是否需要重启
    requires_restart: bool = False  # 类属性：默认不需要重启

    # 依赖列表 (类属性，子类可覆盖)
    dependencies: list[str] = []  # 类属性：依赖ID列表

    def __init__(self):  # 定义初始化方法
        self._info = FeatureInfo(  # 创建功能信息对象
            id=self.feature_id,  # 设置功能ID
            name=self.name,  # 设置功能名称
            description=self.description,  # 设置功能描述
            category=self.category,  # 设置功能分类
            configurable=self.configurable,  # 设置可配置性
            requires_restart=self.requires_restart  # 设置重启要求
        )
        self._initialized = False  # 初始化标志：标记是否已初始化
        self._lock = threading.RLock()  # 创建可重入锁：用于线程安全

    @property  # 定义属性装饰器
    def info(self) -> FeatureInfo:  # 定义info属性
        """获取功能信息"""  # 属性文档字符串
        return self._info  # 返回功能信息对象

    @abstractmethod  # 定义抽象方法装饰器
    def check_availability(self) -> bool:  # 定义检查可用性抽象方法
        """
        检查功能可用性  # 方法文档字符串标题

        Returns:  # 返回值说明
            bool: 功能是否可用  # 返回类型和含义
        """  # 方法文档字符串结束
        pass  # 抽象方法：子类必须实现

    def get_dependencies(self) -> list[DependencyInfo]:  # 定义获取依赖列表方法
        """
        获取依赖列表  # 方法文档字符串标题

        Returns:  # 返回值说明
            依赖信息列表  # 返回类型
        """  # 方法文档字符串结束
        return []  # 默认返回空列表

    def initialize(self) -> bool:  # 定义初始化功能方法
        """
        初始化功能  # 方法文档字符串标题

        Returns:  # 返回值说明
            bool: 初始化是否成功  # 返回类型和含义
        """  # 方法文档字符串结束
        with self._lock:  # 使用锁保证线程安全
            if self._initialized:  # 如果已经初始化
                return True  # 直接返回成功

            try:  # 开始异常处理
                self._info.state = FeatureState.INITIALIZING  # 设置状态为初始化中
                success = self._do_initialize()  # 调用子类实现的初始化逻辑
                self._initialized = success  # 更新初始化标志
                self._info.state = FeatureState.RUNNING if success else FeatureState.ERROR  # 更新状态
                return success  # 返回初始化结果
            except Exception as e:  # 捕获异常
                logger.error(f"[{self.feature_id}] 初始化失败: {e}")  # 记录错误日志
                self._info.state = FeatureState.ERROR  # 设置状态为错误
                self._info.error_message = str(e)  # 记录错误消息
                return False  # 返回失败

    @abstractmethod  # 定义抽象方法装饰器
    def _do_initialize(self) -> bool:  # 定义子类必须实现的初始化方法
        """子类实现初始化逻辑"""  # 方法文档字符串
        pass  # 抽象方法：子类必须实现

    def deinitialize(self) -> bool:  # 定义反初始化功能方法
        """
        反初始化功能  # 方法文档字符串标题

        Returns:  # 返回值说明
            bool: 反初始化是否成功  # 返回类型和含义
        """  # 方法文档字符串结束
        with self._lock:  # 使用锁保证线程安全
            if not self._initialized:  # 如果未初始化
                return True  # 直接返回成功

            try:  # 开始异常处理
                success = self._do_deinitialize()  # 调用子类实现的反初始化逻辑
                self._initialized = False  # 更新初始化标志
                self._info.state = FeatureState.AVAILABLE if success else FeatureState.ERROR  # 更新状态
                return success  # 返回反初始化结果
            except Exception as e:  # 捕获异常
                logger.error(f"[{self.feature_id}] 反初始化失败: {e}")  # 记录错误日志
                return False  # 返回失败

    def _do_deinitialize(self) -> bool:  # 定义子类可覆盖的反初始化方法
        """子类实现反初始化逻辑，默认返回True"""  # 方法文档字符串
        return True  # 默认实现：返回成功

    def configure(self,  # 定义配置功能方法
                  config_dict: dict[str, Any]  # 参数：配置字典
                  ) -> bool:  # 返回：是否成功
        """
        配置功能  # 方法文档字符串标题

        Args:  # 参数说明
            config_dict: 配置字典  # 参数类型和说明

        Returns:  # 返回值说明
            bool: 配置是否成功  # 返回类型和含义
        """  # 方法文档字符串结束
        with self._lock:  # 使用锁保证线程安全
            try:  # 开始异常处理
                self._info.config.update(config_dict)  # 更新配置字典
                return self._do_configure(config_dict)  # 调用子类实现
            except Exception as e:  # 捕获异常
                logger.error(f"[{self.feature_id}] 配置失败: {e}")  # 记录错误日志
                return False  # 返回失败

    def _do_configure(self,  # 定义子类可覆盖的配置方法
                      config_dict: dict[str, Any]  # 参数：配置字典
                      ) -> bool:  # 返回：是否成功
        """子类实现配置逻辑，默认返回True"""  # 方法文档字符串
        return True  # 默认实现：返回成功

    def get_status(self) -> dict[str, Any]:  # 定义获取详细状态方法
        """
        获取详细状态  # 方法文档字符串标题

        Returns:  # 返回值说明
            状态字典  # 返回类型
        """  # 方法文档字符串结束
        return {  # 返回状态字典
            "id": self.feature_id,  # 功能ID字段
            "name": self.name,  # 功能名称字段
            "enabled": self._info.enabled,  # 是否启用字段
            "state": self._info.state.value,  # 状态字段（枚举值）
            "available": self._info.available,  # 是否可用字段
            "initialized": self._initialized,  # 是否已初始化字段
            "error": self._info.error_message,  # 错误消息字段
            "config": self._info.config  # 配置字段
        }


class SimpleFeature(BaseFeature):
    """
    简单功能基类 - 用于无复杂生命周期的纯配置开关。

    子类只需设置 feature_id / name / description / category / requires_restart，
    无需实现 check_availability 和 _do_initialize。
    """

    def check_availability(self) -> bool:
        """简单功能默认始终可用"""
        return True

    def _do_initialize(self) -> bool:
        """简单功能默认初始化成功"""
        return True


class AIBackendFeature(BaseFeature):  # 定义AI后端功能类，继承BaseFeature
    """AI后端功能"""  # 类文档字符串

    feature_id = "ai_backend"  # 功能ID：唯一标识
    name = "AI 后端"  # 功能名称：显示名称
    description = "核心AI对话功能，支持多种后端"  # 功能描述
    category = FeatureCategory.COGNITION  # 功能分类：认知功能

    def __init__(self):  # 定义初始化方法
        super().__init__()  # 调用父类初始化
        self._provider = None  # 初始化AI提供商实例为None

    def check_availability(self) -> bool:  # 定义检查可用性方法
        """检查AI后端可用性"""  # 方法文档字符串
        # 检查本地Ollama
        import urllib.request  # 导入urllib请求模块

        try:  # 开始异常处理
            ollama_url = config.get("ai.ollama_base_url", "http://localhost:11434")  # 获取Ollama地址
            req = urllib.request.Request(  # 创建HTTP请求
                f"{ollama_url}/api/tags",  # 请求URL：获取模型列表
                method="GET"  # 请求方法
            )
            with urllib.request.urlopen(req, timeout=5) as resp:  # 发送请求，超时5秒
                return resp.status == 200  # 返回状态码是否为200
        except Exception as e:  # 捕获异常
            logger.error(f"[FeatureManager] 检查Ollama后端失败: {e}", exc_info=True)  # 忽略异常，继续检查其他后端

        # 检查云端API配置
        return bool(config.get("ai.ark_api_key") or config.get("ai.openai_api_key"))  # 有API密钥则返回可用

    def _do_initialize(self) -> bool:  # 定义初始化实现方法
        """初始化AI后端"""  # 方法文档字符串
        from core.providers.ai_provider_factory import AIProviderFactory  # 导入AI提供商工厂

        try:  # 开始异常处理
            self._provider = AIProviderFactory.get_current_provider()  # 获取当前AI提供商
            return self._provider is not None  # 返回是否成功获取提供商
        except Exception as e:  # 捕获异常
            logger.error(f"[AIBackendFeature] 初始化失败: {e}")  # 记录错误日志
            return False  # 返回失败

    def get_dependencies(self) -> list[DependencyInfo]:  # 定义获取依赖列表方法
        """获取依赖列表"""  # 方法文档字符串
        return [  # 返回依赖列表
            DependencyInfo(  # Ollama服务依赖
                name="ollama",  # 依赖名称
                type="service",  # 依赖类型：服务
                required=False,  # 非必需
                status="available" if self._check_ollama() else "missing",  # 根据检查结果设置状态
                download_url="https://ollama.ai/download"  # 下载地址
            ),
            DependencyInfo(  # OpenAI依赖
                name="openai",  # 依赖名称
                type="pip",  # 依赖类型：pip包
                required=False,  # 非必需
                install_cmd="pip install openai"  # 安装命令
            )
        ]

    def _check_ollama(self) -> bool:  # 定义检查Ollama服务方法
        """检查Ollama服务"""  # 方法文档字符串
        import urllib.request  # 导入urllib请求模块
        try:  # 开始异常处理
            ollama_url = config.get("ai.ollama_base_url", "http://localhost:11434")  # 获取Ollama地址
            req = urllib.request.Request(f"{ollama_url}/api/tags", method="GET")  # 创建请求
            with urllib.request.urlopen(req, timeout=2) as resp:  # 发送请求，超时2秒
                return resp.status == 200  # 返回状态码是否为200
        except Exception:  # 捕获异常
            return False  # 异常时返回不可用


class VoiceFeature(BaseFeature):  # 定义语音功能类，继承BaseFeature
    """语音功能"""  # 类文档字符串

    feature_id = "voice"  # 功能ID：唯一标识
    name = "语音功能"  # 功能名称
    description = "语音识别(ASR)和语音合成(TTS)"  # 功能描述
    category = FeatureCategory.PERCEPTION  # 功能分类：感知功能

    def __init__(self):  # 定义初始化方法
        super().__init__()  # 调用父类初始化
        self._asr_available = False  # 初始化ASR可用性标志为False
        self._tts_available = False  # 初始化TTS可用性标志为False

    def check_availability(self) -> bool:  # 定义检查可用性方法
        """检查语音功能可用性"""  # 方法文档字符串
        from core.utils.dependency_utils import tts_dep, vosk_dep  # 导入依赖检查对象

        self._asr_available = vosk_dep.available  # 检查Vosk依赖是否可用
        self._tts_available = tts_dep.available  # 检查TTS依赖是否可用

        return self._asr_available or self._tts_available  # 任一可用则返回True

    def _do_initialize(self) -> bool:  # 定义初始化实现方法
        """初始化语音功能"""  # 方法文档字符串
        # 检查模型文件
        model_path = config.get("voice.model_path", "assets/models/vosk-model-cn-0.22")  # 获取模型路径
        if not os.path.exists(model_path):  # 检查模型文件是否存在
            logger.warning(f"[VoiceFeature] Vosk模型不存在: {model_path}")  # 记录警告
            self._asr_available = False  # 标记ASR不可用

        return True  # 语音功能可以部分可用

    def get_dependencies(self) -> list[DependencyInfo]:  # 定义获取依赖列表方法
        """获取依赖列表"""  # 方法文档字符串
        from core.utils.dependency_utils import tts_dep, vosk_dep  # 导入依赖检查对象

        deps = []  # 初始化依赖列表

        # ASR依赖
        deps.append(DependencyInfo(  # 添加Vosk依赖信息
            name="vosk",  # 依赖名称
            type="pip",  # 依赖类型：pip包
            required=False,  # 非必需
            feature="voice.asr",  # 关联功能：语音识别
            status="available" if vosk_dep.available else "missing",  # 根据可用性设置状态
            install_cmd="pip install vosk",  # 安装命令
            download_url="https://alphacephei.com/vosk/"  # 下载地址
        ))

        # 模型文件
        model_path = config.get("voice.model_path")  # 获取模型路径配置
        if model_path:  # 如果配置了模型路径
            deps.append(DependencyInfo(  # 添加模型依赖信息
                name="vosk-model",  # 依赖名称
                type="model_file",  # 依赖类型：模型文件
                required=False,  # 非必需
                feature="voice.asr",  # 关联功能
                status="available" if os.path.exists(model_path) else "missing",  # 根据文件是否存在设置状态
                download_url="https://alphacephei.com/vosk/models",  # 下载地址
                size="40MB-1.5GB"  # 文件大小范围
            ))

        # TTS依赖
        deps.append(DependencyInfo(  # 添加Piper TTS依赖信息
            name="piper-tts",  # 依赖名称
            type="pip",  # 依赖类型：pip包
            required=False,  # 非必需
            feature="voice.tts",  # 关联功能：语音合成
            status="available" if tts_dep.available else "missing",  # 根据可用性设置状态
            install_cmd="pip install piper-tts"  # 安装命令
        ))

        return deps  # 返回依赖列表

    def get_status(self) -> dict[str, Any]:  # 定义获取状态方法
        """获取详细状态"""  # 方法文档字符串
        status = super().get_status()  # 获取父类状态
        # [修复] 改为列表格式以匹配API schema期望
        status["sub_features"] = [
            {  # 语音识别状态
                "id": "asr",
                "name": "语音识别",
                "enabled": config.get("features.voice.asr.enabled", True),
                "available": self._asr_available,
                "config_path": "features.voice.asr.enabled",
            },
            {  # 语音合成状态
                "id": "tts",
                "name": "语音合成",
                "enabled": config.get("features.voice.tts.enabled", True),
                "available": self._tts_available,
                "config_path": "features.voice.tts.enabled",
            }
        ]
        return status  # 返回完整状态


class VisionFeature(BaseFeature):  # 定义视觉功能类，继承BaseFeature
    """视觉功能"""  # 类文档字符串

    feature_id = "vision"  # 功能ID：唯一标识
    name = "视觉功能"  # 功能名称
    description = "OCR和图像理解"  # 功能描述
    category = FeatureCategory.PERCEPTION  # 功能分类：感知功能

    def __init__(self):  # 定义初始化方法
        super().__init__()  # 调用父类初始化
        self._ocr_available = False  # 初始化OCR可用性标志为False
        self._vision_available = False  # 初始化视觉可用性标志为False

    def check_availability(self) -> bool:  # 定义检查可用性方法
        """检查视觉功能可用性"""  # 方法文档字符串
        from core.utils.dependency_utils import cv2_dep, numpy_dep  # 导入依赖检查对象

        # 基础图像处理
        basic_available = cv2_dep.available and numpy_dep.available  # 检查基础依赖

        # OCR引擎
        ocr_engine = config.get("features.vision.ocr.engine", "easyocr")  # 获取OCR引擎配置
        if ocr_engine == "easyocr":  # 如果使用EasyOCR
            from core.utils.dependency_utils import check_dependency  # 导入依赖检查函数
            self._ocr_available = check_dependency("easyocr")  # 检查EasyOCR依赖

        # 视觉模型
        self._vision_available = self._check_vision_backend()  # 检查视觉后端

        return basic_available  # 返回基础依赖是否满足

    def _check_vision_backend(self) -> bool:  # 定义检查视觉后端方法
        """检查视觉后端"""  # 方法文档字符串
        import urllib.request  # 导入urllib请求模块
        try:  # 开始异常处理
            ollama_url = config.get("ai.ollama_base_url", "http://localhost:11434")  # 获取Ollama地址
            req = urllib.request.Request(f"{ollama_url}/api/tags", method="GET")  # 创建请求
            with urllib.request.urlopen(req, timeout=2) as resp:  # 发送请求，超时2秒
                if resp.status == 200:  # 如果请求成功
                    data = json.loads(resp.read().decode())  # 解析JSON响应
                    models = [m["name"] for m in data.get("models", [])]  # 提取模型名称列表
                    # 检查视觉模型
                    return any("vl" in m or "vision" in m for m in models)  # 检查是否包含视觉模型
        except Exception as e:  # 捕获异常
            logger.error(f"[FeatureManager] 检查视觉模型失败: {e}", exc_info=True)  # 忽略异常
        return False  # 返回不可用

    def _do_initialize(self) -> bool:  # 定义初始化实现方法
        """初始化视觉功能"""  # 方法文档字符串
        # OCR初始化
        if self._ocr_available:  # 如果OCR可用
            try:  # 开始异常处理
                logger.info("[VisionFeature] EasyOCR已加载")  # 记录信息
            except Exception as e:  # 捕获异常
                logger.warning(f"[VisionFeature] EasyOCR加载失败: {e}")  # 记录警告
                self._ocr_available = False  # 标记OCR不可用

        return True  # 返回成功

    def get_dependencies(self) -> list[DependencyInfo]:  # 定义获取依赖列表方法
        """获取依赖列表"""  # 方法文档字符串
        from core.utils.dependency_utils import cv2_dep, numpy_dep  # 导入依赖检查对象

        deps = [  # 初始化依赖列表
            DependencyInfo(  # OpenCV依赖
                name="opencv-python",  # 依赖名称
                type="pip",  # 依赖类型：pip包
                required=True,  # 必需
                status="available" if cv2_dep.available else "missing",  # 根据可用性设置状态
                install_cmd="pip install opencv-python"  # 安装命令
            ),
            DependencyInfo(  # NumPy依赖
                name="numpy",  # 依赖名称
                type="pip",  # 依赖类型：pip包
                required=True,  # 必需
                status="available" if numpy_dep.available else "missing",  # 根据可用性设置状态
                install_cmd="pip install numpy"  # 安装命令
            )
        ]

        # OCR依赖
        ocr_engine = config.get("features.vision.ocr.engine", "easyocr")  # 获取OCR引擎配置
        if ocr_engine == "easyocr":  # 如果使用EasyOCR
            from core.utils.dependency_utils import check_dependency  # 导入依赖检查函数
            deps.append(DependencyInfo(  # 添加EasyOCR依赖
                name="easyocr",  # 依赖名称
                type="pip",  # 依赖类型：pip包
                required=False,  # 非必需
                feature="vision.ocr",  # 关联功能
                status="available" if check_dependency("easyocr") else "missing",  # 根据可用性设置状态
                install_cmd="pip install easyocr",  # 安装命令
                size="100MB+"  # 包大小
            ))

        return deps  # 返回依赖列表


class EmbeddingFeature(BaseFeature):  # 定义嵌入向量功能类，继承BaseFeature
    """嵌入向量功能"""  # 类文档字符串

    feature_id = "embedding"  # 功能ID：唯一标识
    name = "向量嵌入"  # 功能名称
    description = "文本向量化，用于语义搜索"  # 功能描述
    category = FeatureCategory.COGNITION  # 功能分类：认知功能

    def __init__(self):  # 定义初始化方法
        super().__init__()  # 调用父类初始化
        self._model = None  # 初始化模型实例为None

    def check_availability(self) -> bool:  # 定义检查可用性方法
        """检查嵌入功能可用性"""  # 方法文档字符串
        from core.utils.dependency_utils import sentence_transformers_dep  # 导入依赖检查对象
        return sentence_transformers_dep.available  # 返回sentence-transformers是否可用

    def _do_initialize(self) -> bool:  # 定义初始化实现方法
        """初始化嵌入模型"""  # 方法文档字符串
        from core.utils.dependency_utils import sentence_transformers_dep  # 导入依赖检查对象

        if not sentence_transformers_dep.available:  # 如果依赖不可用
            return False  # 返回失败

        try:  # 开始异常处理
            from pathlib import Path

            from sentence_transformers import SentenceTransformer  # 导入SentenceTransformer

            model_name = config.get(  # 获取模型名称配置
                "features.embedding.model",  # 配置键
                "sentence-transformers/all-MiniLM-L6-v2"  # 默认值
            )

            # 优先查找本地 HF 缓存快照路径
            project_root = Path(__file__).parent.parent.parent
            cache_dir = project_root / "checkpoints" / "hf_cache"
            local_root = cache_dir / f"models--{model_name.replace('/', '--')}"
            snapshot_dir = None
            if local_root.exists():
                snapshots = local_root / "snapshots"
                if snapshots.exists():
                    for child in snapshots.iterdir():
                        if child.is_dir():
                            snapshot_dir = child
                            break

            if snapshot_dir is None or not snapshot_dir.exists():
                raise FileNotFoundError(f"本地模型未找到: {local_root}")

            model_path = str(snapshot_dir).replace('\\', '/')
            logger.info(f"[EmbeddingFeature] 加载本地模型: {model_path}")
            self._model = SentenceTransformer(  # 创建模型实例
                model_path,
                local_files_only=True
            )
            return True  # 返回成功
        except Exception as e:  # 捕获异常
            logger.error(f"[EmbeddingFeature] 模型加载失败: {e}")  # 记录错误
            raise  # 强制报错，不再静默降级

    def get_dependencies(self) -> list[DependencyInfo]:  # 定义获取依赖列表方法
        """获取依赖列表"""  # 方法文档字符串
        from core.utils.dependency_utils import sentence_transformers_dep, torch_dep  # 导入依赖检查对象

        return [  # 返回依赖列表
            DependencyInfo(  # PyTorch依赖
                name="torch",  # 依赖名称
                type="pip",  # 依赖类型：pip包
                required=True,  # 必需
                status="available" if torch_dep.available else "missing",  # 根据可用性设置状态
                install_cmd="pip install torch"  # 安装命令
            ),
            DependencyInfo(  # sentence-transformers依赖
                name="sentence-transformers",  # 依赖名称
                type="pip",  # 依赖类型：pip包
                required=True,  # 必需
                status="available" if sentence_transformers_dep.available else "missing",  # 根据可用性设置状态
                install_cmd="pip install sentence-transformers",  # 安装命令
                download_url="https://huggingface.co/sentence-transformers"  # 下载地址
            ),
            DependencyInfo(  # 嵌入模型文件
                name="embedding-model",  # 依赖名称
                type="model_file",  # 依赖类型：模型文件
                required=False,  # 非必需
                status="available",  # 会自动下载
                download_url="https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2",  # 下载地址
                size="80MB"  # 文件大小
            )
        ]

    def encode(self,  # 定义编码方法
               texts: list[str]  # 参数：文本列表
               ) -> list[list[float]] | None:  # 返回：嵌入向量列表或None
        """编码文本"""  # 方法文档字符串
        if self._model is None:  # 如果模型未加载
            return None  # 返回None
        try:  # 开始异常处理
            embeddings = self._model.encode(texts)  # 编码文本
            return embeddings.tolist()  # 转换为Python列表并返回
        except Exception as e:  # 捕获异常
            logger.error(f"[EmbeddingFeature] 编码失败: {e}")  # 记录错误
            return None  # 返回None


class MemoryFeature(BaseFeature):  # 定义记忆系统功能类，继承BaseFeature
    """记忆系统功能"""  # 类文档字符串

    feature_id = "memory"  # 功能ID：唯一标识
    name = "记忆系统"  # 功能名称
    description = "多层级记忆存储和检索"  # 功能描述
    category = FeatureCategory.MEMORY  # 功能分类：记忆功能

    def check_availability(self) -> bool:  # 定义检查可用性方法
        """检查记忆功能可用性"""  # 方法文档字符串
        # SQLite总是可用
        return True  # 记忆功能总是可用

    def _do_initialize(self) -> bool:  # 定义初始化实现方法
        """初始化记忆系统"""  # 方法文档字符串
        # 检查数据目录
        data_dir = Path(__file__).parent.parent / "data" / "memory"  # 构建数据目录路径
        try:  # 开始异常处理
            data_dir.mkdir(parents=True, exist_ok=True)  # 创建目录（如果不存在）
            return True  # 返回成功
        except Exception as e:  # 捕获异常
            logger.error(f"[MemoryFeature] 初始化失败: {e}")  # 记录错误
            return False  # 返回失败

    def get_dependencies(self) -> list[DependencyInfo]:  # 定义获取依赖列表方法
        """获取依赖列表"""  # 方法文档字符串
        deps = []  # 初始化依赖列表

        # 向量记忆依赖
        vector_enabled = config.get("features.memory.vector.enabled", True)  # 获取向量记忆启用配置
        if vector_enabled:  # 如果启用了向量记忆
            from core.utils.dependency_utils import chromadb_dep  # 导入依赖检查对象
            deps.append(DependencyInfo(  # 添加ChromaDB依赖
                name="chromadb",  # 依赖名称
                type="pip",  # 依赖类型：pip包
                required=False,  # 非必需
                feature="memory.vector",  # 关联功能：向量记忆
                status="available" if chromadb_dep.available else "missing",  # 根据可用性设置状态
                install_cmd="pip install chromadb"  # 安装命令
            ))

        return deps  # 返回依赖列表


class ConsciousnessFeature(BaseFeature):  # 定义意识系统功能类，继承BaseFeature
    """意识系统功能"""  # 类文档字符串

    feature_id = "consciousness"  # 功能ID：唯一标识
    name = "意识系统"  # 功能名称
    description = "自主意识和进化引擎"  # 功能描述
    category = FeatureCategory.CONSCIOUSNESS  # 功能分类：意识功能

    def check_availability(self) -> bool:  # 定义检查可用性方法
        """检查意识系统可用性"""  # 方法文档字符串
        # 依赖AI后端
        return True  # 意识系统默认可用（依赖AI后端）

    def _do_initialize(self) -> bool:  # 定义初始化实现方法
        """初始化意识系统"""  # 方法文档字符串
        # 检查配置
        return bool(config.get("features.consciousness.enabled", True))  # 获取启用配置


class AdvancedNLPFeature(BaseFeature):  # 定义高级NLP功能类，继承BaseFeature
    """高级NLP功能（重型模型）"""  # 类文档字符串

    feature_id = "advanced_nlp"  # 功能ID：唯一标识
    name = "高级NLP"  # 功能名称
    description = "使用大型模型的NLP功能（默认关闭）"  # 功能描述
    category = FeatureCategory.COGNITION  # 功能分类：认知功能
    requires_restart = True  # 需要重启：修改配置后需要重启

    def check_availability(self) -> bool:  # 定义检查可用性方法
        """检查高级NLP可用性"""  # 方法文档字符串
        from core.utils.dependency_utils import torch_dep, transformers_dep  # 导入依赖检查对象
        return torch_dep.available and transformers_dep.available  # 返回两个依赖是否都可用

    def _do_initialize(self) -> bool:  # 定义初始化实现方法
        """初始化高级NLP"""  # 方法文档字符串
        # 检查模型文件（配置路径已统一到 features.advanced_models.w2v_bert）
        model_path = config.get("features.advanced_models.w2v_bert.model_path")
        if model_path and not os.path.exists(model_path):  # 如果配置了路径但文件不存在
            logger.warning(f"[AdvancedNLPFeature] 模型不存在: {model_path}")  # 记录警告
            return False  # 返回失败

        return True  # 返回成功

    def get_dependencies(self) -> list[DependencyInfo]:  # 定义获取依赖列表方法
        """获取依赖列表"""  # 方法文档字符串
        from core.utils.dependency_utils import torch_dep, transformers_dep  # 导入依赖检查对象

        deps = [  # 初始化依赖列表
            DependencyInfo(  # PyTorch依赖
                name="torch",  # 依赖名称
                type="pip",  # 依赖类型：pip包
                required=True,  # 必需
                status="available" if torch_dep.available else "missing",  # 根据可用性设置状态
                install_cmd="pip install torch",  # 安装命令
                size="500MB+"  # 包大小
            ),
            DependencyInfo(  # Transformers依赖
                name="transformers",  # 依赖名称
                type="pip",  # 依赖类型：pip包
                required=True,  # 必需
                status="available" if transformers_dep.available else "missing",  # 根据可用性设置状态
                install_cmd="pip install transformers",  # 安装命令
                size="100MB+"  # 包大小
            )
        ]

        # W2V-BERT模型（配置路径已统一到 features.advanced_models.w2v_bert）
        w2v_enabled = config.get("features.advanced_models.w2v_bert.enabled", False)
        if w2v_enabled:  # 如果启用了W2V-BERT
            model_path = config.get("features.advanced_models.w2v_bert.model_path")
            deps.append(DependencyInfo(  # 添加模型依赖
                name="w2v-bert-model",  # 依赖名称
                type="model_file",  # 依赖类型：模型文件
                required=False,  # 非必需
                status="available" if (model_path and os.path.exists(model_path)) else "missing",  # 根据文件是否存在设置状态
                download_url="https://huggingface.co/Alibaba-NLP/w2v-bert-2.0",  # 下载地址
                size="4.4GB"  # 文件大小
            ))

        return deps  # 返回依赖列表


class BTCTradingFeature(BaseFeature):  # 定义BTC交易功能类，继承BaseFeature
    """BTC量化交易功能"""  # 类文档字符串

    feature_id = "btc_trading"  # 功能ID：唯一标识
    name = "BTC量化交易"  # 功能名称
    description = "连接OKX交易所的BTC量化交易系统，支持自主交易、策略选择和风控管理"  # 功能描述
    category = FeatureCategory.EXTENSION  # 功能分类：扩展功能
    configurable = True  # 可配置
    requires_restart = False  # 修改后不需要重启

    def __init__(self):  # 定义初始化方法
        super().__init__()  # 调用父类初始化
        self._btc_system_available = False  # BTC系统可用性标志
        self._api_configured = False  # API配置状态

    def check_availability(self) -> bool:  # 定义检查可用性方法
        """检查BTC交易功能可用性"""
        # 检查 btc_system_v1 路径
        btc_system_path = config.get("features.btc_trading.btc_system_path", "F:/btc_system_v1")
        self._btc_system_available = os.path.exists(btc_system_path) if btc_system_path else False

        # 检查API配置 (环境变量)
        import os as os_module
        okx_api_key = os_module.environ.get("OKX_API_KEY") or config.get("features.btc_trading.okx_api_key")
        self._api_configured = bool(okx_api_key)

        # 功能可用性：btc_system路径存在即可（API可以是模拟模式）
        return self._btc_system_available

    def _do_initialize(self) -> bool:  # 定义初始化实现方法
        """初始化BTC交易功能"""
        try:
            # 尝试导入btc_system模块
            btc_system_path = config.get("features.btc_trading.btc_system_path", "F:/btc_system_v1")
            if btc_system_path and os.path.exists(btc_system_path):
                import sys as sys_module
                if btc_system_path not in sys_module.path:
                    sys_module.path.insert(0, btc_system_path)
                logger.info(f"[BTCTradingFeature] BTC系统路径已添加: {btc_system_path}")

            logger.info("[BTCTradingFeature] BTC交易功能已初始化")
            return True
        except Exception as e:
            logger.error(f"[BTCTradingFeature] 初始化失败: {e}")
            return False

    def get_dependencies(self) -> list[DependencyInfo]:  # 定义获取依赖列表方法
        """获取依赖列表"""
        deps = []

        # BTC系统路径
        btc_system_path = config.get("features.btc_trading.btc_system_path", "F:/btc_system_v1")
        deps.append(DependencyInfo(
            name="btc_system_v1",
            type="service",
            required=True,
            feature="btc_trading.core",
            status="available" if (btc_system_path and os.path.exists(btc_system_path)) else "missing",
            message=f"BTC系统路径: {btc_system_path}"
        ))

        # OKX API配置
        import os as os_module
        okx_api_key = os_module.environ.get("OKX_API_KEY") or config.get("features.btc_trading.okx_api_key")
        deps.append(DependencyInfo(
            name="okx_api",
            type="service",
            required=False,  # 非必需（支持模拟模式）
            feature="btc_trading.trading",
            status="available" if okx_api_key else "missing",
            message="OKX API密钥（可选，缺失时使用模拟模式）"
        ))

        return deps

    def get_status(self) -> dict[str, Any]:  # 定义获取状态方法
        """获取详细状态"""
        status = super().get_status()
        status["sub_features"] = [
            {
                "id": "market_data",
                "name": "市场数据查询",
                "enabled": True,
                "available": self._btc_system_available,
            },
            {
                "id": "strategy_selection",
                "name": "AI策略选择",
                "enabled": True,
                "available": self._btc_system_available,
            },
            {
                "id": "autopilot",
                "name": "自主交易引擎",
                "enabled": config.get("features.btc_trading.autopilot_enabled", True),
                "available": self._btc_system_available,
                "config_path": "features.btc_trading.autopilot_enabled",
            },
            {
                "id": "risk_control",
                "name": "风控系统",
                "enabled": True,
                "available": self._btc_system_available,
            }
        ]
        status["api_configured"] = self._api_configured
        status["demo_mode"] = not self._api_configured
        return status


# ═══════════════════════════════════════════════════════════════
# 轻量功能开关（无复杂生命周期，仅做配置开关管理）
# ═══════════════════════════════════════════════════════════════

class AgentLoopFeature(SimpleFeature):
    """Agent 执行循环"""
    feature_id = "agent_loop"
    name = "Agent 执行循环"
    description = "核心 Agent 循环，负责任务拆解、工具调用和执行反馈"
    category = FeatureCategory.CORE


class ToolSystemFeature(SimpleFeature):
    """工具系统"""
    feature_id = "tool_system"
    name = "工具系统"
    description = "工具发现、调用和管理的子系统"
    category = FeatureCategory.CORE


class MemorySystemFeature(SimpleFeature):
    """记忆系统"""
    feature_id = "memory_system"
    name = "记忆系统"
    description = "多层级记忆存储与检索（工作记忆、短期记忆、长期记忆）"
    category = FeatureCategory.MEMORY


class WorldModelFeature(SimpleFeature):
    """世界模型"""
    feature_id = "world_model"
    name = "世界模型"
    description = "对世界状态进行预测和学习，提升决策质量"
    category = FeatureCategory.COGNITION
    requires_restart = True


class EvolutionFeature(SimpleFeature):
    """进化系统"""
    feature_id = "evolution"
    name = "进化系统"
    description = "根据执行反馈自动优化行为和策略"
    category = FeatureCategory.CONSCIOUSNESS


class WeakConnectionFeature(SimpleFeature):
    """弱连接网络"""
    feature_id = "weak_connection"
    name = "弱连接网络"
    description = "跨会话的隐性记忆关联与联想召回"
    category = FeatureCategory.MEMORY


class SocialReasoningFeature(SimpleFeature):
    """社交推理"""
    feature_id = "social_reasoning"
    name = "社交推理"
    description = "对话中的社交意图理解与关系建模"
    category = FeatureCategory.CONSCIOUSNESS


class ONNXTrainingModeFeature(SimpleFeature):
    """ONNX 视觉训练模式"""
    feature_id = "onnx_training_mode"
    name = "ONNX 视觉训练"
    description = "自动保存未知 UI 元素截图，用于训练自定义 ONNX 检测模型"
    category = FeatureCategory.PERCEPTION


class AdvancedModelsFeature(SimpleFeature):
    """高级模型总开关"""
    feature_id = "advanced_models"
    name = "高级模型"
    description = "BigVGAN、W2V-BERT、MaskGCT 等大型模型能力"
    category = FeatureCategory.EXTENSION
    requires_restart = True

    def get_status(self) -> dict[str, Any]:
        """获取详细状态，包含子模型开关"""
        status = super().get_status()
        status["sub_features"] = [
            {
                "id": "bigvgan_v2",
                "name": "BigVGAN v2",
                "enabled": config.get("features.advanced_models.bigvgan_v2.enabled", False),
                "available": True,
                "config_path": "features.advanced_models.bigvgan_v2.enabled",
            },
            {
                "id": "w2v_bert",
                "name": "W2V-BERT",
                "enabled": config.get("features.advanced_models.w2v_bert.enabled", False),
                "available": True,
                "config_path": "features.advanced_models.w2v_bert.enabled",
            },
            {
                "id": "maskgct",
                "name": "MaskGCT",
                "enabled": config.get("features.advanced_models.maskgct.enabled", False),
                "available": True,
                "config_path": "features.advanced_models.maskgct.enabled",
            },
        ]
        return status


class FeatureManager:  # 定义功能管理器类（单例模式）
    """
    功能管理器 (单例)  # 类文档字符串标题

    管理所有功能模块的生命周期和状态。  # 类说明
    """  # 类文档字符串结束

    _instance: Optional['FeatureManager'] = None  # 类属性：单例实例
    _lock = threading.Lock()  # 类属性：创建单例锁

    def __new__(cls) -> 'FeatureManager':  # 定义创建实例方法
        if cls._instance is None:  # 如果实例不存在
            with cls._lock:  # 获取锁
                if cls._instance is None:  # 双重检查
                    cls._instance = super().__new__(cls)  # 创建实例
                    cls._instance._initialized = False  # 设置初始化标志为False
        return cls._instance  # 返回单例实例

    def __init__(self):  # 定义初始化方法
        if self._initialized:  # 如果已初始化
            return  # 直接返回，避免重复初始化

        self._initialized = True  # 设置初始化标志为True
        self._features: dict[str, BaseFeature] = {}  # 实例属性：功能实例字典
        self._feature_classes: dict[str, type[BaseFeature]] = {}  # 实例属性：功能类字典
        self._lock = threading.RLock()  # 实例属性：创建可重入锁

        # 注册内置功能
        self._register_builtin_features()  # 调用方法注册内置功能

        # 从配置加载功能状态
        self._load_from_config()  # 调用方法从配置加载状态

        # 监听配置变更
        config.add_change_listener(self._on_config_changed)  # 添加配置变更监听器

        logger.info("[FeatureManager] 功能管理器已初始化")  # 记录信息日志

    def get_app_status(self) -> AppStatus:
        """获取全局应用状态"""
        # 【兼容修复】单例可能已在旧版本代码中初始化，缺 _app_status 属性
        if not hasattr(self, '_app_status'):
            self._app_status = AppStatus.RUNNING
        return self._app_status

    def set_app_status(self, status: AppStatus) -> None:
        """设置全局应用状态"""
        self._app_status = status
        logger.info(f"[FeatureManager] 应用状态切换为: {status.value}")

    def _register_builtin_features(self):  # 定义注册内置功能方法
        """注册内置功能"""  # 方法文档字符串
        builtin_features = [  # 内置功能类列表
            AIBackendFeature,  # AI后端功能
            VoiceFeature,  # 语音功能
            VisionFeature,  # 视觉功能
            EmbeddingFeature,  # 嵌入向量功能
            MemoryFeature,  # 记忆系统功能
            ConsciousnessFeature,  # 意识系统功能
            AdvancedNLPFeature,  # 高级NLP功能
            BTCTradingFeature,  # BTC量化交易功能
            # 轻量配置开关
            AgentLoopFeature,
            ToolSystemFeature,
            MemorySystemFeature,
            WorldModelFeature,
            EvolutionFeature,
            WeakConnectionFeature,
            SocialReasoningFeature,
            ONNXTrainingModeFeature,
            AdvancedModelsFeature,
        ]

        for feature_class in builtin_features:  # 遍历内置功能类
            self.register_class(feature_class)  # 注册功能类

    def register_class(self,  # 定义注册功能类方法
                       feature_class: type[BaseFeature]  # 参数：功能类
                       ) -> bool:  # 返回：是否成功
        """
        注册功能类  # 方法文档字符串标题

        Args:  # 参数说明
            feature_class: 功能类  # 参数类型

        Returns:  # 返回值说明
            bool: 注册是否成功  # 返回类型
        """  # 方法文档字符串结束
        if not feature_class.feature_id:  # 如果功能类没有feature_id
            logger.error(f"[FeatureManager] 功能类缺少feature_id: {feature_class}")  # 记录错误
            return False  # 返回失败

        with self._lock:  # 使用锁保证线程安全
            self._feature_classes[feature_class.feature_id] = feature_class  # 添加到类字典
            logger.debug(f"[FeatureManager] 注册功能类: {feature_class.feature_id}")  # 记录调试日志
            return True  # 返回成功

    def register(self,  # 定义注册功能实例方法
                 feature: BaseFeature  # 参数：功能实例
                 ) -> bool:  # 返回：是否成功
        """
        注册功能实例  # 方法文档字符串标题

        Args:  # 参数说明
            feature: 功能实例  # 参数类型

        Returns:  # 返回值说明
            bool: 注册是否成功  # 返回类型
        """  # 方法文档字符串结束
        with self._lock:  # 使用锁保证线程安全
            self._features[feature.feature_id] = feature  # 添加到实例字典
            logger.info(f"[FeatureManager] 注册功能: {feature.feature_id}")  # 记录信息日志
            return True  # 返回成功

    def _load_from_config(self):  # 定义从配置加载方法
        """从配置加载功能状态"""
        # 加载新配置格式
        features_config = config.get("features", {})

        for feature_id, feature_config in features_config.items():
            if not isinstance(feature_config, dict) or "enabled" not in feature_config:
                continue

            enabled = feature_config["enabled"]

            # 功能类必须已注册
            if feature_id not in self._feature_classes:
                continue

            # 获取或创建功能实例（此时才填充 _features）
            feature = self.get_feature(feature_id)
            if feature is None:
                continue

            feature.info.enabled = enabled
            feature.info.config = feature_config

            # 如果启用，检查可用性
            if enabled:
                self.check_feature(feature_id)

    def _on_config_changed(self,  # 定义配置变更回调方法
                           new_config: dict  # 参数：新配置字典
                           ):  # 方法定义结束
        """配置变更回调"""  # 方法文档字符串
        logger.info("[FeatureManager] 配置已变更，刷新功能状态")  # 记录信息
        self._load_from_config()  # 重新从配置加载

    def get_feature(self,  # 定义获取功能实例方法
                    feature_id: str  # 参数：功能ID
                    ) -> BaseFeature | None:  # 返回：功能实例或None
        """
        获取功能实例  # 方法文档字符串标题

        Args:  # 参数说明
            feature_id: 功能ID  # 参数类型

        Returns:  # 返回值说明
            功能实例或None  # 返回类型
        """  # 方法文档字符串结束
        with self._lock:  # 使用锁保证线程安全
            # 如果实例不存在，创建实例
            if feature_id not in self._features:  # 如果实例不存在
                if feature_id in self._feature_classes:  # 如果类存在
                    try:  # 开始异常处理
                        feature = self._feature_classes[feature_id]()  # 创建实例
                        self._features[feature_id] = feature  # 添加到字典
                    except Exception as e:  # 捕获异常
                        logger.error(f"[FeatureManager] 创建功能实例失败 {feature_id}: {e}")  # 记录错误
                        return None  # 返回None
                else:  # 如果类也不存在
                    return None  # 返回None

            return self._features[feature_id]  # 返回功能实例

    def list_features(self,  # 定义列出所有功能方法
                      category: FeatureCategory | None = None,  # 参数：按分类过滤
                      enabled_only: bool = False  # 参数：只返回启用的功能
                      ) -> list[FeatureInfo]:  # 返回：功能信息列表
        """
        列出所有功能  # 方法文档字符串标题

        Args:  # 参数说明
            category: 按分类过滤  # 参数类型
            enabled_only: 只返回启用的功能  # 参数类型

        Returns:  # 返回值说明
            功能信息列表  # 返回类型
        """  # 方法文档字符串结束
        with self._lock:  # 使用锁保证线程安全
            features = []  # 初始化功能列表

            for feature_id in self._feature_classes:  # 遍历所有功能类
                feature = self.get_feature(feature_id)  # 获取功能实例
                if feature is None:  # 如果获取失败
                    continue  # 跳过

                # 分类过滤
                if category and feature.category != category:  # 如果分类不匹配
                    continue  # 跳过

                # 启用状态过滤
                if enabled_only and not feature.info.enabled:  # 如果要求启用但未启用
                    continue  # 跳过

                features.append(feature.info)  # 添加到列表

            return features  # 返回功能列表

    def is_enabled(self,  # 定义检查功能是否启用方法
                   feature_id: str  # 参数：功能ID
                   ) -> bool:  # 返回：是否启用
        """
        检查功能是否启用  # 方法文档字符串标题

        Args:  # 参数说明
            feature_id: 功能ID  # 参数类型

        Returns:  # 返回值说明
            bool: 是否启用  # 返回类型
        """  # 方法文档字符串结束
        feature = self.get_feature(feature_id)  # 获取功能实例
        if feature is None:  # 如果功能不存在
            return False  # 返回False
        return feature.info.enabled  # 返回启用状态

    def is_available(self,  # 定义检查功能是否可用方法
                     feature_id: str  # 参数：功能ID
                     ) -> bool:  # 返回：是否可用
        """
        检查功能是否可用  # 方法文档字符串标题

        Args:  # 参数说明
            feature_id: 功能ID  # 参数类型

        Returns:  # 返回值说明
            bool: 是否可用  # 返回类型
        """  # 方法文档字符串结束
        feature = self.get_feature(feature_id)  # 获取功能实例
        if feature is None:  # 如果功能不存在
            return False  # 返回False

        # 如果未启用，不可用
        if not feature.info.enabled:  # 如果未启用
            return False  # 返回False

        # 检查可用性
        return feature.check_availability()  # 返回可用性检查结果

    def check_feature(self,  # 定义检查功能状态方法
                      feature_id: str  # 参数：功能ID
                      ) -> FeatureState:  # 返回：功能状态
        """
        检查功能状态  # 方法文档字符串标题

        Args:  # 参数说明
            feature_id: 功能ID  # 参数类型

        Returns:  # 返回值说明
            功能状态  # 返回类型
        """  # 方法文档字符串结束
        feature = self.get_feature(feature_id)  # 获取功能实例
        if feature is None:  # 如果功能不存在
            return FeatureState.UNKNOWN  # 返回未知状态

        # 更新状态
        if not feature.info.enabled:  # 如果未启用
            feature.info.state = FeatureState.DISABLED  # 设置为禁用状态
        else:  # 如果已启用
            feature.info.state = FeatureState.CHECKING  # 设置为检查中
            try:  # 开始异常处理
                available = feature.check_availability()  # 检查可用性
                feature.info.available = available  # 更新可用性
                feature.info.state = FeatureState.AVAILABLE if available else FeatureState.MISSING_DEPS  # 更新状态
            except Exception as e:  # 捕获异常
                logger.error(f"[FeatureManager] 检查功能失败 {feature_id}: {e}")  # 记录错误
                feature.info.state = FeatureState.ERROR  # 设置为错误状态
                feature.info.error_message = str(e)  # 记录错误消息

        return feature.info.state  # 返回功能状态

    def enable(self,  # 定义启用功能方法
               feature_id: str  # 参数：功能ID
               ) -> bool:  # 返回：是否成功
        """
        启用功能  # 方法文档字符串标题

        Args:  # 参数说明
            feature_id: 功能ID  # 参数类型

        Returns:  # 返回值说明
            bool: 是否成功  # 返回类型
        """  # 方法文档字符串结束
        feature = self.get_feature(feature_id)  # 获取功能实例
        if feature is None:  # 如果功能不存在
            logger.error(f"[FeatureManager] 功能不存在: {feature_id}")  # 记录错误
            return False  # 返回失败

        with self._lock:  # 使用锁保证线程安全
            feature.info.enabled = True  # 设置启用状态

            # 检查可用性
            if not feature.check_availability():  # 如果不可用
                feature.info.state = FeatureState.MISSING_DEPS  # 设置为缺少依赖状态
                logger.warning(f"[FeatureManager] 功能启用但依赖缺失: {feature_id}")  # 记录警告
            else:  # 如果可用
                # 初始化功能
                success = feature.initialize()  # 初始化功能
                if success:  # 如果初始化成功
                    feature.info.state = FeatureState.RUNNING  # 设置为运行中
                else:  # 如果初始化失败
                    feature.info.state = FeatureState.ERROR  # 设置为错误状态

            # 更新配置
            config.set(f"features.{feature_id}.enabled", True)  # 保存到配置

            # 触发事件
            event_bus.emit("feature_enabled", {"feature_id": feature_id})  # 发送事件

            logger.info(f"[FeatureManager] 功能已启用: {feature_id}")  # 记录信息
            return True  # 返回成功

    def disable(self,  # 定义禁用功能方法
                feature_id: str  # 参数：功能ID
                ) -> bool:  # 返回：是否成功
        """
        禁用功能  # 方法文档字符串标题

        Args:  # 参数说明
            feature_id: 功能ID  # 参数类型

        Returns:  # 返回值说明
            bool: 是否成功  # 返回类型
        """  # 方法文档字符串结束
        feature = self.get_feature(feature_id)  # 获取功能实例
        if feature is None:  # 如果功能不存在
            return False  # 返回失败

        with self._lock:  # 使用锁保证线程安全
            # 反初始化
            feature.deinitialize()  # 调用反初始化

            feature.info.enabled = False  # 设置禁用状态
            feature.info.state = FeatureState.DISABLED  # 设置状态为禁用

            # 更新配置
            config.set(f"features.{feature_id}.enabled", False)  # 保存到配置

            # 触发事件
            event_bus.emit("feature_disabled", {"feature_id": feature_id})  # 发送事件

            logger.info(f"[FeatureManager] 功能已禁用: {feature_id}")  # 记录信息
            return True  # 返回成功

    def configure(self,  # 定义配置功能方法
                  feature_id: str,  # 参数：功能ID
                  config_dict: dict[str, Any]  # 参数：配置字典
                  ) -> bool:  # 返回：是否成功
        """
        配置功能  # 方法文档字符串标题

        Args:  # 参数说明
            feature_id: 功能ID  # 参数类型
            config_dict: 配置字典  # 参数类型

        Returns:  # 返回值说明
            bool: 是否成功  # 返回类型
        """  # 方法文档字符串结束
        feature = self.get_feature(feature_id)  # 获取功能实例
        if feature is None:  # 如果功能不存在
            return False  # 返回失败

        return feature.configure(config_dict)  # 调用功能的配置方法

    def get_status(self,  # 定义获取功能状态方法
                   feature_id: str  # 参数：功能ID
                   ) -> dict[str, Any] | None:  # 返回：状态字典或None
        """
        获取功能状态  # 方法文档字符串标题

        Args:  # 参数说明
            feature_id: 功能ID  # 参数类型

        Returns:  # 返回值说明
            状态字典或None  # 返回类型
        """  # 方法文档字符串结束
        feature = self.get_feature(feature_id)  # 获取功能实例
        if feature is None:  # 如果功能不存在
            return None  # 返回None

        return feature.get_status()  # 返回功能状态

    def get_all_status(self) -> dict[str, Any]:  # 定义获取所有功能状态方法
        """
        获取所有功能状态  # 方法文档字符串标题

        Returns:  # 返回值说明
            状态字典  # 返回类型
        """  # 方法文档字符串结束
        with self._lock:  # 使用锁保证线程安全
            features = []  # 初始化功能列表

            for feature_id in self._feature_classes:  # 遍历所有功能类
                feature = self.get_feature(feature_id)  # 获取功能实例
                if feature:  # 如果获取成功
                    features.append(feature.get_status())  # 添加状态到列表

            # 计算统计
            total = len(features)  # 总功能数
            enabled = sum(1 for f in features if f["enabled"])  # 启用的功能数
            available = sum(1 for f in features if f["available"])  # 可用的功能数
            running = sum(1 for f in features if f["state"] == "running")  # 运行中的功能数

            return {  # 返回状态字典
                "features": features,  # 功能状态列表
                "summary": {  # 统计摘要
                    "total": total,  # 总数
                    "enabled": enabled,  # 启用数
                    "available": available,  # 可用数
                    "running": running,  # 运行中数
                    "degraded": available < enabled  # 是否降级（可用数小于启用数）
                }
            }

    def get_missing_dependencies(self,  # 定义获取缺失依赖方法
                                 feature_id: str  # 参数：功能ID
                                 ) -> list[DependencyInfo]:  # 返回：缺失依赖列表
        """
        获取功能缺失的依赖  # 方法文档字符串标题

        Args:  # 参数说明
            feature_id: 功能ID  # 参数类型

        Returns:  # 返回值说明
            缺失的依赖列表  # 返回类型
        """  # 方法文档字符串结束
        feature = self.get_feature(feature_id)  # 获取功能实例
        if feature is None:  # 如果功能不存在
            return []  # 返回空列表

        deps = feature.get_dependencies()  # 获取所有依赖
        return [d for d in deps if d.status != "available"]  # 过滤出缺失的依赖

    def initialize_all(self):  # 定义初始化所有启用功能方法
        """初始化所有启用的功能"""  # 方法文档字符串
        with self._lock:  # 使用锁保证线程安全
            for feature_id in self._feature_classes:  # 遍历所有功能类
                feature = self.get_feature(feature_id)  # 获取功能实例
                if feature and feature.info.enabled:  # 如果实例存在且已启用
                    logger.info(f"[FeatureManager] 初始化功能: {feature_id}")  # 记录信息
                    feature.initialize()  # 初始化功能


# 全局单例
feature_manager = FeatureManager()  # 创建功能管理器单例


# 便捷函数
def is_feature_enabled(feature_id: str) -> bool:  # 定义检查功能是否启用便捷函数
    """检查功能是否启用"""  # 函数文档字符串
    return feature_manager.is_enabled(feature_id)  # 调用管理器方法


def require_feature(feature_id: str) -> bool:  # 定义要求功能必须启用函数
    """
    要求功能必须启用  # 函数文档字符串标题

    如果功能未启用，抛出异常。  # 函数说明

    Args:  # 参数说明
        feature_id: 功能ID  # 参数类型

    Returns:  # 返回值说明
        bool: 功能是否可用  # 返回类型

    Raises:  # 异常说明
        RuntimeError: 功能未启用  # 抛出的异常类型
    """  # 函数文档字符串结束
    if not feature_manager.is_enabled(feature_id):  # 如果功能未启用
        raise RuntimeError(f"功能 '{feature_id}' 未启用，请在配置中启用")  # 抛出异常

    if not feature_manager.is_available(feature_id):  # 如果功能不可用
        raise RuntimeError(f"功能 '{feature_id}' 依赖缺失，请安装依赖")  # 抛出异常

    return True  # 返回成功


def feature_guard(feature_id: str):  # 定义功能守卫装饰器工厂函数
    """
    功能守卫装饰器  # 函数文档字符串标题

    装饰函数，在功能未启用时返回错误信息。  # 函数说明

    示例:  # 示例标题
        @feature_guard("embedding")  # 使用装饰器
        def encode_text(text: str) -> dict:  # 定义被装饰函数
            # 功能未启用时不会执行  # 说明
            return {"embedding": [...]}  # 返回结果
    """  # 函数文档字符串结束
    def decorator(func):  # 定义装饰器函数
        def wrapper(*args, **kwargs):  # 定义包装函数
            if not feature_manager.is_enabled(feature_id):  # 如果功能未启用
                return {  # 返回错误信息
                    "success": False,  # 失败标志
                    "error": f"功能 '{feature_id}' 未启用",  # 错误消息
                    "action_required": f"请在设置中启用 {feature_id} 功能"  # 操作提示
                }

            if not feature_manager.is_available(feature_id):  # 如果功能不可用
                return {  # 返回错误信息
                    "success": False,  # 失败标志
                    "error": f"功能 '{feature_id}' 依赖缺失",  # 错误消息
                    "action_required": "请安装缺失的依赖"  # 操作提示
                }

            return func(*args, **kwargs)  # 调用原函数
        return wrapper  # 返回包装函数
    return decorator  # 返回装饰器


# 初始化所有功能
if __name__ != "__main__":  # 如果不是作为主程序运行
    # 延迟初始化，避免循环导入
    def _init_features():  # 定义初始化功能函数
        try:  # 开始异常处理
            feature_manager.initialize_all()  # 初始化所有功能
        except Exception as e:  # 捕获异常
            logger.error(f"[FeatureManager] 初始化功能失败: {e}")  # 记录错误

    # 在后台线程中初始化
    threading.Thread(target=_init_features, daemon=True).start()  # 创建并启动守护线程


# =============================================================================
# 总结性注释：文件角色、关联关系与核心效果
# =============================================================================
#
# 【文件角色】
# 本文件（feature_manager.py）是 SiliconBase V5 系统的"功能管理器"核心模块，
# 采用"插排架构"设计，实现功能模块的注册、管理、启用/禁用、状态监控等功能。
# 它是系统的功能开关中心和依赖管理中枢。
#
# 【核心职责】
# 1. 功能注册管理：支持功能类和功能实例的注册
# 2. 状态监控：跟踪功能的 UNKNOWN/DISABLED/RUNNING/ERROR 等状态
# 3. 依赖检查：检查功能的pip包、服务、模型文件等依赖是否满足
# 4. 生命周期管理：管理功能的初始化、反初始化、配置变更
# 5. 动态启用/禁用：支持运行时启用或禁用功能
# 6. 事件通知：功能状态变更时触发事件通知
#
# 【功能分类】
# - CORE:         核心功能（系统必需）
# - PERCEPTION:   感知功能（语音/视觉）
# - COGNITION:    认知功能（AI/NLP）
# - MEMORY:       记忆功能（记忆存储）
# - CONSCIOUSNESS:意识功能（自主意识）
# - EXTENSION:    扩展功能（可选模块）
#
# 【内置功能】
# 1. ai_backend:    AI后端功能（支持Ollama/云端API）
# 2. voice:         语音功能（ASR/TTS）
# 3. vision:        视觉功能（OCR/图像理解）
# 4. embedding:     向量嵌入功能（语义搜索）
# 5. memory:        记忆系统功能（多层级记忆）
# 6. consciousness: 意识系统功能（自主意识）
# 7. advanced_nlp:  高级NLP功能（重型模型）
#
# 【关联文件】
# 1. core/config.py              - 配置管理器
#    * 关系：被本文件导入，用于读取和保存功能配置
#    * 交互：调用 config.get()/config.set() 读写配置，监听配置变更
#
# 2. core/event_bus.py           - 事件总线
#    * 关系：被本文件导入，用于发送功能状态变更事件
#    * 交互：调用 event_bus.emit() 发送 feature_enabled/feature_disabled 事件
#
# 3. core/logger.py              - 日志记录器
#    * 关系：被本文件导入，用于记录功能管理日志
#    * 交互：各方法中调用 logger 记录 info/debug/error 日志
#
# 4. core/dependency_utils.py    - 依赖检查工具
#    * 关系：被本文件导入，用于检查依赖可用性
#    * 交互：使用 vosk_dep/torch_dep 等对象检查依赖状态
#
# 5. core/providers/ai_provider_factory.py - AI提供商工厂
#    * 关系：被 AIBackendFeature 导入
#    * 交互：调用 get_current_provider() 获取AI提供商实例
#
# 【达到的效果】
# 1. 模块化设计：每个功能独立管理，支持按需启用
# 2. 依赖自检查：启动时自动检查依赖，给出安装提示
# 3. 状态可视化：提供功能状态查询接口，支持状态监控
# 4. 热插拔支持：支持运行时启用/禁用功能（部分需要重启）
# 5. 配置持久化：功能启用状态和配置自动保存到配置文件
# 6. 降级运行：依赖缺失时功能自动降级或禁用，不影响系统运行
# 7. 装饰器支持：提供 @feature_guard 装饰器保护功能调用
#
# 【使用场景】
# - 系统启动时：检查并初始化所有启用的功能
# - 配置变更时：动态启用/禁用功能
# - 功能调用前：检查功能是否启用和可用
# - 依赖安装时：查询缺失的依赖并提示安装
# - UI展示时：获取功能状态列表展示给用户
#
# =============================================================================
