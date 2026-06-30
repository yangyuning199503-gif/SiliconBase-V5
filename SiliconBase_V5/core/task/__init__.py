"""task module - SiliconBase V5

Contains task management modules for:
- completion_analyzer: Task completion detection
- pause_manager: Task pause and resume functionality
- long_running_manager: Long-running task management
"""

# Re-export from submodules for convenience
import contextlib

__all__ = [
    "CompletionScore",
    "TaskAnalysisResult",
    "TaskCompletionAnalyzer",
    "TaskType",
    "check_task_completed",
    "get_task_completion_analyzer",
    "increment_force_continue_count",
    "is_long_task",
    "pause_task_with_sync",
    "register_long_task_callbacks",
]

with contextlib.suppress(ImportError):
    from .completion_analyzer import (
        CompletionScore,
        TaskAnalysisResult,
        TaskCompletionAnalyzer,
        TaskType,
        check_task_completed,
        get_task_completion_analyzer,
        increment_force_continue_count,
    )

with contextlib.suppress(ImportError):
    from .pause_manager import (
        is_long_task,
        pause_task_with_sync,
        register_long_task_callbacks,
    )
