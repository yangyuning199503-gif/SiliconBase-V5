#!/usr/bin/env python3
"""
LLM 语义压缩器
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
将多轮对话中间消息压缩为结构化摘要，供 Prompt 模板卡槽消费。

核心设计：
- 不硬编码模型名，通过 ai_config.get_config(AIScene.SUMMARY) 动态获取
- 压缩只针对"被截断的中间消息"，不是近期对话
- JSON 解析失败时容错回退，不抛异常导致主循环崩溃
"""

import json

from core.ai.ai_adapter import call_thinker_async
from core.ai.ai_config import AIScene, ai_config
from core.logger import logger

COMPRESSION_PROMPT_TEMPLATE = """你是一个专业的对话上下文压缩器。
请分析以下多轮对话记录，提取关键信息并填充到指定的 JSON 结构中。

【压缩规则】
1. 必须保留：未完成的任务、关键结论、用户的明确指令变更、失败教训
2. 必须丢弃：重复确认、闲聊寒暄、无信息量的过程性描述
3. 必须识别：是否涉及"项目定位变更"或"长期目标调整"（如有，在 global_update 中标注）

【对话记录】
{conversation_text}

【输出格式】
请严格返回以下 JSON，不要带任何其他解释：

{{
  "recent_progress": "提炼所有未完成任务和关键结论，不超过150字",
  "current_task_status": "状态标签+一句描述，如：进行中|正在尝试方案B",
  "key_entities": ["实体1", "实体2"],
  "compressed_summary": "保留逻辑链条的最大精简摘要，压缩到原文20%以内",
  "global_update": "如涉及项目定位/长期目标变更，在此说明；否则填null"
}}
"""


def _build_compression_prompt(messages: list[dict]) -> str:
    """将消息列表拼接为压缩器可读的对话文本。"""
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        # 过滤掉内部标记字段，只保留 role/content
        lines.append(f"[{role.upper()}] {content}")
    return COMPRESSION_PROMPT_TEMPLATE.format(conversation_text="\n\n".join(lines))


def _parse_compression_json(raw: str) -> dict:
    """解析 LLM 返回的 JSON，容错处理。"""
    text = raw.strip()
    # 尝试提取 ```json ... ``` 代码块
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        logger.warning(f"[LLMCompressor] JSON 解析失败，尝试回退解析: {text[:200]}")
        result = {
            "recent_progress": "",
            "current_task_status": "未知",
            "key_entities": [],
            "compressed_summary": text[:500],
            "global_update": None,
        }

    # 确保字段存在且类型正确
    for key in ("recent_progress", "current_task_status", "compressed_summary"):
        if key not in result or not isinstance(result[key], str):
            result[key] = ""
    if "key_entities" not in result or not isinstance(result.get("key_entities"), list):
        result["key_entities"] = []
    if "global_update" not in result:
        result["global_update"] = None

    return result


async def compress_conversation(
    messages: list[dict],
    target_tokens: int = 500,
    model: str | None = None,
) -> dict:
    """
    压缩对话消息列表为结构化摘要。

    Args:
        messages: 待压缩的消息列表（被截断的中间消息）
        target_tokens: 目标 token 数（用于指导压缩程度，当前仅作参考）
        model: 可选，强制指定压缩所用模型。不传则使用 SUMMARY 场景配置的模型。

    Returns:
        Dict: 包含 recent_progress / current_task_status / key_entities /
              compressed_summary / global_update 的字典
    """
    if not messages:
        return {
            "recent_progress": "",
            "current_task_status": "无历史任务",
            "key_entities": [],
            "compressed_summary": "",
            "global_update": None,
        }

    # === 动态获取模型，绝不硬编码 ===
    if model is None:
        scene_cfg = ai_config.get_config(AIScene.SUMMARY)
        model = scene_cfg.model_name
        logger.debug(f"[LLMCompressor] 使用 SUMMARY 场景模型: {model}")

    prompt = _build_compression_prompt(messages)

    try:
        response = await call_thinker_async(
            messages=[{"role": "user", "content": prompt}],
            scene=AIScene.SUMMARY,
            model=model,
        )
    except Exception as e:
        logger.error(f"[LLMCompressor] LLM 调用失败: {e}")
        raise

    return _parse_compression_json(response)
