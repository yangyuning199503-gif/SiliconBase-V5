#!/usr/bin/env python3
"""
MCP + 子代理系统初始化脚本

使用方法：
    python init_mcp_subagent.py

或者在其他地方导入：
    from init_mcp_subagent import initialize_mcp_subagent
    await initialize_mcp_subagent()
"""

import asyncio
import os
import sys
from typing import Any

import aiofiles
import yaml

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.tool_manager_v2 import tool_manager

from core.logger import logger
from core.subagent import subagent_manager
from core.subagent.config import SubAgentConfig


async def initialize_mcp(
    config_path: str = "config/mcp_servers.yaml",
    selective_servers: list = None,
    auto_enable: bool = True
) -> dict[str, Any]:
    """
    初始化 MCP 系统

    Args:
        config_path: MCP 配置文件路径
        selective_servers: 选择性启用的服务器名称列表（None 表示启用所有 enabled=true 的）
        auto_enable: 是否自动启用 MCP

    Returns:
        初始化结果
    """
    result = {
        "success": False,
        "servers_connected": 0,
        "tools_added": 0,
        "errors": []
    }

    if not auto_enable:
        logger.info("[Init] MCP 自动启用已关闭")
        return result

    # 检查配置文件
    if not os.path.exists(config_path):
        logger.warning(f"[Init] MCP 配置文件不存在: {config_path}")
        result["errors"].append(f"Config file not found: {config_path}")
        return result

    try:
        # 加载配置
        async with aiofiles.open(config_path, encoding='utf-8') as f:
            content = await f.read()
            config = yaml.safe_load(content)

        servers_config = config.get("mcp_servers", [])

        # 筛选服务器
        if selective_servers:
            servers_config = [
                cfg for cfg in servers_config
                if cfg.get("name") in selective_servers
            ]
        else:
            # 只启用配置中 enabled=true 的
            servers_config = [
                cfg for cfg in servers_config
                if cfg.get("enabled", False)
            ]

        if not servers_config:
            logger.info("[Init] 没有需要启用的 MCP 服务器")
            return result

        # 启用 MCP
        logger.info(f"[Init] 正在启用 {len(servers_config)} 个 MCP 服务器...")
        connect_results = await tool_manager.enable_mcp(servers_config)

        # 统计结果
        success_count = sum(1 for v in connect_results.values() if v)

        result["success"] = success_count > 0
        result["servers_connected"] = success_count
        result["connection_details"] = connect_results

        if tool_manager.is_mcp_enabled():
            mcp_status = tool_manager.get_mcp_status()
            result["tools_added"] = mcp_status.get("tools_count", 0)

            logger.info(f"[Init] MCP 初始化完成: {success_count} 个服务器, "
                       f"{result['tools_added']} 个工具")
        else:
            logger.warning("[Init] MCP 未能成功启用")

    except Exception as e:
        logger.error(f"[Init] MCP 初始化失败: {e}")
        result["errors"].append(str(e))

    return result


async def initialize_subagent(
    config_path: str = "config/subagents.yaml",
    auto_register: bool = True
) -> dict[str, Any]:
    """
    初始化子代理系统

    Args:
        config_path: 子代理配置文件路径
        auto_register: 是否自动注册配置中的代理

    Returns:
        初始化结果
    """
    result = {
        "success": True,
        "agents_registered": 0,
        "errors": []
    }

    # 预设代理已自动加载
    preset_count = len(subagent_manager.list_agents())
    logger.info(f"[Init] 预设子代理已加载: {preset_count} 个")

    if not auto_register:
        return result

    # 检查配置文件
    if not os.path.exists(config_path):
        logger.warning(f"[Init] 子代理配置文件不存在: {config_path}")
        return result

    try:
        # 加载配置
        async with aiofiles.open(config_path, encoding='utf-8') as f:
            content = await f.read()
            config = yaml.safe_load(content)

        agents_config = config.get("subagents", [])

        # 注册代理
        for agent_data in agents_config:
            try:
                cfg = SubAgentConfig.from_dict(agent_data)

                # 避免重复注册
                if subagent_manager.is_registered(cfg.name):
                    logger.debug(f"[Init] 子代理已存在: {cfg.name}")
                    continue

                subagent_manager.register(cfg)
                result["agents_registered"] += 1
                logger.info(f"[Init] 注册子代理: {cfg.name}")

            except Exception as e:
                logger.error(f"[Init] 注册子代理失败 {agent_data.get('name', 'unknown')}: {e}")
                result["errors"].append(f"{agent_data.get('name')}: {e}")

        total_agents = len(subagent_manager.list_agents())
        logger.info(f"[Init] 子代理初始化完成: 共 {total_agents} 个代理")

    except Exception as e:
        logger.error(f"[Init] 子代理初始化失败: {e}")
        result["errors"].append(str(e))
        result["success"] = False

    return result


