#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
from core.logger import logger

# 声明文件编码为UTF-8，支持中文
"""
工作记忆管理 - 维护任务状态和分层查询状态  # 模块功能：任务工作记忆管理

【配置集中化】从 config/memory.yaml 读取配置
"""  # 文档字符串结束

from typing import Any  # 导入类型注解

# 【配置集中化】导入配置模块
from core.config import config
from core.utils.compression import MessageCompressor as _MessageCompressor

# 【整合】从 compression 模块导入统一的压缩器
from core.utils.compression import estimate_tokens

# 【向后兼容】保留MessageCompressor类名，直接使用compression模块的实现
# 注意：实际实现已迁移到 core.compression 模块，此处仅作为别名保留
MessageCompressor = _MessageCompressor


class WorkingMemory:  # 定义工作记忆类
    """
    管理 AI 的工作记忆
    - 记录任务目标、已完成步骤、当前状态
    - 记录分层交互状态（Layer 1/2/3）
    - 层级切换次数限制（防止无限循环）
    - 【新增】阶段锚点（防遗忘机制）
    - 【配置集中化】从 config/memory.yaml 读取配置
    """  # 类文档字符串

    # 【配置集中化】从 config/memory.yaml 读取最大层级切换次数，默认30
    MAX_LAYER_SWITCHES = config.get("memory.max_layer_switches", 30)

    def __init__(self, goal: str = "", completed: list[str] = None, current: str = "",
                 user_id: str = "default", user_name: str = "用户",  # 【修复】新增用户字段，有默认值保证向后兼容
                 **kwargs):  # 初始化方法
        self.goal = goal  # 任务目标
        self.completed = completed or []  # 已完成步骤列表
        self.current = current  # 当前状态

        # 【修复】用户身份信息（新增）
        self.user_id = user_id  # 用户ID
        self.user_name = user_name  # 用户显示名称

        # 分层交互状态  # 分层状态
        self.query_stage: str = "layer1"  # 查询阶段：layer1, layer2, layer3
        self.current_category: str | None = None  # 当前分类
        self.current_tool: str | None = None  # 当前工具

        # 层级切换计数（安全机制）  # 层级切换安全
        self.layer_switch_count: int = 0  # 层级切换计数器
        self.layer_switch_history: list[dict[str, Any]] = []  # 切换历史记录

        # ========== 【阶段锚点 - 防遗忘机制】==========  # 阶段锚点
        self.phase_anchors: list[dict[str, Any]] = []  # 阶段锚点列表
        self.current_phase: str = "init"  # 当前阶段: init/感知/理解/执行/完成
        self.phase_history: list[str] = []  # 阶段历史轨迹
        self.user_intent_snapshot: str = ""  # 用户原始意图快照
        self.key_context: dict[str, Any] = {}  # 关键上下文

        # 当前模型信息
        self.current_model_provider: str | None = None
        self.current_model_name: str | None = None

        # ========== 【任务完成检测 - 防过度拦截机制】==========
        self._force_continue_count: int = 0  # 强制继续次数计数器
        self._task_check_history: list[dict[str, Any]] = []  # 任务检测历史记录
        # =============================================

    def update_after_tool(self, tool_id: str, success: bool, result_summary: str):  # 工具执行后更新
        """工具执行后更新工作记忆"""  # 方法文档字符串
        status = "✓" if success else "✗"  # 根据成功状态设置标记
        self.completed.append(f"{status} {tool_id}: {result_summary}")  # 添加到已完成列表
        self.current = f"刚执行 {tool_id}"  # 更新当前状态
        # 限制历史长度 - 从配置读取最大长度，默认5
        max_completed = config.get("memory.max_completed_items", 5)
        if len(self.completed) > max_completed:
            self.completed.pop(0)  # 移除最旧的一条

    def record_layer_switch(self, from_stage: str, to_stage: str, reason: str = "") -> bool:  # 记录层级切换
        """
        记录层级切换，并检查是否超过限制

        Returns:
            bool: 是否允许继续切换（未超过限制返回True）
        """  # 方法文档字符串
        self.layer_switch_count += 1  # 计数器+1
        self.layer_switch_history.append({  # 添加到历史
            "from": from_stage,  # 源阶段
            "to": to_stage,  # 目标阶段
            "reason": reason,  # 切换原因
            "count": self.layer_switch_count  # 当前计数
        })

        # 限制历史记录长度 - 从配置读取最大长度，默认10
        max_history = config.get("memory.max_layer_switch_history", 10)
        if len(self.layer_switch_history) > max_history:
            self.layer_switch_history.pop(0)  # 移除最旧的一条

        return self.layer_switch_count <= self.MAX_LAYER_SWITCHES  # 返回是否允许继续

    def to_dict(self) -> dict:  # 转换为字典
        """序列化为字典"""  # 方法文档字符串
        return {  # 返回字典
            "goal": self.goal,  # 目标
            "completed": self.completed,  # 已完成
            "current": self.current,  # 当前状态
            "query_stage": self.query_stage,  # 查询阶段
            "current_category": self.current_category,  # 当前分类
            "current_tool": self.current_tool,  # 当前工具
            "layer_switch_count": self.layer_switch_count,  # 切换计数
            "layer_switch_history": self.layer_switch_history,  # 切换历史
            # 【阶段锚点序列化】
            "phase_anchors": self.phase_anchors,  # 阶段锚点
            "current_phase": self.current_phase,  # 当前阶段
            "phase_history": self.phase_history,  # 阶段历史
            "user_intent_snapshot": self.user_intent_snapshot,  # 用户意图快照
            "key_context": self.key_context,  # 关键上下文
            "current_model_provider": self.current_model_provider,  # 当前模型提供商
            "current_model_name": self.current_model_name,  # 当前模型名称
            # 【修复】用户身份信息序列化（新增）
            "user_id": self.user_id,  # 用户ID
            "user_name": self.user_name,  # 用户显示名称
        }

    @classmethod  # 类方法装饰器
    def from_dict(cls, data: dict):  # 从字典恢复
        """从字典恢复"""  # 方法文档字符串
        wm = cls(data.get("goal", ""), data.get("completed", []), data.get("current", ""))  # 创建实例
        wm.query_stage = data.get("query_stage", "layer1")  # 恢复查询阶段
        wm.current_category = data.get("current_category")  # 恢复分类
        wm.current_tool = data.get("current_tool")  # 恢复工具
        wm.layer_switch_count = data.get("layer_switch_count", 0)  # 恢复计数
        wm.layer_switch_history = data.get("layer_switch_history", [])  # 恢复历史
        # 【阶段锚点反序列化】
        wm.phase_anchors = data.get("phase_anchors", [])  # 恢复锚点
        wm.current_phase = data.get("current_phase", "init")  # 恢复当前阶段
        wm.phase_history = data.get("phase_history", [])  # 恢复阶段历史
        wm.user_intent_snapshot = data.get("user_intent_snapshot", "")  # 恢复意图快照
        wm.key_context = data.get("key_context", {})  # 恢复上下文
        wm.current_model_provider = data.get("current_model_provider")  # 恢复模型提供商
        wm.current_model_name = data.get("current_model_name")  # 恢复模型名称
        # 【修复】用户身份信息反序列化（新增）
        wm.user_id = data.get("user_id", "default")  # 恢复用户ID，默认为"default"
        wm.user_name = data.get("user_name", "用户")  # 恢复用户名称，默认为"用户"
        return wm  # 返回实例

    def get_status_bar(self) -> str:  # 生成状态栏
        """生成状态栏文本"""  # 方法文档字符串
        completed_str = " | ".join(self.completed[-3:]) if self.completed else "无"  # 拼接已完成
        return f"目标: {self.goal[:20]}... | 已完成: {completed_str} | 当前: {self.current}"  # 返回状态栏

    # ========== 【阶段锚点方法 - 防遗忘机制】==========  # 阶段锚点方法区域

    async def save_phase_anchor(self, phase_name: str, key_info: dict[str, Any]):  # 保存阶段锚点
        """
        保存阶段锚点
        在每个关键阶段调用，保存当前状态快照

        Args:
            phase_name: 阶段名称 (perception/understanding/execution/completion)
            key_info: 关键信息字典
        """  # 方法文档字符串
        import time  # 导入时间模块
        anchor = {  # 创建锚点字典
            "phase": phase_name,  # 阶段名
            "timestamp": time.time(),  # 时间戳
            "goal": self.goal,  # 目标
            "completed_count": len(self.completed),  # 已完成数
            "current": self.current,  # 当前状态
            "key_info": key_info,  # 关键信息
        }
        self.phase_anchors.append(anchor)  # 添加到锚点列表
        self.current_phase = phase_name  # 更新当前阶段
        self.phase_history.append(phase_name)  # 添加到阶段历史

        # 限制锚点数量（从配置读取最大数量，默认10）
        max_anchors = config.get("memory.phase_anchors.max_anchors", 10)
        if len(self.phase_anchors) > max_anchors:
            self.phase_anchors.pop(0)  # 移除最旧的一个

    def add_phase_anchor(self, phase_name: str, key_info: dict[str, Any] = None) -> None:
        """
        【同步兼容方法】保存阶段锚点

        为兼容历史测试和同步调用方提供的同步版本，行为与 save_phase_anchor 一致。
        """
        import time
        anchor = {
            "phase": phase_name,
            "timestamp": time.time(),
            "goal": self.goal,
            "completed_count": len(self.completed),
            "current": self.current,
            "key_info": key_info or {},
        }
        self.phase_anchors.append(anchor)
        self.current_phase = phase_name
        self.phase_history.append(phase_name)
        max_anchors = config.get("memory.phase_anchors.max_anchors", 10)
        if len(self.phase_anchors) > max_anchors:
            self.phase_anchors.pop(0)

    def set_user_intent(self, intent: str, context: dict[str, Any] = None):  # 设置用户意图
        """
        设置用户原始意图快照
        在任务开始时保存，防止后续遗忘
        """  # 方法文档字符串
        self.user_intent_snapshot = intent  # 保存意图
        if context:  # 如果提供了上下文
            self.key_context = context  # 保存上下文

    def get_phase_summary(self) -> str:  # 获取阶段摘要
        """
        获取阶段摘要
        用于在长任务中提醒AI当前进度和原始目标
        """  # 方法文档字符串
        parts = []  # 部分列表

        # 1. 原始意图  # 意图部分
        if self.user_intent_snapshot:  # 如果有意图快照
            parts.append(f"【原始任务】{self.user_intent_snapshot}")  # 添加意图

        # 2. 当前阶段  # 阶段部分
        if self.current_phase:  # 如果有当前阶段
            parts.append(f"【当前阶段】{self.current_phase}")  # 添加阶段

        # 3. 关键上下文  # 上下文部分
        if self.key_context:  # 如果有上下文
            ctx_parts = []  # 上下文部分列表
            for k, v in self.key_context.items():  # 遍历上下文
                ctx_parts.append(f"{k}:{v}")  # 格式化键值对
            parts.append(f"【关键信息】{', '.join(ctx_parts)}")  # 添加上下文

        # 4. 已完成摘要  # 已完成部分
        if self.completed:  # 如果有已完成
            completed_summary = " → ".join(self.completed[-3:])  # 拼接最近3条
            parts.append(f"【已完成】{completed_summary}")  # 添加已完成

        return " | ".join(parts) if parts else "任务进行中"  # 返回摘要

    def get_context_for_prompt(self) -> str:  # 获取提示词上下文
        """
        生成用于提示词的上下文信息
        在每次调用AI前附加到提示词中
        """  # 方法文档字符串
        summary = self.get_phase_summary()  # 获取阶段摘要

        # 如果阶段多，添加阶段轨迹  # 阶段轨迹
        if len(self.phase_history) > 3:  # 如果阶段历史超过3个
            phase_trail = " → ".join(self.phase_history[-5:])  # 拼接最近5个阶段
            return f"[任务记忆] {summary}\n[阶段轨迹] {phase_trail}"  # 返回带轨迹的上下文

        return f"[任务记忆] {summary}"  # 返回上下文

    # =============================================  # 阶段锚点方法区域结束

    def add_tool_result(self, tool_id: str, result: dict):  # 添加工具结果
        """
        添加工具执行结果到工作记忆
        用于多步骤任务跟踪
        """  # 方法文档字符串
        # 更新已完成列表  # 更新已完成
        success = result.get("success", False)  # 获取成功状态
        message = result.get("user_message", "")  # 获取用户消息
        self.update_after_tool(tool_id, success, message)  # 调用更新方法

        # 标记刚执行了工具（用于多步骤检查）  # 工具标记
        self.just_executed_tool = True  # 设置工具执行标记
        self.last_tool_result = result  # 保存工具结果

    def append(self, item: dict):  # 添加消息
        """
        添加消息到工作记忆（兼容列表接口）
        基于Token数量自动触发压缩，避免无限增长
        【改造】支持 _category + _overwrite：同类别的旧消息自动删除
        """  # 方法文档字符串
        if not hasattr(self, '_message_history'):  # 如果没有消息历史属性
            self._message_history = []  # 创建空列表

        # 【改造】按类别覆盖：同 _category 且 _overwrite=True 的旧消息自动删除
        category = item.get("_category")
        overwrite = item.get("_overwrite", False)
        if category and overwrite:
            self._message_history = [
                m for m in self._message_history
                if m.get("_category") != category
            ]

        self._message_history.append(item)  # 添加消息到历史

    def insert_system_message(self, content: str, priority: str = "normal",
                              category: str = None, overwrite: bool = False,
                              source: str = None):
        """
        插入系统消息到工作记忆

        用于高优先级消息（如紧急洞察）插入到提示词前面
        【改造】支持 category + overwrite：同类别的旧消息自动删除

        Args:
            content: 消息内容
            priority: 优先级 ("high" | "normal")，high会插入到最前面
            category: 消息类别，用于覆盖式管理
            overwrite: 是否覆盖同类别旧消息
            source: 消息来源标识，供 ContextBuilder 等下游白名单校验使用
        """
        if not hasattr(self, '_message_history'):
            self._message_history = []

        message = {"role": "system", "content": content, "_category": category}
        if source:
            message["source"] = source

        # 【改造】按类别覆盖
        if category and overwrite:
            self._message_history = [
                m for m in self._message_history
                if m.get("_category") != category
            ]

        if priority == "high" and self._message_history:
            # 高优先级：插入到最前面（但在任何用户消息之前）
            # 找到最后一个system消息的位置，插入其后
            insert_idx = 0
            for i, msg in enumerate(self._message_history):
                if msg.get("role") == "system":
                    insert_idx = i + 1
            self._message_history.insert(insert_idx, message)
        else:
            # 普通优先级：追加到末尾
            self._message_history.append(message)

        # 【Token压缩】计算当前Token数，超过阈值则压缩  # Token压缩逻辑
        total_tokens = sum(estimate_tokens(m.get("content", "")) for m in self._message_history)  # 计算总token

        if total_tokens > MessageCompressor.TOKEN_THRESHOLD:  # 如果超过阈值
            # 触发压缩  # 执行压缩
            original_count = len(self._message_history)  # 记录原始数量
            self._message_history = MessageCompressor.compress(self._message_history)  # 压缩
            compressed_count = len(self._message_history)  # 获取压缩后数量

            # 记录压缩事件（仅调试）  # 压缩统计
            if hasattr(self, '_compression_stats'):  # 如果有统计属性
                self._compression_stats['count'] = self._compression_stats.get('count', 0) + 1  # 计数+1
                self._compression_stats['saved_tokens'] = self._compression_stats.get('saved_tokens', 0) + (total_tokens - MessageCompressor.TARGET_TOKENS)  # 累节省token

            print(f"[WorkingMemory] 消息历史压缩: {original_count}条 -> {compressed_count}条, Token: {total_tokens} -> ~{MessageCompressor.TARGET_TOKENS}")  # 打印压缩信息

    def get_message_history(self) -> list[dict]:  # 获取消息历史
        """获取当前消息历史（可能被压缩）"""  # 方法文档字符串
        msgs = getattr(self, '_message_history', [])  # 返回消息历史，默认为空列表
        # 【修复】返回前检查并触发压缩，避免 append() 路径无限膨胀
        total_tokens = sum(estimate_tokens(m.get("content", "")) for m in msgs)
        if total_tokens > MessageCompressor.TOKEN_THRESHOLD:
            original_count = len(msgs)
            self._message_history = MessageCompressor.compress(msgs)
            compressed_count = len(self._message_history)
            print(f"[WorkingMemory] 消息历史压缩: {original_count}条 -> {compressed_count}条")
        return getattr(self, '_message_history', [])

    def get_message_stats(self) -> dict[str, Any]:  # 获取消息统计
        """获取消息历史统计"""  # 方法文档字符串
        messages = getattr(self, '_message_history', [])  # 获取消息历史
        total_tokens = sum(estimate_tokens(m.get("content", "")) for m in messages)  # 计算总token
        compressed_count = sum(1 for m in messages if m.get("_compressed"))  # 计算压缩条目数

        return {  # 返回统计字典
            "message_count": len(messages),  # 消息数量
            "estimated_tokens": total_tokens,  # 估算token数
            "compressed_entries": compressed_count,  # 压缩条目数
            "compression_stats": getattr(self, '_compression_stats', {})  # 压缩统计
        }


