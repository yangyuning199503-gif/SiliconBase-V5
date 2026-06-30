#!/usr/bin/env python3
"""
降级管理器 - Fallback Manager

实现多层级降级策略，确保服务高可用性。

降级链设计：
Level 1: GPT-4/Claude-3-Opus (最强云端)
Level 2: GPT-4o/Claude-3-Sonnet (平衡云端)
Level 3: GPT-4o-mini/DeepSeek (经济云端)
Level 4: 本地Ollama (离线可用)
Level 5: 缓存/预设响应 (最后防线)

特性：
1. 自动故障检测
2. 多级降级链
3. 快速恢复检测
4. 降级策略配置
5. 降级事件通知
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import Any

from core.logger import logger


class FallbackLevel(Enum):
    """降级级别"""
    PRIMARY = auto()      # 主模型（GPT-4/Claude-3-Opus）
    SECONDARY = auto()    # 次级模型（GPT-4o/Claude-3-Sonnet）
    TERTIARY = auto()     # 三级模型（GPT-4o-mini/DeepSeek）
    LOCAL = auto()        # 本地模型（Ollama）
    CACHE = auto()        # 缓存/预设响应


class FallbackReason(Enum):
    """降级原因"""
    TIMEOUT = "timeout"           # 超时
    RATE_LIMIT = "rate_limit"     # 速率限制
    ERROR = "error"               # 错误
    COST_LIMIT = "cost_limit"     # 成本限制
    NETWORK = "network"           # 网络问题
    UNAVAILABLE = "unavailable"   # 服务不可用


@dataclass
class FallbackEvent:
    """降级事件"""
    timestamp: datetime
    from_level: FallbackLevel
    to_level: FallbackLevel
    reason: FallbackReason
    error_message: str
    recovery_time_ms: int | None = None


@dataclass
class FallbackChain:
    """降级链配置"""
    task_type: str
    chain: list[tuple[FallbackLevel, str, str]]  # (level, provider, model)
    max_retries: int = 2
    retry_delay_ms: int = 1000

    def get_next_fallback(self,
                         current_level: FallbackLevel) -> tuple[str, str] | None:
        """获取下一级降级目标"""
        current_idx = None
        for i, (level, _, _) in enumerate(self.chain):
            if level == current_level:
                current_idx = i
                break

        if current_idx is not None and current_idx < len(self.chain) - 1:
            _, provider, model = self.chain[current_idx + 1]
            return provider, model

        return None


class FallbackManager:
    """
    降级管理器

    管理模型调用的降级策略和故障恢复。
    """

    # 默认降级链配置
    DEFAULT_CHAINS = {
        "complex_reasoning": FallbackChain(
            task_type="complex_reasoning",
            chain=[
                (FallbackLevel.PRIMARY, "openai", "o1-preview"),
                (FallbackLevel.PRIMARY, "anthropic", "claude-3-opus"),
                (FallbackLevel.SECONDARY, "openai", "gpt-4"),
                (FallbackLevel.TERTIARY, "deepseek", "deepseek-reasoner"),
                (FallbackLevel.LOCAL, "ollama", "qwen3:8b"),
            ],
            max_retries=2,
            retry_delay_ms=2000
        ),
        "coding": FallbackChain(
            task_type="coding",
            chain=[
                (FallbackLevel.PRIMARY, "openai", "gpt-4"),
                (FallbackLevel.SECONDARY, "anthropic", "claude-3-sonnet"),
                (FallbackLevel.SECONDARY, "openai", "gpt-4o"),
                (FallbackLevel.TERTIARY, "deepseek", "deepseek-chat"),
                (FallbackLevel.LOCAL, "ollama", "deepseek-coder:6.7b"),
                (FallbackLevel.LOCAL, "ollama", "qwen3:8b"),
            ],
            max_retries=2,
            retry_delay_ms=1500
        ),
        "vision": FallbackChain(
            task_type="vision",
            chain=[
                (FallbackLevel.PRIMARY, "openai", "gpt-4o"),
                (FallbackLevel.SECONDARY, "anthropic", "claude-3-sonnet"),
                (FallbackLevel.TERTIARY, "openai", "gpt-4o-mini"),
                (FallbackLevel.LOCAL, "ollama", "llama3.2-vision:11b"),
            ],
            max_retries=1,
            retry_delay_ms=2000
        ),
        "chat": FallbackChain(
            task_type="chat",
            chain=[
                (FallbackLevel.SECONDARY, "openai", "gpt-4o"),
                (FallbackLevel.SECONDARY, "anthropic", "claude-3-sonnet"),
                (FallbackLevel.TERTIARY, "openai", "gpt-4o-mini"),
                (FallbackLevel.TERTIARY, "deepseek", "deepseek-chat"),
                (FallbackLevel.LOCAL, "ollama", "llama3.2:3b"),
                (FallbackLevel.LOCAL, "ollama", "qwen3:8b"),
            ],
            max_retries=2,
            retry_delay_ms=1000
        ),
        "default": FallbackChain(
            task_type="default",
            chain=[
                (FallbackLevel.SECONDARY, "openai", "gpt-4o"),
                (FallbackLevel.TERTIARY, "openai", "gpt-4o-mini"),
                (FallbackLevel.TERTIARY, "deepseek", "deepseek-chat"),
                (FallbackLevel.LOCAL, "ollama", "qwen3:8b"),
            ],
            max_retries=2,
            retry_delay_ms=1000
        )
    }

    def __init__(self):
        self.chains = self.DEFAULT_CHAINS.copy()

        # 模型健康状态
        self._health_status: dict[str, dict] = {}

        # 降级历史
        self._fallback_history: list[FallbackEvent] = []

        # 事件回调
        self._event_callbacks: list[Callable[[FallbackEvent], None]] = []

        # 配置
        self._config = {
            "failure_threshold": 3,        # 连续失败阈值
            "failure_window_seconds": 300, # 失败检查窗口
            "recovery_check_interval": 60, # 恢复检查间隔
            "max_fallback_depth": 3,       # 最大降级深度
        }

        logger.info("[FallbackManager] 初始化完成")

    def get_fallback_chain(self, task_type: str) -> FallbackChain:
        """获取任务类型的降级链"""
        return self.chains.get(task_type, self.chains["default"])

    def get_initial_model(self, task_type: str) -> tuple[str, str]:
        """
        获取初始模型

        Args:
            task_type: 任务类型

        Returns:
            (provider, model)
        """
        chain = self.get_fallback_chain(task_type)

        # 找到第一个健康的模型
        for _level, provider, model in chain.chain:
            if self.is_model_healthy(provider, model):
                return provider, model

        # 所有模型都不健康，返回最后一个（本地模型）
        return chain.chain[-1][1], chain.chain[-1][2]

    def get_next_fallback(self,
                         task_type: str,
                         current_provider: str,
                         current_model: str,
                         reason: FallbackReason,
                         error_message: str = "") -> tuple[str, str] | None:
        """
        获取下一个降级目标

        Args:
            task_type: 任务类型
            current_provider: 当前提供商
            current_model: 当前模型
            reason: 降级原因
            error_message: 错误信息

        Returns:
            Optional[(provider, model)]: 下一个降级目标
        """
        chain = self.get_fallback_chain(task_type)

        # 记录失败
        self._record_failure(current_provider, current_model, reason, error_message)

        # 找到当前位置
        current_idx = None
        for i, (_, provider, model) in enumerate(chain.chain):
            if provider == current_provider and model == current_model:
                current_idx = i
                break

        if current_idx is None:
            logger.warning(f"[FallbackManager] 当前模型 {current_provider}/{current_model} 不在降级链中")
            return None

        # 获取下一级
        if current_idx < len(chain.chain) - 1:
            next_level, next_provider, next_model = chain.chain[current_idx + 1]

            # 记录降级事件
            current_level = chain.chain[current_idx][0]
            event = FallbackEvent(
                timestamp=datetime.now(),
                from_level=current_level,
                to_level=next_level,
                reason=reason,
                error_message=error_message
            )
            self._record_fallback_event(event)

            logger.info(f"[FallbackManager] 降级: {current_provider}/{current_model} -> "
                       f"{next_provider}/{next_model}, 原因: {reason.value}")

            return next_provider, next_model

        logger.error("[FallbackManager] 已到达降级链末端，无法再降级")
        return None

    def is_model_healthy(self, provider: str, model: str) -> bool:
        """检查模型健康状态"""
        key = f"{provider}/{model}"
        status = self._health_status.get(key, {})

        # 检查是否被标记为不健康
        if status.get("unhealthy", False):
            # 检查是否过了恢复时间
            last_failure = status.get("last_failure")
            if last_failure:
                elapsed = (datetime.now() - last_failure).total_seconds()
                if elapsed > self._config["recovery_check_interval"]:
                    # 尝试恢复
                    logger.info(f"[FallbackManager] 尝试恢复模型 {key}")
                    return True
            return False

        return True

    def mark_model_unhealthy(self,
                            provider: str,
                            model: str,
                            reason: str = ""):
        """标记模型为不健康"""
        key = f"{provider}/{model}"

        if key not in self._health_status:
            self._health_status[key] = {
                "failure_count": 0,
                "unhealthy": False,
                "last_failure": None,
                "failures": []
            }

        status = self._health_status[key]
        status["failure_count"] += 1
        status["last_failure"] = datetime.now()
        status["failures"].append({
            "timestamp": datetime.now().isoformat(),
            "reason": reason
        })

        # 检查是否达到阈值
        if status["failure_count"] >= self._config["failure_threshold"]:
            status["unhealthy"] = True
            logger.warning(f"[FallbackManager] 模型 {key} 被标记为不健康 "
                          f"(连续失败{status['failure_count']}次)")

    def mark_model_healthy(self, provider: str, model: str):
        """标记模型为健康"""
        key = f"{provider}/{model}"

        if key in self._health_status:
            self._health_status[key] = {
                "failure_count": 0,
                "unhealthy": False,
                "last_failure": None,
                "failures": []
            }
            logger.info(f"[FallbackManager] 模型 {key} 已恢复为健康状态")

    def _record_failure(self,
                       provider: str,
                       model: str,
                       reason: FallbackReason,
                       error_message: str):
        """记录失败"""
        key = f"{provider}/{model}"

        if key not in self._health_status:
            self._health_status[key] = {
                "failure_count": 0,
                "unhealthy": False,
                "last_failure": None,
                "failures": []
            }

        status = self._health_status[key]
        status["failure_count"] += 1
        status["last_failure"] = datetime.now()
        status["failures"].append({
            "timestamp": datetime.now().isoformat(),
            "reason": reason.value,
            "message": error_message
        })

        # 保留最近10次失败记录
        status["failures"] = status["failures"][-10:]

        # 检查是否达到阈值
        if status["failure_count"] >= self._config["failure_threshold"] and not status.get("unhealthy", False):
            status["unhealthy"] = True
            logger.warning(f"[FallbackManager] 模型 {key} 被标记为不健康 "
                          f"(连续失败{status['failure_count']}次)")

    def _record_fallback_event(self, event: FallbackEvent):
        """记录降级事件"""
        self._fallback_history.append(event)

        # 限制历史记录数量
        if len(self._fallback_history) > 1000:
            self._fallback_history = self._fallback_history[-500:]

        # 触发回调
        for callback in self._event_callbacks:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"[FallbackManager] 事件回调出错: {e}")

    def add_event_callback(self, callback: Callable[[FallbackEvent], None]):
        """添加事件回调"""
        self._event_callbacks.append(callback)

    def remove_event_callback(self, callback: Callable[[FallbackEvent], None]):
        """移除事件回调"""
        if callback in self._event_callbacks:
            self._event_callbacks.remove(callback)

    def get_health_report(self) -> dict[str, Any]:
        """获取健康报告"""
        return {
            "timestamp": datetime.now().isoformat(),
            "config": self._config,
            "models": {
                key: {
                    "healthy": not status.get("unhealthy", False),
                    "failure_count": status.get("failure_count", 0),
                    "last_failure": status.get("last_failure").isoformat() if status.get("last_failure") else None,
                }
                for key, status in self._health_status.items()
            },
            "fallback_stats": {
                "total_events": len(self._fallback_history),
                "recent_events": [
                    {
                        "timestamp": e.timestamp.isoformat(),
                        "from": e.from_level.name,
                        "to": e.to_level.name,
                        "reason": e.reason.value
                    }
                    for e in self._fallback_history[-10:]
                ]
            }
        }

    def reset_health_status(self, provider: str | None = None, model: str | None = None):
        """重置健康状态"""
        if provider and model:
            key = f"{provider}/{model}"
            if key in self._health_status:
                del self._health_status[key]
                logger.info(f"[FallbackManager] 重置模型 {key} 的健康状态")
        else:
            self._health_status.clear()
            logger.info("[FallbackManager] 重置所有模型的健康状态")

    async def execute_with_fallback(self,
                                    task_type: str,
                                    execute_fn: Callable[[str, str], Any],
                                    max_attempts: int = 3) -> tuple[Any, str, str]:
        """
        执行带降级的操作

        Args:
            task_type: 任务类型
            execute_fn: 执行函数，接收(provider, model)参数
            max_attempts: 最大尝试次数

        Returns:
            (结果, 最终provider, 最终model)
        """
        provider, model = self.get_initial_model(task_type)
        last_error = None

        for attempt in range(max_attempts):
            try:
                result = await execute_fn(provider, model)

                # 成功，如果之前失败过，标记为健康
                if attempt > 0:
                    self.mark_model_healthy(provider, model)

                return result, provider, model

            except Exception as e:
                last_error = str(e)
                logger.warning(f"[FallbackManager] 尝试 {attempt + 1} 失败: {last_error}")

                # 确定降级原因
                reason = self._determine_fallback_reason(last_error)

                # 获取下一个降级目标
                next_fallback = self.get_next_fallback(
                    task_type, provider, model, reason, last_error
                )

                if next_fallback is None:
                    logger.error("[FallbackManager] 无可用降级目标")
                    break

                provider, model = next_fallback

                # 等待后重试
                chain = self.get_fallback_chain(task_type)
                await asyncio.sleep(chain.retry_delay_ms / 1000)

        # 所有尝试都失败
        raise Exception(f"所有降级尝试均失败，最后错误: {last_error}")

    def _determine_fallback_reason(self, error_message: str) -> FallbackReason:
        """根据错误信息确定降级原因"""
        error_lower = error_message.lower()

        if any(kw in error_lower for kw in ["timeout", "timed out", "超时"]):
            return FallbackReason.TIMEOUT
        elif any(kw in error_lower for kw in ["rate limit", "too many requests", "429"]):
            return FallbackReason.RATE_LIMIT
        elif any(kw in error_lower for kw in ["network", "connection", "connect", "网络"]):
            return FallbackReason.NETWORK
        elif any(kw in error_lower for kw in ["cost", "budget", "quota", "余额", "预算"]):
            return FallbackReason.COST_LIMIT
        elif any(kw in error_lower for kw in ["unavailable", "not available", "不可用"]):
            return FallbackReason.UNAVAILABLE
        else:
            return FallbackReason.ERROR

    def update_chain(self, task_type: str, chain: FallbackChain):
        """更新降级链"""
        self.chains[task_type] = chain
        logger.info(f"[FallbackManager] 更新任务 '{task_type}' 的降级链")

    def get_fallback_chains(self) -> dict[str, FallbackChain]:
        """获取所有降级链"""
        return self.chains.copy()
