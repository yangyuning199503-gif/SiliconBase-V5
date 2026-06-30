#!/usr/bin/env python3
"""
经验记录器（ExperienceRecorder）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
白皮书模块：任务经验记录与沉淀
职责：任务完成后记录经验、提取模式、更新世界模型
约束：
  - 全 async 接口
  - 通过 MemoryService 写入记忆，禁止直接操作底层存储
  - 禁止包含分类/进化逻辑（那是 TaskClassifier 的职责）
"""

from dataclasses import dataclass
from typing import Any

from core.evolution.task_classifier import TaskClassification
from core.logger import logger
from core.memory.memory_schema import MemoryMetadata
from core.memory.memory_service import MemoryService


@dataclass
class TaskRecord:
    """
    任务记录——不可变数据契约
    """
    task_id: str
    user_id: str
    instruction: str
    classification: TaskClassification
    tools_used: list[str]
    execution_time: float
    success: bool
    final_answer: str | None
    reflection_notes: str | None
    is_exploratory: bool = False        # 是否是随机探索产生的数据
    exploration_source: str = ""        # "curiosity_drive" | "random_screenshot"


class ExperienceRecorder:
    """
    经验记录器——负责沉淀、反思、进化

    工作流（record 方法）：
    1. 保存执行记录到 MemoryService
    2. 调用 Reflector 提取模式，如有则保存模式
    3. 调用 WorldModel 学习
    4. 更新 TaskClassifier 的统计画像
    """

    def __init__(
        self,
        reflector: Any,
        world_model: Any,
        memory_service: MemoryService,
        classifier: Any
    ) -> None:
        """
        Args:
            reflector: Reflector 实例（模式提取）
            world_model: WorldModel 实例（世界模型学习）
            memory_service: MemoryService 实例（统一记忆入口）
            classifier: TaskClassifier 实例（统计画像更新）
        """
        self.reflector = reflector
        self.world_model = world_model
        self.memory_service = memory_service
        self.classifier = classifier

    async def record(
        self,
        record: TaskRecord,
        execution_history: list[dict] | None = None
    ) -> None:
        """
        记录任务经验

        四步沉淀：
        1. 保存执行记录
        2. 提取模式
        3. 世界模型学习（遍历 execution_history 逐条观察）
        4. 更新分类画像
        """
        # 探索性数据标记（LeJEPA：随机探索数据比有目的策略数据更适合训练世界模型）
        try:
            from core.strategy.intrinsic_motivation import IntrinsicMotivation
            motivation = IntrinsicMotivation()
            drive = motivation.evaluate_drive()
            if drive.should_explore:
                record.is_exploratory = True
                record.exploration_source = "curiosity_drive"
        except (ImportError, ModuleNotFoundError, AttributeError):
            pass  # 内在动机不可用时不影响主流程

        # 步骤 1：保存执行记录到 MemoryService
        metadata = MemoryMetadata(
            user_id=record.user_id,
            source="reflection",
            content_type="json",
            payload_summary=f"任务 {record.task_id}: {'成功' if record.success else '失败'}",
            raw_payload=record.__dict__.__str__(),
            task_id=record.task_id,
            tags=["experience", record.classification.task_type]
        )
        await self.memory_service.save_execution_record(
            record.instruction,
            metadata
        )

        # 步骤 2：调用 Reflector 提取模式
        try:
            from core.reflector.reflector import extract_pattern_from_success
            trajectory = [
                {"tool": t, "success": record.success}
                for t in (record.tools_used or [])
            ]
            pattern = await extract_pattern_from_success(record.instruction, trajectory)
            if pattern:
                pattern_meta = MemoryMetadata(
                    user_id=record.user_id,
                    source="reflection",
                    content_type="text",
                    payload_summary=pattern.get("description", "")[:200],
                    raw_payload=str(pattern),
                    task_id=record.task_id,
                    tags=["pattern", record.classification.task_type]
                )
                await self.memory_service.save_pattern(
                    pattern.get("description", ""),
                    pattern_meta
                )
        except (ImportError, AttributeError, ValueError, TypeError, ConnectionError, RuntimeError):
            logger.exception(
                f"[ExperienceRecorder] 步骤2（extract_pattern_from_success）失败——"
                f"任务ID={record.task_id}"
            )

        # 步骤 3：调用 WorldModel 逐条观察工具执行
        if not execution_history:
            logger.warning(
                f"[ExperienceRecorder] 步骤3跳过——execution_history 为空，"
                f"任务ID={record.task_id}"
            )
        else:
            try:
                for entry in execution_history:
                    tool_id = entry.get("tool")
                    if not tool_id:
                        continue
                    await self.world_model.record_observation(
                        tool_id=tool_id,
                        params=entry.get("params", {}),
                        result=entry.get("result", {}),
                        source="experience_recorder",
                        duration=0.0,
                        context={
                            "task_id": record.task_id,
                            "instruction": record.instruction,
                            "success": entry.get("success", False),
                            "is_exploratory": record.is_exploratory,
                        },
                    )
            except (AttributeError, ValueError, TypeError, ConnectionError, RuntimeError):
                logger.exception(
                    f"[ExperienceRecorder] 步骤3（WorldModel.record_observation）失败——"
                    f"任务ID={record.task_id}"
                )

        # 步骤 4：更新 TaskClassifier 统计画像
        self.classifier.update_profile(
            record.classification.task_type,
            record.execution_time,
            record.success
        )
