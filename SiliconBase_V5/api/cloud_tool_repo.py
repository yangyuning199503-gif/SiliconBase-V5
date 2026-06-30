#!/usr/bin/env python3
"""
云端工具仓库服务 - Cloud Tool Repository Service
提供云端工具发布、浏览、下载、版本管理等功能

作者: SiliconBase Team
版本: 1.0.0
"""

import asyncio
import hashlib
import json
import os
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import aiofiles
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

# 导入认证依赖
# 注意：不直接在模块顶层从 api.cloud_api 导入，以避免 cloud_api 与 cloud_tool_repo 之间的循环导入。
# 真实认证函数在请求处理时惰性加载。
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> str:
    """获取当前用户（惰性委托给 api.cloud_api，避免循环导入）"""
    try:
        from api.cloud_api import get_current_user as _real_get_current_user
        return await _real_get_current_user(credentials)
    except ImportError:
        # cloud_api 尚未初始化时的降级（理论上不应到达此处）
        logger.debug("[CloudToolRepo] 认证依赖回退到匿名用户")
        return "anonymous"


# 兼容旧代码中直接使用 user_auth_store 的位置
user_auth_store = None

def _get_user_auth_store():
    """惰性获取 user_auth_store，避免循环导入"""
    global user_auth_store
    if user_auth_store is None:
        try:
            from api.cloud_api import user_auth_store as _user_auth_store
            user_auth_store = _user_auth_store
        except ImportError:
            user_auth_store = None
    return user_auth_store

# 导入日志
try:
    from core.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

# ============================================================================
# 数据模型定义
# ============================================================================

class ToolStatus(str, Enum):
    """工具状态枚举"""
    PENDING = "pending"          # 待审核
    AUDITING = "auditing"        # 审核中
    PUBLISHED = "published"      # 已发布
    REJECTED = "rejected"        # 审核未通过
    DEPRECATED = "deprecated"    # 已废弃
    SUSPENDED = "suspended"      # 已暂停


class ToolCategory(str, Enum):
    """工具分类枚举"""
    PRODUCTIVITY = "productivity"      # 生产力
    DEVELOPMENT = "development"        # 开发工具
    MEDIA = "media"                    # 媒体处理
    SYSTEM = "system"                  # 系统工具
    NETWORK = "network"                # 网络通信
    DATA = "data"                      # 数据处理
    SECURITY = "security"              # 安全工具
    ENTERTAINMENT = "entertainment"    # 娱乐
    OTHER = "other"                    # 其他


class ToolMetadata(BaseModel):
    """工具元数据模型"""
    tool_id: str = Field(..., description="工具唯一标识")
    name: str = Field(..., description="工具名称")
    description: str = Field(..., description="工具描述")
    version: str = Field(default="1.0.0", description="版本号")
    author: str = Field(..., description="作者")
    author_id: str = Field(..., description="作者用户ID")
    category: ToolCategory = Field(default=ToolCategory.OTHER, description="工具分类")
    tags: list[str] = Field(default_factory=list, description="标签列表")
    icon: str | None = Field(default=None, description="图标URL或base64")
    screenshots: list[str] = Field(default_factory=list, description="截图列表")
    readme: str | None = Field(default=None, description="README内容")
    license: str = Field(default="MIT", description="许可证")
    homepage: str | None = Field(default=None, description="主页URL")
    repository: str | None = Field(default=None, description="代码仓库URL")
    dependencies: list[str] = Field(default_factory=list, description="依赖包列表")
    min_platform_version: str = Field(default="1.0.0", description="最低平台版本要求")

    class Config:
        use_enum_values = True


class ToolVersionInfo(BaseModel):
    """工具版本信息"""
    version: str
    release_date: datetime
    changelog: str | None = None
    download_count: int = 0
    rating: float = 0.0
    rating_count: int = 0


class ToolInfo(BaseModel):
    """工具信息（用于列表展示）"""
    tool_id: str
    name: str
    description: str
    version: str
    author: str
    category: str
    tags: list[str]
    icon: str | None
    status: str
    download_count: int
    rating: float
    rating_count: int
    release_date: datetime
    last_update: datetime
    size_bytes: int


class ToolVersion(BaseModel):
    """本地工具版本（用于检查更新）"""
    tool_id: str
    version: str


