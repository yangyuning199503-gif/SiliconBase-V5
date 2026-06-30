#!/usr/bin/env python3
"""
Auth Utils - 独立认证工具模块

目的：解决循环导入问题
- cloud_api.py 和 memory_sync_websocket.py 都需要认证功能
- 直接导入会导致循环导入
- 此模块作为中间层，独立于两者

使用方式：
    from api.auth_utils import get_current_user_ws, verify_token
"""

import logging

# 配置日志
logger = logging.getLogger(__name__)

# ============================================================================
# JWT认证相关导入 (与cloud_api.py保持一致)
# ============================================================================
try:
    from jose import JWTError, jwt
    from passlib.context import CryptContext
    PYTHON_JOSE_AVAILABLE = True
except ImportError:
    PYTHON_JOSE_AVAILABLE = False
    JWTError = Exception
    jwt = None
    CryptContext = None
    logger.warning("[AuthUtils] python-jose 未安装，JWT功能将被禁用")


class SimpleAuthStore:
    """
    简化版认证存储 - 用于WebSocket认证

    此实现与cloud_api.py中的UserAuthStore保持兼容
    但独立于cloud_api.py，避免循环导入
    """

    _instance = None
    _secret_key: str = None
    _algorithm: str = "HS256"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _get_secret_key(self) -> str:
        """获取JWT密钥（从环境变量或配置）"""
        if self._secret_key is None:
            import os
            # 尝试多种方式获取密钥
            self._secret_key = os.getenv("JWT_SECRET_KEY") or \
                               os.getenv("SILICONBASE_SECRET_KEY") or \
                               os.getenv("SECRET_KEY")

            if not self._secret_key:
                raise ValueError(
                    "[AuthUtils] JWT_SECRET_KEY 未设置！"
                    "请在 .env 文件中添加 JWT_SECRET_KEY=your-secret-key"
                )

        return self._secret_key

    def verify_token(self, token: str) -> dict | None:
        """
        验证JWT令牌

        Args:
            token: JWT token

        Returns:
            Optional[Dict]: 解码后的payload，无效则返回None
        """
        if not PYTHON_JOSE_AVAILABLE or not jwt:
            logger.error("[AuthUtils] JWT库不可用，无法验证token。请安装: pip install python-jose[cryptography]")
            return None

        try:
            payload = jwt.decode(
                token,
                self._get_secret_key(),
                algorithms=[self._algorithm]
            )
            logger.debug(f"[AuthUtils] Token验证成功: user_id={payload.get('sub')}")
            return payload
        except jwt.ExpiredSignatureError as e:
            logger.error(f"[AuthUtils] Token验证失败: Token已过期 - {e}")
            return None
        except jwt.JWTClaimsError as e:
            logger.error(f"[AuthUtils] Token验证失败: Token声明无效 - {e}")
            return None
        except jwt.JWTError as e:
            logger.error(f"[AuthUtils] Token验证失败: 签名无效或token格式错误 - {e}")
            return None
        except Exception as e:
            logger.error(f"[AuthUtils] Token验证异常: {type(e).__name__}: {e}")
            return None

    def get_user_by_id(self, user_id: str) -> dict | None:
        """
        通过用户ID获取用户信息

        注意：此简化版本仅从token中解析用户信息
        完整功能需要使用cloud_api.py中的UserAuthStore
        """
        # 简化实现：返回基本结构
        # 在实际使用中，用户信息应该从cloud_api的user_auth_store获取
        return {
            "user_id": user_id,
            "username": user_id,
            "is_active": True
        }

    # 【P1-Asyncify】异步版本包装器
    async def averify_token(self, token: str) -> dict | None:
        return self.verify_token(token)

    async def aget_user_by_id(self, user_id: str) -> dict | None:
        return self.get_user_by_id(user_id)


# 全局认证存储实例
_auth_store = SimpleAuthStore()


# ============================================================================
# WebSocket认证函数
# ============================================================================

def verify_token(token: str) -> dict | None:
    """
    验证JWT Token

    Args:
        token: JWT token字符串

    Returns:
        Optional[Dict]: 验证成功返回payload，失败返回None
    """
    if not token:
        logger.error("[AuthUtils] Token验证失败: token为空")
        return None

    result = _auth_store.verify_token(token)
    if result is None:
        # 记录token前缀用于调试（不记录完整token）
        token_preview = token[:20] + "..." if len(token) > 20 else token
        logger.error(f"[AuthUtils] Token验证失败 (前缀: {token_preview})")
    return result


def get_user_from_token(token: str) -> str | None:
    """
    从token中提取用户ID

    Args:
        token: JWT token字符串

    Returns:
        Optional[str]: 用户ID，验证失败返回None
    """
    payload = verify_token(token)
    if payload:
        return payload.get("sub")
    return None


