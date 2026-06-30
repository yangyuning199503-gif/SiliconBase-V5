#!/usr/bin/env python3
"""
GamificationBridge - 游戏化经验值更新桥接器
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
从 agent_loop.py 抽取的任务完成经验值计算与发放逻辑。
"""

import time
from typing import Any

from core.logger import logger


def _get_sync_manager():
    from ..sync.realtime_sync import get_realtime_sync_manager
    return get_realtime_sync_manager()


async def update_gamification_async(
    user_id: str | None,
    session_id: str,
    execution_history: list[dict],
    logger_instance: Any = None,
) -> None:
    """任务完成后更新用户游戏化数据（经验值、等级）。

    Args:
        user_id: 用户ID（可能为None）
        session_id: 会话ID
        execution_history: 执行历史（用于计算步数）
        logger_instance: 可选的日志记录器（默认使用 core.logger）
    """
    _logger = logger_instance or logger
    try:
        from api.gamification_api import (
            _calculate_level,
            _load_gamification_data_async,
            _save_gamification_data_async,
        )

        user_id_for_gamification = user_id if user_id else (
            session_id if session_id and session_id != "console" else "default_user"
        )

        data = await _load_gamification_data_async()
        if user_id_for_gamification not in data:
            data[user_id_for_gamification] = {
                "level": 1, "xp": 0, "total_xp_earned": 0,
                "tools_used": {}, "categories_unlocked": [],
                "achievements": [], "created_at": time.time(),
                "last_active": time.time()
            }

        user_data = data[user_id_for_gamification]

        # 计算经验值（基础20 + 每步5，最多50额外）
        steps_count = len([h for h in execution_history if h.get("tool")])
        xp_earned = 20 + min(steps_count * 5, 50)

        # 更新经验值
        old_level = _calculate_level(user_data["xp"])
        user_data["xp"] += xp_earned
        user_data["total_xp_earned"] += xp_earned
        user_data["last_active"] = time.time()
        new_level = _calculate_level(user_data["xp"])

        # 保存数据
        await _save_gamification_data_async(data)

        # 发送事件
        sync = _get_sync_manager()
        sync.emit_event("xp_earned", session_id or user_id_for_gamification, {
            "xp_earned": xp_earned,
            "source": "task_complete",
            "total_xp": user_data["xp"],
            "level_up": new_level > old_level,
            "new_level": new_level if new_level > old_level else None
        })

        if new_level > old_level:
            sync.emit_event("level_up", session_id or user_id_for_gamification, {
                "old_level": old_level,
                "new_level": new_level
            })

        _logger.info(
            f"[Gamification] 任务完成，用户 {user_id_for_gamification} 获得 {xp_earned} XP"
        )

    except Exception as e:
        _logger.error(f"[SILENT_FAILURE_BLOCKED] [Gamification] 记录任务完成经验值失败: {e}")
