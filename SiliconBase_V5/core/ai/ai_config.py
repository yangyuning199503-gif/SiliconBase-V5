#!/usr/bin/env python3                          # 指定Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文字符
"""
AI 参数集中配置管理模块 V1.0

功能：
1. 集中管理所有AI调用参数，避免分散在各处的魔法数字
2. 支持不同场景的参数配置（ReAct、代码生成、一般对话等）
3. 提供参数验证和动态调整能力
4. 与 core.config 集成，支持从配置文件加载

设计原则：
- 低temperature (0.1-0.2)：用于需要严格格式遵循的场景（ReAct、代码生成）
- 中temperature (0.3-0.5)：用于一般对话场景
- 高temperature (0.7+)：用于创意生成场景

2026-02-22 创建
"""

from dataclasses import dataclass, field  # 从dataclasses导入装饰器和字段工厂
from enum import Enum  # 从enum导入枚举基类
from typing import Any  # 从typing导入类型提示

from core.config import config  # 导入全局配置模块，用于读取配置文件
from core.logger import logger  # 导入日志记录器，用于记录配置变更等信息


class AIScene(Enum):                             # 定义AI场景枚举类，用于区分不同使用场景
    """AI调用场景枚举"""                         # 枚举类文档字符串
    REACT = "react"                              # ReAct思考循环场景（需要严格格式遵循）
    CODE = "code"                                # 代码生成场景（需要确定性输出）
    CHAT = "chat"                                # 一般对话场景（平衡创造性）
    CREATIVE = "creative"                        # 创意生成场景（需要多样性）
    REFLECTION = "reflection"                    # 反思过程场景（需要分析性）
    SUMMARY = "summary"                          # 摘要总结场景（需要简洁）


@dataclass                                       # 数据类装饰器，自动生成__init__等方法
class AIModelConfig:                             # 定义AI模型参数配置数据类
    """                                         # 类文档字符串开始
    AI模型参数配置类                             # 类标题

    参数说明：                                    # 参数说明标题
    - temperature: 温度参数，控制输出的随机性（0.0-1.0）  # temperature参数说明
    - top_p: 核采样参数，控制候选词范围（0.0-1.0）  # top_p参数说明
    - top_k: 候选词数量上限                       # top_k参数说明
    - max_tokens: 最大生成token数                 # max_tokens参数说明
    - repeat_penalty: 重复惩罚系数                # repeat_penalty参数说明
    - presence_penalty: 存在惩罚（鼓励新内容）    # presence_penalty参数说明
    - frequency_penalty: 频率惩罚（降低常见词）   # frequency_penalty参数说明
    - stop_sequences: 停止序列列表                # stop_sequences参数说明
    """                                         # 类文档字符串结束
    # 模型标识                                   # 分类注释：模型标识参数
    model_name: str = "qwen3:8b"                 # 模型名称，默认为qwen3:8b

    # 核心生成参数                               # 分类注释：核心生成参数
    temperature: float = 0.2                     # 温度参数，默认0.2（低随机性）
    top_p: float = 0.5                           # 核采样参数，默认0.5
    top_k: int = 20                              # 候选词上限，默认20
    max_tokens: int = 512                        # 最大生成token数，默认512

    # 惩罚参数                                   # 分类注释：惩罚参数
    repeat_penalty: float = 1.2                  # 重复惩罚系数，默认1.2
    presence_penalty: float = 0.5                # 存在惩罚，默认0.5
    frequency_penalty: float = 0.5               # 频率惩罚，默认0.5

    # 停止序列                                   # 分类注释：停止序列
    stop_sequences: list[str] = field(default_factory=lambda: ["\n\n", "```"])  # 默认停止序列：双换行和代码块结束

    # 请求参数                                   # 分类注释：请求参数
    timeout: int = 30                            # 请求超时时间（秒），默认30
    retry_times: int = 2                         # 重试次数，默认2次

    def to_ollama_options(self) -> dict[str, Any]:   # 定义转换为Ollama选项格式的方法
        """转换为Ollama API的options格式"""      # 方法文档字符串
        return {                                    # 返回Ollama格式的参数字典
            "temperature": self.temperature,        # 温度参数映射
            "num_predict": self.max_tokens,         # max_tokens映射为Ollama的num_predict
            "top_p": self.top_p,                    # top_p参数映射
            "top_k": self.top_k,                    # top_k参数映射
            "repeat_penalty": self.repeat_penalty,  # 重复惩罚映射
            "presence_penalty": self.presence_penalty,  # 存在惩罚映射
            "frequency_penalty": self.frequency_penalty,  # 频率惩罚映射
            "stop": self.stop_sequences             # 停止序列映射
        }

    def to_dict(self) -> dict[str, Any]:          # 定义转换为字典的方法
        """转换为字典格式"""                       # 方法文档字符串
        return {                                    # 返回包含所有字段的字典
            "model_name": self.model_name,          # 模型名称
            "temperature": self.temperature,        # 温度参数
            "top_p": self.top_p,                    # top_p参数
            "top_k": self.top_k,                    # top_k参数
            "max_tokens": self.max_tokens,          # 最大token数
            "repeat_penalty": self.repeat_penalty,  # 重复惩罚
            "presence_penalty": self.presence_penalty,  # 存在惩罚
            "frequency_penalty": self.frequency_penalty,  # 频率惩罚
            "stop_sequences": self.stop_sequences,  # 停止序列
            "timeout": self.timeout,                # 超时时间
            "retry_times": self.retry_times         # 重试次数
        }


