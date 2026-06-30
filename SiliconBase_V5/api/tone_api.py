#!/usr/bin/env python3
"""
语气偏好管理 API

为前端 TonePreferencePanel 提供：
- 用户语气偏好 CRUD
- 语气预设 CRUD
- 语气预览与分析

当前使用内存存储，重启后重置；后续可迁移到数据库。
"""

import random
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Path as FastApiPath
from pydantic import BaseModel, Field

from core.logger import logger

# 认证依赖
try:
    from api.cloud_api import get_current_user
    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False

if not AUTH_AVAILABLE:
    async def _fallback_user():
        return "default"
    get_current_user = _fallback_user

router = APIRouter(prefix="", tags=["tone"])

# ============================================================================
# 数据模型
# ============================================================================

class ToneType(str):
    pass


class ToneConfig(BaseModel):
    type: str = Field(default="casual", description="语气类型")
    formality: int = Field(default=50, ge=0, le=100, description="正式程度")
    enthusiasm: int = Field(default=70, ge=0, le=100, description="热情程度")
    empathy: int = Field(default=80, ge=0, le=100, description="共情程度")
    technicality: int = Field(default=50, ge=0, le=100, description="专业程度")
    custom_prompt: str | None = Field(default=None, description="自定义提示词")
    enabled: bool = Field(default=True, description="是否启用")


class TonePreset(BaseModel):
    id: str
    name: str
    description: str
    config: ToneConfig
    is_builtin: bool = True


class TonePreferenceResponse(BaseModel):
    success: bool
    data: ToneConfig
    message: str | None = None


class TonePresetsResponse(BaseModel):
    success: bool
    data: list[TonePreset]


class TonePresetResponse(BaseModel):
    success: bool
    data: TonePreset


class CreateTonePresetRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(default="")
    config: ToneConfig


class UpdateTonePresetRequest(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None)
    config: ToneConfig | None = Field(default=None)


class TonePreviewRequest(BaseModel):
    type: str = Field(default="casual")
    formality: int = Field(default=50, ge=0, le=100)
    enthusiasm: int = Field(default=70, ge=0, le=100)
    empathy: int = Field(default=80, ge=0, le=100)
    technicality: int = Field(default=50, ge=0, le=100)
    custom_prompt: str | None = Field(default=None)


class TonePreviewResponse(BaseModel):
    success: bool
    data: dict


class ToneAnalyzeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


class ToneAnalyzeResponse(BaseModel):
    success: bool
    data: dict


class ApplyPresetRequest(BaseModel):
    preset_id: str


# ============================================================================
# 内存存储
# ============================================================================

_DEFAULT_CONFIG = ToneConfig(
    type="casual",
    formality=50,
    enthusiasm=70,
    empathy=80,
    technicality=50,
    enabled=True,
)

_USER_PREFERENCES: dict[str, ToneConfig] = {}

_BUILTIN_PRESETS: list[TonePreset] = [
    TonePreset(
        id="formal",
        name="正式",
        description="严肃、规范的表达方式，适合商务场合",
        config=ToneConfig(type="formal", formality=90, enthusiasm=40, empathy=50, technicality=70),
    ),
    TonePreset(
        id="casual",
        name="随意",
        description="轻松、自然的对话风格，像朋友聊天",
        config=ToneConfig(type="casual", formality=30, enthusiasm=70, empathy=80, technicality=40),
    ),
    TonePreset(
        id="humorous",
        name="幽默",
        description="风趣、有趣的表达方式，带有一些俏皮",
        config=ToneConfig(type="humorous", formality=20, enthusiasm=90, empathy=70, technicality=30),
    ),
    TonePreset(
        id="professional",
        name="专业",
        description="权威、精准的表达，注重专业性",
        config=ToneConfig(type="professional", formality=80, enthusiasm=50, empathy=50, technicality=90),
    ),
    TonePreset(
        id="friendly",
        name="友善",
        description="温暖、体贴的沟通风格",
        config=ToneConfig(type="friendly", formality=40, enthusiasm=80, empathy=95, technicality=30),
    ),
    TonePreset(
        id="concise",
        name="简洁",
        description="直接、精简的回答，不拖泥带水",
        config=ToneConfig(type="concise", formality=50, enthusiasm=40, empathy=40, technicality=60),
    ),
    TonePreset(
        id="detailed",
        name="详细",
        description="全面、详尽的解释，包含更多背景信息",
        config=ToneConfig(type="detailed", formality=50, enthusiasm=60, empathy=70, technicality=70),
    ),
]

