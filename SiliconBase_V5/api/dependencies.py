#!/usr/bin/env python3
"""
FastAPI 依赖项 - 包含会员权限检查
"""


from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.auth_utils import verify_token
from core.subscription_manager import subscription_manager

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> str:
    """获取当前用户（强制认证）"""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录已过期，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload.get("sub")


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> str | None:
    """获取当前用户（可选认证）"""
    if credentials is None:
        return None

    payload = verify_token(credentials.credentials)
    return payload.get("sub") if payload else None


def check_feature_permission(feature: str):
    """
    检查功能权限的依赖项工厂

    用法：
        @router.post("/subagent")
        async def use_subagent(
            user_id: str = Depends(get_current_user),
            _: bool = Depends(check_feature_permission("subagent"))
        ):
            ...
    """
    async def permission_checker(user_id: str = Depends(get_current_user)):
        has_perm, reason = subscription_manager.check_permission(user_id, feature)
        if not has_perm:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "权限不足",
                    "reason": reason,
                    "upgrade_url": "/subscription/upgrade"
                }
            )

        # 消费配额
        if not subscription_manager.consume_quota(user_id, feature):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "配额已用完",
                    "reason": "本月用量已用完",
                    "upgrade_url": "/subscription/upgrade"
                }
            )

        return True

    return permission_checker
