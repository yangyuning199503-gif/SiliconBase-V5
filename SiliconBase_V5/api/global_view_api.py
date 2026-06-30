#!/usr/bin/env python3
"""
GlobalView API - 磁盘文件扫描可视化接口
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
提供文件扫描结果的可视化展示和管理接口

端点列表:
- GET    /api/global-view/status           - 获取扫描状态
- GET    /api/global-view/tree             - 获取文件树结构
- GET    /api/global-view/search           - 搜索文件
- POST   /api/global-view/scan/start       - 开始全盘扫描
- POST   /api/global-view/scan/stop        - 停止扫描
- DELETE /api/global-view/clear            - 清空所有扫描数据
- GET    /api/global-view/stats            - 获取统计信息

Author: SiliconBase Team
Version: 1.0.0
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# 导入认证依赖
try:
    from api.auth_utils import get_current_user
    AUTH_AVAILABLE = True
except ImportError:
    try:
        from .auth_utils import get_current_user
        AUTH_AVAILABLE = True
    except ImportError as e:
        AUTH_AVAILABLE = False
        logger.error(f"[GlobalViewAPI] 认证模块导入失败: {e}")

        async def get_current_user() -> str | None:
            raise HTTPException(status_code=503, detail="认证服务不可用")

# 只在认证模块可用时添加认证依赖
router_dependencies = [Depends(get_current_user)] if AUTH_AVAILABLE else []
router = APIRouter(
    prefix="/global-view",
    tags=["global-view"],
    dependencies=router_dependencies
)


# ═══════════════════════════════════════════════════════════════════
# Pydantic 模型定义
# ═══════════════════════════════════════════════════════════════════

class FileNode(BaseModel):
    """文件树节点"""
    id: str = Field(..., description="唯一标识")
    name: str = Field(..., description="文件/目录名")
    path: str = Field(..., description="完整路径")
    type: str = Field(..., description="类型: file/folder")
    size: int | None = Field(default=None, description="文件大小(字节)")
    modified_time: str | None = Field(default=None, description="修改时间")
    file_type: str | None = Field(default=None, description="文件类型分类")
    is_executable: bool | None = Field(default=None, description="是否可执行")
    children: list['FileNode'] | None = Field(default=None, description="子节点(目录)")
    scanned_at: str | None = Field(default=None, description="扫描时间")


class FileTreeResponse(BaseModel):
    """文件树响应"""
    drives: list[FileNode] = Field(..., description="磁盘列表")
    total_files: int = Field(..., description="总文件数")
    total_size: int = Field(..., description="总大小(字节)")
    last_scan: str | None = Field(default=None, description="最后扫描时间")


class ScanStatusResponse(BaseModel):
    """扫描状态响应"""
    is_scanning: bool = Field(..., description="是否正在扫描")
    progress: int = Field(..., description="进度百分比(0-100)")
    current_drive: str | None = Field(default=None, description="当前扫描磁盘")
    scanned_files: int = Field(..., description="已扫描文件数")
    total_files: int = Field(..., description="预估总文件数")
    message: str | None = Field(default=None, description="状态消息")
    last_scan_completed: str | None = Field(default=None, description="上次完成时间")


class SearchRequest(BaseModel):
    """搜索请求"""
    keyword: str = Field(..., description="搜索关键词")
    file_type: str | None = Field(default=None, description="文件类型过滤")
    limit: int = Field(default=20, ge=1, le=100, description="返回数量限制")


class SearchResponse(BaseModel):
    """搜索响应"""
    results: list[FileNode] = Field(..., description="搜索结果")
    total: int = Field(..., description="总数")
    keyword: str = Field(..., description="搜索关键词")


class StatsResponse(BaseModel):
    """统计信息响应"""
    total_files: int = Field(..., description="总文件数")
    total_folders: int = Field(..., description="总目录数")
    total_size: int = Field(..., description="总大小")
    by_type: dict[str, int] = Field(..., description="按类型统计")
    by_drive: dict[str, int] = Field(..., description="按磁盘统计")
    last_scan: str | None = Field(default=None, description="最后扫描时间")


class MessageResponse(BaseModel):
    """通用消息响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="消息内容")


# ═══════════════════════════════════════════════════════════════════
# API 端点实现
# ═══════════════════════════════════════════════════════════════════