_CUSTOM_PRESETS: dict[str, TonePreset] = {}


def _get_user_config(user_id: str) -> ToneConfig:
    return _USER_PREFERENCES.get(user_id, _DEFAULT_CONFIG.copy(deep=True))


def _all_presets() -> list[TonePreset]:
    return _BUILTIN_PRESETS + list(_CUSTOM_PRESETS.values())


# ============================================================================
# API 端点：用户语气偏好
# ============================================================================

@router.get("/users/{user_id}/tone-preference", response_model=TonePreferenceResponse)
async def get_tone_preference(
    user_id: str = FastApiPath(..., description="用户ID"),
    current_user: str = Depends(get_current_user)
):
    """获取用户语气偏好"""
    config = _get_user_config(user_id)
    return TonePreferenceResponse(success=True, data=config)


@router.put("/users/{user_id}/tone-preference", response_model=TonePreferenceResponse)
async def update_tone_preference(
    request: ToneConfig,
    user_id: str = FastApiPath(..., description="用户ID"),
    current_user: str = Depends(get_current_user)
):
    """更新用户语气偏好"""
    _USER_PREFERENCES[user_id] = request
    logger.info(f"[ToneAPI] 用户 {user_id} 更新语气偏好")
    return TonePreferenceResponse(success=True, data=request, message="语气偏好已保存")


@router.post("/users/{user_id}/tone-preference/reset", response_model=TonePreferenceResponse)
async def reset_tone_preference(
    user_id: str = FastApiPath(..., description="用户ID"),
    current_user: str = Depends(get_current_user)
):
    """重置用户语气偏好为默认"""
    config = _DEFAULT_CONFIG.copy(deep=True)
    _USER_PREFERENCES[user_id] = config
    return TonePreferenceResponse(success=True, data=config, message="已恢复默认语气偏好")


@router.post("/users/{user_id}/tone-preference/apply-preset", response_model=TonePreferenceResponse)
async def apply_preset_to_user(
    request: ApplyPresetRequest,
    user_id: str = FastApiPath(..., description="用户ID"),
    current_user: str = Depends(get_current_user)
):
    """将预设应用到用户偏好"""
    preset = next((p for p in _all_presets() if p.id == request.preset_id), None)
    if not preset:
        raise HTTPException(status_code=404, detail="预设不存在")
    _USER_PREFERENCES[user_id] = preset.config.copy(deep=True)
    return TonePreferenceResponse(success=True, data=_USER_PREFERENCES[user_id], message="预设已应用")


# ============================================================================
# API 端点：语气预设
# ============================================================================

@router.get("/tone-presets", response_model=TonePresetsResponse)
async def list_tone_presets(current_user: str = Depends(get_current_user)):
    """获取语气预设列表"""
    return TonePresetsResponse(success=True, data=_all_presets())


@router.get("/tone-presets/{preset_id}", response_model=TonePresetResponse)
async def get_tone_preset(
    preset_id: str = FastApiPath(..., description="预设ID"),
    current_user: str = Depends(get_current_user)
):
    """获取单个语气预设"""
    preset = next((p for p in _all_presets() if p.id == preset_id), None)
    if not preset:
        raise HTTPException(status_code=404, detail="预设不存在")
    return TonePresetResponse(success=True, data=preset)


@router.post("/tone-presets", response_model=TonePresetResponse)
async def create_tone_preset(
    request: CreateTonePresetRequest,
    current_user: str = Depends(get_current_user)
):
    """创建自定义语气预设"""
    preset_id = str(uuid.uuid4())
    preset = TonePreset(
        id=preset_id,
        name=request.name,
        description=request.description or "",
        config=request.config,
        is_builtin=False,
    )
    _CUSTOM_PRESETS[preset_id] = preset
    logger.info(f"[ToneAPI] 用户 {current_user} 创建语气预设 {preset_id}")
    return TonePresetResponse(success=True, data=preset)