class AIConfigManager:                           # 定义AI配置管理器类
    """                                         # 类文档字符串开始
    AI配置管理器                                 # 类标题

    为不同场景提供优化的参数配置                   # 类功能描述
    """                                         # 类文档字符串结束

    # 场景默认配置                               # 类属性注释：场景默认配置字典
    DEFAULT_SCENE_CONFIGS: dict[AIScene, dict[str, Any]] = {   # 定义各场景的默认配置
        # ReAct场景：极低温度，强制格式遵循      # 场景说明注释
        AIScene.REACT: {                           # ReAct场景配置
            "temperature": 0.1,                     # 极低温度0.1，确保格式严格遵循
            "top_p": 0.5,                           # top_p设为0.5
            "top_k": 20,                            # top_k设为20
            "max_tokens": 2048,                     # 最大2048token，确保JSON完整输出
            "repeat_penalty": 1.2,                  # 重复惩罚1.2
            "presence_penalty": 0.2,                # 存在惩罚0.2
            "frequency_penalty": 0.2,               # 频率惩罚0.2
            "stop_sequences": ["\n\n\n"],           # 只保留段落分隔符，不拦截JSON
            "timeout": 60,                          # 超时60秒
            "retry_times": 2                        # 重试2次
        },

        # 代码生成场景：低温度，确定性输出         # 场景说明注释
        AIScene.CODE: {                            # 代码生成场景配置
            "temperature": 0.15,                    # 低温度0.15确保代码正确性
            "top_p": 0.4,                           # top_p设为0.4
            "top_k": 15,                            # top_k设为15
            "max_tokens": 4096,                     # 最大4096token，代码可能需要更长
            "repeat_penalty": 1.1,                  # 重复惩罚1.1
            "presence_penalty": 0.2,                # 存在惩罚0.2
            "frequency_penalty": 0.2,               # 频率惩罚0.2
            "stop_sequences": ["\n\n\n"],           # 停止序列
            "timeout": 60,                          # 超时60秒，代码生成可能更久
            "retry_times": 2                        # 重试2次
        },

        # 一般对话场景：中等温度，平衡               # 场景说明注释
        AIScene.CHAT: {                            # 一般对话场景配置
            "temperature": 0.3,                     # 中等温度0.3
            "top_p": 0.7,                           # top_p设为0.7
            "top_k": 40,                            # top_k设为40
            "max_tokens": 1024,                     # 最大1024token
            "repeat_penalty": 1.1,                  # 重复惩罚1.1
            "presence_penalty": 0.5,                # 存在惩罚0.5
            "frequency_penalty": 0.5,               # 频率惩罚0.5
            "stop_sequences": [],                   # 无停止序列
            "timeout": 20,                          # 超时20秒（从30缩短，提高响应速度）
            "retry_times": 2                        # 重试2次
        },

        # 创意生成场景：高温度，鼓励多样性           # 场景说明注释
        AIScene.CREATIVE: {                        # 创意生成场景配置
            "temperature": 0.7,                     # 高温度0.7鼓励多样性
            "top_p": 0.9,                           # top_p设为0.9
            "top_k": 50,                            # top_k设为50
            "max_tokens": 2048,                     # 最大2048token
            "repeat_penalty": 1.0,                  # 重复惩罚1.0（不惩罚）
            "presence_penalty": 0.7,                # 存在惩罚0.7
            "frequency_penalty": 0.7,               # 频率惩罚0.7
            "stop_sequences": [],                   # 无停止序列
            "timeout": 45,                          # 超时45秒
            "retry_times": 2                        # 重试2次
        },

        # 反思场景：较低温度，确保分析准确           # 场景说明注释
        AIScene.REFLECTION: {                      # 反思场景配置
            "temperature": 0.2,                     # 温度0.2
            "top_p": 0.5,                           # top_p设为0.5
            "top_k": 20,                            # top_k设为20
            "max_tokens": 512,                      # 最大512token
            "repeat_penalty": 1.2,                  # 重复惩罚1.2
            "presence_penalty": 0.4,                # 存在惩罚0.4
            "frequency_penalty": 0.4,               # 频率惩罚0.4
            "stop_sequences": ["\n\n"],             # 停止序列
            "timeout": 30,                          # 超时30秒
            "retry_times": 2                        # 重试2次
        },

        # 摘要场景：低温度，确保简洁                 # 场景说明注释
        AIScene.SUMMARY: {                         # 摘要场景配置
            "temperature": 0.15,                    # 低温度0.15
            "top_p": 0.4,                           # top_p设为0.4
            "top_k": 15,                            # top_k设为15
            "max_tokens": 256,                      # 最大256token（摘要要简洁）
            "repeat_penalty": 1.3,                  # 重复惩罚1.3
            "presence_penalty": 0.3,                # 存在惩罚0.3
            "frequency_penalty": 0.3,               # 频率惩罚0.3
            "stop_sequences": ["\n\n", "1.", "2.", "3."],  # 停止序列（避免生成列表）
            "timeout": 15,                          # 超时15秒（从20缩短，提高响应速度）
            "retry_times": 1                        # 重试1次
        }
    }

    def __init__(self):                            # 构造方法
        self._configs: dict[AIScene, AIModelConfig] = {}   # 初始化配置缓存字典
        self._default_model: str = "qwen3:8b"       # 设置默认模型名称
        self._load_from_config()                    # 从配置文件加载设置

        # 注册配置变更监听器，实现热重载             # 注释：热重载机制
        config.add_change_listener(self._on_config_changed)   # 注册配置变更回调

    def _on_config_changed(self, new_config: dict):  # 配置变更回调方法
        """配置变更回调（热重载）"""               # 方法文档字符串
        try:                                        # 异常处理块开始
            old_model = self._default_model         # 记录旧模型名称
            self._configs.clear()                   # 清除缓存，强制重新加载
            self._load_from_config()                # 重新从配置加载
            logger.info(f"[AIConfig] 配置已热重载，模型: {old_model} -> {self._default_model}")   # 记录热重载日志

            # 刷新AI Provider，确保使用新配置（延迟导入避免循环依赖）  # 注释：刷新Provider
            try:                                    # 内层try块
                import core.ai_adapter as ai_adapter  # 延迟导入ai_adapter
                ai_adapter.refresh_provider()       # 刷新AI Provider
                logger.info("[AIConfig] AI Provider已刷新")   # 记录成功日志
            except Exception as e:                  # 捕获Provider刷新异常
                logger.warning(f"[AIConfig] 刷新Provider失败: {e}")   # 记录警告日志
        except Exception as e:                      # 捕获热重载异常
            logger.error(f"[AIConfig] 热重载配置失败: {e}")   # 记录错误日志

    def _load_from_config(self):                   # 从配置加载方法
        """从全局配置加载设置"""                   # 方法文档字符串
        try:                                        # 异常处理块
            # 从config加载默认模型                   # 注释：加载默认模型
            self._default_model = config.get("ai.default_model", "qwen3:8b")   # 从全局配置读取默认模型

            # 【新增】场景到 timeouts 配置的映射         # 注释：超时配置映射
            scene_timeout_map = {                   # 定义场景到timeout配置的映射
                AIScene.CHAT: "timeouts.chat",      # chat场景使用timeouts.chat
                AIScene.CODE: "timeouts.vision",    # code场景使用timeouts.vision
                AIScene.REACT: "timeouts.long",     # react场景使用timeouts.long
                AIScene.CREATIVE: "timeouts.default",  # creative场景使用timeouts.default
                AIScene.REFLECTION: "timeouts.long",   # reflection场景使用timeouts.long
                AIScene.SUMMARY: "timeouts.default"    # summary场景使用timeouts.default
            }

            # 从config加载自定义配置（如果存在）       # 注释：加载场景配置
            for scene in AIScene:                   # 遍历所有场景枚举
                config_key = f"ai.scene.{scene.value}"   # 构建配置键名
                scene_config = config.get(config_key)   # 从全局配置获取场景配置

                # 合并默认配置和自定义配置             # 注释：配置合并逻辑
                defaults = self.DEFAULT_SCENE_CONFIGS[scene].copy()   # 复制默认配置

                # 【新增】从 timeouts.* 读取超时配置      # 注释：从配置读取超时
                timeout_path = scene_timeout_map.get(scene, "timeouts.default")   # 获取超时配置路径
                try:                                # 异常处理块
                    config_timeout = config.get(timeout_path)   # 从全局配置读取超时
                    if config_timeout is not None:  # 如果配置存在
                        defaults["timeout"] = int(config_timeout)   # 使用配置的超时值
                        logger.debug(f"[AIConfig] 场景 {scene.value} 从 {timeout_path} 加载超时: {config_timeout}s")   # 记录调试日志
                except (ValueError, TypeError) as e:   # 捕获转换异常
                    logger.warning(f"[AIConfig] 超时配置格式错误 {timeout_path}: {e}，使用默认值")   # 记录警告

                # 合并自定义场景配置（如果存在）         # 注释：合并自定义配置
                if scene_config and isinstance(scene_config, dict):   # 如果存在且是字典
                    # 【修复】过滤掉 AIModelConfig 不接受的字段（如旧版 'model'）
                    valid_keys = set(AIModelConfig.__dataclass_fields__.keys())
                    filtered_config = {k: v for k, v in scene_config.items() if k in valid_keys}
                    if len(filtered_config) != len(scene_config):
                        dropped = set(scene_config.keys()) - valid_keys
                        logger.debug(f"[AIConfig] 场景 {scene.value} 配置中存在未知字段，已忽略: {dropped}")
                    defaults.update(filtered_config)   # 用自定义配置覆盖
                    logger.debug(f"[AIConfig] 从配置加载场景 {scene.value}")   # 记录调试日志

                # 设置模型名称（兼容旧版 'model' 键）
                scene_model = scene_config.get("model") if scene_config else None
                if scene_model and str(scene_model).lower() != "default":
                    defaults["model_name"] = scene_model
                elif "model_name" not in defaults:
                    defaults["model_name"] = self._default_model

                # 创建配置对象                         # 注释：创建配置对象
                self._configs[scene] = AIModelConfig(**defaults)   # 创建并缓存配置对象

        except Exception as e:                      # 捕获加载异常
            logger.warning(f"[AIConfig] 从配置加载失败: {e}，使用默认配置")   # 记录警告，使用默认配置

    def get_config(self, scene: AIScene, model_name: str | None = None) -> AIModelConfig:   # 获取配置方法
        """                                         # 方法文档字符串开始
        获取指定场景的配置                           # 方法功能描述

        Args:                                       # 参数说明
            scene: AI场景枚举                         # scene参数
            model_name: 可选，指定模型名称（覆盖默认）  # model_name参数

        Returns:                                    # 返回值说明
            AIModelConfig 配置对象                    # 返回类型
        """                                         # 方法文档字符串结束
        if scene not in self._configs:              # 如果该场景配置尚未加载
            # 创建默认配置                           # 注释：创建默认配置
            defaults = self.DEFAULT_SCENE_CONFIGS[scene].copy()   # 复制场景默认配置
            actual_model = model_name if model_name and str(model_name).lower() != "default" else self._default_model   # 过滤"default"
            defaults["model_name"] = actual_model   # 设置模型名称
            self._configs[scene] = AIModelConfig(**defaults)   # 创建并缓存配置对象

        config_obj = self._configs[scene]           # 获取场景配置对象

        # 如果指定了模型名称，临时替换               # 注释：模型名称覆盖逻辑
        if model_name and str(model_name).lower() != "default":  # 如果提供了有效模型名称（不是"default"）
            config_obj = AIModelConfig(              # 创建新的配置对象
                **{**config_obj.to_dict(), "model_name": model_name}   # 复制原配置并覆盖模型名
            )

        return config_obj                           # 返回配置对象

    def get_react_config(self, model_name: str | None = None) -> AIModelConfig:   # 获取ReAct配置便捷方法
        """获取ReAct场景配置（便捷方法）"""         # 方法文档字符串
        return self.get_config(AIScene.REACT, model_name)   # 调用get_config获取REACT场景配置

    def get_code_config(self, model_name: str | None = None) -> AIModelConfig:   # 获取代码配置便捷方法
        """获取代码生成场景配置（便捷方法）"""       # 方法文档字符串
        return self.get_config(AIScene.CODE, model_name)   # 调用get_config获取CODE场景配置

    def get_chat_config(self, model_name: str | None = None) -> AIModelConfig:   # 获取对话配置便捷方法
        """获取一般对话场景配置（便捷方法）"""       # 方法文档字符串
        return self.get_config(AIScene.CHAT, model_name)   # 调用get_config获取CHAT场景配置

    def update_scene_config(self, scene: AIScene, **kwargs):   # 更新场景配置方法
        """                                         # 方法文档字符串开始
        更新指定场景的配置                           # 方法功能描述

        Args:                                       # 参数说明
            scene: AI场景枚举                         # scene参数
            **kwargs: 要更新的参数                     # kwargs可变参数
        """                                         # 方法文档字符串结束
        current_config = self.get_config(scene)     # 获取当前场景配置
        current_dict = current_config.to_dict()     # 转换为字典
        current_dict.update(kwargs)                 # 更新字典
        self._configs[scene] = AIModelConfig(**current_dict)   # 创建新的配置对象并缓存
        logger.info(f"[AIConfig] 已更新场景 {scene.value} 配置: {kwargs}")   # 记录更新日志

    def get_all_configs(self) -> dict[str, dict[str, Any]]:   # 获取所有配置方法
        """获取所有场景配置的字典表示"""             # 方法文档字符串
        return {                                    # 返回字典推导式
            scene.value: self.get_config(scene).to_dict()   # 键为场景名，值为配置字典
            for scene in AIScene                    # 遍历所有场景
        }

    def validate_config(self, config_obj: AIModelConfig) -> tuple[bool, list[str]]:   # 验证配置方法
        """                                         # 方法文档字符串开始
        验证配置参数的有效性                         # 方法功能描述

        Returns:                                    # 返回值说明
            (是否有效, 错误信息列表)                  # 返回元组
        """                                         # 方法文档字符串结束
        errors = []                                 # 初始化错误列表

        # 验证temperature                            # 注释：验证温度参数
        if not 0.0 <= config_obj.temperature <= 2.0:   # 检查范围[0.0, 2.0]
            errors.append(f"temperature {config_obj.temperature} 超出范围 [0.0, 2.0]")   # 添加错误信息

        # 验证top_p                                  # 注释：验证top_p参数
        if not 0.0 <= config_obj.top_p <= 1.0:      # 检查范围[0.0, 1.0]
            errors.append(f"top_p {config_obj.top_p} 超出范围 [0.0, 1.0]")   # 添加错误信息

        # 验证top_k                                  # 注释：验证top_k参数
        if config_obj.top_k < 1:                    # 检查是否>=1
            errors.append(f"top_k {config_obj.top_k} 必须 >= 1")   # 添加错误信息

        # 验证max_tokens                             # 注释：验证max_tokens参数
        if config_obj.max_tokens < 1:               # 检查是否>=1
            errors.append(f"max_tokens {config_obj.max_tokens} 必须 >= 1")   # 添加错误信息

        # 验证timeout                                # 注释：验证timeout参数
        if config_obj.timeout < 1:                  # 检查是否>=1
            errors.append(f"timeout {config_obj.timeout} 必须 >= 1")   # 添加错误信息

        # 验证retry_times                            # 注释：验证retry_times参数
        if config_obj.retry_times < 0:              # 检查是否>=0
            errors.append(f"retry_times {config_obj.retry_times} 必须 >= 0")   # 添加错误信息

        return len(errors) == 0, errors             # 返回验证结果（无错误则有效）


