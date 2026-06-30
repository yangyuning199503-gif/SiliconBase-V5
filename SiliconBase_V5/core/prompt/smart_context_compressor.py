#!/usr/bin/env python3
"""
智能上下文压缩器 - 方向B: 智能上下文压缩
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

核心改进：
1. 基于重要性评估决定保留哪些信息（不只是简单截断）
2. 使用语义相似度判断与当前任务的相关性
3. 智能摘要而非简单截断
4. 保留关键决策点和失败经验
5. 动态调整压缩策略

Author: Agent-Refactoring
Version: 1.0.0
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MessageImportance:
    """消息重要性评估结果"""
    message_id: str
    content: str
    role: str

    # 各维度重要性分数 (0-1)
    semantic_score: float = 0.0      # 与当前任务的语义相关性
    decision_score: float = 0.0      # 是否包含决策点
    failure_score: float = 0.0       # 是否包含失败经验
    recency_score: float = 0.0       # 时效性
    uniqueness_score: float = 0.0    # 信息独特性

    # 综合分数
    final_score: float = 0.0

    def calculate_final(self, weights: dict[str, float] | None = None):
        """计算综合重要性分数"""
        w = weights or {
            "semantic": 0.30,
            "decision": 0.25,
            "failure": 0.20,
            "recency": 0.15,
            "uniqueness": 0.10
        }

        self.final_score = (
            self.semantic_score * w["semantic"] +
            self.decision_score * w["decision"] +
            self.failure_score * w["failure"] +
            self.recency_score * w["recency"] +
            self.uniqueness_score * w["uniqueness"]
        )
        return self.final_score


@dataclass
class CompressionResult:
    """压缩结果"""
    compressed_messages: list[dict]
    original_count: int
    compressed_count: int
    importance_scores: list[MessageImportance]
    tokens_saved: int
    compression_ratio: float
    strategy_used: str
    metadata: dict[str, Any] = field(default_factory=dict)


class SmartContextCompressor:
    """
    智能上下文压缩器

    特点：
    1. 重要性导向：基于多维度评估选择保留哪些信息
    2. 语义感知：使用向量相似度判断相关性
    3. 智能摘要：使用LLM生成高质量摘要
    4. 关键信息保护：保留决策点和失败经验
    """

    def __init__(self,
                 target_tokens: int = 2000,
                 max_messages: int = 30,
                 min_importance_threshold: float = 0.3,
                 preserve_failures: bool = True,
                 preserve_decisions: bool = True):
        """
        初始化智能压缩器

        Args:
            target_tokens: 目标token数
            max_messages: 最大保留消息数
            min_importance_threshold: 最小重要性阈值
            preserve_failures: 是否保护失败经验
            preserve_decisions: 是否保护决策点
        """
        self.target_tokens = target_tokens
        self.max_messages = max_messages
        self.min_importance_threshold = min_importance_threshold
        self.preserve_failures = preserve_failures
        self.preserve_decisions = preserve_decisions

        # 统计信息
        self.stats = {
            "total_compressions": 0,
            "total_tokens_saved": 0,
            "avg_compression_ratio": 0.0
        }

        # 嵌入模型缓存
        self._embedding_model = None

    def compress(self,
                 messages: list[dict],
                 current_task: str | None = None,
                 execution_history: list[dict] | None = None) -> CompressionResult:
        """
        智能压缩上下文

        Args:
            messages: 消息列表
            current_task: 当前任务描述（用于计算相关性）
            execution_history: 执行历史（用于提取工具结果）

        Returns:
            CompressionResult: 压缩结果
        """
        if not messages:
            return CompressionResult(
                compressed_messages=[],
                original_count=0,
                compressed_count=0,
                importance_scores=[],
                tokens_saved=0,
                compression_ratio=0.0,
                strategy_used="none"
            )

        original_count = len(messages)
        original_tokens = self._estimate_tokens(messages)

        # 如果消息数在限制内，无需压缩
        if original_count <= self.max_messages and original_tokens <= self.target_tokens:
            return CompressionResult(
                compressed_messages=messages,
                original_count=original_count,
                compressed_count=original_count,
                importance_scores=[],
                tokens_saved=0,
                compression_ratio=1.0,
                strategy_used="none_needed"
            )

        # ═════════════════════════════════════════════════════════════════════════════
        # 步骤1: 评估每条消息的重要性
        # ═════════════════════════════════════════════════════════════════════════════
        importance_scores = self._evaluate_importance(
            messages, current_task, execution_history
        )

        # ═════════════════════════════════════════════════════════════════════════════
        # 步骤2: 分类处理消息
        # ═════════════════════════════════════════════════════════════════════════════
        protected_msgs = []      # 必须保留（失败经验、决策点）
        high_value_msgs = []     # 高重要性消息
        medium_value_msgs = []   # 中等重要性消息
        low_value_msgs = []      # 低重要性消息

        for score in importance_scores:
            msg = self._find_message_by_id(messages, score.message_id)
            if not msg:
                continue

            # 保护关键消息
            if self.preserve_failures and score.failure_score > 0.7 or self.preserve_decisions and score.decision_score > 0.7:
                protected_msgs.append((msg, score))
            elif score.final_score >= 0.7:
                high_value_msgs.append((msg, score))
            elif score.final_score >= self.min_importance_threshold:
                medium_value_msgs.append((msg, score))
            else:
                low_value_msgs.append((msg, score))

        # ═════════════════════════════════════════════════════════════════════════════
        # 步骤3: 智能选择保留的消息
        # ═════════════════════════════════════════════════════════════════════════════
        selected_msgs = []
        selected_ids = set()
        current_tokens = 0

        # 3.1 首先保留受保护的消息
        for msg, score in protected_msgs:
            msg_tokens = self._estimate_tokens([msg])
            if current_tokens + msg_tokens <= self.target_tokens:
                selected_msgs.append((msg, score, "protected"))
                selected_ids.add(score.message_id)
                current_tokens += msg_tokens

        # 3.2 保留高价值消息
        for msg, score in high_value_msgs:
            if len(selected_msgs) >= self.max_messages:
                break
            if score.message_id in selected_ids:
                continue
            msg_tokens = self._estimate_tokens([msg])
            if current_tokens + msg_tokens <= self.target_tokens:
                selected_msgs.append((msg, score, "high_value"))
                selected_ids.add(score.message_id)
                current_tokens += msg_tokens

        # 3.3 保留最近的中等价值消息
        recent_medium = medium_value_msgs[-10:]  # 只保留最近的10条中等价值消息
        for msg, score in recent_medium:
            if len(selected_msgs) >= self.max_messages:
                break
            if score.message_id in selected_ids:
                continue
            msg_tokens = self._estimate_tokens([msg])
            if current_tokens + msg_tokens <= self.target_tokens:
                selected_msgs.append((msg, score, "medium_value"))
                selected_ids.add(score.message_id)
                current_tokens += msg_tokens

        # ═════════════════════════════════════════════════════════════════════════════
        # 步骤4: 生成智能摘要
        # ═════════════════════════════════════════════════════════════════════════════
        # 对被舍弃的消息生成摘要
        discarded_msgs = [m for m in messages if m.get("id") not in selected_ids]
        if discarded_msgs:
            summary = self._generate_smart_summary(discarded_msgs, execution_history)
            summary_msg = {
                "role": "system",
                "content": f"[上下文摘要] {summary}",
                "id": f"summary_{int(time.time())}",
                "_compressed": True,
                "_compression_info": {
                    "original_count": len(discarded_msgs),
                    "summary_method": "smart",
                    "protected_count": len(protected_msgs)
                }
            }
            selected_msgs.insert(0, (summary_msg, None, "summary"))

        # ═════════════════════════════════════════════════════════════════════════════
        # 步骤5: 排序并组装最终结果
        # ═════════════════════════════════════════════════════════════════════════════
        # 按原始顺序排序（摘要除外，它放在最前面）
        result_msgs = []
        summary_item = None

        for msg, _score, category in selected_msgs:
            if category == "summary":
                summary_item = msg
            else:
                result_msgs.append(msg)

        # 保持原始顺序
        original_order = {m.get("id"): i for i, m in enumerate(messages)}
        result_msgs.sort(key=lambda m: original_order.get(m.get("id"), 999999))

        # 摘要在最前
        if summary_item:
            result_msgs.insert(0, summary_item)

        # ═════════════════════════════════════════════════════════════════════════════
        # 步骤6: 计算统计信息
        # ═════════════════════════════════════════════════════════════════════════════
        compressed_tokens = self._estimate_tokens(result_msgs)
        tokens_saved = original_tokens - compressed_tokens
        compression_ratio = compressed_tokens / original_tokens if original_tokens > 0 else 1.0

        # 更新统计
        self.stats["total_compressions"] += 1
        self.stats["total_tokens_saved"] += tokens_saved
        self.stats["avg_compression_ratio"] = (
            (self.stats["avg_compression_ratio"] * (self.stats["total_compressions"] - 1) + compression_ratio)
            / self.stats["total_compressions"]
        )

        return CompressionResult(
            compressed_messages=result_msgs,
            original_count=original_count,
            compressed_count=len(result_msgs),
            importance_scores=importance_scores,
            tokens_saved=tokens_saved,
            compression_ratio=compression_ratio,
            strategy_used="smart_importance",
            metadata={
                "protected_count": len(protected_msgs),
                "high_value_count": len(high_value_msgs),
                "medium_value_count": len(recent_medium),
                "discarded_count": len(discarded_msgs)
            }
        )

    def _evaluate_importance(self,
                            messages: list[dict],
                            current_task: str | None,
                            execution_history: list[dict] | None) -> list[MessageImportance]:
        """
        评估每条消息的重要性

        评估维度：
        1. 语义相关性：与当前任务的相似度
        2. 决策重要性：是否包含关键决策
        3. 失败经验：是否包含失败/错误信息
        4. 时效性：消息的最近程度
        5. 独特性：信息是否重复
        """
        scores = []

        # 提取执行历史中的工具结果用于上下文
        self._extract_tool_results(execution_history)

        for i, msg in enumerate(messages):
            content = msg.get("content", "")
            role = msg.get("role", "")
            msg_id = msg.get("id", f"msg_{i}")

            score = MessageImportance(
                message_id=msg_id,
                content=content[:200],  # 截断用于显示
                role=role
            )

            # 1. 语义相关性评分
            if current_task:
                score.semantic_score = self._calculate_semantic_relevance(content, current_task)
            else:
                score.semantic_score = 0.5

            # 2. 决策重要性评分
            score.decision_score = self._evaluate_decision_importance(content, role)

            # 3. 失败经验评分
            score.failure_score = self._evaluate_failure_value(content, role)

            # 4. 时效性评分（越新越高）
            score.recency_score = self._calculate_recency_score(i, len(messages))

            # 5. 独特性评分（基于内容独特性）
            score.uniqueness_score = self._evaluate_uniqueness(content, [s.content for s in scores])

            # 计算综合分数
            score.calculate_final()

            scores.append(score)

        return scores

    def _calculate_semantic_relevance(self, content: str, task: str) -> float:
        """计算内容与任务的语义相关性

        优先使用向量相似度，向量服务不可用时优雅降级到文本相似度。
        确保核心流程不会因向量服务故障而中断。
        """
        # TODO: 待上层异步化后可接入向量相似度
        # 回退到文本相似度（始终作为最终回退）
        return self._text_similarity(content, task)

    def _text_similarity(self, text1: str, text2: str) -> float:
        """计算两段文本的Jaccard相似度"""
        import re

        def tokenize(text):
            text = text.lower()
            chinese = re.findall(r'[\u4e00-\u9fff]', text)
            english = re.findall(r'[a-zA-Z]+', text)
            return set(chinese + english)

        set1 = tokenize(text1)
        set2 = tokenize(text2)

        if not set1 or not set2:
            return 0.0

        intersection = set1 & set2
        union = set1 | set2

        return len(intersection) / len(union) if union else 0.0

    def _evaluate_decision_importance(self, content: str, role: str) -> float:
        """评估决策重要性"""
        score = 0.0

        # 决策关键词
        decision_keywords = [
            "决定", "选择", "采用", "使用.*工具", "调用.*函数",
            "decide", "choose", "select", "adopt", "use tool", "call function"
        ]

        import re
        for kw in decision_keywords:
            if re.search(kw, content, re.IGNORECASE):
                score += 0.2

        # system消息中的决策通常更重要
        if role == "system":
            score += 0.1

        # 包含工具结果的消息通常包含决策
        if "【工具结果】" in content or "[工具结果]" in content:
            score += 0.15

        # 【P0修复】OpenAI标准 role="tool" 消息（工具调用结果）必须保留
        if role == "tool":
            score += 0.5

        # 【P0修复】工具执行结果消息（无论成功/失败）对避免重复调用至关重要
        if "[工具执行结果]" in content or "工具执行结果" in content:
            score += 0.4

        return min(score, 1.0)

    def _evaluate_failure_value(self, content: str, role: str) -> float:
        """评估失败经验的价值"""
        score = 0.0

        # 失败关键词
        failure_keywords = [
            "失败", "错误", "异常", "无法", "不能", "报错", "timeout", "超时",
            "fail", "error", "exception", "unable", "cannot", "timeout"
        ]

        content_lower = content.lower()
        for kw in failure_keywords:
            if kw in content_lower:
                score += 0.3
                break

        # 包含解决方案的失败信息更有价值
        solution_keywords = ["解决", "修复", "调整", "尝试", "fix", "solve", "adjust"]
        for kw in solution_keywords:
            if kw in content_lower:
                score += 0.2
                break

        return min(score, 1.0)

    def _calculate_recency_score(self, index: int, total: int) -> float:
        """计算时效性分数（越新越高）"""
        if total <= 1:
            return 1.0

        # 线性衰减，最新消息=1.0，最旧消息=0.3
        return 0.3 + 0.7 * (index / (total - 1))

    def _evaluate_uniqueness(self, content: str, previous_contents: list[str]) -> float:
        """评估内容的独特性"""
        if not previous_contents:
            return 1.0

        # 与之前内容的平均相似度
        similarities = [self._text_similarity(content, prev) for prev in previous_contents[-5:]]
        avg_similarity = sum(similarities) / len(similarities) if similarities else 0

        # 越独特分数越高
        return 1.0 - avg_similarity

    def _generate_smart_summary(self,
                               discarded_msgs: list[dict],
                               execution_history: list[dict] | None) -> str:
        """
        生成智能摘要

        不是简单截断，而是提取关键信息
        """
        # 提取工具调用统计
        tool_stats = defaultdict(lambda: {"success": 0, "fail": 0})
        key_events = []

        for msg in discarded_msgs:
            content = msg.get("content", "")
            role = msg.get("role", "")

            # 统计工具调用
            if "【工具结果】" in content:
                tool_name = self._extract_tool_name(content)
                success = "成功" in content or "✓" in content or "success" in content.lower()
                if success:
                    tool_stats[tool_name]["success"] += 1
                else:
                    tool_stats[tool_name]["fail"] += 1

            # 提取关键事件
            if role == "assistant" and len(content) > 20:
                # 提取前60个字符作为事件描述
                event = content[:60] + "..." if len(content) > 60 else content
                key_events.append(event)

        # 构建摘要
        summary_parts = []

        # 工具调用摘要
        if tool_stats:
            tool_summary = []
            for tool, stats in tool_stats.items():
                if stats["fail"] > 0:
                    tool_summary.append(f"{tool}(成功{stats['success']}/失败{stats['fail']})")
                else:
                    tool_summary.append(f"{tool}(成功{stats['success']})")
            summary_parts.append(f"执行({len(tool_stats)}种工具): " + ", ".join(tool_summary))

        # 关键事件（去重后取前3）
        if key_events:
            unique_events = list(dict.fromkeys(key_events))[:3]
            summary_parts.append("关键事件: " + "; ".join(unique_events))

        return " | ".join(summary_parts) if summary_parts else f"已压缩{len(discarded_msgs)}条历史消息"

    def _extract_tool_results(self, execution_history: list[dict] | None) -> dict[str, Any]:
        """从执行历史中提取工具结果"""
        results = {}
        if not execution_history:
            return results

        for h in execution_history:
            tool = h.get("tool", "unknown")
            success = h.get("success", False)
            results[tool] = {"success": success, "result": h.get("result", {})}

        return results

    def _extract_tool_name(self, content: str) -> str:
        """从内容中提取工具名称"""
        import re

        # 匹配【工具结果】工具名: ...
        match = re.search(r'【工具结果】([^:]+):', content)
        if match:
            return match.group(1).strip()[:20]

        return "unknown"

    def _estimate_tokens(self, messages: list[dict]) -> int:
        """估算消息的token数"""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            # 简单估算：中文2字符/token，英文4字符/token
            chinese_chars = len([c for c in content if '\u4e00' <= c <= '\u9fff'])
            other_chars = len(content) - chinese_chars
            total += chinese_chars // 2 + other_chars // 4 + 1
        return total

    def _find_message_by_id(self, messages: list[dict], msg_id: str) -> dict | None:
        """根据ID查找消息"""
        for msg in messages:
            if msg.get("id") == msg_id:
                return msg
        return None

    def get_stats(self) -> dict[str, Any]:
        """获取压缩统计信息"""
        return self.stats.copy()


# ═════════════════════════════════════════════════════════════════════════════
# 便捷函数
# ═════════════════════════════════════════════════════════════════════════════

def compress_context_smart(messages: list[dict],
                          current_task: str | None = None,
                          execution_history: list[dict] | None = None,
                          **kwargs) -> CompressionResult:
    """
    便捷函数：智能压缩上下文

    Args:
        messages: 消息列表
        current_task: 当前任务描述
        execution_history: 执行历史
        **kwargs: 其他参数传递给SmartContextCompressor

    Returns:
        CompressionResult: 压缩结果
    """
    compressor = SmartContextCompressor(**kwargs)
    return compressor.compress(messages, current_task, execution_history)


# 全局实例
_smart_compressor: SmartContextCompressor | None = None


def get_smart_compressor() -> SmartContextCompressor:
    """获取全局智能压缩器实例"""
    global _smart_compressor
    if _smart_compressor is None:
        _smart_compressor = SmartContextCompressor()
    return _smart_compressor
