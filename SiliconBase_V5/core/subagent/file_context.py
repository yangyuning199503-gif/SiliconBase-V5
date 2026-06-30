#!/usr/bin/env python3
"""
子代理文件上下文注入
让子代理能"看到"项目结构和相关文件
"""
import logging
import os

logger = logging.getLogger(__name__)


class SubAgentFileContext:
    """为子代理提供文件系统上下文"""

    async def get_context_for_task(self, task_description: str, work_dir: str = None) -> str:
        """
        根据任务描述决定给子代理提供什么文件上下文
        """
        work_dir = work_dir or os.getcwd()

        # 分析任务类型
        if any(k in task_description for k in ["修改", "修复", "更新", "优化"]):
            return self._get_relevant_files_context(task_description, work_dir)

        elif any(k in task_description for k in ["新建", "创建", "添加"]):
            return self._get_project_structure_summary(work_dir)

        elif any(k in task_description for k in ["查找", "搜索", "定位"]):
            return await self._get_file_location_hint(task_description)

        return ""

    def _get_relevant_files_context(self, task: str, work_dir: str) -> str:
        """智能找出任务相关的文件"""
        keywords = self._extract_keywords(task)
        relevant_files = []

        for root, _dirs, files in os.walk(work_dir):
            if root.count(os.sep) - work_dir.count(os.sep) > 2:
                break

            for f in files:
                if any(kw in f.lower() for kw in keywords):
                    file_path = os.path.join(root, f)
                    try:
                        with open(file_path, encoding="utf-8", errors="ignore") as fp:
                            content = fp.read(2000)
                        relevant_files.append({
                            "path": file_path,
                            "name": f,
                            "preview": content[:500]
                        })
                    except (OSError, PermissionError) as e:
                        logger.error(f"[FileContext] 读取文件失败 {file_path}: {e}", exc_info=True)
                        raise RuntimeError(f"无法读取文件 {file_path}: {e}") from e

        if not relevant_files:
            return ""

        context = "【相关文件】\n"
        for f in relevant_files[:3]:
            context += f"\n📄 {f['path']}\n"
            context += f"```\n{f['preview'][:300]}\n```\n"

        return context

    def _get_project_structure_summary(self, work_dir: str) -> str:
        """获取项目结构摘要"""
        structure = []

        for item in os.scandir(work_dir):
            if item.is_dir() and not item.name.startswith("."):
                file_count = len([f for f in os.listdir(item.path) if os.path.isfile(os.path.join(item.path, f))])
                structure.append(f"📁 {item.name}/ ({file_count}个文件)")
            elif item.is_file():
                if item.name.endswith((".py", ".md", ".json", ".yaml")):
                    structure.append(f"📄 {item.name}")

        if not structure:
            return ""

        return "【项目结构】\n" + "\n".join(structure[:15])

    async def _get_file_location_hint(self, task: str) -> str:
        """从记忆系统获取文件位置"""
        try:
            from core.memory.memory_service import get_memory_service

            ms = await get_memory_service()
            results = await ms.query_memories(
                user_id="default_user",
                layer="medium",
                mem_type="file_location",
                limit=3
            )

            if not results:
                return ""

            context = "【文件位置】\n"
            for r in results:
                content = r.get("content", "")
                if ":" in content:
                    name, path = content.split(":", 1)
                    context += f"• {name}: {path}\n"

            return context

        except (ImportError, AttributeError, ConnectionError) as e:
            logger.error(f"[FileContext] 记忆查询失败: {e}", exc_info=True)
            # 不返回空字符串，而是抛出异常让上层处理
            raise RuntimeError(f"记忆查询失败: {e}") from e

    def _extract_keywords(self, text: str) -> list[str]:
        """从文本提取关键词"""
        keywords = []
        for ext in [".py", ".js", ".json", ".yaml", ".md", ".txt", ".ini"]:
            if ext in text:
                keywords.append(ext)

        words = text.lower().split()
        for w in words:
            if len(w) > 3 and w not in ["修改", "修复", "更新", "文件", "代码"]:
                keywords.append(w)

        return list(set(keywords))[:5]


async def inject_file_context_to_subagent(task: str, runtime_context: dict) -> dict:
    """在创建子代理时调用，注入文件上下文"""
    context_provider = SubAgentFileContext()
    file_context = await context_provider.get_context_for_task(task)

    if file_context:
        runtime_context['file_system_context'] = file_context

    return runtime_context