# ═══════════════════════════════════════════════════════════════
# 【Phase 1 Week 2】Coordinator 集成方法
# ═══════════════════════════════════════════════════════════════

    def to_dict_full(self) -> dict[str, Any]:
        """
        完整序列化（包含所有细节，用于Coordinator保存）

        相比 to_dict()，此方法包含更多内部状态信息：
        - _message_history: 消息历史
        - _compression_stats: 压缩统计
        - just_executed_tool 等临时状态
        """
        data = self.to_dict()

        # 添加内部状态
        data["_message_history"] = getattr(self, '_message_history', [])
        data["_compression_stats"] = getattr(self, '_compression_stats', {})
        data["just_executed_tool"] = getattr(self, 'just_executed_tool', False)
        data["last_tool_result"] = getattr(self, 'last_tool_result', None)

        return data

    @classmethod
    def from_dict_full(cls, data: dict[str, Any]) -> 'WorkingMemory':
        """
        从完整字典恢复（包含所有细节，用于Coordinator恢复）

        相比 from_dict()，此方法恢复更多内部状态信息
        """
        # 先使用基础反序列化
        wm = cls.from_dict(data)

        # 恢复内部状态
        if '_message_history' in data:
            wm._message_history = data['_message_history']
        if '_compression_stats' in data:
            wm._compression_stats = data['_compression_stats']
        if 'just_executed_tool' in data:
            wm.just_executed_tool = data['just_executed_tool']
        if 'last_tool_result' in data:
            wm.last_tool_result = data['last_tool_result']

        return wm

    def save_for_coordinator(self, user_id: str = "default", session_id: str | None = None) -> dict[str, Any]:
        """
        为 Coordinator 保存状态

        Args:
            user_id: 用户ID
            session_id: 会话ID

        Returns:
            状态字典
        """
        return {
            "data": self.to_dict_full(),
            "user_id": user_id,
            "session_id": session_id,
            "saved_at": __import__('time').time()
        }

    def restore_from_coordinator(self, state: dict[str, Any], strategy: str = "merge") -> bool:
        """
        从 Coordinator 恢复状态

        Args:
            state: Coordinator 保存的状态
            strategy: 恢复策略 - "merge" | "replace"

        Returns:
            是否成功
        """
        try:
            data = state.get("data")
            if not data:
                return False

            if strategy == "replace":
                # 完全替换
                restored = self.from_dict_full(data)
                # 复制所有属性
                self.__dict__.update(restored.__dict__)
                return True
            elif strategy == "merge":
                # 合并策略
                self.key_context.update(data.get("key_context", {}))
                self.user_intent_snapshot = data.get("user_intent_snapshot", self.user_intent_snapshot)
                if data.get("goal"):
                    self.goal = data["goal"]
                return True

            return False
        except Exception as e:
            print(f"[WorkingMemory] 从 Coordinator 恢复失败: {e}")
            return False


