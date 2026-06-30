"""
Metrics API - 系统指标和统计接口
"""
import logging
import threading
import time
from typing import Any

from fastapi import APIRouter, Depends

# logger 已在上面定义

logger = logging.getLogger(__name__)

# 尝试导入 get_current_user，如果不可用则使用默认实现
try:
    from api.cloud_api import get_current_user
except ImportError:
    async def get_current_user(): return "default"

router = APIRouter(
    prefix="/metrics",
    tags=["metrics"],
    dependencies=[Depends(get_current_user)]
)

# ============================================================================
# 任务统计计数器（全局）
# ============================================================================
_task_stats = {
    "completed_today": 0,
    "failed_today": 0,
    "last_reset_date": None
}
_task_stats_lock = threading.Lock()

def _ensure_daily_reset():
    """确保每日重置计数器"""
    import datetime
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    with _task_stats_lock:
        if _task_stats["last_reset_date"] != today:
            _task_stats["completed_today"] = 0
            _task_stats["failed_today"] = 0
            _task_stats["last_reset_date"] = today

def increment_task_completed():
    """增加完成任务计数"""
    _ensure_daily_reset()
    with _task_stats_lock:
        _task_stats["completed_today"] += 1

def increment_task_failed():
    """增加失败任务计数"""
    _ensure_daily_reset()
    with _task_stats_lock:
        _task_stats["failed_today"] += 1

# 尝试导入 psutil，如果不可用则使用模拟数据
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logger.warning("psutil not available, using mock data for system metrics")


@router.get("/system")
async def get_system_metrics() -> dict[str, Any]:
    """
    获取系统资源使用情况

    Returns:
        CPU、内存、磁盘使用指标
    """
    try:
        if PSUTIL_AVAILABLE:
            cpu_percent = psutil.cpu_percent(interval=0.5)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            return {
                "success": True,
                "data": {
                    "cpu_percent": cpu_percent,
                    "memory": {
                        "percent": memory.percent,
                        "used": memory.used,
                        "total": memory.total,
                        "available": memory.available
                    },
                    "disk": {
                        "percent": (disk.used / disk.total) * 100,
                        "used": disk.used,
                        "total": disk.total
                    },
                    "timestamp": int(time.time())
                },
                "message": "System metrics retrieved successfully"
            }
        else:
            # 模拟数据
            mock_cpu_percent = 25.5
            return {
                "success": True,
                "data": {
                    "cpu_percent": mock_cpu_percent,
                    "memory": {
                        "percent": 50.0,
                        "used": 4294967296,
                        "total": 8589934592,
                        "available": 4294967296
                    },
                    "disk": {
                        "percent": 50.0,
                        "used": 53687091200,
                        "total": 107374182400
                    },
                    "timestamp": int(time.time())
                },
                "message": "System metrics retrieved successfully (mock data)"
            }
    except Exception as e:
        logger.error(f"Error getting system metrics: {e}")
        return {
            "success": False,
            "data": None,
            "message": f"Error getting system metrics: {str(e)}"
        }


