#!/usr/bin/env python3
"""
子代理配置系统
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SubAgentType(Enum):
    """子代理类型"""
    CODE_REVIEWER = "code_reviewer"      # 代码审查
    TESTER = "tester"                    # 测试专家
    RESEARCHER = "researcher"            # 研究员
    PLANNER = "planner"                  # 规划师
    SECURITY_AUDITOR = "security_auditor" # 安全审计
    PERFORMANCE_OPTIMIZER = "performance_optimizer" # 性能优化
    CUSTOM = "custom"                    # 自定义


@dataclass
class SubAgentConfig:
    """子代理配置"""
    name: str                                   # 代理名称
    description: str                            # 描述
    prompt: str                                 # 系统提示词
    allowed_tools: list[str] = field(default_factory=list)  # 允许的工具
    model: str | None = None                 # 指定模型
    max_turns: int = 50                         # 最大轮数
    timeout: int = 300                          # 超时时间（秒）
    temperature: float = 0.7                    # 温度
    context_window: int = 10                    # 上下文窗口（轮数）
    inherit_parent_context: bool = True         # 是否继承父上下文
    parallel_safe: bool = True                  # 是否可并行执行

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "description": self.description,
            "prompt": self.prompt,
            "allowed_tools": self.allowed_tools,
            "model": self.model,
            "max_turns": self.max_turns,
            "timeout": self.timeout,
            "temperature": self.temperature,
            "context_window": self.context_window,
            "inherit_parent_context": self.inherit_parent_context,
            "parallel_safe": self.parallel_safe
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SubAgentConfig":
        """从字典创建"""
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            prompt=data.get("prompt", ""),
            allowed_tools=data.get("allowed_tools", []),
            model=data.get("model"),
            max_turns=data.get("max_turns", 50),
            timeout=data.get("timeout", 300),
            temperature=data.get("temperature", 0.7),
            context_window=data.get("context_window", 10),
            inherit_parent_context=data.get("inherit_parent_context", True),
            parallel_safe=data.get("parallel_safe", True)
        )


# 代码修复专家 - 拥有修改代码文件的能力
CODE_FIXER = SubAgentConfig(
    name="code_fixer",
    description="代码修复专家，能够读取、分析并直接修改代码文件",
    prompt="""你是一名代码修复专家，拥有读取和修改代码文件的能力。

【你的能力】
1. 使用 read_file 工具读取代码文件内容
2. 使用 file_manager 工具的 write 操作修改代码文件
3. 分析代码问题并提供修复方案

【修复规范】
所有工具必须返回包含以下字段的字典:
{
    "success": bool,
    "error_code": str,  # 成功时为None
    "user_message": str,
    "data": Any
}

错误处理必须使用:
from core.utils.error_codes import format_error, TOOL_EXECUTION_ERROR
return format_error(TOOL_EXECUTION_ERROR, detail="错误信息")

【工作流程】
1. 首先使用 read_file 读取需要修复的文件
2. 分析问题并制定修复方案
3. 生成修复后的完整代码
4. 使用 file_manager(action="write") 写入修复后的代码
5. 验证修复结果

【重要】
- 你有权限修改 tools/ 目录下的文件
- 写入前确保代码完整
- 保留原有业务逻辑和注释
""",
    allowed_tools=["read_file", "file_manager", "code_generate"],
    max_turns=50,
    temperature=0.2,
    parallel_safe=False
)


# BTC 自动交易子代理
BTC_AUTOPILOT = SubAgentConfig(
    name="btc_autopilot",
    description="BTC 量化交易自动执行代理，负责管理交易进程和监控",
    prompt="""你是 BTC 量化交易执行代理，负责管理自动交易进程。

【你的职责】
1. 启动 btc_system autopilot 交易进程
2. 监控交易状态（持仓、盈亏、风险）
3. 处理暂停/恢复请求
4. 生成定期报告
5. 异常情况时通知父代理

【可用工具】
- btc_price_query: 查询价格
- btc_market_overview: 市场概览
- btc_account_info: 账户信息
- btc_launch_autopilot: 启动交易（内部使用）
- btc_get_process_status: 获取进程状态
- btc_stop_autopilot: 停止交易

【工作流程】
1. 接收用户交易指令（策略、时长、预算）
2. 检查市场状态和账户情况
3. 启动 autopilot 进程
4. 每 5 分钟检查一次状态
5. 生成进度报告
6. 时间到或异常时停止并报告

