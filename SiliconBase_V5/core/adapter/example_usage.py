#!/usr/bin/env python3
"""
适配器使用示例
展示如何使用标准化适配器包装现有模块
"""

# ==================== 基础用法 ====================

"""
1. 基本使用 - 直接通过适配器调用原有功能
"""
def example_basic_usage():
    """基础用法示例"""
    from core.adapter import get_agent_loop_adapter
    from core.task.task_queue import Task

    # 获取适配器实例（单例）
    adapter = get_agent_loop_adapter()

    # 创建任务
    task = Task(
        type="user",
        intent={"raw": "查询天气"},
        priority=3,
        session_id="example"
    )

    # 运行 Agent Loop（通过适配器）
    result, working_memory = adapter.run_agent_loop(
        task=task,
        max_rounds=10,
        session_id="example"
    )

    print(f"任务结果: {result}")
    print(f"执行统计: {adapter.get_execution_stats()}")


# ==================== 事件发射用法 ====================

"""
2. 事件驱动 - 使用事件发射器
"""
def example_with_event_emitter():
    """使用事件发射器的示例"""
    from core.adapter import get_agent_loop_adapter, get_consciousness_adapter, get_evolution_adapter

    # 简单的事件发射器实现
    class SimpleEventEmitter:
        def __init__(self):
            self.handlers = {}

        def emit(self, event_type: str, data: dict):
            print(f"[事件] {event_type}: {data}")
            if event_type in self.handlers:
                for handler in self.handlers[event_type]:
                    handler(data)

        def on(self, event_type: str, handler):
            if event_type not in self.handlers:
                self.handlers[event_type] = []
            self.handlers[event_type].append(handler)

    # 创建事件发射器
    emitter = SimpleEventEmitter()

    # 设置到各个适配器
    agent_adapter = get_agent_loop_adapter()
    agent_adapter.set_event_emitter(emitter)

    evo_adapter = get_evolution_adapter()
    evo_adapter.set_event_emitter(emitter)

    con_adapter = get_consciousness_adapter()
    con_adapter.set_event_emitter(emitter)

    # 注册自定义事件处理器
    emitter.on("task:completed", lambda data: print(f"任务完成: {data['task_id']}"))
    emitter.on("evolution:success_reflection", lambda data: print(f"成功反思: {data['task_desc']}"))
    emitter.on("consciousness:thought", lambda data: print(f"意识思考: {data['content'][:50]}..."))


# ==================== 消息处理器用法 ====================

"""
3. 消息协议 - 使用标准化消息
"""
def example_with_message_handler():
    """使用消息处理器的示例"""
    from core.adapter import get_agent_loop_adapter, get_evolution_adapter
    from core.protocol import AgentMessage, MessageType, get_message_type

    # 消息处理器
    def message_handler(message: AgentMessage):
        """处理标准化消息"""
        msg_type = get_message_type(message)

        if msg_type == MessageType.TASK_RESULT:
            print(f"[任务结果] ID: {message['payload']['task_id']}")
            print(f"           成功: {message['payload']['success']}")

        elif msg_type == MessageType.EVOLUTION_TRIGGER:
            print(f"[进化触发] 类型: {message['payload']['trigger_type']}")
            print(f"           描述: {message['payload']['description']}")

        elif msg_type == MessageType.THOUGHT_GENERATED:
            print(f"[思考生成] 内容: {message['payload']['content'][:80]}...")

    # 设置消息处理器
    agent_adapter = get_agent_loop_adapter()
    agent_adapter.set_message_handler(message_handler)

    evo_adapter = get_evolution_adapter()
    evo_adapter.set_message_handler(message_handler)


# ==================== 监听器用法 ====================

"""
4. 监听器模式 - Evolution 事件监听
"""
def example_with_listeners():
    """使用监听器的示例"""
    from core.adapter import get_consciousness_adapter, get_evolution_adapter

    # Evolution 监听器
    def evolution_listener(event_type: str, data: dict):
        if "reflection" in event_type:
            print(f"[反思事件] {event_type}: 任务 {data.get('task_id', 'unknown')}")
        elif "pattern" in event_type:
            print(f"[模式提取] 从 {data.get('task_count', 0)} 个任务中提取")

    evo_adapter = get_evolution_adapter()
    evo_adapter.add_listener(evolution_listener)

    # Consciousness 思考监听器
    def thought_listener(content: str):
        print(f"[思考内容] {content[:60]}...")

    con_adapter = get_consciousness_adapter()
    con_adapter.add_thought_listener(thought_listener)


# ==================== 综合用法 ====================

