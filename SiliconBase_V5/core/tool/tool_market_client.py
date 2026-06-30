#!/usr/bin/env python3
"""
本地工具市场客户端 - Tool Market Client
提供浏览、下载、安装云端工具的功能

作者: SiliconBase Team
版本: 1.0.0

架构说明：当前使用私有协议（ZIP 下载 + 本地安装）接入外部工具。
标准 MCP（Model Context Protocol）协议待后续版本接入。
"""

import asyncio
import hashlib
import hmac
import json
import os
import shutil
import sys
import tempfile
import threading
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

# 导入日志
try:
    from core.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


# 导入工具管理器
try:
    from core.tool.tool_manager import tool_manager
    TOOL_MANAGER_AVAILABLE = True
except ImportError:
    TOOL_MANAGER_AVAILABLE = False

# 导入BaseTool
try:
    from core.tool.base_tool import BaseTool
    BASE_TOOL_AVAILABLE = True
except ImportError:
    BASE_TOOL_AVAILABLE = False


# ============================================================================
# 数据模型
# ============================================================================

class InstallStatus(str, Enum):
    """安装状态"""
    PENDING = "pending"           # 等待安装
    DOWNLOADING = "downloading"   # 下载中
    VERIFYING = "verifying"       # 验证中
    INSTALLING = "installing"     # 安装中
    COMPLETED = "completed"       # 安装完成
    FAILED = "failed"             # 安装失败
    ROLLING_BACK = "rolling_back" # 回滚中


@dataclass
class InstallTask:
    """安装任务"""
    task_id: str
    tool_id: str
    version: str
    status: InstallStatus
    progress: int = 0  # 0-100
    message: str = ""
    error: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None


@dataclass
class InstalledToolInfo:
    """已安装工具信息"""
    tool_id: str
    name: str
    version: str
    description: str
    author: str
    category: str
    install_date: datetime
    install_path: Path
    source: str = "cloud"  # cloud/local
    auto_update: bool = True


@dataclass
class CloudToolInfo:
    """云端工具信息"""
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


# ============================================================================
# 云端API客户端
# ============================================================================

class CloudToolAPI:
    """云端工具API客户端"""

    def __init__(self, base_url: str = None):
        self.base_url = base_url or os.getenv(
            "CLOUD_API_URL",
            "https://api.siliconbase.com"
        )
        self.api_prefix = "/api/cloud-tools"
        self.timeout = 30

        # 获取认证token
        self.auth_token = self._get_auth_token()

    def _get_auth_token(self) -> str | None:
        """获取认证token"""
        # 从环境变量或配置文件读取
        token = os.getenv("SILICONBASE_CLOUD_TOKEN")
        if token:
            return token

        # 尝试从本地文件读取
        token_file = Path.home() / ".siliconbase" / "cloud_token"
        if token_file.exists():
            return token_file.read_text().strip()

        return None

    def _get_headers(self) -> dict[str, str]:
        """获取请求头"""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "SiliconBase-ToolMarket/1.0.0"
        }
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers

    async def get_tool_list(self, category: str = None, page: int = 1) -> list[CloudToolInfo]:
        """获取云端工具列表"""
        try:
            import httpx

            params = {"page": page, "page_size": 20}
            if category:
                params["category"] = category

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}{self.api_prefix}/list",
                    params=params,
                    headers=self._get_headers()
                )
                response.raise_for_status()
                data = response.json()

                tools = []
                for tool_data in data.get("tools", []):
                    tools.append(CloudToolInfo(
                        tool_id=tool_data["tool_id"],
                        name=tool_data["name"],
                        description=tool_data["description"],
                        version=tool_data["version"],
                        author=tool_data["author"],
                        category=tool_data["category"],
                        tags=tool_data.get("tags", []),
                        icon=tool_data.get("icon"),
                        status=tool_data["status"],
                        download_count=tool_data["download_count"],
                        rating=tool_data["rating"],
                        rating_count=tool_data["rating_count"],
                        release_date=datetime.fromisoformat(tool_data["release_date"]),
                        last_update=datetime.fromisoformat(tool_data["last_update"]),
                        size_bytes=tool_data["size_bytes"]
                    ))
                return tools

        except Exception as e:
            logger.error(f"[CloudToolAPI] 获取工具列表失败: {e}")
            return []

    async def download_tool(self, tool_id: str, version: str,
                           progress_callback: Callable[[int], None] = None) -> bytes:
        """下载工具包"""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=300) as client:
                with client.stream(
                    "GET",
                    f"{self.base_url}{self.api_prefix}/{tool_id}/{version}/download",
                    headers=self._get_headers()
                ) as response:
                    response.raise_for_status()

                    total_size = int(response.headers.get("content-length", 0))
                    chunks = []
                    downloaded = 0

                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        chunks.append(chunk)
                        downloaded += len(chunk)

                        if progress_callback and total_size > 0:
                            progress = int(downloaded / total_size * 100)
                            progress_callback(progress)

                    return b"".join(chunks)

        except Exception as e:
            logger.error(f"[CloudToolAPI] 下载工具失败: {e}")
            raise

    async def check_updates(self, local_tools: list[dict[str, str]]) -> list[dict[str, Any]]:
        """检查工具更新"""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}{self.api_prefix}/check-updates",
                    json=local_tools,
                    headers=self._get_headers()
                )
                response.raise_for_status()
                data = response.json()
                return data.get("updates", [])

        except Exception as e:
            logger.error(f"[CloudToolAPI] 检查更新失败: {e}")
            return []

    async def get_tool_detail(self, tool_id: str, version: str) -> dict[str, Any] | None:
        """获取工具详情"""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}{self.api_prefix}/{tool_id}/{version}/detail",
                    headers=self._get_headers()
                )
                response.raise_for_status()
                return response.json()

        except Exception as e:
            logger.error(f"[CloudToolAPI] 获取工具详情失败: {e}")
            return None


