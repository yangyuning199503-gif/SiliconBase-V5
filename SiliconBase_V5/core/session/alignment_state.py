#!/usr/bin/env python3
"""
聊天对齐状态管理
大纲：语音输入必须经过聊天对齐，用户和AI对齐需求前不进入循环模式
"""
import asyncio
import threading
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AlignmentState:
    """单次对话对齐状态"""
    user_id: str
    original_input: str           # 用户原始输入（语音转文字）
    ai_understanding: str = ""    # AI对需求的理解
    is_confirmed: bool = False    # 是否已确认
    conversation_history: list[dict] = field(default_factory=list)  # 对齐过程对话
    created_at: datetime = field(default_factory=datetime.now)
    confirmed_at: datetime | None = None

    # 【新增】纠正相关字段
    is_correction: bool = False           # 是否是纠正流程
    parent_task_id: str | None = None  # 父任务ID

    def add_turn(self, role: str, content: str):
        """添加对话轮次"""
        self.conversation_history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })

    def confirm(self, ai_final_understanding: str):
        """确认对齐完成"""
        self.ai_understanding = ai_final_understanding
        self.is_confirmed = True
        self.confirmed_at = datetime.now()


class AlignmentStateManager:
    """对齐状态管理器（单例）"""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._states: dict[str, AlignmentState] = {}
                    cls._instance._initialized = True
        return cls._instance

    def create_alignment(self, user_id: str, original_input: str) -> AlignmentState:
        """创建新的对齐状态"""
        state = AlignmentState(
            user_id=user_id,
            original_input=original_input
        )
        self._states[user_id] = state
        return state

    def get_alignment(self, user_id: str) -> AlignmentState | None:
        """获取用户的对齐状态"""
        return self._states.get(user_id)

    def confirm_alignment(self, user_id: str, ai_understanding: str) -> bool:
        """确认对齐完成"""
        state = self._states.get(user_id)
        if state:
            state.confirm(ai_understanding)
            return True
        return False

    def clear_alignment(self, user_id: str):
        """清除对齐状态"""
        if user_id in self._states:
            del self._states[user_id]

    def is_in_alignment(self, user_id: str) -> bool:
        """检查用户是否在对齐模式"""
        state = self._states.get(user_id)
        return state is not None and not state.is_confirmed


# 触发进入循环的关键词（AI说这些词表示要进入循环）
TRIGGER_LOOP_KEYWORDS = [
    "开始执行", "启动任务", "进入循环", "开始处理",
    "确认执行", "立即执行", "准备执行"
]

# 明确任务指令模式 - 用户说这些词表示明确的执行意图
DIRECT_TASK_PATTERNS = [
    r"打开[\s\u4e00-\u9fa5]+",           # 打开XX
    r"启动[\s\u4e00-\u9fa5]+",           # 启动XX
    r"执行[\s\u4e00-\u9fa5]+",           # 执行XX
    r"运行[\s\u4e00-\u9fa5]+",           # 运行XX
    r"开始[\s\u4e00-\u9fa5]+",           # 开始XX
    r"关闭[\s\u4e00-\u9fa5]+",           # 关闭XX
    r"播放[\s\u4e00-\u9fa5]+",           # 播放XX
    r"暂停[\s\u4e00-\u9fa5]+",           # 暂停XX
    r"停止[\s\u4e00-\u9fa5]+",           # 停止XX
    r"发送[\s\u4e00-\u9fa5]+",           # 发送XX
    r"查询[\s\u4e00-\u9fa5]+",           # 查询XX
    r"搜索[\s\u4e00-\u9fa5]+",           # 搜索XX
]

# 需要进一步确认的模式（模糊需求）
AMBIGUOUS_PATTERNS = [
    r"帮[我\s]*[做弄弄一下]?",            # 帮我...（不完整）
    r"能[不能]?.*吗[?？]?$",               # 能不能...吗？（疑问句）
    r"可以.*吗[?？]?$",                    # 可以...吗？（疑问句）
    r".*[是\s]*什么",                     # ...是什么（询问）
    r".*怎[么样做]",                       # ...怎么样/怎么做（询问）
]

# 【新增】纠正意图模式 - 用户在对齐上下文中纠正AI理解
CORRECTION_PATTERNS = [
    r"不[对是行好]",                    # 不对、不是、不行、不好
    r"错[了误]",                        # 错了、错误
    r"[你您].*[理解错错错搞]",          # 你理解错了、你搞错了
    r"方[式法].*错",                    # 方式错了、方法错了
    r"重[新来]",                        # 重新来、重来
    r"换[一个个种]",                    # 换一个、换一种
    r"不[要要需].*[这那]",              # 不要这样、不要这个
    r"我[说的意思是].*是",              # 我说的是、我的意思是
]


def check_trigger_loop(ai_response: str) -> bool:
    """检查AI响应是否触发进入循环"""
    ai_response_lower = ai_response.lower()
    return any(keyword in ai_response_lower for keyword in TRIGGER_LOOP_KEYWORDS)


