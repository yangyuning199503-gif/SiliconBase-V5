#!/usr/bin/env python3
"""
功能管理API - SiliconBase V5 插排架构

提供功能状态查询、开关控制、依赖检查等接口。

Endpoints:
    GET    /api/features                    获取所有功能状态
    GET    /api/features/{feature_id}       获取特定功能详情
    POST   /api/features/{feature_id}/enable   启用功能
    POST   /api/features/{feature_id}/disable  禁用功能
    GET    /api/features/dependencies/check    运行依赖检查
    GET    /api/features/dependencies/missing  获取缺失依赖
    POST   /api/features/dependencies/install  安装依赖
    GET    /api/features/categories         获取功能分类
    POST   /api/features/refresh            刷新功能状态
"""

import time
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from core.config import config
from core.feature_manager import FeatureCategory, FeatureState, feature_manager
from core.logger import logger
from core.utils.dependency_checker import DependencyStatus, DependencyType, dependency_checker

# 导入认证依赖
try:
    from api.cloud_api import get_current_user
except ImportError:
    from .cloud_api import get_current_user

# 创建路由
features_router = APIRouter(prefix="/features", tags=["features"])

# 额外路由（不带前缀）用于系统级端点
system_router = APIRouter(tags=["system"])


# ═══════════════════════════════════════════════════════════════
# Pydantic 模型
# ═══════════════════════════════════════════════════════════════

class FeatureStatus(BaseModel):
    """功能状态模型"""
    id: str
    name: str
    description: str
    category: str
    enabled: bool
    state: str
    available: bool
    configurable: bool = True
    requires_restart: bool = False
    error_message: str | None = None
    sub_features: list[dict[str, Any]] = Field(default_factory=list)
    dependencies: list[dict[str, Any]] = Field(default_factory=list)


class DependencyInfo(BaseModel):
    """依赖信息模型"""
    name: str
    type: str
    required: bool = False
    feature: str | None = None
    description: str | None = None
    status: str
    version: str | None = None
    message: str | None = None
    install_cmd: str | None = None
    download_url: str | None = None
    size: str | None = None


class FeatureSummary(BaseModel):
    """功能摘要模型"""
    total: int
    enabled: int
    available: int
    running: int
    degraded: bool


class FeaturesResponse(BaseModel):
    """功能列表响应"""
    features: list[FeatureStatus]
    summary: FeatureSummary


class FeatureDetailResponse(BaseModel):
    """功能详情响应"""
    feature: FeatureStatus
    config: dict[str, Any]
    dependencies: list[DependencyInfo]
    missing_deps: list[DependencyInfo]
    install_guide: str | None = None


class DependencyCheckResponse(BaseModel):
    """依赖检查响应"""
    available: list[DependencyInfo]
    missing: list[DependencyInfo]
    optional: list[DependencyInfo]
    errors: list[DependencyInfo]
    all_ok: bool


class InstallRequest(BaseModel):
    """安装请求"""
    dependency_name: str


class InstallResponse(BaseModel):
    """安装响应"""
    success: bool
    message: str
    dependency: str | None = None


class EnableRequest(BaseModel):
    """启用功能请求"""
    confirm_restart: bool = False  # 确认需要重启


class FeatureActionResponse(BaseModel):
    """功能操作响应"""
    success: bool
    feature_id: str
    message: str
    requires_restart: bool = False
    new_state: str


class CategoryInfo(BaseModel):
    """分类信息"""
    id: str
    name: str
    description: str


class CategoriesResponse(BaseModel):
    """分类列表响应"""
    categories: list[CategoryInfo]


class ModeSwitchRequest(BaseModel):
    """模式切换请求"""
    mode: str  # "daily" or "focus"
    reason: str = ""


class ModeSwitchResponse(BaseModel):
    """模式切换响应"""
    success: bool
    mode: str
    message: str = ""


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════

def _feature_to_status(feature) -> FeatureStatus:
    """将功能实例转换为状态模型"""
    info = feature.info

    # 获取子功能状态
    sub_features = []
    if hasattr(feature, 'get_status'):
        status = feature.get_status()
        sub_features = status.get("sub_features", [])

    # 获取依赖
    dependencies = []
    try:
        deps = feature.get_dependencies()
        dependencies = [d.to_dict() for d in deps]
    except Exception as e:
        logger.error(f"[FeaturesAPI] 获取功能依赖失败: {e}", exc_info=True)

    return FeatureStatus(
        id=info.id,
        name=info.name,
        description=info.description,
        category=info.category.value,
        enabled=info.enabled,
        state=info.state.value,
        available=info.available,
        configurable=info.configurable,
        requires_restart=info.requires_restart,
        error_message=info.error_message,
        sub_features=sub_features,
        dependencies=dependencies
    )


