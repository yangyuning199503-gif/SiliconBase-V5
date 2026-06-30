"""
WeakConnectionBridge - 弱连接触发桥接器
从 agent_loop.py 抽取的 Daily 模式弱连接主动服务逻辑。
"""

from typing import Any

from core.logger import logger


def trigger_weak_connection(
    work_mode: str,
    working_memory: Any,
    loop_state: Any | None = None,
    agent_loop_hooks: Any | None = None,
    hook_ctx: Any | None = None,
    perception_manager: Any | None = None,
) -> None:
    """同步版：Daily 模式下检查并触发弱连接主动服务。"""
    if work_mode != "daily":
        logger.debug("[P2断裂点#5] Focus模式：弱连接已关闭，专注执行")
        return

    try:
        from core.work_mode_manager import WorkMode, get_work_mode_manager
        mode_manager = get_work_mode_manager()
        if mode_manager.get_current_mode() != WorkMode.DAILY:
            return

        from core.weak_connection import get_weak_connection_engine
        get_weak_connection_engine()

        # 获取环境感知数据（如果可用）
        if perception_manager is not None:
            try:
                perception_data = perception_manager.get_current_perception()
                logger.debug(
                    f"[P2断裂点#5] 获取环境感知: "
                    f"CPU={getattr(perception_data, 'cpu_percent', 'N/A')}%"
                )
            except Exception as e:
                logger.debug(f"[P2断裂点#5] 获取感知数据失败: {e}")

        should_propose = False
        proposal_reason = ""

        # CPU 检查
        try:
            import psutil
            cpu_percent = psutil.cpu_percent(interval=0.1)
            if cpu_percent > 80:
                should_propose = True
                proposal_reason = f"CPU使用率较高({cpu_percent:.1f}%)，建议优化后台进程"
        except Exception as e:
            logger.error(f"[AgentLoop] 获取系统CPU使用率失败: {e}", exc_info=True)

        # 工作时段结束检查
        try:
            from datetime import datetime
            if datetime.now().hour == 18:
                should_propose = True
                proposal_reason = "工作时间即将结束，建议生成今日总结"
        except Exception as e:
            logger.error(f"[AgentLoop] 获取当前时间失败: {e}", exc_info=True)

        if should_propose and proposal_reason:
            weak_prompt = f"""
【弱连接触发】检测到环境变化，建议主动服务:
- 触发原因: {proposal_reason}
- 行为准则: 主动询问用户是否需要帮助，用友好、自然的语气
- 注意: 这是Daily模式的主动服务特性，体现AI的生命感和温度
"""
            working_memory.insert_system_message(
                weak_prompt, priority="medium",
                category="weak_connection", overwrite=True,
                source="weak_connection"
            )
            logger.info(f"[P2断裂点#5] Daily模式弱连接触发已注入: {proposal_reason}")

            # 语音播报
            if loop_state is not None and getattr(loop_state, "round_count", 0) == 0 and agent_loop_hooks is not None and hook_ctx is not None:
                try:
                    agent_loop_hooks.execute(
                        'on_user_assist',
                        hook_ctx,
                        reason=f"我注意到{proposal_reason}，需要我帮您处理吗？"
                    )
                except Exception as e:
                    logger.debug(f"[P2断裂点#5] 语音播报失败: {e}")
    except Exception as e:
        logger.warning(f"[P2断裂点#5] Daily模式弱连接触发检查失败: {e}")


async def trigger_weak_connection_async(
    work_mode: str,
    working_memory: Any,
) -> None:
    """异步版：Daily 模式下检查并触发弱连接主动服务。"""
    if work_mode != "daily":
        logger.debug("[P2断裂点#5-Async] Focus模式：弱连接已关闭，专注执行")
        return

    try:
        from core.work_mode_manager import WorkMode, get_work_mode_manager
        mode_manager = get_work_mode_manager()
        if mode_manager.get_current_mode() != WorkMode.DAILY:
            return

        from core.weak_connection import get_weak_connection_engine
        get_weak_connection_engine()

        should_propose = False
        proposal_reason = ""

        try:
            import psutil
            cpu_percent = psutil.cpu_percent(interval=0.1)
            if cpu_percent > 80:
                should_propose = True
                proposal_reason = f"CPU使用率较高({cpu_percent:.1f}%)，建议优化后台进程"
        except Exception as e:
            logger.error(f"[AgentLoop-Async] 获取系统CPU使用率失败: {e}", exc_info=True)

        try:
            from datetime import datetime
            if datetime.now().hour == 18:
                should_propose = True
                proposal_reason = "工作时间即将结束，建议生成今日总结"
        except Exception as e:
            logger.error(f"[AgentLoop-Async] 获取当前时间失败: {e}", exc_info=True)

        if should_propose and proposal_reason:
            weak_prompt = f"""
【弱连接触发】检测到环境变化，建议主动服务:
- 触发原因: {proposal_reason}
- 行为准则: 主动询问用户是否需要帮助，用友好、自然的语气
- 注意: 这是Daily模式的主动服务特性，体现AI的生命感和温度
"""
            working_memory.insert_system_message(
                weak_prompt, priority="medium",
                category="weak_connection", overwrite=True,
                source="weak_connection"
            )
            logger.info(f"[P2断裂点#5-Async] Daily模式弱连接触发已注入: {proposal_reason}")
    except Exception as e:
        logger.warning(f"[P2断裂点#5-Async] Daily模式弱连接触发检查失败: {e}")
