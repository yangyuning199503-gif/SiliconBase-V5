#!/usr/bin/env python3
"""
语音播报API
提供前端接口用于：
1. 播报文本消息
2. 控制语音开关
3. 层级切换语音反馈（L1/L2/L3）

【大纲规则3】切换时语音播报"正在查询中，请稍后"
"""

import json
import os
import subprocess
import tempfile
import wave

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from core.logger import logger
from voice.voice_prompts import SystemAnnouncements

# 导入认证依赖
try:
    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

    security = HTTPBearer(auto_error=False)
    HAS_AUTH = True
except ImportError:
    HAS_AUTH = False
    security = None

# 可选认证依赖
async def get_current_user_optional(credentials: HTTPAuthorizationCredentials = Depends(security) if security else None) -> str:
    """可选认证，返回用户ID或default_user"""
    if not HAS_AUTH or credentials is None:
        return "default_user"
    try:
        from api.cloud_api import get_current_user as get_user
        return await get_user(credentials)
    except Exception:
        return "default_user"

router = APIRouter(
    prefix="/voice",
    tags=["语音播报"]
)


# ============ 数据模型 ============

class VoiceAnnounceRequest(BaseModel):
    """语音播报请求"""
    text: str = Field(..., description="要播报的文本内容")
    priority: str = Field(default="normal", description="优先级: low/normal/high")
    is_system: bool = Field(default=True, description="是否是系统音")


class LayerSwitchRequest(BaseModel):
    """层级切换语音请求"""
    to_layer: str = Field(..., description="目标层级: l1/l2/l3")
    from_layer: str | None = Field(default=None, description="源层级: l1/l2/l3")
    tool_name: str | None = Field(default=None, description="L3层工具名称")


class VoiceStatusResponse(BaseModel):
    """语音状态响应"""
    enabled: bool
    available: bool
    engine: str | None = None


# ============ API端点 ============

@router.post("/announce")
async def announce_voice(
    request: VoiceAnnounceRequest,
    user_id: str = Depends(get_current_user_optional)
):
    """
    播报语音消息

    将文本转换为语音播报，用于系统提示和用户反馈。
    【大纲规则3】层级切换时播报"正在查询中，请稍后"
    """
    try:
        # 尝试导入语音模块
        try:
            from voice import get_voice_interface
            from voice.voice_assistant import get_voice_assistant

            voice_interface = get_voice_interface()
            assistant = get_voice_assistant(voice_interface)

            # 执行播报
            assistant.speak(request.text, is_system=request.is_system)

            return {
                "success": True,
                "message": "语音播报已发送",
                "text": request.text
            }
        except ImportError:
            # 语音模块不可用
            logger.warning("[VoiceAPI] 语音模块不可用，跳过播报")
            return {
                "success": False,
                "message": "语音模块不可用",
                "text": request.text
            }
    except Exception as e:
        logger.error(f"[VoiceAPI] 语音播报失败: {e}")
        return {
            "success": False,
            "message": f"语音播报失败: {str(e)}",
            "text": request.text
        }


@router.post("/layer-switch")
async def announce_layer_switch(
    request: LayerSwitchRequest,
    user_id: str = Depends(get_current_user_optional)
):
    """
    播报层级切换提示

    【大纲规则3】切换L1/L2/L3层级时语音播报"正在查询中，请稍后"

    Args:
        request: 层级切换信息

    Returns:
        播报结果
    """
    try:
        try:
            from voice import get_voice_interface
            from voice.voice_assistant import get_voice_assistant

            voice_interface = get_voice_interface()
            assistant = get_voice_assistant(voice_interface)

            # 根据层级调用相应播报方法
            if request.to_layer.lower() == 'l1':
                assistant.announce_l1_overview(from_layer=request.from_layer)
            elif request.to_layer.lower() == 'l2':
                assistant.announce_l2_manual(from_layer=request.from_layer)
            elif request.to_layer.lower() == 'l3' and request.tool_name:
                assistant.announce_l3_tool_detail(request.tool_name, from_layer=request.from_layer)
            else:
                # 通用切换播报
                assistant.speak(SystemAnnouncements.QUERYING, is_system=True)

            return {
                "success": True,
                "message": f"已播报{request.to_layer.upper()}层级切换",
                "announcement": SystemAnnouncements.QUERYING
            }
        except ImportError:
            logger.warning("[VoiceAPI] 语音模块不可用")
            return {
                "success": False,
                "message": "语音模块不可用"
            }
    except Exception as e:
        logger.error(f"[VoiceAPI] 层级切换播报失败: {e}")
        return {
            "success": False,
            "message": f"播报失败: {str(e)}"
        }


class VoiceTestRequest(BaseModel):
    """语音测试请求"""
    text: str = Field(default="你好，我是硅基生命体，语音测试成功", description="要播报的测试文本")


@router.post("/test")
async def test_voice(
    request: VoiceTestRequest,
    user_id: str = Depends(get_current_user_optional)
):
    """
    语音测试

    调用 TTS 播报一段测试文本，用于前端设置页验证语音功能。
    """
    return await announce_voice(
        VoiceAnnounceRequest(text=request.text, priority="normal", is_system=True),
        user_id
    )


@router.get("/status", response_model=VoiceStatusResponse)
async def get_voice_status(user_id: str = Depends(get_current_user_optional)):
    """
    获取语音系统状态

    Returns:
        语音系统是否可用和当前状态
    """
    try:
        try:
            from voice import get_voice_interface
            voice = get_voice_interface()

            return {
                "enabled": True,
                "available": voice is not None,
                "engine": getattr(voice, 'engine', 'unknown') if voice else None
            }
        except ImportError:
            return {
                "enabled": False,
                "available": False,
                "engine": None
            }
    except Exception as e:
        logger.error(f"[VoiceAPI] 获取语音状态失败: {e}")
        return {
            "enabled": False,
            "available": False,
            "engine": None
        }


