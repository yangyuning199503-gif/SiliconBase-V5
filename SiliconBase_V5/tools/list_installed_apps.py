#!/usr/bin/env python3
"""
原子工具：列出已安装软件
获取系统中所有已安装的软件列表，包括名称和路径
"""
import asyncio

from core.base_tool import BaseTool
from core.error_codes import TOOL_EXECUTION_ERROR, format_error
from core.logger import logger


class ListInstalledApps(BaseTool):
    tool_id = "list_installed_apps"
    name = "列出已安装软件"
    description = "获取系统中所有已安装的软件列表，包括名称、路径、版本等信息。适用于用户想查看电脑上已安装软件的场景。"
    input_schema = {
        "type": "object",
        "properties": {
            "keyword": {"type": "string", "description": "可选，过滤关键字，只返回名称包含此关键字的软件"},
            "limit": {"type": "integer", "default": 100, "description": "返回结果数量限制，默认100"}
        }
    }

    def _execute(self, **kwargs):
        try:
            # 延迟导入 global_view 避免循环导入
            from sensors.system.global_view import global_view

            keyword = kwargs.get("keyword", "").strip()
            limit = kwargs.get("limit", 100)

            # 获取所有软件列表
            if keyword:
                # 有关键字时，使用搜索功能
                apps = global_view.find_software(keyword)
                logger.info(f"搜索软件，关键字: '{keyword}'，找到 {len(apps)} 个")
            else:
                # 无关键字时，获取所有软件
                apps = global_view.get_all_software()
                logger.info(f"获取所有软件，共 {len(apps)} 个")

            # 限制返回数量
            total = len(apps)
            if limit > 0 and len(apps) > limit:
                apps = apps[:limit]

            # 格式化返回结果
            formatted_apps = []
            for app in apps:
                formatted_apps.append({
                    "name": app.get("name", ""),
                    "path": app.get("install_path", ""),
                    "version": app.get("version", ""),
                    "process_name": app.get("process_name", ""),
                    "launch_count": app.get("launch_count", 0)
                })

            user_msg = f"找到 {len(formatted_apps)} 个已安装软件" if keyword else f"共 {len(formatted_apps)} 个已安装软件"
            return {
                "success": True,
                "error_code": None,
                "user_message": user_msg,
                "data": {
                    "apps": formatted_apps,
                    "total": total,
                    "returned": len(formatted_apps),
                    "keyword": keyword if keyword else None
                }
            }

        except Exception as e:
            logger.error(f"获取已安装软件列表失败: {e}")
            return format_error(TOOL_EXECUTION_ERROR, detail=f"获取软件列表失败: {str(e)}")

    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)