# ============================================================================
# 安全扫描器
# ============================================================================

class SecurityScanner:
    """工具包安全扫描器"""

    def __init__(self):
        # 危险模式列表
        self.dangerous_patterns = [
            r'os\.system\s*\(',
            r'subprocess\.call\s*\(',
            r'subprocess\.run\s*\(',
            r'subprocess\.Popen\s*\(',
            r'eval\s*\(',
            r'exec\s*\(',
            r'compile\s*\(',
            r'__import__\s*\(',
            r'importlib\.import_module',
            r'open\s*\([^)]*["\']w',
            r'shutil\.rmtree',
            r'os\.remove\s*\(',
            r'os\.unlink\s*\(',
        ]

        # 允许的导入白名单
        self.allowed_imports = {
            'core.base_tool',
            'core.tool_manager',
            'core.logger',
            'typing',
            'json',
            'os',
            'sys',
            'time',
            'datetime',
            'pathlib',
            're',
            'math',
            'random',
            'hashlib',
            'base64',
            'urllib',
            'http',
        }

    async def scan(self, tool_package: bytes) -> dict[str, Any]:
        """
        扫描工具包安全性

        Returns:
            Dict: {
                "safe": bool,
                "score": float,
                "warnings": List[str],
                "errors": List[str]
            }
        """
        warnings = []
        errors = []
        score = 100.0

        try:
            # 解压到临时目录
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                package_path = tmp_path / "package.zip"

                import aiofiles
                async with aiofiles.open(package_path, "wb") as f:
                    await f.write(tool_package)

                extract_path = tmp_path / "extracted"
                await asyncio.to_thread(extract_path.mkdir)

                with zipfile.ZipFile(package_path, 'r') as zf:
                    zf.extractall(extract_path)

                # 扫描所有Python文件
                for py_file in extract_path.rglob("*.py"):
                    try:
                        content = await asyncio.to_thread(py_file.read_text, 'utf-8')

                        # 检查危险模式
                        import re
                        for pattern in self.dangerous_patterns:
                            matches = re.finditer(pattern, content, re.IGNORECASE)
                            for match in matches:
                                line_num = content[:match.start()].count('\n') + 1
                                errors.append(f"{py_file.name}:{line_num} 发现危险代码: {match.group()}")
                                score -= 10

                        # 检查导入语句
                        import_lines = re.findall(r'^(?:from|import)\s+([\w\.]+)', content, re.MULTILINE)
                        for imp in import_lines:
                            if not any(imp.startswith(allowed) for allowed in self.allowed_imports):
                                warnings.append(f"{py_file.name} 使用了非白名单导入: {imp}")
                                score -= 5

                        # AST语法检查
                        try:
                            import ast
                            ast.parse(content)
                        except SyntaxError as e:
                            errors.append(f"{py_file.name} 语法错误: {e}")
                            score -= 20

                    except Exception as e:
                        warnings.append(f"无法检查文件 {py_file.name}: {e}")

                # 检查必需文件
                if not any((extract_path / f).exists() for f in ["tool.py", "__init__.py", "manifest.json"]):
                    errors.append("工具包缺少入口文件 (tool.py, __init__.py 或 manifest.json)")
                    score -= 30

        except zipfile.BadZipFile:
            errors.append("无效的工具包格式")
            score = 0
        except Exception as e:
            errors.append(f"扫描过程出错: {e}")
            score -= 20

        # 确保分数在有效范围
        score = max(0, min(100, score))

        return {
            "safe": score >= 70 and len(errors) == 0,
            "score": score,
            "warnings": warnings,
            "errors": errors
        }


