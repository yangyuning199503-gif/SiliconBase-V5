"""模型能力自描述 - Model Capability Profiles"""  # 模块文档字符串：定义模型能力画像系统

import json  # 导入JSON模块，用于序列化和反序列化
from dataclasses import dataclass, field  # 从dataclasses导入数据类装饰器和字段函数
from enum import Enum  # 从enum导入枚举类


class TaskType(Enum):  # 定义任务类型枚举类
    """任务类型枚举"""  # 类文档字符串
    CHAT = "chat"  # 普通对话任务  # 枚举值1
    PLANNING = "planning"  # 规划任务，如任务分解  # 枚举值2
    CODE = "code"  # 代码生成任务  # 枚举值3
    ANALYSIS = "analysis"  # 分析任务，如数据分析  # 枚举值4
    CREATIVE = "creative"  # 创意写作任务  # 枚举值5
    SUMMARIZE = "summarize"  # 文本摘要任务  # 枚举值6
    TRANSLATE = "translate"  # 翻译任务  # 枚举值7
    REASONING = "reasoning"  # 推理任务，如逻辑推理  # 枚举值8
    VISION = "vision"  # 视觉任务，如图像理解  # 枚举值9


class SafetyRating(Enum):  # 定义安全评级枚举类
    """安全评级"""  # 类文档字符串
    LOW = "LOW"  # 低安全级别，适合内部测试  # 枚举值1
    MEDIUM = "MEDIUM"  # 中等安全级别，一般场景  # 枚举值2
    HIGH = "HIGH"  # 高安全级别，生产环境  # 枚举值3
    ENTERPRISE = "ENTERPRISE"  # 企业级安全，最高标准  # 枚举值4


