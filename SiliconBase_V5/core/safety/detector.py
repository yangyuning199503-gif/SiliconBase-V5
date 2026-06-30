#!/usr/bin/env python3
"""
幻觉检测器（HallucinationDetector）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
白皮书模块：安全系统三层拆分之检测层
职责：异步检测 AI 响应是否存在幻觉，返回纯数据 DetectionResult
约束：
  - 禁止做任何策略决策（那是 SafetyPolicy 的职责）
  - 禁止修改外部状态
  - 只允许返回 DetectionResult
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DetectionResult:
    """
    检测结果——不可变数据契约
    """
    level: str              # "none" / "low" / "medium" / "high" / "critical"
    score: float            # 0-1
    verification_notes: list[str]
    raw_details: dict | None = None


class HallucinationDetector:
    """
    幻觉检测器——可能调用 LLM，因此接口为 async

    设计约束：只检测，不决策。策略决策交给 SafetyPolicy。
    """

    async def detect(
        self,
        ai_response: str,
        context: dict,
        session_id: str
    ) -> DetectionResult:
        """
        检测 AI 响应是否存在幻觉

        Args:
            ai_response: AI 生成的响应文本
            context: 当前上下文（工具结果、历史对话等）
            session_id: 会话 ID，用于追踪

        Returns:
            DetectionResult: 纯数据，无状态修改
        """
        # TODO: 接入实际检测算法（目前返回占位结果，避免阻塞）
        # 后续可接入：
        # 1. 基于规则的快速过滤（关键词、格式异常）
        # 2. 基于 LLM 的深度验证（与 context 交叉核对）
        # 3. 基于统计的历史模式匹配
        return DetectionResult(
            level="none",
            score=0.0,
            verification_notes=["检测器已初始化，待接入实际算法"],
            raw_details={"session_id": session_id, "response_length": len(ai_response)}
        )
