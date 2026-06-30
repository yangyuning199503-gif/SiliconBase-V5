#!/usr/bin/env python3
"""
UI 元素知识管理模块
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
职责：
1. 将大模型标注结果转换为 MemoryManager 可存储的记忆记录（mem_type="ui_element"）
2. 调用 memory_manager.add_memory() 存入向量记忆库
3. 提供查询接口 query_ui_knowledge(features: str) -> List[Dict]

设计原则：
- 大脑与感官解耦：记忆存储失败绝不中断主循环
- 所有异步方法正确 await
- 所有异常显式日志，不得静默失败
"""

import json
import time
from typing import Any

from core.logger import logger

# MemoryManager 单例
try:
    from core.memory.memory_manager import memory_manager
except ImportError as e:
    logger.warning(f"[VisionElementKnowledge] memory_manager 导入失败: {e}")
    memory_manager = None


def _build_ui_element_content(label: dict[str, str], obj: dict[str, Any]) -> str:
    """
    将 AI 标签和原始对象信息构建为自然语言描述，用于向量检索。

    【V2增强】加入 context_vector 信息（应用/窗口/页面），
    使向量检索可以区分"chrome 的搜索框"和"edge 的搜索框"。

    【字段兼容】同时支持大模型原始字段(element_type/function/interaction)
    和记忆库字段(label/description/action)。
    """
    element_type = label.get("element_type") or label.get("label", "未知元素")
    function_desc = label.get("function") or label.get("description", "未知功能")
    interaction = label.get("interaction") or label.get("action", "click")
    source = obj.get("source", "unknown")
    confidence = obj.get("confidence", 0.0)

    # 【V2新增】context_vector 注入到检索文本
    app_name = obj.get("app_name", "")
    window_title = obj.get("window_title", "")
    page_state = obj.get("page_state", "")

    context_parts = []
    if app_name:
        context_parts.append(f"应用: {app_name}")
    if window_title:
        context_parts.append(f"窗口: {window_title}")
    if page_state:
        context_parts.append(f"页面: {page_state}")
    context_str = "。".join(context_parts)
    if context_str:
        context_str = "。" + context_str

    content = (
        f"UI元素类型: {element_type}。"
        f"功能: {function_desc}。"
        f"交互方式: {interaction}。"
        f"检测来源: {source}。"
        f"原始置信度: {confidence:.2f}"
        f"{context_str}。"
    )
    return content


# 【V2新增】视觉记忆存储配额
class VisualMemoryQuota:
    MAX_ELEMENTS_PER_APP = 200
    MAX_TOTAL_ELEMENTS = 2000


# 内存中的配额计数器（进程级，重启后从 0 开始，ChromaDB 中已有数据不受影响）
_app_element_counts: dict[str, int] = {}
_total_element_count = 0