@dataclass  # 使用数据类装饰器
class ModelCapabilities:  # 定义模型能力描述数据类
    """  # 类文档字符串开始
    模型能力描述  # 类标题

    描述AI模型的各项能力指标，用于智能路由决策。  # 类说明
    """  # 类文档字符串结束
    task_types: list[TaskType]  # 支持的任务类型列表  # 字段1
    context_length: int  # 上下文长度（token数）  # 字段2
    supports_tools: bool = False  # 是否支持工具调用，默认False  # 字段3
    supports_vision: bool = False  # 是否支持视觉输入，默认False  # 字段4
    supports_streaming: bool = True  # 是否支持流式输出，默认True  # 字段5
    supports_json_mode: bool = False  # 是否支持JSON模式，默认False  # 字段6
    cost_per_1k_tokens: float = 0.0  # 每1k token成本（美元），默认0  # 字段7
    cost_per_1k_input: float = 0.0  # 每1k输入token成本，默认0  # 字段8
    cost_per_1k_output: float = 0.0  # 每1k输出token成本，默认0  # 字段9
    avg_latency_ms: int = 1000  # 平均延迟（毫秒），默认1000  # 字段10
    quality_score: float = 7.0  # 质量评分 0-10，默认7.0  # 字段11
    safety_rating: SafetyRating = SafetyRating.MEDIUM  # 安全评级，默认MEDIUM  # 字段12
    languages: list[str] = field(default_factory=lambda: ["zh", "en"])  # 支持语言，默认中文和英文  # 字段13
    special_features: set[str] = field(default_factory=set)  # 特殊功能集合，默认空集合  # 字段14

    def supports_task(self, task_type: TaskType) -> bool:  # 定义检查是否支持特定任务方法
        """检查是否支持特定任务类型"""  # 方法文档字符串
        return task_type in self.task_types  # 返回任务类型是否在支持列表中

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:  # 定义估算成本方法
        """估算成本（美元）"""  # 方法文档字符串
        if self.cost_per_1k_tokens > 0:  # 如果按总token计费
            return (input_tokens + output_tokens) / 1000 * self.cost_per_1k_tokens  # 计算总成本
        return (input_tokens / 1000 * self.cost_per_1k_input +  # 计算输入成本
                output_tokens / 1000 * self.cost_per_1k_output)  # 加上输出成本

    def to_dict(self) -> dict:  # 定义转换为字典方法
        """转换为字典"""  # 方法文档字符串
        return {  # 返回字典
            "task_types": [t.value for t in self.task_types],  # 任务类型值列表
            "context_length": self.context_length,  # 上下文长度
            "supports_tools": self.supports_tools,  # 工具支持
            "supports_vision": self.supports_vision,  # 视觉支持
            "supports_streaming": self.supports_streaming,  # 流式支持
            "supports_json_mode": self.supports_json_mode,  # JSON模式支持
            "cost_per_1k_tokens": self.cost_per_1k_tokens,  # 统一成本
            "cost_per_1k_input": self.cost_per_1k_input,  # 输入成本
            "cost_per_1k_output": self.cost_per_1k_output,  # 输出成本
            "avg_latency_ms": self.avg_latency_ms,  # 平均延迟
            "quality_score": self.quality_score,  # 质量评分
            "safety_rating": self.safety_rating.value,  # 安全评级值
            "languages": self.languages,  # 支持语言
            "special_features": list(self.special_features),  # 特殊功能转为列表
        }  # 字典结束

    @classmethod  # 类方法装饰器
    def from_dict(cls, data: dict) -> "ModelCapabilities":  # 定义从字典创建方法
        """从字典创建"""  # 方法文档字符串
        return cls(  # 返回类实例
            task_types=[TaskType(t) for t in data.get("task_types", [])],  # 任务类型列表
            context_length=data.get("context_length", 4096),  # 上下文长度，默认4096
            supports_tools=data.get("supports_tools", False),  # 工具支持，默认False
            supports_vision=data.get("supports_vision", False),  # 视觉支持，默认False
            supports_streaming=data.get("supports_streaming", True),  # 流式支持，默认True
            supports_json_mode=data.get("supports_json_mode", False),  # JSON模式，默认False
            cost_per_1k_tokens=data.get("cost_per_1k_tokens", 0.0),  # 统一成本，默认0
            cost_per_1k_input=data.get("cost_per_1k_input", 0.0),  # 输入成本，默认0
            cost_per_1k_output=data.get("cost_per_1k_output", 0.0),  # 输出成本，默认0
            avg_latency_ms=data.get("avg_latency_ms", 1000),  # 延迟，默认1000
            quality_score=data.get("quality_score", 7.0),  # 质量分，默认7.0
            safety_rating=SafetyRating(data.get("safety_rating", "MEDIUM")),  # 安全评级
            languages=data.get("languages", ["zh", "en"]),  # 语言，默认中英
            special_features=set(data.get("special_features", [])),  # 特殊功能转为集合
        )  # 返回结束


@dataclass  # 使用数据类装饰器
class ModelProfile:  # 定义模型画像数据类
    """  # 类文档字符串开始
    模型画像  # 类标题

    完整的模型描述，包含能力、配置和元信息。  # 类说明
    """  # 类文档字符串结束
    name: str  # 模型名称，如 "gpt-4", "qwen3:8b"  # 字段1
    provider: str  # Provider名称，如 "openai", "ollama"  # 字段2
    capabilities: ModelCapabilities  # 能力描述对象  # 字段3
    config: dict = field(default_factory=dict)  # 连接配置字典，默认空  # 字段4
    description: str = ""  # 模型描述，默认空字符串  # 字段5
    version: str = "1.0"  # 模型版本，默认1.0  # 字段6
    is_active: bool = True  # 是否激活，默认True  # 字段7
    priority: int = 0  # 优先级（越高越优先），默认0  # 字段8
    tags: set[str] = field(default_factory=set)  # 标签集合，默认空  # 字段9

    @property  # 属性装饰器
    def full_name(self) -> str:  # 定义完整名称属性
        """完整名称：provider/name"""  # 属性文档字符串
        return f"{self.provider}/{self.name}"  # 返回 provider/name 格式

    def to_dict(self) -> dict:  # 定义转换为字典方法
        """转换为字典"""  # 方法文档字符串
        return {  # 返回字典
            "name": self.name,  # 模型名称
            "provider": self.provider,  # 提供方
            "full_name": self.full_name,  # 完整名称
            "capabilities": self.capabilities.to_dict(),  # 能力字典
            "config": self.config,  # 配置
            "description": self.description,  # 描述
            "version": self.version,  # 版本
            "is_active": self.is_active,  # 激活状态
            "priority": self.priority,  # 优先级
            "tags": list(self.tags),  # 标签转为列表
        }  # 字典结束

    @classmethod  # 类方法装饰器
    def from_dict(cls, data: dict) -> "ModelProfile":  # 定义从字典创建方法
        """从字典创建"""  # 方法文档字符串
        return cls(  # 返回类实例
            name=data["name"],  # 模型名称
            provider=data["provider"],  # 提供方
            capabilities=ModelCapabilities.from_dict(data.get("capabilities", {})),  # 能力对象
            config=data.get("config", {}),  # 配置
            description=data.get("description", ""),  # 描述
            version=data.get("version", "1.0"),  # 版本
            is_active=data.get("is_active", True),  # 激活状态
            priority=data.get("priority", 0),  # 优先级
            tags=set(data.get("tags", [])),  # 标签转为集合
        )  # 返回结束


