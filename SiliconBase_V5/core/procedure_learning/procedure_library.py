#!/usr/bin/env python3
"""
操作流程库 (Procedure Library)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

存储和管理学习到的操作流程，支持查询、更新和执行。

功能：
1. 保存操作流程
2. 按意图查询流程
3. 流程版本管理
4. 执行统计和优化建议
"""

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ProcedureStep:
    """
    流程步骤

    Attributes:
        step_id: 步骤ID
        step_number: 步骤序号
        description: 步骤描述
        tool_name: 使用的工具名
        tool_params: 工具参数模板
        expected_result: 预期结果
        retry_count: 重试次数
        timeout: 超时时间（秒）
        fallback_step: 失败时的回退步骤ID
    """
    step_id: str
    step_number: int
    description: str
    tool_name: str
    tool_params: dict[str, Any] = field(default_factory=dict)
    expected_result: str | None = None
    retry_count: int = 1
    timeout: int = 30
    fallback_step: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'ProcedureStep':
        return cls(**data)


@dataclass
class Procedure:
    """
    操作流程

    Attributes:
        procedure_id: 流程ID
        name: 流程名称
        intent: 意图关键词
        description: 流程描述
        steps: 步骤列表
        created_at: 创建时间
        updated_at: 更新时间
        usage_count: 使用次数
        success_count: 成功次数
        avg_execution_time: 平均执行时间
        is_active: 是否激活
        tags: 标签
        parameters: 可配置参数（如目的地、日期等）
    """
    procedure_id: str
    name: str
    intent: str
    description: str
    steps: list[ProcedureStep] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    usage_count: int = 0
    success_count: int = 0
    avg_execution_time: float = 0.0
    is_active: bool = True
    tags: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    source_recording_id: str | None = None  # 来源录制ID

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data['steps'] = [step.to_dict() for step in self.steps]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'Procedure':
        steps_data = data.pop('steps', [])
        procedure = cls(**data)
        procedure.steps = [ProcedureStep.from_dict(s) for s in steps_data]
        return procedure

    def record_execution(self, success: bool, execution_time: float):
        """记录执行结果"""
        self.usage_count += 1
        if success:
            self.success_count += 1
        # 更新平均执行时间
        if self.avg_execution_time == 0:
            self.avg_execution_time = execution_time
        else:
            self.avg_execution_time = (self.avg_execution_time + execution_time) / 2
        self.updated_at = time.time()

    def get_success_rate(self) -> float:
        """获取成功率"""
        if self.usage_count == 0:
            return 0.0
        return self.success_count / self.usage_count

    def fill_parameters(self, **kwargs) -> 'Procedure':
        """
        填充参数到流程

        Args:
            **kwargs: 参数值

        Returns:
            填充参数后的流程副本
        """
        import copy
        filled = copy.deepcopy(self)

        def replace_params(obj):
            if isinstance(obj, dict):
                return {k: replace_params(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [replace_params(item) for item in obj]
            elif isinstance(obj, str):
                result = obj
                for key, value in kwargs.items():
                    placeholder = f"{{{key}}}"
                    if placeholder in result:
                        result = result.replace(placeholder, str(value))
                return result
            return obj

        for step in filled.steps:
            step.tool_params = replace_params(step.tool_params)
            step.description = replace_params(step.description)

        return filled


class ProcedureLibrary:
    """
    操作流程库

    管理所有学习到的操作流程。
    """

    def __init__(self, storage_dir: str | None = None):
        self._procedures: dict[str, Procedure] = {}
        self._intent_index: dict[str, list[str]] = {}  # intent -> procedure_ids
        self._tag_index: dict[str, list[str]] = {}  # tag -> procedure_ids

        self._storage_dir = Path(storage_dir) if storage_dir else Path("data/procedures")
        self._storage_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()

        # 加载已有流程
        self._load_all()

    def _load_all(self):
        """加载所有保存的流程"""
        for file_path in self._storage_dir.glob("*.json"):
            try:
                with open(file_path, encoding='utf-8') as f:
                    data = json.load(f)
                    procedure = Procedure.from_dict(data)
                    self._add_to_index(procedure)
                    self._procedures[procedure.procedure_id] = procedure
            except Exception as e:
                print(f"[ProcedureLibrary] 加载流程失败 {file_path}: {e}")

    def _save_procedure(self, procedure: Procedure):
        """保存单个流程"""
        file_path = self._storage_dir / f"{procedure.procedure_id}.json"
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(procedure.to_dict(), f, ensure_ascii=False, indent=2)

    def _add_to_index(self, procedure: Procedure):
        """添加流程到索引"""
        # 意图索引
        intent = procedure.intent.lower()
        if intent not in self._intent_index:
            self._intent_index[intent] = []
        if procedure.procedure_id not in self._intent_index[intent]:
            self._intent_index[intent].append(procedure.procedure_id)

        # 标签索引
        for tag in procedure.tags:
            tag = tag.lower()
            if tag not in self._tag_index:
                self._tag_index[tag] = []
            if procedure.procedure_id not in self._tag_index[tag]:
                self._tag_index[tag].append(procedure.procedure_id)

    def add_procedure(self, procedure: Procedure) -> str:
        """
        添加新流程

        Args:
            procedure: 流程对象

        Returns:
            procedure_id
        """
        with self._lock:
            if not procedure.procedure_id:
                procedure.procedure_id = f"proc_{int(time.time())}_{uuid.uuid4().hex[:8]}"

            self._procedures[procedure.procedure_id] = procedure
            self._add_to_index(procedure)
            self._save_procedure(procedure)

            return procedure.procedure_id

    def get_procedure(self, procedure_id: str) -> Procedure | None:
        """获取流程"""
        return self._procedures.get(procedure_id)

    def find_by_intent(self, intent: str, limit: int = 5) -> list[Procedure]:
        """
        按意图查找流程

        Args:
            intent: 意图关键词
            limit: 返回数量限制

        Returns:
            匹配的流程列表（按成功率排序）
        """
        intent = intent.lower()
        procedure_ids = self._intent_index.get(intent, [])

        # 如果没有精确匹配，尝试模糊匹配
        if not procedure_ids:
            for key, ids in self._intent_index.items():
                if intent in key or key in intent:
                    procedure_ids.extend(ids)

        procedures = [self._procedures[pid] for pid in set(procedure_ids) if pid in self._procedures]
        procedures = [p for p in procedures if p.is_active]

        # 按成功率排序
        procedures.sort(key=lambda p: p.get_success_rate(), reverse=True)

        return procedures[:limit]

    def find_by_tags(self, tags: list[str]) -> list[Procedure]:
        """按标签查找流程"""
        matching_ids = set()
        for tag in tags:
            tag = tag.lower()
            matching_ids.update(self._tag_index.get(tag, []))

        procedures = [self._procedures[pid] for pid in matching_ids if pid in self._procedures]
        return [p for p in procedures if p.is_active]

    def update_procedure(self, procedure_id: str, updates: dict[str, Any]) -> bool:
        """更新流程"""
        with self._lock:
            if procedure_id not in self._procedures:
                return False

            procedure = self._procedures[procedure_id]
            for key, value in updates.items():
                if hasattr(procedure, key):
                    setattr(procedure, key, value)

            procedure.updated_at = time.time()
            self._save_procedure(procedure)
            return True

    def delete_procedure(self, procedure_id: str) -> bool:
        """删除流程"""
        with self._lock:
            if procedure_id not in self._procedures:
                return False

            del self._procedures[procedure_id]

            # 从索引中移除
            for key in list(self._intent_index.keys()):
                if procedure_id in self._intent_index[key]:
                    self._intent_index[key].remove(procedure_id)

            for key in list(self._tag_index.keys()):
                if procedure_id in self._tag_index[key]:
                    self._tag_index[key].remove(procedure_id)

            # 删除文件
            file_path = self._storage_dir / f"{procedure_id}.json"
            if file_path.exists():
                file_path.unlink()

            return True

    def list_procedures(
        self,
        active_only: bool = True,
        sort_by: str = "usage_count"
    ) -> list[Procedure]:
        """
        列出所有流程

        Args:
            active_only: 仅显示激活的流程
            sort_by: 排序字段（usage_count/success_rate/updated_at）

        Returns:
            流程列表
        """
        procedures = list(self._procedures.values())

        if active_only:
            procedures = [p for p in procedures if p.is_active]

        # 排序
        if sort_by == "usage_count":
            procedures.sort(key=lambda p: p.usage_count, reverse=True)
        elif sort_by == "success_rate":
            procedures.sort(key=lambda p: p.get_success_rate(), reverse=True)
        elif sort_by == "updated_at":
            procedures.sort(key=lambda p: p.updated_at, reverse=True)

        return procedures

    def get_statistics(self) -> dict[str, Any]:
        """获取统计信息"""
        total = len(self._procedures)
        active = len([p for p in self._procedures.values() if p.is_active])
        total_usage = sum(p.usage_count for p in self._procedures.values())
        total_success = sum(p.success_count for p in self._procedures.values())

        return {
            "total_procedures": total,
            "active_procedures": active,
            "inactive_procedures": total - active,
            "total_usage": total_usage,
            "total_success": total_success,
            "overall_success_rate": total_success / total_usage if total_usage > 0 else 0,
            "unique_intents": len(self._intent_index),
            "unique_tags": len(self._tag_index),
        }


# 全局实例
_library_instance: ProcedureLibrary | None = None

def get_procedure_library() -> ProcedureLibrary:
    """获取全局流程库实例"""
    global _library_instance
    if _library_instance is None:
        _library_instance = ProcedureLibrary()
    return _library_instance