@router.post("/enable")
async def enable_voice(user_id: str = Depends(get_current_user_optional)):
    """启用语音播报"""
    try:
        try:
            from voice import get_voice_interface
            from voice.voice_assistant import get_voice_assistant

            voice_interface = get_voice_interface()
            assistant = get_voice_assistant(voice_interface)
            assistant.enable()

            return {"success": True, "message": "语音播报已启用"}
        except ImportError:
            return {"success": False, "message": "语音模块不可用"}
    except Exception as e:
        logger.error(f"[VoiceAPI] 启用语音失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/disable")
async def disable_voice(user_id: str = Depends(get_current_user_optional)):
    """禁用语音播报"""
    try:
        try:
            from voice import get_voice_interface
            from voice.voice_assistant import get_voice_assistant

            voice_interface = get_voice_interface()
            assistant = get_voice_assistant(voice_interface)
            assistant.disable()

            return {"success": True, "message": "语音播报已禁用"}
        except ImportError:
            return {"success": False, "message": "语音模块不可用"}
    except Exception as e:
        logger.error(f"[VoiceAPI] 禁用语音失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ============ 音频 STT 端点（hold-to-talk）============

class STTResponse(BaseModel):
    """语音识别响应"""
    text: str = Field(default="", description="识别出的文本")
    success: bool = Field(default=True, description="是否成功")
    message: str | None = Field(default=None, description="错误信息")


@router.post("/stt", response_model=STTResponse)
async def speech_to_text(
    audio: UploadFile = File(..., description="音频文件（webm/opus 格式）"),
    user_id: str = Depends(get_current_user_optional)
):
    """
    音频语音识别（Speech-to-Text）

    接收前端录制的音频文件，使用 Vosk 进行离线识别，返回识别文本。
    支持 webm/opus 等浏览器录制格式，后端自动转换为 WAV PCM。

    Args:
        audio: 音频文件

    Returns:
        STTResponse: 识别结果
    """
    try:
        # 读取上传的音频数据
        audio_data = await audio.read()
        if not audio_data or len(audio_data) < 100:
            return STTResponse(text="", success=False, message="音频数据为空或太短")

        # 使用临时文件保存上传的音频和转换后的 wav
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.webm")
            wav_path = os.path.join(tmpdir, "output.wav")

            with open(input_path, "wb") as f:
                f.write(audio_data)

            # 使用 ffmpeg 转换为 16kHz 单声道 WAV（Vosk 需要）
            try:
                import asyncio
                result = await asyncio.to_thread(
                    subprocess.run,
                    [
                        "ffmpeg", "-y", "-i", input_path,
                        "-ar", "16000", "-ac", "1", "-f", "wav",
                        wav_path
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode != 0:
                    logger.error(f"[VoiceAPI] ffmpeg 转换失败: {result.stderr}")
                    return STTResponse(text="", success=False, message="音频格式转换失败")
            except FileNotFoundError:
                logger.error("[VoiceAPI] ffmpeg 未安装")
                return STTResponse(text="", success=False, message="服务器缺少 ffmpeg，无法处理音频")
            except Exception as e:
                logger.error(f"[VoiceAPI] ffmpeg 异常: {e}")
                return STTResponse(text="", success=False, message="音频处理异常")

            # 使用 Vosk 识别（在线程池中执行，避免阻塞事件循环）
            try:
                from core.config import config
                model_path = config.get("voice.model_path", "assets/models/vosk-model-cn-0.22")

                if not os.path.exists(model_path):
                    return STTResponse(text="", success=False, message="Vosk 模型未找到")

                import asyncio

                import vosk

                def _recognize_with_vosk(wav_path: str, model_path: str) -> str:
                    """同步执行 Vosk 识别"""
                    model = vosk.Model(model_path)
                    rec = vosk.KaldiRecognizer(model, 16000)
                    with wave.open(wav_path, "rb") as wf:
                        while True:
                            data = wf.readframes(4000)
                            if len(data) == 0:
                                break
                            rec.AcceptWaveform(data)
                    result_json = json.loads(rec.FinalResult())
                    return result_json.get("text", "").strip()

                recognized_text = await asyncio.to_thread(
                    _recognize_with_vosk, wav_path, model_path
                )

                logger.info(f"[VoiceAPI] STT 识别结果: '{recognized_text}'")
                return STTResponse(text=recognized_text, success=True)

            except ImportError:
                logger.error("[VoiceAPI] vosk 未安装")
                return STTResponse(text="", success=False, message="Vosk 语音识别库未安装")
            except Exception as e:
                logger.error(f"[VoiceAPI] Vosk 识别异常: {e}", exc_info=True)
                return STTResponse(text="", success=False, message=f"识别异常: {str(e)}")

    except Exception as e:
        logger.error(f"[VoiceAPI] STT 端点异常: {e}", exc_info=True)
        return STTResponse(text="", success=False, message=f"服务端异常: {str(e)}")


# 快捷播报端点
@router.get("/quick-announce")
async def quick_announce(
    text: str = Query(default="正在查询中，请稍后", description="播报文本"),
    user_id: str = Depends(get_current_user_optional)
):
    """
    快捷语音播报（GET方式）

    用于简单场景的快速播报，默认播报"正在查询中，请稍后"

    Args:
        text: 要播报的文本，默认为"正在查询中，请稍后"

    Returns:
        播报结果
    """
    return await announce_voice(
        VoiceAnnounceRequest(text=text, priority="normal", is_system=True),
        user_id
    )
