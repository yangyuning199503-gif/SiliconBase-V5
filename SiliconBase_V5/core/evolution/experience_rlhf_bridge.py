#!/usr/bin/env python3
"""
经验-RLHF联动桥 - Experience-RLHF Bridge

当用户反馈"这个回答不好"时:
1. 记录当前使用的经验条目
2. 降低这些经验的权重
3. 下次避免使用类似经验

正向反馈同理，增强成功经验

Author: SiliconBase V5
Version: 1.0.0
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.evolution.rlhf_feedback import FeedbackType
from core.exceptions import ExperienceUpdateError, RLHFStorageError  # 【Agent3】导入异常类型
from core.logger import logger


@dataclass
class ExperienceFeedbackLink:
    """经验与反馈的关联记录"""
    exp_id: str
    feedback_id: str
    feedback_type: str  # "positive" | "negative"
    task_hash: str | None = None
    timestamp: float = field(default_factory=time.time)
    impact_score: float = 0.0  # 影响程度 0-1

    def to_dict(self) -> dict[str, Any]:
        return {
            "exp_id": self.exp_id,
            "feedback_id": self.feedback_id,
            "feedback_type": self.feedback_type,
            "task_hash": self.task_hash,
            "timestamp": self.timestamp,
            "impact_score": self.impact_score
        }


class ExperienceRLHFBridge:
    """
    经验-RLHF联动桥

    核心功能：
    - 追踪哪些经验被用于生成回复
    - 根据用户反馈调整经验权重
    - 构建反馈闭环
    """

    def __init__(self):
        self.data_dir = Path(__file__).parent.parent / "data" / "rlhf"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 经验-反馈关联存储
        self.links_file = self.data_dir / "exp_feedback_links.jsonl"

        # 经验权重调整记录
        self.weights_file = self.data_dir / "exp_weights.json"
        self._weights_cache: dict[str, float] = {}
        self._load_weights()

        # 当前活跃的经验使用记录
        self._active_exp_usage: dict[str, dict] = {}  # response_id -> {exp_ids, task_hash, timestamp}

        # 权重调整配置
        self.boost_factor = 1.1  # 正向反馈权重提升因子
        self.reduce_factor = 0.8  # 负向反馈权重降低因子
        self.max_weight = 2.0     # 最大权重
        self.min_weight = 0.3     # 最小权重

        logger.info(f"[ExpRLHFBridge] 初始化完成，已加载 {len(self._weights_cache)} 条权重记录")

    def record_experience_usage(
        self,
        response_id: str,
        exp_ids: list[str],
        task_hash: str | None = None
    ):
        """
        记录经验使用情况

        Args:
            response_id: 回复ID
            exp_ids: 使用的经验ID列表
            task_hash: 任务哈希（用于追踪）
        """
        if not exp_ids:
            return

        self._active_exp_usage[response_id] = {
            "exp_ids": exp_ids,
            "task_hash": task_hash,
            "timestamp": time.time()
        }

        logger.debug(f"[ExpRLHFBridge] 记录经验使用: response={response_id}, exps={exp_ids}")

    def process_feedback(
        self,
        response_id: str,
        feedback_type: FeedbackType,
        feedback_id: str
    ) -> dict[str, Any]:
        """
        处理用户反馈，调整相关经验权重

        Args:
            response_id: 回复ID
            feedback_type: 反馈类型（赞/踩）
            feedback_id: 反馈ID

        Returns:
            处理结果统计
        """
        result = {
            "affected_experiences": 0,
            "weight_adjustments": [],
            "message": "",
            "feedback_type": feedback_type.value
        }

        # 获取该回复使用的经验
        usage = self._active_exp_usage.get(response_id)
        if not usage:
            logger.warning(f"[ExpRLHFBridge] 未找到回复 {response_id} 的经验使用记录")
            result["message"] = "反馈已记录，但未关联到具体经验"
            return result

        exp_ids = usage.get("exp_ids", [])
        if not exp_ids:
            result["message"] = "反馈已记录"
            return result

        is_positive = feedback_type == FeedbackType.THUMBS_UP

        # 调整每个经验的权重
        for exp_id in exp_ids:
            old_weight = self._weights_cache.get(exp_id, 1.0)

            if is_positive:
                # 正向反馈：增强经验权重
                new_weight = min(self.max_weight, old_weight * self.boost_factor)
                impact = new_weight - old_weight
            else:
                # 负向反馈：降低经验权重
                new_weight = max(self.min_weight, old_weight * self.reduce_factor)
                impact = old_weight - new_weight

            self._weights_cache[exp_id] = round(new_weight, 3)

            # 记录关联
            link = ExperienceFeedbackLink(
                exp_id=exp_id,
                feedback_id=feedback_id,
                feedback_type="positive" if is_positive else "negative",
                task_hash=usage.get("task_hash"),
                impact_score=round(impact, 3)
            )
            self._save_link(link)

            result["weight_adjustments"].append({
                "exp_id": exp_id,
                "old_weight": round(old_weight, 3),
                "new_weight": round(new_weight, 3),
                "change": round(new_weight - old_weight, 3)
            })

        result["affected_experiences"] = len(exp_ids)
        result["message"] = self._generate_feedback_message(is_positive, len(exp_ids))

        # 持久化权重
        self._save_weights()

        # 清理已处理的记录（保留最近100条用于调试）
        if len(self._active_exp_usage) > 100:
            oldest_key = min(self._active_exp_usage.keys(),
                           key=lambda k: self._active_exp_usage[k]["timestamp"])
            del self._active_exp_usage[oldest_key]

        logger.info(
            f"[ExpRLHFBridge] 处理反馈 {feedback_id}: "
            f"类型={'正向' if is_positive else '负向'}, "
            f"影响 {len(exp_ids)} 条经验"
        )
        return result

    def get_experience_weight(self, exp_id: str) -> float:
        """
        获取经验当前权重

        Args:
            exp_id: 经验ID

        Returns:
            权重值 (0.3 - 2.0)，默认1.0
        """
        return self._weights_cache.get(exp_id, 1.0)

    def get_experience_weights_batch(self, exp_ids: list[str]) -> dict[str, float]:
        """
        批量获取经验权重

        Args:
            exp_ids: 经验ID列表

        Returns:
            {exp_id: weight} 字典
        """
        return {exp_id: self._weights_cache.get(exp_id, 1.0) for exp_id in exp_ids}

    def get_weight_stats(self) -> dict[str, Any]:
        """
        获取权重统计信息

        Returns:
            统计信息字典
        """
        if not self._weights_cache:
            return {
                "total": 0,
                "avg_weight": 1.0,
                "max_weight": 1.0,
                "min_weight": 1.0,
                "boosted_count": 0,
                "reduced_count": 0,
                "neutral_count": 0
            }

        weights = list(self._weights_cache.values())
        return {
            "total": len(weights),
            "avg_weight": round(sum(weights) / len(weights), 3),
            "max_weight": round(max(weights), 3),
            "min_weight": round(min(weights), 3),
            "boosted_count": sum(1 for w in weights if w > 1.0),
            "reduced_count": sum(1 for w in weights if w < 1.0),
            "neutral_count": sum(1 for w in weights if w == 1.0)
        }

    def reset_weight(self, exp_id: str):
        """
        重置经验权重为默认值

        Args:
            exp_id: 经验ID
        """
        if exp_id in self._weights_cache:
            del self._weights_cache[exp_id]
            self._save_weights()
            logger.info(f"[ExpRLHFBridge] 重置经验 {exp_id} 权重为默认")

    def get_recent_links(self, limit: int = 20) -> list[dict]:
        """
        获取最近的关联记录

        Args:
            limit: 返回记录数量

        Returns:
            关联记录列表
        """
        if not self.links_file.exists():
            return []

        links = []
        try:
            with open(self.links_file, encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        links.append(json.loads(line))
        except Exception as e:
            logger.error(f"[ExpRLHFBridge] 读取关联记录失败: {e}")

        # 按时间倒序
        links.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return links[:limit]

    def _generate_feedback_message(self, is_positive: bool, count: int) -> str:
        """
        生成反馈确认消息

        Args:
            is_positive: 是否为正向反馈
            count: 影响的经验数量

        Returns:
            确认消息
        """
        import random

        if is_positive:
            messages = [
                f"✓ 已记录你的认可！这{count}条经验会在未来的任务中更频繁地被参考。",
                "✓ 感谢反馈！我会记住这些成功经验。",
                "✓ 你的肯定让这些经验更有价值了！",
                "✓ 已学习！我会继续沿用这种方法。",
            ]
        else:
            messages = [
                f"✓ 已记录你的反馈。我会降低这{count}条经验的参考权重。",
                "✓ 感谢指出问题！我会避免使用类似的经验。",
                "✓ 收到！我会从这次失败中学习并改进。",
                "✓ 已调整！下次会尝试不同的方法。",
            ]

        return random.choice(messages)

    def _save_link(self, link: ExperienceFeedbackLink):
        """保存经验-反馈关联 - 【Agent3】禁止静默失败"""
        if not link:
            logger.error("[ExpRLHFBridge] [SILENT_FAILURE_BLOCKED] 关联记录为空")
            raise RLHFStorageError("关联记录不能为空")

        try:
            with open(self.links_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(link.to_dict(), ensure_ascii=False) + '\n')
        except OSError as e:
            logger.error(f"[ExpRLHFBridge] [SILENT_FAILURE_BLOCKED] 保存关联记录失败: {e}", exc_info=True)
            raise RLHFStorageError(f"保存经验-反馈关联失败: {e}") from e

    def _load_weights(self):
        """加载经验权重"""
        if self.weights_file.exists():
            try:
                with open(self.weights_file, encoding='utf-8') as f:
                    self._weights_cache = json.load(f)
                    logger.info(f"[ExpRLHFBridge] 加载了 {len(self._weights_cache)} 条权重记录")
            except Exception as e:
                logger.warning(f"[ExpRLHFBridge] 加载权重失败: {e}")
                self._weights_cache = {}

    def _save_weights(self):
        """保存经验权重 - 【Agent3】禁止静默失败"""
        try:
            with open(self.weights_file, 'w', encoding='utf-8') as f:
                json.dump(self._weights_cache, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error(f"[ExpRLHFBridge] [SILENT_FAILURE_BLOCKED] 保存权重失败: {e}", exc_info=True)
            raise ExperienceUpdateError(f"保存经验权重失败: {e}") from e


# =============================================================================
# 全局桥接器实例和便捷函数
# =============================================================================

# 全局桥接器实例
exp_rlhf_bridge: ExperienceRLHFBridge | None = None


def get_exp_rlhf_bridge() -> ExperienceRLHFBridge:
    """获取全局 ExperienceRLHFBridge 实例（单例模式）"""
    global exp_rlhf_bridge
    if exp_rlhf_bridge is None:
        exp_rlhf_bridge = ExperienceRLHFBridge()
    return exp_rlhf_bridge


def record_exp_usage_for_response(response_id: str, exp_ids: list[str], task_hash: str | None = None):
    """
    便捷函数：记录回复使用的经验

    Args:
        response_id: 回复ID
        exp_ids: 经验ID列表
        task_hash: 任务哈希
    """
    bridge = get_exp_rlhf_bridge()
    bridge.record_experience_usage(response_id, exp_ids, task_hash)


def apply_feedback_to_experiences(response_id: str, feedback_type: FeedbackType, feedback_id: str) -> dict:
    """
    便捷函数：应用反馈到经验

    Args:
        response_id: 回复ID
        feedback_type: 反馈类型
        feedback_id: 反馈ID

    Returns:
        处理结果
    """
    bridge = get_exp_rlhf_bridge()
    return bridge.process_feedback(response_id, feedback_type, feedback_id)


def get_exp_weight(exp_id: str) -> float:
    """
    便捷函数：获取经验权重

    Args:
        exp_id: 经验ID

    Returns:
        权重值
    """
    bridge = get_exp_rlhf_bridge()
    return bridge.get_experience_weight(exp_id)


# =============================================================================
# 模块测试
# =============================================================================

if __name__ == "__main__":
    # 简单测试
    print("=== Experience-RLHF Bridge 测试 ===")

    bridge = get_exp_rlhf_bridge()

    # 测试记录经验使用
    bridge.record_experience_usage("resp_001", ["exp_001", "exp_002", "exp_003"], "task_hash_001")
    print("已记录经验使用: resp_001")

    # 测试处理反馈
    result = bridge.process_feedback("resp_001", FeedbackType.THUMBS_UP, "fb_001")
    print("\n处理正向反馈结果:")
    print(f"  消息: {result['message']}")
    print(f"  影响经验数: {result['affected_experiences']}")
    print(f"  权重调整: {result['weight_adjustments']}")

    # 测试获取权重统计
    stats = bridge.get_weight_stats()
    print("\n权重统计:")
    print(f"  总记录数: {stats['total']}")
    print(f"  平均权重: {stats['avg_weight']}")
    print(f"  增强数量: {stats['boosted_count']}")
    print(f"  降低数量: {stats['reduced_count']}")

    print("\n=== 测试完成 ===")
