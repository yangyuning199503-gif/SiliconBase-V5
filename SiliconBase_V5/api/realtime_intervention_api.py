#!/usr/bin/env python3
"""
实时干预 API - WebSocket 双工通信
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
让用户在任务执行时仍能打字干预，像和真人助手对话一样自然。

【通信模型】
  前端 ←──WebSocket──→ 后端
   ↓                      ↓
  显示执行中 ←───────  任务执行（AgentLoop）
  输入框可用 ←───────  接收干预指令
   ↓                      ↓
  发送干预 ─────────→  调整执行策略
"""

import asyncio
import json
from datetime import datetime

from core.agent.realtime_intervention import ExecutionDelta, realtime_intervention
from core.logger import logger


class InterventionWebSocketHandler:
    """
    WebSocket 干预处理器

    管理前端与执行中任务的双工通信。
    """

    def __init__(self):
        # task_id -> WebSocket connection
        self._active_connections: dict[str, any] = {}

        # 任务状态推送频率控制
        self._last_push_time: dict[str, float] = {}
        self._push_interval = 1.0  # 秒

    async def register_connection(self, task_id: str, websocket):
        """注册 WebSocket 连接"""
        self._active_connections[task_id] = websocket
        logger.info(f"[InterventionWS] 任务 {task_id} WebSocket 连接已注册")

    async def unregister_connection(self, task_id: str):
        """注销 WebSocket 连接"""
        self._active_connections.pop(task_id, None)
        logger.info(f"[InterventionWS] 任务 {task_id} WebSocket 连接已注销")

    async def handle_message(self, task_id: str, message: str, user_id: str = "default"):
        """
        处理前端发来的干预消息

        消息格式:
        {
            "type": "intervention",
            "content": "换个方式试试",
            "emotional_tone": "frustrated"
        }
        """
        try:
            data = json.loads(message)
            msg_type = data.get("type", "chat")
            content = data.get("content", "")
            tone = data.get("emotional_tone", "neutral")

            if msg_type == "intervention":
                # 提交干预
                success = realtime_intervention.submit_intervention(
                    task_id=task_id,
                    user_input=content,
                    emotional_tone=tone
                )

                if success:
                    # 确认收到干预
                    await self._send_to_frontend(task_id, {
                        "type": "intervention_ack",
                        "content": "已收到您的指示",
                        "timestamp": datetime.now().isoformat()
                    })
                else:
                    await self._send_to_frontend(task_id, {
                        "type": "error",
                        "content": "任务不存在或已结束"
                    })

            elif msg_type == "query_progress":
                # 查询进度
                memory = realtime_intervention.get_task_memory(task_id)
                if memory:
                    await self._send_to_frontend(task_id, {
                        "type": "progress_update",
                        "completed_steps": len(memory.completed_steps),
                        "adaptations": len(memory.adaptations),
                        "current_goal": memory.current_goal,
                        "history": [
                            {
                                "type": a.change_type,
                                "reason": a.reason,
                                "preserved": len(a.preserved_work),
                                "discarded": len(a.discarded_work)
                            }
                            for a in memory.adaptations[-5:]  # 最近5次调整
                        ]
                    })

            elif msg_type == "chat":
                # 闲聊消息 - 不影响执行，但会回复
                await self._send_to_frontend(task_id, {
                    "type": "chat_reply",
                    "content": f"我正在忙，但听到了：{content[:50]}...",
                    "executing": True
                })

        except json.JSONDecodeError:
            await self._send_to_frontend(task_id, {
                "type": "error",
                "content": "消息格式错误"
            })

    async def push_execution_status(self, task_id: str, status: dict):
        """
        向推送任务执行状态（由 AgentLoop 调用）

        包含：
        - 当前步骤
        - 执行进度
        - 是否可以干预
        """
        now = asyncio.get_event_loop().time()
        last_push = self._last_push_time.get(task_id, 0)

        # 频率控制
        if now - last_push < self._push_interval:
            return

        self._last_push_time[task_id] = now

        await self._send_to_frontend(task_id, {
            "type": "execution_status",
            "timestamp": datetime.now().isoformat(),
            **status
        })

    async def notify_adaptation(self, task_id: str, delta: "ExecutionDelta"):
        """通知前端执行已调整"""
        await self._send_to_frontend(task_id, {
            "type": "adaptation_applied",
            "change_type": delta.change_type,
            "reason": delta.reason,
            "preserved_count": len(delta.preserved_work),
            "discarded_count": len(delta.discarded_work),
            "message": self._generate_adaptation_message(delta)
        })

    async def _send_to_frontend(self, task_id: str, data: dict):
        """发送消息到前端"""
        ws = self._active_connections.get(task_id)
        if ws:
            try:
                await ws.send(json.dumps(data, ensure_ascii=False))
            except Exception as e:
                logger.error(f"[InterventionWS] 发送消息失败: {e}")

    def _generate_adaptation_message(self, delta: "ExecutionDelta") -> str:
        """生成用户友好的调整通知"""
        change_type_names = {
            "ADJUST_APPROACH": "调整了执行方法",
            "REPLAN": "重新规划了执行步骤",
            "PIVOT": "切换到了新目标",
            "PAUSE": "暂停执行等待确认",
            "CONTINUE": "继续执行"
        }

        change_name = change_type_names.get(delta.change_type, "执行了调整")

        if delta.change_type == "ADJUST_APPROACH":
            return f"{change_name}，之前完成的工作仍然保留。"
        elif delta.change_type == "REPLAN":
            return f"{change_name}，保留了 {len(delta.preserved_work)} 个已完成的步骤。"
        elif delta.change_type == "PIVOT":
            return f"{change_name}，保留了 {len(delta.preserved_work)} 个相关成果。"
        else:
            return change_name


