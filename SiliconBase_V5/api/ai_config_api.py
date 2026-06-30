"""
AI 配置管理 API 路由模块

提供AI Provider配置相关的API端点，包括：
- 获取Provider列表
- 获取/更新当前配置
- 测试配置
- 获取模型列表
- 视觉配置管理（新增）
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

# 配置日志记录器
logger = logging.getLogger(__name__)

# 创建路由实例
router = APIRouter(prefix="/ai", tags=["ai_config"])


# ============================================================================
# 导入认证依赖 - 使用独立的auth_utils模块避免循环导入
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
        logger.warning(f"[AIConfigAPI] 认证模块导入失败: {e}")
        async def _fallback_get_current_user():
            raise HTTPException(status_code=500, detail="认证模块不可用")
        get_current_user = _fallback_get_current_user


# ============================================================================
# 导入Provider Factory
# ============================================================================
try:
    from core.providers.ai_provider_factory import AIProviderFactory
    PROVIDER_FACTORY_AVAILABLE = True
except ImportError as e:
    PROVIDER_FACTORY_AVAILABLE = False
    logger.warning(f"[AIConfigAPI] Provider Factory导入失败: {e}")


# ============================================================================
# 辅助函数：刷新视觉配置缓存
# ============================================================================
def _refresh_vision_cache():
    """
    刷新视觉工具的配置缓存

    当视觉配置变更时调用，确保 vision_agent 等工具使用最新配置
    """
    try:
        # 刷新 vision_agent 工具的缓存
        from core.tool.tool_manager import tool_manager
        vision_tool = tool_manager.get_tool("vision_agent")
        if vision_tool and hasattr(vision_tool, 'clear_provider_cache'):
            vision_tool.clear_provider_cache()
            logger.info("[AIConfigAPI] vision_agent 缓存已刷新")
    except Exception as e:
        logger.error(f"[AIConfigAPI] 刷新 vision_agent 缓存失败: {e}", exc_info=True)

    try:
        # 刷新 visual_understand 工具（如果有缓存）
        from core.tool.tool_manager import tool_manager
        visual_tool = tool_manager.get_tool("visual_understand")
        if visual_tool and hasattr(visual_tool, 'clear_cache'):
            visual_tool.clear_cache()
            logger.info("[AIConfigAPI] visual_understand 缓存已刷新")
    except Exception as e:
        logger.error(f"[AIConfigAPI] 刷新 visual_understand 缓存失败: {e}", exc_info=True)


def _save_vision_config(config, vision_config: dict[str, Any]) -> bool:
    """
    保存视觉配置到配置中心

    Args:
        config: 配置中心实例
        vision_config: 视觉配置字典

    Returns:
        是否保存成功
    """
    try:
        # 1. 保存完整的 vision 配置到 ai.vision
        config.set("ai.vision", vision_config)

        # 2. 同时更新 ai.vision.backends（兼容 vision_agent）
        backends = vision_config.get("backends", {})
        if backends:
            config.set("ai.vision.backends", backends)

        # 3. 更新 ai.vision.default_backend（兼容 vision_agent）
        default_backend = vision_config.get("default_backend")
        if default_backend:
            config.set("ai.vision.default_backend", default_backend)

        # 4. 向后兼容：同时更新 ai.vision.model（嵌套路径）和 ai.vision_model（扁平路径）
        # 优先从第一个backend获取model
        if backends and default_backend and default_backend in backends:
            default_model = backends[default_backend].get("model")
            if default_model:
                config.set("ai.vision.model", default_model)
                config.set("ai.vision_model", default_model)

        logger.info("[AIConfigAPI] 视觉配置已保存")
        return True

    except Exception as e:
        logger.error(f"[AIConfigAPI] 保存视觉配置失败: {e}")
        return False


def _get_vision_config(config) -> dict[str, Any]:
    """
    获取视觉配置

    Args:
        config: 配置中心实例

    Returns:
        视觉配置字典
    """
    vision_config = config.get("ai.vision", {})

    # 如果 ai.vision 为空，尝试从 legacy 配置构建
    if not vision_config:
        vision_model = config.get("ai.vision_model")
        if vision_model:
            vision_config = {
                "default_backend": "default",
                "backends": {
                    "default": {
                        "name": "Default Vision Model",
                        "model": vision_model,
                        "provider": config.get("ai.provider", "ollama"),
                        "base_url": config.get("ai.config.base_url", "http://localhost:11434"),
                        "capabilities": ["description", "qa", "ocr"],
                        "supports_vision": True
                    }
                }
            }

    return vision_config


# ============================================================================
# 端点 1: 获取AI Provider列表
# ============================================================================
@router.get("/providers")
async def get_ai_providers(
    user_id: str = Depends(get_current_user)
) -> dict[str, Any]:
    """
    获取所有可用的AI Provider列表

    返回每个Provider的详细信息，包括名称、分类、描述和配置要求

    - **user_id**: 从认证token解析的用户ID

    Returns:
        {
            "success": True,
            "data": [
                {
                    "type": "ollama",
                    "name": "Ollama",
                    "category": "local",
                    "description": "本地Ollama服务",
                    "required_config": [],
                    "optional_config": ["base_url", "model", "timeout"],
                    "default_model": "qwen3:8b"
                },
                ...
            ],
            "message": "获取Provider列表成功"
        }
    """
    if not PROVIDER_FACTORY_AVAILABLE:
        return {
            "success": False,
            "error": "Provider Factory模块不可用",
            "data": [],
            "message": "AI Provider系统未正确加载"
        }

    try:
        providers = AIProviderFactory.list_supported_providers()
        provider_list = []

        for provider_type in providers:
            info = AIProviderFactory.get_provider_info(provider_type)
            provider_list.append({
                "type": provider_type,
                "name": info.get("name", provider_type),
                "category": info.get("category", "other"),
                "description": info.get("description", ""),
                "required_config": info.get("required_config", []),
                "optional_config": info.get("optional_config", []),
                "default_model": info.get("default_model", "")
            })

        return {
            "success": True,
            "data": provider_list,
            "message": "获取Provider列表成功"
        }

    except Exception as e:
        logger.error(f"[AIConfigAPI] 获取Provider列表失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "data": [],
            "message": "获取Provider列表失败"
        }


# ============================================================================
# 端点 2: 获取当前AI配置
# ============================================================================
@router.get("/config")
async def get_ai_config(
    user_id: str = Depends(get_current_user)
) -> dict[str, Any]:
    """
    获取当前AI配置

    返回当前使用的Provider类型和配置（不包含敏感信息如API Key）

    - **user_id**: 从认证token解析的用户ID

    Returns:
        {
            "success": True,
            "data": {
                "provider": "ollama",
                "config": {
                    "base_url": "http://localhost:11434",
                    "model": "qwen3:8b",
                    "timeout": 30
                },
                "available_providers": ["ollama", "openai", ...]
            },
            "message": "获取配置成功"
        }
    """
    try:
        from core.config import config

        provider_type = config.get("ai.provider", "ollama")
        provider_config = config.get("ai.config", {})

        # 过滤掉敏感信息
        safe_config = {k: v for k, v in provider_config.items()
                      if "key" not in k.lower() and "secret" not in k.lower()}

        available_providers = AIProviderFactory.list_supported_providers() \
            if PROVIDER_FACTORY_AVAILABLE else []

        return {
            "success": True,
            "data": {
                "provider": provider_type,
                "config": safe_config,
                "available_providers": available_providers
            },
            "message": "获取配置成功"
        }

    except Exception as e:
        logger.error(f"[AIConfigAPI] 获取AI配置失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "data": None,
            "message": "获取配置失败"
        }


# ============================================================================
# 端点 3: 更新AI配置
# ============================================================================
class UpdateAIConfigRequest:
    """更新AI配置请求模型"""
    provider: str
    config: dict[str, Any]
    persist: bool = True
    save_api_key: bool = False
    vision: dict[str, Any] | None = None  # 新增：视觉配置


@router.post("/config")
async def update_ai_config(
    request: dict[str, Any],
    user_id: str = Depends(get_current_user)
) -> dict[str, Any]:
    """
    更新AI配置

    更新当前使用的Provider和相关配置，支持视觉配置保存

    - **provider**: Provider类型（如 "ollama", "openai"）
    - **config**: Provider配置字典
    - **persist**: 是否持久化到配置文件（默认True）
    - **save_api_key**: 是否保存API Key（默认False，为安全考虑）
    - **vision**: 视觉配置字典（可选）
        - **default_backend**: 默认视觉后端名称
        - **backends**: 视觉后端配置字典
        - **model**: 视觉模型名称（向后兼容）

    Returns:
        {
            "success": True,
            "message": "配置已更新",
            "refreshed": True,
            "vision_updated": True  # 新增：视觉配置是否已更新
        }
    """
    try:
        from core.config import config

        provider_type = request.get("provider")
        provider_config = request.get("config", {})
        persist = request.get("persist", True)
        request.get("save_api_key", False)
        vision_config = request.get("vision")  # 新增：视觉配置

        if not provider_type:
            return {
                "success": False,
                "error": "缺少provider参数",
                "message": "必须指定Provider类型"
            }

        # 验证Provider类型是否有效
        if PROVIDER_FACTORY_AVAILABLE:
            available = AIProviderFactory.list_supported_providers()
            if provider_type.lower() not in available:
                return {
                    "success": False,
                    "error": f"不支持的Provider类型: {provider_type}",
                    "message": f"支持的类型: {available}"
                }

        # 更新主AI配置
        config.set("ai.provider", provider_type.lower())
        config.set("ai.config", provider_config)

        # 同时保存到 ai.providers.<provider_type> 以确保一致性
        # 这是为了兼容 ai_provider_factory.py 中的配置读取逻辑
        config.set(f"ai.providers.{provider_type.lower()}", provider_config)

        # 处理视觉配置（如果提供）
        vision_updated = False
        if vision_config is not None:
            if _save_vision_config(config, vision_config):
                vision_updated = True
                # 刷新视觉工具缓存
                _refresh_vision_cache()
            else:
                # 发生异常时记录 ERROR 日志
                logger.error("[AIConfigAPI] 保存视觉配置失败，主配置已更新但视觉配置保存失败")
                return {
                    "success": False,
                    "error": "保存视觉配置失败",
                    "message": "主配置已更新，但视觉配置保存失败"
                }

        # 持久化配置（如果需要）
        # 注意：config.set() 内部已自动调用 _save_config() 和 increment_version()，无需额外保存
        if persist:
            logger.debug("[AIConfigAPI] 配置已通过 config.set() 自动持久化")

        # 刷新Provider实例
        refreshed = False
        if PROVIDER_FACTORY_AVAILABLE:
            try:
                AIProviderFactory.refresh_provider()
                refreshed = True
                logger.info("[AIConfigAPI] AI Provider已刷新")
            except Exception as e:
                # 【修复】所有 Exception 必须打 ERROR 日志
                logger.error(f"[AIConfigAPI] 刷新Provider失败: {e}", exc_info=True)

        # 获取当前配置版本号
        config_version = config.get_version()
        logger.info(f"[AIConfigAPI] AI配置已更新，当前版本号: {config_version}")

        # 4. 【新增】刷新 ai_adapter 缓存
        try:
            from core import ai_adapter
            if hasattr(ai_adapter, '_current_provider'):
                ai_adapter._current_provider = None
                logger.info("[AIConfigAPI] ai_adapter 缓存已刷新")
        except Exception as e:
            logger.error(f"[AIConfigAPI] ai_adapter 刷新失败: {e}", exc_info=True)

        # 5. 【新增】刷新 AIClient 缓存
        try:
            from core.ai.ai_client import get_default_client
            client = get_default_client()
            if hasattr(client, '_provider'):
                client._provider = None
                logger.info("[AIConfigAPI] AIClient 缓存已刷新")
        except Exception as e:
            logger.error(f"[AIConfigAPI] AIClient 刷新失败: {e}", exc_info=True)

        # 6. 【新增】重置 ModelRouter
        # 原因：ModelRouter 的 providers 在初始化时从环境变量读取，
        # 当用户通过API修改配置时，需要重置以使新配置生效
        try:
            from core.ai.model_router import reset_model_router
            reset_model_router()
            logger.info("[AIConfigAPI] ModelRouter 已重置")
        except Exception as e:
            # 【铁律】异常必须打 ERROR 级别日志，禁止静默
            logger.error(f"[AIConfigAPI] ModelRouter 重置失败: {e}", exc_info=True)

        return {
            "success": True,
            "message": "配置已更新",
            "refreshed": refreshed,
            "vision_updated": vision_updated,
            "version": config_version  # 保持与API文档一致，使用 "version" 字段名
        }

    except Exception as e:
        logger.error(f"[AIConfigAPI] 更新AI配置失败: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "message": "更新配置失败"
        }


# ============================================================================
# 端点 4: 测试AI配置
# ============================================================================
@router.post("/test")
async def test_ai_config(
    request: dict[str, Any],
    user_id: str = Depends(get_current_user)
) -> dict[str, Any]:
    """
    测试AI配置是否有效

    测试指定的Provider配置是否可以正常连接和使用

    - **provider**: Provider类型
    - **config**: Provider配置字典

    Returns:
        {
            "success": True,
            "message": "连接成功！模型可正常使用。",
            "available_models": ["qwen3:8b", "llama3.1:8b", ...],
            "response_preview": "Hello! How can I help you today?"
        }
    """
    if not PROVIDER_FACTORY_AVAILABLE:
        return {
            "success": False,
            "error": "Provider Factory模块不可用",
            "message": "AI Provider系统未正确加载",
            "available_models": []
        }

    provider_type = request.get("provider")
    provider_config = request.get("config", {})

    if not provider_type:
        return {
            "success": False,
            "error": "缺少provider参数",
            "message": "必须指定Provider类型",
            "available_models": []
        }

    try:
        result = AIProviderFactory.test_provider(provider_type, provider_config)
        return result

    except Exception as e:
        logger.error(f"[AIConfigAPI] 测试AI配置失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "测试配置时发生错误",
            "available_models": []
        }


# ============================================================================
# 端点 5: 获取模型列表（核心缺失端点）
# ============================================================================
@router.get("/models")
async def get_ai_models(
    provider: str | None = Query(None, description="Provider类型，为空则使用当前配置"),
    vision: bool = Query(False, description="是否只返回支持视觉的模型"),
    user_id: str = Depends(get_current_user)
) -> dict[str, Any]:
    """
    获取AI模型列表

    获取指定Provider或当前Provider的可用模型列表。
    支持按视觉能力筛选模型。

    - **provider**: Provider类型（可选，如 "ollama", "openai"）
    - **vision**: 是否只返回支持视觉的模型（默认False）
    - **user_id**: 从认证token解析的用户ID

    Returns:
        {
            "success": True,
            "data": ["qwen3:8b", "llama3.1:8b", "gpt-4", ...],
            "message": "获取模型列表成功",
            "provider": "ollama",
            "total": 10,
            "vision_filtered": false
        }
    """
    if not PROVIDER_FACTORY_AVAILABLE:
        return {
            "success": False,
            "error": "Provider Factory模块不可用",
            "data": [],
            "message": "AI Provider系统未正确加载",
            "provider": provider,
            "total": 0,
            "vision_filtered": vision
        }

    provider_instance = None
    actual_provider = provider

    try:
        # 获取Provider实例
        if provider:
            # 创建指定Provider实例
            # 如果提供了配置，尝试从请求或配置文件获取
            try:
                from core.config import config
                provider_config = config.get("ai.config", {})
            except ImportError:
                provider_config = {}

            provider_instance = AIProviderFactory.create_provider(
                provider, **provider_config
            )
            actual_provider = provider
        else:
            # 获取当前配置的Provider
            provider_instance = AIProviderFactory.get_current_provider()

            # 获取当前Provider的类型
            try:
                from core.config import config
                actual_provider = config.get("ai.provider", "ollama")
            except ImportError:
                actual_provider = "unknown"

        # 检查Provider是否可用
        if not provider_instance.is_available():
            return {
                "success": False,
                "error": f"Provider '{actual_provider}' 当前不可用",
                "data": [],
                "message": f"无法连接到 {actual_provider} 服务，请检查服务是否运行",
                "provider": actual_provider,
                "total": 0,
                "vision_filtered": vision
            }

        # 获取模型列表
        models = provider_instance.get_model_list()

        # 如果需要筛选vision模型
        if vision and models:
            capabilities = provider_instance.get_capabilities()

            if not capabilities.vision:
                # Provider本身不支持vision，返回空列表或提示
                return {
                    "success": True,
                    "data": [],
                    "message": f"Provider '{actual_provider}' 不支持视觉能力",
                    "provider": actual_provider,
                    "total": 0,
                    "vision_filtered": True,
                    "vision_supported": False
                }

            # 筛选支持vision的模型（基于命名启发式）
            # 常见的vision模型命名模式
            vision_keywords = [
                "vision", "vl", "multimodal", "image", "gpt-4o",
                "claude-3", "llava", "bakllava", "qwen-vl", "yi-vl"
            ]

            filtered_models = []
            for model in models:
                model_lower = model.lower()
                if any(keyword in model_lower for keyword in vision_keywords):
                    filtered_models.append(model)

            models = filtered_models

        return {
            "success": True,
            "data": models,
            "message": "获取模型列表成功",
            "provider": actual_provider,
            "total": len(models),
            "vision_filtered": vision,
            "vision_supported": vision and provider_instance.get_capabilities().vision
        }

    except ValueError as e:
        # Provider类型无效
        logger.warning(f"[AIConfigAPI] 无效的Provider类型 '{provider}': {e}")
        return {
            "success": False,
            "error": str(e),
            "data": [],
            "message": f"不支持的Provider类型: {provider}",
            "provider": provider,
            "total": 0,
            "vision_filtered": vision
        }

    except Exception as e:
        logger.error(f"[AIConfigAPI] 获取模型列表失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "data": [],
            "message": "获取模型列表失败",
            "provider": actual_provider or provider,
            "total": 0,
            "vision_filtered": vision
        }


# ============================================================================
# 端点 6: 获取特定Provider的模型列表（路径参数版本）
# ============================================================================
@router.get("/models/{provider}")
async def get_provider_models(
    provider: str,
    vision: bool = Query(False, description="是否只返回支持视觉的模型"),
    user_id: str = Depends(get_current_user)
) -> dict[str, Any]:
    """
    获取指定Provider的模型列表

    路径参数版本，与查询参数版本 `/models?provider=xxx` 功能相同

    - **provider**: Provider类型（路径参数，如 "ollama", "openai"）
    - **vision**: 是否只返回支持视觉的模型（默认False）
    - **user_id**: 从认证token解析的用户ID
    """
    # 复用主端点逻辑
    return await get_ai_models(provider=provider, vision=vision, user_id=user_id)


# ============================================================================
# 端点 7: 获取视觉配置（新增）
# ============================================================================
@router.get("/config/vision")
async def get_vision_config_endpoint(
    user_id: str = Depends(get_current_user)
) -> dict[str, Any]:
    """
    获取当前视觉配置

    返回当前配置的视觉后端设置，包括默认后端和所有可用后端配置

    - **user_id**: 从认证token解析的用户ID

    Returns:
        {
            "success": True,
            "data": {
                "default_backend": "qwen3-vl",
                "backends": {
                    "qwen3-vl": {
                        "name": "Qwen3-VL",
                        "model": "qwen3-vl:8b",
                        "provider": "ollama",
                        "base_url": "http://localhost:11434",
                        "capabilities": ["description", "qa", "ocr"],
                        "supports_vision": true
                    },
                    "ui-tars": {
                        "name": "UI-TARS",
                        "model": "ui-tars",
                        "provider": "ollama",
                        "base_url": "http://localhost:11434",
                        "capabilities": ["gui_action", "coordinate"],
                        "supports_vision": true
                    }
                },
                "legacy_model": "qwen3-vl:8b"  # 向后兼容
            },
            "message": "获取视觉配置成功"
        }
    """
    try:
        from core.config import config

        # 获取视觉配置
        vision_config = _get_vision_config(config)

        # 获取向后兼容的legacy配置
        legacy_model = config.get("ai.vision_model")

        # 构建返回数据（过滤敏感信息）
        safe_config = {}
        if vision_config:
            safe_config = {
                "default_backend": vision_config.get("default_backend"),
                "backends": {}
            }

            # 过滤backend配置中的敏感信息
            for backend_name, backend_config in vision_config.get("backends", {}).items():
                safe_backend = {k: v for k, v in backend_config.items()
                               if "key" not in k.lower() and "secret" not in k.lower()}
                safe_config["backends"][backend_name] = safe_backend

        # 如果视觉配置为空，返回友好的提示
        if not safe_config:
            return {
                "success": True,
                "data": {
                    "default_backend": None,
                    "backends": {},
                    "legacy_model": legacy_model,
                    "configured": False
                },
                "message": "视觉配置尚未设置，请先配置视觉模型"
            }

        safe_config["legacy_model"] = legacy_model
        safe_config["configured"] = True

        return {
            "success": True,
            "data": safe_config,
            "message": "获取视觉配置成功"
        }

    except Exception as e:
        logger.error(f"[AIConfigAPI] 获取视觉配置失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "data": None,
            "message": "获取视觉配置失败"
        }


# ============================================================================
# 端点 8: 更新视觉配置（新增 - 独立端点）
# ============================================================================
@router.post("/config/vision")
async def update_vision_config(
    request: dict[str, Any],
    user_id: str = Depends(get_current_user)
) -> dict[str, Any]:
    """
    更新视觉配置

    独立更新视觉配置，不影响主AI配置

    - **default_backend**: 默认视觉后端名称
    - **backends**: 视觉后端配置字典
        - **name**: 后端显示名称
        - **model**: 模型名称
        - **provider**: Provider类型 (ollama/openai/anthropic等)
        - **base_url**: 服务地址
        - **capabilities**: 能力列表
        - **supports_vision**: 是否支持视觉
    - **persist**: 是否持久化到配置文件（默认True）

    Returns:
        {
            "success": True,
            "message": "视觉配置已更新",
            "vision_refreshed": True
        }
    """
    try:
        from core.config import config

        # 验证请求体
        if not request:
            return {
                "success": False,
                "error": "缺少配置参数",
                "message": "必须提供视觉配置参数"
            }

        # 构建视觉配置
        vision_config = {
            "default_backend": request.get("default_backend"),
            "backends": request.get("backends", {})
        }

        # 验证必要字段
        if not vision_config["default_backend"]:
            return {
                "success": False,
                "error": "缺少default_backend",
                "message": "必须指定默认视觉后端"
            }

        if not vision_config["backends"]:
            return {
                "success": False,
                "error": "缺少backends配置",
                "message": "必须至少配置一个视觉后端"
            }

        # 验证默认后端是否存在
        if vision_config["default_backend"] not in vision_config["backends"]:
            return {
                "success": False,
                "error": "无效的default_backend",
                "message": f"默认后端 '{vision_config['default_backend']}' 不在backends配置中"
            }

        persist = request.get("persist", True)

        # 保存视觉配置
        if not _save_vision_config(config, vision_config):
            # 【铁律】防御性代码必须记录 ERROR 日志
            logger.error("[AIConfigAPI] 保存视觉配置失败")
            return {
                "success": False,
                "error": "保存失败",
                "message": "视觉配置保存失败"
            }

        # 持久化配置
        # 注意：config.set() 内部已自动调用 _save_config()，无需额外保存
        if persist:
            logger.debug("[AIConfigAPI] 视觉配置已通过 config.set() 自动持久化")

        # 刷新视觉工具缓存
        _refresh_vision_cache()

        # 更新配置版本号（关键：用于配置刷新冲突检测）
        config.increment_version()
        config_version = config.get_version()
        logger.info(f"[AIConfigAPI] 视觉配置已更新，当前版本号: {config_version}")

        return {
            "success": True,
            "message": "视觉配置已更新",
            "vision_refreshed": True,
            "config_version": config_version
        }

    except Exception as e:
        logger.error(f"[AIConfigAPI] 更新视觉配置失败: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "message": "更新视觉配置失败"
        }


# ============================================================================
# 端点 9: 测试视觉配置（新增）
# ============================================================================
@router.post("/test/vision")
async def test_vision_config(
    request: dict[str, Any],
    user_id: str = Depends(get_current_user)
) -> dict[str, Any]:
    """
    测试视觉配置是否有效

    测试指定的视觉后端配置是否可以正常连接和使用

    - **backend**: 后端名称（如 "qwen3-vl", "ui-tars"）
    - **config**: 后端配置字典（如果不提供，从当前配置读取）

    Returns:
        {
            "success": True,
            "message": "视觉模型连接成功！",
            "available_models": ["qwen3-vl:8b", ...],
            "backend": "qwen3-vl"
        }
    """
    if not PROVIDER_FACTORY_AVAILABLE:
        return {
            "success": False,
            "error": "Provider Factory模块不可用",
            "message": "AI Provider系统未正确加载",
            "available_models": []
        }

    backend_name = request.get("backend")
    backend_config = request.get("config")

    try:
        from core.config import config

        # 如果没有提供配置，从当前配置读取
        if not backend_config:
            vision_config = _get_vision_config(config)
            backends = vision_config.get("backends", {})

            if not backend_name:
                backend_name = vision_config.get("default_backend")

            if backend_name and backend_name in backends:
                backend_config = backends[backend_name]
            else:
                return {
                    "success": False,
                    "error": "配置未找到",
                    "message": f"后端 '{backend_name}' 未配置",
                    "available_models": []
                }

        # 获取Provider类型和配置
        provider_type = backend_config.get("provider", "ollama")
        provider_config = {
            "base_url": backend_config.get("base_url", "http://localhost:11434"),
            "model": backend_config.get("model"),
            "timeout": backend_config.get("timeout", 60)
        }

        # 如果需要API key
        if backend_config.get("requires_api_key"):
            api_key = backend_config.get("api_key")
            if api_key:
                provider_config["api_key"] = api_key

        # 测试Provider
        result = AIProviderFactory.test_provider(provider_type, provider_config)
        result["backend"] = backend_name

        # 额外检查视觉能力
        if result.get("success"):
            capabilities = result.get("capabilities", {})
            if not capabilities.get("vision"):
                result["warning"] = "该Provider报告不支持视觉能力，但配置中标记为支持"

        return result

    except Exception as e:
        logger.error(f"[AIConfigAPI] 测试视觉配置失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "测试视觉配置时发生错误",
            "available_models": [],
            "backend": backend_name
        }


# ============================================================================
# 模块导出
# ============================================================================
__all__ = ["router"]
