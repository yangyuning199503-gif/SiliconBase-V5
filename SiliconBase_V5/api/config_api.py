"""
配置管理 API 路由模块

提供配置文件的读取、保存、备份、恢复和热重载功能
"""

import asyncio
import logging
from pathlib import Path
from typing import Any

import aiofiles
from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)

# 导入认证依赖（SEC-003修复）
try:
    from api.cloud_api import get_current_user
except ImportError:
    async def get_current_user() -> str:
        return "default_user"

# 创建路由实例，设置前缀和标签
# 注意：认证在各自端点单独设置，GET端点公开访问，POST/PUT/DELETE需要认证
router = APIRouter(
    prefix="/config",
    tags=["config"]
)


# ============================================================================
# 端点 1: 获取配置 Schema
# ============================================================================
@router.get("/schema")
async def get_config_schema() -> dict[str, Any]:
    """
    获取配置项的 JSON Schema

    返回配置结构的元数据描述，用于前端表单验证和动态渲染

    Returns:
        Dict[str, Any]: 包含配置类型定义的字典
    """
    return {
        "type": "object",
        "properties": {
            "ai": {
                "type": "object",
                "description": "AI 模型相关配置"
            },
            "memory": {
                "type": "object",
                "description": "记忆系统相关配置"
            },
            "voice": {
                "type": "object",
                "description": "语音合成相关配置"
            }
        }
    }


# ============================================================================
# 端点 2: 获取 YAML 配置内容
# ============================================================================
@router.get("/yaml")
async def get_config_yaml() -> dict[str, Any]:
    """
    读取 global.yaml 配置文件内容
    """
    import yaml  # 确保yaml导入

    config_path = Path(__file__).parent.parent / "config" / "global.yaml"

    # 检查配置文件是否存在
    if not config_path.exists():
        raise HTTPException(status_code=404, detail="配置文件不存在")

    # 以 UTF-8 编码读取文件内容
    try:
        async with aiofiles.open(config_path, encoding='utf-8') as f:
            content = await f.read()
    except UnicodeDecodeError as e:
        raise HTTPException(status_code=500, detail=f"配置文件编码错误: {str(e)}") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取配置文件失败: {str(e)}") from e

    # 解析YAML内容为对象
    try:
        parsed = yaml.safe_load(content) if content else {}
    except Exception:
        parsed = {}

    # 返回前端期望的格式
    return {
        "success": True,
        "data": {
            "content": content,
            "parsed": parsed
        }
    }


# ============================================================================
# 端点 3: 保存 YAML 配置
# ============================================================================
@router.post("/yaml")
async def save_config_yaml(
    data: dict[str, Any],
    user_id: str = Depends(get_current_user)
) -> dict[str, bool]:
    """
    保存 YAML 配置到 global.yaml

    保存前会自动创建备份文件(.bak)，确保配置安全

    Args:
        data: 包含 "content" 字段的字典，内容为 YAML 字符串

    Returns:
        Dict[str, bool]: 操作结果状态

    Raises:
        HTTPException: 当保存失败时返回 500 错误
    """
    content = data.get("content", "")
    # 使用基于当前文件位置的绝对路径，确保在任何工作目录下都能正确找到配置文件
    config_path = Path(__file__).parent.parent / "config" / "global.yaml"

    try:
        # 确保配置目录存在
        await asyncio.to_thread(config_path.parent.mkdir, parents=True, exist_ok=True)

        # 备份原文件（如果存在）
        if config_path.exists():
            backup_path = config_path.with_suffix('.yaml.bak')
            try:
                async with aiofiles.open(config_path, encoding='utf-8') as f:
                    old_content = await f.read()
                async with aiofiles.open(backup_path, 'w', encoding='utf-8') as f:
                    await f.write(old_content)
            except Exception as e:
                # 备份失败不影响主流程，但记录错误
                print(f"[警告] 配置备份失败: {str(e)}")

        # 保存新内容到配置文件
        async with aiofiles.open(config_path, 'w', encoding='utf-8') as f:
            await f.write(content)

    except PermissionError as e:
        raise HTTPException(
            status_code=403,
            detail=f"没有权限写入配置文件: {str(e)}"
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"保存配置文件失败: {str(e)}"
        ) from e

    return {"success": True}