# 全局配置管理器实例                             # 注释：全局单例实例
ai_config = AIConfigManager()                    # 创建AIConfigManager全局单例


# 便捷函数                                       # 注释：模块级便捷函数

def get_react_config(model_name: str | None = None) -> AIModelConfig:   # 获取ReAct配置便捷函数
    """获取ReAct配置"""                         # 函数文档字符串
    return ai_config.get_react_config(model_name)   # 调用管理器方法获取ReAct配置


def get_code_config(model_name: str | None = None) -> AIModelConfig:   # 获取代码配置便捷函数
    """获取代码生成配置"""                       # 函数文档字符串
    return ai_config.get_code_config(model_name)   # 调用管理器方法获取CODE配置


def get_chat_config(model_name: str | None = None) -> AIModelConfig:   # 获取对话配置便捷函数
    """获取对话配置"""                           # 函数文档字符串
    return ai_config.get_chat_config(model_name)   # 调用管理器方法获取CHAT配置


def get_config_for_scene(scene: str, model_name: str | None = None) -> AIModelConfig:   # 根据场景名获取配置
    """                                         # 函数文档字符串开始
    根据场景名称获取配置                         # 函数功能描述

    Args:                                       # 参数说明
        scene: 场景名称字符串                     # scene参数
        model_name: 可选模型名称                  # model_name参数

    Returns:                                    # 返回值说明
        AIModelConfig                             # 返回配置对象
    """                                         # 函数文档字符串结束
    try:                                        # 异常处理块
        scene_enum = AIScene(scene.lower())     # 将字符串转换为枚举
        return ai_config.get_config(scene_enum, model_name)   # 获取配置
    except ValueError:                          # 捕获无效场景名异常
        logger.warning(f"[AIConfig] 未知场景 '{scene}'，使用CHAT默认配置")   # 记录警告
        return ai_config.get_chat_config(model_name)   # 返回CHAT默认配置