@router.get("/tasks")
async def get_task_metrics(user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    """
    获取任务队列统计

    Returns:
        待处理任务数、当前任务、完成/失败计数
    """
    try:
        from core.task.task_queue import task_queue

        # 确保计数器已重置（按天）
        _ensure_daily_reset()

        # 获取队列统计（优先使用 get_stats 方法）
        queue_stats = {}
        try:
            if hasattr(task_queue, 'get_stats'):
                queue_stats = task_queue.get_stats()
        except Exception as e:
            logger.warning(f"Error getting task queue stats: {e}")

        # 安全获取队列大小
        queue_size = queue_stats.get('queue_size', 0)
        if queue_size == 0:
            try:
                queue_size = task_queue._queue.qsize() if hasattr(task_queue._queue, 'qsize') else 0
            except Exception as e:
                logger.error(f"[MetricsAPI] 获取队列大小失败: {e}", exc_info=True)
                queue_size = -1

        # 获取当前任务（返回对象格式）
        current_task = None
        try:
            current = queue_stats.get('current_task') or task_queue.current_task()
            if current:
                current_task = {
                    "id": getattr(current, 'id', str(current)),
                    "type": getattr(current, 'type', 'unknown'),
                    "status": str(getattr(current, 'status', 'pending'))
                }
        except Exception as e:
            logger.error(f"[MetricsAPI] 获取当前任务失败: {e}", exc_info=True)

        # 计算平均等待时间（基于队列大小估算）
        average_wait_time = 0.0
        try:
            if queue_size > 0:
                # 基于队列大小估算等待时间（每个任务平均5秒）
                average_wait_time = queue_size * 5.0
        except Exception as e:
            logger.error(f"[MetricsAPI] 计算等待时间失败: {e}", exc_info=True)

        # 读取全局统计计数器
        with _task_stats_lock:
            completed_today = _task_stats["completed_today"]
            failed_today = _task_stats["failed_today"]

        return {
            "success": True,
            "data": {
                "queue_size": queue_size,
                "current_task": current_task,
                "completed_today": completed_today,
                "failed_today": failed_today,
                "average_wait_time": average_wait_time,
                "timestamp": int(time.time())
            },
            "message": "Task metrics retrieved successfully"
        }
    except ImportError as e:
        logger.warning(f"Task queue not available: {e}")
        return {
            "success": True,
            "data": {
                "queue_size": 0,
                "current_task": None,
                "completed_today": 0,
                "failed_today": 0,
                "average_wait_time": 0.0,
                "timestamp": int(time.time())
            },
            "message": "Task queue not available"
        }
    except Exception as e:
        logger.error(f"Error getting task metrics: {e}")
        return {
            "success": False,
            "data": {
                "queue_size": 0,
                "current_task": None,
                "completed_today": 0,
                "failed_today": 0,
                "average_wait_time": 0.0,
                "timestamp": int(time.time())
            },
            "message": f"Error getting task metrics: {str(e)}"
        }


@router.get("/memory")
async def get_memory_metrics(user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    """
    获取记忆库统计

    Args:
        user_id: 用户ID

    Returns:
        记忆业务指标：短期/长期/进化记忆数量，向量条目数，最后清理时间
    """
    # 前端期望的业务指标结构
    stats = {
        "short_term_count": 0,
        "long_term_count": 0,
        "evolution_count": 0,
        "vector_entries": 0,
        "last_cleanup": None,
        "user_id": user_id
    }

    try:
        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()

        # 查询记忆统计
        try:
            all_memories = await ms.query_memories(user_id, limit=10000)

            # 按层级统计转换为业务指标
            for mem in all_memories:
                layer = mem.get('layer', 'unknown')
                mem.get('mem_type', 'unknown')

                # 统计各层级数量
                if layer == 'short':
                    stats["short_term_count"] += 1
                elif layer == 'long':
                    stats["long_term_count"] += 1
                elif layer == 'evolve':
                    stats["evolution_count"] += 1

                # 统计向量条目（假设每个记忆对应一个向量条目）
                if mem.get('vectorized', False) or mem.get('embedding'):
                    stats["vector_entries"] += 1

            # 查找最后清理时间（从进化记录中查找）
            try:
                cleanup_records = await ms.query_memories(
                    user_id,
                    layer="evolve",
                    filter_dict={"mem_type": "cleanup"},
                    limit=1,
                )
                if cleanup_records:
                    stats["last_cleanup"] = cleanup_records[0].get('created_at')
            except Exception as e:
                logger.error(f"[MetricsAPI] 查询最后清理时间失败: {e}", exc_info=True)

        except Exception as query_error:
            logger.warning(f"Error querying memories: {query_error}")
            stats["query_error"] = str(query_error)

        return {
            "success": True,
            "data": stats,
            "message": "Memory metrics retrieved successfully"
        }

    except ImportError as e:
        logger.warning(f"Memory manager not available: {e}")
        stats["note"] = "Memory manager not available"
        return {
            "success": True,
            "data": stats,
            "message": "Memory manager not available"
        }
    except Exception as e:
        logger.error(f"Error getting memory metrics: {e}")
        stats["error"] = str(e)
        return {
            "success": False,
            "data": stats,
            "message": f"Error getting memory metrics: {str(e)}"
        }


@router.get("/reflections")
async def get_reflection_metrics(user_id: str = Depends(get_current_user), limit: int = 10) -> dict[str, Any]:
    """
    获取反思统计

    Args:
        user_id: 用户ID
        limit: 返回记录数量限制

    Returns:
        反思记录总数和详情列表
    """
    try:
        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()

        # 查询反思类型的记忆
        reflections_data = await ms.query_memories(user_id, mem_type="reflection", limit=limit)

        # 构建前端期望格式的反思列表
        reflections = []
        for r in reflections_data:
            reflection = {
                "id": r.get('id'),
                "content": r.get('content', ''),
                "created_at": r.get('created_at'),
                # 前端期望的 scene 字段（从 metadata 或 scene 字段获取）
                "scene": r.get('scene') or r.get('metadata', {}).get('scene', ''),
                # 前端期望的 rating 字段（从 value_assessment 或 rating 字段获取）
                "rating": r.get('rating') or r.get('value_assessment', {}).get('score', 0)
            }
            reflections.append(reflection)

        return {
            "success": True,
            "data": {
                "total": len(reflections),
                "reflections": reflections
            },
            "message": "Reflection metrics retrieved successfully"
        }

    except ImportError as e:
        logger.warning(f"Memory manager not available: {e}")
        return {
            "success": True,
            "data": {
                "total": 0,
                "reflections": []
            },
            "message": "Memory manager not available"
        }
    except Exception as e:
        logger.error(f"Error getting reflection metrics: {e}")
        return {
            "success": False,
            "data": {
                "total": 0,
                "reflections": []
            },
            "message": f"Error getting reflection metrics: {str(e)}"
        }
