#!/usr/bin/env python3  # 指定Python解释器路径
# 声明UTF-8编码支持中文
"""
依赖检查器 - SiliconBase V5 插排架构

自动检测Python包、外部服务、模型文件的可用性，
提供安装指南和一键安装功能。

示例:
    from core.dependency_checker import dependency_checker

    # 检查所有依赖
    result = dependency_checker.check_all()

    # 检查特定功能依赖
    result = dependency_checker.check_feature("voice")

    # 获取安装指南
    guide = dependency_checker.get_install_guide("vosk")
"""

import os  # 导入os模块，用于环境变量和路径操作
import socket  # 导入socket模块，用于TCP端口检查
import subprocess  # 导入subprocess模块，用于执行安装命令
import sys  # 导入sys模块，用于Python运行时信息
import urllib.request  # 导入urllib.request模块，用于HTTP检查
from collections.abc import Callable  # 导入类型注解
from dataclasses import asdict, dataclass, field  # 从dataclasses导入数据类工具
from enum import Enum  # 从enum导入Enum基类
from pathlib import Path  # 从pathlib导入Path类，用于路径操作
from typing import Any

from core.config import config  # 从core.config导入config实例
from core.logger import logger  # 从core.logger导入logger实例


class DependencyType(Enum):  # 定义依赖类型枚举
    """依赖类型"""  # 类文档字符串
    PIP = "pip"                     # Python包  # 注释说明类型
    SERVICE = "service"             # 外部服务(HTTP)  # 注释说明类型
    MODEL_FILE = "model_file"       # 模型文件  # 注释说明类型
    BINARY = "binary"               # 可执行文件  # 注释说明类型
    SYSTEM = "system"               # 系统依赖  # 注释说明类型


class DependencyStatus(Enum):  # 定义依赖状态枚举
    """依赖状态"""  # 类文档字符串
    UNKNOWN = "unknown"  # 未知状态
    AVAILABLE = "available"  # 可用
    MISSING = "missing"  # 缺失
    OPTIONAL = "optional"  # 可选（缺失不影响核心功能）
    ERROR = "error"  # 检查出错


@dataclass  # 数据类装饰器
class Dependency:  # 定义依赖项数据类
    """依赖项"""  # 类文档字符串
    name: str  # 依赖名称
    type: DependencyType  # 依赖类型
    required: bool = False  # 是否为必需依赖，默认False
    feature: str | None = None  # 关联功能，可选
    description: str | None = None  # 依赖描述，可选
    status: DependencyStatus = DependencyStatus.UNKNOWN  # 状态，默认UNKNOWN
    version: str | None = None  # 版本号，可选
    message: str | None = None  # 状态消息，可选

    # 安装信息  # 注释标记安装信息字段
    install_cmd: str | None = None  # 安装命令，可选
    pip_package: str | None = None  # pip包名，可选
    download_url: str | None = None  # 下载URL，可选
    install_guide: str | None = None  # 安装指南，可选
    size: str | None = None  # 安装包大小，可选

    # 检查参数  # 注释标记检查参数字段
    check_url: str | None = None  # HTTP检查URL，可选
    check_host: str | None = None  # TCP检查主机，可选
    check_port: int | None = None  # TCP检查端口，可选
    check_path: str | None = None  # 文件检查路径，可选

    def to_dict(self) -> dict[str, Any]:  # 定义转字典方法
        """转换为字典"""  # 方法文档字符串
        result = asdict(self)  # 使用asdict转换为字典
        result['type'] = self.type.value  # 将枚举转为字符串值
        result['status'] = self.status.value  # 将枚举转为字符串值
        return result  # 返回字典


@dataclass  # 数据类装饰器
class CheckResult:  # 定义检查结果数据类
    """检查结果"""  # 类文档字符串
    available: list[Dependency] = field(default_factory=list)  # 可用依赖列表
    missing: list[Dependency] = field(default_factory=list)  # 缺失依赖列表
    optional: list[Dependency] = field(default_factory=list)  # 可选依赖列表
    errors: list[Dependency] = field(default_factory=list)  # 出错依赖列表

    @property  # 属性装饰器
    def all_ok(self) -> bool:  # 定义全部正常属性
        """是否全部可用"""  # 属性文档字符串
        return len(self.missing) == 0 and len(self.errors) == 0  # 检查缺失和错误列表是否为空

    @property  # 属性装饰器
    def required_missing(self) -> list[Dependency]:  # 定义必需缺失属性
        """获取缺失的必须依赖"""  # 属性文档字符串
        return [d for d in self.missing if d.required]  # 过滤出必需的缺失依赖

    def to_dict(self) -> dict[str, Any]:  # 定义转字典方法
        """转换为字典"""  # 方法文档字符串
        return {  # 返回字典
            "available": [d.to_dict() for d in self.available],  # 转换可用依赖
            "missing": [d.to_dict() for d in self.missing],  # 转换缺失依赖
            "optional": [d.to_dict() for d in self.optional],  # 转换可选依赖
            "errors": [d.to_dict() for d in self.errors],  # 转换出错依赖
            "all_ok": self.all_ok  # 包含all_ok标志
        }  # 字典返回结束


