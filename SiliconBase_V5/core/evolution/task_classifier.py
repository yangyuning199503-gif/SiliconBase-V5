#!/usr/bin/env python3
"""
任务分类器（TaskClassifier）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
白皮书模块：从 ExplorationEngine 拆出的纯分类职责
职责：无状态、纯分类，返回 TaskClassification 数据契约
约束：
  - 不是单例，可实例化或依赖注入
  - 禁止包含进化/经验/探索逻辑
  - 禁止包含 get_task_stage() 等无价值方法
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskClassification:
    """
    任务分类结果——不可变数据契约
    """
    task_type: str           # 如 file_operation / search / coding / general
    complexity: int          # 1-10
    estimated_steps: int     # 预估步骤数
    required_tools: list[str]
    confidence: float        # 分类置信度 0-1


class TaskClassifier:
    """
    任务分类器——无状态，纯分类

    设计约束：
    - 删除 attempt_count / common_patterns / exploration_history 等进化字段
    - 删除 get_task_stage() 方法（由调用方根据 complexity + confidence 判断）
    """

    def __init__(self) -> None:
        # 内部统计簿记，不暴露给调用方
        self._profile: dict = {}

    def classify(self, instruction: str) -> TaskClassification:
        """
        分类用户指令

        当前实现：基于关键词匹配（保留原有逻辑）
        后续可扩展：轻量级模型分类
        """
        instruction_lower = instruction.lower()

        # 文件操作
        if any(kw in instruction_lower for kw in ("文件", "读取", "写入", "删除", "移动", "复制", "folder", "directory", "file")):
            return TaskClassification(
                task_type="file_operation",
                complexity=3,
                estimated_steps=2,
                required_tools=["read_file", "write_file", "list_directory"],
                confidence=0.85
            )

        # 搜索/研究
        if any(kw in instruction_lower for kw in ("搜索", "查找", "查询", "研究", "调查", "search", "find", "research")):
            return TaskClassification(
                task_type="search",
                complexity=5,
                estimated_steps=4,
                required_tools=["web_search", "read_file", "grep_content"],
                confidence=0.80
            )

        # 编码
        if any(kw in instruction_lower for kw in ("代码", "编程", "写程序", "函数", "class", "coding", "program", "implement")):
            return TaskClassification(
                task_type="coding",
                complexity=7,
                estimated_steps=6,
                required_tools=["read_file", "write_file", "execute_code"],
                confidence=0.85
            )

        # 浏览器/UI 操作
        if any(kw in instruction_lower for kw in ("浏览器", "网页", "点击", "打开页面", "browser", "click", "website")):
            return TaskClassification(
                task_type="browser",
                complexity=6,
                estimated_steps=5,
                required_tools=["browser_navigate", "browser_click", "screenshot"],
                confidence=0.80
            )

        # 数学/推理
        if any(kw in instruction_lower for kw in ("计算", "数学", "公式", "math", "calculate", "equation")):
            return TaskClassification(
                task_type="math",
                complexity=4,
                estimated_steps=2,
                required_tools=["calculate", "execute_code"],
                confidence=0.90
            )

        # 默认：通用对话
        return TaskClassification(
            task_type="general",
            complexity=2,
            estimated_steps=1,
            required_tools=[],
            confidence=0.60
        )

    def update_profile(self, task_type: str, execution_time: float, success: bool) -> None:
        """
        更新内部统计簿记

        注意：此方法只更新本实例的内部统计，不涉及进化/经验逻辑。
        """
        if task_type not in self._profile:
            self._profile[task_type] = {"count": 0, "total_time": 0.0, "successes": 0}
        self._profile[task_type]["count"] += 1
        self._profile[task_type]["total_time"] += execution_time
        if success:
            self._profile[task_type]["successes"] += 1