# ============================================================================
# 端点 4: 热重载配置
# ============================================================================
@router.post("/reload")
async def reload_config(user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    """
    触发配置热重载

    重新加载配置文件并应用到运行中的系统，无需重启服务

    Returns:
        Dict[str, Any]: 包含操作结果和状态消息

    Raises:
        HTTPException: 当重载失败时返回 500 错误
    """
    try:
        from core.config import config
        config.reload()
    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"配置模块导入失败: {str(e)}"
        ) from e
    except AttributeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"配置对象不支持重载: {str(e)}"
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"配置重载失败: {str(e)}"
        ) from e

    return {
        "success": True,
        "message": "配置已重载"
    }


# ============================================================================
# 端点 5: 获取备份列表
# ============================================================================
@router.get("/backups")
async def get_config_backups() -> dict[str, Any]:
    """
    获取所有配置备份列表

    扫描 config 目录下的所有 .yaml.bak 备份文件

    Returns:
        Dict: 包含 success 和 data 字段的标准响应格式
        data 中包含 backups 列表、count 和 max_backups
        每个备份包含 filename、path、size 和 created 字段
    """
    # 使用基于当前文件位置的绝对路径
    config_dir = Path(__file__).parent.parent / "config"
    max_backups = 10

    # 如果配置目录不存在，返回空列表
    if not config_dir.exists():
        return {
            "success": True,
            "data": {"backups": [], "count": 0, "max_backups": max_backups}
        }

    try:
        # 查找所有备份文件
        backups = list(config_dir.glob("*.yaml.bak"))

        # 构建备份信息列表
        backup_list = []
        for b in backups:
            try:
                stat = b.stat()
                backup_list.append({
                    "filename": b.name,
                    "path": str(b),
                    "size": stat.st_size,
                    "created": stat.st_mtime
                })
            except OSError:
                # 忽略无法访问的备份文件
                continue

        # 按创建时间降序排序
        backup_list.sort(key=lambda x: x["created"], reverse=True)

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"扫描备份文件失败: {str(e)}"
        ) from e

    return {
        "success": True,
        "data": {
            "backups": backup_list,
            "count": len(backup_list),
            "max_backups": max_backups
        }
    }


# ============================================================================
# 端点 6: 恢复备份
# ============================================================================
@router.post("/restore")
async def restore_config_backup(
    data: dict[str, Any],
    user_id: str = Depends(get_current_user)
) -> dict[str, bool]:
    """
    从备份文件恢复配置

    将指定的备份文件内容恢复到 global.yaml

    Args:
        data: 包含 "filename" 字段的字典，指定要恢复的备份文件名

    Returns:
        Dict[str, bool]: 操作结果状态

    Raises:
        HTTPException: 当备份文件不存在或恢复失败时返回错误
    """
    # 支持两种字段名：filename（后端原始）和 backup_filename（前端实际发送）
    filename = data.get("filename") or data.get("backup_filename")

    # 参数验证
    if not filename:
        raise HTTPException(
            status_code=400,
            detail="必须提供文件名参数（filename 或 backup_filename）"
        )

    # 防止路径遍历攻击
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(
            status_code=400,
            detail="无效的文件名"
        )

    # 使用基于当前文件位置的绝对路径
    config_base = Path(__file__).parent.parent / "config"
    backup_path = config_base / filename

    # 检查备份文件是否存在
    if not backup_path.exists():
        raise HTTPException(
            status_code=404,
            detail="备份文件不存在"
        )

    config_path = config_base / "global.yaml"

    try:
        # 读取备份内容并写入配置文件
        async with aiofiles.open(backup_path, encoding='utf-8') as f:
            backup_content = await f.read()
        async with aiofiles.open(config_path, 'w', encoding='utf-8') as f:
            await f.write(backup_content)
    except PermissionError as e:
        raise HTTPException(
            status_code=403,
            detail=f"没有权限恢复配置文件: {str(e)}"
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"恢复备份失败: {str(e)}"
        ) from e

    return {"success": True}