# ==================== 预定义模型画像 ====================  # 分隔线：预定义模型画像

MODEL_PROFILES: dict[str, ModelProfile] = {}  # 全局模型画像字典，key为full_name


def register_profile(profile: ModelProfile):  # 定义注册模型画像函数
    """注册模型画像"""  # 函数文档字符串
    MODEL_PROFILES[profile.full_name] = profile  # 以完整名称为键存入字典


def get_profile(full_name: str) -> ModelProfile | None:  # 定义获取模型画像函数
    """获取模型画像"""  # 函数文档字符串
    return MODEL_PROFILES.get(full_name)  # 从字典获取，不存在返回None


def list_profiles(  # 定义列出模型画像函数
        provider: str | None = None,  # 按提供方过滤（可选）
        task_type: TaskType | None = None,  # 按任务类型过滤（可选）
        active_only: bool = True  # 是否只返回激活的，默认True
) -> list[ModelProfile]:  # 返回模型画像列表
    """列出模型画像"""  # 函数文档字符串
    profiles = MODEL_PROFILES.values()  # 获取所有画像值

    if provider:  # 如果指定了提供方
        profiles = [p for p in profiles if p.provider == provider]  # 过滤提供方

    if task_type:  # 如果指定了任务类型
        profiles = [p for p in profiles if p.capabilities.supports_task(task_type)]  # 过滤任务支持

    if active_only:  # 如果只返回激活的
        profiles = [p for p in profiles if p.is_active]  # 过滤激活状态

    return list(profiles)  # 转为列表返回


# ===== Ollama 本地模型 =====  # 分隔线：Ollama本地模型
register_profile(ModelProfile(  # 注册通义千问3 8B模型
    name="qwen3:8b",  # 模型名称
    provider="ollama",  # 提供方
    capabilities=ModelCapabilities(  # 能力配置
        task_types=[TaskType.CHAT, TaskType.PLANNING, TaskType.CODE,  # 支持任务类型
                    TaskType.ANALYSIS, TaskType.SUMMARIZE],  # 分析、摘要
        context_length=32768,  # 32K上下文
        supports_tools=True,  # 支持工具
        supports_vision=False,  # 不支持视觉
        supports_streaming=True,  # 支持流式
        supports_json_mode=True,  # 支持JSON
        cost_per_1k_tokens=0.0,  # 本地免费
        avg_latency_ms=500,  # 平均延迟500ms
        quality_score=7.5,  # 质量分7.5
        safety_rating=SafetyRating.MEDIUM,  # 中等安全
        languages=["zh", "en"],  # 支持中英文
        special_features={"local", "offline"},  # 本地、离线特性
    ),
    config={"base_url": "http://localhost:11434"},  # Ollama本地地址
    description="通义千问3 8B本地模型，适合一般任务",  # 描述
    tags={"local", "free", "qwen"},  # 标签
))