class DependencyChecker:  # 定义依赖检查器类
    """  # 类文档字符串开始
    依赖检查器  # 功能描述

    检查各种依赖的可用性，提供安装指南。  # 功能说明
    """  # 类文档字符串结束

    def __init__(self):  # 初始化方法
        self._checkers: dict[DependencyType, Callable[[Dependency], DependencyStatus]] = {  # 初始化检查器映射
            DependencyType.PIP: self._check_pip,  # pip包检查器
            DependencyType.SERVICE: self._check_service,  # 服务检查器
            DependencyType.MODEL_FILE: self._check_model_file,  # 模型文件检查器
            DependencyType.BINARY: self._check_binary,  # 可执行文件检查器
            DependencyType.SYSTEM: self._check_system,  # 系统依赖检查器
        }  # 检查器映射结束

        # 内置依赖定义  # 注释说明内置依赖
        self._builtin_dependencies: dict[str, Dependency] = {}  # 初始化内置依赖字典
        self._init_builtin_dependencies()  # 调用初始化方法

    def _init_builtin_dependencies(self):  # 定义初始化内置依赖方法
        """初始化内置依赖定义"""  # 方法文档字符串
        # AI后端依赖  # 注释标记AI后端依赖
        self._builtin_dependencies["ollama"] = Dependency(  # 创建ollama依赖定义
            name="ollama",  # 名称
            type=DependencyType.SERVICE,  # 类型：服务
            required=False,  # 非必需
            feature="ai_backend",  # 关联功能：AI后端
            description="本地大模型服务",  # 描述
            check_url="http://localhost:11434/api/tags",  # 检查URL
            install_guide="https://ollama.ai/download",  # 安装指南
            download_url="https://ollama.ai/download"  # 下载URL
        )  # ollama依赖定义结束

        # 语音依赖  # 注释标记语音依赖
        self._builtin_dependencies["vosk"] = Dependency(  # 创建vosk依赖定义
            name="vosk",  # 名称
            type=DependencyType.PIP,  # 类型：pip包
            required=False,  # 非必需
            feature="voice.asr",  # 关联功能：语音识别
            description="语音识别库",  # 描述
            pip_package="vosk",  # pip包名
            install_cmd="pip install vosk",  # 安装命令
            download_url="https://alphacephei.com/vosk/"  # 下载URL
        )  # vosk依赖定义结束

        self._builtin_dependencies["piper-tts"] = Dependency(  # 创建piper-tts依赖定义
            name="piper-tts",  # 名称
            type=DependencyType.PIP,  # 类型：pip包
            required=False,  # 非必需
            feature="voice.tts",  # 关联功能：语音合成
            description="语音合成库",  # 描述
            pip_package="piper-tts",  # pip包名
            install_cmd="pip install piper-tts"  # 安装命令
        )  # piper-tts依赖定义结束

        self._builtin_dependencies["sounddevice"] = Dependency(  # 创建sounddevice依赖定义
            name="sounddevice",  # 名称
            type=DependencyType.PIP,  # 类型：pip包
            required=False,  # 非必需
            feature="voice",  # 关联功能：语音
            description="音频设备访问",  # 描述
            pip_package="sounddevice",  # pip包名
            install_cmd="pip install sounddevice"  # 安装命令
        )  # sounddevice依赖定义结束

        # 视觉依赖  # 注释标记视觉依赖
        self._builtin_dependencies["opencv-python"] = Dependency(  # 创建opencv依赖定义
            name="opencv-python",  # 名称
            type=DependencyType.PIP,  # 类型：pip包
            required=True,  # 必需
            feature="vision",  # 关联功能：视觉
            description="OpenCV图像处理",  # 描述
            pip_package="opencv-python",  # pip包名
            install_cmd="pip install opencv-python"  # 安装命令
        )  # opencv依赖定义结束

        self._builtin_dependencies["easyocr"] = Dependency(  # 创建easyocr依赖定义
            name="easyocr",  # 名称
            type=DependencyType.PIP,  # 类型：pip包
            required=False,  # 非必需
            feature="vision.ocr",  # 关联功能：OCR
            description="OCR文字识别",  # 描述
            pip_package="easyocr",  # pip包名
            install_cmd="pip install easyocr",  # 安装命令
            size="100MB+"  # 包大小
        )  # easyocr依赖定义结束

        self._builtin_dependencies["pillow"] = Dependency(  # 创建pillow依赖定义
            name="pillow",  # 名称
            type=DependencyType.PIP,  # 类型：pip包
            required=True,  # 必需
            feature="vision",  # 关联功能：视觉
            description="图像处理库",  # 描述
            pip_package="pillow",  # pip包名
            install_cmd="pip install pillow"  # 安装命令
        )  # pillow依赖定义结束

        # 嵌入依赖  # 注释标记嵌入依赖
        self._builtin_dependencies["torch"] = Dependency(  # 创建torch依赖定义
            name="torch",  # 名称
            type=DependencyType.PIP,  # 类型：pip包
            required=False,  # 非必需
            feature="embedding",  # 关联功能：嵌入
            description="PyTorch深度学习框架",  # 描述
            pip_package="torch",  # pip包名
            install_cmd="pip install torch",  # 安装命令
            size="500MB+"  # 包大小
        )  # torch依赖定义结束

        self._builtin_dependencies["sentence-transformers"] = Dependency(  # 创建sentence-transformers依赖定义
            name="sentence-transformers",  # 名称
            type=DependencyType.PIP,  # 类型：pip包
            required=False,  # 非必需
            feature="embedding",  # 关联功能：嵌入
            description="句子嵌入模型",  # 描述
            pip_package="sentence-transformers",  # pip包名
            install_cmd="pip install sentence-transformers",  # 安装命令
            size="80MB+"  # 包大小
        )  # sentence-transformers依赖定义结束

        # 记忆依赖  # 注释标记记忆依赖
        self._builtin_dependencies["chromadb"] = Dependency(  # 创建chromadb依赖定义
            name="chromadb",  # 名称
            type=DependencyType.PIP,  # 类型：pip包
            required=False,  # 非必需
            feature="memory.vector",  # 关联功能：向量记忆
            description="向量数据库",  # 描述
            pip_package="chromadb",  # pip包名
            install_cmd="pip install chromadb"  # 安装命令
        )  # chromadb依赖定义结束

        # 数据库依赖  # 注释标记数据库依赖
        self._builtin_dependencies["psycopg2"] = Dependency(  # 创建psycopg2依赖定义
            name="psycopg2",  # 名称
            type=DependencyType.PIP,  # 类型：pip包
            required=False,  # 非必需
            feature="database.postgresql",  # 关联功能：PostgreSQL数据库
            description="PostgreSQL适配器",  # 描述
            pip_package="psycopg2-binary",  # pip包名（使用-binary版本更易安装）
            install_cmd="pip install psycopg2-binary"  # 安装命令
        )  # psycopg2依赖定义结束

        self._builtin_dependencies["redis"] = Dependency(  # 创建redis依赖定义
            name="redis",  # 名称
            type=DependencyType.PIP,  # 类型：pip包
            required=False,  # 非必需
            feature="cache.redis",  # 关联功能：Redis缓存
            description="Redis客户端",  # 描述
            pip_package="redis",  # pip包名
            install_cmd="pip install redis"  # 安装命令
        )  # redis依赖定义结束

        # 高级NLP依赖  # 注释标记高级NLP依赖
        self._builtin_dependencies["transformers"] = Dependency(  # 创建transformers依赖定义
            name="transformers",  # 名称
            type=DependencyType.PIP,  # 类型：pip包
            required=False,  # 非必需
            feature="advanced_nlp",  # 关联功能：高级NLP
            description="HuggingFace Transformers",  # 描述
            pip_package="transformers",  # pip包名
            install_cmd="pip install transformers",  # 安装命令
            size="100MB+"  # 包大小
        )  # transformers依赖定义结束

        # 网络工具  # 注释标记网络工具依赖
        self._builtin_dependencies["requests"] = Dependency(  # 创建requests依赖定义
            name="requests",  # 名称
            type=DependencyType.PIP,  # 类型：pip包
            required=True,  # 必需
            description="HTTP请求库",  # 描述
            pip_package="requests",  # pip包名
            install_cmd="pip install requests"  # 安装命令
        )  # requests依赖定义结束

        self._builtin_dependencies["aiohttp"] = Dependency(  # 创建aiohttp依赖定义
            name="aiohttp",  # 名称
            type=DependencyType.PIP,  # 类型：pip包
            required=False,  # 非必需
            description="异步HTTP客户端",  # 描述
            pip_package="aiohttp",  # pip包名
            install_cmd="pip install aiohttp"  # 安装命令
        )  # aiohttp依赖定义结束

        # Web框架  # 注释标记Web框架依赖
        self._builtin_dependencies["fastapi"] = Dependency(  # 创建fastapi依赖定义
            name="fastapi",  # 名称
            type=DependencyType.PIP,  # 类型：pip包
            required=True,  # 必需
            description="Web框架",  # 描述
            pip_package="fastapi",  # pip包名
            install_cmd="pip install fastapi"  # 安装命令
        )  # fastapi依赖定义结束

        self._builtin_dependencies["uvicorn"] = Dependency(  # 创建uvicorn依赖定义
            name="uvicorn",  # 名称
            type=DependencyType.PIP,  # 类型：pip包
            required=True,  # 必需
            description="ASGI服务器",  # 描述
            pip_package="uvicorn",  # pip包名
            install_cmd="pip install uvicorn"  # 安装命令
        )  # uvicorn依赖定义结束

    def _check_pip(self, dep: Dependency) -> DependencyStatus:  # 定义pip包检查方法
        """检查pip包"""  # 方法文档字符串
        try:  # 尝试检查
            package_name = dep.pip_package or dep.name  # 获取包名

            # 尝试导入  # 注释说明检查方式
            __import__(package_name.replace("-", "_"))  # 导入包（将-替换为_）

            # 获取版本  # 注释说明版本获取
            try:  # 尝试获取版本
                module = sys.modules[package_name.replace("-", "_")]  # 获取已加载的模块
                dep.version = getattr(module, "__version__", None)  # 获取__version__属性
            except Exception:  # 如果获取失败
                pass  # 忽略错误

            return DependencyStatus.AVAILABLE  # 返回可用状态
        except ImportError:  # 如果导入失败
            return DependencyStatus.MISSING  # 返回缺失状态
        except Exception as e:  # 如果发生其他错误
            dep.message = str(e)  # 记录错误消息
            return DependencyStatus.ERROR  # 返回错误状态

    def _check_service(self, dep: Dependency) -> DependencyStatus:  # 定义服务检查方法
        """检查外部服务"""  # 方法文档字符串
        try:  # 尝试检查
            # HTTP检查  # 注释说明HTTP检查
            if dep.check_url:  # 如果配置了检查URL
                req = urllib.request.Request(dep.check_url, method="GET")  # 创建GET请求
                with urllib.request.urlopen(req, timeout=5) as resp:  # 发送请求（5秒超时）
                    if resp.status in (200, 204):  # 如果状态码为200或204
                        return DependencyStatus.AVAILABLE  # 返回可用
                    return DependencyStatus.ERROR  # 其他状态码返回错误

            # TCP端口检查  # 注释说明TCP检查
            if dep.check_host and dep.check_port:  # 如果配置了主机和端口
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # 创建TCP socket
                sock.settimeout(3)  # 设置3秒超时
                result = sock.connect_ex((dep.check_host, dep.check_port))  # 尝试连接
                sock.close()  # 关闭socket

                if result == 0:  # 如果连接成功
                    return DependencyStatus.AVAILABLE  # 返回可用
                return DependencyStatus.MISSING  # 返回缺失

            return DependencyStatus.UNKNOWN  # 无检查配置返回未知
        except urllib.error.URLError:  # URL错误
            return DependencyStatus.MISSING  # 返回缺失
        except OSError:  # socket错误
            return DependencyStatus.MISSING  # 返回缺失
        except Exception as e:  # 其他错误
            dep.message = str(e)  # 记录错误消息
            return DependencyStatus.ERROR  # 返回错误

    def _check_model_file(self, dep: Dependency) -> DependencyStatus:  # 定义模型文件检查方法
        """检查模型文件"""  # 方法文档字符串
        try:  # 尝试检查
            check_path = dep.check_path  # 获取检查路径
            if not check_path:  # 如果未配置路径
                return DependencyStatus.UNKNOWN  # 返回未知

            path = Path(check_path)  # 创建Path对象
            if path.exists() and (path.is_dir() and any(path.iterdir()) or path.is_file()):  # 如果路径存在且是非空目录或文件
                return DependencyStatus.AVAILABLE  # 返回可用

            return DependencyStatus.MISSING  # 返回缺失
        except Exception as e:  # 如果发生错误
            dep.message = str(e)  # 记录错误消息
            return DependencyStatus.ERROR  # 返回错误

    def _check_binary(self, dep: Dependency) -> DependencyStatus:  # 定义可执行文件检查方法
        """检查可执行文件"""  # 方法文档字符串
        try:  # 尝试检查
            if not dep.check_path:  # 如果未配置路径
                return DependencyStatus.UNKNOWN  # 返回未知

            # 检查PATH  # 注释说明PATH检查
            for path_dir in os.environ.get("PATH", "").split(os.pathsep):  # 遍历PATH中的目录
                binary_path = Path(path_dir) / dep.check_path  # 构建完整路径
                if binary_path.exists():  # 如果文件存在
                    return DependencyStatus.AVAILABLE  # 返回可用

            # 检查绝对路径  # 注释说明绝对路径检查
            if Path(dep.check_path).exists():  # 如果绝对路径存在
                return DependencyStatus.AVAILABLE  # 返回可用

            return DependencyStatus.MISSING  # 返回缺失
        except Exception as e:  # 如果发生错误
            dep.message = str(e)  # 记录错误消息
            return DependencyStatus.ERROR  # 返回错误

    def _check_system(self, dep: Dependency) -> DependencyStatus:  # 定义系统依赖检查方法
        """检查系统依赖"""  # 方法文档字符串
        # 子类可覆盖  # 注释说明可扩展性
        return DependencyStatus.UNKNOWN  # 默认返回未知

    def check(self, dep: Dependency) -> DependencyStatus:  # 定义通用检查方法
        """  # 方法文档字符串开始
        检查单个依赖  # 功能描述

        Args:  # 参数说明
            dep: 依赖项  # 参数描述

        Returns:  # 返回值说明
            依赖状态  # 返回类型
        """  # 方法文档字符串结束
        dep_type = dep.type
        # 兼容从 feature_manager.DependencyInfo 传入的字符串类型
        if isinstance(dep_type, str):
            try:
                dep_type = DependencyType(dep_type)
            except ValueError:
                dep_type = None

        checker = self._checkers.get(dep_type)  # 获取对应类型的检查器
        if checker:  # 如果找到检查器
            dep.status = checker(dep)  # 执行检查并更新状态
        else:  # 如果未找到检查器
            dep.status = DependencyStatus.UNKNOWN  # 设置为未知

        return dep.status  # 返回状态

    def check_dependency(self, name: str) -> DependencyStatus:  # 定义检查内置依赖方法
        """  # 方法文档字符串开始
        检查内置依赖  # 功能描述

        Args:  # 参数说明
            name: 依赖名称  # 参数描述

        Returns:  # 返回值说明
            依赖状态  # 返回类型
        """  # 方法文档字符串结束
        dep = self._builtin_dependencies.get(name)  # 获取依赖定义
        if dep is None:  # 如果不存在
            return DependencyStatus.UNKNOWN  # 返回未知

        return self.check(dep)  # 执行检查

    def check_all(self) -> CheckResult:  # 定义检查所有依赖方法
        """  # 方法文档字符串开始
        检查所有内置依赖  # 功能描述

        Returns:  # 返回值说明
            检查结果  # 返回类型
        """  # 方法文档字符串结束
        result = CheckResult()  # 创建结果对象

        for _name, dep in self._builtin_dependencies.items():  # 遍历所有内置依赖
            self.check(dep)  # 执行检查

            if dep.status == DependencyStatus.AVAILABLE:  # 如果可用
                result.available.append(dep)  # 加入可用列表
            elif dep.status == DependencyStatus.MISSING:  # 如果缺失
                if dep.required:  # 如果是必需依赖
                    result.missing.append(dep)  # 加入缺失列表
                else:  # 如果是可选依赖
                    result.optional.append(dep)  # 加入可选列表
            elif dep.status == DependencyStatus.ERROR:  # 如果出错
                result.errors.append(dep)  # 加入错误列表

        return result  # 返回结果

    def check_feature(self, feature_id: str) -> CheckResult:  # 定义按功能检查方法
        """  # 方法文档字符串开始
        检查功能相关依赖  # 功能描述

        Args:  # 参数说明
            feature_id: 功能ID  # 参数描述

        Returns:  # 返回值说明
            检查结果  # 返回类型
        """  # 方法文档字符串结束
        result = CheckResult()  # 创建结果对象

        for _name, dep in self._builtin_dependencies.items():  # 遍历所有依赖
            if dep.feature and dep.feature.startswith(feature_id):  # 如果功能ID匹配
                self.check(dep)  # 执行检查

                if dep.status == DependencyStatus.AVAILABLE:  # 如果可用
                    result.available.append(dep)  # 加入可用列表
                elif dep.status == DependencyStatus.MISSING:  # 如果缺失
                    if dep.required:  # 如果是必需依赖
                        result.missing.append(dep)  # 加入缺失列表
                    else:  # 如果是可选依赖
                        result.optional.append(dep)  # 加入可选列表
                elif dep.status == DependencyStatus.ERROR:  # 如果出错
                    result.errors.append(dep)  # 加入错误列表

        return result  # 返回结果

    def get_dependency(self, name: str) -> Dependency | None:  # 定义获取依赖定义方法
        """  # 方法文档字符串开始
        获取依赖定义  # 功能描述

        Args:  # 参数说明
            name: 依赖名称  # 参数描述

        Returns:  # 返回值说明
            依赖定义或None  # 返回类型
        """  # 方法文档字符串结束
        return self._builtin_dependencies.get(name)  # 返回依赖定义

    def get_install_guide(self, name: str) -> dict[str, str] | None:  # 定义获取安装指南方法
        """  # 方法文档字符串开始
        获取安装指南  # 功能描述

        Args:  # 参数说明
            name: 依赖名称  # 参数描述

        Returns:  # 返回值说明
            安装指南或None  # 返回类型
        """  # 方法文档字符串结束
        dep = self._builtin_dependencies.get(name)  # 获取依赖定义
        if dep is None:  # 如果不存在
            return None  # 返回None

        guide = {  # 构建指南字典
            "name": dep.name,  # 依赖名称
            "type": dep.type.value,  # 依赖类型
            "description": dep.description or "",  # 描述
        }  # 基础信息结束

        if dep.pip_package:  # 如果有pip包名
            guide["pip_install"] = f"pip install {dep.pip_package}"  # 添加pip安装命令

        if dep.install_cmd:  # 如果有安装命令
            guide["install_command"] = dep.install_cmd  # 添加安装命令

        if dep.download_url:  # 如果有下载URL
            guide["download_url"] = dep.download_url  # 添加下载URL

        if dep.install_guide:  # 如果有安装指南
            guide["install_guide"] = dep.install_guide  # 添加安装指南

        if dep.size:  # 如果有大小信息
            guide["size"] = dep.size  # 添加大小

        # 根据类型添加特定指南  # 注释说明类型特定指南
        if dep.type == DependencyType.PIP:  # pip包
            guide["notes"] = "在虚拟环境中运行: source .venv/bin/activate 或 .venv\\Scripts\\activate"  # 添加提示
        elif dep.type == DependencyType.SERVICE:  # 服务
            guide["notes"] = "需要手动安装并启动服务"  # 添加提示
        elif dep.type == DependencyType.MODEL_FILE:  # 模型文件
            guide["notes"] = "需要下载模型文件到指定目录"  # 添加提示

        return guide  # 返回指南

    def install_dependency(self, name: str, timeout: int = 300) -> tuple[bool, str]:  # 定义安装依赖方法
        """  # 方法文档字符串开始
        安装依赖  # 功能描述

        尝试自动安装pip包。服务需要手动安装。  # 限制说明

        Args:  # 参数说明
            name: 依赖名称  # 参数描述
            timeout: 超时时间（秒）  # 参数描述

        Returns:  # 返回值说明
            (是否成功, 消息)  # 返回类型
        """  # 方法文档字符串结束
        dep = self._builtin_dependencies.get(name)  # 获取依赖定义
        if dep is None:  # 如果不存在
            return False, f"未知依赖: {name}"  # 返回错误

        # 只能自动安装pip包  # 注释说明限制
        if dep.type != DependencyType.PIP:  # 如果不是pip包
            guide = self.get_install_guide(name)  # 获取指南
            return False, f"无法自动安装 {dep.type.value} 类型依赖，请手动安装: {guide}"  # 返回错误

        # 构建安装命令  # 注释说明命令构建
        package = dep.pip_package or dep.name  # 获取包名
        cmd = [sys.executable, "-m", "pip", "install", package]  # 构建pip安装命令

        try:  # 尝试安装
            logger.info(f"[DependencyChecker] 安装依赖: {package}")  # 记录日志
            result = subprocess.run(  # 执行安装命令
                cmd,  # 命令
                capture_output=True,  # 捕获输出
                text=True,  # 文本模式
                timeout=timeout  # 超时
            )  # 命令执行结束

            if result.returncode == 0:  # 如果成功
                # 重新检查状态  # 注释说明状态更新
                self.check(dep)  # 更新依赖状态
                return True, f"成功安装 {package}"  # 返回成功
            else:  # 如果失败
                return False, f"安装失败: {result.stderr}"  # 返回错误
        except subprocess.TimeoutExpired:  # 如果超时
            return False, f"安装超时（{timeout}秒）"  # 返回超时错误
        except Exception as e:  # 如果发生其他错误
            return False, f"安装出错: {e}"  # 返回错误

    def get_missing_for_feature(self, feature_id: str) -> list[Dependency]:  # 定义获取功能缺失依赖方法
        """  # 方法文档字符串开始
        获取功能缺失的依赖  # 功能描述

        Args:  # 参数说明
            feature_id: 功能ID  # 参数描述

        Returns:  # 返回值说明
            缺失的依赖列表  # 返回类型
        """  # 方法文档字符串结束
        result = self.check_feature(feature_id)  # 检查功能依赖
        return result.missing + result.errors  # 返回缺失和出错的依赖

    def generate_install_script(self, feature_id: str | None = None) -> str:  # 定义生成安装脚本方法
        """  # 方法文档字符串开始
        生成安装脚本  # 功能描述

        Args:  # 参数说明
            feature_id: 功能ID，为None时生成全部  # 参数描述

        Returns:  # 返回值说明
            安装脚本内容  # 返回类型
        """  # 方法文档字符串结束
        lines = [  # 初始化脚本行列表
            "#!/bin/bash",  # Shebang行
            "# SiliconBase V5 依赖安装脚本",  # 脚本标题
            "# 自动生成，请根据实际需要调整",  # 说明
            "",  # 空行
            "set -e",  # 设置错误时退出
            "",  # 空行
            "echo '开始安装依赖...'",  # 开始消息
            ""  # 空行占位
        ]  # 初始化结束

        if feature_id:  # 如果指定了功能
            result = self.check_feature(feature_id)  # 检查功能依赖
            deps = result.missing + result.optional  # 获取缺失和可选依赖
        else:  # 如果未指定功能
            result = self.check_all()  # 检查所有依赖
            deps = result.missing + result.optional  # 获取缺失和可选依赖

        pip_packages = []  # pip包列表
        services = []  # 服务列表

        for dep in deps:  # 遍历依赖
            if dep.type == DependencyType.PIP and dep.pip_package:  # pip包
                pip_packages.append(dep.pip_package)  # 添加到列表
            elif dep.type == DependencyType.SERVICE:  # 服务
                services.append(dep)  # 添加到列表

        # pip包安装  # 注释说明pip安装部分
        if pip_packages:  # 如果有pip包
            lines.append("# 安装Python包")  # 添加注释
            lines.append(f"pip install {' '.join(pip_packages)}")  # 添加安装命令
            lines.append("")  # 空行

        # 服务安装提示  # 注释说明服务部分
        if services:  # 如果有服务
            lines.append("# 以下服务需要手动安装:")  # 添加注释
            for svc in services:  # 遍历服务
                lines.append(f"# - {svc.name}: {svc.install_guide or svc.download_url or '请查阅官方文档'}")  # 添加提示
            lines.append("")  # 空行

        lines.append("echo '依赖安装完成'")  # 添加完成消息

        return "\n".join(lines)  # 返回脚本内容

    def check_from_config(self) -> CheckResult:  # 定义从配置检查方法
        """  # 方法文档字符串开始
        从配置文件检查依赖  # 功能描述

        Returns:  # 返回值说明
            检查结果  # 返回类型
        """  # 方法文档字符串结束
        result = CheckResult()  # 创建结果对象

        # 获取配置中的依赖定义  # 注释说明配置读取
        dep_configs = config.get("dependency_check.dependencies", [])  # 从配置获取依赖列表

        for dep_config in dep_configs:  # 遍历配置
            dep = Dependency(  # 创建依赖对象
                name=dep_config.get("name", ""),  # 名称
                type=DependencyType(dep_config.get("type", "pip")),  # 类型
                required=dep_config.get("required", False),  # 是否必需
                feature=dep_config.get("feature"),  # 功能
                install_cmd=dep_config.get("install_cmd"),  # 安装命令
                download_url=dep_config.get("download_url"),  # 下载URL
                check_url=dep_config.get("check_url"),  # 检查URL
                check_host=dep_config.get("check_host"),  # 检查主机
                check_port=dep_config.get("check_port"),  # 检查端口
                size=dep_config.get("size")  # 大小
            )  # 依赖创建结束

            self.check(dep)  # 执行检查

            if dep.status == DependencyStatus.AVAILABLE:  # 如果可用
                result.available.append(dep)  # 加入可用列表
            elif dep.status == DependencyStatus.MISSING:  # 如果缺失
                if dep.required:  # 如果是必需
                    result.missing.append(dep)  # 加入缺失列表
                else:  # 如果是可选
                    result.optional.append(dep)  # 加入可选列表
            elif dep.status == DependencyStatus.ERROR:  # 如果出错
                result.errors.append(dep)  # 加入错误列表

        return result  # 返回结果


