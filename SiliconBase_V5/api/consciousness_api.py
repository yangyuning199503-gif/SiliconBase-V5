"""
硅基生命意识API
获取生命体征、自发行动等
"""
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

try:
    from core.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

try:
    from api.cloud_api import get_current_user
    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False
    async def get_current_user():
        return "default"

try:
    from core.consciousness.silicon_life_consciousness import get_silicon_life
    from core.memory.memory_service import get_memory_service
    CORE_AVAILABLE = True
except ImportError as e:
    CORE_AVAILABLE = False
    print(f"[ConsciousnessAPI] 核心模块导入失败: {e}")

router = APIRouter(prefix="/consciousness", tags=["consciousness"])


# ============================================================================
# Pydantic 请求/响应模型
# ============================================================================

class VitalSignsResponse(BaseModel):
    """生命体征响应模型"""
    energy: float = Field(..., description="能量 (0-10)", ge=0, le=10)
    curiosity: float = Field(..., description="好奇心 (0-10)", ge=0, le=10)
    satisfaction: float = Field(..., description="满足感 (0-10)", ge=0, le=10)
    stress: float = Field(..., description="压力 (0-10)", ge=0, le=10)
    mood: str = Field(..., description="心情描述")
    is_hungry: bool = Field(default=False, description="是否饥饿")
    is_tired: bool = Field(default=False, description="是否疲倦")
    is_excited: bool = Field(default=False, description="是否兴奋")


class VitalSignsHistoryItem(BaseModel):
    """生命体征历史记录项"""
    id: int
    timestamp: str
    energy: float
    curiosity: float
    satisfaction: float
    stress: float
    mood: str
    is_hibernating: bool


class VitalSignsHistoryResponse(BaseModel):
    """生命体征历史响应"""
    user_id: str
    records: list[VitalSignsHistoryItem]
    total: int


class SelfActionItem(BaseModel):
    """自发行动记录项"""
    id: int
    timestamp: str
    action_type: str
    action_content: str | None
    energy_cost: float
    satisfaction_gain: float
    status: str


class SelfActionsResponse(BaseModel):
    """自发行动列表响应"""
    user_id: str
    actions: list[SelfActionItem]
    total: int


class ActionFeedbackRequest(BaseModel):
    """行动反馈请求"""
    feedback: str = Field(..., description="用户反馈内容")
    rating: int = Field(default=5, description="评分 (1-10)", ge=1, le=10)


class ActionFeedbackResponse(BaseModel):
    """行动反馈响应"""
    success: bool
    message: str
    action_id: int


class LifeStatusResponse(BaseModel):
    """生命状态综合响应"""
    user_id: str
    vitals: VitalSignsResponse
    activity_level: float
    current_interval: float
    pending_actions: int
    recent_thoughts: int
    is_running: bool


# ============================================================================
# API 端点
# ============================================================================