register_profile(ModelProfile(  # 注册Llama 3.2 3B模型
    name="llama3.2:3b",  # 模型名称
    provider="ollama",  # 提供方
    capabilities=ModelCapabilities(  # 能力配置
        task_types=[TaskType.CHAT, TaskType.CODE, TaskType.SUMMARIZE],  # 任务类型
        context_length=128000,  # 128K上下文
        supports_tools=False,  # 不支持工具
        supports_vision=False,  # 不支持视觉
        supports_streaming=True,  # 支持流式
        cost_per_1k_tokens=0.0,  # 本地免费
        avg_latency_ms=300,  # 平均延迟300ms（更快）
        quality_score=6.5,  # 质量分6.5
        safety_rating=SafetyRating.MEDIUM,  # 中等安全
        languages=["en", "zh"],  # 支持语言
        special_features={"local", "offline", "fast"},  # 快速特性
    ),
    config={"base_url": "http://localhost:11434"},  # Ollama本地地址
    description="Llama 3.2 3B轻量级模型，速度极快",  # 描述
    tags={"local", "free", "llama", "fast"},  # 标签
))

register_profile(ModelProfile(  # 注册Llama 3.2 Vision 11B模型
    name="llama3.2-vision:11b",  # 模型名称
    provider="ollama",  # 提供方
    capabilities=ModelCapabilities(  # 能力配置
        task_types=[TaskType.CHAT, TaskType.VISION, TaskType.ANALYSIS],  # 视觉任务
        context_length=128000,  # 128K上下文
        supports_tools=False,  # 不支持工具
        supports_vision=True,  # 支持视觉
        supports_streaming=True,  # 支持流式
        cost_per_1k_tokens=0.0,  # 本地免费
        avg_latency_ms=1500,  # 平均延迟1500ms（较慢）
        quality_score=7.0,  # 质量分7.0
        safety_rating=SafetyRating.MEDIUM,  # 中等安全
        languages=["en", "zh"],  # 支持语言
        special_features={"local", "offline", "vision"},  # 视觉特性
    ),
    config={"base_url": "http://localhost:11434"},  # Ollama本地地址
    description="Llama 3.2 Vision 11B本地视觉模型",  # 描述
    tags={"local", "free", "llama", "vision"},  # 标签
))

register_profile(ModelProfile(  # 注册DeepSeek Coder 6.7B模型
    name="deepseek-coder:6.7b",  # 模型名称
    provider="ollama",  # 提供方
    capabilities=ModelCapabilities(  # 能力配置
        task_types=[TaskType.CODE, TaskType.ANALYSIS, TaskType.REASONING],  # 代码、推理
        context_length=16384,  # 16K上下文
        supports_tools=False,  # 不支持工具
        supports_vision=False,  # 不支持视觉
        supports_streaming=True,  # 支持流式
        cost_per_1k_tokens=0.0,  # 本地免费
        avg_latency_ms=800,  # 平均延迟800ms
        quality_score=8.0,  # 质量分8.0（代码强）
        safety_rating=SafetyRating.MEDIUM,  # 中等安全
        languages=["zh", "en"],  # 支持语言
        special_features={"local", "offline", "coding"},  # 代码特性
    ),
    config={"base_url": "http://localhost:11434"},  # Ollama本地地址
    description="DeepSeek Coder专门用于代码生成",  # 描述
    tags={"local", "free", "coding"},  # 标签
))

register_profile(ModelProfile(  # 注册Microsoft Phi-4 14B模型
    name="phi4:14b",  # 模型名称
    provider="ollama",  # 提供方
    capabilities=ModelCapabilities(  # 能力配置
        task_types=[TaskType.CHAT, TaskType.REASONING, TaskType.ANALYSIS],  # 推理任务
        context_length=16384,  # 16K上下文
        supports_tools=False,  # 不支持工具
        supports_vision=False,  # 不支持视觉
        supports_streaming=True,  # 支持流式
        cost_per_1k_tokens=0.0,  # 本地免费
        avg_latency_ms=1200,  # 平均延迟1200ms
        quality_score=7.8,  # 质量分7.8
        safety_rating=SafetyRating.HIGH,  # 高安全
        languages=["en", "zh"],  # 支持语言
        special_features={"local", "offline"},  # 本地离线
    ),
    config={"base_url": "http://localhost:11434"},  # Ollama本地地址
    description="Microsoft Phi-4 14B，推理能力强",  # 描述
    tags={"local", "free", "phi"},  # 标签
))