# 全局实例  # 注释说明全局实例
dependency_checker = DependencyChecker()  # 创建全局依赖检查器实例


# 便捷函数  # 注释标记便捷函数
def check_dependency(name: str) -> bool:  # 定义快速检查函数
    """  # 函数文档字符串开始
    快速检查依赖是否可用  # 功能描述

    Args:  # 参数说明
        name: 依赖名称  # 参数描述

    Returns:  # 返回值说明
        bool: 是否可用  # 返回类型
    """  # 函数文档字符串结束
    status = dependency_checker.check_dependency(name)  # 执行检查
    return status == DependencyStatus.AVAILABLE  # 返回是否可用


def get_missing_dependencies() -> list[str]:  # 定义获取缺失依赖函数
    """  # 函数文档字符串开始
    获取所有缺失的依赖名称  # 功能描述

    Returns:  # 返回值说明
        缺失的依赖名称列表  # 返回类型
    """  # 函数文档字符串结束
    result = dependency_checker.check_all()  # 检查所有依赖
    return [d.name for d in result.missing]  # 返回缺失依赖名称列表


def print_dependency_report():  # 定义打印依赖报告函数
    """打印依赖报告"""  # 函数文档字符串
    result = dependency_checker.check_all()  # 检查所有依赖

    print("=" * 60)  # 打印分隔线
    print("SiliconBase V5 依赖检查报告")  # 打印标题
    print("=" * 60)  # 打印分隔线

    print(f"\n✅ 可用依赖 ({len(result.available)}):")  # 打印可用依赖标题
    for dep in result.available:  # 遍历可用依赖
        version = f" (v{dep.version})" if dep.version else ""  # 构建版本字符串
        print(f"  - {dep.name}{version}")  # 打印依赖信息

    if result.missing:  # 如果有缺失依赖
        print(f"\n❌ 缺失依赖 ({len(result.missing)}):")  # 打印缺失依赖标题
        for dep in result.missing:  # 遍历缺失依赖
            guide = dependency_checker.get_install_guide(dep.name)  # 获取指南
            install_cmd = guide.get("pip_install", guide.get("install_command", "请查阅文档"))  # 获取安装命令
            print(f"  - {dep.name}: {install_cmd}")  # 打印依赖和安装命令

    if result.optional:  # 如果有可选依赖
        print(f"\n⚠️  可选依赖 ({len(result.optional)}):")  # 打印可选依赖标题
        for dep in result.optional:  # 遍历可选依赖
            print(f"  - {dep.name} (可选)")  # 打印依赖信息

    if result.errors:  # 如果有出错依赖
        print(f"\n💥 错误 ({len(result.errors)}):")  # 打印错误标题
        for dep in result.errors:  # 遍历出错依赖
            print(f"  - {dep.name}: {dep.message}")  # 打印依赖和错误消息

    print("\n" + "=" * 60)  # 打印分隔线
    print(f"状态: {'全部正常' if result.all_ok else '有依赖缺失'}")  # 打印状态
    print("=" * 60)  # 打印分隔线