def get_working_memory_for_coordinator(user_id: str = "default", session_id: str | None = None) -> WorkingMemory | None:
    """
    获取用于 Coordinator 的工作记忆

    从全局状态获取当前活跃的工作记忆实例
    """
    try:
        from core import global_state
        wm = getattr(global_state, 'current_working_memory', None)
        if wm and isinstance(wm, WorkingMemory):
            return wm
    except Exception as e:
        # 【静默失败修复】不能静默，必须记录ERROR日志
        logger.error(f"[WorkingMemory] 从global_state恢复失败: {e}", exc_info=True)
    return None


# ═══════════════════════════════════════════════════════════════
# 文件角色总结
# ═══════════════════════════════════════════════════════════════
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"工作记忆管理器"，负责维护AI在任务执行过程中的状态信息。
# 是AgentLoop的核心数据结构，支持分层交互和防遗忘机制。
#
# 【架构设计】
# - 状态管理: 记录任务目标、已完成步骤、当前状态
# - 分层查询: 支持Layer 1/2/3三层交互状态
# - 安全防护: 层级切换次数限制，防止无限循环
# - Token压缩: 基于token数量自动压缩消息历史
# - 阶段锚点: 防遗忘机制，保存关键阶段状态快照
# - 【Phase 1 Week 2】Coordinator集成: 支持通过Coordinator保存/恢复
#
# 【关联文件】
# - core/agent_loop.py                : Agent主循环，使用WorkingMemory
# - core/state_snapshot.py            : 状态快照，捕获和恢复WorkingMemory
# - core/loop_types.py                : 循环状态定义
# - core/pause_confirmation_state_machine.py : 长任务状态机，保存任务状态
# - core/state_coordinator.py         : 状态协调器，统一管理工作记忆
#
# 【核心功能效果】
# 1. 任务状态跟踪: 记录目标、已完成、当前状态
# 2. 分层交互: 支持L1/L2/L3三层查询状态管理
# 3. 循环防护: 层级切换超过30次自动阻止，防止无限循环
# 4. 消息压缩: Token超过3000自动压缩，保留关键信息
# 5. 防遗忘机制: 阶段锚点保存关键状态，长任务不偏离目标
# 6. 序列化支持: 支持to_dict/from_dict，便于快照存储
# 7. 【Phase 1 Week 2】Coordinator集成: to_dict_full/from_dict_full支持完整序列化
#
# 【使用场景】
# - 多轮对话: 维护对话历史和上下文
# - 工具调用链: 跟踪多步骤工具调用
# - 长任务执行: 24小时任务的状态保持
# - 分层查询: L1概览->L2详情->L3执行的分层推进
# - 模式切换: 通过Coordinator保存/恢复工作记忆
# ═══════════════════════════════════════════════════════════════