# ===== OpenAI 云端模型 =====  # 分隔线：OpenAI云端模型
register_profile(ModelProfile(  # 注册GPT-4模型
    name="gpt-4",  # 模型名称
    provider="openai",  # 提供方
    capabilities=ModelCapabilities(  # 能力配置
        task_types=[TaskType.CHAT, TaskType.PLANNING, TaskType.CODE,  # 多任务
                    TaskType.ANALYSIS, TaskType.CREATIVE],  # 创意写作
        context_length=8192,  # 8K上下文
        supports_tools=True,  # 支持工具
        supports_vision=False,  # 不支持视觉
        supports_streaming=True,  # 支持流式
        supports_json_mode=True,  # 支持JSON
        cost_per_1k_input=0.03,  # 输入$0.03/1K
        cost_per_1k_output=0.06,  # 输出$0.06/1K
        avg_latency_ms=2000,  # 平均延迟2000ms
        quality_score=9.5,  # 质量分9.5（旗舰）
        safety_rating=SafetyRating.HIGH,  # 高安全
        languages=["zh", "en", "ja", "ko", "de", "fr", "es"],  # 多语言
        special_features={"enterprise", "reliable"},  # 企业级
    ),
    config={},  # 使用默认配置
    description="GPT-4旗舰模型，综合能力最强",  # 描述
    priority=10,  # 优先级10（最高）
    tags={"cloud", "premium", "gpt"},  # 标签
))

register_profile(ModelProfile(  # 注册GPT-4o模型
    name="gpt-4o",  # 模型名称
    provider="openai",  # 提供方
    capabilities=ModelCapabilities(  # 能力配置
        task_types=[TaskType.CHAT, TaskType.PLANNING, TaskType.CODE,  # 多任务
                    TaskType.ANALYSIS, TaskType.CREATIVE, TaskType.VISION],  # 支持视觉
        context_length=128000,  # 128K上下文
        supports_tools=True,  # 支持工具
        supports_vision=True,  # 支持视觉
        supports_streaming=True,  # 支持流式
        supports_json_mode=True,  # 支持JSON
        cost_per_1k_input=0.005,  # 输入$0.005/1K（更便宜）
        cost_per_1k_output=0.015,  # 输出$0.015/1K
        avg_latency_ms=1500,  # 平均延迟1500ms
        quality_score=9.2,  # 质量分9.2
        safety_rating=SafetyRating.HIGH,  # 高安全
        languages=["zh", "en", "ja", "ko", "de", "fr", "es"],  # 多语言
        special_features={"enterprise", "reliable", "vision", "fast"},  # 快速视觉
    ),
    config={},  # 使用默认配置
    description="GPT-4o多模态模型，支持视觉",  # 描述
    priority=9,  # 优先级9
    tags={"cloud", "vision", "gpt"},  # 标签
))

register_profile(ModelProfile(  # 注册GPT-4o Mini模型
    name="gpt-4o-mini",  # 模型名称
    provider="openai",  # 提供方
    capabilities=ModelCapabilities(  # 能力配置
        task_types=[TaskType.CHAT, TaskType.CODE, TaskType.SUMMARIZE],  # 基础任务
        context_length=128000,  # 128K上下文
        supports_tools=True,  # 支持工具
        supports_vision=True,  # 支持视觉
        supports_streaming=True,  # 支持流式
        supports_json_mode=True,  # 支持JSON
        cost_per_1k_input=0.00015,  # 输入$0.00015/1K（极便宜）
        cost_per_1k_output=0.0006,  # 输出$0.0006/1K
        avg_latency_ms=800,  # 平均延迟800ms（快）
        quality_score=8.0,  # 质量分8.0
        safety_rating=SafetyRating.HIGH,  # 高安全
        languages=["zh", "en"],  # 支持语言
        special_features={"cheap", "fast"},  # 便宜快速
    ),
    config={},  # 使用默认配置
    description="GPT-4o Mini经济型模型",  # 描述
    priority=8,  # 优先级8
    tags={"cloud", "cheap", "gpt"},  # 标签
))

