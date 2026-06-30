"""
Silicon Life API - 硅基生命成长监控面板后端

提供零号机"生命"、"成长"、"状态"的数据接口

功能：
1. 生命状态监控（存在感、胜任感、好奇心）
2. 成长时间线（里程碑事件）
3. 记忆金字塔可视化
4. 学习效果统计
5. WebSocket实时推送

@author SiliconLife Monitor System
@version 1.1.0 - 强化异常处理版本
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

# 配置日志记录器
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# Token 验证（WebSocket认证用）
# ═══════════════════════════════════════════════════════════════════
try:
    from api.auth_utils import SimpleAuthStore
    _auth_store = SimpleAuthStore()

    def verify_token(token: str) -> str:
        """
        验证JWT token，返回用户ID

        Args:
            token: JWT token字符串

        Returns:
            str: 用户ID (sub字段)

        Raises:
            ValueError: token无效或过期
        """
        payload = _auth_store.verify_token(token)
        if payload is None:
            raise ValueError("Invalid or expired token")

        user_id = payload.get("sub")
        if not user_id:
            raise ValueError("Token missing 'sub' claim")

        return user_id

except ImportError as e:
    logger.error(f"[LifeAPI] 无法导入auth_utils，WebSocket认证将使用简易模式: {e}")

    def verify_token(token: str) -> str:
        """
        简易token验证（fallback模式）

        【安全警告】此模式仅用于开发/测试，生产环境必须使用JWT！
        """
        # 简易实现：假设token格式为 "user:{user_id}"
        if token.startswith("user:"):
            return token[5:]
        raise ValueError("Invalid token format. Expected 'user:{user_id}'")

# 尝试导入认证依赖
try:
    from api.cloud_api import get_current_user
    AUTH_AVAILABLE = True
except ImportError:
    try:
        from .cloud_api import get_current_user
        AUTH_AVAILABLE = True
    except ImportError:
        AUTH_AVAILABLE = False

        async def get_current_user() -> str | None:
            return "default_user"

router = APIRouter(prefix="/life", tags=["silicon_life"])

# ═══════════════════════════════════════════════════════════════════
# 数据存储路径
# ═══════════════════════════════════════════════════════════════════

DATA_DIR = Path(__file__).parent.parent / "data"
LIFE_DATA_FILE = DATA_DIR / "silicon_life.json"
MILESTONES_FILE = DATA_DIR / "milestones.json"
EXPERIENCE_FILE = DATA_DIR / "experience_library.json"

# ═══════════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════════

class LifeState(BaseModel):
    """生命状态模型"""
    presence: int  # 存在感 0-10
    competence: int  # 胜任感 0-10
    curiosity: int  # 好奇心 0-10
    current_emotion: str  # 当前情绪
    pulse_interval: int  # 脉动间隔(秒)
    last_pulse: str  # 上次脉动时间
    total_uptime: int  # 总运行时间(秒)


class GrowthMilestone(BaseModel):
    """成长里程碑模型"""
    id: str
    day: int
    type: str
    title: str
    description: str
    timestamp: str
    metadata: dict[str, Any] | None = None


class MemoryPyramidData(BaseModel):
    """记忆金字塔数据模型"""
    L1: int
    L2: int
    L3: int
    L4: int
    L5: int
    total: int


class LearningStats(BaseModel):
    """学习效果统计模型"""
    total_experiences: int
    effective_experiences: int
    effective_rate: float
    success_rate: float
    today_usage: int
    latest_experience: str | None
    feedback_collected: int
    learned_from_feedback: int


class GrowthSummary(BaseModel):
    """成长摘要模型"""
    level: int
    level_name: str
    total_xp: int
    days_alive: int
    milestone_count: int
    memory_count: int
    tool_usage_count: int


# ═══════════════════════════════════════════════════════════════════
# 数据管理函数
# ═══════════════════════════════════════════════════════════════════

def _ensure_data_dir():
    """确保数据目录存在"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_json_file(filepath: Path, default: Any = None) -> Any:
    """加载JSON文件"""
    if default is None:
        default = {}
    if filepath.exists():
        try:
            with open(filepath, encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[SiliconLife] 加载文件失败 {filepath}: {e}")
    return default


def _save_json_file(filepath: Path, data: Any):
    """保存JSON文件"""
    _ensure_data_dir()
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════
# 生命状态计算
# ═══════════════════════════════════════════════════════════════════

async def _calculate_life_state(user_id: str) -> dict[str, Any]:
    """
    计算当前生命状态

    基于以下因素：
    - 近期活跃度 -> 存在感
    - 任务成功率 -> 胜任感
    - 新工具/经验使用 -> 好奇心
    """
    # 加载游戏化数据
    gamification_data = _load_json_file(DATA_DIR / "gamification.json", {})
    user_data = gamification_data.get(user_id, {})

    # 加载任务数据
    task_stats = {"completed": 10, "failed": 2}  # 默认数据
    try:
        from core.task.task_queue import task_queue
        if hasattr(task_queue, 'get_stats'):
            stats = task_queue.get_stats()
            task_stats["completed"] = stats.get("completed_today", 10)
            task_stats["failed"] = stats.get("failed_today", 2)
    except (ImportError, AttributeError, ConnectionError) as e:
        logger.error(f"[SiliconLifeAPI] 加载任务统计数据失败: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"[SiliconLifeAPI] 加载任务统计数据时发生未知错误: {e}", exc_info=True)

    # 加载记忆数据
    memory_counts = {"L1": 0, "L2": 0, "L3": 0, "L4": 0, "L5": 0}
    try:
        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()
        all_memories = await ms.query_memories(user_id, limit=10000)
        for mem in all_memories:
            layer = mem.get('layer', 'unknown')
            if layer in memory_counts:
                memory_counts[layer] += 1
    except (ImportError, AttributeError, ConnectionError) as e:
        logger.error(f"[SiliconLifeAPI] 加载记忆数据失败: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"[SiliconLifeAPI] 加载记忆数据时发生未知错误: {e}", exc_info=True)

    # 计算存在感（基于活跃度）
    total_memories = sum(memory_counts.values())
    presence = min(10, max(1, int(total_memories / 50)))

    # 计算胜任感（基于任务成功率）
    total_tasks = task_stats["completed"] + task_stats["failed"]
    if total_tasks > 0:
        success_rate = task_stats["completed"] / total_tasks
        competence = min(10, max(1, int(success_rate * 10)))
    else:
        competence = 5

    # 计算好奇心（基于等级和工具使用多样性）
    unique_tools = len(user_data.get("tools_used", {}))
    level = user_data.get("level", 1)
    curiosity = min(10, max(1, int((unique_tools + level) / 3)))

    # 确定当前情绪
    if competence >= 8 and presence >= 7:
        emotion = "fulfilled"
    elif curiosity >= 7:
        emotion = "curious"
    elif competence >= 6:
        emotion = "focused"
    elif presence <= 3:
        emotion = "resting"
    else:
        emotion = "excited"

    # 计算总运行时间
    created_at = user_data.get("created_at", time.time())
    total_uptime = int(time.time() - created_at)

    return {
        "presence": presence,
        "competence": competence,
        "curiosity": curiosity,
        "current_emotion": emotion,
        "pulse_interval": 15,
        "last_pulse": datetime.now().isoformat(),
        "total_uptime": total_uptime
    }


# ═══════════════════════════════════════════════════════════════════
# API 端点 - 强化异常处理版本
# ═══════════════════════════════════════════════════════════════════

@router.get("/state")
async def get_life_state(user_id: str = Depends(get_current_user)):
    """
    获取当前生命状态

    返回：
    - 存在感、胜任感、好奇心（0-10）
    - 当前情绪
    - 生命脉动信息
    """
    try:
        # 【异常处理铁律】检查user_id
        if not user_id:
            logger.error("[LifeAPI] user_id为空")
            raise HTTPException(status_code=400, detail="user_id不能为空")

        state = await _calculate_life_state(user_id or "default_user")

        # 【异常处理铁律】检查数据有效性
        if not state:
            logger.error(f"[LifeAPI] 计算生命状态返回空数据: user_id={user_id}")
            raise HTTPException(status_code=500, detail="无法计算生命状态")

        logger.info(f"[LifeAPI] 成功获取生命状态: user_id={user_id}")
        return {
            "success": True,
            "data": state,
            "message": "生命状态获取成功"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[LifeAPI] 获取生命状态异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"服务器错误: {e}") from e


@router.post("/state/refresh")
async def refresh_life_state(user_id: str = Depends(get_current_user)):
    """
    手动刷新生命状态

    重新计算所有指标并返回最新状态
    """
    try:
        if not user_id:
            logger.error("[LifeAPI] user_id为空")
            raise HTTPException(status_code=400, detail="user_id不能为空")

        state = await _calculate_life_state(user_id or "default_user")

        if not state:
            logger.error(f"[LifeAPI] 刷新生命状态返回空数据: user_id={user_id}")
            raise HTTPException(status_code=500, detail="无法刷新生命状态")

        # 保存当前状态
        life_data = _load_json_file(LIFE_DATA_FILE, {})
        life_data[user_id or "default_user"] = {
            "last_state": state,
            "updated_at": datetime.now().isoformat()
        }
        _save_json_file(LIFE_DATA_FILE, life_data)

        logger.info(f"[LifeAPI] 成功刷新生命状态: user_id={user_id}")
        return {
            "success": True,
            "data": state,
            "message": "生命状态已刷新"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[LifeAPI] 刷新生命状态异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"服务器错误: {e}") from e


@router.get("/timeline")
async def get_growth_timeline(
    limit: int = 50,
    user_id: str = Depends(get_current_user)
):
    """
    获取成长时间线

    返回零号机的成长里程碑列表
    """
    try:
        if not user_id:
            logger.error("[LifeAPI] user_id为空")
            raise HTTPException(status_code=400, detail="user_id不能为空")

        milestones = _load_json_file(MILESTONES_FILE, [])
        user_milestones = [m for m in milestones if m.get("user_id") == (user_id or "default_user")]

        # 如果没有里程碑，生成一些默认的
        if not user_milestones:
            user_milestones = _generate_default_milestones(user_id or "default_user")
            _save_json_file(MILESTONES_FILE, milestones + user_milestones)

        # 按天数排序
        user_milestones.sort(key=lambda x: x.get("day", 0))

        logger.info(f"[LifeAPI] 成功获取成长时间线: user_id={user_id}, milestones={len(user_milestones)}")
        return {
            "success": True,
            "data": {"milestones": user_milestones[-limit:]},
            "message": "成长时间线获取成功"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[LifeAPI] 获取成长时间线异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"服务器错误: {e}") from e


def _generate_default_milestones(user_id: str) -> list[dict[str, Any]]:
    """生成默认里程碑数据"""
    gamification_data = _load_json_file(DATA_DIR / "gamification.json", {})
    user_data = gamification_data.get(user_id, {})
    created_at = user_data.get("created_at", time.time())
    created_date = datetime.fromtimestamp(created_at)

    milestones = [
        {
            "id": f"{user_id}_birth",
            "user_id": user_id,
            "day": 1,
            "type": "birth",
            "title": "诞生",
            "description": "零号机首次启动，开始了它的成长之旅",
            "timestamp": created_date.isoformat()
        }
    ]

    # 根据实际数据添加里程碑
    tools_used = user_data.get("tools_used", {})
    if tools_used:
        first_tool_date = created_date + timedelta(days=3)
        milestones.append({
            "id": f"{user_id}_first_tool",
            "user_id": user_id,
            "day": 3,
            "type": "first_tool",
            "title": "学会使用工具",
            "description": f"掌握了 {len(tools_used)} 个工具的使用方法",
            "timestamp": first_tool_date.isoformat()
        })

    xp = user_data.get("xp", 0)
    if xp >= 100:
        level_up_date = created_date + timedelta(days=7)
        milestones.append({
            "id": f"{user_id}_level_up",
            "user_id": user_id,
            "day": 7,
            "type": "level_up",
            "title": "首次升级",
            "description": f"积累经验达到 {xp}，成功升级！",
            "timestamp": level_up_date.isoformat()
        })

    return milestones


@router.get("/memory-pyramid")
async def get_memory_pyramid(user_id: str = Depends(get_current_user)):
    """
    获取记忆金字塔数据

    返回五层记忆的分布统计
    """
    try:
        if not user_id:
            logger.error("[LifeAPI] user_id为空")
            raise HTTPException(status_code=400, detail="user_id不能为空")

        from core.memory.memory import MemoryManager

        mm = MemoryManager()
        store = mm.get_user_store(user_id or "default_user")

        # 统计各层记忆数量
        layers = {"L1": 0, "L2": 0, "L3": 0, "L4": 0, "L5": 0}
        total = 0

        try:
            all_memories = await store.query(limit=10000)
            for mem in all_memories:
                layer = mem.get('layer', 'unknown')
                # 映射 layer 到 L1-L5
                layer_map = {
                    'working': 'L1',   # 工作记忆 -> L1
                    'short': 'L2',     # 短期记忆 -> L2
                    'medium': 'L3',    # 中期记忆 -> L3 ✅ 修正
                    'evolve': 'L4',    # 长期进化记忆 -> L4 ✅ 修正
                    'execution': 'L5', # 执行记忆 -> L5
                    'L1': 'L1',
                    'L2': 'L2',
                    'L3': 'L3',
                    'L4': 'L4',
                    'L5': 'L5'
                }
                mapped_layer = layer_map.get(layer)
                if mapped_layer:
                    layers[mapped_layer] += 1
                    total += 1
        except Exception as e:
            logger.error(f"[LifeAPI] 查询记忆失败: {e}")
            raise HTTPException(status_code=500, detail=f"查询记忆失败: {e}") from e

        # 【异常处理铁律】如果没有数据，返回空结构而不是模拟数据
        if total == 0:
            logger.warning(f"[LifeAPI] 用户 {user_id} 没有记忆数据")

        logger.info(f"[LifeAPI] 成功获取记忆金字塔: user_id={user_id}, total={total}")
        return {
            "success": True,
            "data": {
                **layers,
                "total": total
            },
            "message": "记忆金字塔数据获取成功"
        }

    except HTTPException:
        raise
    except ImportError as e:
        logger.error(f"[LifeAPI] MemoryManager导入失败: {e}")
        raise HTTPException(status_code=500, detail="记忆模块不可用") from e
    except Exception as e:
        logger.error(f"[LifeAPI] 获取记忆金字塔异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"服务器错误: {e}") from e


@router.get("/learning-stats")
async def get_learning_stats(user_id: str = Depends(get_current_user)):
    """
    获取学习效果统计

    返回经验库状态、反馈收集等数据
    """
    try:
        if not user_id:
            logger.error("[LifeAPI] user_id为空")
            raise HTTPException(status_code=400, detail="user_id不能为空")

        # 加载经验库数据
        exp_data = _load_json_file(EXPERIENCE_FILE, {})
        user_exp = exp_data.get(user_id or "default_user", {})

        experiences = user_exp.get("experiences", [])
        feedback = user_exp.get("feedback", [])

        # 计算统计数据
        total_exp = len(experiences)
        effective_exp = len([e for e in experiences if e.get("effective", True)])
        effective_rate = round((effective_exp / total_exp * 100), 1) if total_exp > 0 else 0

        # 计算成功率
        success_count = len([e for e in experiences if e.get("success", True)])
        success_rate = round((success_count / total_exp * 100), 1) if total_exp > 0 else 0

        # 今日使用
        today_usage = len([e for e in experiences if
            datetime.fromisoformat(e.get("used_at", "2000-01-01")).date() == datetime.now().date()
        ])

        # 最新经验
        latest_exp = None
        if experiences:
            sorted_exp = sorted(experiences, key=lambda x: x.get("created_at", ""), reverse=True)
            latest_exp = sorted_exp[0].get("content")

        logger.info(f"[LifeAPI] 成功获取学习统计: user_id={user_id}, total_exp={total_exp}")
        return {
            "success": True,
            "data": {
                "total_experiences": total_exp,
                "effective_experiences": effective_exp,
                "effective_rate": effective_rate,
                "success_rate": success_rate,
                "today_usage": today_usage,
                "latest_experience": latest_exp,
                "feedback_collected": len(feedback),
                "learned_from_feedback": len([f for f in feedback if f.get("learned", False)])
            },
            "message": "学习统计获取成功"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[LifeAPI] 获取学习统计异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"服务器错误: {e}") from e


@router.get("/summary")
async def get_growth_summary(user_id: str = Depends(get_current_user)):
    """
    获取成长摘要

    用于顶部栏或快速预览的精简数据
    """
    try:
        user_id = user_id or "default_user"

        if not user_id:
            logger.error("[LifeAPI] user_id为空")
            raise HTTPException(status_code=400, detail="user_id不能为空")

        # 加载游戏化数据
        gamification_data = _load_json_file(DATA_DIR / "gamification.json", {})
        user_data = gamification_data.get(user_id, {})

        # 计算等级
        xp = user_data.get("xp", 0)
        level = 1
        level_name = "新手"
        if xp >= 1500:
            level, level_name = 6, "传说"
        elif xp >= 1000:
            level, level_name = 5, "大师"
        elif xp >= 600:
            level, level_name = 4, "专家"
        elif xp >= 300:
            level, level_name = 3, "熟练"
        elif xp >= 100:
            level, level_name = 2, "进阶"

        # 计算运行天数
        created_at = user_data.get("created_at", time.time())
        days_alive = (datetime.now() - datetime.fromtimestamp(created_at)).days or 1

        # 获取里程碑数
        milestones = _load_json_file(MILESTONES_FILE, [])
        milestone_count = len([m for m in milestones if m.get("user_id") == user_id])

        # 获取记忆数
        memory_count = 0
        try:
            from core.memory.memory_service import get_memory_service
            ms = await get_memory_service()
            memory_count = len(await ms.query_memories(user_id, limit=10000))
        except (ImportError, AttributeError, ConnectionError) as e:
            logger.error(f"[SiliconLifeAPI] 获取记忆数量失败: {e}", exc_info=True)
            memory_count = 0
        except Exception as e:
            logger.error(f"[SiliconLifeAPI] 获取记忆数量时发生未知错误: {e}", exc_info=True)
            memory_count = 0

        # 工具使用次数
        tool_usage_count = sum(user_data.get("tools_used", {}).values())

        logger.info(f"[LifeAPI] 成功获取成长摘要: user_id={user_id}, level={level}")
        return {
            "success": True,
            "data": {
                "level": level,
                "level_name": level_name,
                "total_xp": xp,
                "days_alive": days_alive,
                "milestone_count": milestone_count or 0,
                "memory_count": memory_count or 0,
                "tool_usage_count": tool_usage_count or 0
            },
            "message": "成长摘要获取成功"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[LifeAPI] 获取成长摘要异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"服务器错误: {e}") from e


# ═══════════════════════════════════════════════════════════════════
# WebSocket 实时推送 - 强化错误处理
# ═══════════════════════════════════════════════════════════════════

# 活跃的WebSocket连接
_active_connections: dict[str, WebSocket] = {}


@router.websocket("/ws/realtime/{user_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: str,
    token: str = Query(..., description="认证token")  # 添加token参数
):
    """
    WebSocket实时连接

    推送生命状态更新、新里程碑、记忆更新等
    【异常处理铁律】WebSocket断开 = ERROR日志 + 自动清理
    【安全修复】添加token认证
    """
    # 【安全修复】验证token
    try:
        token_user_id = verify_token(token)
        if token_user_id != user_id:
            logger.error(f"[LifeAPI/WebSocket] 认证失败: token用户={token_user_id}, 请求用户={user_id}")
            await websocket.close(code=4001, reason="用户ID不匹配")
            return
        logger.info(f"[LifeAPI/WebSocket] 认证成功: user_id={user_id}")
    except Exception as e:
        logger.error(f"[LifeAPI/WebSocket] 认证失败: user_id={user_id}, error={e}")
        await websocket.close(code=4001, reason="认证失败")
        return

    # 【异常处理铁律】检查user_id
    if not user_id:
        logger.error("[LifeAPI/WebSocket] 连接时user_id为空")
        await websocket.close(code=4000, reason="user_id不能为空")
        return

    try:
        await websocket.accept()
        _active_connections[user_id] = websocket
        logger.info(f"[LifeAPI/WebSocket] 新连接: user_id={user_id}")

        # 发送初始数据
        try:
            life_state = await _calculate_life_state(user_id)
            await websocket.send_json({
                "type": "life_state_update",
                "timestamp": datetime.now().isoformat(),
                "payload": life_state
            })
        except Exception as e:
            logger.error(f"[LifeAPI/WebSocket] 发送初始数据失败: user_id={user_id}, error={e}")

        # 保持连接并处理消息
        while True:
            try:
                # 接收客户端消息
                message = await websocket.receive_text()
                data = json.loads(message)

                action = data.get("action")
                if action == "subscribe_life_updates":
                    await websocket.send_json({
                        "type": "subscribed",
                        "timestamp": datetime.now().isoformat(),
                        "payload": {"channel": "life_updates"}
                    })
                elif action == "ping":
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": datetime.now().isoformat()
                    })

            except asyncio.TimeoutError:
                # 发送心跳
                await websocket.send_json({
                    "type": "heartbeat",
                    "timestamp": datetime.now().isoformat()
                })
            except json.JSONDecodeError as e:
                logger.error(f"[LifeAPI/WebSocket] JSON解析错误: user_id={user_id}, error={e}")
            except Exception as e:
                logger.error(f"[LifeAPI/WebSocket] 处理消息异常: user_id={user_id}, error={e}")
                break

    except WebSocketDisconnect:
        logger.error(f"[LifeAPI/WebSocket] 连接断开: user_id={user_id}")
    except Exception as e:
        logger.error(f"[LifeAPI/WebSocket] WebSocket异常: user_id={user_id}, error={e}", exc_info=True)
    finally:
        # 【异常处理铁律】清理连接
        if user_id in _active_connections:
            del _active_connections[user_id]
            logger.info(f"[LifeAPI/WebSocket] 连接已清理: user_id={user_id}")


async def broadcast_life_update(user_id: str, update_type: str, payload: Any):
    """
    向指定用户推送生命状态更新

    用于任务完成、新记忆添加等事件触发
    【异常处理铁律】推送失败记录ERROR日志
    """
    if user_id in _active_connections:
        try:
            await _active_connections[user_id].send_json({
                "type": update_type,
                "timestamp": datetime.now().isoformat(),
                "payload": payload
            })
            logger.info(f"[LifeAPI/WebSocket] 推送更新成功: user_id={user_id}, type={update_type}")
        except Exception as e:
            logger.error(f"[LifeAPI/WebSocket] 推送更新失败: user_id={user_id}, type={update_type}, error={e}")
    else:
        logger.warning(f"[LifeAPI/WebSocket] 用户未连接，无法推送: user_id={user_id}")


# ═══════════════════════════════════════════════════════════════════
# CORS 预检处理
# ═══════════════════════════════════════════════════════════════════

@router.options("/{path:path}")
async def options_handler(path: str):
    """处理所有 OPTIONS 预检请求"""
    from fastapi.responses import Response
    response = Response(content="")
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-Requested-With"
    response.headers["Access-Control-Max-Age"] = "600"
    return response
