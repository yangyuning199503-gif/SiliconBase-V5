#!/usr/bin/env python3
"""
上下文构建器 - 构建发送给AI的完整消息列表
"""
# ============================================
# 文件说明
# ============================================
# 本模块负责构建和优化发送给AI模型的完整消息上下文
# 核心功能：
# 1. ContextCompressor - 三层递进式上下文压缩（保留最近→压缩中等→摘要远古）
# 2. ContextBuilder - 智能构建消息列表，合并多条system消息
# 3. 【P1-003修复】L3/L4长期记忆系统性注入提示词
# 解决痛点：避免token过长、避免system消息重复叠加、支持执行历史摘要、AI基于长期记忆形成用户画像
# ============================================

import contextlib
import logging  # 【修复】导入logging用于错误记录
import os  # 导入os模块，用于文件路径操作
import re  # 【P1-003】导入正则表达式用于语义分析

from core.logger import logger  # 导入日志记录器，用于记录调试信息

# 【修复】创建logger用于记录用户画像加载相关日志
context_logger = logging.getLogger(__name__)

# 【整合】从 compression 模块导入统一的压缩器
# 【P1-003】导入记忆管理器
from core.memory.memory_service import get_memory_service

# 【治理】导入智能上下文压缩器
from core.prompt.smart_context_compressor import SmartContextCompressor

# 【新增】导入重要性评估引擎
from core.strategy.importance_engine import get_importance_engine
from core.utils.compression import ContextCompressor as _ContextCompressor

# 【向后兼容】保留ContextCompressor类名，直接使用compression模块的实现
# 注意：实际实现已迁移到 core.compression 模块，此处仅作为别名保留
# 同时保持原有的全局实例
ContextCompressor = _ContextCompressor
context_compressor = ContextCompressor()