async def store_ui_element_knowledge(
    discovered_elements: list[dict[str, Any]],
    user_id: str = "default",
    scene: str = "",
) -> list[str]:
    """
    将未知元素发现模块的标注结果存入向量记忆库。

    Args:
        discovered_elements: discover_and_label_unknowns() 返回的列表
        user_id: 用户标识
        scene: 场景描述（如"网易云音乐"、"桌面"）

    Returns:
        成功存储的记忆 ID 列表
    """
    global _total_element_count

    if memory_manager is None:
        logger.warning("[VisionElementKnowledge] memory_manager 不可用，跳过存储")
        return []

    stored_ids: list[str] = []

    for elem in discovered_elements:
        label = elem.get("ai_label")
        if not label:
            continue

        try:
            content = _build_ui_element_content(label, elem)

            # 【修复】查重：若已有相似度 > 0.9 的 ui_element 记忆，则跳过
            duplicates = await memory_manager.retrieve_memory(
                query=content,
                mem_type="ui_element",
                limit=3,
                use_vector=True,
                use_cache=False,
            )
            has_duplicate = False
            for dup in duplicates:
                sim = dup.get("similarity", 0.0)
                if sim > 0.9:
                    logger.debug(
                        f"[VisionElementKnowledge] 相似 UI 元素知识已存在 "
                        f"(similarity={sim:.3f})，跳过写入: {label.get('element_type')}"
                    )
                    has_duplicate = True
                    break
            if has_duplicate:
                continue

            # 【V2新增】配额检查
            app_key = elem.get("app_name", scene or "unknown")
            current_app_count = _app_element_counts.get(app_key, 0)
            if current_app_count >= VisualMemoryQuota.MAX_ELEMENTS_PER_APP:
                logger.warning(
                    f"[VisionElementKnowledge] 应用 {app_key} 的视觉记忆已达上限 "
                    f"{VisualMemoryQuota.MAX_ELEMENTS_PER_APP}，跳过写入"
                )
                continue
            if _total_element_count >= VisualMemoryQuota.MAX_TOTAL_ELEMENTS:
                logger.warning(
                    f"[VisionElementKnowledge] 总视觉记忆已达上限 "
                    f"{VisualMemoryQuota.MAX_TOTAL_ELEMENTS}，跳过写入"
                )
                continue

            metadata = {
                "element_type": label.get("element_type"),
                "function": label.get("function"),
                "interaction": label.get("interaction"),
                "bbox": elem.get("bbox"),
                "source": elem.get("source"),
                "discovered_at": elem.get("discovered_at", time.time()),
                "original_confidence": elem.get("confidence"),
                # 【P1修复】场景关联字段
                "app_name": elem.get("app_name", ""),
                "window_title": elem.get("window_title", ""),
                "page_state": elem.get("page_state", ""),
                "recalled_from": elem.get("recalled_from", ""),
            }

            # 使用 memory_manager.add_memory 存入向量层
            mem_id = await memory_manager.add_memory(
                user_id=user_id,
                content=content,
                memory_type="ui_element",
                metadata=metadata,
                layer="medium",           # 中层记忆，UI 元素知识需要保留一段时间
                expire_days=30,           # 30 天过期，可定期刷新
                scene=scene or "unknown",
                source="vision_unknown_discovery",
            )

            # 【V2新增】更新配额计数器
            _app_element_counts[app_key] = current_app_count + 1
            _total_element_count += 1

            stored_ids.append(mem_id)
            logger.info(
                f"[VisionElementKnowledge] UI 元素知识已入库 "
                f"[mem_id={mem_id}, type={label.get('element_type')}]"
            )

        except Exception as e:
            logger.error(
                f"[VisionElementKnowledge] 存储 UI 元素知识失败: {e}",
                exc_info=False,
            )
            continue

    return stored_ids


async def query_ui_knowledge(
    features: str,
    user_id: str = "default",
    limit: int = 5,
) -> list[dict[str, Any]]:
    """
    用自然语言描述查询向量记忆库中相似的 UI 元素知识。

    Args:
        features: 特征描述，例如"关闭按钮"、"搜索框"
        user_id: 用户标识
        limit: 返回数量上限

    Returns:
        相似 UI 元素知识列表
    """
    if memory_manager is None:
        logger.warning("[VisionElementKnowledge] memory_manager 不可用，返回空结果")
        return []

    try:
        results = await memory_manager.retrieve_memory(
            query=features,
            mem_type="ui_element",
            limit=limit,
            use_vector=True,
            use_cache=True,
        )

        # 统一输出格式
        formatted: list[dict[str, Any]] = []
        for r in results:
            content = r.get("content", "")
            # 如果 content 是 JSON 字符串，尝试解析
            if isinstance(content, str):
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, dict) and "text" in parsed:
                        content = parsed["text"]
                except Exception:
                    pass

            metadata = r.get("metadata", {})
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except Exception:
                    metadata = {}

            formatted.append({
                "memory_id": r.get("id") or r.get("memory_id"),
                "content": content,
                "element_type": metadata.get("element_type") if isinstance(metadata, dict) else None,
                "function": metadata.get("function") if isinstance(metadata, dict) else None,
                "interaction": metadata.get("interaction") if isinstance(metadata, dict) else None,
                "scene": r.get("scene", ""),
                "similarity": r.get("similarity", 0.0),
                "timestamp": r.get("timestamp") or r.get("created_at"),
                # 【P1修复】场景关联字段透出
                "app_name": metadata.get("app_name", "") if isinstance(metadata, dict) else "",
                "window_title": metadata.get("window_title", "") if isinstance(metadata, dict) else "",
                "page_state": metadata.get("page_state", "") if isinstance(metadata, dict) else "",
            })

        logger.debug(
            f"[VisionElementKnowledge] 查询 '{features}' 返回 {len(formatted)} 条结果"
        )
        return formatted

    except Exception as e:
        logger.error(f"[VisionElementKnowledge] 查询 UI 知识失败: {e}", exc_info=False)
        return []