class UpdateInfo(BaseModel):
    """更新信息"""
    tool_id: str
    current: str
    latest: str
    changelog: str | None = None
    download_url: str | None = None


class AuditResult(BaseModel):
    """安全审核结果"""
    passed: bool
    score: float = Field(ge=0, le=100)
    details: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class PublishResponse(BaseModel):
    """发布响应"""
    success: bool
    tool_id: str
    version: str
    download_url: str | None = None
    audit_result: AuditResult | None = None
    error: str | None = None


class ToolListResponse(BaseModel):
    """工具列表响应"""
    success: bool
    tools: list[ToolInfo]
    total: int
    page: int
    page_size: int


# ============================================================================
# 云端工具仓库核心类
# ============================================================================

class OSSAdapter:
    """
    对象存储适配器 - 支持多种存储后端

    当前支持:
    - 本地文件系统（开发/测试）
    - 阿里云OSS（生产环境）
    """

    def __init__(self):
        self.storage_type = os.getenv("STORAGE_TYPE", "local")
        self.local_storage_path = Path(os.getenv("TOOL_STORAGE_PATH", "./data/cloud_tools"))

        # 本地存储初始化
        if self.storage_type == "local":
            self.local_storage_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"[OSSAdapter] 使用本地存储: {self.local_storage_path}")

        # 阿里云OSS初始化
        elif self.storage_type == "aliyun":
            try:
                import oss2
                access_key = os.getenv("ALIYUN_ACCESS_KEY")
                secret_key = os.getenv("ALIYUN_SECRET_KEY")
                endpoint = os.getenv("ALIYUN_OSS_ENDPOINT")
                bucket_name = os.getenv("ALIYUN_OSS_BUCKET")

                if not all([access_key, secret_key, endpoint, bucket_name]):
                    raise ValueError("阿里云OSS配置不完整")

                self.auth = oss2.Auth(access_key, secret_key)
                self.bucket = oss2.Bucket(self.auth, endpoint, bucket_name)
                logger.info(f"[OSSAdapter] 使用阿里云OSS: {bucket_name}")
            except ImportError:
                logger.error("[OSSAdapter] 未安装oss2库，请运行: pip install oss2")
                raise

    async def upload(self, data: bytes, key: str) -> str:
        """上传文件到存储"""
        if self.storage_type == "local":
            file_path = self.local_storage_path / key
            await asyncio.to_thread(file_path.parent.mkdir, parents=True, exist_ok=True)
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(data)
            return f"file://{file_path.absolute()}"

        elif self.storage_type == "aliyun":
            self.bucket.put_object(key, data)
            return f"https://{self.bucket.bucket_name}.{self.bucket.endpoint}/{key}"

        else:
            raise ValueError(f"不支持的存储类型: {self.storage_type}")

    def _validate_path(self, key: str) -> Path:
        """
        验证路径安全，防止路径遍历攻击

        Args:
            key: 文件路径key

        Returns:
            Path: 验证后的安全路径

        Raises:
            ValueError: 路径验证失败
        """
        # 移除file://前缀
        if key.startswith("file://"):
            key = key[7:]

        # 解析路径
        file_path = Path(key)

        # 如果路径不是绝对路径，基于存储目录解析
        if not file_path.is_absolute():
            file_path = self.local_storage_path / file_path

        # 【安全修复】路径遍历检测：确保解析后的路径在允许的存储目录内
        try:
            resolved_path = file_path.resolve()
            resolved_base = self.local_storage_path.resolve()

            # 检查路径是否在允许的目录内
            if not str(resolved_path).startswith(str(resolved_base)):
                logger.error(f"[SECURITY_ERROR] 路径遍历攻击检测: 试图访问 '{key}'，该路径超出允许范围")
                raise ValueError("非法路径: 访问被拒绝")

            # 检查路径中是否包含危险模式
            dangerous_patterns = ['..', '~', '//', '\\', '\x00']
            for pattern in dangerous_patterns:
                if pattern in key:
                    logger.error(f"[SECURITY_ERROR] 路径包含危险模式 '{pattern}': {key}")
                    raise ValueError("非法路径: 包含危险字符")

            return resolved_path
        except Exception as e:
            if isinstance(e, ValueError):
                raise
            logger.error(f"[SECURITY_ERROR] 路径验证失败: {e}")
            raise ValueError(f"路径验证失败: {e}") from e

    async def download(self, key: str) -> bytes:
        """从存储下载文件"""
        if self.storage_type == "local":
            # 【安全修复】验证路径安全
            file_path = self._validate_path(key)

            if not file_path.exists():
                raise FileNotFoundError(f"文件不存在: {key}")
            if not file_path.is_file():
                raise ValueError(f"路径不是文件: {key}")

            logger.info(f"[SECURITY] 安全下载文件: {file_path}")
            async with aiofiles.open(file_path, "rb") as f:
                return await f.read()

        elif self.storage_type == "aliyun":
            return self.bucket.get_object(key).read()

        else:
            raise ValueError(f"不支持的存储类型: {self.storage_type}")

    async def delete(self, key: str) -> bool:
        """删除存储中的文件"""
        try:
            if self.storage_type == "local":
                # 【安全修复】验证路径安全
                file_path = self._validate_path(key)

                if file_path.exists():
                    if not file_path.is_file():
                        logger.error(f"[SECURITY_ERROR] 删除操作目标不是文件: {key}")
                        return False
                    await asyncio.to_thread(file_path.unlink)
                    logger.info(f"[SECURITY] 安全删除文件: {file_path}")
                return True

            elif self.storage_type == "aliyun":
                self.bucket.delete_object(key)
                return True

            return False
        except ValueError as e:
            # 安全验证失败
            logger.error(f"[SECURITY_ERROR] 删除操作安全验证失败: {e}")
            return False
        except Exception as e:
            logger.error(f"[OSSAdapter] 删除文件失败: {e}")
            return False

    def get_url(self, key: str, expire_seconds: int = 3600) -> str:
        """获取临时访问URL"""
        if self.storage_type == "local":
            return key

        elif self.storage_type == "aliyun":
            return self.bucket.sign_url('GET', key, expire_seconds)

        return key


