"""
高级模型管理API
提供模型查询、启用/禁用、下载进度等功能

修复说明:
- 修复路由前缀重复问题（移除router prefix，由cloud_api统一配置）
- 添加认证依赖
- 添加sizeBytes字段支持
- 与前端AdvancedModelsPage完全兼容
"""
import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from core.ai.advanced_model_manager import advanced_model_manager

logger = logging.getLogger(__name__)

# 注意：前缀由cloud_api.py统一配置为 /api/advanced-models
router = APIRouter(tags=["advanced-models"])


# ============================================================================
# 认证依赖导入 - 使用独立的auth_utils模块避免循环导入
# ============================================================================
get_current_user = None
AUTH_AVAILABLE = False

try:
    from api.auth_utils import get_current_user
    AUTH_AVAILABLE = True
except ImportError:
    try:
        from .auth_utils import get_current_user
        AUTH_AVAILABLE = True
    except ImportError as e:
        logger.warning(f"[AdvancedModelsAPI] 认证模块导入失败: {e}，API将无需认证访问")
        async def _fallback_get_current_user():
            return "anonymous"
        get_current_user = _fallback_get_current_user


# ============================================================================
# Pydantic模型定义
# ============================================================================
class ModelStatusResponse(BaseModel):
    """模型状态响应"""
    id: str
    name: str
    description: str
    size: str
    sizeBytes: int  # 前端需要这个字段计算内存
    category: str
    enabled: bool
    downloaded: bool
    loaded: bool
    device: str | None = None
    use_cases: list[str]


class EnableRequest(BaseModel):
    """启用模型请求"""
    auto_download: bool = False


class OperationResponse(BaseModel):
    """操作响应"""
    success: bool
    message: str
    action_required: str | None = None


class MemoryStatusResponse(BaseModel):
    """内存状态响应"""
    total_loaded: int
    total_memory_bytes: int
    total_memory_gb: float
    loaded_models: list[dict]


# ============================================================================
# 分类映射
# ============================================================================
CATEGORY_MAP = {
    "bigvgan_v2": "speech",
    "maskgct": "speech",
    "w2v_bert": "nlp",
    "campplus": "vad"
}

CATEGORY_LABELS = {
    "speech": "语音增强",
    "nlp": "高级NLP",
    "vad": "语音检测"
}


# ============================================================================
# SSE下载进度管理
# ============================================================================
_download_progress: dict[str, asyncio.Queue] = {}


def _get_model_category(model_id: str) -> str:
    """获取模型分类"""
    return CATEGORY_MAP.get(model_id, "other")


def _build_model_response(model_info, status: dict) -> ModelStatusResponse:
    """构建模型响应对象"""
    model_id = model_info.id
    return ModelStatusResponse(
        id=model_id,
        name=model_id.replace('_', ' ').title(),
        description=model_info.description,
        size=model_info.size,
        sizeBytes=model_info.size_bytes,  # 前端需要这个字段
        category=_get_model_category(model_id),
        enabled=status.get("enabled", False),
        downloaded=status.get("downloaded", False),
        loaded=status.get("loaded", False),
        device=status.get("device") if status.get("loaded") else None,
        use_cases=model_info.use_cases if model_info.use_cases else []
    )


# ============================================================================
# API端点
# ============================================================================

@router.get("", response_model=list[ModelStatusResponse])
async def list_models(user_id: str = Depends(get_current_user)):
    """
    获取所有高级模型列表

    - 返回系统中所有可用的高级模型及其状态
    - 包含大小、下载状态、加载状态等信息
    """
    try:
        models = advanced_model_manager.list_available_models()
        result = []

        for model in models:
            status = advanced_model_manager.get_model_status(model.id)
            response = _build_model_response(model, status)
            result.append(response)

        logger.info(f"[AdvancedModelsAPI] 用户 {user_id} 获取模型列表，共 {len(result)} 个模型")
        return result

    except Exception as e:
        logger.error(f"[AdvancedModelsAPI] 获取模型列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取模型列表失败: {str(e)}") from e


@router.get("/{model_id}", response_model=ModelStatusResponse)
async def get_model(model_id: str, user_id: str = Depends(get_current_user)):
    """
    获取单个模型的详细状态

    - **model_id**: 模型ID (bigvgan_v2, w2v_bert, maskgct, campplus)
    """
    try:
        # 检查模型是否存在
        info = advanced_model_manager.get_model_info(model_id)
        if not info:
            raise HTTPException(status_code=404, detail=f"模型 {model_id} 不存在")

        status = advanced_model_manager.get_model_status(model_id)
        return _build_model_response(info, status)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AdvancedModelsAPI] 获取模型 {model_id} 状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取模型状态失败: {str(e)}") from e