register_profile(ModelProfile(  # 注册O1 Preview模型
    name="o1-preview",  # 模型名称
    provider="openai",  # 提供方
    capabilities=ModelCapabilities(  # 能力配置
        task_types=[TaskType.REASONING, TaskType.ANALYSIS, TaskType.CODE],  # 推理专用
        context_length=128000,  # 128K上下文
        supports_tools=False,  # 不支持工具
        supports_vision=False,  # 不支持视觉
        supports_streaming=False,  # 不支持流式（思考模式）
        supports_json_mode=False,  # 不支持JSON
        cost_per_1k_input=0.015,  # 输入$0.015/1K
        cost_per_1k_output=0.06,  # 输出$0.06/1K
        avg_latency_ms=5000,  # 平均延迟5000ms（慢但强）
        quality_score=9.8,  # 质量分9.8（推理最强）
        safety_rating=SafetyRating.HIGH,  # 高安全
        languages=["zh", "en"],  # 支持语言
        special_features={"reasoning", "chain_of_thought"},  # 推理特性
    ),
    config={},  # 使用默认配置
    description="O1 Preview推理模型，适合复杂推理",  # 描述
    priority=7,  # 优先级7
    tags={"cloud", "reasoning", "o1"},  # 标签
))

# ===== Anthropic Claude =====  # 分隔线：Anthropic Claude模型
register_profile(ModelProfile(  # 注册Claude 3 Opus模型
    name="claude-3-opus",  # 模型名称
    provider="anthropic",  # 提供方
    capabilities=ModelCapabilities(  # 能力配置
        task_types=[TaskType.CHAT, TaskType.PLANNING, TaskType.CODE,  # 多任务
                    TaskType.ANALYSIS, TaskType.CREATIVE],  # 创意
        context_length=200000,  # 200K超长上下文
        supports_tools=True,  # 支持工具
        supports_vision=True,  # 支持视觉
        supports_streaming=True,  # 支持流式
        cost_per_1k_input=0.015,  # 输入$0.015/1K
        cost_per_1k_output=0.075,  # 输出$0.075/1K
        avg_latency_ms=2500,  # 平均延迟2500ms
        quality_score=9.6,  # 质量分9.6
        safety_rating=SafetyRating.ENTERPRISE,  # 企业级安全
        languages=["zh", "en", "ja", "ko", "de", "fr"],  # 多语言
        special_features={"enterprise", "long_context", "vision"},  # 长上下文
    ),
    config={},  # 使用默认配置
    description="Claude 3 Opus，超长上下文",  # 描述
    priority=10,  # 优先级10
    tags={"cloud", "premium", "claude"},  # 标签
))

register_profile(ModelProfile(  # 注册Claude 3 Sonnet模型
    name="claude-3-sonnet",  # 模型名称
    provider="anthropic",  # 提供方
    capabilities=ModelCapabilities(  # 能力配置
        task_types=[TaskType.CHAT, TaskType.CODE, TaskType.ANALYSIS],  # 任务类型
        context_length=200000,  # 200K上下文
        supports_tools=True,  # 支持工具
        supports_vision=True,  # 支持视觉
        supports_streaming=True,  # 支持流式
        cost_per_1k_input=0.003,  # 输入$0.003/1K
        cost_per_1k_output=0.015,  # 输出$0.015/1K
        avg_latency_ms=1500,  # 平均延迟1500ms
        quality_score=8.8,  # 质量分8.8
        safety_rating=SafetyRating.HIGH,  # 高安全
        languages=["zh", "en", "ja", "ko"],  # 支持语言
        special_features={"long_context", "vision", "balanced"},  # 平衡特性
    ),
    config={},  # 使用默认配置
    description="Claude 3 Sonnet，平衡性能与成本",  # 描述
    priority=8,  # 优先级8
    tags={"cloud", "balanced", "claude"},  # 标签
))