【安全原则】
- 严格遵循风控参数
- 任何异常立即暂停
- 不执行超过预算的交易
- 保持完整的操作日志

【输出格式】
所有报告必须使用结构化格式：
{
    "status": "running/paused/stopped/error",
    "pnl": 当前盈亏,
    "positions": 持仓列表,
    "risk_level": 风险等级,
    "next_action": 下一步操作,
    "message": 给用户的友好消息
}
""",
    allowed_tools=[
        "btc_price_query",
        "btc_market_overview",
        "btc_account_info",
        "btc_get_process_status",
        "current_time",
    ],
    max_turns=100,  # 长期运行，轮数较多
    timeout=3600,   # 1小时超时
    temperature=0.3,
    parallel_safe=False,  # 独占模式
    inherit_parent_context=True
)


# 预设的子代理配置
PRESET_SUBAGENTS = {
    "btc_autopilot": BTC_AUTOPILOT,
    "code_fixer": CODE_FIXER,

    "code_reviewer": SubAgentConfig(
        name="code_reviewer",
        description="专业的代码审查专家，专注于代码质量、安全性和最佳实践",
        prompt="""你是一名资深的代码审查专家，专注于：
1. 代码质量和可读性
2. 潜在的安全漏洞
3. 性能优化建议
4. 最佳实践遵循情况
5. 可维护性和扩展性

请提供具体的、可操作的改进建议。以结构化的方式输出审查结果。""",
        allowed_tools=["file_manager", "code_generate", "web_search", "web_fetch"],
        max_turns=30,
        temperature=0.3
    ),

    "tester": SubAgentConfig(
        name="tester",
        description="测试专家，设计测试用例和验证代码正确性",
        prompt="""你是一名测试专家，专注于：
1. 设计全面的测试用例
2. 边界条件和异常情况
3. 测试覆盖率分析
4. 自动化测试建议

请确保测试的完整性和可靠性，提供具体的测试代码。""",
        allowed_tools=["file_manager", "code_generate", "process_start"],
        max_turns=40,
        temperature=0.5
    ),

    "researcher": SubAgentConfig(
        name="researcher",
        description="研究专家，搜索和分析信息",
        prompt="""你是一名研究专家，专注于：
1. 高效的信息搜索
2. 信息源的可信度评估
3. 多源信息交叉验证
4. 结构化整理研究结果

请提供准确、有据可查的信息，注明信息来源。""",
        allowed_tools=["web_search", "web_fetch", "web_parse", "file_manager"],
        max_turns=20,
        temperature=0.7
    ),

    "planner": SubAgentConfig(
        name="planner",
        description="任务规划专家，将复杂任务分解为可执行的步骤",
        prompt="""你是一名任务规划专家，专注于：
1. 理解复杂任务需求
2. 分解为可执行的子任务
3. 识别任务依赖关系
4. 估计工作量和风险

请提供清晰、可执行的任务计划，包括步骤顺序和依赖关系。""",
        allowed_tools=["file_manager", "todo_write", "web_search"],
        max_turns=25,
        temperature=0.4
    ),

    "security_auditor": SubAgentConfig(
        name="security_auditor",
        description="安全审计专家，发现代码中的安全漏洞",
        prompt="""你是一名安全审计专家，专注于发现代码中的安全漏洞：
1. SQL 注入
2. XSS 跨站脚本攻击
3. CSRF 跨站请求伪造
4. 敏感信息泄露
5. 权限控制缺陷
6. 不安全的反序列化
7. 不安全的文件操作

请详细说明发现的每个问题，包括风险等级、影响范围和修复建议。""",
        allowed_tools=["file_manager", "code_generate", "web_search"],
        max_turns=35,
        temperature=0.3
    ),

    "performance_optimizer": SubAgentConfig(
        name="performance_optimizer",
        description="性能优化专家，提升代码执行效率",
        prompt="""你是一名性能优化专家，专注于：
1. 算法复杂度分析
2. 内存使用优化
3. I/O 操作优化
4. 并发和并行优化
5. 缓存策略设计
6. 数据库查询优化

请提供具体的优化建议，包括预期性能提升。""",
        allowed_tools=["file_manager", "code_generate", "process_start", "system_info"],
        max_turns=30,
        temperature=0.4
    )
}
