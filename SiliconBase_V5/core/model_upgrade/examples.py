#!/usr/bin/env python3
"""
模型升级方案使用示例

展示如何使用模型升级与接入方案的各种功能。
"""

import asyncio

from core.model_upgrade import BudgetLimit, ModelUpgradeOrchestrator, RoutingStrategy, get_upgrade_orchestrator


async def example_basic_usage():
    """基础使用示例"""
    print("=" * 60)
    print("示例 1: 基础使用")
    print("=" * 60)

    # 获取编排器实例
    orchestrator = get_upgrade_orchestrator()

    # 简单聊天（自动路由）
    result = await orchestrator.chat("你好，请介绍一下自己")

    print(f"响应: {result.content[:100]}...")
    print(f"使用模型: {result.provider}/{result.model}")
    print(f"成本: ${result.cost:.6f}")
    print(f"延迟: {result.latency_ms}ms")
    print()


async def example_smart_routing():
    """智能路由示例"""
    print("=" * 60)
    print("示例 2: 智能路由")
    print("=" * 60)

    orchestrator = get_upgrade_orchestrator()

    # 不同复杂度的任务
    tasks = [
        ("你好", "chat"),
        ("帮我写一个快速排序算法", "code"),
        ("分析这张图片里的内容", "vision"),
        ("设计一个分布式系统架构", "analysis"),
    ]

    for message, task_type in tasks:
        result = await orchestrator.chat_with_smart_upgrade(
            message=message,
            task_type=task_type,
            strategy=RoutingStrategy.ADAPTIVE
        )
        print(f"任务: {task_type:10} -> 模型: {result.provider}/{result.model:20} "
              f"成本: ${result.cost:.6f}")
    print()


async def example_quality_priority():
    """质量优先策略示例"""
    print("=" * 60)
    print("示例 3: 质量优先策略")
    print("=" * 60)

    orchestrator = get_upgrade_orchestrator()

    result = await orchestrator.chat_with_smart_upgrade(
        message="设计一个高并发的微服务架构，考虑容错和扩展性",
        task_type="analysis",
        strategy=RoutingStrategy.QUALITY_FIRST  # 质量优先
    )

    print(f"响应: {result.content[:200]}...")
    print(f"使用模型: {result.provider}/{result.model}")
    print(f"成本: ${result.cost:.6f} (质量优先可能选择更贵的模型)")
    print()


async def example_cost_control():
    """成本控制示例"""
    print("=" * 60)
    print("示例 4: 成本控制")
    print("=" * 60)

    # 创建带预算限制的编排器
    budget = BudgetLimit(
        daily=5.0,      # 日预算 $5
        monthly=50.0,   # 月预算 $50
        per_request=0.02  # 单次请求上限 $0.02
    )

    orchestrator = ModelUpgradeOrchestrator(budget=budget)

    # 检查预算
    can_request, reason = orchestrator.cost_controller.can_make_request()
    print(f"可以请求: {can_request}, 原因: {reason}")

    # 获取优化建议
    suggestions = orchestrator.get_optimization_suggestions()
    print(f"\n优化建议 ({len(suggestions)}条):")
    for suggestion in suggestions:
        print(f"  - [{suggestion['priority']}] {suggestion['message']}")

    # 获取成本报告
    report = orchestrator.get_cost_report(days=7)
    print("\n成本报告摘要:")
    print(f"  总成本: ${report['summary']['total_cost']:.4f}")
    print(f"  日均成本: ${report['summary']['daily_average']:.4f}")
    print()


async def example_fallback():
    """降级策略示例"""
    print("=" * 60)
    print("示例 5: 降级策略")
    print("=" * 60)

    orchestrator = get_upgrade_orchestrator()

    # 获取健康状态
    health = orchestrator.get_health_status()
    print("模型健康状态:")

    fallback_stats = health.get('fallback_manager', {})
    if 'models' in fallback_stats:
        for model, status in fallback_stats['models'].items():
            health_str = "健康" if status['healthy'] else "异常"
            print(f"  - {model}: {health_str}")

    print("\n降级链配置:")
    chains = orchestrator.fallback_manager.get_fallback_chains()
    for task_type, chain in chains.items():
        print(f"  {task_type}:")
        for _level, provider, model in chain.chain[:3]:
            print(f"    -> {provider}/{model}")
    print()


async def example_custom_routing():
    """自定义路由示例"""
    print("=" * 60)
    print("示例 6: 自定义路由策略")
    print("=" * 60)

    orchestrator = get_upgrade_orchestrator()

    # 成本优先
    result_cost = await orchestrator.chat_with_smart_upgrade(
        message="总结一下机器学习的概念",
        task_type="summarize",
        strategy=RoutingStrategy.COST_FIRST
    )
    print(f"成本优先: {result_cost.provider}/{result_cost.model} "
          f"(${result_cost.cost:.6f})")

    # 速度优先
    result_speed = await orchestrator.chat_with_smart_upgrade(
        message="总结一下机器学习的概念",
        task_type="summarize",
        strategy=RoutingStrategy.SPEED_FIRST
    )
    print(f"速度优先: {result_speed.provider}/{result_speed.model} "
          f"({result_speed.latency_ms}ms)")

    # 平衡策略
    result_balanced = await orchestrator.chat_with_smart_upgrade(
        message="总结一下机器学习的概念",
        task_type="summarize",
        strategy=RoutingStrategy.BALANCED
    )
    print(f"平衡策略: {result_balanced.provider}/{result_balanced.model} "
          f"(${result_balanced.cost:.6f}, {result_balanced.latency_ms}ms)")
    print()


def print_cost_comparison():
    """打印成本对比表"""
    print("=" * 60)
    print("成本对比参考")
    print("=" * 60)

    models = [
        ("GPT-4", 0.03, 0.06, "最强通用"),
        ("GPT-4o", 0.005, 0.015, "多模态"),
        ("GPT-4o-mini", 0.00015, 0.0006, "经济型"),
        ("Claude-3-Opus", 0.015, 0.075, "超长上下文"),
        ("Claude-3-Sonnet", 0.003, 0.015, "平衡型"),
        ("Claude-3-Haiku", 0.00025, 0.00125, "快速响应"),
        ("DeepSeek-Chat", 0.00014, 0.00028, "性价比之选"),
        ("Ollama/qwen3:8b", 0.0, 0.0, "本地免费"),
    ]

    print(f"{'模型':<20} {'Input':>10} {'Output':>10} {'特点':<15}")
    print("-" * 60)
    for model, inp, out, feature in models:
        print(f"{model:<20} ${inp:>9.5f} ${out:>9.5f} {feature:<15}")
    print()


async def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("SiliconBase V5 - 模型升级方案示例")
    print("=" * 60 + "\n")

    # 打印成本对比
    print_cost_comparison()

    # 运行示例
    try:
        await example_basic_usage()
    except Exception as e:
        print(f"基础示例跳过 (需要API配置): {e}\n")

    try:
        await example_smart_routing()
    except Exception as e:
        print(f"智能路由示例跳过 (需要API配置): {e}\n")

    try:
        await example_quality_priority()
    except Exception as e:
        print(f"质量优先示例跳过 (需要API配置): {e}\n")

    # 这些示例不需要API调用
    await example_cost_control()
    await example_fallback()
    await example_custom_routing()

    print("=" * 60)
    print("示例运行完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