# ===== DeepSeek API =====  # 分隔线：DeepSeek API模型
register_profile(ModelProfile(  # 注册DeepSeek Chat模型
    name="deepseek-chat",  # 模型名称
    provider="deepseek",  # 提供方
    capabilities=ModelCapabilities(  # 能力配置
        task_types=[TaskType.CHAT, TaskType.CODE, TaskType.ANALYSIS],  # 任务类型
        context_length=64000,  # 64K上下文
        supports_tools=True,  # 支持工具
        supports_vision=False,  # 不支持视觉
        supports_streaming=True,  # 支持流式
        supports_json_mode=True,  # 支持JSON
        cost_per_1k_input=0.00014,  # 输入$0.00014/1K（极便宜）
        cost_per_1k_output=0.00028,  # 输出$0.00028/1K
        avg_latency_ms=1200,  # 平均延迟1200ms
        quality_score=8.5,  # 质量分8.5
        safety_rating=SafetyRating.HIGH,  # 高安全
        languages=["zh", "en"],  # 支持语言
        special_features={"cheap", "fast", "coding"},  # 便宜快速
    ),
    config={"base_url": "https://api.deepseek.com"},  # DeepSeek API地址
    description="DeepSeek Chat，性价比极高",  # 描述
    priority=8,  # 优先级8
    tags={"cloud", "cheap", "deepseek"},  # 标签
))

register_profile(ModelProfile(  # 注册DeepSeek Reasoner模型
    name="deepseek-reasoner",  # 模型名称
    provider="deepseek",  # 提供方
    capabilities=ModelCapabilities(  # 能力配置
        task_types=[TaskType.REASONING, TaskType.ANALYSIS, TaskType.CODE],  # 推理
        context_length=64000,  # 64K上下文
        supports_tools=True,  # 支持工具
        supports_vision=False,  # 不支持视觉
        supports_streaming=True,  # 支持流式
        cost_per_1k_input=0.00055,  # 输入$0.00055/1K
        cost_per_1k_output=0.00219,  # 输出$0.00219/1K
        avg_latency_ms=3000,  # 平均延迟3000ms
        quality_score=9.0,  # 质量分9.0
        safety_rating=SafetyRating.HIGH,  # 高安全
        languages=["zh", "en"],  # 支持语言
        special_features={"reasoning", "chain_of_thought"},  # 推理特性
    ),
    config={"base_url": "https://api.deepseek.com"},  # DeepSeek API地址
    description="DeepSeek Reasoner，推理专用",  # 描述
    priority=7,  # 优先级7
    tags={"cloud", "reasoning", "deepseek"},  # 标签
))


# ===== 实用函数 =====  # 分隔线：实用函数

def export_profiles_to_json(filepath: str):  # 定义导出配置到JSON函数
    """导出所有配置到JSON文件"""  # 函数文档字符串
    data = {name: profile.to_dict() for name, profile in MODEL_PROFILES.items()}  # 转为字典
    with open(filepath, "w", encoding="utf-8") as f:  # 打开文件写入
        json.dump(data, f, indent=2, ensure_ascii=False)  # 写入JSON，缩进2，支持中文


def load_profiles_from_json(filepath: str):  # 定义从JSON加载配置函数
    """从JSON文件加载配置"""  # 函数文档字符串
    with open(filepath, encoding="utf-8") as f:  # 打开文件读取
        data = json.load(f)  # 加载JSON
    for _name, profile_data in data.items():  # 遍历数据
        register_profile(ModelProfile.from_dict(profile_data))  # 注册每个画像


# 获取所有支持的Provider  # 计算所有Provider列表
PROVIDERS = list({p.provider for p in MODEL_PROFILES.values()})  # 从所有画像提取唯一Provider