@router.get("/status", response_model=ScanStatusResponse)
async def get_scan_status(user_id: str = Depends(get_current_user)):
    """
    获取当前扫描状态

    返回扫描进度、是否正在扫描等信息
    （不依赖数据库，避免连接池耗尽时无法响应）
    """
    try:
        from sensors.system.global_view import SCAN_PROGRESS, global_view_instance

        # 从全局实例获取扫描状态
        is_scanning = False
        if global_view_instance:
            is_scanning = getattr(global_view_instance, '_scanning', False)

        return ScanStatusResponse(
            is_scanning=is_scanning,
            progress=SCAN_PROGRESS.get("progress", 0),
            current_drive=SCAN_PROGRESS.get("current_drive"),
            scanned_files=SCAN_PROGRESS.get("current", 0),
            total_files=SCAN_PROGRESS.get("total", 0),
            message=SCAN_PROGRESS.get("message", ""),
            last_scan_completed=None
        )
    except Exception as e:
        logger.error(f"[GlobalViewAPI] 获取扫描状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取扫描状态失败: {str(e)}") from e


@router.get("/tree", response_model=FileTreeResponse)
async def get_file_tree(
    drive: str | None = Query(default=None, description="指定磁盘，如C、D"),
    max_depth: int = Query(default=3, ge=1, le=10, description="最大深度"),
    user_id: str = Depends(get_current_user)
):
    """
    获取文件树结构

    以树状结构返回扫描的文件目录，支持按磁盘和深度过滤
    """
    try:
        from sensors.system.global_view import SoftwareDB

        db = SoftwareDB()

        # 获取所有文件
        all_files = db.get_all_files(user_id=user_id)

        # 构建树结构
        tree_builder = _TreeBuilder(max_depth=max_depth)

        for file_info in all_files:
            # 如果指定了磁盘，过滤
            if drive and not file_info.get('file_path', '').upper().startswith(f"{drive.upper()}:"):
                continue
            tree_builder.add_file(file_info)

        drives = tree_builder.get_drives()

        # 计算统计
        total_files = len(all_files)
        total_size = sum(f.get('file_size', 0) for f in all_files)

        return FileTreeResponse(
            drives=drives,
            total_files=total_files,
            total_size=total_size,
            last_scan=None
        )

    except Exception as e:
        logger.error(f"[GlobalViewAPI] 获取文件树失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取文件树失败: {str(e)}") from e


@router.get("/search", response_model=SearchResponse)
async def search_files(
    keyword: str = Query(..., description="搜索关键词"),
    file_type: str | None = Query(default=None, description="文件类型过滤"),
    limit: int = Query(default=20, ge=1, le=100),
    user_id: str = Depends(get_current_user)
):
    """
    搜索文件

    支持文件名模糊搜索和类型过滤
    """
    try:
        from sensors.system.global_view import global_view_instance

        if not global_view_instance:
            raise HTTPException(status_code=503, detail="GlobalView服务未初始化")

        results = global_view_instance.smart_file_search(
            query=keyword,
            user_id=user_id,
            limit=limit
        )

        # 转换为FileNode列表
        file_nodes = []
        for item in results.get('results', []):
            file_nodes.append(FileNode(
                id=item.get('id', ''),
                name=item.get('file_name', ''),
                path=item.get('file_path', ''),
                type='file',
                size=item.get('file_size'),
                modified_time=item.get('modified_time'),
                file_type=item.get('file_type')
            ))

        return SearchResponse(
            results=file_nodes,
            total=len(file_nodes),
            keyword=keyword
        )

    except Exception as e:
        logger.error(f"[GlobalViewAPI] 搜索文件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}") from e


@router.post("/scan/start", response_model=MessageResponse)
async def start_scan(
    drives: list[str] | None = None,
    user_id: str = Depends(get_current_user)
):
    """
    开始全盘扫描

    启动后台扫描任务，扫描指定磁盘或所有磁盘
    """
    try:
        from sensors.system.global_view import global_view_instance

        if not global_view_instance:
            raise HTTPException(status_code=503, detail="GlobalView服务未初始化")

        # 检查是否已在扫描
        if getattr(global_view_instance, '_scanning', False):
            return MessageResponse(
                success=False,
                message="扫描已在进行中"
            )

        # 启动扫描（后台线程）
        import threading
        scan_thread = threading.Thread(
            target=global_view_instance.start_full_disk_scan,
            args=(user_id,),
            daemon=True
        )
        scan_thread.start()

        return MessageResponse(
            success=True,
            message="扫描任务已启动"
        )

    except Exception as e:
        logger.error(f"[GlobalViewAPI] 启动扫描失败: {e}")
        raise HTTPException(status_code=500, detail=f"启动扫描失败: {str(e)}") from e