# 向后兼容：提供类似config.get的接口             # 注释：向后兼容接口
def get_ai_param(key: str, default: Any = None) -> Any:   # 获取AI参数便捷函数
    """                                         # 函数文档字符串开始
    获取AI参数（向后兼容）                       # 函数功能描述

    支持的路径：                                  # 支持的路径格式说明
    - scene.<scene_name>.<param> 如 scene.react.temperature  # 场景参数路径示例
    - default.<param> 如 default.model           # 默认参数路径示例
    """                                         # 函数文档字符串结束
    parts = key.split(".")                      # 按点分割键名
    if len(parts) >= 2 and parts[0] == "scene": # 如果是场景参数路径
        scene_name = parts[1]                   # 提取场景名
        param_name = ".".join(parts[2:]) if len(parts) > 2 else None   # 提取参数名

        cfg = get_config_for_scene(scene_name)  # 获取场景配置
        if param_name:                          # 如果指定了参数名
            return getattr(cfg, param_name, default)   # 返回指定参数值
        return cfg                              # 返回整个配置对象

    # 默认从全局config获取                         # 注释：默认处理方式
    return config.get(f"ai.{key}", default)     # 从全局配置获取AI参数


def _get_default_timeout(scene: str) -> int:
    """
    获取场景的默认超时时间（硬编码默认值）

    Args:
        scene: 场景名称字符串

    Returns:
        默认超时时间（秒）
    """
    defaults = {
        "chat": 20,
        "vision": 60,
        "code": 60,
        "summarize": 15,
        "plan": 45,
        "default": 30
    }
    return defaults.get(scene, 30)