async def initialize_mcp_subagent(
    mcp_config_path: str = "config/mcp_servers.yaml",
    subagent_config_path: str = "config/subagents.yaml",
    enable_mcp: bool = True,
    enable_subagent: bool = True,
    selective_mcp_servers: list = None
) -> dict[str, Any]:
    """
    完整初始化 MCP + 子代理系统

    这是主要的初始化函数，通常在应用启动时调用。

    Args:
        mcp_config_path: MCP 配置文件路径
        subagent_config_path: 子代理配置文件路径
        enable_mcp: 是否启用 MCP
        enable_subagent: 是否启用子代理
        selective_mcp_servers: 选择性启用的 MCP 服务器

    Returns:
        完整的初始化结果

    Example:
        result = await initialize_mcp_subagent(
            enable_mcp=True,
            enable_subagent=True,
            selective_mcp_servers=["filesystem"]  # 只启用 filesystem
        )

        if result["mcp"]["success"]:
            print(f"MCP 已启用，{result['mcp']['tools_added']} 个工具")

        if result["subagent"]["success"]:
            print(f"子代理已加载，{result['subagent']['agents_registered']} 个配置")
    """
    print("=" * 70)
    print("初始化 MCP + 子代理系统")
    print("=" * 70)

    result = {
        "mcp": {"success": False},
        "subagent": {"success": False},
        "overall_success": False
    }

    # 初始化 MCP
    if enable_mcp:
        print("\n[1/2] 初始化 MCP...")
        mcp_result = await initialize_mcp(
            config_path=mcp_config_path,
            selective_servers=selective_mcp_servers,
            auto_enable=True
        )
        result["mcp"] = mcp_result

        if mcp_result["success"]:
            print(f"  ✅ MCP 已启用: {mcp_result['servers_connected']} 个服务器, "
                  f"{mcp_result['tools_added']} 个工具")
        else:
            print("  ⚠️ MCP 未启用（非关键）")
            if mcp_result["errors"]:
                print(f"     错误: {mcp_result['errors']}")
    else:
        print("\n[1/2] MCP 已禁用")

    # 初始化子代理
    if enable_subagent:
        print("\n[2/2] 初始化子代理...")
        subagent_result = await initialize_subagent(
            config_path=subagent_config_path,
            auto_register=True
        )
        result["subagent"] = subagent_result

        if subagent_result["success"]:
            total_agents = len(subagent_manager.list_agents())
            print(f"  ✅ 子代理已加载: {subagent_result['agents_registered']} 个新配置, "
                  f"共 {total_agents} 个代理")
        else:
            print("  ⚠️ 子代理初始化失败")
    else:
        print("\n[2/2] 子代理已禁用")

    # 总体状态
    result["overall_success"] = True  # 部分失败不影响整体

    print("\n" + "=" * 70)
    print("初始化完成")
    print("=" * 70)

    return result


def initialize_sync(
    mcp_config_path: str = "config/mcp_servers.yaml",
    subagent_config_path: str = "config/subagents.yaml",
    enable_mcp: bool = True,
    enable_subagent: bool = True
) -> dict[str, Any]:
    """
    同步版本的初始化函数

    用于非异步环境
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 如果事件循环已在运行，创建新任务
            future = asyncio.run_coroutine_threadsafe(
                initialize_mcp_subagent(
                    mcp_config_path=mcp_config_path,
                    subagent_config_path=subagent_config_path,
                    enable_mcp=enable_mcp,
                    enable_subagent=enable_subagent
                ),
                loop
            )
            return future.result()
        else:
            return loop.run_until_complete(
                initialize_mcp_subagent(
                    mcp_config_path=mcp_config_path,
                    subagent_config_path=subagent_config_path,
                    enable_mcp=enable_mcp,
                    enable_subagent=enable_subagent
                )
            )
    except RuntimeError:
        # 没有事件循环
        return asyncio.run(
            initialize_mcp_subagent(
                mcp_config_path=mcp_config_path,
                subagent_config_path=subagent_config_path,
                enable_mcp=enable_mcp,
                enable_subagent=enable_subagent
            )
        )


# 命令行入口
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="初始化 MCP + 子代理系统")
    parser.add_argument("--no-mcp", action="store_true", help="禁用 MCP")
    parser.add_argument("--no-subagent", action="store_true", help="禁用子代理")
    parser.add_argument("--mcp-config", default="config/mcp_servers.yaml", help="MCP 配置文件")
    parser.add_argument("--subagent-config", default="config/subagents.yaml", help="子代理配置文件")
    parser.add_argument("--mcp-servers", nargs="+", help="选择性启用的 MCP 服务器")

    args = parser.parse_args()

    # 运行初始化
    result = asyncio.run(initialize_mcp_subagent(
        mcp_config_path=args.mcp_config,
        subagent_config_path=args.subagent_config,
        enable_mcp=not args.no_mcp,
        enable_subagent=not args.no_subagent,
        selective_mcp_servers=args.mcp_servers
    ))

    # 输出结果摘要
    print("\n结果摘要:")
    print(f"  MCP: {'成功' if result['mcp']['success'] else '未启用/失败'}")
    print(f"  子代理: {'成功' if result['subagent']['success'] else '失败'}")