@router.put("/tone-presets/{preset_id}", response_model=TonePresetResponse)
async def update_tone_preset(
    request: UpdateTonePresetRequest,
    preset_id: str = FastApiPath(..., description="预设ID"),
    current_user: str = Depends(get_current_user)
):
    """更新语气预设（仅自定义预设可更新）"""
    if preset_id in {p.id for p in _BUILTIN_PRESETS}:
        raise HTTPException(status_code=403, detail="内置预设不可修改")
    preset = _CUSTOM_PRESETS.get(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="预设不存在")

    if request.name is not None:
        preset.name = request.name
    if request.description is not None:
        preset.description = request.description
    if request.config is not None:
        preset.config = request.config
    return TonePresetResponse(success=True, data=preset)


@router.delete("/tone-presets/{preset_id}")
async def delete_tone_preset(
    preset_id: str = FastApiPath(..., description="预设ID"),
    current_user: str = Depends(get_current_user)
):
    """删除自定义语气预设"""
    if preset_id in {p.id for p in _BUILTIN_PRESETS}:
        raise HTTPException(status_code=403, detail="内置预设不可删除")
    if preset_id not in _CUSTOM_PRESETS:
        raise HTTPException(status_code=404, detail="预设不存在")
    del _CUSTOM_PRESETS[preset_id]
    return {"success": True, "message": "预设已删除"}


# ============================================================================
# API 端点：预览与分析
# ============================================================================

_PREVIEW_TEMPLATES = {
    "formal": "您好，关于您提出的问题，我将基于现有信息为您提供严谨、规范的解答。",
    "casual": "嗨，这个问题挺有意思的，我来跟你聊聊~",
    "humorous": "哈哈，这题我会！让我用轻松有趣的方式告诉你~",
    "professional": "从专业角度分析，该问题涉及多个关键要素，建议采用系统化方法处理。",
    "friendly": "没关系，我来帮你慢慢梳理，咱们一起把这个问题搞清楚。",
    "concise": "简要回答：核心要点如下。",
    "detailed": "这个问题可以从以下几个方面详细说明：背景、原因、影响与建议。",
}


@router.post("/tone-preview", response_model=TonePreviewResponse)
async def generate_tone_preview(
    request: TonePreviewRequest,
    current_user: str = Depends(get_current_user)
):
    """根据当前语气配置生成预览文本"""
    template = _PREVIEW_TEMPLATES.get(request.type, _PREVIEW_TEMPLATES["casual"])
    # 根据参数简单调整预览
    if request.formality > 70:
        template = template.replace("聊", "阐述").replace("~", "。")
    if request.enthusiasm > 80 and "~" not in template:
        template += " 非常乐意为您服务！"
    if request.technicality > 70:
        template += "（涉及技术细节可进一步展开）"

    config = ToneConfig(
        type=request.type,
        formality=request.formality,
        enthusiasm=request.enthusiasm,
        empathy=request.empathy,
        technicality=request.technicality,
        custom_prompt=request.custom_prompt,
        enabled=True,
    )
    return TonePreviewResponse(success=True, data={"preview": template, "config": config.dict()})


@router.post("/tone-analyze", response_model=ToneAnalyzeResponse)
async def analyze_tone(
    request: ToneAnalyzeRequest,
    current_user: str = Depends(get_current_user)
):
    """分析文本语气（基于关键词的轻量规则）"""
    text = request.text.lower()
    scores = {
        "formal": 0,
        "casual": 0,
        "humorous": 0,
        "professional": 0,
        "friendly": 0,
        "concise": 0,
        "detailed": 0,
    }

    # 简单规则
    if any(w in text for w in ["您好", "尊敬的", "谨此", "特此", "敬请"]):
        scores["formal"] += 3
    if any(w in text for w in ["哈哈", "~", "呢", "呀", "哦"]):
        scores["casual"] += 2
    if any(w in text for w in ["哈哈", "有趣", "开玩笑", "俏皮"]):
        scores["humorous"] += 3
    if any(w in text for w in ["分析", "专业", "系统", "方案", "建议"]):
        scores["professional"] += 2
    if any(w in text for w in ["没关系", "帮你", "一起", "放心"]):
        scores["friendly"] += 3
    if len(text) < 20:
        scores["concise"] += 2
    if len(text) > 100:
        scores["detailed"] += 2

    detected = max(scores, key=scores.get)
    confidence = min(50 + scores[detected] * 10 + random.randint(0, 10), 95)
    suggestions = [
        "可尝试调整正式程度以匹配场景",
        "如需更热情，可提高 enthusiasm 参数",
    ]
    return ToneAnalyzeResponse(
        success=True,
        data={
            "detected_tone": detected,
            "confidence": confidence,
            "suggestions": suggestions,
        }
    )