@router.post("/{model_id}/enable", response_model=OperationResponse)
async def enable_model(
    model_id: str,
    request: EnableRequest,
    user_id: str = Depends(get_current_user)
):
    """
    启用模型

    - **model_id**: 模型ID
    - **auto_download**: 如果未下载，是否自动下载
    """
    try:
        logger.info(f"[AdvancedModelsAPI] 用户 {user_id} 请求启用模型 {model_id}")
        result = advanced_model_manager.enable_model(model_id, request.auto_download)
        return OperationResponse(**result)

    except Exception as e:
        logger.error(f"[AdvancedModelsAPI] 启用模型 {model_id} 失败: {e}")
        raise HTTPException(status_code=500, detail=f"启用模型失败: {str(e)}") from e


@router.post("/{model_id}/disable", response_model=OperationResponse)
async def disable_model(model_id: str, user_id: str = Depends(get_current_user)):
    """
    禁用模型

    - 禁用后会自动卸载已加载的模型释放内存
    - **model_id**: 模型ID
    """
    try:
        logger.info(f"[AdvancedModelsAPI] 用户 {user_id} 请求禁用模型 {model_id}")
        result = advanced_model_manager.disable_model(model_id)
        return OperationResponse(**result)

    except Exception as e:
        logger.error(f"[AdvancedModelsAPI] 禁用模型 {model_id} 失败: {e}")
        raise HTTPException(status_code=500, detail=f"禁用模型失败: {str(e)}") from e


@router.post("/{model_id}/deploy", response_model=OperationResponse)
async def deploy_model(
    model_id: str,
    user_id: str = Depends(get_current_user)
):
    """
    部署模型（启用并加载）

    - 先启用模型，然后加载到内存
    - **model_id**: 模型ID
    """
    try:
        logger.info(f"[AdvancedModelsAPI] 用户 {user_id} 请求部署模型 {model_id}")

        # 先启用
        enable_result = advanced_model_manager.enable_model(model_id, auto_download=True)

        # 如果已下载，尝试加载
        status = advanced_model_manager.get_model_status(model_id)
        if status.get("downloaded") and not status.get("loaded"):
            model = advanced_model_manager.load_model(model_id)
            if model:
                return OperationResponse(
                    success=True,
                    message=f"模型 {model_id} 已部署并加载到内存",
                    action_required=None
                )

        return OperationResponse(**enable_result)

    except Exception as e:
        logger.error(f"[AdvancedModelsAPI] 部署模型 {model_id} 失败: {e}")
        raise HTTPException(status_code=500, detail=f"部署模型失败: {str(e)}") from e


@router.post("/{model_id}/undeploy", response_model=OperationResponse)
async def undeploy_model(model_id: str, user_id: str = Depends(get_current_user)):
    """
    卸载模型（禁用并释放内存）

    - 卸载模型并禁用，释放内存资源
    - **model_id**: 模型ID
    """
    try:
        logger.info(f"[AdvancedModelsAPI] 用户 {user_id} 请求卸载模型 {model_id}")

        # 先卸载
        advanced_model_manager.unload_model(model_id)

        # 再禁用
        advanced_model_manager.disable_model(model_id)
        return OperationResponse(
            success=True,
            message=f"模型 {model_id} 已卸载并禁用",
            action_required=None
        )

    except Exception as e:
        logger.error(f"[AdvancedModelsAPI] 卸载模型 {model_id} 失败: {e}")
        raise HTTPException(status_code=500, detail=f"卸载模型失败: {str(e)}") from e


@router.post("/{model_id}/download")
async def download_model(
    model_id: str,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user)
):
    """
    开始下载模型（后台任务）

    - **model_id**: 模型ID
    - 下载进度通过 /{model_id}/download-progress SSE端点获取
    """
    try:
        # 检查模型是否存在
        info = advanced_model_manager.get_model_info(model_id)
        if not info:
            raise HTTPException(status_code=404, detail=f"模型 {model_id} 不存在")

        # 创建进度队列
        _download_progress[model_id] = asyncio.Queue()

        logger.info(f"[AdvancedModelsAPI] 用户 {user_id} 启动模型 {model_id} 下载")

        # 启动后台下载
        async def download_with_progress():
            try:
                queue = _download_progress[model_id]

                # 发送开始
                await queue.put({"status": "started", "progress": 0})

                # 实际下载
                result = advanced_model_manager.download_model(model_id)

                if result.get("success"):
                    await queue.put({"status": "complete", "progress": 100})
                else:
                    await queue.put({
                        "status": "error",
                        "message": result.get("message", "下载失败")
                    })

            except Exception as e:
                logger.error(f"[AdvancedModelsAPI] 下载任务异常: {e}")
                if model_id in _download_progress:
                    await _download_progress[model_id].put({
                        "status": "error",
                        "message": str(e)
                    })
            finally:
                # 清理
                if model_id in _download_progress:
                    await asyncio.sleep(5)  # 给客户端时间读取最终状态
                    del _download_progress[model_id]

        background_tasks.add_task(download_with_progress)

        return {"success": True, "message": "下载任务已启动"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AdvancedModelsAPI] 启动下载失败: {e}")
        raise HTTPException(status_code=500, detail=f"启动下载失败: {str(e)}") from e