def _dep_to_info(dep) -> DependencyInfo:
    """将依赖转换为信息模型"""
    return DependencyInfo(
        name=dep.name,
        type=dep.type.value if isinstance(dep.type, DependencyType) else dep.type,
        required=dep.required,
        feature=dep.feature,
        description=dep.description,
        status=dep.status.value if isinstance(dep.status, DependencyStatus) else dep.status,
        version=dep.version,
        message=dep.message,
        install_cmd=dep.install_cmd,
        download_url=dep.download_url,
        size=dep.size
    )


# ═══════════════════════════════════════════════════════════════
# API 端点
# ═══════════════════════════════════════════════════════════════

@features_router.get("", response_model=FeaturesResponse)
async def get_all_features(
    category: str | None = None,
    enabled_only: bool = False
):
    """
    获取所有功能状态

    Args:
        category: 按分类过滤 (core, perception, cognition, memory, consciousness, extension)
        enabled_only: 只返回启用的功能

    Returns:
        功能列表和摘要
    """
    try:
        # 转换分类
        cat = None
        if category:
            try:
                cat = FeatureCategory(category)
            except ValueError as _exc:
                raise HTTPException(status_code=400, detail=f"无效的分类: {category}") from _exc

        # 获取功能列表
        feature_list = feature_manager.list_features(
            category=cat,
            enabled_only=enabled_only
        )

        # 转换为响应模型
        features = []
        for info in feature_list:
            feature = feature_manager.get_feature(info.id)
            if feature:
                features.append(_feature_to_status(feature))

        # 计算摘要
        total = len(features)
        enabled = sum(1 for f in features if f.enabled)
        available = sum(1 for f in features if f.available)
        running = sum(1 for f in features if f.state == "running")
        degraded = available < enabled

        return FeaturesResponse(
            features=features,
            summary=FeatureSummary(
                total=total,
                enabled=enabled,
                available=available,
                running=running,
                degraded=degraded
            )
        )

    except Exception as e:
        logger.error(f"[FeaturesAPI] 获取功能列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@features_router.get("/categories", response_model=CategoriesResponse)
async def get_categories():
    """获取所有功能分类"""
    categories = [
        CategoryInfo(
            id=FeatureCategory.CORE.value,
            name="核心功能",
            description="系统核心必需功能"
        ),
        CategoryInfo(
            id=FeatureCategory.PERCEPTION.value,
            name="感知功能",
            description="语音、视觉等感知能力"
        ),
        CategoryInfo(
            id=FeatureCategory.COGNITION.value,
            name="认知功能",
            description="AI推理、NLP等认知能力"
        ),
        CategoryInfo(
            id=FeatureCategory.MEMORY.value,
            name="记忆功能",
            description="记忆存储和检索"
        ),
        CategoryInfo(
            id=FeatureCategory.CONSCIOUSNESS.value,
            name="意识功能",
            description="自主意识和进化引擎"
        ),
        CategoryInfo(
            id=FeatureCategory.EXTENSION.value,
            name="扩展功能",
            description="可选扩展功能"
        ),
    ]

    return CategoriesResponse(categories=categories)


@features_router.get("/{feature_id}", response_model=FeatureDetailResponse)
async def get_feature_detail(feature_id: str):
    """
    获取特定功能详情

    Args:
        feature_id: 功能ID

    Returns:
        功能详情
    """
    feature = feature_manager.get_feature(feature_id)
    if feature is None:
        raise HTTPException(status_code=404, detail=f"功能不存在: {feature_id}")

    try:
        # 获取依赖信息
        deps = feature.get_dependencies()
        dep_infos = [_dep_to_info(d) for d in deps]

        # 检查缺失依赖
        missing = []
        for dep in deps:
            status = dependency_checker.check(dep)
            if status != DependencyStatus.AVAILABLE:
                dep.status = status
                missing.append(_dep_to_info(dep))

        # 生成安装指南
        install_guide = None
        if missing:
            pip_packages = [d.name for d in deps if d.pip_package and d.status != DependencyStatus.AVAILABLE]
            if pip_packages:
                install_guide = f"pip install {' '.join(pip_packages)}"

        return FeatureDetailResponse(
            feature=_feature_to_status(feature),
            config=feature.info.config,
            dependencies=dep_infos,
            missing_deps=missing,
            install_guide=install_guide
        )

    except Exception as e:
        logger.error(f"[FeaturesAPI] 获取功能详情失败 {feature_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@features_router.post("/{feature_id}/enable", response_model=FeatureActionResponse)
async def enable_feature(feature_id: str, request: EnableRequest):
    """
    启用功能

    Args:
        feature_id: 功能ID
        request: 启用请求

    Returns:
        操作结果
    """
    feature = feature_manager.get_feature(feature_id)
    if feature is None:
        raise HTTPException(status_code=404, detail=f"功能不存在: {feature_id}")

    # 检查是否需要重启
    if feature.requires_restart and not request.confirm_restart:
        return FeatureActionResponse(
            success=False,
            feature_id=feature_id,
            message=f"启用 {feature.name} 需要重启系统",
            requires_restart=True,
            new_state=feature.info.state.value
        )

    try:
        success = feature_manager.enable(feature_id)

        if success:
            # 获取更新后的状态
            feature = feature_manager.get_feature(feature_id)
            state = feature.info.state.value

            # 检查是否有缺失依赖
            missing = feature_manager.get_missing_dependencies(feature_id)
            if missing and not feature.check_availability():
                return FeatureActionResponse(
                    success=True,
                    feature_id=feature_id,
                    message=f"功能已启用，但有 {len(missing)} 个依赖缺失",
                    requires_restart=feature.requires_restart,
                    new_state=state
                )

            return FeatureActionResponse(
                success=True,
                feature_id=feature_id,
                message=f"功能 {feature.name} 已启用",
                requires_restart=feature.requires_restart,
                new_state=state
            )
        else:
            return FeatureActionResponse(
                success=False,
                feature_id=feature_id,
                message="启用功能失败",
                requires_restart=False,
                new_state=feature.info.state.value
            )

    except Exception as e:
        logger.error(f"[FeaturesAPI] 启用功能失败 {feature_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@features_router.post("/{feature_id}/disable", response_model=FeatureActionResponse)
async def disable_feature(feature_id: str):
    """
    禁用功能

    Args:
        feature_id: 功能ID

    Returns:
        操作结果
    """
    feature = feature_manager.get_feature(feature_id)
    if feature is None:
        raise HTTPException(status_code=404, detail=f"功能不存在: {feature_id}")

    try:
        success = feature_manager.disable(feature_id)

        if success:
            return FeatureActionResponse(
                success=True,
                feature_id=feature_id,
                message=f"功能 {feature.name} 已禁用",
                requires_restart=feature.requires_restart,
                new_state="disabled"
            )
        else:
            return FeatureActionResponse(
                success=False,
                feature_id=feature_id,
                message="禁用功能失败",
                requires_restart=False,
                new_state=feature.info.state.value
            )

    except Exception as e:
        logger.error(f"[FeaturesAPI] 禁用功能失败 {feature_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@features_router.post("/{feature_id}/check", response_model=FeatureActionResponse)
async def check_feature(feature_id: str):
    """
    检查功能状态

    Args:
        feature_id: 功能ID

    Returns:
        检查结果
    """
    feature = feature_manager.get_feature(feature_id)
    if feature is None:
        raise HTTPException(status_code=404, detail=f"功能不存在: {feature_id}")

    try:
        state = feature_manager.check_feature(feature_id)
        feature = feature_manager.get_feature(feature_id)

        available = state in (FeatureState.AVAILABLE, FeatureState.RUNNING)

        return FeatureActionResponse(
            success=available,
            feature_id=feature_id,
            message=f"功能状态: {state.value}",
            new_state=state.value
        )

    except Exception as e:
        logger.error(f"[FeaturesAPI] 检查功能失败 {feature_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@features_router.get("/dependencies/check", response_model=DependencyCheckResponse)
async def check_all_dependencies():
    """
    检查所有依赖

    Returns:
        依赖检查结果
    """
    try:
        result = dependency_checker.check_all()

        return DependencyCheckResponse(
            available=[_dep_to_info(d) for d in result.available],
            missing=[_dep_to_info(d) for d in result.missing],
            optional=[_dep_to_info(d) for d in result.optional],
            errors=[_dep_to_info(d) for d in result.errors],
            all_ok=result.all_ok
        )

    except Exception as e:
        logger.error(f"[FeaturesAPI] 依赖检查失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@features_router.get("/{feature_id}/dependencies", response_model=DependencyCheckResponse)
async def check_feature_dependencies(feature_id: str):
    """
    检查功能依赖

    Args:
        feature_id: 功能ID

    Returns:
        依赖检查结果
    """
    feature = feature_manager.get_feature(feature_id)
    if feature is None:
        raise HTTPException(status_code=404, detail=f"功能不存在: {feature_id}")

    try:
        result = dependency_checker.check_feature(feature_id)

        return DependencyCheckResponse(
            available=[_dep_to_info(d) for d in result.available],
            missing=[_dep_to_info(d) for d in result.missing],
            optional=[_dep_to_info(d) for d in result.optional],
            errors=[_dep_to_info(d) for d in result.errors],
            all_ok=result.all_ok
        )

    except Exception as e:
        logger.error(f"[FeaturesAPI] 检查功能依赖失败 {feature_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@features_router.post("/dependencies/install", response_model=InstallResponse)
async def install_dependency(request: InstallRequest, background_tasks: BackgroundTasks):
    """
    安装依赖

    尝试自动安装pip包。大型依赖可能需要较长时间。

    Args:
        request: 安装请求
        background_tasks: 后台任务

    Returns:
        安装结果
    """
    dep = dependency_checker.get_dependency(request.dependency_name)
    if dep is None:
        raise HTTPException(
            status_code=404,
            detail=f"未知依赖: {request.dependency_name}"
        )

    # 检查是否可自动安装
    if dep.type != DependencyType.PIP:
        dependency_checker.get_install_guide(request.dependency_name)
        return InstallResponse(
            success=False,
            message=f"无法自动安装 {dep.type.value} 类型依赖，请手动安装",
            dependency=request.dependency_name
        )

    try:
        # 在后台安装
        success, message = dependency_checker.install_dependency(request.dependency_name)

        return InstallResponse(
            success=success,
            message=message,
            dependency=request.dependency_name
        )

    except Exception as e:
        logger.error(f"[FeaturesAPI] 安装依赖失败 {request.dependency_name}: {e}")
        return InstallResponse(
            success=False,
            message=f"安装失败: {e}",
            dependency=request.dependency_name
        )


@features_router.get("/dependencies/guide/{dependency_name}")
async def get_dependency_guide(dependency_name: str):
    """
    获取依赖安装指南

    Args:
        dependency_name: 依赖名称

    Returns:
        安装指南
    """
    guide = dependency_checker.get_install_guide(dependency_name)

    if guide is None:
        raise HTTPException(
            status_code=404,
            detail=f"未找到依赖: {dependency_name}"
        )

    return guide


@features_router.post("/refresh")
async def refresh_features():
    """
    刷新功能状态

    重新检查所有功能的状态。

    Returns:
        刷新结果
    """
    try:
        results = {}

        for feature_id in feature_manager._feature_classes:
            state = feature_manager.check_feature(feature_id)
            results[feature_id] = state.value

        return {
            "success": True,
            "message": "功能状态已刷新",
            "results": results
        }

    except Exception as e:
        logger.error(f"[FeaturesAPI] 刷新功能状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@features_router.get("/status")
async def get_features_status_redirect():
    """
    【重定向路由】兼容旧版前端路径

    将 /api/features/status 重定向到 /api/features/system/status
    """
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/api/features/system/status", status_code=307)


@features_router.get("/system/status")
async def get_system_status():
    """
    获取系统状态

    返回系统整体运行状态。

    Returns:
        系统状态
    """
    try:
        # 获取功能摘要
        all_features = feature_manager.get_all_status()

        # 获取依赖状态
        dep_result = dependency_checker.check_all()

        # 确定系统状态
        if all_features["summary"]["degraded"]:
            status = "degraded"
        elif dep_result.missing:
            status = "partial"
        else:
            status = "healthy"

        return {
            "status": status,
            "mode": config.get("system.mode", "local"),
            "features": all_features["summary"],
            "dependencies": {
                "total": len(dep_result.available) + len(dep_result.missing) + len(dep_result.optional),
                "available": len(dep_result.available),
                "missing": len(dep_result.missing),
                "optional": len(dep_result.optional)
            },
            "version": config.get("system.version", "5.0.0")
        }

    except Exception as e:
        logger.error(f"[FeaturesAPI] 获取系统状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ═══════════════════════════════════════════════════════════════
# 管理端点（需要管理员权限）
# ═══════════════════════════════════════════════════════════════

@features_router.post("/{feature_id}/configure")
async def configure_feature(feature_id: str, config_dict: dict[str, Any]):
    """
    配置功能

    需要管理员权限。

    Args:
        feature_id: 功能ID
        config_dict: 配置字典

    Returns:
        配置结果
    """
    # TODO: 添加管理员权限检查

    feature = feature_manager.get_feature(feature_id)
    if feature is None:
        raise HTTPException(status_code=404, detail=f"功能不存在: {feature_id}")

    try:
        success = feature_manager.configure(feature_id, config_dict)

        return {
            "success": success,
            "feature_id": feature_id,
            "config": config_dict
        }

    except Exception as e:
        logger.error(f"[FeaturesAPI] 配置功能失败 {feature_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ═══════════════════════════════════════════════════════════════
# 系统级端点
# ═══════════════════════════════════════════════════════════════

@system_router.get("/mode")
async def get_system_mode(
    user_id: str = Depends(get_current_user)
):
    """
    获取当前用户的工作模式

    【P2-整合】使用 DualModeManager 实现用户隔离

    Args:
        user_id: 当前用户ID（通过认证获取）

    Returns:
        Dict: 包含mode、user_id和详细信息的字典
    """
    try:
        system_mode = config.get("system.mode", "local")

        # 【P2-整合】使用 DualModeManager 获取用户专属模式
        try:
            from core.dialog.chat_mode_handler import dual_mode_manager
            user_manager = dual_mode_manager.get_mode_manager(user_id)
            current_work_mode = user_manager.get_current_mode().value
            mode_info = user_manager.get_mode_info()
        except Exception as e:
            logger.warning(f"[FeaturesAPI] 获取用户工作模式失败，回退到全局模式: {e}")
            # 回退到全局模式（向后兼容）
            from core.work_mode_manager import get_work_mode_manager
            work_mode_manager = get_work_mode_manager()
            current_work_mode = work_mode_manager.get_current_mode().value if work_mode_manager else "daily"
            mode_info = work_mode_manager.get_mode_info() if work_mode_manager else {}

        return {
            "success": True,
            "mode": current_work_mode,  # 【修复】返回工作模式(daily/focus)而非系统模式(local/cloud)
            "work_mode": current_work_mode,
            "system_mode": system_mode,  # 系统模式单独返回
            "user_id": user_id,
            "description": {
                "daily": "日常模式 - AI会主动思考，适合日常对话",
                "focus": "专注模式 - AI专注执行任务，适合工作流程"
            }.get(current_work_mode, "未知模式"),
            "mode_info": {
                "mode": mode_info.get("mode", current_work_mode),
                "name": mode_info.get("name", ""),
                "description": mode_info.get("description", ""),
                "interval": mode_info.get("interval", 300),
                "auto_think": mode_info.get("auto_think", True)
            }
        }
    except Exception as e:
        logger.error(f"[FeaturesAPI] 获取系统模式失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@system_router.post("/mode", response_model=ModeSwitchResponse)
async def set_system_mode(
    data: ModeSwitchRequest,
    user_id: str = Depends(get_current_user)
):
    """
    设置当前用户的工作模式

    【P2-整合】使用 DualModeManager 实现用户隔离
    切换工作模式（daily/focus），切换只影响当前用户

    Args:
        data: 模式切换请求数据
        user_id: 当前用户ID（通过认证获取）

    Returns:
        ModeSwitchResponse: 切换结果
    """
    try:
        # 【P2-整合】使用 DualModeManager 获取用户专属管理器
        from core.dialog.chat_mode_handler import dual_mode_manager
        from core.work_mode_manager import WorkMode

        # 验证模式值
        try:
            new_mode = WorkMode(data.mode)
        except ValueError as _exc:
            valid_modes = [m.value for m in WorkMode]
            raise HTTPException(
                status_code=400,
                detail=f"无效的模式: {data.mode}，有效值: {valid_modes}"
            ) from _exc

        # 获取用户的模式管理器并执行切换
        user_manager = dual_mode_manager.get_mode_manager(user_id)
        success = await user_manager.switch_mode(new_mode)

        if success:
            # 通过WebSocket广播模式变更（统一走 ConnectionManager，8600 端口）
            try:
                from api.cloud_api import ConnectionManager
                await ConnectionManager().send_to_user(user_id, {
                    "type": "mode_switched",
                    "timestamp": time.time(),
                    "data": {
                        "mode": new_mode.value,
                        "user_id": user_id,
                        "reason": data.reason
                    }
                })
            except ImportError:
                logger.debug("[FeaturesAPI] ConnectionManager 不可用，跳过WebSocket广播")
            except Exception as ws_error:
                logger.warning(f"[FeaturesAPI] WebSocket广播模式变更失败: {ws_error}")

            logger.info(f"[FeaturesAPI] 用户 {user_id} 模式切换成功: {new_mode.value}")

            return ModeSwitchResponse(
                success=True,
                mode=new_mode.value,
                message=f"模式已切换至 {new_mode.value}"
            )
        else:
            return ModeSwitchResponse(
                success=False,
                mode=data.mode,
                message="模式切换失败"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[FeaturesAPI] 设置系统模式失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ═══════════════════════════════════════════════════════════════
# 导出路由
# ═══════════════════════════════════════════════════════════════

__all__ = ["features_router", "system_router"]