# 命令行运行  # 注释说明命令行入口
if __name__ == "__main__":  # 如果是主程序运行
    print_dependency_report()  # 打印依赖报告


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"依赖检查器"，自动检测Python包、外部服务、
# 模型文件的可用性，提供安装指南和一键安装功能，确保系统运行环境完整。
#
# 【设计特点】
# 1. 类型分类：使用DependencyType枚举区分pip、service、model_file等类型
# 2. 状态管理：使用DependencyStatus枚举标记unknown/available/missing/error状态
# 3. 内置依赖：预定义了AI后端、语音、视觉、数据库等常用依赖的配置
# 4. 多检查方式：支持pip导入检查、HTTP服务检查、TCP端口检查、文件检查
# 5. 自动安装：支持自动安装pip包，生成bash安装脚本
# 6. 功能分组：支持按feature_id（如"voice"、"vision"）检查相关依赖
#
# 【关联文件】
# - core/dependency_utils.py     : 提供OptionalDependency包装器
# - core/config.py               : 读取依赖配置
# - core/logger.py               : 记录检查日志
# - main.py                      : 启动时检查必需依赖
#
# 【核心功能效果】
# 1. 环境自检：系统启动前自动检查依赖环境，提前发现问题
# 2. 功能降级：依赖缺失时提供回退方案，不完全阻止系统启动
# 3. 安装辅助：生成安装脚本，提供详细的安装指南
# 4. 版本追踪：自动获取已安装依赖的版本号
# 5. 配置扩展：支持从配置文件动态添加依赖检查
#
# 【使用示例】
# from core.dependency_checker import dependency_checker, check_dependency
#
# # 检查所有依赖
# result = dependency_checker.check_all()
# if not result.all_ok:
#     print("有依赖缺失")
#
# # 检查特定功能
# voice_deps = dependency_checker.check_feature("voice")
#
# # 快速检查
# if check_dependency("redis"):
#     use_redis()
#
# # 获取安装指南
# guide = dependency_checker.get_install_guide("torch")
# print(guide["pip_install"])
# =============================================================================