@router.get("/{model_id}/download-progress")
async def download_progress(model_id: str, user_id: str = Depends(get_current_user)):
    """
    SSE: 获取下载进度

    - **model_id**: 模型ID
    - 返回SSE流，包含下载进度更新
    """
    import json

    from fastapi.responses import StreamingResponse

    async def event_generator():
        if model_id not in _download_progress:
            yield f"data: {json.dumps({'status': 'not_found', 'message': '没有活动的下载任务'})}\n\n"
            return

        queue = _download_progress[model_id]

        try:
            while True:
                # 等待进度更新（30秒超时）
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {json.dumps(data)}\n\n"

                    if data.get("status") in ["complete", "error"]:
                        break

                except asyncio.TimeoutError:
                    # 发送心跳保持连接
                    yield f"data: {json.dumps({'status': 'ping'})}\n\n"

        except Exception as e:
            logger.error(f"[AdvancedModelsAPI] SSE异常: {e}")
            yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@router.post("/{model_id}/load")
async def load_model_endpoint(model_id: str, user_id: str = Depends(get_current_user)):
    """
    手动加载模型到内存

    - **model_id**: 模型ID
    """
    try:
        logger.info(f"[AdvancedModelsAPI] 用户 {user_id} 请求加载模型 {model_id}")

        model = advanced_model_manager.load_model(model_id)

        if model:
            status = advanced_model_manager.get_model_status(model_id)
            return {
                "success": True,
                "message": f"模型 {model_id} 已加载",
                "memory_usage": status.get("memory_usage", 0)
            }
        else:
            status = advanced_model_manager.get_model_status(model_id)
            if not status.get("enabled"):
                raise HTTPException(status_code=400, detail="模型未启用，请先启用模型")
            if not status.get("downloaded"):
                raise HTTPException(status_code=400, detail="模型未下载，请先下载模型")

            return {
                "success": False,
                "message": f"模型 {model_id} 加载失败"
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AdvancedModelsAPI] 加载模型 {model_id} 失败: {e}")
        raise HTTPException(status_code=500, detail=f"加载模型失败: {str(e)}") from e


@router.post("/{model_id}/unload")
async def unload_model_endpoint(model_id: str, user_id: str = Depends(get_current_user)):
    """
    卸载模型释放内存

    - **model_id**: 模型ID
    """
    try:
        logger.info(f"[AdvancedModelsAPI] 用户 {user_id} 请求卸载模型 {model_id}")

        advanced_model_manager.unload_model(model_id)

        return {
            "success": True,
            "message": f"模型 {model_id} 已卸载"
        }

    except Exception as e:
        logger.error(f"[AdvancedModelsAPI] 卸载模型 {model_id} 失败: {e}")
        raise HTTPException(status_code=500, detail=f"卸载模型失败: {str(e)}") from e


@router.get("/system/memory", response_model=MemoryStatusResponse)
async def get_memory_status(user_id: str = Depends(get_current_user)):
    """
    获取系统内存使用情况

    - 返回所有已加载模型的内存占用情况
    """
    try:
        models = advanced_model_manager.list_available_models()

        loaded_models = []
        total_memory = 0

        for model in models:
            status = advanced_model_manager.get_model_status(model.id)
            if status.get("loaded"):
                memory_usage = status.get("memory_usage", 0)
                loaded_models.append({
                    "id": model.id,
                    "name": model.id.replace('_', ' ').title(),
                    "memory_usage": memory_usage,
                    "size_bytes": model.size_bytes
                })
                total_memory += memory_usage

        return MemoryStatusResponse(
            total_loaded=len(loaded_models),
            total_memory_bytes=total_memory,
            total_memory_gb=round(total_memory / (1024**3), 2),
            loaded_models=loaded_models
        )

    except Exception as e:
        logger.error(f"[AdvancedModelsAPI] 获取内存状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取内存状态失败: {str(e)}") from e


# ============================================================================
# 模块导出
# ============================================================================
__all__ = ["router"]