@router.get("/vital-signs", response_model=VitalSignsResponse)
async def get_current_vital_signs(user: dict = Depends(get_current_user)):
    """
    获取当前生命体征

    返回硅基生命的实时生命体征数据：
    - 能量 (energy): 决定活动水平，范围 0-10
    - 好奇心 (curiosity): 驱动探索欲望，范围 0-10
    - 满足感 (satisfaction): 反馈调节，范围 0-10
    - 压力 (stress): 负面影响，范围 0-10
    - 心情 (mood): 当前情绪状态描述
    """
    if not CORE_AVAILABLE:
        raise HTTPException(status_code=503, detail="硅基生命核心模块不可用")

    try:
        # 获取用户ID
        user_id = user if isinstance(user, str) else user.get("user_id", "default")

        # 从硅基生命意识获取实时体征
        silicon_life = get_silicon_life(user_id)
        vitals = silicon_life.vitals.signs

        return VitalSignsResponse(
            energy=vitals.energy,
            curiosity=vitals.curiosity,
            satisfaction=vitals.satisfaction,
            stress=vitals.stress,
            mood=vitals.mood,
            is_hungry=vitals.is_hungry,
            is_tired=vitals.is_tired,
            is_excited=vitals.is_excited
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取生命体征失败: {str(e)}") from e


@router.get("/vital-signs/history", response_model=VitalSignsHistoryResponse)
async def get_vital_signs_history(
    limit: int = Query(100, ge=1, le=1000, description="返回记录数量限制"),
    user: dict = Depends(get_current_user)
):
    """
    获取生命体征历史

    查询保存的生命体征历史记录，用于分析生命状态变化趋势。
    """
    if not CORE_AVAILABLE:
        raise HTTPException(status_code=503, detail="记忆模块不可用")

    try:
        # 获取用户ID
        user_id = user if isinstance(user, str) else user.get("user_id", "default")

        # 从记忆系统获取历史记录
        ms = await get_memory_service()
        records = await ms.get_vital_signs_history(user_id=user_id, limit=limit)

        history_items = [
            VitalSignsHistoryItem(
                id=r["id"],
                timestamp=r["timestamp"],
                energy=r["energy"],
                curiosity=r["curiosity"],
                satisfaction=r["satisfaction"],
                stress=r["stress"],
                mood=r["mood"],
                is_hibernating=r["is_hibernating"]
            )
            for r in records
        ]

        return VitalSignsHistoryResponse(
            user_id=user_id,
            records=history_items,
            total=len(history_items)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取生命体征历史失败: {str(e)}") from e


@router.get("/self-actions", response_model=SelfActionsResponse)
async def get_self_actions(
    limit: int = Query(100, ge=1, le=1000, description="返回记录数量限制"),
    user: dict = Depends(get_current_user)
):
    """
    获取自发行动列表

    查询硅基生命生成的自发行动历史记录。
    行动类型包括：explore(探索), assist(协助), reflect(反思), rest(休息)
    """
    if not CORE_AVAILABLE:
        raise HTTPException(status_code=503, detail="记忆模块不可用")

    try:
        # 获取用户ID
        user_id = user if isinstance(user, str) else user.get("user_id", "default")

        # 从记忆系统获取自发行动记录
        ms = await get_memory_service()
        actions = await ms.get_self_actions(user_id=user_id, limit=limit)

        action_items = [
            SelfActionItem(
                id=a["id"],
                timestamp=a["timestamp"],
                action_type=a["action_type"],
                action_content=a.get("action_content"),
                energy_cost=a["energy_cost"],
                satisfaction_gain=a["satisfaction_gain"],
                status=a["status"]
            )
            for a in actions
        ]

        return SelfActionsResponse(
            user_id=user_id,
            actions=action_items,
            total=len(action_items)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取自发行动失败: {str(e)}") from e


@router.post("/self-actions/{action_id}/feedback", response_model=ActionFeedbackResponse)
async def feedback_self_action(
    action_id: int,
    feedback: ActionFeedbackRequest,
    user: dict = Depends(get_current_user)
):
    """
    对自发行动进行反馈

    用户对硅基生命的自发行动提供反馈，帮助调整行为倾向。
    """
    if not CORE_AVAILABLE:
        raise HTTPException(status_code=503, detail="硅基生命核心模块不可用")

    try:
        # 获取用户ID
        user_id = user if isinstance(user, str) else user.get("user_id", "default")

        # 获取硅基生命实例
        silicon_life = get_silicon_life(user_id)

        # 查找对应的行动
        action_key = f"sa_{action_id}"
        if action_key in silicon_life.action_tracker.pending_actions:
            silicon_life.action_tracker.pending_actions[action_key]

            # 记录结果（根据评分判断成功/失败）
            outcome = {
                'success': feedback.rating >= 5,
                'user_satisfied': feedback.rating >= 7,
                'result_summary': feedback.feedback,
                'reward': (feedback.rating - 5) / 5.0  # 转换为 -1.0 到 1.0
            }
            silicon_life.action_tracker.record_outcome(action_key, outcome)

            return ActionFeedbackResponse(
                success=True,
                message="反馈已记录",
                action_id=action_id
            )
        else:
            raise HTTPException(status_code=404, detail=f"未找到行动 {action_id}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"提交反馈失败: {str(e)}") from e


@router.get("/status", response_model=LifeStatusResponse)
async def get_life_status(user: dict = Depends(get_current_user)):
    """
    获取硅基生命综合状态

    返回硅基生命的完整状态信息，包括生命体征、活动水平、待处理行动等。
    """
    if not CORE_AVAILABLE:
        raise HTTPException(status_code=503, detail="硅基生命核心模块不可用")

    try:
        # 获取用户ID
        user_id = user if isinstance(user, str) else user.get("user_id", "default")

        # 获取硅基生命实例
        silicon_life = get_silicon_life(user_id)

        # 获取生命状态
        status = silicon_life.get_life_status()
        vitals = status['vitals']

        return LifeStatusResponse(
            user_id=status['user_id'],
            vitals=VitalSignsResponse(
                energy=vitals['energy'],
                curiosity=vitals['curiosity'],
                satisfaction=vitals['satisfaction'],
                stress=vitals['stress'],
                mood=vitals['mood'],
                is_hungry=vitals.get('is_hungry', False),
                is_tired=vitals.get('is_tired', False),
                is_excited=vitals.get('is_excited', False)
            ),
            activity_level=status['activity_level'],
            current_interval=status['current_interval'],
            pending_actions=status['pending_actions'],
            recent_thoughts=status['recent_thoughts'],
            is_running=status['is_running']
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取生命状态失败: {str(e)}") from e


@router.post("/update-vital-signs")
async def trigger_vital_signs_update(user: dict = Depends(get_current_user)):
    """
    触发生命体征更新

    手动触发一次生命体征更新，用于测试或强制刷新状态。
    """
    if not CORE_AVAILABLE:
        raise HTTPException(status_code=503, detail="硅基生命核心模块不可用")

    try:
        # 获取用户ID
        user_id = user if isinstance(user, str) else user.get("user_id", "default")

        # 获取硅基生命实例并更新体征
        silicon_life = get_silicon_life(user_id)
        vitals = silicon_life.update_vital_signs()

        return {
            "success": True,
            "message": "生命体征已更新",
            "vitals": {
                "energy": vitals.energy,
                "curiosity": vitals.curiosity,
                "satisfaction": vitals.satisfaction,
                "stress": vitals.stress,
                "mood": vitals.mood
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新生命体征失败: {str(e)}") from e


@router.post("/generate-action")
async def trigger_self_action(user: dict = Depends(get_current_user)):
    """
    触发生成自发行动

    手动触发一次自发行动生成，用于测试。
    """
    if not CORE_AVAILABLE:
        raise HTTPException(status_code=503, detail="硅基生命核心模块不可用")

    try:
        # 获取用户ID
        user_id = user if isinstance(user, str) else user.get("user_id", "default")

        # 获取硅基生命实例并生成行动
        silicon_life = get_silicon_life(user_id)
        action = silicon_life.generate_self_action()

        if action:
            return {
                "success": True,
                "message": "自发行动已生成",
                "action": {
                    "action_id": action.action_id,
                    "action_type": action.action_type,
                    "intention": action.intention,
                    "trigger_emotion": action.trigger_emotion
                }
            }
        else:
            return {
                "success": False,
                "message": "当前状态不满足生成自发行动的条件"
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成自发行动失败: {str(e)}") from e


# ============================================================================
# 新增：Growth Stats 响应模型
# ============================================================================

class GrowthStatsResponse(BaseModel):
    """意识生长统计 —— 数字生命体的生命体征监视器"""
    user_id: str
    model_file_size: int                    # 模型文件字节数
    model_last_modified: float              # 模型文件修改时间戳
    training_samples_total: int             # 磁盘上训练历史总条数
    training_samples_memory: int            # 内存缓冲区当前条数
    motivation_state: dict[str, float]      # 好奇心/胜任感/自主性/目的感
    ukf_state: dict[str, Any] | None     # UKF 状态向量
    recent_thoughts: list[dict[str, Any]]   # 最近思考历史
    thinking_stats: dict[str, Any]          # 思考统计
    is_running: bool                        # 意识线程是否运行
    timestamp: str


# ============================================================================
# 新增：GET /api/consciousness/growth-stats
# ============================================================================

@router.get("/growth-stats", response_model=GrowthStatsResponse)
async def get_growth_stats(user: dict = Depends(get_current_user)):
    """
    获取 Consciousness 核心引擎的实时生长指标。

    返回：
    - 模型状态（文件大小、修改时间）
    - 训练数据积累（磁盘总量、内存当前量）
    - 动机状态（好奇心、胜任感、自主性、目的感）
    - UKF 状态估计（行动意愿、反思倾向、探索倾向）
    - 最近思考历史
    """
    if not CORE_AVAILABLE:
        raise HTTPException(status_code=503, detail="硅基生命核心模块不可用")

    try:
        user_id = user if isinstance(user, str) else user.get("user_id", "default")

        # 1. 获取 Consciousness 实例（安全路径：通过代理）
        from core.consciousness.Consciousness import get_consciousness
        consciousness = get_consciousness(user_id)

        # 2. 模型文件信息（直接 os.stat）
        model_path = Path("data/action_preference_model.pt")
        model_file_size = 0
        model_last_modified = 0.0
        if model_path.exists():
            stat = model_path.stat()
            model_file_size = stat.st_size
            model_last_modified = stat.st_mtime

        # 3. 训练样本统计
        training_samples_total = 0
        history_path = Path("data/training_history.jsonl")
        if history_path.exists():
            with open(history_path, "rb") as f:
                training_samples_total = sum(1 for _ in f)

        training_samples_memory = 0
        if hasattr(consciousness, 'online_learner') and consciousness.online_learner:
            training_samples_memory = consciousness.online_learner.sample_count

        # 4. 动机状态
        motivation_state = {}
        if hasattr(consciousness, 'intrinsic_motivation') and consciousness.intrinsic_motivation:
            mot = consciousness.intrinsic_motivation.get_motivation_state()
            motivation_state = {
                "curiosity": round(mot.curiosity, 4),
                "mastery": round(mot.mastery, 4),
                "autonomy": round(mot.autonomy, 4),
                "purpose": round(mot.purpose, 4),
            }

        # 5. UKF 状态（通过 system_state 同步读取）
        ukf_state = None
        try:
            from core.runtime import system_state
            ukf_raw = system_state.get_sync("consciousness.ukf_state")
            if ukf_raw:
                ukf_state = {
                    "action_will": ukf_raw.get("action_will", 0.0),
                    "reflect_tendency": ukf_raw.get("reflect_tendency", 0.0),
                    "explore_tendency": ukf_raw.get("explore_tendency", 0.0),
                    "timestamp": ukf_raw.get("timestamp"),
                }
        except Exception as e:
            logger.warning(f"[GrowthStats] UKF状态读取失败: {e}")

        # 6. 最近思考历史
        recent_thoughts = []
        if hasattr(consciousness, '_thought_history'):
            history = consciousness._thought_history
            if isinstance(history, list):
                for item in history[-3:]:
                    if isinstance(item, dict):
                        recent_thoughts.append({
                            "timestamp": item.get("timestamp"),
                            "content": item.get("content", "")[:100],
                            "mode": item.get("mode", "unknown"),
                        })

        # 7. 思考统计
        thinking_stats = {}
        try:
            thinking_stats = consciousness.get_thinking_stats()
        except Exception as e:
            logger.error(f"[ConsciousnessAPI] 获取思考统计失败: {e}", exc_info=True)

        # 8. 运行状态
        is_running = getattr(consciousness, '_running', False)

        return GrowthStatsResponse(
            user_id=user_id,
            model_file_size=model_file_size,
            model_last_modified=model_last_modified,
            training_samples_total=training_samples_total,
            training_samples_memory=training_samples_memory,
            motivation_state=motivation_state,
            ukf_state=ukf_state,
            recent_thoughts=recent_thoughts,
            thinking_stats=thinking_stats,
            is_running=is_running,
            timestamp=datetime.now().isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GrowthStats] 获取生长统计失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取生长统计失败: {str(e)}") from e


# ============================================================================
# 新增：Training Control 响应模型
# ============================================================================

class TrainingStatusResponse(BaseModel):
    """训练模式状态响应"""
    training_enabled: bool


# ============================================================================
# 新增：POST /api/consciousness/training/start
# ============================================================================

@router.post("/training/start")
async def start_training(user: dict = Depends(get_current_user)):
    """
    开启 Consciousness 训练模式。

    开启后，意识线程将执行 _think()（慢思考）、_deep_reflect()（深度反思）
    和 _default_mode_tick()（走神），产生训练样本并更新模型权重。
    """
    if not CORE_AVAILABLE:
        raise HTTPException(status_code=503, detail="硅基生命核心模块不可用")

    try:
        user_id = user if isinstance(user, str) else user.get("user_id", "default")
        from core.consciousness.Consciousness import get_consciousness
        consciousness = get_consciousness(user_id)
        consciousness.training_enabled = True
        logger.info(f"[TrainingControl] 用户 {user_id} 开启训练模式")
        return {
            "success": True,
            "training_enabled": True,
            "message": "训练模式已开启"
        }
    except Exception as e:
        logger.error(f"[TrainingControl] 开启训练失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"开启训练失败: {str(e)}") from e


# ============================================================================
# 新增：POST /api/consciousness/training/stop
# ============================================================================

@router.post("/training/stop")
async def stop_training(user: dict = Depends(get_current_user)):
    """
    关闭 Consciousness 训练模式。

    关闭后，意识线程仅保留最基本的感知和状态保存，不再调用 LLM 进行
    思考、反思或走神，也不会产生新的训练样本。
    """
    if not CORE_AVAILABLE:
        raise HTTPException(status_code=503, detail="硅基生命核心模块不可用")

    try:
        user_id = user if isinstance(user, str) else user.get("user_id", "default")
        from core.consciousness.Consciousness import get_consciousness
        consciousness = get_consciousness(user_id)
        consciousness.training_enabled = False
        logger.info(f"[TrainingControl] 用户 {user_id} 关闭训练模式")
        return {
            "success": True,
            "training_enabled": False,
            "message": "训练模式已关闭"
        }
    except Exception as e:
        logger.error(f"[TrainingControl] 关闭训练失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"关闭训练失败: {str(e)}") from e


# ============================================================================
# 新增：GET /api/consciousness/training/status
# ============================================================================

@router.get("/training/status", response_model=TrainingStatusResponse)
async def get_training_status(user: dict = Depends(get_current_user)):
    """
    获取当前 Consciousness 训练模式状态。
    """
    if not CORE_AVAILABLE:
        raise HTTPException(status_code=503, detail="硅基生命核心模块不可用")

    try:
        user_id = user if isinstance(user, str) else user.get("user_id", "default")
        from core.consciousness.Consciousness import get_consciousness
        consciousness = get_consciousness(user_id)
        enabled = getattr(consciousness, 'training_enabled', False)
        return TrainingStatusResponse(training_enabled=enabled)
    except Exception as e:
        logger.error(f"[TrainingControl] 获取训练状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取训练状态失败: {str(e)}") from e


# ============================================================================
# 新增：Vision Discovery Control 响应模型
# ============================================================================

class VisionDiscoveryStatusResponse(BaseModel):
    """视觉未知元素发现状态响应"""
    vision_discovery_enabled: bool


# ============================================================================
# 新增：POST /api/consciousness/vision-discovery/start
# ============================================================================

@router.post("/vision-discovery/start")
async def start_vision_discovery(user: dict = Depends(get_current_user)):
    """
    开启视觉未知元素自动发现与标注。

    开启后，视觉系统将自动检测屏幕上的未知 UI 元素，调用视觉大模型
    进行识别和标注，并将结果存入记忆库。
    """
    try:
        from core.vision.vision_unknown_discovery import enable_vision_discovery
        enable_vision_discovery()
        logger.info("[VisionDiscoveryControl] 视觉未知元素发现已开启")
        return {
            "success": True,
            "vision_discovery_enabled": True,
            "message": "视觉未知元素发现已开启"
        }
    except Exception as e:
        logger.error(f"[VisionDiscoveryControl] 开启失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"开启视觉发现失败: {str(e)}") from e


# ============================================================================
# 新增：POST /api/consciousness/vision-discovery/stop
# ============================================================================

@router.post("/vision-discovery/stop")
async def stop_vision_discovery(user: dict = Depends(get_current_user)):
    """
    关闭视觉未知元素自动发现与标注。

    关闭后，视觉系统将不再调用大模型对未知 UI 元素进行自动识别和标注，
    但仍保留基础的视觉检测和已知元素召回功能。
    """
    try:
        from core.vision.vision_unknown_discovery import disable_vision_discovery
        disable_vision_discovery()
        logger.info("[VisionDiscoveryControl] 视觉未知元素发现已关闭")
        return {
            "success": True,
            "vision_discovery_enabled": False,
            "message": "视觉未知元素发现已关闭"
        }
    except Exception as e:
        logger.error(f"[VisionDiscoveryControl] 关闭失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"关闭视觉发现失败: {str(e)}") from e


# ============================================================================
# 新增：GET /api/consciousness/vision-discovery/status
# ============================================================================

@router.get("/vision-discovery/status", response_model=VisionDiscoveryStatusResponse)
async def get_vision_discovery_status(user: dict = Depends(get_current_user)):
    """
    获取视觉未知元素自动发现与标注的当前状态。
    """
    try:
        from core.vision.vision_unknown_discovery import is_vision_discovery_enabled
        enabled = is_vision_discovery_enabled()
        return VisionDiscoveryStatusResponse(vision_discovery_enabled=enabled)
    except Exception as e:
        logger.error(f"[VisionDiscoveryControl] 获取状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取视觉发现状态失败: {str(e)}") from e
