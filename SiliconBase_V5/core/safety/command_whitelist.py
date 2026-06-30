#!/usr/bin/env python3
"""
统一命令白名单
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

治理目标：消灭分散在 shell_execute.py 和 process_start.py 中的重复白名单。
所有命令权限统一在此维护，按类别分组，各工具按需引用。

使用方式：
    from core.safety.command_whitelist import COMMAND_WHITELIST, get_commands_for_scope

    # shell_execute 允许：开发工具 + 系统工具 + 网络工具
    allowed = get_commands_for_scope("shell_execute")

    # process_start 允许：开发工具 + 浏览器 + GUI工具
    allowed = get_commands_for_scope("process_start")
"""


COMMAND_WHITELIST: dict[str, set[str]] = {
    "development": {
        'python', 'python3', 'python.exe', 'python3.exe', 'pythonw.exe',
        'pip', 'pip3', 'pip.exe', 'pip3.exe',
        'node', 'node.exe', 'npm', 'npm.cmd', 'npm.exe', 'npx', 'npx.exe',
        'git', 'git.exe',
        'code', 'code.cmd', 'code.exe',
    },
    "container": {
        'docker', 'docker.exe', 'docker-compose', 'docker-compose.exe',
    },
    "shell": {
        'cmd', 'cmd.exe',
        'powershell', 'powershell.exe', 'pwsh', 'pwsh.exe',
        'bash', 'sh', 'zsh',
    },
    "system": {
        'ping', 'ping.exe', 'tracert', 'tracert.exe',
        'ipconfig', 'ipconfig.exe', 'ifconfig',
        'netstat', 'netstat.exe',
        'tasklist', 'tasklist.exe', 'ps',
        'dir', 'echo', 'type', 'findstr', 'cd', 'mkdir', 'rmdir', 'del', 'copy', 'move',
        'ls', 'cat', 'grep', 'find', 'pwd', 'touch', 'cp', 'mv', 'rm', 'chmod', 'chown',
        'exit', 'cls', 'clear', 'whoami', 'date', 'time',
    },
    "network": {
        'curl', 'curl.exe', 'wget', 'wget.exe',
    },
    "browser": {
        'chrome', 'chrome.exe', 'chromium', 'chromium.exe',
        'firefox', 'firefox.exe',
        'msedge', 'msedge.exe', 'edge.exe',
        'safari', 'safari.exe',
    },
    "gui": {
        'notepad', 'notepad.exe',
        'calc', 'calc.exe', 'calculator', 'calculator.exe',
        'mspaint', 'mspaint.exe',
        'explorer', 'explorer.exe',
    },
    "editor": {
        'notepad', 'notepad.exe',
        'code', 'code.exe', 'code.cmd',
        'vim', 'vi', 'nano',
    },
}


# 各工具的权限范围：{tool_name: [category_names]}
TOOL_COMMAND_SCOPES: dict[str, list[str]] = {
    "shell_execute": [
        "development", "container", "shell", "system", "network"
    ],
    "process_start": [
        "development", "container", "shell", "browser", "gui", "editor", "network"
    ],
}


def get_commands_for_scope(tool_name: str) -> set[str]:
    """
    获取指定工具允许使用的命令集合

    Args:
        tool_name: 工具名称（如 "shell_execute"）

    Returns:
        Set[str]: 允许的命令集合
    """
    categories = TOOL_COMMAND_SCOPES.get(tool_name, [])
    allowed: set[str] = set()
    for cat in categories:
        allowed.update(COMMAND_WHITELIST.get(cat, set()))
    return allowed


def is_command_allowed(command: str, tool_name: str) -> bool:
    """
    检查命令是否允许在指定工具中使用

    Args:
        command: 命令名称
        tool_name: 工具名称

    Returns:
        bool
    """
    allowed = get_commands_for_scope(tool_name)
    return command.lower() in {c.lower() for c in allowed}


def get_command_categories() -> dict[str, list[str]]:
    """
    获取所有命令分类（用于前端展示或日志）

    Returns:
        Dict[str, List[str]]: {category: [commands]}
    """
    return {
        cat: sorted(cmds)
        for cat, cmds in COMMAND_WHITELIST.items()
    }


def add_command_to_category(category: str, command: str) -> None:
    """
    动态添加命令到白名单（用于运行时扩展）

    Args:
        category: 分类名称
        command: 命令名称
    """
    if category not in COMMAND_WHITELIST:
        COMMAND_WHITELIST[category] = set()
    COMMAND_WHITELIST[category].add(command)