# ============================================================================
# 端点 7: 更新配置项
# ============================================================================
@router.post("")
async def update_config(
    data: dict[str, Any],
    user_id: str = Depends(get_current_user)
) -> dict[str, bool]:
    """
    更新单个或多个配置项

    通过键值对方式更新配置，支持嵌套配置路径（如 "ai.model"）

    Args:
        data: 配置键值对字典，key 为配置路径，value 为新值

    Returns:
        Dict[str, bool]: 操作结果状态

    Raises:
        HTTPException: 当配置模块导入失败或更新失败时返回错误
    """
    try:
        from core.config import config
    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"配置模块导入失败: {str(e)}"
        ) from e

    # 遍历并更新所有配置项
    try:
        for key, value in data.items():
            config.set(key, value)
    except AttributeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"配置对象不支持 set 方法: {str(e)}"
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"更新配置失败: {str(e)}"
        ) from e

    # 【新增】检测是否更新了AI相关配置，如果是则刷新缓存
    ai_config_keys = ["ai.provider", "ai.config", "ai.model", "ai.default_model",
                      "ai.temperature", "ai.max_tokens", "ai.vision"]
    updated_ai_keys = [k for k in data if any(k.startswith(ai_key) for ai_key in ai_config_keys)]

    if updated_ai_keys:
        logger.warning(f"[ConfigAPI] 通过通用配置接口修改AI配置 {updated_ai_keys}，建议改用 /ai/config 端点以获得更完整的缓存刷新")
        logger.info(f"[ConfigAPI] 检测到AI配置更新: {updated_ai_keys}")

        # 1. 刷新 AI Provider Factory
        try:
            from core.providers.ai_provider_factory import AIProviderFactory
            AIProviderFactory.refresh_provider()
            logger.info("[ConfigAPI] AI Provider Factory 缓存已刷新")
        except Exception as e:
            logger.error(f"[ConfigAPI] AI Provider Factory 刷新失败: {e}", exc_info=True)

        # 2. 刷新 ai_adapter
        try:
            from core import ai_adapter
            if hasattr(ai_adapter, '_current_provider'):
                ai_adapter._current_provider = None
                logger.info("[ConfigAPI] ai_adapter 缓存已刷新")
        except Exception as e:
            logger.error(f"[ConfigAPI] ai_adapter 刷新失败: {e}", exc_info=True)

        # 3. 刷新 AIClient
        try:
            from core.ai.ai_client import get_default_client
            client = get_default_client()
            if client and hasattr(client, '_provider'):
                client._provider = None
                logger.info("[ConfigAPI] AIClient 缓存已刷新")
        except Exception as e:
            logger.error(f"[ConfigAPI] AIClient 刷新失败: {e}", exc_info=True)

        # 4. 刷新 ModelRouter
        try:
            from core.ai.model_router import reset_model_router
            reset_model_router()
            logger.info("[ConfigAPI] ModelRouter 已重置")
        except Exception as e:
            logger.error(f"[ConfigAPI] ModelRouter 重置失败: {e}", exc_info=True)

        # 5. 强制递增版本号
        try:
            config.increment_version()
            logger.info(f"[ConfigAPI] 配置版本号已递增到: {config.get_version()}")
        except Exception as e:
            logger.error(f"[ConfigAPI] 版本号递增失败: {e}", exc_info=True)

    logger.info(f"[ConfigAPI] 配置更新完成，共更新 {len(data)} 项")
    return {"success": True}