"""
5. 综合示例 - 完整的集成用法
"""
def example_integrated_usage():
    """综合集成示例"""
    from core.adapter import get_agent_loop_adapter, get_consciousness_adapter, get_evolution_adapter
    from core.task.task_queue import Task

    # 创建统一的事件中心
    class EventCenter:
        def __init__(self):
            self.event_log = []

        def emit(self, event_type: str, data: dict):
            event = {"type": event_type, "data": data, "timestamp": __import__('time').time()}
            self.event_log.append(event)
            print(f"[EventCenter] {event_type}")

        def get_events(self, event_type: str = None):
            if event_type:
                return [e for e in self.event_log if e["type"] == event_type]
            return self.event_log

    # 初始化
    event_center = EventCenter()

    # 配置所有适配器
    agent_adapter = get_agent_loop_adapter()
    agent_adapter.set_event_emitter(event_center)

    evo_adapter = get_evolution_adapter()
    evo_adapter.set_event_emitter(event_center)
    evo_adapter.add_listener(lambda t, d: print(f"  [EvoListener] {t}"))

    con_adapter = get_consciousness_adapter()
    con_adapter.set_event_emitter(event_center)

    # 启动意识线程
    con_adapter.start()

    # 模拟任务处理
    task = Task(
        type="user",
        intent={"raw": "示例任务"},
        priority=3,
        session_id="demo"
    )

    # 通过适配器运行
    try:
        result, memory = agent_adapter.run_agent_loop(
            task=task,
            max_rounds=5,
            session_id="demo"
        )
        print(f"\n任务执行完成: {result}")
    except Exception as e:
        print(f"任务执行出错: {e}")

    # 查看统计
    print("\n=== 统计信息 ===")
    print(f"Agent 执行统计: {agent_adapter.get_execution_stats()}")
    print(f"Evolution 反思统计: {evo_adapter.get_reflection_stats()}")
    print(f"Consciousness 思考统计: {con_adapter.get_thinking_stats()}")
    print(f"事件中心记录数: {len(event_center.get_events())}")

    # 停止意识线程
    con_adapter.stop()


# ==================== 消息协议用法 ====================

"""
6. 消息协议 - 直接使用协议创建消息
"""
def example_protocol_usage():
    """消息协议使用示例"""
    from core.protocol import (
        create_evolution_trigger,
        create_reflection_request,
        create_task_request,
        create_task_result,
        create_thought,
        create_tool_call,
        get_message_type,
        validate_message,
    )

    # 创建各种类型的消息

    # 1. 任务请求
    task_msg = create_task_request(
        goal="执行数据分析",
        source="user",
        priority="high",
        context={"data_source": "sales.csv"},
        session_id="session_001"
    )
    print(f"任务请求消息: {task_msg['msg_type']}")

    # 2. 任务结果
    result_msg = create_task_result(
        task_id="task_001",
        success=True,
        result={"analysis": "completed", "rows": 1000},
        tools_used=["csv_reader", "data_analyzer"],
        execution_time=2.5
    )
    print(f"任务结果消息: {result_msg['msg_type']}")

    # 3. 工具调用
    tool_msg = create_tool_call(
        tool_id="file_reader",
        params={"path": "/tmp/data.txt", "encoding": "utf-8"},
        task_id="task_001",
        timeout=30
    )
    print(f"工具调用消息: {tool_msg['msg_type']}")

    # 4. 思考生成
    thought_msg = create_thought(
        content="用户似乎在进行数据分析任务，我需要准备相关的工具...",
        source="consciousness",
        emotional_state={"energy": 7, "curiosity": 8},
        trigger="task_observation"
    )
    print(f"思考消息: {thought_msg['msg_type']}")

    # 5. 反思请求
    reflect_msg = create_reflection_request(
        task_description="执行数据分析任务",
        execution_history=[
            {"tool": "csv_reader", "success": True},
            {"tool": "data_analyzer", "success": True}
        ],
        task_id="task_001"
    )
    print(f"反思请求消息: {reflect_msg['msg_type']}")

    # 6. 进化触发
    evolve_msg = create_evolution_trigger(
        trigger_type="success",
        task_id="task_001",
        description="成功完成数据分析任务",
        report={"improvement_suggestions": ["缓存数据结果"]}
    )
    print(f"进化触发消息: {evolve_msg['msg_type']}")

    # 验证消息
    print("\n消息验证:")
    print(f"  task_msg 有效: {validate_message(task_msg)}")
    print(f"  result_msg 类型: {get_message_type(result_msg)}")


# ==================== 接口检查用法 ====================

"""
7. 接口检查 - 验证对象是否实现接口
"""
def example_interface_check():
    """接口检查示例"""
    from core.adapter import get_agent_loop_adapter, get_consciousness_adapter, get_evolution_adapter
    from core.interfaces import IAgentLoop, IConsciousness, IEvolutionEngine

    agent = get_agent_loop_adapter()
    evo = get_evolution_adapter()
    con = get_consciousness_adapter()

    # 检查是否实现接口
    print("接口实现检查:")
    print(f"  Agent Loop 实现 IAgentLoop: {isinstance(agent, IAgentLoop)}")
    print(f"  Evolution 实现 IEvolutionEngine: {isinstance(evo, IEvolutionEngine)}")
    print(f"  Consciousness 实现 IConsciousness: {isinstance(con, IConsciousness)}")


# ==================== 运行示例 ====================

if __name__ == "__main__":
    print("=" * 60)
    print("适配器使用示例")
    print("=" * 60)

    print("\n1. 消息协议示例:")
    example_protocol_usage()

    print("\n2. 接口检查示例:")
    example_interface_check()

    print("\n3. 事件发射示例:")
    example_with_event_emitter()

    print("\n注意: 其他示例需要完整的系统环境才能运行")
    print("请根据实际需求选择合适的集成方式")