class PostgreSQLAdapter:
    """
    工具元数据存储适配器（当前仅实现 SQLite）

    TODO: 类名保留为 PostgreSQLAdapter 仅为了兼容现有调用；PostgreSQL 分支尚未实现，
          当前所有操作实际走 SQLite。后续若接入 PostgreSQL，应实现真实异步 PostgreSQL
          操作或复用 core.memory.postgres_pool。
    """

    def __init__(self):
        self.db_type = os.getenv("DB_TYPE", "sqlite")
        self.connection = None
        self._init_db()

    def _init_db(self):
        """初始化数据库连接和表结构"""
        if self.db_type == "postgresql":
            import importlib.util
            if importlib.util.find_spec("asyncpg") is None:
                logger.warning("[PostgreSQLAdapter] 未安装asyncpg，使用SQLite")
                self.db_type = "sqlite"
            else:
                self.connection_string = os.getenv(
                    "DATABASE_URL",
                    "postgresql://user:password@localhost/siliconbase"
                )

        if self.db_type == "sqlite":
            import sqlite3
            self.db_path = Path(os.getenv("SQLITE_PATH", "./data/cloud_tools.db"))
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            # 初始化表
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            # 工具元数据表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cloud_tools (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    author TEXT,
                    author_id TEXT,
                    category TEXT DEFAULT 'other',
                    tags TEXT,
                    icon TEXT,
                    screenshots TEXT,
                    readme TEXT,
                    license TEXT DEFAULT 'MIT',
                    homepage TEXT,
                    repository TEXT,
                    dependencies TEXT,
                    min_platform_version TEXT DEFAULT '1.0.0',
                    status TEXT DEFAULT 'pending',
                    storage_path TEXT,
                    size_bytes INTEGER DEFAULT 0,
                    download_count INTEGER DEFAULT 0,
                    rating REAL DEFAULT 0.0,
                    rating_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(tool_id, version)
                )
            """)

            # 审核记录表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tool_audits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    auditor_id TEXT,
                    status TEXT,
                    score REAL,
                    details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 下载记录表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tool_downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    user_id TEXT,
                    client_ip TEXT,
                    downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.commit()
            conn.close()
            logger.info(f"[PostgreSQLAdapter] SQLite数据库初始化完成: {self.db_path}")

    async def _async_sqlite(self, fn):
        """在默认执行器中运行同步 SQLite 操作（替代 aiosqlite）"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fn)

    async def save(self, metadata: ToolMetadata, storage_path: str, size_bytes: int) -> bool:
        """保存工具元数据"""
        def _sync_save():
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO cloud_tools (
                        tool_id, version, name, description, author, author_id,
                        category, tags, icon, screenshots, readme, license,
                        homepage, repository, dependencies, min_platform_version,
                        status, storage_path, size_bytes, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    metadata.tool_id,
                    metadata.version,
                    metadata.name,
                    metadata.description,
                    metadata.author,
                    metadata.author_id,
                    metadata.category.value if isinstance(metadata.category, ToolCategory) else metadata.category,
                    json.dumps(metadata.tags),
                    metadata.icon,
                    json.dumps(metadata.screenshots),
                    metadata.readme,
                    metadata.license,
                    metadata.homepage,
                    metadata.repository,
                    json.dumps(metadata.dependencies),
                    metadata.min_platform_version,
                    ToolStatus.PENDING.value,
                    storage_path,
                    size_bytes
                ))
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"[PostgreSQLAdapter] 保存工具元数据失败: {e}")
                return False
            finally:
                conn.close()

        return await self._async_sqlite(_sync_save)

    async def query(self, category: str = None, status: str = "published",
                    page: int = 1, page_size: int = 20) -> list[ToolInfo]:
        """查询工具列表"""
        def _sync_query():
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            try:
                query = "SELECT * FROM cloud_tools WHERE status = ?"
                params = [status]

                if category:
                    query += " AND category = ?"
                    params.append(category)

                query += " ORDER BY download_count DESC, rating DESC LIMIT ? OFFSET ?"
                params.extend([page_size, (page - 1) * page_size])

                cursor.execute(query, params)
                rows = cursor.fetchall()

                tools = []
                for row in rows:
                    tool = ToolInfo(
                        tool_id=row["tool_id"],
                        name=row["name"],
                        description=row["description"],
                        version=row["version"],
                        author=row["author"],
                        category=row["category"],
                        tags=json.loads(row["tags"]) if row["tags"] else [],
                        icon=row["icon"],
                        status=row["status"],
                        download_count=row["download_count"],
                        rating=row["rating"],
                        rating_count=row["rating_count"],
                        release_date=row["created_at"],
                        last_update=row["updated_at"],
                        size_bytes=row["size_bytes"]
                    )
                    tools.append(tool)

                return tools
            finally:
                conn.close()

        return await self._async_sqlite(_sync_query)

    async def get(self, tool_id: str, version: str = None) -> dict[str, Any] | None:
        """获取指定工具"""
        def _sync_get():
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            try:
                if version:
                    cursor.execute(
                        "SELECT * FROM cloud_tools WHERE tool_id = ? AND version = ?",
                        (tool_id, version)
                    )
                else:
                    cursor.execute(
                        "SELECT * FROM cloud_tools WHERE tool_id = ? ORDER BY version DESC LIMIT 1",
                        (tool_id,)
                    )

                row = cursor.fetchone()
                if row:
                    return dict(row)
                return None
            finally:
                conn.close()

        return await self._async_sqlite(_sync_get)

    async def get_latest_version(self, tool_id: str) -> ToolVersionInfo | None:
        """获取最新版本"""
        from packaging import version

        def _sync_get_latest():
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT * FROM cloud_tools WHERE tool_id = ? AND status = 'published'",
                    (tool_id,)
                )
                rows = cursor.fetchall()

                if not rows:
                    return None

                # 找到最新版本
                latest_row = max(rows, key=lambda r: version.parse(r["version"]))

                return ToolVersionInfo(
                    version=latest_row["version"],
                    release_date=latest_row["created_at"],
                    changelog=None,
                    download_count=latest_row["download_count"],
                    rating=latest_row["rating"],
                    rating_count=latest_row["rating_count"]
                )
            except Exception as e:
                logger.error(f"[PostgreSQLAdapter] 获取最新版本失败: {e}")
                return None
            finally:
                conn.close()

        return await self._async_sqlite(_sync_get_latest)

    async def update_status(self, tool_id: str, version: str, status: ToolStatus) -> bool:
        """更新工具状态"""
        def _sync_update():
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "UPDATE cloud_tools SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE tool_id = ? AND version = ?",
                    (status.value, tool_id, version)
                )
                conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"[PostgreSQLAdapter] 更新状态失败: {e}")
                return False
            finally:
                conn.close()

        return await self._async_sqlite(_sync_update)

    async def increment_download(self, tool_id: str, version: str) -> bool:
        """增加下载计数"""
        def _sync_increment():
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "UPDATE cloud_tools SET download_count = download_count + 1 WHERE tool_id = ? AND version = ?",
                    (tool_id, version)
                )
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"[PostgreSQLAdapter] 增加下载计数失败: {e}")
                return False
            finally:
                conn.close()

        return await self._async_sqlite(_sync_increment)

    async def get_total_count(self, status: str = "published") -> int:
        """获取工具总数"""
        def _sync_count():
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT COUNT(*) FROM cloud_tools WHERE status = ?", (status,))
                row = cursor.fetchone()
                return row[0]
            finally:
                conn.close()

        return await self._async_sqlite(_sync_count)

    async def get_versions(self, tool_id: str) -> list[ToolVersionInfo]:
        """获取工具的所有版本"""
        from packaging import version

        def _sync_versions():
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT * FROM cloud_tools WHERE tool_id = ? AND status = 'published' ORDER BY created_at DESC",
                    (tool_id,)
                )
                rows = cursor.fetchall()

                versions = []
                for row in rows:
                    versions.append(ToolVersionInfo(
                        version=row["version"],
                        release_date=row["created_at"],
                        changelog=None,
                        download_count=row["download_count"],
                        rating=row["rating"],
                        rating_count=row["rating_count"]
                    ))

                versions.sort(key=lambda v: version.parse(v.version), reverse=True)
                return versions
            finally:
                conn.close()

        return await self._async_sqlite(_sync_versions)


