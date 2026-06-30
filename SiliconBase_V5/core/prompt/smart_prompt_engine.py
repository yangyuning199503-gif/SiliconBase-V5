#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""
智能提示词引擎 V2.0 - 支持模块化热编辑
核心思路：AI的"智商" = 上下文质量 × 思考框架

V2.0 更新：
- 集成 PromptBuilderV2，支持 roles.yaml 热编辑
- 支持前端模块选择
- 保持向后兼容

通过提供以下信息让AI表现更智能：
1. 环境感知 - 系统状态、历史行为
2. 用户画像 - 偏好、习惯、情绪
3. 任务记忆 - 类似任务的成功/失败经验
4. 思考框架 - CoT/ToT等推理结构
5. 自我修正 - 允许反思和重新规划
"""  # 模块文档字符串：说明核心思路和V2.0更新
import os  # 操作系统接口：用于路径检查等
from dataclasses import dataclass  # dataclass装饰器
from datetime import datetime  # datetime类：用于获取当前时间
from typing import Any  # 类型注解

from core.logger import logger  # 日志记录器：记录调试信息
from core.memory.memory_service import get_memory_service  # 【新增】异步记忆服务
from core.prompt.prompt_builder_v2 import get_prompt_builder  # PromptBuilderV2：模块化提示词构建
from core.tool.tool_manager import tool_manager  # 工具管理器：获取可用工具列表


@dataclass  # 使用@dataclass自动生成__init__等方法
class UserContext:  # 用户上下文数据类：封装用户相关信息
    """用户上下文"""  # 类文档字符串
    user_id: str = "default"  # 用户ID：默认default
    preferred_apps: list[str] = None  # 常用应用：用户偏好的应用列表
    recent_tasks: list[dict] = None  # 最近任务：用户最近执行的任务
    skill_level: str = "normal"  # 用户技术水平：normal/expert等
    mood_history: list[dict] = None  # 情绪历史：用户的情绪变化记录
    known_app_paths: dict[str, str] = None  # 【Phase 3】已知的应用路径 {应用名: 路径}

    def __post_init__(self):  # 初始化后处理方法
        """初始化后设置默认值"""  # 方法文档字符串
        if self.preferred_apps is None:  # 如果未提供
            self.preferred_apps = []  # 设为空列表
        if self.recent_tasks is None:  # 如果未提供
            self.recent_tasks = []  # 设为空列表
        if self.mood_history is None:  # 如果未提供
            self.mood_history = []  # 设为空列表
        if self.known_app_paths is None:  # 【Phase 3】
            self.known_app_paths = {}


@dataclass  # 使用@dataclass简化类定义
class SystemContext:  # 系统上下文数据类：封装系统状态信息
    """系统上下文"""  # 类文档字符串
    current_time: str = ""  # 当前时间：格式化的时间字符串
    active_windows: list[str] = None  # 当前活跃窗口：系统窗口列表
    system_load: float = 0.0  # 系统负载：CPU使用率
    last_action_success: bool = True  # 上次操作是否成功
    available_resources: dict = None  # 可用资源：系统资源信息
    installed_software: str = ""  # 【新增】已安装软件摘要：用于AI了解用户软件环境

    def __post_init__(self):  # 初始化后处理方法
        """初始化后设置默认值"""  # 方法文档字符串
        if self.active_windows is None:  # 如果未提供
            self.active_windows = []  # 设为空列表
        if self.available_resources is None:  # 如果未提供
            self.available_resources = {}  # 设为空字典
        if not self.installed_software:  # 【新增】如果未提供
            self.installed_software = "未获取"  # 设置默认值


class SmartPromptEngine:  # 智能提示词引擎类：核心组件
    """
    智能提示词引擎
    构建丰富的上下文让AI表现更聪明
    """  # 类文档字符串

    def __init__(self):  # 初始化方法
        """初始化智能提示词引擎"""  # 方法文档字符串
        self.tool_mgr = tool_manager  # 保存工具管理器引用

    async def build_smart_context_async(self,
                                        user_instruction: str,
                                        working_memory=None,
                                        session_id: str = "default",
                                        selected_modules: list[str] | None = None,
                                        mode: str = "daily") -> dict[str, Any]:
        """【异步改造】构建智能上下文，使用 MemoryService 替代同步记忆接口"""
        # 1. 收集环境信息
        user_ctx = await self._get_user_context_async(session_id)
        sys_ctx = self._get_system_context()

        # 2. 检索相关记忆
        relevant_memories = await self._get_relevant_memories_async(
            user_instruction, user_id=session_id
        )

        # 3. 分析任务类型
        task_analysis = self._analyze_task(user_instruction)  # 分析任务复杂度

        # 4. 【V2.0】使用 PromptBuilderV2 构建基础提示词
        builder = get_prompt_builder()  # 获取PromptBuilderV2实例

        # 准备变量
        variables = {
            "current_time": sys_ctx.current_time,  # 当前时间
            "system_load": sys_ctx.system_load,  # 系统负载
            "mode": mode,  # 【P2断裂点#5】工作模式
            "preferred_apps": ", ".join(user_ctx.preferred_apps) if user_ctx.preferred_apps else "暂无",  # 常用应用
            "recent_tasks": user_ctx.recent_tasks[0][:50] + "..." if user_ctx.recent_tasks and self._is_clean_text(user_ctx.recent_tasks[0]) else "暂无",  # 最近任务
            "skill_level": user_ctx.skill_level,  # 技术水平
            "task_type": task_analysis["type"],  # 任务类型
            "complexity": task_analysis["complexity"],  # 复杂度
            "estimated_steps": task_analysis["estimated_steps"],  # 预估步骤数
            "tool_count": len(tool_manager.tools),  # 当前加载的工具数量
            "category_list": self._build_dynamic_tool_summary(),  # 【修复】动态工具分类列表
            "installed_software": sys_ctx.installed_software,  # 【修复】已安装软件摘要
        }

        # === 新增：从 working_memory 注入 LLM 压缩结果 ===
        if working_memory and hasattr(working_memory, '_compression_cache'):
            cache = working_memory._compression_cache
            variables.update({
                "recent_progress": cache.get("recent_progress", "暂无"),
                "current_task_status": cache.get("current_task_status", "未知"),
                "key_entities": ", ".join(cache.get("key_entities", [])),
                "compressed_summary": cache.get("compressed_summary", ""),
            })

        # === 新增：常驻基底全局背景卡槽 ===
        try:
            from core.agent.context_assembler import ContextAssembler
            assembler = ContextAssembler()
            global_ctx = await assembler._extract_global_context(session_id)
            variables["project_goal"] = global_ctx.get("project_goal") or "协助用户完成当前任务"
            variables["user_long_term_preference"] = global_ctx.get("user_long_term_preference", "暂无")
            variables["historical_major_decisions"] = global_ctx.get("historical_major_decisions", "无")
        except Exception:
            variables.setdefault("project_goal", "协助用户完成当前任务")
            variables.setdefault("user_long_term_preference", "暂无")
            variables.setdefault("historical_major_decisions", "无")

        # 构建提示词（如果前端传入了selected_modules则使用，否则使用用户保存的偏好）
        system_prompt = builder.build_prompt(
            role="assistant",
            selected_modules=selected_modules,
            user_id=session_id,
            variables=variables
        )

        # 【P2断裂点#5修复】双模式差异化行为：如果V2构建成功，追加模式特定提示词
        if system_prompt:
            mode_prompt = self._build_mode_system_prompt(mode, sys_ctx)
            system_prompt = system_prompt + "\n\n" + mode_prompt

            # 【Phase 3】追加已知的应用路径
            if user_ctx.known_app_paths:
                app_paths_section = self._build_known_apps_section(user_ctx.known_app_paths)
                system_prompt = system_prompt + "\n\n" + app_paths_section

            # 【加密货币交易能力】仅在用户启用交易模块时注入
            if self._is_crypto_enabled():
                crypto_section = self._build_crypto_knowledge_section()
                system_prompt = system_prompt + "\n\n" + crypto_section
        elif not system_prompt:  # V2构建失败，回退到V1方式
            logger.debug("[SmartPromptEngine] V2构建失败，回退到V1方式")  # 记录日志
            system_prompt = self._build_system_prompt(
                user_ctx, sys_ctx, relevant_memories, task_analysis
            )
            # 【P2断裂点#5】即使是V1方式，也追加模式特定提示词
            mode_prompt = self._build_mode_system_prompt(mode, sys_ctx)
            system_prompt = system_prompt + "\n\n" + mode_prompt

        # 5. 构建思考框架
        reasoning_framework = self._build_reasoning_framework(
            task_analysis, working_memory
        )

        return {  # 返回智能上下文字典
            "system_prompt": system_prompt,  # 系统提示词
            "reasoning_framework": reasoning_framework,  # 推理框架
            "context": {  # 上下文信息
                "user": user_ctx,
                "system": sys_ctx,
                "memories": relevant_memories,
                "task": task_analysis
            },
            "modules_used": selected_modules or builder.get_user_selection(session_id, "assistant")  # 使用的模块
        }

    # 【修复】过滤异常文本，防止错误信息污染用户画像
    _ERROR_FILTER_KEYWORDS = ["coroutine", "cannot unpack", "RuntimeError", "Traceback", "<coroutine object"]

    @classmethod
    def _is_clean_text(cls, text: str) -> bool:
        """检查文本是否包含异常/错误关键词"""
        if not isinstance(text, str):
            return False
        text_lower = text.lower()
        return not any(kw.lower() in text_lower for kw in cls._ERROR_FILTER_KEYWORDS)

    @classmethod
    def _filter_recent_tasks(cls, tasks: list) -> list:
        """过滤掉包含异常文本的最近任务"""
        cleaned = []
        for t in tasks:
            if isinstance(t, str) and cls._is_clean_text(t):
                cleaned.append(t)
            elif isinstance(t, str):
                logger.warning(f"[SmartPrompt] 过滤污染的活动记录: {t[:60]}...")
            else:
                cleaned.append(str(t))
        return cleaned

    async def _get_user_context_async(self, session_id: str) -> UserContext:
        """【异步改造】获取用户上下文，使用 MemoryService 替代同步 memory.get()"""
        ctx = UserContext(user_id=session_id)

        try:
            memory_service = await get_memory_service()

            # 1. 从记忆中获取用户偏好
            prefs = await memory_service.query_memories(
                user_id=session_id,
                layer="medium",
                mem_type="user_preference",
                limit=5
            )
            for p in prefs:
                if isinstance(p, dict) and "content" in p:
                    content = p["content"]
                    if "常用" in content or "喜欢" in content:
                        import re
                        apps = re.findall(r'[\w\u4e00-\u9fa5]+(?:音乐|微信|QQ|浏览器|编辑器)', content)
                        ctx.preferred_apps.extend(apps)

            ctx.preferred_apps = list(set(ctx.preferred_apps))[:5]

            # 2. 获取记忆的应用路径
            try:
                app_path_memories = await memory_service.query_memories(
                    user_id=session_id,
                    layer="medium",
                    mem_type="app_path",
                    limit=10
                )
                ctx.known_app_paths = {}
                for mem in app_path_memories:
                    content = mem.get("content", "") if isinstance(mem, dict) else str(mem)
                    if "路径:" in content:
                        parts = content.split("路径:", 1)
                        app_name_part = parts[0].strip()
                        path_part = parts[1].strip()
                        if app_name_part and path_part and os.path.exists(path_part):
                            ctx.known_app_paths[app_name_part] = path_part
            except Exception as e:
                logger.debug(f"[SmartPrompt] 获取应用路径记忆失败: {e}")
                ctx.known_app_paths = {}

            # 3. 获取最近任务
            recent = await memory_service.query_memories(
                user_id=session_id,
                layer="short",
                limit=3
            )

            def _to_text(content):
                if isinstance(content, str):
                    return content
                elif isinstance(content, dict):
                    return content.get("text") or content.get("desc") or str(content)
                # 【修复】如果内容是协程对象，说明上游有 await 缺失，返回占位符而不是 str(coroutine)
                import inspect
                if inspect.isawaitable(content):
                    logger.error(f"[SmartPrompt] 发现未 await 的协程对象，上游存在协程泄露: {type(content)}")
                    return "[活动记录暂不可用]"
                return str(content)

            raw_tasks = [_to_text(r.get("content", "")) for r in recent if isinstance(r, dict)]
            ctx.recent_tasks = self._filter_recent_tasks(raw_tasks)

        except Exception as e:
            logger.debug(f"[SmartPrompt] 获取用户上下文失败: {e}")

        return ctx

    def _get_system_context(self) -> SystemContext:  # 获取系统上下文方法
        """获取系统上下文"""  # 方法文档字符串
        ctx = SystemContext()  # 创建系统上下文对象
        ctx.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # 格式化当前时间

        try:  # 异常处理块
            # 获取系统负载（轻量级）
            import psutil  # 导入psutil
            ctx.system_load = psutil.cpu_percent(interval=0.1)  # 获取CPU使用率

            # 获取活跃窗口（如果可能）
            # ctx.active_windows = self._get_active_windows()  # 当前禁用

        except Exception as e:  # 捕获异常
            logger.debug(f"[SmartPrompt] 获取系统上下文失败: {e}")  # 记录调试日志

        # 【新增】获取已安装软件摘要
        try:
            ctx.installed_software = self._get_installed_software_summary()
        except Exception as e:
            logger.debug(f"[SmartPrompt] 获取软件列表失败: {e}")
            ctx.installed_software = "未获取"

        return ctx  # 返回系统上下文

    def _get_installed_software_summary(self, limit: int = 30) -> str:
        """
        【新增】获取已安装软件摘要，用于系统提示词

        Args:
            limit: 最多返回的软件数量

        Returns:
            格式化的软件列表字符串
        """
        try:
            # 延迟导入避免循环依赖
            from sensors.system.global_view import global_view

            # 获取软件列表（从数据库，快速）
            all_software = global_view.get_all_software(user_id="default")

            if not all_software:
                return "暂无软件信息"

            # 按功能分类
            categories = {}
            for sw in all_software[:limit]:
                name = sw.get("name", "")
                if not name:
                    continue

                # 推断功能类别
                function_category = global_view._infer_function_from_name(name)

                if function_category not in categories:
                    categories[function_category] = []
                categories[function_category].append(name)

            # 格式化为文本
            summary_parts = []
            for category, apps in categories.items():
                # 每个类别最多显示5个
                app_list = ", ".join(apps[:5])
                if len(apps) > 5:
                    app_list += f" 等{len(apps)}个"
                summary_parts.append(f"{category}: {app_list}")

            return "; ".join(summary_parts) if summary_parts else "软件信息待分类"

        except Exception as e:
            logger.debug(f"[SmartPrompt] 构建软件摘要失败: {e}")
            return "未获取"

    async def _get_relevant_memories_async(self, query: str, limit: int = 3, user_id: str = "") -> list[dict]:
        """【异步改造】检索与当前任务相关的记忆，使用 MemoryService 替代同步接口"""
        memories = []

        try:
            memory_service = await get_memory_service()

            # 1. 向量检索相关经验记忆（通过 retrieve_context 获取 L4 经验层）
            retrieved = await memory_service.retrieve_context(user_id=user_id, query=query)
            for r in retrieved.l4[:limit]:
                memories.append({
                    "content": r.document,
                    "type": r.metadata.get("mem_type", "unknown"),
                    "rating": r.metadata.get("rating", 0),
                    "scene": r.metadata.get("scene", "")
                })

            # 2. 特别检索失败经验（避免重蹈覆辙）
            failures = await memory_service.query_memories(
                user_id=user_id,
                layer="evolve",
                mem_type="experience",
                limit=5
            )
            for f in failures:
                if isinstance(f, dict) and f.get("rating", 5) < 3:
                    memories.append({
                        "content": f"⚠️ 失败教训: {f.get('content', '')}",
                        "type": "lesson",
                        "rating": f.get("rating", 1),
                        "scene": f.get("scene", "")
                    })

        except Exception as e:
            logger.debug(f"[SmartPrompt] 检索记忆失败: {e}")

        return memories[:5]

    def _analyze_task(self, instruction: str) -> dict[str, Any]:  # 分析任务方法
        """分析任务类型和复杂度"""  # 方法文档字符串
        analysis = {  # 初始化分析结果
            "type": "simple",  # 默认简单类型
            "complexity": "low",  # 默认低复杂度
            "estimated_steps": 1,  # 默认1步
            "requires_planning": False,  # 默认不需要规划
            "keywords": []  # 关键词列表
        }

        # 简单启发式分析
        instruction_lower = instruction.lower()  # 转小写便于匹配

        # 检测复杂度
        complex_indicators = ["然后", "接着", "再", "并且", "同时", "如果", "否则"]  # 复杂任务指示词
        if any(ind in instruction for ind in complex_indicators):  # 包含复杂指示词
            analysis["complexity"] = "medium"  # 中等复杂度
            analysis["requires_planning"] = True  # 需要规划

        if instruction.count("，") > 2 or instruction.count("。") > 1:  # 多个分句或句号
            analysis["complexity"] = "high"  # 高复杂度
            analysis["requires_planning"] = True  # 需要规划
            analysis["estimated_steps"] = instruction.count("，") + 1  # 预估步骤数

        # 检测任务类型
        if any(kw in instruction_lower for kw in ["搜索", "查找", "查"]):  # 搜索类
            analysis["type"] = "search"
        elif any(kw in instruction_lower for kw in ["打开", "启动", "运行"]):  # 启动类
            analysis["type"] = "launch"
        elif any(kw in instruction_lower for kw in ["点击", "输入", "选择"]):  # 交互类
            analysis["type"] = "interaction"
        elif any(kw in instruction_lower for kw in ["监控", "提醒", "如果"]):  # 条件类
            analysis["type"] = "conditional"
            analysis["requires_planning"] = True  # 条件任务需要规划

        return analysis  # 返回分析结果

    def _build_dynamic_tool_summary(self) -> str:
        """构建动态工具分类摘要，用于注入到 PromptBuilderV2 的变量中。

        这样即使 roles.yaml 的静态 tool_list 被截断，AI 也能看到实时的工具分类。
        为每个分类的前3个高频工具附上简要参数说明，控制 Token 消耗。
        """
        try:
            categories = tool_manager.get_tool_categories()
            if not categories:
                return "  (暂无工具分类)"
            lines = []
            for cat_name, info in sorted(categories.items()):
                count = info.get('count', 0)
                lines.append(f"  • {cat_name} ({count}个)")
                # 为前3个高频工具附加必填参数说明
                tool_ids = info.get('tools', [])[:3]
                for tid in tool_ids:
                    try:
                        detail = tool_manager.get_tool_detail(tid)
                        required = detail.get('required', [])
                        if required:
                            lines.append(f"    - {tid}({', '.join(required)})")
                        else:
                            lines.append(f"    - {tid}")
                    except Exception:
                        lines.append(f"    - {tid}")
            return "【可用工具分类】\n" + "\n".join(lines) + "\n\n输入'手册'进入L2查看完整列表，或直接输入工具名查看L3详情。"
        except Exception as e:
            logger.debug(f"[SmartPrompt] 构建工具分类列表失败: {e}")
            return "  (工具分类暂不可用)"

    def _build_mode_system_prompt(self, mode: str, sys_ctx: SystemContext) -> str:
        """
        【P2断裂点#5修复】根据工作模式构建差异化系统提示词

        Daily模式：主动思考，弱连接可用，生命感，发散，对话优先
        Focus模式：专注执行，弱连接关闭，效率优先，确认理解，闭环

        Args:
            mode: 工作模式 (daily/focus)
            sys_ctx: 系统上下文

        Returns:
            模式特定的系统提示词
        """
        if mode == "daily":
            prompt = "【工作模式：日常模式】工具优先执行，弱连接可用，可主动建议。"
        else:  # focus模式
            prompt = "【工作模式：专注模式】直接执行，不主动建议，效率优先，完成后报告结果。"

        # 添加当前环境状态
        if sys_ctx.system_load > 80:
            prompt += f"\n【环境状态】⚠️ 系统负载较高({sys_ctx.system_load}%)，操作需谨慎"

        return prompt

    def _build_known_apps_section(self, known_app_paths: dict[str, str]) -> str:
        """【Phase 3】构建已知的应用路径提示词段落"""
        if not known_app_paths:
            return ""

        lines = ["【已知的应用路径】"]

        for app_name, path in list(known_app_paths.items())[:10]:  # 最多10个
            lines.append(f"• {app_name}: {path}")

        lines.append("提示: launch_app(\"应用名\") 直接调用")

        return "\n".join(lines)

    def _is_crypto_enabled(self) -> bool:
        """检查用户是否启用了加密货币交易模块"""
        try:
            from core.config import config
            # 方式1: 检查 trading.enabled
            trading_cfg = config.get("trading", {})
            if isinstance(trading_cfg, dict) and trading_cfg.get("enabled"):
                return True
            # 方式2: 检查 features.btc_trading
            features = config.get("features", {})
            if isinstance(features, dict) and features.get("btc_trading"):
                return True
        except Exception:
            pass
        return False

    def _build_crypto_knowledge_section(self) -> str:
        """构建加密货币交易领域知识段落（精简，控制Token）"""
        return (
            "【加密货币交易能力】\n"
            "工具: shadow_analyze(分析信号), shadow_execute(执行策略), get_quant_report(获取报告)。\n"
            "模式: Auto(自动)/AI全自动/AI半自动(需确认)/手动。\n"
            "术语: 合约=永续合约(BTC-USDT-SWAP), 做多=押涨, 做空=押跌, 平仓=了结持仓, 爆仓=保证金不足强制平仓。"
        )

    def _build_system_prompt(self,  # 构建系统提示词方法（V1兼容）
                             user_ctx: UserContext,  # 用户上下文
                             sys_ctx: SystemContext,  # 系统上下文
                             memories: list[dict],  # 相关记忆
                             task_analysis: dict) -> str:  # 任务分析
        """构建智能系统提示词"""  # 方法文档字符串

        # 基础身份
        lines = [  # 构建提示词行列表
            "🧠 你是底座，一个具身智能助手。",
            "",
            "【当前环境】",
            f"时间: {sys_ctx.current_time}",
        ]

        # 【新增】已安装软件信息
        if sys_ctx.installed_software and sys_ctx.installed_software != "未获取":
            lines.extend([
                "",
                "【已安装软件 - 用户可直接使用的应用】",
                sys_ctx.installed_software,
                "💡 当用户要求打开软件时，使用 launch_app 工具",
            ])

        # 系统状态
        if sys_ctx.system_load > 80:  # CPU负载高
            lines.append("⚠️ 系统负载较高，操作需谨慎")  # 添加警告

        # 用户画像
        lines.extend([  # 添加用户画像部分
            "",
            "【用户画像】",
        ])
        if user_ctx.preferred_apps:  # 有常用应用
            lines.append(f"常用应用: {', '.join(user_ctx.preferred_apps)}")
        if user_ctx.recent_tasks and self._is_clean_text(user_ctx.recent_tasks[0]):  # 有最近任务且未被污染
            lines.append(f"最近活动: {user_ctx.recent_tasks[0][:30]}...")

        # 相关记忆（让AI"记得"之前的经验）
        if memories:  # 有记忆
            lines.extend([  # 添加相关经验部分
                "",
                "【相关经验】",
            ])
            for i, mem in enumerate(memories[:3], 1):  # 最多3条
                content = mem["content"][:80] + "..." if len(mem["content"]) > 80 else mem["content"]  # 截断
                lines.append(f"{i}. [{mem['type']}] {content}")

        # 任务分析
        lines.extend([  # 添加任务分析部分
            "",
            "【任务分析】",
            f"类型: {task_analysis['type']}",
            f"复杂度: {task_analysis['complexity']}",
        ])
        if task_analysis['requires_planning']:  # 需要规划
            lines.append("⚡ 此任务需要多步规划，请先思考再执行")

        # 【新增】可用工具列表 - 高频工具 + 手册入口，控制Token
        try:
            from core.tool.tool_manager import tool_manager

            # 高频工具：AI必须直接知道ID的常用工具（保持精简）
            priority_tools = [
                ("launch_app", "启动应用"),
                ("keyboard_input", "键盘输入"),
                ("mouse_click", "鼠标点击"),
                ("click_text", "点击文字"),
                ("screenshot", "截图"),
                ("screen_ocr", "OCR识别"),
                ("window_focus", "聚焦窗口"),
                ("window_get", "获取窗口"),
                ("system_info", "系统信息"),
                ("file_manager", "文件管理(list/write/delete)"),
                ("read_file", "读取文件内容(支持分页)"),
                ("find_file", "查找文件位置(基于全盘扫描)"),
                ("clipboard_get", "获取剪贴板"),
                ("clipboard_set", "设置剪贴板"),
                ("web_search", "网页搜索"),
                ("web_open", "打开网页"),
                ("create_task", "创建定时任务"),
                ("list_tasks", "列出所有定时任务"),
                ("get_tool_manual", "获取完整工具手册，不确定工具时调用"),
                ("get_tool_detail_l3", "查询指定工具的详细参数和用法"),
            ]

            tool_lines = []
            for tool_id, desc in priority_tools:
                tool = tool_manager.get_tool(tool_id)
                if tool:
                    tool_lines.append(f"  • {tool_id}: {desc}")

            if tool_lines:
                lines.extend([
                    "",
                    "【高频工具 - 必须使用正确工具ID】",
                    "如果你需要的工具不在上面，调用 get_tool_manual 查看完整手册，",
                    "或调用 get_tool_detail_l3 查询某个工具的参数。",
                    "",
                ] + tool_lines)
        except Exception as e:
            logger.debug(f"[SmartPrompt] 获取工具列表失败: {e}")

        # 记忆使用策略
        lines.extend([  # 添加记忆使用策略
            "",
            "【记忆使用策略】",
            "- L1短期记忆：当前对话上下文（最近30轮，显示前3轮摘要）",
            "- L2中期记忆：今天类似任务经验",
            "- L3长期记忆：通用策略和方法论",
            "",
            "使用建议：",
            "1. 优先参考L1短期记忆保持对话连贯性",
            "2. 结合L2中期经验优化执行方式",
            "3. 参考L3长期策略形成完整方案",
        ])

        # 智能行为准则
        lines.extend([  # 添加行为准则
            "",
            "【智能行为准则】",
            "1. 主动联想: 根据用户历史偏好，预判需求",
            "2. 学习记忆: 参考相关经验，避免重复错误",
            "3. 情境感知: 结合时间、系统状态调整策略",
            "4. 解释说明: 执行前简要说明你的思路",
            "5. 优雅失败: 如果无法完成，解释原因并提供替代方案",
        ])

        return "\n".join(lines)  # 用换行连接所有行

    def _build_reasoning_framework(self,  # 构建推理框架方法
                                   task_analysis: dict,  # 任务分析
                                   working_memory=None) -> str:  # 工作记忆
        """
        构建推理框架
        根据任务复杂度选择不同的思考方式
        """  # 方法文档字符串
        complexity = task_analysis["complexity"]  # 获取复杂度

        if complexity == "high":  # 高复杂度
            return """【思考框架】理解→规划→执行→反思→总结
