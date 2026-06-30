#!/usr/bin/env python3
"""
API注册中心
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
统一管理所有API的注册和挂载状态

使用方式:
    from api import API_REGISTRY, get_api_status, check_api_health

    # 获取所有API状态
    status = get_api_status()

    # 检查健康状态
    health = check_api_health(app)

维护说明:
    - 每次新增API时更新API_REGISTRY
    - 标记必需(required=True)的API
    - 记录未挂载的issue

作者: Kimi Code CLI
日期: 2026-04-13
版本: 1.0
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

# FastAPI 仅在运行时通过 app 参数传入，这里只做可用性标记
FASTAPI_AVAILABLE = False
try:
    import fastapi  # noqa: F401
    FASTAPI_AVAILABLE = True
except ImportError:
    pass


@dataclass
class APIInfo:
    """API信息数据类"""
    name: str
    file: str
    prefix: str
    required: bool
    mounted: bool
    description: str
    issue: str = ""
    cloud_api_line: int = 0  # 在cloud_api.py中的挂载行号


# ═══════════════════════════════════════════════════════════════
# API注册表
# ═══════════════════════════════════════════════════════════════
#
# 【维护说明】
# 1. 新增API时在此添加记录
# 2. 设置required=True表示核心API
# 3. 如果未挂载，在issue字段说明原因
# 4. 定期运行check_api_health()同步mounted状态
#
# ═══════════════════════════════════════════════════════════════

API_REGISTRY: list[APIInfo] = [
    # 核心交易API
    APIInfo(
        name="trading_api",
        file="trading_api.py",
        prefix="/api/trading",
        required=True,
        mounted=True,
        description="交易基础API（币种、K线、价格、持仓）",
        cloud_api_line=3668
    ),
    APIInfo(
        name="trading_mode_api",
        file="trading_mode_api.py",
        prefix="/api/trading/mode",
        required=True,
        mounted=True,  # 2026-04-13 已挂载
        description="方案C三种交易模式管理（全自动/AI辅助/手动）",
        issue="已挂载，功能可用"
    ),
    APIInfo(
        name="exchange_config_api",
        file="exchange_config_api.py",
        prefix="/api/exchange",
        required=True,
        mounted=True,
        description="交易所API密钥管理（OKX/Binance）",
        cloud_api_line=3680
    ),
    APIInfo(
        name="auto_trading_api",
        file="auto_trading_api.py",
        prefix="/api/auto-trading",
        required=True,
        mounted=True,
        description="24小时自动交易调度",
        cloud_api_line=3692
    ),

    # 经验量化API
    APIInfo(
        name="experience_api",
        file="experience_api.py",
        prefix="/api/experience",
        required=False,
        mounted=True,  # 2026-04-13 已挂载
        description="经验量化A/B测试、效果评估、淘汰机制",
        issue="已挂载，ExperienceQuantificationPage可用"
    ),

    # 提示词管理API
    APIInfo(
        name="prompt_api",
        file="prompt_api.py",
        prefix="/api/prompts",
        required=True,
        mounted=True,
        description="提示词管理",
        cloud_api_line=3366
    ),
    APIInfo(
        name="prompt_layer_api",
        file="prompt_layer_api.py",
        prefix="/api/prompt-layers",
        required=True,
        mounted=True,
        description="提示词分层管理",
        cloud_api_line=3374
    ),
    APIInfo(
        name="prompt_variant_api",
        file="prompt_variant_api.py",
        prefix="/api/prompt-variants",
        required=True,
        mounted=True,
        description="提示词变体管理",
        cloud_api_line=3383
    ),

    # 记忆系统API
    APIInfo(
        name="memory_api",
        file="memory_api.py",
        prefix="/api/memories",
        required=True,
        mounted=True,
        description="记忆管理（含可视化、图谱、向量搜索）",
        cloud_api_line=3423
    ),

    # 系统管理API
    APIInfo(
        name="task_api",
        file="task_api.py",
        prefix="/api/tasks",
        required=True,
        mounted=True,
        description="任务管理",
        cloud_api_line=3356
    ),
    APIInfo(
        name="config_api",
        file="config_api.py",
        prefix="/api/config",
        required=True,
        mounted=True,
        description="配置管理",
        cloud_api_line=3415
    ),
    APIInfo(
        name="stats_api",
        file="stats_api.py",
        prefix="/api/stats",
        required=True,
        mounted=True,
        description="统计信息",
        cloud_api_line=3391
    ),
    APIInfo(
        name="metrics_api",
        file="metrics_api.py",
        prefix="/api/metrics",
        required=True,
        mounted=True,
        description="监控指标",
        cloud_api_line=3468
    ),

    # AI能力API
    APIInfo(
        name="ai_config_api",
        file="ai_config_api.py",
        prefix="/api/ai-config",
        required=True,
        mounted=True,
        description="AI模型配置",
        cloud_api_line=3495
    ),
    APIInfo(
        name="features_api",
        file="features_api.py",
        prefix="/api/features",
        required=True,
        mounted=True,
        description="功能开关",
        cloud_api_line=3509
    ),

    # 进阶功能API
    APIInfo(
        name="gamification_api",
        file="gamification_api.py",
        prefix="/api/gamification",
        required=True,
        mounted=True,
        description="游戏化系统",
        cloud_api_line=3476
    ),
    APIInfo(
        name="consciousness_api",
        file="consciousness_api.py",
        prefix="/api/consciousness",
        required=True,
        mounted=True,
        description="意识系统",
        cloud_api_line=3532
    ),
    APIInfo(
        name="three_views_api",
        file="three_views_api.py",
        prefix="/api/three-views",
        required=True,
        mounted=True,
        description="三视图（全局/执行/异常）",
        cloud_api_line=3544
    ),
    APIInfo(
        name="advanced_models_api",
        file="advanced_models_api.py",
        prefix="/api/advanced-models",
        required=True,
        mounted=True,
        description="高级模型",
        cloud_api_line=3556
    ),
    APIInfo(
        name="global_view_api",
        file="global_view_api.py",
        prefix="/api/global-view",
        required=True,
        mounted=True,
        description="磁盘文件扫描可视化",
        cloud_api_line=3720
    ),

    # 工具生态API
    APIInfo(
        name="tools_api",
        file="tools_api.py",
        prefix="/api/tools",
        required=True,
        mounted=True,
        description="工具管理",
        cloud_api_line=3460
    ),
    APIInfo(
        name="tool_market_api",
        file="tool_market_api.py",
        prefix="/api/tool-market",
        required=True,
        mounted=True,
        description="工具市场",
        cloud_api_line=3600
    ),
    APIInfo(
        name="cloud_tool_repo_api",
        file="cloud_tool_repo.py",
        prefix="/api/cloud-tools",
        required=True,
        mounted=True,
        description="云端工具仓库",
        cloud_api_line=3590
    ),

    # 语音交互API
    APIInfo(
        name="voice_api",
        file="voice_api.py",
        prefix="/api/voice",
        required=True,
        mounted=True,
        description="语音合成",
        cloud_api_line=3399
    ),
    APIInfo(
        name="voice_announce_api",
        file="voice_announce_api.py",
        prefix="/api/voice/announce",
        required=True,
        mounted=True,
        description="语音播报",
        cloud_api_line=3407
    ),

    # 其他功能API
    APIInfo(
        name="silicon_life_api",
        file="silicon_life_api.py",
        prefix="/api/silicon-life",
        required=True,
        mounted=True,
        description="硅基生命成长监控",
        cloud_api_line=3656
    ),
    APIInfo(
        name="session_api",
        file="session_api.py",
        prefix="/api/sessions",
        required=True,
        mounted=True,
        description="会话管理",
        cloud_api_line=3705
    ),
    APIInfo(
        name="workflow_api",
        file="workflow_api.py",
        prefix="/api/workflows",
        required=True,
        mounted=True,
        description="工作流管理",
        cloud_api_line=3757
    ),
    APIInfo(
        name="procedure_learning_api",
        file="procedure_learning_api.py",
        prefix="/api/procedures",
        required=True,
        mounted=True,
        description="程序学习",
        cloud_api_line=3773
    ),
    # 【已废弃】checkpoint_api.py 已删除，功能合并至 task_api.py
    APIInfo(
        name="rlhf_api",
        file="api/routes/rlhf.py",
        prefix="/api/rlhf",
        required=True,
        mounted=True,
        description="RLHF训练（从routes目录导入）",
        cloud_api_line=3644
    ),
    APIInfo(
        name="cost_api",
        file="cost_api.py",
        prefix="/api/costs",
        required=True,
        mounted=True,
        description="成本管理",
        cloud_api_line=3613
    ),
    APIInfo(
        name="sync_api",
        file="sync_api.py",
        prefix="/api/sync",
        required=True,
        mounted=True,
        description="数据同步",
        cloud_api_line=3580
    ),
    APIInfo(
        name="template_experiment_api",
        file="template_experiment_api.py",
        prefix="/api/templates",
        required=True,
        mounted=True,
        description="模板实验",
        cloud_api_line=3568
    ),
    APIInfo(
        name="interrupt_api",
        file="interrupt_api.py",
        prefix="/api/sessions",
        required=True,
        mounted=True,
        description="会话中断管理",
        cloud_api_line=3744
    ),
]


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def get_api_status() -> list[APIInfo]:
    """
    获取所有API的注册信息

    Returns:
        List[APIInfo]: API信息列表
    """
    return API_REGISTRY.copy()


def get_mounted_apis() -> list[APIInfo]:
    """获取已挂载的API列表"""
    return [api for api in API_REGISTRY if api.mounted]


def get_unmounted_apis() -> list[APIInfo]:
    """获取未挂载的API列表"""
    return [api for api in API_REGISTRY if not api.mounted]


def get_required_unmounted_apis() -> list[APIInfo]:
    """获取必需但未挂载的API列表"""
    return [api for api in API_REGISTRY if api.required and not api.mounted]


def get_api_by_name(name: str) -> APIInfo | None:
    """根据名称获取API信息"""
    for api in API_REGISTRY:
        if api.name == name:
            return api
    return None


def get_api_by_prefix(prefix: str) -> APIInfo | None:
    """根据路由前缀获取API信息"""
    for api in API_REGISTRY:
        if api.prefix == prefix:
            return api
    return None


def check_api_health(app: Any = None) -> dict[str, Any]:
    """
    检查API健康状态

    Args:
        app: FastAPI应用实例（可选）

    Returns:
        Dict: 健康检查结果
    """
    result = {
        "timestamp": datetime.now().isoformat(),
        "total": len(API_REGISTRY),
        "mounted": 0,
        "unmounted": 0,
        "required_unmounted": 0,
        "issues": [],
        "apis": []
    }

    # 获取所有路由路径（如果提供了app）
    mounted_routes = set()
    if app and FASTAPI_AVAILABLE:
        for route in app.routes:
            if hasattr(route, 'path'):
                mounted_routes.add(route.path)

    for api in API_REGISTRY:
        # 检查是否实际挂载（如果提供了app）
        if mounted_routes:
            # 检查是否有路由匹配前缀
            api.mounted = any(
                route.startswith(api.prefix) or api.prefix.startswith(route.rstrip('/'))
                for route in mounted_routes if route != '/'
            )

        status = {
            "name": api.name,
            "prefix": api.prefix,
            "mounted": api.mounted,
            "required": api.required,
            "description": api.description
        }
        result["apis"].append(status)

        if api.mounted:
            result["mounted"] += 1
        else:
            result["unmounted"] += 1
            if api.required:
                result["required_unmounted"] += 1
                result["issues"].append({
                    "api": api.name,
                    "prefix": api.prefix,
                    "issue": api.issue or "[MISSING] 未挂载",
                    "action": f"在cloud_api.py中挂载 {api.file}"
                })

    return result


def generate_api_manifest() -> str:
    """
    生成API清单Markdown

    Returns:
        str: Markdown格式的API清单
    """
    lines = [
        "# API挂载状态清单",
        "",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**API总数**: {len(API_REGISTRY)}",
        "",
        "| API名称 | 路由前缀 | 必需 | 状态 | 说明 |",
        "|---------|----------|------|------|------|"
    ]

    # 先显示未挂载的（红色警告）
    for api in API_REGISTRY:
        if not api.mounted:
            status = "[MISSING] 未挂载"
            req = "是" if api.required else "否"
            lines.append(f"| {api.name} | {api.prefix} | {req} | **{status}** | {api.description} |")

    # 再显示已挂载的
    for api in API_REGISTRY:
        if api.mounted:
            status = "[OK] 正常"
            req = "是" if api.required else "否"
            lines.append(f"| {api.name} | {api.prefix} | {req} | {status} | {api.description} |")

    # 添加问题汇总
    issues = [api for api in API_REGISTRY if api.required and not api.mounted]
    if issues:
        lines.extend([
            "",
            "## [WARNING] 需要关注的问题",
            "",
            "以下API是必需的但未挂载：",
            ""
        ])
        for api in issues:
            lines.append(f"- **{api.name}**: {api.issue or '未挂载'}")

    return "\n".join(lines)


def print_api_status():
    """打印API状态到控制台"""
    print("=" * 80)
    print("API注册中心 - 状态报告".center(80))
    print("=" * 80)
    print()

    mounted = sum(1 for api in API_REGISTRY if api.mounted)
    unmounted = sum(1 for api in API_REGISTRY if not api.mounted)
    required_unmounted = sum(1 for api in API_REGISTRY if api.required and not api.mounted)

    print(f"总API数: {len(API_REGISTRY)}")
    print(f"已挂载: {mounted} [OK]")
    print(f"未挂载: {unmounted} [MISSING]")
    print()

    if required_unmounted > 0:
        print(f"[!] 警告: 有 {required_unmounted} 个必需API未挂载！")
        print()
        print("需要修复的API:")
        for api in API_REGISTRY:
            if api.required and not api.mounted:
                print(f"  - {api.name}: {api.prefix}")
                print(f"    说明: {api.issue or '未挂载'}")
        print()
    else:
        print("[OK] 所有必需API已正常挂载")
        print()

    print("详细清单:")
    print("-" * 80)
    for api in API_REGISTRY:
        status = "[OK]" if api.mounted else "[MISSING]"
        req = "[必需]" if api.required else "[可选]"
        print(f"{status} {api.name:30} {api.prefix:25} {req}")
    print()
    print("=" * 80)


# ═══════════════════════════════════════════════════════════════
# 直接运行时的输出
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print_api_status()
    print()
    print("生成API清单Markdown:")
    print("-" * 80)
    print(generate_api_manifest())