class SecurityAuditor:
    """安全审核器"""

    async def audit(self, tool_package: bytes) -> AuditResult:
        """对工具包进行安全审核"""
        details = []
        warnings = []
        errors = []
        score = 100.0

        try:
            # 检查文件结构
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                tmp.write(tool_package)
                tmp_path = tmp.name

            with zipfile.ZipFile(tmp_path, 'r') as zf:
                files = zf.namelist()

                # 检查必需文件
                if "tool.py" not in files and "__init__.py" not in files:
                    errors.append("缺少工具入口文件 (tool.py 或 __init__.py)")
                    score -= 30

                # 检查manifest.json
                if "manifest.json" not in files:
                    warnings.append("缺少 manifest.json")
                    score -= 10

                # 检查危险文件
                dangerous_patterns = ['.exe', '.dll', '.so', '.dylib', '.bat', '.cmd']
                for f in files:
                    if any(f.lower().endswith(p) for p in dangerous_patterns):
                        errors.append(f"包含可疑文件: {f}")
                        score -= 50

                # 检查Python代码安全
                for f in files:
                    if f.endswith('.py'):
                        try:
                            code = zf.read(f).decode('utf-8')

                            # 检查危险导入
                            dangerous_imports = [
                                'os.system', 'subprocess.call', 'subprocess.run',
                                'eval(', 'exec(', '__import__', 'importlib'
                            ]
                            for imp in dangerous_imports:
                                if imp in code:
                                    warnings.append(f"{f} 包含潜在危险调用: {imp}")
                                    score -= 5

                            # AST语法检查
                            try:
                                import ast
                                ast.parse(code)
                                details.append(f"{f} 语法检查通过")
                            except SyntaxError as e:
                                errors.append(f"{f} 语法错误: {e}")
                                score -= 20

                        except Exception as e:
                            warnings.append(f"无法检查文件 {f}: {e}")

            # 清理临时文件
            await asyncio.to_thread(os.unlink, tmp_path)

        except zipfile.BadZipFile:
            errors.append("无效的工具包格式（必须是zip）")
            score = 0
        except Exception as e:
            errors.append(f"审核过程出错: {e}")
            score -= 20

        # 确保分数在有效范围
        score = max(0, min(100, score))

        passed = score >= 70 and len(errors) == 0

        return AuditResult(
            passed=passed,
            score=score,
            details=details,
            warnings=warnings,
            errors=errors
        )


