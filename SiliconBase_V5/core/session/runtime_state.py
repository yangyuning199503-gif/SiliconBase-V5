#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""
运行时状态管理器 V2.0 - 彻底替代对话历史，防止 token 爆炸
核心功能：
- 只存储精简摘要，不存完整工具结果
- 支持持久化，用于中断恢复
- 控制Prompt长度在200 token以内
"""  # 模块文档字符串：说明本模块的核心功能和设计目标
import json  # JSON模块：用于状态数据的序列化和反序列化
import time  # 时间模块：用于记录创建和更新时间戳
from dataclasses import (  # 导入dataclass装饰器用于简化类定义，field用于默认值，asdict用于转换为字典
    asdict,
    dataclass,
    field,
)
from pathlib import Path  # Path类：用于处理文件路径，支持跨平台
from typing import Any  # 导入类型注解：Dict字典、Any任意类型、Optional可选类型、List列表

from core.logger import logger  # 导入日志记录器：用于记录持久化操作日志


@dataclass  # 使用@dataclass装饰器自动生成__init__、__repr__、__eq__等方法
class RuntimeState:  # 运行时状态类：压缩的任务运行时状态，用于替代冗长的对话历史
    """压缩的任务运行时状态，用于替代冗长的对话历史"""  # 类文档字符串
    task_id: str  # 任务ID：唯一标识符，用于区分不同任务的状态
    user_instruction: str  # 用户指令：原始的用户输入指令，限制长度避免过长
    current_role: str = "analyst"  # 当前角色：AI当前扮演的角色，默认为分析师(analyst)
    round_count: int = 0  # 轮次计数：已进行的对话轮次，用于控制任务长度
    last_tool: str | None = None  # 最后使用的工具：上一次调用的工具ID，None表示未使用
    last_result_summary: str | None = None  # 最后结果摘要：工具执行结果的简短描述，30字以内
    retry_count: int = 0  # 重试次数：当前步骤的重试计数，用于检测循环和限制重试
    step_summary: list[str] = field(default_factory=list)  # 步骤摘要列表：已完成步骤的摘要，最多保留5条，防止列表无限增长
    failed_tools: dict[str, int] = field(default_factory=dict)  # 工具失败计数字典：记录每个工具的失败次数，用于避免重复调用问题工具
    perception_snapshot: dict[str, Any] = field(default_factory=dict)  # 感知快照：系统环境状态摘要，包括窗口、CPU、内存等
    created_at: float = field(default_factory=time.time)  # 创建时间戳：状态对象创建时的Unix时间戳
    updated_at: float = field(default_factory=time.time)  # 更新时间戳：最后修改状态的时间，用于过期检测

    def to_prompt(self) -> str:  # 生成Prompt方法：将状态转换为AI可读的精简描述
        """生成给 AI 看的精简状态描述，控制在 200 token 以内"""  # 方法文档字符串
        lines = [  # 构建输出行列表
            f"【任务】{self.user_instruction[:50]}",  # 用户指令前50字，提供任务背景
            f"【当前角色】{self.current_role}，已进行 {self.round_count} 轮，已完成 {len(self.step_summary)} 步",  # 角色和进度信息
            f"【上一步】工具：{self.last_tool or '无'}，结果：{self.last_result_summary or '等待中'}",  # 上一步执行情况
            f"【重试次数】{self.retry_count}"  # 当前重试计数
        ]
        if self.step_summary:  # 如果有步骤摘要
            lines.append("【步骤摘要】" + " → ".join(self.step_summary[-3:]))  # 追加最近3步摘要，用箭头连接
        if self.perception_snapshot:  # 如果有感知快照
            win = self.perception_snapshot.get("active_window", "")  # 获取活动窗口标题
            cpu = self.perception_snapshot.get("cpu_high", "")  # # 获取高CPU进程信息
            lines.append(f"【环境】窗口：{win[:20]}，高CPU：{cpu[:20]}")  # 追加环境信息，限制长度
        return "\n".join(lines)  # 用换行连接所有行，形成最终Prompt文本

    def update_after_tool(self, tool_id: str, success: bool, summary: str):  # 工具调用后更新状态方法
        """工具调用后更新状态（只存储摘要）"""  # 方法文档字符串
        self.last_tool = tool_id  # 记录本次使用的工具ID
        if success:  # 判断工具执行是否成功
            msg = summary if summary else "成功"  # 成功时使用摘要，默认为"成功"
        else:  # 执行失败的情况
            msg = summary if summary else "失败"  # 使用摘要，默认为"失败"
            self.failed_tools[tool_id] = self.failed_tools.get(tool_id, 0) + 1  # 该工具失败计数+1
        self.last_result_summary = f"{tool_id}: {msg[:30]}"  # 生成结果摘要，格式为"工具名: 消息前30字"
        self.step_summary.append(self.last_result_summary)  # 将摘要添加到步骤历史
        if len(self.step_summary) > 5:  # 检查步骤摘要是否超过5条
            self.step_summary.pop(0)  # 超出限制时移除最旧的一条，保持列表长度固定
        self.round_count += 1  # 轮次计数+1
        self.updated_at = time.time()  # 更新修改时间戳

    def update_perception(self, snapshot: dict):  # 更新感知快照方法
        """更新感知快照（由外部调用）"""  # 方法文档字符串
        self.perception_snapshot = {  # 只保留关键字段，过滤无关数据
            "active_window": snapshot.get("active_window", ""),  # 当前活动窗口标题
            "cpu_high": snapshot.get("cpu_high", ""),  # CPU使用率高的进程
            "mem_high": snapshot.get("mem_high", "")  # 内存使用率高的进程
        }
        self.updated_at = time.time()  # 更新修改时间戳

    def to_dict(self) -> dict:  # 转换为字典方法
        return asdict(self)  # 使用asdict将dataclass实例转换为普通字典，便于JSON序列化

    @classmethod  # 类方法装饰器
    def from_dict(cls, data: dict):  # 从字典创建实例方法
        return cls(**data)  # 使用字典解包作为参数创建新的RuntimeState实例


class StatePersistence:  # 状态持久化管理器类：支持崩溃恢复和过期清理
    """状态持久化管理器，支持崩溃恢复和过期清理"""  # 类文档字符串
    def __init__(self, state_dir: Path = None):  # 初始化方法
        if state_dir is None:  # 如果未指定状态目录
            state_dir = Path(__file__).parent.parent / "data" / "states"  # 默认路径：项目根目录/data/states
        self.state_dir = state_dir  # 保存状态目录路径
        self.state_dir.mkdir(parents=True, exist_ok=True)  # 创建目录（如果不存在），parents=True递归创建，exist_ok=True已存在不报错

    def save(self, state: RuntimeState):  # 保存状态方法
        file_path = self.state_dir / f"{state.task_id}.json"  # 构建文件路径：task_id.json
        with open(file_path, "w", encoding="utf-8") as f:  # 以UTF-8编码打开文件用于写入
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)  # 序列化为JSON，保留中文，缩进2空格便于阅读

    def load(self, task_id: str) -> RuntimeState | None:  # 加载状态方法
        file_path = self.state_dir / f"{task_id}.json"  # 构建文件路径
        if file_path.exists():  # 检查文件是否存在
            with open(file_path, encoding="utf-8") as f:  # 以UTF-8编码打开文件用于读取
                data = json.load(f)  # 解析JSON为字典
                return RuntimeState.from_dict(data)  # 从字典恢复RuntimeState实例
        return None  # 文件不存在时返回None

    def delete(self, task_id: str):  # 删除状态方法
        file_path = self.state_dir / f"{task_id}.json"  # 构建文件路径
        if file_path.exists():  # 检查文件是否存在
            file_path.unlink()  # 删除文件

    def cleanup_expired(self, max_age_hours: int = 24):  # 清理过期状态方法
        now = time.time()  # 获取当前时间戳
        expired_count = 0  # 过期文件计数器
        for file_path in self.state_dir.glob("*.json"):  # 遍历目录下所有.json文件
            if now - file_path.stat().st_mtime > max_age_hours * 3600:  # 检查文件修改时间是否超过阈值（小时转秒）
                file_path.unlink()  # 删除过期文件
                expired_count += 1  # 计数+1
        if expired_count > 0:  # 如果有文件被清理
            logger.info(f"清理过期状态文件 {expired_count} 个")  # 记录清理日志


_state_persistence = StatePersistence()  # 模块级单例实例：全局共享的StatePersistence实例

def get_state_persistence() -> StatePersistence:  # 获取状态持久化实例函数
    return _state_persistence  # 返回全局单例，供其他模块调用


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase_V5 系统的"运行时状态管理器"，解决AI Agent在长对话中
# token消耗爆炸的问题。通过只存储精简摘要而非完整对话历史，将Prompt控制在
# 200 token以内，大幅降低API调用成本并提高响应速度。
#
# 【架构设计】
# - RuntimeState: 轻量级状态类，使用@dataclass简化定义，自动管理序列化
# - StatePersistence: 文件系统持久化，支持JSON格式存储，便于人工检查和调试
# - 摘要策略: 只保留步骤摘要（最多5条）、最后工具结果（30字）、环境快照
# - 过期清理: 自动清理24小时前的状态文件，防止磁盘无限增长
#
# 【关联文件】
# - core/agent_loop.py      : 调用方，在ReAct循环中更新和读取运行时状态
# - core/tool_executor.py   : 工具执行后调用update_after_tool()更新状态
# - core/perception.py      : 提供感知数据，调用update_perception()更新环境快照
# - core/logger.py          : 记录持久化操作日志
#
# 【核心功能效果】
# 1. Token控制: 将状态Prompt控制在200 token以内，避免长对话导致的成本激增
# 2. 崩溃恢复: 任务中断后可从文件恢复状态，继续执行未完成的任务
# 3. 循环检测: 通过retry_count和failed_tools检测工具调用循环，及时止损
# 4. 上下文保持: 即使不存储完整历史，仍保留足够上下文供AI决策
# 5. 自动清理: 过期状态自动清理，避免磁盘空间无限占用
#
# 【数据流向】
# 输入：工具执行结果 → update_after_tool() → 提取摘要 → 更新step_summary
# 输入：感知数据 → update_perception() → 过滤关键字段 → 更新perception_snapshot
# 输出：to_prompt() → 格式化文本 → 提供给LLM作为上下文
# 持久化：save() → JSON文件 / load() ← JSON文件
#
# 【使用场景】
# 场景1: 工具执行后 → update_after_tool() → 更新last_tool和step_summary
# 场景2: 每轮开始前 → to_prompt() → 生成精简状态描述注入Prompt
# 场景3: 系统崩溃后 → load(task_id) → 恢复状态继续任务
# 场景4: 定时任务 → cleanup_expired() → 清理24小时前的过期状态
# =============================================================================