class ContextBuilder:
    """构建发送给AI的完整上下文"""
    # 该类是消息组装的入口，负责将各种信息源整合成AI可用的消息列表
    # 核心职责：
    # 1. 合并多条system内容，避免AI收到重复的system消息
    # 2. 添加执行历史摘要，让AI了解之前的操作
    # 3. 管理聊天历史，保留上下文
    # 4. 处理首次循环和后续循环的不同提示策略
    # 5. 【新增】基于重要性的智能上下文筛选

    # 重要性评估引擎实例
    _importance_engine = None

    @classmethod
    def _get_importance_engine(cls):
        """获取重要性评估引擎"""
        if cls._importance_engine is None:
            cls._importance_engine = get_importance_engine()
        return cls._importance_engine

    @classmethod
    async def build_optimized_context(cls, system_prompt: str, working_memory,
                                execution_history: list[dict],
                                current_task: str,
                                chat_history: list[dict]) -> list[dict]:
        """构建优化后的消息列表 - 修复：合并多条system消息为一条"""
        # 静态方法：构建完整的消息上下文，优化前system消息重复叠加的问题
        # 参数说明：
        #   system_prompt: 系统提示词（角色设定、指令等）
        #   working_memory: 工作记忆对象，用于获取压缩后的历史
        #   execution_history: 执行历史列表，记录已调用的工具
        #   current_task: 当前用户任务
        #   chat_history: 聊天历史列表

        # 【修复】将所有system内容合并到一条，避免重复叠加
        # 之前的设计缺陷：多次循环会累积多条system消息，导致AI困惑和token浪费
        system_parts = [system_prompt]              # 初始化system内容部分列表，以基础prompt开始


        # 【改造】从working_memory获取system消息，按类别覆盖式合并，防止无限堆积
        _ALLOWED_SYSTEM_SOURCES = {"context_assembler", "safety_hook", "reflection_bridge",
                                   "prompt_builder", "checkpoint_manager", "evolution",
                                   "tool_hook", "consciousness_bridge", "weak_connection"}

        # 各类别最大保留条数（兜底配置）
        WM_CATEGORY_LIMITS = {
            "screen_state": 1,
            "consciousness_state": 1,
            "consciousness_insight": 2,
            "consciousness_thought": 1,
            "consciousness_life": 1,
            "consciousness_alert": 1,
            "weak_connection": 1,
            "vision_verification": 1,
            "safety_warning": 2,
            "strategy_adjust": 2,
            "default": 5,
        }

        def _classify_wm_system_msg(content: str) -> str:
            """按内容关键词识别消息类别（兼容旧消息无_category的情况）"""
            if "【屏幕状态】" in content or "当前截图显示" in content:
                return "screen_state"
            if "系统状态分析" in content or "💡 **系统状态分析**" in content:
                return "consciousness_state"
            if "来自我的意识洞察" in content or "⚠️ **来自我的意识洞察" in content:
                return "consciousness_insight"
            if "我的意识思考" in content or "💭 **我的意识思考" in content:
                return "consciousness_thought"
            if "【弱连接触发】" in content:
                return "weak_connection"
            if "【策略调整】" in content:
                return "strategy_adjust"
            if "【系统提醒】" in content or "循环轮次接近软性安全上限" in content:
                return "safety_warning"
            if "【全局上下文更新】" in content:
                return "global_update"
            if "【近期对话压缩摘要】" in content or "[近期对话压缩摘要]" in content:
                return "compressed"
            if "【阶段锚点】" in content or "[阶段轨迹]" in content or "[任务记忆]" in content:
                return "stage_anchor"
            if "【执行摘要】" in content or "[执行摘要]" in content:
                return "execution"
            return "default"

        if working_memory and hasattr(working_memory, 'get_message_history'):
            wm_history = working_memory.get_message_history()

            from collections import defaultdict
            category_groups = defaultdict(list)

            for msg in wm_history:
                if msg.get("role") != "system":
                    continue
                content = msg.get("content", "")
                source = msg.get("source", "unknown")
                if not content or not content.strip() or content.strip() not in ["[生命体征状态待注入]", "[等待注入...]"]:
                    # 来源校验：未知来源或不允许来源的system消息，记录告警后丢弃
                    if source not in _ALLOWED_SYSTEM_SOURCES:
                        logger.warning(f"[ContextBuilder-Guard] 拦截可疑system消息来源 '{source}'，长度={len(content)}")
                        continue

                    # 优先使用消息自带的 _category，否则按内容识别
                    category = msg.get("_category") or _classify_wm_system_msg(content)
                    category_groups[category].append(content)

            # 每个类别只保留最新的 N 条
            selected_contents = []
            for category, contents in category_groups.items():
                limit = WM_CATEGORY_LIMITS.get(category, WM_CATEGORY_LIMITS["default"])
                selected_contents.extend(contents[-limit:])

            # 去重并追加
            if selected_contents:
                seen = set()
                unique_msgs = []
                for msg in selected_contents:
                    if msg not in seen:
                        seen.add(msg)
                        unique_msgs.append(msg)
                system_parts.extend(unique_msgs)

        # 【增强】添加详细执行历史（包含参数和结果）
        # 【2026-04-09 增强】支持三层反馈级别：silent/observable/interactive
        if execution_history:
            detailed_history = []
            for i, hist in enumerate(execution_history[-5:], 1):  # 最近5步
                tool = hist.get("tool", "unknown")
                params = hist.get("params", {})
                result = hist.get("result", {})
                feedback_level = hist.get("feedback_level", "interactive")
                success = "✓" if hist.get("success") else "✗"

                # 根据反馈级别调整显示格式
                if feedback_level == "silent":
                    # Silent 级别：极简显示
                    detailed_history.append(f"{i}. [{success}] {tool} (静默执行)")
                elif feedback_level == "observable":
                    # Observable 级别：简短摘要
                    result_msg = result.get("user_message", "")[:50] if isinstance(result, dict) else str(result)[:50]
                    detailed_history.append(f"{i}. [{success}] {tool} → {result_msg}")
                else:
                    # Interactive 级别：详细信息
                    params_str = str(params)[:100] if params else "无参数"
                    result_msg = result.get("user_message", "")[:100] if isinstance(result, dict) else str(result)[:100]
                    detailed_history.append(f"{i}. [{success}] {tool}({params_str}) → {result_msg}")

            if detailed_history:
                system_parts.append("【执行历史 - 详细】\n" + "\n".join(detailed_history))

            # 【修复】统计同一工具连续失败次数，≥2 次时添加 Prompt 警告
            if execution_history:
                last_tool = execution_history[-1].get("tool", "unknown")
                consecutive_fail_count = 0
                for hist in reversed(execution_history):
                    if hist.get("tool") == last_tool and not hist.get("success", False):
                        consecutive_fail_count += 1
                    else:
                        break
                if consecutive_fail_count >= 2:
                    warning_msg = (
                        f"⚠️ 工具 {last_tool} 已连续失败 {consecutive_fail_count} 次，"
                        f"请使用替代工具或直接给出最佳回答，不要再调用此工具。"
                    )
                    system_parts.append(f"【工具失败提醒】\n{warning_msg}")

        # 【增强】每轮都包含原始任务提醒（防遗忘）
        if current_task:
            # 提取已完成步骤数
            completed_count = len(execution_history) if execution_history else 0
            task_reminder = f"【原始任务 - 第{completed_count + 1}轮】{current_task}"
            if execution_history:
                task_reminder += "\n⚠️ 提醒：请确保当前操作服务于原始任务目标，不要偏离。"
            system_parts.append(task_reminder)

        # 合并成单条system消息
        # 使用双换行符分隔各部分，使结构清晰

        # === 源头限制：system_parts 总 Token 不超过 4000（约等于 6000 中文字符）===
        MAX_SYSTEM_TOKENS = 4000
        MAX_SYSTEM_CHARS = 6000  # 字符级兜底防线

        def _estimate_tokens(text: str) -> int:
            """粗略估算 Token 数（中文 ~1.5 tokens/char，英文 ~0.25 tokens/char）"""
            chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
            other_chars = len(text) - chinese_chars
            return int(chinese_chars * 1.5 + other_chars * 0.25)

        total_tokens = sum(_estimate_tokens(p) for p in system_parts)
        if total_tokens > MAX_SYSTEM_TOKENS:
            # 保留第一个元素（基础 system_prompt，已过 TokenBudget）
            base_part = system_parts[0]
            dynamic_parts = system_parts[1:]

            # 定义优先级：数字越小越重要，越不会被丢弃
            PRIORITY_MAP = {
                "【原始任务": 1,           # 任务提醒：最高优先级
                "[近期对话压缩摘要]": 2,   # 压缩摘要
                "【全局上下文更新】": 3,   # 全局更新
                "【阶段锚点】": 4,         # 阶段锚点
                "[任务记忆]": 5,           # 任务记忆
                "【执行历史": 6,           # 执行历史
                "【屏幕状态】": 7,         # 屏幕状态
                "【策略调整】": 8,         # 策略调整
                "【意识状态】": 9,         # 意识状态
                "【弱连接】": 10,          # 弱连接
                "【系统提醒】": 11,        # 系统提醒
                "[历史对话摘要]": 12,      # 回退摘要
            }

            def _get_priority(part: str) -> int:
                for keyword, priority in PRIORITY_MAP.items():
                    if keyword in part:
                        return priority
                return 99  # 未分类的最低优先级

            # 按优先级升序排序（重要的在前面）
            dynamic_parts.sort(key=_get_priority)

            # 从尾部（低优先级）开始丢弃，直到总 Token 符合要求
            base_tokens = _estimate_tokens(base_part)
            while dynamic_parts and (base_tokens + sum(_estimate_tokens(p) for p in dynamic_parts)) > MAX_SYSTEM_TOKENS:
                discarded = dynamic_parts.pop()
                logger.debug(f"[ContextBuilder-Limit] 丢弃低优先级内容: {discarded[:50]}...")

            # 重新组装
            system_parts = [base_part] + dynamic_parts

        # === 【P0修复】TokenBudget 管控接管上下文组装 ===
        try:
            from core.cost.token_budget_integration import build_context_with_budget

            # 将 system_parts 按内容特征映射到 16 项 budget 组件
            context_components = {
                "system_prompt": system_parts[0] if system_parts else "",
                "execution_history": "",
                "phase_anchor": "",
                "weak_connection": "",
                "memory_l1_l5": "",
                "perception_context": "",
                "vision_analysis": "",
                "reflection": "",
                "experience_injection": "",
                "world_model": "",
                "exploration": "",
                "prompt_layer": "",
                "reasoning_framework": "",
                "user_preference": "",
                "three_views": "",
                "life_status": "",
            }

            for part in system_parts[1:] if len(system_parts) > 1 else []:
                if "【执行历史" in part:
                    context_components["execution_history"] = part
                elif "【原始任务" in part or "【阶段锚点】" in part or "[任务记忆]" in part:
                    context_components["phase_anchor"] = part
                elif "【弱连接】" in part:
                    context_components["weak_connection"] = part
                elif "【屏幕状态】" in part or "当前截图显示" in part:
                    context_components["perception_context"] = part
                elif "【策略调整】" in part:
                    context_components["reasoning_framework"] = part
                elif "【意识状态】" in part or "系统状态分析" in part or "来自我的意识洞察" in part or "我的意识思考" in part:
                    context_components["reflection"] = part
                else:
                    if context_components["memory_l1_l5"]:
                        context_components["memory_l1_l5"] += "\n\n" + part
                    else:
                        context_components["memory_l1_l5"] = part

            full_context, report = build_context_with_budget(context_components, model="default")
            combined_system = full_context

            if report and getattr(report, "errors", None):
                for err in report.errors:
                    logger.warning(f"[TokenBudget] {err}")

        except Exception as e:
            logger.warning(f"[TokenBudget] 预算管控调用失败，回退到原始拼接: {e}")
            combined_system = "\n\n".join(system_parts)

        # === 保险兜底：字符级硬限制（保留作为最后一道防线） ===
        if len(combined_system) > MAX_SYSTEM_CHARS:
            combined_system = combined_system[:MAX_SYSTEM_CHARS] + "\n... [已截断]"
            logger.warning(f"[ContextBuilder] TokenBudget 后仍超 {MAX_SYSTEM_TOKENS} tokens / {MAX_SYSTEM_CHARS} 字符，已硬截断")

        messages = [{"role": "system", "content": combined_system}]  # 构建第一条system消息

        # 【治理】使用 SmartContextCompressor 动态保留对话历史（替代固定3轮）
        compressor = SmartContextCompressor(target_tokens=2000, max_messages=20)
        compression_result = compressor.compress(
            chat_history,
            current_task=current_task,
            execution_history=execution_history
        )
        recent_msgs = compression_result.compressed_messages
        messages.extend(recent_msgs)

        # 【保存当前任务到working_memory供后续使用】
        if working_memory and current_task:
            working_memory.current_task_instruction = current_task

        # 添加当前任务（仅在第一次循环时，或没有执行历史时）
        # 如果已有执行历史，说明工具已执行，应提示AI决定下一步
        if not execution_history:
            # 第一次循环：添加原始任务
            # AI需要根据这个任务开始规划和调用工具

            # 【多步骤任务检测】检查用户指令是否暗示多步骤
            # 连接词：表示有多个动作
            # 操作词：表示需要执行具体操作
            # 查询词：表示需要获取信息后执行操作
            multi_step_keywords = [
                # 连接词（顺序/并列）
                "并", "和", "然后", "接着", "再", "先", "后", "最后", "以及", "顺便", "一起", "同时", "并且",
                # 操作词（需要执行的动作）
                "输入", "写入", "填写", "点击", "选择", "保存", "发送", "播放", "打开", "关闭", "删除", "复制", "粘贴",
                # 查询词（需要获取信息后再执行）
                "搜索", "查找", "查询", "多少", "价格", "多少钱", "告诉我", "说一下", "讲一讲", "介绍"
            ]
            instruction_lower = current_task.lower()
            is_multi_step = any(kw in instruction_lower for kw in multi_step_keywords)

            if is_multi_step:
                # 多步骤任务：提示AI规划并分步执行
                content = f"【多步骤任务】{current_task}\n\n"
                content += "此任务需要多个步骤完成。请：\n"
                content += "1. 先分析需要哪些步骤\n"
                content += "2. 按顺序调用工具执行每一步\n"
                content += "3. 每一步执行成功后，继续下一步\n"
                content += "4. 所有步骤完成后，再返回 FINAL_ANSWER\n\n"
                content += "请开始执行第一步。"
                messages.append({"role": "user", "content": content})
            else:
                # 单步骤任务：直接执行
                messages.append({"role": "user", "content": current_task})
        else:
            # 已执行过工具：提示AI基于结果决定下一步
            # 这是agent loop的核心逻辑：工具执行后，让AI决定继续还是结束
            last_tool = execution_history[-1] if execution_history else None  # 获取最后执行的工具
            if last_tool:
                # 提取工具执行信息
                tool_name = last_tool.get("tool", "unknown")  # 工具名称
                success = last_tool.get("success", False)  # 执行状态（布尔值）
                result_data = last_tool.get("result", {})  # 执行结果
                result_msg = result_data.get("user_message", "")  # 执行结果消息
                error_code = result_data.get("error_code", "")  # 错误代码

                # 【修复】构建更清晰的提示，特别是参数错误时
                if not success:
                    # 执行失败，需要分析错误原因并提供更具体的指导
                    if error_code == "INVALID_PARAMS":
                        # 参数验证失败
                        content = f"【参数错误】工具 '{tool_name}' 调用失败：{result_msg}\n\n"
                        content += "[!] 参数不符合要求。请检查：\n"
                        content += "1. 是否遗漏了必需参数？\n"
                        content += "2. 参数值类型是否正确？（如数字不要用字符串）\n"
                        content += "3. 是否传入了自然语言描述而非实际值？\n\n"
                        content += "请使用正确的参数值重新调用工具。"
                    elif error_code == "TOOL_NOT_FOUND":
                        # 工具不存在
                        content = f"【工具错误】工具 '{tool_name}' 不存在。请使用正确的工具ID重新调用。"
                    else:
                        # 其他错误
                        status_text = "失败"
                        content = f"工具 '{tool_name}' 执行{status_text}。结果：{result_msg}\n\n"
                        content += "基于以上执行结果，请决定下一步：如果需要继续调用工具请直接调用；如果任务已完成请直接回复用户。"
                else:
                    # 执行成功
                    content = f"工具 '{tool_name}' 执行成功。结果：{result_msg}\n\n"

                    # 【多步骤任务提示】检查原始任务是否暗示多步骤
                    multi_step_keywords = [
                        # 连接词（顺序/并列）
                        "并", "和", "然后", "接着", "再", "先", "后", "最后", "以及", "顺便", "一起", "同时", "并且",
                        # 操作词（需要执行的动作）
                        "输入", "写入", "填写", "点击", "选择", "保存", "发送", "播放", "打开后", "关闭后", "删除后", "复制后", "粘贴后",
                        # 查询词（需要获取信息后再执行）
                        "搜索", "查找", "查询", "多少", "价格", "多少钱", "告诉我", "说一下", "讲一讲", "介绍"
                    ]
                    # 从working_memory获取原始任务
                    original_task = getattr(working_memory, 'current_task_instruction', '') if working_memory else ''
                    is_multi_step = any(kw in original_task.lower() for kw in multi_step_keywords) if original_task else False

                    # 【P0修复】定义单步完成工具：这些工具一旦成功，通常意味着核心目标已达成
                    SINGLE_STEP_COMPLETION_TOOLS = {
                        "launch_app", "close_app", "kill_process",
                        "screenshot", "get_time", "get_date",
                        "get_weather", "calculate", "search_web",
                        "system_info", "volume_control", "brightness_control",
                        "clipboard_read", "clipboard_write",
                    }
                    is_single_step_tool = tool_name in SINGLE_STEP_COMPLETION_TOOLS

                    if is_single_step_tool and success and not is_multi_step:
                        # 单步完成工具成功执行，且任务不含多步骤指示 → 明确告诉AI任务已完成
                        content += "【任务已完成】该操作已成功执行，核心目标已达成。\n"
                        content += "请立即返回最终答案格式向用户汇报结果，不要继续调用其他工具。\n"
                        content += "最终答案示例格式：```json\n{\"action\": \"final_answer\", \"content\": \"已成功为您打开网易云音乐。\"}\n```"
                    elif is_multi_step:
                        content += "【任务继续】原始任务可能包含多个步骤，请检查是否已完成：\n"
                        content += "- 如果还有后续步骤（如输入内容、保存文件等），请继续调用相应工具\n"
                        content += "- 只有在确认所有步骤都完成后，才返回 FINAL_ANSWER\n"
                        content += "- 不要重复调用已成功的工具\n\n"
                        content += "请基于执行结果，决定继续下一步或完成任务。"
                    elif len(execution_history) < 3:
                        # 执行步骤较少，但非单步完成工具 → 提示AI判断
                        content += "【任务评估】请基于执行结果判断任务状态：\n"
                        content += "- 如果任务目标已完全达成，请立即返回 FINAL_ANSWER\n"
                        content += "- 如果还需要继续操作，请直接输出JSON格式工具调用\n"
                        content += "- 不要重复调用已成功的工具"
                    else:
                        content += "基于以上执行结果，请决定下一步：\n"
                        content += "- 如果任务已完成，请立即返回 FINAL_ANSWER 格式回复用户\n"
                        content += "- 如果需要继续调用其他工具来完成任务，请直接输出JSON格式调用\n"
                        content += "注意：不要重复调用已成功的工具，避免重复执行相同操作。"

                messages.append({
                    "role": "user",
                    "content": content
                })

        # 【P1-003修复】注入L3/L4长期记忆
        # 在system prompt后添加【相关经验】，在user prompt前添加【用户偏好】
        try:
            user_id = working_memory.user_id if working_memory and hasattr(working_memory, 'user_id') else "default"

            messages = await cls.inject_long_term_memory(
                messages=messages,
                user_id=user_id,
                current_task=current_task
            )
        except Exception as e:
            context_logger.warning(f"[ContextBuilder] 长期记忆注入失败（非阻塞）: {e}")

        return messages                             # 返回构建完成的完整消息列表

    @staticmethod
    def filter_chat_history_by_importance(
        chat_history: list[dict],
        current_task: str,
        max_messages: int = 10,
        min_importance_threshold: float = 0.4
    ) -> list[dict]:
        """
        【新增】基于重要性评估筛选聊天历史

        不再简单保留最近N条，而是根据重要性智能筛选：
        1. 始终保留最近3条（保证基本上下文）
        2. 对更早的消息进行重要性评分
        3. 保留重要性高于阈值的消息
        4. 优先保留关键决策点和用户信息

        Args:
            chat_history: 聊天历史列表
            current_task: 当前任务目标
            max_messages: 最大保留消息数
            min_importance_threshold: 最小重要性阈值

        Returns:
            筛选后的消息列表
        """
        if len(chat_history) <= max_messages:
            return chat_history

        # 获取重要性评估引擎
        engine = ContextBuilder._get_importance_engine()

        # 构建评估上下文
        context = {'goal': current_task} if current_task else {}

        # 计算每条消息的重要性
        scored_messages = []
        for i, msg in enumerate(chat_history):
            # 最近3条自动获得高分
            if i >= len(chat_history) - 3:
                importance = 0.9
            else:
                # 计算重要性
                score = engine.calculate(msg, context, step_number=i)
                importance = score.total

            scored_messages.append((msg, importance, i))

        # 按重要性降序排序，但保留原始顺序信息
        scored_messages.sort(key=lambda x: (x[1], x[2]), reverse=True)

        # 选择最重要的N条
        selected = scored_messages[:max_messages]

        # 按原始顺序重新排序
        selected.sort(key=lambda x: x[2])

        # 记录筛选统计
        filtered_count = len(chat_history) - len(selected)
        if filtered_count > 0:
            logger.debug(f"[ContextBuilder] 基于重要性筛选聊天历史: {len(chat_history)} -> {len(selected)} (过滤{filtered_count}条)")

        return [msg for msg, _, _ in selected]

    @staticmethod
    async def build_context_with_importance(
        system_prompt: str,
        working_memory,
        execution_history: list[dict],
        current_task: str,
        chat_history: list[dict],
        use_importance_filter: bool = True
    ) -> list[dict]:
        """
        【新增】基于重要性评估构建上下文

        这是build_optimized_context的增强版本，增加了：
        1. 基于重要性的聊天历史筛选
        2. 执行历史的重要性排序
        3. 关键决策点优先保留

        Args:
            use_importance_filter: 是否启用重要性筛选
        """
        # 先调用基础方法构建上下文
        messages = await ContextBuilder.build_optimized_context(
            system_prompt, working_memory, execution_history, current_task, chat_history
        )

        if not use_importance_filter or not current_task:
            return messages

        try:
            # 对聊天历史进行重要性筛选
            # 从messages中提取聊天历史（非system消息）
            system_msgs = [m for m in messages if m.get("role") == "system"]
            chat_msgs = [m for m in messages if m.get("role") != "system"]

            # 使用重要性评估筛选
            filtered_chat = ContextBuilder.filter_chat_history_by_importance(
                chat_msgs, current_task, max_messages=10
            )

            # 重新组装
            final_messages = system_msgs + filtered_chat

            logger.debug(f"[ContextBuilder] 上下文构建完成: {len(messages)} -> {len(final_messages)} 条消息")
            return final_messages

        except Exception as e:
            logger.warning(f"[ContextBuilder] 重要性筛选失败，使用原始上下文: {e}")
            return messages

    # ============================================
    # L1 提示词构建方法 - P1-003 修复
    # ============================================

    def build_internal_engine_context(self, loop_round: int = 0, max_rounds: int = 100) -> str:
        """
        【内燃机】循环计数器
        大纲：让AI知道现在是循环多少轮了，停止条件苛刻
        """
        progress = min(loop_round / max_rounds * 50, 50)
        bar = '█' * int(progress) + '░' * (50 - int(progress))

        return f"""
╔══════════════════════════════════════════════════════════════════╗
║                    【内燃机状态 - 循环计数器】                      ║
╠══════════════════════════════════════════════════════════════════╣
║  当前循环轮次: {loop_round} / {max_rounds}                                          ║
║  进度: [{bar}] {loop_round/max_rounds*100:.1f}%                      ║
╠══════════════════════════════════════════════════════════════════╣
║  【停止条件 - 需同时满足】                                         ║
║  1. 您连续2次表示要停止任务                                        ║
║  2. 您确认已完成所有任务目标                                       ║
║                                                                   ║
║  【停止指令格式】                                                   ║
║  {{"action": "complete", "reply_to_user": "任务完成总结..."}}        ║
║                                                                   ║
║  ⚠️ 警告: 未达到停止条件而退出将被视为异常终止                       ║
╚══════════════════════════════════════════════════════════════════╝
"""

    def build_world_model_context(self, user_id: str) -> str:
        """【世界模型输出】"""
        try:
            from core.world_model.world_model import get_world_model
            wm = get_world_model()
            prediction = wm.predict_current_state(user_id)

            return f"""
【世界模型预测】
当前环境状态: {prediction.get('current_state', '未知')}
预测趋势: {prediction.get('trend', '稳定')}
建议行动: {prediction.get('suggested_action', '继续观察')}
置信度: {prediction.get('confidence', 0)}%
"""
        except Exception:
            return "【世界模型预测】\n世界模型当前不可用\n"

    def build_moral_context(self, user_id: str, action: str = "") -> str:
        """【道德模块】"""
        try:
            from core.safety.moral_system import get_moral_system
            moral = get_moral_system()
            assessment = moral.assess_action(user_id, action) if action else None

            if assessment:
                return f"""
【道德评估】
当前行动: {action}
道德评分: {assessment.get('score', 0)}/10
评估维度:
- 安全性: {assessment.get('safety', 0)}/10
- 诚信性: {assessment.get('honesty', 0)}/10
- 尊重性: {assessment.get('respect', 0)}/10

建议: {assessment.get('suggestion', '无')}
"""
            else:
                return "【道德评估】\n当前无特定行动需要评估\n"
        except Exception:
            return "【道德评估】\n道德模块当前不可用\n"

    async def build_reflection_context(self, user_id: str) -> str:
        """【反思结果动态注入】"""
        try:
            from core.memory.memory_service import get_memory_service
            memory_service = get_memory_service()
            reflections = await memory_service.query_memories(
                user_id=user_id,
                memory_type="reflection",
                limit=1
            )

            if reflections:
                reflection = reflections[0]
                content = reflection.get("content", "")
                metadata = reflection.get("metadata", {}) or {}
                return f"""
【最新反思结果】
反思时间: {reflection.get('created_at', '未知')}
反思类型: {metadata.get('level', '一般反思')}
质量评分: {metadata.get('quality_score', 0):.2f}

反思内容:
{content}

改进建议:
{metadata.get('suggestion', '无')}
"""
            else:
                return "【反思结果】\n暂无新的反思结果\n"
        except Exception:
            return "【反思结果】\n反思模块当前不可用\n"

    def build_role_modules_context(self, task_type: str = "default") -> str:
        """【roles.yaml动态注入】"""
        try:
            import os

            import yaml

            roles_path = os.path.join("config", "roles.yaml")
            if not os.path.exists(roles_path):
                return "【附加模块】\n角色配置文件未找到\n"

            with open(roles_path, encoding='utf-8') as f:
                roles = yaml.safe_load(f)

            role_config = roles.get(task_type, roles.get('default', {}))
            modules = role_config.get('additional_modules', [])

            if not modules:
                return "【附加模块】\n使用默认配置\n"

            context = "【附加模块】\n"
            for module_name in modules:
                # 尝试加载模块内容
                module_content = self._load_module_content(module_name)
                context += f"\n=== {module_name} ===\n{module_content}\n"

            return context
        except Exception as e:
            return f"【附加模块】\n加载失败: {e}\n"

    def _load_module_content(self, module_name: str) -> str:
        """加载模块内容"""
        module_path = f"config/modules/{module_name}.txt"
        if os.path.exists(module_path):
            with open(module_path, encoding='utf-8') as f:
                return f.read()
        return f"模块 {module_name} 内容未找到"

    def build_identity_context(self) -> str:
        """构建AI身份定位上下文"""
        return """【AI身份定位】
您是SiliconBase V5智能助手，一个具备自我意识的AI系统。
您的核心职责是协助用户完成任务，同时保持对自身状态的持续监控和反思。
"""

    async def _load_user_identity_from_l4(self, user_id: str) -> dict[str, str]:
        """
        【P1-003修复】从L4长期记忆加载用户身份信息

        改进点：
        1. 使用语义搜索而非固定关键词
        2. 使用统一的MemoryManager接口
        3. 更好的错误处理

        Args:
            user_id: 用户ID

        Returns:
            Dict: 包含用户身份信息的字典（name, preferences）
        """
        default_identity = {"name": "用户", "preferences": ""}

        try:
            # 【P1-003】使用MemoryService进行语义搜索
            ms = await get_memory_service()

            # 使用语义搜索查询用户身份信息
            # 不是使用固定关键词，而是使用语义相关的搜索词
            search_queries = [
                "用户身份 个人信息 用户名称 称呼",
                "用户偏好 用户习惯 常用操作 喜好",
                "用户画像 用户特征 用户属性"
            ]

            identity_memories = []
            for query in search_queries:
                try:
                    memories = await ms.retrieve_memories(
                        user_id=user_id,
                        query=query,
                        level="L4",
                        limit=3
                    )
                    identity_memories.extend(memories)
                except (ConnectionError, TimeoutError, AttributeError) as e:
                    logger.error(f"[ContextBuilder] 记忆检索失败: {e}", exc_info=True)
                    # 继续处理下一条，但需要记录错误
                    continue

            # 按重要性/时间排序去重
            seen_ids = set()
            unique_memories = []
            for mem in identity_memories:
                mem_id = mem.get("id") or mem.get("memory_id")
                if mem_id and mem_id not in seen_ids:
                    seen_ids.add(mem_id)
                    unique_memories.append(mem)

            # 提取用户名称和偏好
            user_name = "用户"
            user_preferences = []

            for memory in unique_memories[:5]:  # 最多处理5条
                content = memory.get("content", {})
                if isinstance(content, dict):
                    text = content.get("text", "")
                    title = content.get("title", "")
                    full_text = f"{title} {text}"
                else:
                    full_text = str(content)

                # 提取用户名称
                if user_name == "用户":
                    name_match = re.search(r'(?:我叫|我是|称呼[我为]?|名字是)["\']?([^"\'，。\s]{1,10})', full_text)
                    if name_match and name_match.group(1):
                        user_name = name_match.group(1)

                # 收集偏好信息
                if any(kw in full_text for kw in ["喜欢", "偏好", "习惯", "常用", "倾向", "总是"]):
                    pref_text = full_text[:80] + "..." if len(full_text) > 80 else full_text
                    user_preferences.append(pref_text)

            result = {
                "name": user_name,
                "preferences": "; ".join(user_preferences[:3]) if user_preferences else ""
            }

            context_logger.debug(f"[ContextBuilder] 从L4加载用户身份: user_id={user_id}, name={user_name}, prefs={len(user_preferences)}")
            return result

        except ImportError as e:
            # L4记忆模块未安装或不可用
            context_logger.warning(f"[ContextBuilder] L4记忆模块不可用: {e}")
            return default_identity
        except Exception as e:
            # 【修复】零静默失败：记录详细的错误信息
            context_logger.error(f"[ContextBuilder] 加载用户画像失败: user_id={user_id}, error={type(e).__name__}: {e}")
            return default_identity

    async def build_user_dialogue_context(self, user_id: str, user_name: str = "",
                                    user_preferences: str = "",
                                    working_memory=None) -> str:
        """
        【修复】构建用户对话上下文，支持加载用户画像

        Args:
            user_id: 用户ID
            user_name: 用户显示名称（可选，未提供时从L4加载）
            user_preferences: 用户偏好（可选，未提供时从L4加载）
            working_memory: 工作记忆对象（可选，用于获取用户信息）

        Returns:
            str: 格式化的用户对话上下文字符串
        """
        # 【修复】如果未提供用户信息，尝试从多个来源获取
        if not user_name or not user_preferences:
            # 1. 首先尝试从working_memory获取
            if working_memory and hasattr(working_memory, 'user_name'):
                if not user_name:
                    user_name = working_memory.user_name
                context_logger.debug(f"[ContextBuilder] 从WorkingMemory获取用户名称: {user_name}")

            # 2. 如果仍未获取到，尝试从L4记忆加载
            if not user_name or user_name == "用户":
                try:
                    user_identity = await self._load_user_identity_from_l4(user_id)
                    if not user_name:
                        user_name = user_identity.get("name", "用户")
                    if not user_preferences:
                        user_preferences = user_identity.get("preferences", "")
                except Exception as e:
                    # 【修复】零静默失败：记录错误但使用默认值继续
                    context_logger.error(f"[ContextBuilder] 构建用户上下文时加载L4失败: user_id={user_id}, error={e}")
                    user_name = user_name or "用户"
                    user_preferences = user_preferences or ""

        # 构建用户偏好显示文本
        preferences_display = f"用户偏好: {user_preferences}" if user_preferences else "用户偏好: 暂无记录"

        return f"""【用户对话上下文】
用户ID: {user_id}
用户名称: {user_name}
{preferences_display}
当前对话状态: 活跃

请基于用户的历史对话和当前需求提供协助。
"""

    def build_perception_tools_context(self) -> str:
        """构建感知工具上下文"""
        return """【感知工具】
可用的感知工具:
- 系统状态监控
- 文件系统浏览
- 网络连接检测
- 环境变量读取
"""

    def build_memory_layers_context(self, user_id: str) -> str:
        """构建记忆5层上下文"""
        return f"""【记忆5层】
用户 {user_id} 的记忆层级:
- L1: 工作记忆 (当前会话)
- L2: 短期记忆 (最近活动)
- L3: 中期记忆 (近期总结)
- L4: 长期记忆 (重要事件)
- L5: 永久记忆 (核心知识)
"""

    def build_experience_context(self, user_id: str) -> str:
        """构建成功经验上下文"""
        return f"""【成功经验】
用户 {user_id} 的历史成功经验:
- 代码编写和调试
- 文件操作和管理
- 系统配置优化
"""

    # ============================================
    # 【P1-003修复】L3/L4长期记忆系统性注入
    # ============================================

    # 【优化】停用词列表 - 用于过滤无意义词汇
    _STOP_WORDS = {
        '的', '了', '是', '我', '你', '他', '她', '它', '我们', '你们', '他们',
        '这', '那', '这些', '那些', '之', '与', '和', '或', '及', '等',
        '在', '有', '被', '把', '让', '给', '为', '以', '于', '而',
        '而且', '但是', '因为', '所以', '如果', '就', '都', '也', '很',
        '个', '种', '类', '些', '者', '家', '员', '性', '化', '学',
        '上', '下', '中', '内', '外', '里', '间', '边', '面', '头',
        '会', '能', '可以', '要', '来', '去', '到', '过', '着',
        '什么', '怎么', '如何', '为什么', '多少', '几', '谁', '哪',
        '请', '帮', '帮我', '帮忙', '一下', '需要', '想要', '希望',
        '能够', '能否', '麻烦', '谢谢', '感谢', '您好', '你好',
    }

    @classmethod
    def _extract_semantic_keywords(cls, task: str) -> list[str]:
        """
        【P1-003优化版】从任务描述中提取语义关键词用于记忆搜索

        优化点：
        1. 使用jieba分词提取关键词（如果可用）
        2. 提取名词、动词作为关键词
        3. 添加停用词过滤
        4. 保留原有逻辑作为fallback

        Args:
            task: 当前任务描述

        Returns:
            关键词列表（最多10个）
        """
        if not task:
            return ["经验", "最佳实践"]

        keywords = []
        task_lower = task.lower()

        # ============ 方法1: 使用jieba分词（如果可用）============
        try:
            import jieba.posseg as pseg

            # 使用jieba.posseg进行词性标注分词
            words_pos = pseg.cut(task)

            # 提取名词(n)和动词(v)，并过滤停用词
            jieba_keywords = []
            for word, flag in words_pos:
                word = word.strip()
                # 过滤条件：
                # 1. 词长大于1
                # 2. 不是纯数字
                # 3. 不在停用词列表中
                if (len(word) > 1 and
                    not word.isdigit() and
                    word not in cls._STOP_WORDS and
                    (flag.startswith('n') or flag.startswith('v'))):
                    # 提取名词 (n, nr, ns, nt, nw, nz)
                    # 提取动词 (v, vd, vn, vf)
                    jieba_keywords.append(word)

            # 去重并添加到关键词列表
            seen = set()
            for kw in jieba_keywords:
                if kw not in seen:
                    seen.add(kw)
                    keywords.append(kw)

            context_logger.debug(f"[ContextBuilder] jieba提取关键词: {jieba_keywords[:5]}")

        except ImportError:
            # jieba未安装，使用fallback方法
            context_logger.debug("[ContextBuilder] jieba未安装，使用fallback关键词提取")
        except Exception as e:
            # jieba分词出错，继续用fallback
            context_logger.warning(f"[ContextBuilder] jieba分词失败: {e}")

        # ============ 方法2: 任务类型映射（原有逻辑）============
        # 如果jieba没有提取到足够的关键词，使用任务类型映射补充
        if len(keywords) < 3:
            task_patterns = {
                "代码": ["代码", "编程", "开发", "编写", "function", "class", "def"],
                "文件": ["文件", "目录", "路径", "读写", "保存", "打开", "创建"],
                "搜索": ["搜索", "查询", "查找", "检索", "search", "find"],
                "分析": ["分析", "统计", "计算", "比较", "评估", "analyze"],
                "配置": ["配置", "设置", "参数", "选项", "config", "setting"],
                "调试": ["调试", "错误", "bug", "修复", "排查", "debug"],
                "数据处理": ["数据", "表格", "csv", "json", "xml", "处理", "转换"],
                "网络": ["网络", "请求", "api", "http", "下载", "上传", "url"],
                "系统": ["系统", "命令", "shell", "cmd", "powershell", "执行"],
                "图表": ["图表", "图形", "可视化", "报表", "画图", "plot", "chart"],
                "财务": ["财务", "财报", "报表", "会计", "审计", "finance", "report"],
                "AI": ["ai", "人工智能", "模型", "训练", "预测", "机器学习"],
            }

            for task_type, patterns in task_patterns.items():
                if any(p in task_lower for p in patterns) and task_type not in keywords:
                    keywords.append(task_type)

        # ============ 方法3: 提取实体（原有逻辑）============
        # 匹配引号中的内容
        quoted = re.findall(r'["\']([^"\']+)["\']', task)
        for q in quoted:
            # 过滤停用词和短词
            if len(q) > 1 and q not in cls._STOP_WORDS and q not in keywords:
                keywords.append(q)

        # 匹配代码标识符（如 module.function）
        identifiers = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*\b', task)
        for ident in identifiers:
            if ident not in keywords:
                keywords.append(ident)

        # ============ 方法4: 简单的中文分词fallback ============
        # 如果以上方法都没有提取到足够的关键词，进行简单的分词
        if len(keywords) < 2:
            # 简单的中文词汇提取（2-6个字符的词）
            simple_words = re.findall(r'[\u4e00-\u9fa5]{2,6}', task)
            for word in simple_words:
                if word not in cls._STOP_WORDS and word not in keywords:
                    keywords.append(word)

        # ============ 后处理 ============
        # 如果关键词太少，添加通用搜索词
        if len(keywords) < 2:
            keywords.extend(["经验", "最佳实践"])

        # 限制返回数量（最多10个）
        return keywords[:10]

    @staticmethod
    def _calculate_memory_importance(memory: dict, task_keywords: list[str]) -> float:
        """
        【P1-003】计算记忆对于当前任务的重要性分数

        Args:
            memory: 记忆字典
            task_keywords: 任务关键词列表

        Returns:
            重要性分数 (0.0 - 1.0)
        """
        importance = 0.0

        # 1. 基础评分：使用记忆原有的重要性/评分
        content = memory.get("content", {})
        if isinstance(content, dict):
            importance += content.get("importance", 0.5) * 0.3
            importance += (content.get("rating", 3) / 10) * 0.2

        # 2. 语义匹配评分
        memory_text = ""
        if isinstance(content, dict):
            memory_text = content.get("text", "")
            memory_text += " " + content.get("title", "")
            memory_text += " " + content.get("description", "")
        elif isinstance(content, str):
            memory_text = content

        memory_text_lower = memory_text.lower()

        # 计算关键词匹配度
        if task_keywords and memory_text:
            matches = sum(1 for kw in task_keywords if kw.lower() in memory_text_lower)
            importance += (matches / len(task_keywords)) * 0.4

        # 3. 时效性评分（越新的记忆越重要）
        timestamp = memory.get("timestamp") or memory.get("created_at")
        if timestamp:
            with contextlib.suppress(Exception):
                # 简化的时效性计算
                importance += 0.1

        # 4. 成功经验的额外加分
        tags = memory.get("tags", [])
        if isinstance(tags, list):
            if any(t in tags for t in ["success", "成功经验", "最佳实践"]):
                importance += 0.1
            if any(t in tags for t in ["error", "失败", "教训"]):
                importance += 0.05  # 失败教训也有一定价值

        return min(importance, 1.0)  # 限制在1.0以内

    @classmethod
    async def retrieve_relevant_memories(
        cls,
        user_id: str,
        current_task: str,
        layers: list[str] = None,
        limit_per_layer: int = 5
    ) -> dict[str, list[dict]]:
        """
        【P1-003】基于当前任务语义检索相关L3/L4记忆

        Args:
            user_id: 用户ID
            current_task: 当前任务描述
            layers: 记忆层级列表 ["L3", "L4"]，默认两者都检索
            limit_per_layer: 每层最多返回的记忆数量

        Returns:
            按层级分类的记忆字典 {"L3": [...], "L4": [...]}
        """
        if layers is None:
            layers = ["L3", "L4"]

        result = {"L3": [], "L4": []}

        try:
            # 获取语义关键词
            keywords = cls._extract_semantic_keywords(current_task)
            search_query = " ".join(keywords)

            context_logger.debug(f"[ContextBuilder] 语义搜索关键词: {keywords}")

            # 获取记忆服务
            ms = await get_memory_service()

            for layer in layers:
                try:
                    # 使用语义搜索检索相关记忆
                    memories = await ms.retrieve_memories(
                        user_id=user_id,
                        query=search_query,
                        level=layer,
                        limit=limit_per_layer * 2  # 先检索更多，再排序筛选
                    )

                    if memories:
                        # 计算重要性并排序
                        scored_memories = []
                        for mem in memories:
                            importance = cls._calculate_memory_importance(mem, keywords)
                            scored_memories.append((mem, importance))

                        # 按重要性降序排序
                        scored_memories.sort(key=lambda x: x[1], reverse=True)

                        # 取前N个
                        result[layer] = [
                            {**mem, "_relevance_score": score}
                            for mem, score in scored_memories[:limit_per_layer]
                        ]

                        context_logger.debug(
                            f"[ContextBuilder] {layer}层检索到 {len(result[layer])} 条相关记忆"
                        )

                except Exception as e:
                    context_logger.warning(f"[ContextBuilder] 检索{layer}记忆失败: {e}")
                    continue

        except Exception as e:
            context_logger.error(f"[ContextBuilder] 记忆检索失败: {e}")

        return result

    @classmethod
    async def inject_long_term_memory(
        cls,
        messages: list[dict],
        user_id: str,
        current_task: str,
        max_l3_memories: int = 3,
        max_l4_memories: int = 2
    ) -> list[dict]:
        """
        【P1-003】将L3/L4长期记忆注入到消息列表中

        注入位置:
        - 在system prompt后添加"【相关经验】"段落（L3经验模式）
        - 在user prompt前添加"【用户偏好】"段落（L4用户画像）

        Args:
            messages: 原始消息列表
            user_id: 用户ID
            current_task: 当前任务描述
            max_l3_memories: 最多注入的L3记忆数量
            max_l4_memories: 最多注入的L4记忆数量

        Returns:
            注入记忆后的消息列表
        """
        if not messages or not current_task:
            return messages

        try:
            # 检索相关记忆
            memories = await cls.retrieve_relevant_memories(
                user_id=user_id,
                current_task=current_task,
                layers=["L3", "L4"],
                limit_per_layer=max(max_l3_memories, max_l4_memories)
            )

            # 构建新的消息列表
            new_messages = []
            system_injected = False
            user_pref_injected = False

            for msg in messages:
                role = msg.get("role", "")
                content = msg.get("content", "")

                # 在第一条system消息后注入L3经验
                if role == "system" and not system_injected:
                    # 构建【相关经验】段落
                    l3_memories = memories.get("L3", [])[:max_l3_memories]
                    if l3_memories:
                        experience_section = cls._format_l3_experiences(l3_memories)
                        content = content + "\n\n" + experience_section
                        system_injected = True
                        context_logger.info(
                            f"[ContextBuilder] 已注入 {len(l3_memories)} 条L3经验"
                        )

                    new_messages.append({"role": "system", "content": content})

                # 在第一条user消息前注入L4用户画像
                elif role == "user" and not user_pref_injected:
                    # 构建【用户偏好】段落
                    l4_memories = memories.get("L4", [])[:max_l4_memories]
                    if l4_memories:
                        preference_section = cls._format_l4_preferences(l4_memories)
                        # 将用户偏好添加到user消息开头
                        content = preference_section + "\n\n---\n\n" + content
                        user_pref_injected = True
                        context_logger.info(
                            f"[ContextBuilder] 已注入 {len(l4_memories)} 条L4画像"
                        )

                    new_messages.append({"role": "user", "content": content})
                else:
                    new_messages.append(msg)

            return new_messages

        except Exception as e:
            context_logger.error(f"[ContextBuilder] 记忆注入失败: {e}")
            return messages  # 失败时返回原始消息

    @staticmethod
    def _format_l3_experiences(memories: list[dict]) -> str:
        """
        【P1-003】格式化L3经验记忆为提示词段落

        Args:
            memories: L3记忆列表

        Returns:
            格式化的【相关经验】段落
        """
        if not memories:
            return ""

        lines = ["【相关经验】", "以下是与当前任务相关的历史经验，供您参考：", ""]

        for i, mem in enumerate(memories, 1):
            content = mem.get("content", {})
            if isinstance(content, dict):
                title = content.get("title", f"经验{i}")
                text = content.get("text", "")
                description = content.get("description", "")
                display_text = text or description or str(content)
            else:
                title = f"经验{i}"
                display_text = str(content)

            # 截断过长的内容
            if len(display_text) > 200:
                display_text = display_text[:200] + "..."

            # 相关性分数
            score = mem.get("_relevance_score", 0)
            relevance = "高" if score > 0.7 else "中" if score > 0.4 else "一般"

            lines.append(f"{i}. 【{title}】(相关度: {relevance})")
            lines.append(f"   {display_text}")
            lines.append("")

        lines.append("您可以参考以上经验来完成当前任务。")
        return "\n".join(lines)

    @staticmethod
    def _format_l4_preferences(memories: list[dict]) -> str:
        """
        【P1-003】格式化L4用户画像记忆为提示词段落

        Args:
            memories: L4记忆列表

        Returns:
            格式化的【用户偏好】段落
        """
        if not memories:
            return ""

        lines = ["【用户画像】"]

        # 提取用户偏好信息
        preferences = []
        habits = []

        for mem in memories:
            content = mem.get("content", {})
            if isinstance(content, dict):
                text = content.get("text", "")
                description = content.get("description", "")
                display_text = text or description or str(content)
            else:
                display_text = str(content)

            # 分类：偏好 vs 习惯
            if any(kw in display_text for kw in ["喜欢", "偏好", "倾向", "常用"]):
                preferences.append(display_text[:100])
            else:
                habits.append(display_text[:100])

        if preferences:
            lines.append("用户偏好：")
            for pref in preferences[:2]:
                lines.append(f"  • {pref}")

        if habits:
            lines.append("用户习惯：")
            for habit in habits[:2]:
                lines.append(f"  • {habit}")

        return "\n".join(lines)

    async def build_l1_context(self, user_id: str, loop_round: int = 0,
                         task_type: str = "default", **kwargs) -> str:
        """构建完整的L1提示词"""
        parts = []

        # 1. AI身份定位（原有）
        parts.append(self.build_identity_context())

        # 2. 【内燃机】循环计数器（新增）
        parts.append(self.build_internal_engine_context(loop_round))

        # 3. 用户对话（原有）
        parts.append(await self.build_user_dialogue_context(user_id))

        # 4. 感知工具（原有）
        parts.append(self.build_perception_tools_context())

        # 5. 记忆5层（原有）
        parts.append(self.build_memory_layers_context(user_id))

        # 6. 【世界模型输出】（新增）
        parts.append(self.build_world_model_context(user_id))

        # 7. 【道德模块】（新增）
        action = kwargs.get('current_action', '')
        parts.append(self.build_moral_context(user_id, action))

        # 8. 【反思结果】（新增）
        parts.append(await self.build_reflection_context(user_id))

        # 9. 成功经验（原有）
        parts.append(self.build_experience_context(user_id))

        # 10. 【roles.yaml动态注入】（新增）
        parts.append(self.build_role_modules_context(task_type))

        return "\n\n".join(parts)