# ============================================================================
# 工具市场客户端主类
# ============================================================================

class ToolMarketClient:
    """
    本地工具市场客户端

    职责：
    1. 浏览云端工具市场
    2. 下载和安装工具
    3. 管理已安装工具
    4. 检查更新
    5. 版本管理
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, '_initialized', False):
            return
        self._initialized = True

        # 初始化组件
        self.cloud_api = CloudToolAPI()
        self.security_scanner = SecurityScanner()

        # 初始化工具管理器
        if TOOL_MANAGER_AVAILABLE:
            self.local_tool_manager = tool_manager
        else:
            self.local_tool_manager = None

        # 安装路径
        self.install_base_path = Path(os.getenv(
            "INSTALLED_TOOLS_PATH",
            str(Path(__file__).parent.parent / "tools" / "installed")
        ))
        self.install_base_path.mkdir(parents=True, exist_ok=True)

        # 已安装工具索引文件
        self.installed_index_path = self.install_base_path / "installed_index.json"
        self._installed_tools: dict[str, InstalledToolInfo] = {}
        self._load_installed_index()

        # 安装任务
        self._install_tasks: dict[str, InstallTask] = {}

        logger.info("[ToolMarketClient] 工具市场客户端初始化完成")
        logger.info(f"[ToolMarketClient] 安装路径: {self.install_base_path}")

    def _load_installed_index(self):
        """加载已安装工具索引"""
        if self.installed_index_path.exists():
            try:
                data = json.loads(self.installed_index_path.read_text())
                for tool_id, info_dict in data.items():
                    self._installed_tools[tool_id] = InstalledToolInfo(
                        tool_id=info_dict["tool_id"],
                        name=info_dict["name"],
                        version=info_dict["version"],
                        description=info_dict.get("description", ""),
                        author=info_dict.get("author", ""),
                        category=info_dict.get("category", "other"),
                        install_date=datetime.fromisoformat(info_dict["install_date"]),
                        install_path=Path(info_dict["install_path"]),
                        source=info_dict.get("source", "cloud"),
                        auto_update=info_dict.get("auto_update", True)
                    )
                logger.info(f"[ToolMarketClient] 已加载 {len(self._installed_tools)} 个已安装工具")
            except Exception as e:
                logger.error(f"[ToolMarketClient] 加载已安装工具索引失败: {e}")

    def _save_installed_index(self):
        """保存已安装工具索引"""
        try:
            data = {}
            for tool_id, info in self._installed_tools.items():
                data[tool_id] = {
                    "tool_id": info.tool_id,
                    "name": info.name,
                    "version": info.version,
                    "description": info.description,
                    "author": info.author,
                    "category": info.category,
                    "install_date": info.install_date.isoformat(),
                    "install_path": str(info.install_path),
                    "source": info.source,
                    "auto_update": info.auto_update
                }
            self.installed_index_path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.error(f"[ToolMarketClient] 保存已安装工具索引失败: {e}")

    # ========================================================================
    # 浏览和搜索
    # ========================================================================

    async def browse_tools(self, category: str = None, page: int = 1) -> list[CloudToolInfo]:
        """
        浏览云端工具市场

        Args:
            category: 分类筛选
            page: 页码

        Returns:
            List[CloudToolInfo]: 工具列表
        """
        return await self.cloud_api.get_tool_list(category, page)

    async def search_tools(self, query: str) -> list[CloudToolInfo]:
        """
        搜索云端工具

        Args:
            query: 搜索关键词

        Returns:
            List[CloudToolInfo]: 匹配的工具列表
        """
        # 获取所有工具然后本地过滤
        all_tools = await self.browse_tools()
        query_lower = query.lower()

        return [
            tool for tool in all_tools
            if query_lower in tool.name.lower()
            or query_lower in tool.description.lower()
            or any(query_lower in tag.lower() for tag in tool.tags)
        ]

    async def get_tool_detail(self, tool_id: str, version: str = None) -> dict[str, Any] | None:
        """
        获取工具详情

        Args:
            tool_id: 工具ID
            version: 版本号

        Returns:
            Optional[Dict]: 工具详情
        """
        return await self.cloud_api.get_tool_detail(tool_id, version or "latest")

    # ========================================================================
    # 安装管理
    # ========================================================================

    async def install_tool(
        self,
        tool_id: str,
        version: str = "latest",
        progress_callback: Callable[[str, int, str], None] = None
    ) -> InstallTask:
        """
        安装云端工具到本地

        Args:
            tool_id: 工具ID
            version: 版本号，默认最新
            progress_callback: 进度回调函数(task_id, progress, message)

        Returns:
            InstallTask: 安装任务
        """
        task_id = f"{tool_id}_{version}_{datetime.now().timestamp()}"
        task = InstallTask(
            task_id=task_id,
            tool_id=tool_id,
            version=version,
            status=InstallStatus.PENDING
        )
        self._install_tasks[task_id] = task

        def update_progress(progress: int, message: str):
            task.progress = progress
            task.message = message
            if progress_callback:
                progress_callback(task_id, progress, message)

        try:
            # 1. 获取工具详情
            update_progress(5, "获取工具信息...")
            detail = await self.get_tool_detail(tool_id, version)
            if not detail:
                raise Exception(f"工具不存在: {tool_id}")

            version = detail["data"]["version"]  # 获取实际版本号
            task.version = version

            # 2. 下载工具包
            update_progress(10, "开始下载...")

            def download_progress(p):
                update_progress(10 + int(p * 0.4), f"下载中... {p}%")

            task.status = InstallStatus.DOWNLOADING
            tool_package = await self.cloud_api.download_tool(tool_id, version, download_progress)

            # 3. 验证签名
            update_progress(50, "验证签名...")
            task.status = InstallStatus.VERIFYING
            if not await self._verify_signature(tool_package, detail):
                raise Exception("工具签名验证失败")

            # 4. 安全扫描
            update_progress(60, "安全扫描...")
            scan_result = await self.security_scanner.scan(tool_package)
            if not scan_result["safe"]:
                error_msg = f"安全扫描未通过: {'; '.join(scan_result['errors'])}"
                raise Exception(error_msg)

            # 5. 解压安装
            update_progress(70, "安装中...")
            task.status = InstallStatus.INSTALLING
            install_path = await self._install_package(tool_package, tool_id, version)

            # 6. 注册到工具管理器
            update_progress(90, "注册工具...")
            await self._register_tool(tool_id, version, install_path, detail["data"])

            # 7. 完成
            update_progress(100, "安装完成")
            task.status = InstallStatus.COMPLETED
            task.completed_at = datetime.now()

            logger.info(f"[ToolMarketClient] 工具安装成功: {tool_id} v{version}")

        except Exception as e:
            task.status = InstallStatus.FAILED
            task.error = str(e)
            logger.error(f"[ToolMarketClient] 工具安装失败: {tool_id} - {e}")

            # 尝试回滚
            await self._rollback_install(tool_id, version)

        return task

    async def uninstall_tool(self, tool_id: str) -> bool:
        """
        卸载工具

        Args:
            tool_id: 工具ID

        Returns:
            bool: 是否成功
        """
        try:
            if tool_id not in self._installed_tools:
                logger.warning(f"[ToolMarketClient] 工具未安装: {tool_id}")
                return False

            info = self._installed_tools[tool_id]

            # 1. 从工具管理器注销
            if self.local_tool_manager and hasattr(self.local_tool_manager, '_tools') and tool_id in self.local_tool_manager._tools:
                del self.local_tool_manager._tools[tool_id]

            # 2. 删除安装目录
            if info.install_path.exists():
                await asyncio.to_thread(shutil.rmtree, info.install_path)

            # 3. 更新索引
            del self._installed_tools[tool_id]
            self._save_installed_index()

            logger.info(f"[ToolMarketClient] 工具已卸载: {tool_id}")
            return True

        except Exception as e:
            logger.error(f"[ToolMarketClient] 卸载工具失败: {tool_id} - {e}")
            return False

    async def update_tool(self, tool_id: str) -> InstallTask:
        """
        更新工具到最新版本

        Args:
            tool_id: 工具ID

        Returns:
            InstallTask: 安装任务
        """
        # 先卸载旧版本
        await self.uninstall_tool(tool_id)

        # 安装新版本
        return await self.install_tool(tool_id, "latest")

    # ========================================================================
    # 更新检查
    # ========================================================================

    async def check_updates(self) -> list[dict[str, Any]]:
        """
        检查已安装工具的更新

        Returns:
            List[Dict]: 可更新的工具列表
        """
        if not self._installed_tools:
            return []

        local_tools = [
            {"tool_id": tool_id, "version": info.version}
            for tool_id, info in self._installed_tools.items()
            if info.auto_update
        ]

        return await self.cloud_api.check_updates(local_tools)

    async def auto_update_all(self) -> list[InstallTask]:
        """
        自动更新所有可更新的工具

        Returns:
            List[InstallTask]: 更新任务列表
        """
        updates = await self.check_updates()
        tasks = []

        for update in updates:
            task = await self.update_tool(update["tool_id"])
            tasks.append(task)

        return tasks

    # ========================================================================
    # 已安装工具管理
    # ========================================================================

    def get_installed_tools(self) -> list[InstalledToolInfo]:
        """
        获取所有已安装工具

        Returns:
            List[InstalledToolInfo]: 已安装工具列表
        """
        return list(self._installed_tools.values())

    def get_installed_tool(self, tool_id: str) -> InstalledToolInfo | None:
        """
        获取指定已安装工具信息

        Args:
            tool_id: 工具ID

        Returns:
            Optional[InstalledToolInfo]: 工具信息
        """
        return self._installed_tools.get(tool_id)

    def is_installed(self, tool_id: str) -> bool:
        """
        检查工具是否已安装

        Args:
            tool_id: 工具ID

        Returns:
            bool: 是否已安装
        """
        return tool_id in self._installed_tools

    def get_install_task(self, task_id: str) -> InstallTask | None:
        """
        获取安装任务状态

        Args:
            task_id: 任务ID

        Returns:
            Optional[InstallTask]: 任务信息
        """
        return self._install_tasks.get(task_id)

    # ========================================================================
    # 内部方法
    # ========================================================================

    async def _verify_signature(self, tool_package: bytes, detail: dict) -> bool:
        """验证工具签名"""
        # 简化的签名验证，实际生产环境需要更安全的实现
        try:
            # 如果云端提供了签名，则验证
            cloud_signature = detail.get("data", {}).get("signature")
            if not cloud_signature:
                # 没有签名时，仅检查包完整性
                return len(tool_package) > 0

            # HMAC签名验证
            secret = os.getenv("TOOL_SIGNING_SECRET", "default_secret_key_change_in_production")
            expected_signature = hmac.new(
                secret.encode(),
                tool_package,
                hashlib.sha256
            ).hexdigest()

            return hmac.compare_digest(cloud_signature, expected_signature)

        except Exception as e:
            logger.error(f"[ToolMarketClient] 签名验证失败: {e}")
            return False

    async def _install_package(self, tool_package: bytes, tool_id: str, version: str) -> Path:
        """解压安装工具包"""
        install_path = self.install_base_path / tool_id / version

        # 如果已存在，先删除
        if install_path.exists():
            await asyncio.to_thread(shutil.rmtree, install_path)

        await asyncio.to_thread(install_path.mkdir, True)

        # 解压
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp.write(tool_package)
            tmp_path = tmp.name

        try:
            with zipfile.ZipFile(tmp_path, 'r') as zf:
                zf.extractall(install_path)
        finally:
            await asyncio.to_thread(os.unlink, tmp_path)

        return install_path

    async def _register_tool(self, tool_id: str, version: str, install_path: Path, metadata: dict):
        """注册工具到本地工具管理器"""
        # 1. 添加到已安装索引
        installed_info = InstalledToolInfo(
            tool_id=tool_id,
            name=metadata.get("name", tool_id),
            version=version,
            description=metadata.get("description", ""),
            author=metadata.get("author", ""),
            category=metadata.get("category", "other"),
            install_date=datetime.now(),
            install_path=install_path,
            source="cloud"
        )
        self._installed_tools[tool_id] = installed_info
        self._save_installed_index()

        # 2. 动态加载工具
        if TOOL_MANAGER_AVAILABLE and self.local_tool_manager:
            try:
                # 将安装路径添加到sys.path
                if str(install_path) not in sys.path:
                    sys.path.insert(0, str(install_path))

                # 查找并加载工具类
                for py_file in install_path.glob("*.py"):
                    if py_file.name.startswith("_"):
                        continue

                    module_name = py_file.stem
                    try:
                        import importlib.util
                        spec = importlib.util.spec_from_file_location(
                            f"installed.{tool_id}.{module_name}",
                            py_file
                        )
                        if spec and spec.loader:
                            module = importlib.util.module_from_spec(spec)
                            sys.modules[spec.name] = module
                            spec.loader.exec_module(module)

                            # 查找BaseTool子类
                            if BASE_TOOL_AVAILABLE:
                                for attr_name in dir(module):
                                    attr = getattr(module, attr_name)
                                    if (isinstance(attr, type) and
                                        issubclass(attr, BaseTool) and
                                        attr != BaseTool):
                                        tool = attr()
                                        # 注册到工具管理器
                                        self.local_tool_manager._tools[tool_id] = tool
                                        logger.info(f"[ToolMarketClient] 工具已注册: {tool_id}")
                                        break
                    except Exception as e:
                        logger.warning(f"[ToolMarketClient] 加载模块失败 {module_name}: {e}")

            except Exception as e:
                logger.error(f"[ToolMarketClient] 注册工具失败: {e}")
                raise

    async def _rollback_install(self, tool_id: str, version: str):
        """回滚安装"""
        try:
            install_path = self.install_base_path / tool_id / version
            if install_path.exists():
                await asyncio.to_thread(shutil.rmtree, install_path)

            if tool_id in self._installed_tools:
                del self._installed_tools[tool_id]
                self._save_installed_index()

        except Exception as e:
            logger.error(f"[ToolMarketClient] 回滚安装失败: {e}")


# 全局客户端实例
tool_market_client = ToolMarketClient()


# 导出
__all__ = [
    'ToolMarketClient',
    'tool_market_client',
    'CloudToolAPI',
    'SecurityScanner',
    'InstallTask',
    'InstallStatus',
    'InstalledToolInfo',
    'CloudToolInfo'
]