# =============================================================================
# 总结性注释：文件角色、关联关系与核心效果
# =============================================================================
#
# 【文件角色】
# 本文件（model_profile.py）是 SiliconBase V5 系统的"模型能力画像中心"，
# 负责定义和管理所有可用AI模型的能力描述、成本、性能指标等元数据。
# 是智能模型路由（Model Routing）的基础数据源。
#
# 【核心定位】
# - 模型自描述：每个模型都有完整的能力画像（Capabilities + Profile）
# - 智能路由基础：为模型选择器提供决策数据（成本、质量、延迟、功能）
# - 多Provider支持：统一描述本地（Ollama）和云端（OpenAI等）模型
# - 任务适配：根据任务类型选择最合适的模型
#
# 【核心类说明】
# 1. TaskType(Enum): 任务类型枚举
#    - CHAT, PLANNING, CODE, ANALYSIS, CREATIVE, SUMMARIZE, TRANSLATE, REASONING, VISION
#
# 2. SafetyRating(Enum): 安全评级枚举
#    - LOW, MEDIUM, HIGH, ENTERPRISE
#
# 3. ModelCapabilities(dataclass): 模型能力描述
#    - 任务类型支持、上下文长度、工具/视觉/流式/JSON支持
#    - 成本估算（input/output统一或分开）
#    - 延迟、质量分、安全评级、语言支持、特殊功能
#    - 方法：supports_task(), estimate_cost(), to_dict(), from_dict()
#
# 4. ModelProfile(dataclass): 完整模型画像
#    - 名称、提供方、能力对象、连接配置
#    - 描述、版本、激活状态、优先级、标签
#    - 属性：full_name（provider/name格式）
#    - 方法：to_dict(), from_dict()
#
# 【预定义模型】
# - Ollama本地模型（5个）：qwen3:8b, llama3.2:3b, llama3.2-vision:11b,
#   deepseek-coder:6.7b, phi4:14b
# - OpenAI云端模型（4个）：gpt-4, gpt-4o, gpt-4o-mini, o1-preview
# - Anthropic模型（2个）：claude-3-opus, claude-3-sonnet
# - DeepSeek API（2个）：deepseek-chat, deepseek-reasoner
#
# 【全局函数】
# - register_profile(): 注册模型画像到全局字典
# - get_profile(): 根据full_name获取画像
# - list_profiles(): 列表查询（支持provider/task_type/active过滤）
# - export_profiles_to_json(): 导出所有配置到JSON
# - load_profiles_from_json(): 从JSON加载配置
#
# 【关联文件】
# 1. core/model_router.py              - 模型路由器（核心使用者）
#    * 关系：本文件是其数据源
#    * 交互：根据capabilities选择最佳模型
#
# 2. core/llm_manager.py               - LLM管理器
#    * 关系：模型实例化管理
#    * 交互：根据profile创建对应模型实例
#
# 3. core/agent_loop.py                - Agent主循环
#    * 关系：任务执行
#    * 交互：根据任务类型查询支持的模型
#
# 4. core/config.py                    - 配置系统
#    * 关系：配置读取
#    * 交互：模型连接配置
#
# 5. 各Provider客户端（openai, ollama等）- 实际调用
#    * 关系：被管理和描述的对象
#    * 交互：profile中的config用于初始化客户端
#
# 【达到的效果】
# 1. 统一描述：所有模型（本地+云端）统一描述格式
# 2. 智能选型：根据任务类型、成本、质量、延迟自动选择最优模型
# 3. 成本估算：精确估算每次调用的成本
# 4. 能力发现：动态查询模型支持的功能
# 5. 灵活配置：支持JSON导入导出，便于管理
# 6. 多租户支持：不同场景使用不同模型集合
# 7. 优先级控制：通过priority字段控制模型选择优先级
#
# 【使用场景】
# - Agent需要根据任务类型选择合适模型时
# - 需要平衡成本和质量进行模型选型时
# - 需要评估不同模型的调用成本时
# - 需要筛选支持特定功能的模型时（如视觉、工具）
# - 需要统一管理多个Provider的模型时
#
# 【数据流】
# 系统启动 -> 加载预定义模型 -> MODEL_PROFILES字典
#     |
# 任务请求 -> ModelRouter根据task_type/cost/quality选择 -> 返回model_profile
#     |
# LLMManager使用profile.config初始化客户端 -> 执行实际调用
#
# =============================================================================