async def get_current_user_ws(token: str) -> str | None:
    """
    WebSocket认证函数

    专用于WebSocket连接的认证验证

    Args:
        token: JWT token字符串（从WebSocket query参数获取）

    Returns:
        Optional[str]: 用户ID，验证失败返回None

    Example:
        user_id = await get_current_user_ws(token)
        if user_id:
            # 认证成功
            pass
        else:
            # 认证失败
            pass
    """
    if not token:
        return None

    # 验证token
    user_id = get_user_from_token(token)
    if not user_id:
        logger.warning("[AuthUtils] WebSocket token验证失败")
        return None

    # 检查用户是否活跃
    user = await _auth_store.aget_user_by_id(user_id)
    if not user or not user.get("is_active", True):
        logger.warning(f"[AuthUtils] 用户不活跃或不存在: {user_id}")
        return None

    logger.debug(f"[AuthUtils] WebSocket认证成功: {user_id}")
    return user_id


# 向后兼容的别名
validate_token = verify_token


# ============================================================================
# HTTP API认证依赖（用于FastAPI）
# ============================================================================

try:
    from fastapi import Depends, HTTPException, Request, status
    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
    FASTAPI_AUTH_AVAILABLE = True
except ImportError:
    FASTAPI_AUTH_AVAILABLE = False
    HTTPException = None
    status = None
    Depends = None
    Request = None
    HTTPAuthorizationCredentials = None

if FASTAPI_AUTH_AVAILABLE:
    security = HTTPBearer(auto_error=False)

    async def get_current_user_http(
        request: Request,
        credentials: HTTPAuthorizationCredentials = Depends(security)
    ) -> str:
        """
        HTTP API认证依赖 - 强制认证版本

        支持：
        1. Authorization: Bearer <token> 请求头
        2. URL query 参数 ?token=<token>（用于 EventSource/SSE 等无法设置 header 的场景）

        用法：
            @app.get("/api/protected")
            async def protected_endpoint(user_id: str = Depends(get_current_user_http)):
                ...
        """
        token = None
        if credentials is not None:
            token = credentials.credentials

        # SSE/EventSource 无法携带 header，允许从 query 参数获取 token
        if not token and request is not None:
            token = request.query_params.get("token")

        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 验证token
        payload = verify_token(token)
        if payload:
            user_id = payload.get("sub")
            if user_id:
                return user_id

        # 验证失败
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    async def get_current_user_optional_http(
        request: Request,
        credentials: HTTPAuthorizationCredentials = Depends(security)
    ) -> str | None:
        """
        HTTP API认证依赖 - 可选认证版本

        有凭证时验证并返回用户ID，无凭证时返回None
        同时支持 Authorization header 和 URL query token
        """
        token = None
        if credentials is not None:
            token = credentials.credentials

        if not token and request is not None:
            token = request.query_params.get("token")

        if not token:
            return None

        # 验证token
        payload = verify_token(token)
        if payload:
            user_id = payload.get("sub")
            if user_id:
                return user_id

        # 验证失败返回None（不抛出异常）
        return None

    # 向后兼容的别名
    get_current_user = get_current_user_http
    get_current_user_optional = get_current_user_optional_http

else:
    # FastAPI不可用时的回退
    async def get_current_user_http(*args, **kwargs) -> str:
        raise Exception("FastAPI not available")

    async def get_current_user_optional_http(*args, **kwargs) -> str | None:
        return None

    get_current_user = get_current_user_http
    get_current_user_optional = get_current_user_optional_http


# ============================================================================
# 初始化函数 - 从cloud_api同步配置
# ============================================================================

def init_auth_from_cloud_api():
    """
    从cloud_api.py同步认证配置

    在cloud_api初始化完成后调用，确保使用相同的密钥
    """
    try:
        # 尝试导入cloud_api中的配置
        from api.cloud_api import user_auth_store as cloud_auth_store

        # 同步密钥
        if hasattr(cloud_auth_store, '_secret_key'):
            _auth_store._secret_key = cloud_auth_store._secret_key
            _auth_store._algorithm = getattr(cloud_auth_store, '_algorithm', "HS256")
            logger.info("[AuthUtils] 已从cloud_api同步认证配置")
    except ImportError:
        logger.debug("[AuthUtils] cloud_api未初始化，使用默认配置")
    except Exception as e:
        logger.warning(f"[AuthUtils] 同步配置失败: {e}")


# 延迟初始化：不再在模块导入时调用，避免循环导入
# 由 cloud_api.py 在初始化完成后显式调用 init_auth_from_cloud_api()
# try:
#     init_auth_from_cloud_api()
# except Exception:
#     pass