输出: 思考:[分析] 计划:[步骤] 行动:{"tool":"...","params":{...}}"""
        elif complexity == "medium":  # 中等复杂度
            return """【思考框架】分析→规划→执行→验证
输出: 思考:[分析] 行动:{"tool":"...","params":{...}}"""
        else:  # 低复杂度
            return """【思考框架】直接执行，快速响应
输出: {"tool":"...","params":{...}}"""

    def build_enriched_messages(self,  # 构建丰富消息列表方法
                                user_instruction: str,  # 用户指令
                                context: dict[str, Any]) -> list[dict[str, str]]:  # 上下文
        """
        构建丰富的消息列表
        包含：
        - 系统提示词
        - 相关历史（类似任务）
        - 当前任务
        """  # 方法文档字符串
        messages = []  # 消息列表

        # 1. 系统提示词
        messages.append({  # 添加系统消息
            "role": "system",
            "content": context["system_prompt"] + "\n\n" + context["reasoning_framework"]  # 组合提示词和框架
        })

        # 2.  few-shot 示例（如果有高价值经验）
        memories = context["context"]["memories"]  # 获取记忆
        for mem in memories:  # 遍历记忆
            if mem.get("rating", 0) >= 4:  # 高评分经验（4分以上）
                content = mem["content"]
                if "成功" in content or "完成" in content:  # 成功经验
                    # 提取任务和解决方案
                    messages.append({  # 添加示例消息
                        "role": "user",
                        "content": f"类似任务参考: {content[:100]}"
                    })
                    break  # 只加一个示例，避免token过多

        # 3. 当前任务
        messages.append({  # 添加用户当前任务
            "role": "user",
            "content": user_instruction
        })

        return messages  # 返回消息列表


# 全局实例
_smart_engine: SmartPromptEngine | None = None  # 引擎单例引用


def get_smart_prompt_engine() -> SmartPromptEngine:  # 获取引擎单例函数
    """获取智能提示词引擎单例"""  # 函数文档字符串
    global _smart_engine  # 引用全局变量
    if _smart_engine is None:  # 如果未创建
        _smart_engine = SmartPromptEngine()  # 创建实例
    return _smart_engine  # 返回实例


async def build_smart_context(user_instruction: str,
                                working_memory=None,
                                session_id: str = "default",
                                mode: str = "daily") -> dict[str, Any]:
    """【异步改造】便捷函数：构建智能上下文"""
    return await get_smart_prompt_engine().build_smart_context_async(
        user_instruction, working_memory, session_id, mode=mode
    )


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase_V5 系统的"智能提示词引擎"，负责构建丰富的上下文环境，
# 通过整合用户画像、系统状态、相关经验和思考框架，显著提升AI的表现质量。
#
# 【架构设计】
# - UserContext: 用户上下文数据类，封装用户偏好、最近任务、技术水平
# - SystemContext: 系统上下文数据类，封装时间、负载、资源状态
# - SmartPromptEngine: 核心引擎，实现5步上下文构建流程
# - PromptBuilderV2集成: V2.0版本支持模块化热编辑，通过roles.yaml配置
#
# 【5步上下文构建流程】
# 1. 收集环境: _get_user_context() + _get_system_context() → 用户+系统信息
# 2. 检索记忆: _get_relevant_memories() → 向量检索相关经验 + 失败教训
# 3. 分析任务: _analyze_task() → 启发式分析任务类型和复杂度
# 4. 构建提示: PromptBuilderV2.build_prompt() → 模块化构建，V1方式回退
# 5. 推理框架: _build_reasoning_framework() → 根据复杂度选择CoT/简化/直接
#
# 【任务分析规则】
# 复杂度检测:
# - 包含"然后/接着/如果"等词 → medium复杂度，需要规划
# - 多个分句（，>2或。>1） → high复杂度，预估步骤=分句数+1
# 任务类型:
# - 搜索/查找/查 → search类型
# - 打开/启动/运行 → launch类型
# - 点击/输入/选择 → interaction类型
# - 监控/提醒/如果 → conditional类型
#
# 【关联文件】
# - core/memory.py              : memory实例，检索用户偏好和相关经验
# - core/tool_manager.py        : tool_manager实例，获取可用工具列表
# - core/prompt_builder_v2.py   : PromptBuilderV2，模块化提示词构建
# - core/logger.py              : 记录调试信息
#
# 【核心功能效果】
# 1. 环境感知: 自动收集系统时间、负载、用户偏好应用等信息
# 2. 记忆检索: 向量检索相关经验，特别检索失败教训避免重蹈覆辙
# 3. 任务分析: 启发式分析任务类型和复杂度，动态调整策略
# 4. 模块化构建: V2.0支持roles.yaml热编辑，前端可选择模块
# 5. 推理框架: 根据复杂度提供完整CoT（高）、简化CoT（中）、直接执行（低）
# 6. 工具指导: 列出可用工具及ID，确保AI使用正确的工具
# 7. 向后兼容: V2构建失败自动回退到V1方式
#
# 【数据流向】
# 构建流程: build_smart_context() → 收集环境 → 检索记忆 → 分析任务 → 构建提示 → 生成框架
# 消息构建: build_enriched_messages() → 系统提示 + few-shot示例 + 当前任务
# 用户上下文: memory.get() → 偏好+最近任务 → UserContext
# 系统上下文: psutil + datetime → 时间+负载 → SystemContext
#
# 【使用场景】
# 场景1: 任务开始前 → build_smart_context() → 获取完整上下文 → 发送给LLM
# 场景2: 复杂任务 → _analyze_task()判定high → 提供完整CoT框架指导思考
# 场景3: 用户反馈 → 检索相关记忆 → 引用成功经验 → 提升执行质量
# 场景4: 模块化配置 → 前端选择模块 → PromptBuilderV2热编辑 → 定制化提示词
# =============================================================================