def _get_default_temperature(scene: str) -> float:
    """
    获取场景的默认温度参数（硬编码默认值）

    Args:
        scene: 场景名称字符串

    Returns:
        默认temperature值
    """
    defaults = {
        "chat": 0.3,
        "vision": 0.2,
        "code": 0.15,
        "summarize": 0.15,
        "plan": 0.2,
        "default": 0.2
    }
    return defaults.get(scene, 0.2)


def _get_default_max_tokens(scene: str) -> int:
    """
    获取场景的默认最大token数（硬编码默认值）

    Args:
        scene: 场景名称字符串

    Returns:
        默认max_tokens值
    """
    defaults = {
        "chat": 1024,
        "vision": 2048,
        "code": 4096,
        "summarize": 256,
        "plan": 2048,
        "default": 1024
    }
    return defaults.get(scene, 1024)


def get_scene_config(scene: str) -> dict[str, Any]:
    """
    【修改】获取场景配置，优先从 timeouts.* 读取超时配置

    Args:
        scene: 场景名称字符串，支持 chat/vision/code/summarize/plan/creative/reflection/default

    Returns:
        包含 timeout, temperature, max_tokens 的字典

    Example:
        >>> get_scene_config("chat")
        {'timeout': 20, 'temperature': 0.3, 'max_tokens': 1024}
        >>> get_scene_config("code")
        {'timeout': 60, 'temperature': 0.15, 'max_tokens': 4096}
    """
    # 场景到 timeouts 配置的映射
    scene_timeout_map = {
        "chat": "timeouts.chat",
        "vision": "timeouts.vision",
        "code": "timeouts.vision",      # code 使用 vision 的超时
        "summarize": "timeouts.default",
        "plan": "timeouts.long",
        "creative": "timeouts.default",
        "reflection": "timeouts.long",
        "default": "timeouts.default"
    }

    # 硬编码默认值（向后兼容）
    hardcoded_timeouts = {
        "chat": 20,
        "vision": 60,
        "code": 60,
        "summarize": 15,
        "plan": 45,
        "creative": 30,
        "reflection": 30,
        "default": 30
    }

    try:
        # 【新增】从配置读取超时
        timeout_path = scene_timeout_map.get(scene, "timeouts.default")
        config_timeout = config.get(timeout_path)

        if config_timeout is not None:
            try:
                timeout = int(config_timeout)
                logger.debug(f"[AIConfig] 场景 {scene} 使用配置超时: {timeout}s (来源: {timeout_path})")
            except (ValueError, TypeError) as e:
                logger.error(f"[AIConfig] 超时配置格式错误 {timeout_path}={config_timeout}: {e}")
                # 回退到硬编码
                timeout = hardcoded_timeouts.get(scene, 30)
        else:
            # 配置不存在，使用硬编码
            timeout = hardcoded_timeouts.get(scene, 30)
            logger.debug(f"[AIConfig] 场景 {scene} 使用默认超时: {timeout}s")

    except Exception as e:
        logger.error(f"[AIConfig] 读取超时配置失败: {e}", exc_info=True)
        # 使用硬编码默认值
        timeout = hardcoded_timeouts.get(scene, 30)

    # 其他配置参数（保持原有逻辑）
    return {
        "timeout": timeout,
        "temperature": _get_default_temperature(scene),
        "max_tokens": _get_default_max_tokens(scene)
    }