def is_direct_task_command(user_input: str) -> bool:
    """
    检测用户输入是否是明确的任务指令

    如果用户说"打开网易云音乐"这样的明确指令，
    应该直接执行而不是反复询问确认。

    Args:
        user_input: 用户输入文本

    Returns:
        bool: 是否是明确的任务指令
    """
    import re

    # 去除首尾空白
    text = user_input.strip()

    # 检查明确任务模式
    return any(
        re.search(pattern, text) and not text.endswith(("?", "？", "吗"))
        for pattern in DIRECT_TASK_PATTERNS
    )


def is_ambiguous_request(user_input: str) -> bool:
    """
    检测用户输入是否是模糊的需求

    模糊需求需要进一步对齐确认，
    明确指令可以直接执行。

    Args:
        user_input: 用户输入文本

    Returns:
        bool: 是否是模糊需求
    """
    import re

    text = user_input.strip()

    # 检查模糊模式
    for pattern in AMBIGUOUS_PATTERNS:
        if re.search(pattern, text):
            return True

    # 过短的输入（少于4个字符）视为模糊
    return len(text) < 4


async def classify_voice_intent(user_input: str, context: dict = None) -> str:
    """
    分类语音输入的意图

    【生命化改造】从纯文本正则升级为"LLM 情境理解 + 正则快速路径"：
    - 明确指令仍走正则快速返回（零延迟）
    - 非明确指令调用轻量 LLM（5秒超时），结合对话历史做情境判断
    - LLM 失败降级回正则逻辑

    Args:
        user_input: 用户输入文本
        context: 上下文信息，包含 in_alignment, chat_history, session_id 等

    Returns:
        str: 意图类型
            - "direct_task": 明确任务指令，直接执行
            - "correction": 纠正意图，用户纠正AI理解
            - "ambiguous": 模糊需求，需要对齐确认
            - "chat": 闲聊/询问，纯聊天回复
    """
    import re

    # ═══════════════════════════════════════════════════════════════
    # 第一层：明确指令快速路径（正则，零延迟）
    # ═══════════════════════════════════════════════════════════════
    if is_direct_task_command(user_input):
        return "direct_task"

    # ═══════════════════════════════════════════════════════════════
    # 第二层：纠正意图检查（只在已有对齐上下文时触发）
    # ═══════════════════════════════════════════════════════════════
    if context and context.get('in_alignment', False):
        for pattern in CORRECTION_PATTERNS:
            if re.search(pattern, user_input, re.IGNORECASE):
                return "correction"

    # ═══════════════════════════════════════════════════════════════
    # 第三层：LLM 情境理解（非明确指令时启用）
    # ═══════════════════════════════════════════════════════════════
    chat_history = context.get('chat_history', []) if context else []

    # 构建轻量 prompt（控制在 200 tokens 以内）
    history_text = ""
    if chat_history:
        # 只取最近 2 轮（用户+AI）
        recent = chat_history[-4:]
        lines = []
        for msg in recent:
            role = "用户" if msg.get('role') == 'user' else "AI"
            content = msg.get('content', '')[:40]
            lines.append(f"{role}: {content}")
        history_text = "\n".join(lines)

    llm_prompt = f"""你是意图分类器。只输出一个单词。

【最近对话】
{history_text or "（无）"}

【当前输入】{user_input}

【选项】direct_task（明确任务：打开/执行/查询等）/ ambiguous（模糊：帮我看看/处理一下）/ chat（闲聊/问答）

意图："""

    try:
        from core.ai.ai_adapter import call_thinker_async
        from core.ai.ai_config import AIScene

        # 5 秒硬超时，避免阻塞主流程
        llm_response = await asyncio.wait_for(
            call_thinker_async(
                [{"role": "user", "content": llm_prompt}],
                scene=AIScene.CHAT
            ),
            timeout=5.0
        )

        if llm_response:
            # 清洗输出：取第一个有效单词
            clean = llm_response.strip().lower().split()[0] if llm_response.strip() else ""
            # 去掉标点
            clean = re.sub(r'[^a-z_]', '', clean)
            if clean in ("direct_task", "ambiguous", "chat", "correction"):
                return clean
    except asyncio.TimeoutError:
        pass  # 超时降级
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug(f"[classify_voice_intent] LLM 判断失败: {e}")

    # ═══════════════════════════════════════════════════════════════
    # 第四层：正则降级兜底
    # ═══════════════════════════════════════════════════════════════
    if chat_history:
        # 上下文引用词检测
        context_reference_keywords = ['刚才', '之前', '继续', '接着', '刚才那个', '上面']
        if any(kw in user_input for kw in context_reference_keywords):
            return "chat"

        # 快速连续提问检测
        user_msgs = [m for m in chat_history if m.get('role') == 'user']
        if len(user_msgs) >= 2:
            try:
                t1 = datetime.fromisoformat(user_msgs[-1].get('timestamp', ''))
                t2 = datetime.fromisoformat(user_msgs[-2].get('timestamp', ''))
                if (t1 - t2).total_seconds() < 30 and len(user_input.strip()) <= 8:
                    return "chat"
            except Exception:
                pass

    if is_ambiguous_request(user_input):
        return "ambiguous"

    return "chat"