# ============================================================================
# 云端工具仓库主类
# ============================================================================

class CloudToolRepository:
    """
    云端工具仓库 - 核心服务类

    职责：
    1. 工具发布与审核
    2. 工具存储管理
    3. 工具元数据管理
    4. 版本控制
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, '_initialized', False):
            return
        self._initialized = True

        self.tools_db = PostgreSQLAdapter()
        self.storage = OSSAdapter()
        self.auditor = SecurityAuditor()

        logger.info("[CloudToolRepository] 云端工具仓库初始化完成")

    async def publish_tool(self, tool_package: bytes, metadata: ToolMetadata) -> PublishResponse:
        """
        发布工具到云端市场

        Args:
            tool_package: 工具包文件内容（zip格式）
            metadata: 工具元数据

        Returns:
            PublishResponse: 发布结果
        """
        try:
            # 1. 安全审核
            logger.info(f"[CloudToolRepository] 开始安全审核: {metadata.tool_id} v{metadata.version}")
            audit_result = await self.auditor.audit(tool_package)

            if not audit_result.passed:
                logger.warning(f"[CloudToolRepository] 安全审核未通过: {metadata.tool_id}")
                return PublishResponse(
                    success=False,
                    tool_id=metadata.tool_id,
                    version=metadata.version,
                    audit_result=audit_result,
                    error="安全审核未通过"
                )

            # 2. 数字签名
            self._sign_tool(tool_package, metadata)

            # 3. 上传到存储
            storage_key = f"tools/{metadata.tool_id}/{metadata.version}/package.zip"
            storage_path = await self.storage.upload(tool_package, storage_key)

            # 4. 保存元数据
            success = await self.tools_db.save(metadata, storage_path, len(tool_package))

            if not success:
                return PublishResponse(
                    success=False,
                    tool_id=metadata.tool_id,
                    version=metadata.version,
                    error="保存工具元数据失败"
                )

            logger.info(f"[CloudToolRepository] 工具发布成功: {metadata.tool_id} v{metadata.version}")

            return PublishResponse(
                success=True,
                tool_id=metadata.tool_id,
                version=metadata.version,
                download_url=f"/api/cloud-tools/{metadata.tool_id}/{metadata.version}/download",
                audit_result=audit_result
            )

        except Exception as e:
            logger.error(f"[CloudToolRepository] 发布工具失败: {e}")
            return PublishResponse(
                success=False,
                tool_id=metadata.tool_id,
                version=metadata.version,
                error=str(e)
            )

    async def get_tool_list(self, category: str = None, status: str = "published",
                           page: int = 1, page_size: int = 20) -> ToolListResponse:
        """
        获取工具列表（供客户端浏览）

        Args:
            category: 分类筛选
            status: 状态筛选
            page: 页码
            page_size: 每页数量

        Returns:
            ToolListResponse: 工具列表响应
        """
        tools = await self.tools_db.query(
            category=category,
            status=status,
            page=page,
            page_size=page_size
        )
        total = await self.tools_db.get_total_count(status)

        return ToolListResponse(
            success=True,
            tools=tools,
            total=total,
            page=page,
            page_size=page_size
        )

    async def download_tool(self, tool_id: str, version: str, user_id: str = None) -> bytes:
        """
        下载指定版本工具

        Args:
            tool_id: 工具ID
            version: 版本号
            user_id: 下载用户ID（用于统计）

        Returns:
            bytes: 工具包内容
        """
        metadata = await self.tools_db.get(tool_id, version)
        if not metadata:
            raise HTTPException(404, "工具不存在")

        if metadata["status"] != ToolStatus.PUBLISHED.value:
            raise HTTPException(403, "工具未发布或已被下架")

        # 下载文件
        tool_package = await self.storage.download(metadata["storage_path"])

        # 更新下载计数
        await self.tools_db.increment_download(tool_id, version)

        return tool_package

    async def check_updates(self, local_tools: list[ToolVersion]) -> list[UpdateInfo]:
        """
        检查工具更新

        Args:
            local_tools: 本地已安装工具版本列表

        Returns:
            List[UpdateInfo]: 可更新的工具列表
        """
        updates = []

        for local_tool in local_tools:
            try:
                from packaging import version
                latest = await self.tools_db.get_latest_version(local_tool.tool_id)

                if latest and version.parse(latest.version) > version.parse(local_tool.version):
                    updates.append(UpdateInfo(
                        tool_id=local_tool.tool_id,
                        current=local_tool.version,
                        latest=latest.version,
                        download_url=f"/api/cloud-tools/{local_tool.tool_id}/{latest.version}/download"
                    ))
            except Exception as e:
                logger.warning(f"[CloudToolRepository] 检查更新失败 {local_tool.tool_id}: {e}")
                continue

        return updates

    async def get_tool_detail(self, tool_id: str, version: str = None) -> dict[str, Any] | None:
        """
        获取工具详情

        Args:
            tool_id: 工具ID
            version: 版本号（可选，默认最新）

        Returns:
            Optional[Dict]: 工具详情
        """
        return await self.tools_db.get(tool_id, version)

    async def get_versions(self, tool_id: str) -> list[ToolVersionInfo]:
        """
        获取工具的所有版本

        Args:
            tool_id: 工具ID

        Returns:
            List[ToolVersionInfo]: 版本列表
        """
        return await self.tools_db.get_versions(tool_id)

    async def approve_tool(self, tool_id: str, version: str, auditor_id: str) -> bool:
        """
        审核通过工具

        Args:
            tool_id: 工具ID
            version: 版本号
            auditor_id: 审核员ID

        Returns:
            bool: 是否成功
        """
        return await self.tools_db.update_status(tool_id, version, ToolStatus.PUBLISHED)

    async def reject_tool(self, tool_id: str, version: str, reason: str) -> bool:
        """
        拒绝工具发布

        Args:
            tool_id: 工具ID
            version: 版本号
            reason: 拒绝原因

        Returns:
            bool: 是否成功
        """
        return await self.tools_db.update_status(tool_id, version, ToolStatus.REJECTED)

    def _sign_tool(self, tool_package: bytes, metadata: ToolMetadata) -> str:
        """
        对工具包进行数字签名

        Args:
            tool_package: 工具包内容
            metadata: 工具元数据

        Returns:
            str: 签名

        Raises:
            ValueError: 当未配置签名密钥时
        """
        import hmac
        # 【安全修复】强制从环境变量获取密钥，禁止使用硬编码默认密钥
        secret = os.getenv("TOOL_SIGNING_SECRET")
        if not secret:
            logger.error("[SECURITY_ERROR] TOOL_SIGNING_SECRET环境变量未设置，无法进行数字签名")
            raise ValueError("TOOL_SIGNING_SECRET环境变量必须设置才能使用工具签名功能")

        # 验证密钥强度
        if len(secret) < 32:
            logger.error("[SECURITY_ERROR] TOOL_SIGNING_SECRET密钥长度不足32字符，存在安全隐患")
            raise ValueError("TOOL_SIGNING_SECRET密钥长度必须至少32字符")

        content = tool_package + json.dumps(metadata.dict(), default=str).encode()
        signature = hmac.new(secret.encode(), content, hashlib.sha256).hexdigest()
        logger.debug("[SECURITY] 工具签名成功")
        return signature


# 全局仓库实例
cloud_tool_repo = CloudToolRepository()


# ============================================================================
# FastAPI路由
# ============================================================================

router = APIRouter(prefix="/cloud-tools", tags=["cloud-tools"])


@router.post("/publish", response_model=PublishResponse)
async def publish_tool_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    metadata_json: str = Form(...),
    user_id: str = Depends(get_current_user)
):
    """
    发布工具到云端市场

    - **file**: 工具包文件（zip格式）
    - **metadata_json**: 工具元数据JSON字符串
    """
    try:
        # 解析元数据
        metadata_dict = json.loads(metadata_json)
        metadata = ToolMetadata(**metadata_dict, author_id=user_id)

        # 读取文件内容
        contents = await file.read()

        # 发布工具
        result = await cloud_tool_repo.publish_tool(contents, metadata)
        return result

    except json.JSONDecodeError as _exc:
        raise HTTPException(400, "无效的元数据JSON格式") from _exc
    except Exception as e:
        logger.error(f"[CloudToolAPI] 发布工具失败: {e}")
        raise HTTPException(500, f"发布失败: {str(e)}") from e


@router.get("/list", response_model=ToolListResponse)
async def get_tool_list_endpoint(
    category: str | None = None,
    page: int = 1,
    page_size: int = 20,
    user_id: str = Depends(get_current_user)
):
    """获取云端工具列表"""
    return await cloud_tool_repo.get_tool_list(
        category=category,
        page=page,
        page_size=page_size
    )


@router.get("/{tool_id}/versions")
async def get_tool_versions_endpoint(
    tool_id: str,
    user_id: str = Depends(get_current_user)
):
    """获取工具的所有版本"""
    versions = await cloud_tool_repo.get_versions(tool_id)
    return {
        "success": True,
        "tool_id": tool_id,
        "versions": [v.dict() for v in versions]
    }


@router.get("/{tool_id}/{version}/download")
async def download_tool_endpoint(
    tool_id: str,
    version: str,
    user_id: str = Depends(get_current_user)
):
    """下载工具包"""
    try:
        tool_package = await cloud_tool_repo.download_tool(tool_id, version, user_id)

        return StreamingResponse(
            iter([tool_package]),
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename={tool_id}-{version}.zip"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[CloudToolAPI] 下载工具失败: {e}")
        raise HTTPException(500, f"下载失败: {str(e)}") from e


@router.get("/{tool_id}/{version}/detail")
async def get_tool_detail_endpoint(
    tool_id: str,
    version: str,
    user_id: str = Depends(get_current_user)
):
    """获取工具详情"""
    detail = await cloud_tool_repo.get_tool_detail(tool_id, version)
    if not detail:
        raise HTTPException(404, "工具不存在")

    return {
        "success": True,
        "data": detail
    }


@router.post("/check-updates")
async def check_updates_endpoint(
    request: list[ToolVersion],
    user_id: str = Depends(get_current_user)
):
    """检查工具更新"""
    updates = await cloud_tool_repo.check_updates(request)
    return {
        "success": True,
        "updates": [u.dict() for u in updates],
        "count": len(updates)
    }


# ============================================================================
# 权限检查辅助函数
# ============================================================================
async def require_admin(user_id: str) -> bool:
    """
    验证用户是否为管理员

    【安全要求】所有管理员操作端点必须调用此函数验证权限

    Args:
        user_id: 用户ID

    Returns:
        bool: 是否为管理员

    Raises:
        HTTPException: 403 如果不是管理员
    """
    # 从认证存储获取用户角色
    if not user_id or user_id == "anonymous":
        logger.error("[SECURITY_ERROR] 权限检查失败: 用户未登录")
        raise HTTPException(status_code=401, detail="未登录")

    # 获取用户角色 (从 user_auth_store 或数据库)
    try:
        # 优先从环境变量获取管理员列表
        admin_users = os.getenv("ADMIN_USERS", "").split(",")
        admin_users = [u.strip() for u in admin_users if u.strip()]

        # 检查用户是否在管理员列表中
        is_admin = user_id in admin_users

        # 也可以从用户存储查询角色
        _user_auth_store = _get_user_auth_store()
        if _user_auth_store and hasattr(_user_auth_store, 'get_user_role'):
            user_role = _user_auth_store.get_user_role(user_id)
            if user_role == "admin":
                is_admin = True

        if not is_admin:
            logger.error(f"[SECURITY_ERROR] 用户 '{user_id}' 尝试执行管理员操作但被拒绝")
            raise HTTPException(status_code=403, detail="权限不足：需要管理员权限")

        logger.info(f"[SECURITY] 管理员权限验证通过: {user_id}")
        return True

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[SECURITY_ERROR] 权限检查异常: {e}")
        raise HTTPException(status_code=500, detail="权限检查失败") from e


@router.post("/{tool_id}/{version}/approve")
async def approve_tool_endpoint(
    tool_id: str,
    version: str,
    user_id: str = Depends(get_current_user)
):
    """审核通过工具（管理员权限）"""
    # 【安全修复】强制进行管理员权限验证
    await require_admin(user_id)

    logger.info(f"[SECURITY] 管理员 {user_id} 执行审核通过操作: {tool_id} v{version}")

    success = await cloud_tool_repo.approve_tool(tool_id, version, user_id)
    if not success:
        raise HTTPException(500, "审核操作失败")

    logger.info(f"[SECURITY] 工具审核通过: {tool_id} v{version} by {user_id}")

    return {
        "success": True,
        "message": f"工具 {tool_id} v{version} 已审核通过"
    }


# 导出
__all__ = [
    'CloudToolRepository',
    'cloud_tool_repo',
    'router',
    'ToolMetadata',
    'ToolInfo',
    'ToolVersion',
    'UpdateInfo',
    'AuditResult',
    'ToolStatus',
    'ToolCategory'
]