@router.post("/scan/stop", response_model=MessageResponse)
async def stop_scan(user_id: str = Depends(get_current_user)):
    """
    停止扫描

    中断当前正在进行的扫描任务
    """
    try:
        from sensors.system.global_view import global_view_instance

        if not global_view_instance:
            raise HTTPException(status_code=503, detail="GlobalView服务未初始化")

        # 设置停止标志
        if hasattr(global_view_instance, '_scan_stop_flag') and global_view_instance._scan_stop_flag is not None:
            global_view_instance._scan_stop_flag.set()

        return MessageResponse(
            success=True,
            message="扫描停止信号已发送"
        )

    except Exception as e:
        logger.error(f"[GlobalViewAPI] 停止扫描失败: {e}")
        raise HTTPException(status_code=500, detail=f"停止扫描失败: {str(e)}") from e


@router.delete("/clear", response_model=MessageResponse)
async def clear_all_data(user_id: str = Depends(get_current_user)):
    """
    清空所有扫描数据

    删除该用户的所有文件扫描记录（不可逆操作）
    """
    try:
        from sensors.system.global_view import global_view_instance

        if not global_view_instance:
            raise HTTPException(status_code=503, detail="GlobalView服务未初始化")

        # 调用清理方法
        deleted_count = global_view_instance.clear_user_data(user_id)

        return MessageResponse(
            success=True,
            message=f"已清空 {deleted_count} 条扫描记录"
        )

    except Exception as e:
        logger.error(f"[GlobalViewAPI] 清空数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"清空数据失败: {str(e)}") from e


@router.get("/stats", response_model=StatsResponse)
async def get_stats(user_id: str = Depends(get_current_user)):
    """
    获取统计信息

    返回文件数量、大小、类型分布等统计
    """
    try:
        from sensors.system.global_view import SoftwareDB

        db = SoftwareDB()
        all_files = db.get_all_files(user_id=user_id)

        # 按类型统计
        by_type: dict[str, int] = {}
        by_drive: dict[str, int] = {}
        total_size = 0

        for f in all_files:
            # 类型统计
            ft = f.get('file_type', 'other')
            by_type[ft] = by_type.get(ft, 0) + 1

            # 磁盘统计
            path = f.get('file_path', '')
            if len(path) > 1 and path[1] == ':':
                drive = path[0].upper()
                by_drive[drive] = by_drive.get(drive, 0) + 1

            total_size += f.get('file_size', 0)

        return StatsResponse(
            total_files=len(all_files),
            total_folders=0,
            total_size=total_size,
            by_type=by_type,
            by_drive=by_drive,
            last_scan=None
        )

    except Exception as e:
        logger.error(f"[GlobalViewAPI] 获取统计失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取统计失败: {str(e)}") from e


# ═══════════════════════════════════════════════════════════════════
# 辅助类
# ═══════════════════════════════════════════════════════════════════

class _TreeBuilder:
    """树结构构建器"""

    def __init__(self, max_depth: int = 3):
        self.max_depth = max_depth
        self.drives: dict[str, FileNode] = {}
        self._node_cache: dict[str, FileNode] = {}

    def add_file(self, file_info: dict):
        """添加文件到树"""
        path = file_info.get('file_path', '')
        if not path:
            return

        # 解析路径
        parts = path.replace('\\', '/').split('/')
        if not parts:
            return

        # 获取磁盘
        drive = parts[0]
        if drive not in self.drives:
            self.drives[drive] = FileNode(
                id=f"drive_{drive}",
                name=drive,
                path=drive,
                type='folder',
                children=[]
            )

        # 构建目录结构
        current = self.drives[drive]
        current_path = drive

        for i, part in enumerate(parts[1:], 1):
            if i > self.max_depth:
                break

            current_path = f"{current_path}/{part}"

            # 检查是否已存在
            found = None
            if current.children:
                for child in current.children:
                    if child.name == part:
                        found = child
                        break

            if not found:
                is_last = (i == len(parts) - 1)
                new_node = FileNode(
                    id=f"node_{current_path}",
                    name=part,
                    path=current_path,
                    type='file' if is_last else 'folder',
                    children=[] if not is_last else None,
                    size=file_info.get('file_size') if is_last else None,
                    modified_time=file_info.get('modified_time'),
                    file_type=file_info.get('file_type') if is_last else None
                )
                if current.children is None:
                    current.children = []
                current.children.append(new_node)
                current = new_node
            else:
                current = found

    def get_drives(self) -> list[FileNode]:
        """获取磁盘列表"""
        return list(self.drives.values())