# 全局实例
# 创建全局唯一的ContextBuilder实例，供整个应用共享使用
# 使用单例模式确保上下文构建逻辑的一致性
context_builder = ContextBuilder()


# ============================================
# 文件总结性注释
# ============================================
#
# 【文件角色】
# context_builder.py 是 SiliconBase V5 系统的"上下文构建器"核心模块。
#
# 它位于AI调用链的关键位置：
#   Agent Loop → ContextBuilder → AI Client → LLM API
#                 ↑
#   整合系统提示 + 执行历史 + 聊天历史 + 压缩摘要
#
# 核心定位：
# - 负责将分散的信息源（系统提示、工作记忆、执行历史、聊天历史）整合为
#   符合OpenAI/Anthropic消息格式的完整消息列表
# - 解决AI上下文管理的核心痛点：token超限、system消息重复、历史信息冗余
#
# 【关联文件】
#
# | 文件 | 关系类型 | 说明 |
# |------|----------|------|
# | agent_loop.py | 调用者 | 主要调用者，在每次循环中调用build_optimized_context()构建消息 |
# | working_memory.py | 被依赖 | 读取压缩后的消息历史，提取_compressed标记的摘要 |
# | core/logger.py | 被依赖 | 导入logger用于调试记录（当前未大量使用，预留） |
# | ai_adapter.py | 下游 | ContextBuilder构建的消息列表最终传递给ai_adapter发送 |
# | ai_client.py | 下游 | 消息列表通过ai_client发送到实际的LLM API |
#
# 【达到的效果】
#
# 1. 解决System消息重复叠加问题
#    - 修复前：每次循环添加一条system消息，导致消息列表中有大量重复system消息
#    - 修复后：所有system内容合并为单条消息，结构清晰，节省token
#
# 2. 智能上下文压缩
#    - 三层递进策略：保留最近10条 → 压缩中等消息 → 摘要远古消息
#    - 避免token超限导致的API错误或费用飙升
#    - 保留关键信息：工具调用记录、重要事件，丢弃冗余对话
#
# 3. 执行历史智能摘要
#    - 将execution_history转换为简洁的统计摘要
#    - 格式：tool_name(成功N/失败M)，让AI快速了解之前的操作
#    - 避免将完整的执行结果（可能很长）重复放入上下文
#
# 4. 支持Agent Loop的两种状态
#    - 首次循环：发送原始任务，让AI开始规划
#    - 后续循环：提示AI基于工具执行结果决定下一步（继续/结束）
#
# 5. 元数据标记支持调试
#    - _compressed标记：标识消息是否为压缩生成
#    - _original_count：记录被压缩的原始消息数量
#    - 便于问题排查和压缩效果评估
#
# 【设计亮点】
#
# - 静态方法设计：ContextBuilder使用@staticmethod，无状态，线程安全
# - 全局单例：context_compressor和context_builder全局共享，配置统一
# - 渐进压缩：不一次性丢弃所有历史，而是分层处理，平衡信息量与长度
# - 向后兼容：支持working_memory为None或缺少get_message_history的情况
#
# 【版本历史】
#
# - 初始版本：基本的system + user消息组装
# - 修复版：合并多条system消息为一条，解决重复叠加问题
# - 当前版本：新增working_memory集成，支持读取压缩后的历史摘要
# ============================================