# =============================================================================
# 【文件总结性注释】
# =============================================================================
#
# 【文件角色】
# core/ai_config.py 是 SiliconBase V5 项目的 "AI参数集中配置管理模块"，位于 core 目录下。
#
# 核心定位：
#   - 作为AI模型参数的"配置中心"，统一管理所有AI调用参数
#   - 避免参数分散在各处形成的"魔法数字"问题
#   - 为不同使用场景（ReAct、代码生成、对话等）提供优化的参数配置
#
# 主要职责：
#   1. 场景化管理：定义6种AI使用场景（REACT/CODE/CHAT/CREATIVE/REFLECTION/SUMMARY）
#   2. 参数封装：通过 AIModelConfig 数据类封装所有模型参数
#   3. 配置热重载：与 core.config 集成，支持配置文件变更时自动刷新
#   4. 参数验证：提供 validate_config 方法验证参数有效性
#   5. 便捷访问：提供模块级便捷函数，简化配置获取
#
# -----------------------------------------------------------------------------
#
# 【关联文件】
#
# 1. 依赖的模块（被本文件导入）：
#    - core.config
#      * 提供全局配置管理功能
#      * 本文件注册配置变更监听器到 config
#      * 从 config 读取 ai.default_model 等配置
#
#    - core.logger
#      * 提供日志记录功能
#      * 记录配置变更、热重载等信息
#
# 2. 被依赖的模块（导入本文件）：
#    - core/ai_adapter.py
#      * 调用本文件的 get_react_config、get_code_config、get_chat_config
#      * 调用 AIScene 枚举区分场景
#      * 在 _on_config_changed 中被刷新 Provider
#
#    - ai_client.py（根目录）
#      * 可能间接使用本模块的配置
#
#    - 各业务模块
#      * 根据业务场景调用相应的配置获取函数
#
# -----------------------------------------------------------------------------
#
# 【核心组件】
#
# 1. AIScene 枚举：
#    - 定义6种AI使用场景
#    - 作为配置管理的键值
#
# 2. AIModelConfig 数据类：
#    - 封装所有模型参数（temperature/top_p/max_tokens等）
#    - 提供 to_ollama_options() 转换为Ollama格式
#    - 提供 to_dict() 转换为字典格式
#
# 3. AIConfigManager 配置管理器：
#    - 维护场景到配置的映射
#    - 实现配置热重载机制
#    - 提供参数验证功能
#
# -----------------------------------------------------------------------------
#
# 【达到的效果】
#
# 1. 集中管理：
#    - 所有AI参数集中在一处管理
#    - 避免分散在各处的魔法数字
#    - 便于统一调整和优化
#
# 2. 场景化配置：
#    - 不同场景使用最优参数组合
#    - ReAct：低temperature确保JSON格式遵循
#    - CODE：低temperature确保代码正确性
#    - CREATIVE：高temperature鼓励多样性
#
# 3. 配置热重载：
#    - 配置文件变更时自动刷新
#    - 无需重启应用即可生效
#    - 自动刷新关联的AI Provider
#
# 4. 参数验证：
#    - 提供参数有效性检查
#    - 避免无效参数导致的运行时错误
#    - 返回详细的错误信息
#
# 5. 向后兼容：
#    - 提供 get_ai_param() 兼容旧接口
#    - 支持类似 config.get 的调用方式
#    - 平滑过渡，不影响现有代码
#
# -----------------------------------------------------------------------------
#
# 【使用示例】
#
# 1. 获取特定场景配置：
#    from core.ai.ai_config import get_react_config, AIScene, ai_config
#    config = get_react_config()  # 获取ReAct场景配置
#    config = ai_config.get_config(AIScene.CODE)  # 获取代码场景配置
#
# 2. 通过场景名称获取：
#    from core.ai.ai_config import get_config_for_scene
#    config = get_config_for_scene("chat")  # 字符串方式获取
#
# 3. 覆盖模型名称：
#    config = get_react_config(model_name="gpt-4")  # 使用特定模型
#
# 4. 配置热重载：
#    - 修改配置文件中的 ai.default_model
#    - 系统自动检测变更并刷新配置
#    - 无需手动干预
#
# -----------------------------------------------------------------------------
#
# 【场景参数设计原则】
#
# 温度参数 (temperature)：
#   - 0.1-0.2：严格格式遵循（ReAct、代码生成）
#   - 0.3-0.5：平衡对话
#   - 0.7+：创意生成
#
# 最大token (max_tokens)：
#   - CODE：4096（代码可能很长）
#   - REACT：2048（JSON需要完整输出）
#   - SUMMARY：256（摘要要简洁）
#
# 停止序列 (stop_sequences)：
#   - ReAct：只保留段落分隔，不拦截JSON
#   - 其他场景：根据需要设置
#
# =============================================================================
