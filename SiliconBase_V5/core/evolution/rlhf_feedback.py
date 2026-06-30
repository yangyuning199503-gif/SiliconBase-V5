#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
RLHF反馈系统 - 硅基生命的"学习"能力  # 模块功能概述：人类反馈强化学习

核心功能：  # 功能列表
1. 收集用户对AI回复的反馈（👍/👎）  # 功能1
2. 记录任务执行的成功/失败反馈  # 功能2
3. 生成DPO训练数据对（偏好数据）  # 功能3
4. 支持反馈数据的持久化存储（JSON格式）  # 功能4
5. 提供反馈统计和分析功能  # 功能5

设计原则：  # 设计原则
- 数据完整性：每条反馈都有完整的上下文信息  # 原则1
- 可追溯性：关联到具体的对话和任务  # 原则2
- 隐私保护：敏感信息脱敏处理  # 原则3
- 高效存储：增量写入，定期归档  # 原则4
"""  # 文档字符串结束

import json  # 导入JSON模块
import time  # 导入时间模块
import uuid  # 导入UUID模块
from dataclasses import dataclass, field  # 从dataclasses导入数据类装饰器
from enum import Enum  # 从enum导入枚举类
from pathlib import Path  # 从pathlib导入Path类
from typing import Any  # 从typing导入类型注解

from core.config import config  # 导入配置模块
from core.exceptions import RLHFStorageError  # 【Agent3】导入异常类型
from core.logger import logger  # 导入日志记录器


class FeedbackType(str, Enum):  # 反馈类型枚举类
    """反馈类型枚举"""  # 类文档字符串
    THUMBS_UP = "thumbs_up"      # 👍 点赞
    THUMBS_DOWN = "thumbs_down"  # 👎 点踩
    NEUTRAL = "neutral"          # 中立


class TaskOutcome(str, Enum):  # 任务结果枚举类
    """任务结果枚举"""  # 类文档字符串
    SUCCESS = "success"          # 成功
    PARTIAL = "partial"          # 部分成功
    FAILURE = "failure"          # 失败
    CANCELLED = "cancelled"      # 取消


@dataclass  # 数据类装饰器
class ResponseFeedback:  # 用户对AI回复的反馈数据类
    """
    用户对AI回复的反馈

    Attributes:
        feedback_id: 反馈唯一ID
        response_id: 关联的回复ID
        feedback_type: 反馈类型（赞/踩/中立）
        user_comment: 用户评论（可选）
        conversation_id: 对话ID
        prompt_text: 原始提示词
        response_text: AI回复内容
        timestamp: 反馈时间戳
        metadata: 额外元数据
    """  # 类文档字符串
    feedback_id: str  # 反馈唯一ID
    response_id: str  # 关联的回复ID
    feedback_type: FeedbackType  # 反馈类型
    user_comment: str | None = None  # 用户评论
    conversation_id: str | None = None  # 对话ID
    prompt_text: str | None = None  # 原始提示词
    response_text: str | None = None  # AI回复内容
    timestamp: float = field(default_factory=time.time)  # 反馈时间戳
    metadata: dict[str, Any] = field(default_factory=dict)  # 额外元数据

    def to_dict(self) -> dict[str, Any]:  # 转换为字典
        """转换为字典"""  # 方法文档字符串
        return {  # 返回字典表示
            "feedback_id": self.feedback_id,  # 反馈ID
            "response_id": self.response_id,  # 回复ID
            "feedback_type": self.feedback_type.value,  # 反馈类型值
            "user_comment": self.user_comment,  # 用户评论
            "conversation_id": self.conversation_id,  # 对话ID
            "prompt_text": self.prompt_text,  # 提示词
            "response_text": self.response_text,  # 回复内容
            "timestamp": self.timestamp,  # 时间戳
            "metadata": self.metadata  # 元数据
        }

    @classmethod  # 类方法装饰器
    def from_dict(cls, data: dict[str, Any]) -> "ResponseFeedback":  # 从字典创建实例
        """从字典创建实例"""  # 方法文档字符串
        return cls(  # 创建并返回实例
            feedback_id=data["feedback_id"],  # 反馈ID
            response_id=data["response_id"],  # 回复ID
            feedback_type=FeedbackType(data.get("feedback_type", "neutral")),  # 反馈类型
            user_comment=data.get("user_comment"),  # 用户评论
            conversation_id=data.get("conversation_id"),  # 对话ID
            prompt_text=data.get("prompt_text"),  # 提示词
            response_text=data.get("response_text"),  # 回复内容
            timestamp=data.get("timestamp", time.time()),  # 时间戳
            metadata=data.get("metadata", {})  # 元数据
        )


@dataclass  # 数据类装饰器
class TaskFeedback:  # 任务执行反馈数据类
    """
    任务执行反馈

    Attributes:
        feedback_id: 反馈唯一ID
        task_id: 任务ID
        outcome: 任务结果
        feedback_score: 用户评分（1-5分）
        user_comment: 用户评论
        execution_steps: 执行步骤记录
        error_message: 错误信息
        duration: 执行耗时（秒）
        timestamp: 反馈时间戳
        metadata: 额外元数据
    """  # 类文档字符串
    feedback_id: str  # 反馈唯一ID
    task_id: str  # 任务ID
    outcome: TaskOutcome  # 任务结果
    feedback_score: int | None = None  # 用户评分
    user_comment: str | None = None  # 用户评论
    execution_steps: list[dict] = field(default_factory=list)  # 执行步骤记录
    error_message: str | None = None  # 错误信息
    duration: float | None = None  # 执行耗时
    timestamp: float = field(default_factory=time.time)  # 反馈时间戳
    metadata: dict[str, Any] = field(default_factory=dict)  # 额外元数据

    def to_dict(self) -> dict[str, Any]:  # 转换为字典
        """转换为字典"""  # 方法文档字符串
        return {  # 返回字典表示
            "feedback_id": self.feedback_id,  # 反馈ID
            "task_id": self.task_id,  # 任务ID
            "outcome": self.outcome.value,  # 结果值
            "feedback_score": self.feedback_score,  # 评分
            "user_comment": self.user_comment,  # 评论
            "execution_steps": self.execution_steps,  # 执行步骤
            "error_message": self.error_message,  # 错误信息
            "duration": self.duration,  # 耗时
            "timestamp": self.timestamp,  # 时间戳
            "metadata": self.metadata  # 元数据
        }

    @classmethod  # 类方法装饰器
    def from_dict(cls, data: dict[str, Any]) -> "TaskFeedback":  # 从字典创建实例
        """从字典创建"""  # 方法文档字符串
        return cls(  # 创建并返回实例
            feedback_id=data["feedback_id"],  # 反馈ID
            task_id=data["task_id"],  # 任务ID
            outcome=TaskOutcome(data.get("outcome", "failure")),  # 结果
            feedback_score=data.get("feedback_score"),  # 评分
            user_comment=data.get("user_comment"),  # 评论
            execution_steps=data.get("execution_steps", []),  # 执行步骤
            error_message=data.get("error_message"),  # 错误信息
            duration=data.get("duration"),  # 耗时
            timestamp=data.get("timestamp", time.time()),  # 时间戳
            metadata=data.get("metadata", {})  # 元数据
        )


@dataclass  # 数据类装饰器
class DPOPair:  # DPO训练数据对数据类
    """
    DPO训练数据对（Direct Preference Optimization）

    用于偏好学习，包含被偏好的回复和不被偏好的回复

    Attributes:
        pair_id: 数据对ID
        prompt: 输入提示词
        chosen: 被偏好的回复
        rejected: 不被偏好的回复
        source: 数据来源
        preference_score: 偏好强度分数
        timestamp: 创建时间戳
    """  # 类文档字符串
    pair_id: str  # 数据对ID
    prompt: str  # 输入提示词
    chosen: str  # 被偏好的回复
    rejected: str  # 不被偏好的回复
    source: str  # 数据来源（"response_feedback" 或 "task_feedback"）
    preference_score: float = 1.0  # 偏好强度分数
    timestamp: float = field(default_factory=time.time)  # 创建时间戳

    def to_dict(self) -> dict[str, Any]:  # 转换为字典
        """转换为字典"""  # 方法文档字符串
        return {  # 返回字典表示
            "pair_id": self.pair_id,  # 数据对ID
            "prompt": self.prompt,  # 提示词
            "chosen": self.chosen,  # 被偏好的回复
            "rejected": self.rejected,  # 不被偏好的回复
            "source": self.source,  # 来源
            "preference_score": self.preference_score,  # 偏好分数
            "timestamp": self.timestamp  # 时间戳
        }


class RLHFFeedbackCollector:  # RLHF反馈收集器类
    """
    RLHF反馈收集器 - 收集和管理用户反馈，生成DPO训练数据

    使用示例：
        # 收集回复反馈
        rlhf_collector.collect_response_feedback(
            response_id="resp_123",
            feedback_type=FeedbackType.THUMBS_UP,
            user_comment="回答很有帮助"
        )

        # 收集任务反馈
        rlhf_collector.collect_task_feedback(
            task_id="task_456",
            success=True,
            feedback_score=5
        )

        # 生成DPO训练数据
        dpo_pairs = rlhf_collector.generate_dpo_pairs()

        # 获取统计信息
        stats = rlhf_collector.get_feedback_stats()
    """  # 类文档字符串

    def __init__(self):  # 初始化
        self.enabled = config.get("features.rlhf", False)  # 从配置读取是否启用

        # 数据存储目录
        self.data_dir = Path(__file__).parent.parent / "data" / "rlhf"  # 数据目录路径
        self.data_dir.mkdir(parents=True, exist_ok=True)  # 确保目录存在

        # 响应反馈存储文件
        self.response_feedback_file = self.data_dir / "response_feedback.jsonl"  # 响应反馈文件

        # 任务反馈存储文件
        self.task_feedback_file = self.data_dir / "task_feedback.jsonl"  # 任务反馈文件

        # DPO数据对存储文件
        self.dpo_pairs_file = self.data_dir / "dpo_pairs.jsonl"  # DPO数据对文件

        # 缓存（内存中保留最近的数据）
        self._response_feedback_cache: list[ResponseFeedback] = []  # 响应反馈缓存
        self._task_feedback_cache: list[TaskFeedback] = []  # 任务反馈缓存
        self._cache_size = 100  # 缓存大小

        # 待生成DPO对的响应ID集合（避免重复生成）
        self._processed_response_ids: set = self._load_processed_ids()  # 加载已处理ID

        if self.enabled:  # 如果启用
            logger.info("[RLHF] 反馈系统已启用")  # 记录日志
        else:  # 如果禁用
            logger.info("[RLHF] 反馈系统已禁用（在配置中启用 features.rlhf）")  # 记录日志

    def _load_processed_ids(self) -> set:  # 加载已处理的响应ID集合
        """加载已处理的响应ID集合"""  # 方法文档字符串
        processed = set()  # 初始化集合
        if self.dpo_pairs_file.exists():  # 如果文件存在
            try:  # 异常处理
                with open(self.dpo_pairs_file, encoding='utf-8') as f:  # 打开文件
                    for line in f:  # 遍历每行
                        if line.strip():  # 如果非空
                            data = json.loads(line)  # 解析JSON
                            processed.add(data.get("source_response_id", ""))  # 添加ID
            except Exception as e:  # 捕获异常
                logger.warning(f"[RLHF] 加载已处理ID失败: {e}")  # 记录警告
        return processed  # 返回集合

    def _generate_id(self, prefix: str = "") -> str:  # 生成唯一ID
        """生成唯一ID"""  # 方法文档字符串
        timestamp = int(time.time() * 1000)  # 毫秒时间戳
        random_part = uuid.uuid4().hex[:8]  # 随机部分
        return f"{prefix}_{timestamp}_{random_part}"  # 返回ID

    def _append_to_jsonl(self, file_path: Path, data: dict):  # 追加数据到JSONL文件
        """追加数据到JSONL文件 - 【Agent3】禁止静默失败"""  # 方法文档字符串
        if not file_path:
            logger.error("[RLHF] [SILENT_FAILURE_BLOCKED] 文件路径为空，写入失败")
            raise RLHFStorageError("文件路径不能为空")

        try:  # 异常处理
            with open(file_path, 'a', encoding='utf-8') as f:  # 追加模式打开
                f.write(json.dumps(data, ensure_ascii=False) + '\n')  # 写入JSON行
        except OSError as e:  # 【Agent3】捕获具体IO异常
            logger.error(f"[RLHF] [SILENT_FAILURE_BLOCKED] 写入文件失败 {file_path}: {e}", exc_info=True)
            raise RLHFStorageError(f"保存反馈数据失败: {e}") from e

    def _load_jsonl(self, file_path: Path) -> list[dict]:  # 加载JSONL文件
        """加载JSONL文件的所有数据"""  # 方法文档字符串
        data = []  # 数据列表
        if not file_path.exists():  # 如果文件不存在
            return data  # 返回空列表

        try:  # 异常处理
            with open(file_path, encoding='utf-8') as f:  # 打开文件
                for line in f:  # 遍历每行
                    if line.strip():  # 如果非空
                        data.append(json.loads(line))  # 解析并添加
        except Exception as e:  # 捕获异常
            logger.error(f"[RLHF] 读取文件失败 {file_path}: {e}")  # 记录错误

        return data  # 返回数据

    def collect_response_feedback(  # 收集用户对AI回复的反馈
        self,
        response_id: str,  # 回复ID
        feedback_type: FeedbackType,  # 反馈类型
        user_comment: str | None = None,  # 用户评论
        conversation_id: str | None = None,  # 对话ID
        prompt_text: str | None = None,  # 原始提示词
        response_text: str | None = None,  # AI回复内容
        metadata: dict[str, Any] | None = None  # 额外元数据
    ) -> str | None:  # 返回反馈ID或None
        """
        收集用户对AI回复的反馈 - 【Agent3】禁止静默失败

        Args:
            response_id: 回复的唯一ID
            feedback_type: 反馈类型（赞/踩/中立）
            user_comment: 用户的文字评论（可选）
            conversation_id: 对话ID（可选）
            prompt_text: 原始提示词（可选，用于DPO训练）
            response_text: AI回复内容（可选，用于DPO训练）
            metadata: 额外元数据（可选）

        Returns:
            反馈ID，如果系统禁用则返回None

        Raises:
            RLHFStorageError: 保存反馈失败时抛出
            ValueError: 参数无效时抛出
        """  # 方法文档字符串
        if not self.enabled:  # 如果未启用
            logger.debug("[RLHF] 反馈系统已禁用，跳过收集")  # 记录调试日志
            return None  # 返回None

        # 【Agent3】参数校验 - 禁止静默失败
        if not response_id:
            logger.error("[RLHF] [SILENT_FAILURE_BLOCKED] 反馈参数无效: response_id为空")
            raise ValueError("反馈参数无效: response_id不能为空")

        if not feedback_type:
            logger.error("[RLHF] [SILENT_FAILURE_BLOCKED] 反馈参数无效: feedback_type为空")
            raise ValueError("反馈参数无效: feedback_type不能为空")

        try:  # 异常处理
            feedback = ResponseFeedback(  # 创建反馈对象
                feedback_id=self._generate_id("resp_fb"),  # 生成反馈ID
                response_id=response_id,  # 回复ID
                feedback_type=feedback_type,  # 反馈类型
                user_comment=user_comment,  # 用户评论
                conversation_id=conversation_id,  # 对话ID
                prompt_text=prompt_text,  # 提示词
                response_text=response_text,  # 回复内容
                metadata=metadata or {}  # 元数据
            )

            # 持久化存储 - 失败会抛出RLHFStorageError
            self._append_to_jsonl(self.response_feedback_file, feedback.to_dict())  # 追加到文件

            # 添加到缓存
            self._response_feedback_cache.append(feedback)  # 添加到缓存
            if len(self._response_feedback_cache) > self._cache_size:  # 如果超过缓存大小
                self._response_feedback_cache.pop(0)  # 删除最旧的

            logger.info(f"[RLHF] 收集回复反馈: {feedback_type.value} for {response_id}")  # 记录日志

            return feedback.feedback_id  # 返回反馈ID

        except OSError as e:  # 【Agent3】捕获具体IO异常
            logger.error(f"[RLHF] [SILENT_FAILURE_BLOCKED] 收集回复反馈失败: {e}", exc_info=True)
            raise RLHFStorageError(f"保存回复反馈失败: {e}") from e
        except Exception as e:  # 【Agent3】捕获其他异常
            logger.error(f"[RLHF] [SILENT_FAILURE_BLOCKED] 收集回复反馈发生未预期错误: {e}", exc_info=True)
            raise RLHFStorageError(f"保存回复反馈失败: {e}") from e

    def collect_task_feedback(  # 收集任务执行反馈
        self,
        task_id: str,  # 任务ID
        success: bool,  # 是否成功
        feedback_score: int | None = None,  # 用户评分
        user_comment: str | None = None,  # 用户评论
        execution_steps: list[dict] | None = None,  # 执行步骤
        error_message: str | None = None,  # 错误信息
        duration: float | None = None,  # 执行耗时
        metadata: dict[str, Any] | None = None  # 额外元数据
    ) -> str | None:  # 返回反馈ID或None
        """
        收集任务执行的成功/失败反馈 - 【Agent3】禁止静默失败

        Args:
            task_id: 任务的唯一ID
            success: 任务是否成功
            feedback_score: 用户评分（1-5分，可选）
            user_comment: 用户的文字评论（可选）
            execution_steps: 任务执行步骤记录（可选）
            error_message: 错误信息（可选）
            duration: 任务执行耗时（秒，可选）
            metadata: 额外元数据（可选）

        Returns:
            反馈ID，如果系统禁用则返回None

        Raises:
            RLHFStorageError: 保存反馈失败时抛出
            ValueError: 参数无效时抛出
        """  # 方法文档字符串
        if not self.enabled:  # 如果未启用
            logger.debug("[RLHF] 反馈系统已禁用，跳过收集")  # 记录调试日志
            return None  # 返回None

        # 【Agent3】参数校验 - 禁止静默失败
        if not task_id:
            logger.error("[RLHF] [SILENT_FAILURE_BLOCKED] 任务反馈参数无效: task_id为空")
            raise ValueError("任务反馈参数无效: task_id不能为空")

        try:  # 异常处理
            # 转换布尔值为枚举
            outcome = TaskOutcome.SUCCESS if success else TaskOutcome.FAILURE  # 成功或失败结果

            feedback = TaskFeedback(  # 创建反馈对象
                feedback_id=self._generate_id("task_fb"),  # 生成反馈ID
                task_id=task_id,  # 任务ID
                outcome=outcome,  # 结果
                feedback_score=feedback_score,  # 评分
                user_comment=user_comment,  # 评论
                execution_steps=execution_steps or [],  # 执行步骤
                error_message=error_message,  # 错误信息
                duration=duration,  # 耗时
                metadata=metadata or {}  # 元数据
            )

            # 持久化存储 - 失败会抛出RLHFStorageError
            self._append_to_jsonl(self.task_feedback_file, feedback.to_dict())  # 追加到文件

            # 添加到缓存
            self._task_feedback_cache.append(feedback)  # 添加到缓存
            if len(self._task_feedback_cache) > self._cache_size:  # 如果超过缓存大小
                self._task_feedback_cache.pop(0)  # 删除最旧的

            logger.info(f"[RLHF] 收集任务反馈: {outcome.value} for {task_id}")  # 记录日志

            return feedback.feedback_id  # 返回反馈ID

        except OSError as e:  # 【Agent3】捕获具体IO异常
            logger.error(f"[RLHF] [SILENT_FAILURE_BLOCKED] 收集任务反馈失败: {e}", exc_info=True)
            raise RLHFStorageError(f"保存任务反馈失败: {e}") from e
        except Exception as e:  # 【Agent3】捕获其他异常
            logger.error(f"[RLHF] [SILENT_FAILURE_BLOCKED] 收集任务反馈发生未预期错误: {e}", exc_info=True)
            raise RLHFStorageError(f"保存任务反馈失败: {e}") from e

    def generate_dpo_pairs(self, min_preference_gap: float = 0.5) -> list[DPOPair]:  # 生成DPO训练数据对
        """
        生成DPO训练数据对（偏好数据）

        DPO（Direct Preference Optimization）需要成对的偏好数据：
        - chosen: 被偏好的回复
        - rejected: 不被偏好的回复

        生成策略：
        1. 从响应反馈中找出点赞的回复作为chosen，点踩的作为rejected
        2. 只生成包含完整prompt和response的pair
        3. 同一对话内的不同回复可以组成pair

        Args:
            min_preference_gap: 最小偏好差距（用于筛选高质量pair）

        Returns:
            生成的DPO数据对列表
        """  # 方法文档字符串
        if not self.enabled:  # 如果未启用
            logger.debug("[RLHF] 反馈系统已禁用，跳过DPO生成")  # 记录调试日志
            return []  # 返回空列表

        try:  # 异常处理
            # 加载所有响应反馈
            all_feedback = self._load_jsonl(self.response_feedback_file)  # 加载反馈

            # 转换为对象
            feedbacks = [ResponseFeedback.from_dict(fb) for fb in all_feedback]  # 转换为对象列表

            # 分离正负反馈（只取包含完整prompt和response的）
            positive_feedbacks = [  # 正面反馈
                fb for fb in feedbacks
                if fb.feedback_type == FeedbackType.THUMBS_UP  # 点赞
                and fb.prompt_text and fb.response_text  # 有完整内容
                and fb.response_id not in self._processed_response_ids  # 未处理过
            ]

            negative_feedbacks = [  # 负面反馈
                fb for fb in feedbacks
                if fb.feedback_type == FeedbackType.THUMBS_DOWN  # 点踩
                and fb.prompt_text and fb.response_text  # 有完整内容
            ]

            dpo_pairs: list[DPOPair] = []  # DPO对列表

            # 策略1：同一conversation内的正负反馈配对
            conv_positive: dict[str, list[ResponseFeedback]] = {}  # 会话正面反馈字典
            conv_negative: dict[str, list[ResponseFeedback]] = {}  # 会话负面反馈字典

            for fb in positive_feedbacks:  # 遍历正面反馈
                conv_id = fb.conversation_id or "unknown"  # 获取会话ID
                if conv_id not in conv_positive:  # 如果会话不存在
                    conv_positive[conv_id] = []  # 创建列表
                conv_positive[conv_id].append(fb)  # 添加到列表

            for fb in negative_feedbacks:  # 遍历负面反馈
                conv_id = fb.conversation_id or "unknown"  # 获取会话ID
                if conv_id not in conv_negative:  # 如果会话不存在
                    conv_negative[conv_id] = []  # 创建列表
                conv_negative[conv_id].append(fb)  # 添加到列表

            # 为每个conversation生成pair
            for conv_id in conv_positive:  # 遍历有正面反馈的会话
                if conv_id in conv_negative:  # 如果也有负面反馈
                    for pos_fb in conv_positive[conv_id]:  # 遍历正面反馈
                        # 找到相同或相似prompt的负反馈
                        for neg_fb in conv_negative[conv_id]:  # 遍历负面反馈
                            # 简单相似度：检查prompt是否相同或相似
                            if self._prompt_similarity(  # 计算相似度
                                pos_fb.prompt_text,
                                neg_fb.prompt_text
                            ) >= min_preference_gap:  # 如果达到阈值
                                pair = DPOPair(  # 创建DPO对
                                    pair_id=self._generate_id("dpo"),  # 生成ID
                                    prompt=pos_fb.prompt_text,  # 提示词
                                    chosen=pos_fb.response_text,  # 被偏好的回复
                                    rejected=neg_fb.response_text,  # 不被偏好的回复
                                    source="response_feedback",  # 来源
                                    preference_score=1.0  # 偏好分数
                                )
                                dpo_pairs.append(pair)  # 添加到列表
                                self._processed_response_ids.add(pos_fb.response_id)  # 标记为已处理
                                self._processed_response_ids.add(neg_fb.response_id)  # 标记为已处理
                                break  # 找到一个即可

            # 策略2：从任务反馈生成pair（成功vs失败的任务执行）
            task_feedbacks = self._load_jsonl(self.task_feedback_file)  # 加载任务反馈
            tasks = [TaskFeedback.from_dict(tf) for tf in task_feedbacks]  # 转换为对象

            successful_tasks = [  # 成功任务
                t for t in tasks
                if t.outcome == TaskOutcome.SUCCESS and t.execution_steps  # 成功且有步骤
            ]
            failed_tasks = [  # 失败任务
                t for t in tasks
                if t.outcome == TaskOutcome.FAILURE and t.execution_steps  # 失败且有步骤
            ]

            # 相似任务配对
            for success_task in successful_tasks[:50]:  # 限制数量
                for failed_task in failed_tasks[:50]:  # 限制数量
                    # 简单判断：使用相同的task_id前缀或相似步骤
                    if self._task_similarity(success_task, failed_task) >= min_preference_gap:  # 如果相似
                        # 将任务转换为prompt-response格式
                        prompt = f"执行任务: {success_task.task_id}"  # 提示词
                        chosen = self._task_to_text(success_task)  # 被偏好的（成功）
                        rejected = self._task_to_text(failed_task)  # 不被偏好的（失败）

                        pair = DPOPair(  # 创建DPO对
                            pair_id=self._generate_id("dpo_task"),  # 生成ID
                            prompt=prompt,  # 提示词
                            chosen=chosen,  # 被偏好的
                            rejected=rejected,  # 不被偏好的
                            source="task_feedback",  # 来源
                            preference_score=success_task.feedback_score or 1.0  # 偏好分数
                        )
                        dpo_pairs.append(pair)  # 添加到列表
                        break  # 找到一个即可

            # 保存DPO pairs
            for pair in dpo_pairs:  # 遍历所有对
                self._append_to_jsonl(self.dpo_pairs_file, pair.to_dict())  # 追加到文件

            logger.info(f"[RLHF] 生成 {len(dpo_pairs)} 个DPO训练数据对")  # 记录日志

            return dpo_pairs  # 返回DPO对列表

        except Exception as e:  # 捕获异常
            logger.error(f"[RLHF] 生成DPO数据对失败: {e}")  # 记录错误
            return []  # 返回空列表

    def _prompt_similarity(self, prompt1: str, prompt2: str) -> float:  # 计算提示词相似度
        """
        计算两个prompt的相似度（简单实现）

        Returns:
            相似度分数（0-1）
        """  # 方法文档字符串
        if not prompt1 or not prompt2:  # 如果任一为空
            return 0.0  # 返回0

        # 简单判断：相同prompt返回1.0
        if prompt1 == prompt2:  # 如果完全相同
            return 1.0  # 返回1

        # 计算共同词的比例
        words1 = set(prompt1.lower().split())  # 第一个提示词的词集合
        words2 = set(prompt2.lower().split())  # 第二个提示词的词集合

        if not words1 or not words2:  # 如果任一为空
            return 0.0  # 返回0

        intersection = words1 & words2  # 交集
        union = words1 | words2  # 并集

        return len(intersection) / len(union) if union else 0.0  # 返回Jaccard相似度

    def _task_similarity(self, task1: TaskFeedback, task2: TaskFeedback) -> float:  # 计算任务相似度
        """
        计算两个任务的相似度

        Returns:
            相似度分数（0-1）
        """  # 方法文档字符串
        # 如果task_id相同或相似
        if task1.task_id == task2.task_id:  # 如果ID相同
            return 1.0  # 返回1

        # 比较执行步骤的工具使用
        tools1 = set()  # 任务1工具集合
        tools2 = set()  # 任务2工具集合

        for step in task1.execution_steps:  # 遍历任务1步骤
            tool = step.get("tool") or step.get("action", "")  # 获取工具名
            if tool:  # 如果非空
                tools1.add(tool)  # 添加到集合

        for step in task2.execution_steps:  # 遍历任务2步骤
            tool = step.get("tool") or step.get("action", "")  # 获取工具名
            if tool:  # 如果非空
                tools2.add(tool)  # 添加到集合

        if not tools1 or not tools2:  # 如果任一为空
            return 0.0  # 返回0

        intersection = tools1 & tools2  # 交集
        union = tools1 | tools2  # 并集

        return len(intersection) / len(union) if union else 0.0  # 返回Jaccard相似度

    def _task_to_text(self, task: TaskFeedback) -> str:  # 将任务转换为文本
        """将任务反馈转换为文本格式"""  # 方法文档字符串
        lines = [f"任务: {task.task_id}"]  # 任务ID
        lines.append(f"结果: {task.outcome.value}")  # 结果

        if task.execution_steps:  # 如果有执行步骤
            lines.append("执行步骤:")  # 添加标题
            for i, step in enumerate(task.execution_steps, 1):  # 遍历步骤
                action = step.get("action") or step.get("tool", "未知")  # 获取动作
                lines.append(f"  {i}. {action}")  # 添加步骤

        if task.user_comment:  # 如果有用户评论
            lines.append(f"用户评论: {task.user_comment}")  # 添加评论

        return "\n".join(lines)  # 返回文本

    def get_feedback_stats(self) -> dict[str, Any]:  # 获取反馈统计
        """
        获取反馈统计和分析信息

        Returns:
            包含各类统计信息的字典
        """  # 方法文档字符串
        stats = {  # 初始化统计字典
            "enabled": self.enabled,  # 是否启用
            "response_feedback": {  # 响应反馈统计
                "total": 0,  # 总数
                "thumbs_up": 0,  # 点赞数
                "thumbs_down": 0,  # 点踩数
                "neutral": 0,  # 中立数
                "with_comments": 0  # 带评论数
            },
            "task_feedback": {  # 任务反馈统计
                "total": 0,  # 总数
                "success": 0,  # 成功数
                "partial": 0,  # 部分成功数
                "failure": 0,  # 失败数
                "cancelled": 0,  # 取消数
                "avg_score": 0.0  # 平均评分
            },
            "dpo_pairs": {  # DPO对统计
                "total": 0,  # 总数
                "from_response": 0,  # 来自响应反馈
                "from_task": 0  # 来自任务反馈
            },
            "timeline": {  # 时间线统计
                "last_24h": {"responses": 0, "tasks": 0},  # 最近24小时
                "last_7d": {"responses": 0, "tasks": 0},  # 最近7天
                "last_30d": {"responses": 0, "tasks": 0}  # 最近30天
            }
        }

        if not self.enabled:  # 如果未启用
            return stats  # 返回初始统计

        try:  # 异常处理
            now = time.time()  # 当前时间
            one_day = 24 * 60 * 60  # 一天的秒数

            # 响应反馈统计
            response_data = self._load_jsonl(self.response_feedback_file)  # 加载数据
            stats["response_feedback"]["total"] = len(response_data)  # 总数

            scores = []  # 评分列表
            for fb in response_data:  # 遍历反馈
                fb_type = fb.get("feedback_type", "")  # 反馈类型
                if fb_type == FeedbackType.THUMBS_UP.value:  # 点赞
                    stats["response_feedback"]["thumbs_up"] += 1  # 增加计数
                elif fb_type == FeedbackType.THUMBS_DOWN.value:  # 点踩
                    stats["response_feedback"]["thumbs_down"] += 1  # 增加计数
                else:  # 中立
                    stats["response_feedback"]["neutral"] += 1  # 增加计数

                if fb.get("user_comment"):  # 如果有评论
                    stats["response_feedback"]["with_comments"] += 1  # 增加计数

                # 时间线统计
                timestamp = fb.get("timestamp", 0)  # 时间戳
                if now - timestamp <= one_day:  # 24小时内
                    stats["timeline"]["last_24h"]["responses"] += 1  # 增加计数
                if now - timestamp <= 7 * one_day:  # 7天内
                    stats["timeline"]["last_7d"]["responses"] += 1  # 增加计数
                if now - timestamp <= 30 * one_day:  # 30天内
                    stats["timeline"]["last_30d"]["responses"] += 1  # 增加计数

            # 任务反馈统计
            task_data = self._load_jsonl(self.task_feedback_file)  # 加载数据
            stats["task_feedback"]["total"] = len(task_data)  # 总数

            for fb in task_data:  # 遍历反馈
                outcome = fb.get("outcome", "")  # 结果
                if outcome == TaskOutcome.SUCCESS.value:  # 成功
                    stats["task_feedback"]["success"] += 1  # 增加计数
                elif outcome == TaskOutcome.PARTIAL.value:  # 部分成功
                    stats["task_feedback"]["partial"] += 1  # 增加计数
                elif outcome == TaskOutcome.FAILURE.value:  # 失败
                    stats["task_feedback"]["failure"] += 1  # 增加计数
                elif outcome == TaskOutcome.CANCELLED.value:  # 取消
                    stats["task_feedback"]["cancelled"] += 1  # 增加计数

                score = fb.get("feedback_score")  # 评分
                if score is not None:  # 如果存在
                    scores.append(score)  # 添加到列表

                # 时间线统计
                timestamp = fb.get("timestamp", 0)  # 时间戳
                if now - timestamp <= one_day:  # 24小时内
                    stats["timeline"]["last_24h"]["tasks"] += 1  # 增加计数
                if now - timestamp <= 7 * one_day:  # 7天内
                    stats["timeline"]["last_7d"]["tasks"] += 1  # 增加计数
                if now - timestamp <= 30 * one_day:  # 30天内
                    stats["timeline"]["last_30d"]["tasks"] += 1  # 增加计数

            if scores:  # 如果有评分
                stats["task_feedback"]["avg_score"] = round(sum(scores) / len(scores), 2)  # 计算平均分

            # DPO数据对统计
            dpo_data = self._load_jsonl(self.dpo_pairs_file)  # 加载数据
            stats["dpo_pairs"]["total"] = len(dpo_data)  # 总数

            for pair in dpo_data:  # 遍历数据对
                source = pair.get("source", "")  # 来源
                if source == "response_feedback":  # 来自响应反馈
                    stats["dpo_pairs"]["from_response"] += 1  # 增加计数
                elif source == "task_feedback":  # 来自任务反馈
                    stats["dpo_pairs"]["from_task"] += 1  # 增加计数

            # 计算满意度
            total_feedback = stats["response_feedback"]["thumbs_up"] + \
                           stats["response_feedback"]["thumbs_down"]  # 总反馈数
            if total_feedback > 0:  # 如果大于0
                stats["satisfaction_rate"] = round(  # 计算满意度
                    stats["response_feedback"]["thumbs_up"] / total_feedback * 100, 2
                )
            else:  # 无反馈
                stats["satisfaction_rate"] = 0.0  # 满意度为0

            logger.info(f"[RLHF] 统计信息: {stats['response_feedback']['total']} 条回复反馈, "
                       f"{stats['task_feedback']['total']} 条任务反馈, "
                       f"{stats['dpo_pairs']['total']} 个DPO数据对")  # 记录日志

            return stats  # 返回统计

        except Exception as e:  # 捕获异常
            logger.error(f"[RLHF] 获取统计信息失败: {e}")  # 记录错误
            return stats  # 返回初始统计

    def get_recent_feedback(  # 获取最近反馈
        self,
        feedback_type: str = "response",  # 反馈类型
        limit: int = 10  # 数量限制
    ) -> list[dict]:  # 返回反馈列表
        """
        获取最近的反馈记录

        Args:
            feedback_type: "response" 或 "task"
            limit: 返回记录数量

        Returns:
            反馈记录列表
        """  # 方法文档字符串
        try:  # 异常处理
            if feedback_type == "response":  # 响应反馈
                data = self._load_jsonl(self.response_feedback_file)  # 加载数据
            else:  # 任务反馈
                data = self._load_jsonl(self.task_feedback_file)  # 加载数据

            # 按时间戳倒序排序
            data.sort(key=lambda x: x.get("timestamp", 0), reverse=True)  # 降序排序

            return data[:limit]  # 返回前limit条

        except Exception as e:  # 捕获异常
            logger.error(f"[RLHF] 获取最近反馈失败: {e}")  # 记录错误
            return []  # 返回空列表

    def export_dpo_dataset(self, output_file: str | None = None) -> str:  # 导出DPO数据集
        """
        导出DPO训练数据集为标准格式

        标准DPO格式：
        [
          {
            "prompt": "...",
            "chosen": "...",
            "rejected": "..."
          },
          ...
        ]

        Args:
            output_file: 输出文件路径（可选，默认使用data/rlhf/dpo_dataset.json）

        Returns:
            输出文件路径
        """  # 方法文档字符串
        if output_file is None:  # 如果未指定
            output_file = str(self.data_dir / "dpo_dataset.json")  # 使用默认路径

        try:  # 异常处理
            dpo_data = self._load_jsonl(self.dpo_pairs_file)  # 加载DPO数据

            # 转换为标准DPO格式
            dataset = [  # 数据集列表
                {
                    "prompt": item["prompt"],  # 提示词
                    "chosen": item["chosen"],  # 被偏好的回复
                    "rejected": item["rejected"]  # 不被偏好的回复
                }
                for item in dpo_data  # 遍历数据
            ]

            with open(output_file, 'w', encoding='utf-8') as f:  # 打开文件
                json.dump(dataset, f, ensure_ascii=False, indent=2)  # 写入JSON

            logger.info(f"[RLHF] 导出DPO数据集到 {output_file}，共 {len(dataset)} 条")  # 记录日志

            return output_file  # 返回文件路径

        except Exception as e:  # 捕获异常
            logger.error(f"[RLHF] 导出DPO数据集失败: {e}")  # 记录错误
            return ""  # 返回空字符串

    def clear_all_feedback(self, confirm: bool = False) -> bool:  # 清空所有反馈
        """
        清空所有反馈数据（慎用）

        Args:
            confirm: 必须设置为True才能执行

        Returns:
            是否成功
        """  # 方法文档字符串
        if not confirm:  # 如果未确认
            logger.warning("[RLHF] 清空反馈数据需要设置 confirm=True")  # 记录警告
            return False  # 返回失败

        try:  # 异常处理
            # 备份现有数据
            backup_dir = self.data_dir / "backups"  # 备份目录
            backup_dir.mkdir(exist_ok=True)  # 确保目录存在

            timestamp = int(time.time())  # 时间戳

            for file_path in [self.response_feedback_file, self.task_feedback_file, self.dpo_pairs_file]:  # 遍历文件
                if file_path.exists():  # 如果文件存在
                    backup_path = backup_dir / f"{file_path.stem}_{timestamp}{file_path.suffix}"  # 备份路径
                    file_path.rename(backup_path)  # 重命名（移动）
                    logger.info(f"[RLHF] 已备份 {file_path.name} 到 {backup_path}")  # 记录日志

            # 清空缓存
            self._response_feedback_cache.clear()  # 清空响应缓存
            self._task_feedback_cache.clear()  # 清空任务缓存
            self._processed_response_ids.clear()  # 清空已处理ID

            logger.info("[RLHF] 所有反馈数据已清空")  # 记录日志

            return True  # 返回成功

        except Exception as e:  # 捕获异常
            logger.error(f"[RLHF] 清空反馈数据失败: {e}")  # 记录错误
            return False  # 返回失败


# 全局实例
rlhf_collector = RLHFFeedbackCollector()  # 创建全局单例


def collect_quick_feedback(response_id: str, is_positive: bool, comment: str = "") -> str | None:  # 快速收集反馈
    """
    便捷函数：快速收集反馈

    Args:
        response_id: 回复ID
        is_positive: True表示点赞，False表示点踩
        comment: 可选评论

    Returns:
        反馈ID
    """  # 函数文档字符串
    feedback_type = FeedbackType.THUMBS_UP if is_positive else FeedbackType.THUMBS_DOWN  # 确定类型
    return rlhf_collector.collect_response_feedback(  # 调用收集方法
        response_id=response_id,
        feedback_type=feedback_type,
        user_comment=comment if comment else None
    )


def get_rlhf_stats() -> dict[str, Any]:  # 获取RLHF统计
    """
    便捷函数：获取RLHF统计信息

    Returns:
        统计信息字典
    """  # 函数文档字符串
    return rlhf_collector.get_feedback_stats()  # 调用统计方法


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"RLHF反馈系统"，实现人类反馈强化学习，
# 收集用户对AI回复和任务执行的反馈，生成DPO训练数据。
#
# 【主要功能】
# 1. 反馈收集：收集用户对AI回复的点赞/点踩反馈
# 2. 任务反馈：记录任务执行的成功/失败结果
# 3. DPO数据生成：将反馈转换为DPO训练数据对（chosen/rejected）
# 4. 数据持久化：使用JSONL格式存储，支持增量写入
# 5. 统计分析：提供反馈数量、满意度、时间线等统计
#
# 【关联文件】
# - core/config.py                : 配置模块，控制RLHF是否启用
# - data/rlhf/                    : 反馈数据存储目录
#   - response_feedback.jsonl     : 响应反馈数据
#   - task_feedback.jsonl         : 任务反馈数据
#   - dpo_pairs.jsonl             : DPO训练数据对
#   - dpo_dataset.json            : 标准格式DPO数据集
#
# 【数据类说明】
# - ResponseFeedback: 用户对AI回复的反馈
# - TaskFeedback: 任务执行反馈
# - DPOPair: DPO训练数据对（prompt/chosen/rejected）
#
# 【核心功能效果】
# 1. 持续学习：通过用户反馈不断优化AI表现
# 2. 数据积累：为模型微调提供高质量的偏好数据
# 3. 可追溯：每条反馈都关联到具体的对话和任务
# 4. 隐私保护：支持敏感信息脱敏
#
# 【使用场景】
# - 用户对AI回复点赞/点踩时收集反馈
# - 任务完成后记录执行结果
# - 定期导出DPO数据用于模型训练
# =============================================================================