# 全局实例
intervention_ws_handler = InterventionWebSocketHandler()


# ═══════════════════════════════════════════════════════════════
# FastAPI 路由（如果使用 FastAPI）
# ═══════════════════════════════════════════════════════════════

"""
# 在 main.py 中添加：

from fastapi import WebSocket, WebSocketDisconnect
from api.realtime_intervention_api import intervention_ws_handler

@app.websocket("/ws/task/{task_id}")
async def task_execution_websocket(websocket: WebSocket, task_id: str):
    await websocket.accept()
    await intervention_ws_handler.register_connection(task_id, websocket)

    try:
        while True:
            # 接收前端消息
            message = await websocket.receive_text()
            await intervention_ws_handler.handle_message(task_id, message)

    except WebSocketDisconnect:
        await intervention_ws_handler.unregister_connection(task_id)
"""


# ═══════════════════════════════════════════════════════════════
# 与现有系统集成
# ═══════════════════════════════════════════════════════════════

def integrate_with_agent_loop():
    """
    将实时干预集成到 AgentLoop

    需要在 AgentLoop 的以下位置调用：
    1. 任务开始时注册任务
    2. 每轮执行前检查干预
    3. 步骤完成后记录进度
    4. 任务结束时注销任务
    """

    # 这个函数会返回集成指南
    integration_guide = """
    【AgentLoop 集成指南】

    1. 任务开始时（约第 2900 行附近）：

       realtime_intervention.register_task(
           task_id=task.id,
           goal=task.intent.get("raw", ""),
           listener=lambda ctx: on_intervention_received(ctx)
       )

    2. 每轮执行前（主循环开始处）：

       has_intervention, adaptation_type, details = check_and_apply_intervention(
           task_id=task.id,
           current_working_memory=working_memory,
           current_plan=execution_plan
       )

       if has_intervention:
           if adaptation_type == "PAUSE":
               # 暂停处理
               pass
           elif adaptation_type == "ADJUST_APPROACH":
               # 调整方法
               pass
           elif adaptation_type == "PIVOT":
               # 切换目标
               pass

    3. 步骤完成后：

       realtime_intervention.complete_step(task_id, {
           "id": step_id,
           "name": step_name,
           "result": step_result
       })

    4. 任务结束时：

       final_memory = realtime_intervention.unregister_task(task.id)
       # 可以归档 final_memory 到数据库
    """

    return integration_guide
