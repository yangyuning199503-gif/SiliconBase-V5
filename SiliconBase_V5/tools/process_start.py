#!/usr/bin/env python3
"""
原子工具：启动进程
安全加固版本 - 修复命令注入风险 (TOOL-002)
"""
import os
import re
import shutil
import subprocess
from typing import Any

from core.base_tool import BaseTool
from core.error_codes import FILE_NOT_FOUND, INVALID_PARAMS, TOOL_EXECUTION_ERROR, format_error

# ============================================================================
# 安全配置
# ============================================================================

# 【治理】统一命令白名单：从 core.safety.command_whitelist 获取
# 不再在此文件中维护独立的白名单列表
try:
    from core.safety.command_whitelist import get_commands_for_scope
    ALLOWED_COMMANDS = get_commands_for_scope("process_start")
except ImportError:
    # 兜底：如果统一白名单模块未加载，使用精简默认列表
    ALLOWED_COMMANDS = {
        'python', 'python3', 'node', 'npm', 'git', 'docker',
        'notepad', 'calc', 'chrome', 'firefox', 'msedge',
        'cmd', 'powershell', 'explorer',
        'ping', 'ipconfig',
    }

# 危险字符模式：禁止在参数中出现的危险字符
# 包括：命令分隔符、管道、重定向、变量扩展、命令替换等
DANGEROUS_CHARS = re.compile(r'[;&|`$(){}[\]\\<>!]')

# 路径遍历模式
PATH_TRAVERSAL_PATTERN = re.compile(r'\.\.|^/|^\\\\|^[a-zA-Z]:\\\\\.\.|~')

# 默认超时时间（秒）
DEFAULT_TIMEOUT = 300
MAX_TIMEOUT = 3600  # 最大允许1小时


# ============================================================================
# 安全验证函数
# ============================================================================

def validate_command(cmd: str) -> tuple[bool, str]:
    """
    验证命令在白名单中

    Returns:
        (is_valid, error_message)
    """
    if not cmd:
        return False, "命令不能为空"

    if not isinstance(cmd, str):
        return False, "命令必须是字符串"

    # 检查命令长度
    if len(cmd) > 1024:
        return False, "命令长度超过限制"

    cmd_name = os.path.basename(cmd.strip())

    # 去除可能的扩展名再检查
    cmd_base = cmd_name
    if cmd_name.lower().endswith('.exe') or cmd_name.lower().endswith('.cmd') or cmd_name.lower().endswith('.bat'):
        cmd_base = cmd_name[:-4]

    # 检查是否在白名单中
    if cmd_name.lower() in {c.lower() for c in ALLOWED_COMMANDS}:
        return True, ""
    if cmd_base.lower() in {c.lower() for c in ALLOWED_COMMANDS}:
        return True, ""

    return False, f"命令 '{cmd}' 不在允许的白名单中"


def validate_args(args: list[str]) -> tuple[bool, str]:
    """
    验证参数不包含危险字符

    Returns:
        (is_valid, error_message)
    """
    if not isinstance(args, list):
        return False, "参数必须是列表"

    for i, arg in enumerate(args):
        if not isinstance(arg, (str, int, float)):
            return False, f"参数[{i}]类型无效，必须是字符串或数字"

        arg_str = str(arg)

        # 检查参数长度
        if len(arg_str) > 8192:
            return False, f"参数[{i}]长度超过限制"

        # 检查危险字符
        if DANGEROUS_CHARS.search(arg_str):
            return False, f"参数[{i}]包含危险字符"

        # 检查潜在的命令注入
        if any(dangerous in arg_str.lower() for dangerous in [
            '&&', '||', '`', '$(', '${', '%', '!', '|'
        ]):
            return False, f"参数[{i}]包含潜在的命令注入模式"

    return True, ""


def validate_cwd(cwd: str | None) -> tuple[bool, str]:
    """
    验证工作目录路径

    Returns:
        (is_valid, error_message)
    """
    if cwd is None:
        return True, ""

    if not isinstance(cwd, str):
        return False, "工作目录必须是字符串"

    # 检查路径长度
    if len(cwd) > 4096:
        return False, "工作目录路径过长"

    # 检查路径遍历
    if '..' in cwd:
        return False, "工作目录包含路径遍历(..)"

    # 检查危险字符
    if DANGEROUS_CHARS.search(cwd):
        return False, "工作目录包含危险字符"

    # 检查是否是绝对路径
    try:
        os.path.abspath(cwd)
        # 允许在当前目录下的路径
        return True, ""
    except Exception as e:
        return False, f"工作目录路径无效: {e}"

    return True, ""


def validate_timeout(timeout: int | None) -> tuple[bool, int, str]:
    """
    验证超时时间

    Returns:
        (is_valid, validated_timeout, error_message)
    """
    if timeout is None:
        return True, DEFAULT_TIMEOUT, ""

    if not isinstance(timeout, (int, float)):
        return False, DEFAULT_TIMEOUT, "超时时间必须是数字"

    timeout_int = int(timeout)

    if timeout_int < 0:
        return False, DEFAULT_TIMEOUT, "超时时间不能为负数"

    if timeout_int > MAX_TIMEOUT:
        return False, DEFAULT_TIMEOUT, f"超时时间不能超过 {MAX_TIMEOUT} 秒"

    return True, timeout_int, ""


def resolve_executable(executable: str) -> tuple[bool, str, str]:
    """
    解析可执行文件路径

    Returns:
        (is_valid, resolved_path, error_message)
    """
    # 如果路径已存在，直接返回
    if os.path.isfile(executable) and (os.access(executable, os.X_OK) or executable.lower().endswith(('.exe', '.bat', '.cmd'))):
        return True, executable, ""

    # 尝试添加 .exe 后缀
    if not executable.lower().endswith('.exe'):
        executable_exe = executable + '.exe'
        if os.path.isfile(executable_exe):
            return True, executable_exe, ""

    # 使用 shutil.which 查找命令
    resolved = shutil.which(executable)
    if resolved:
        return True, resolved, ""

    return False, executable, f"找不到可执行文件: {executable}"


# ============================================================================
# 主工具类
# ============================================================================

class ProcessStart(BaseTool):
    tool_id = "process_start"
    name = "启动进程"
    description = "启动可执行文件 (安全加固版本)"
    input_schema = {
        "type": "object",
        "properties": {
            "executable": {
                "type": "string",
                "description": "要执行的可执行文件路径或命令名"
            },
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "传递给可执行文件的参数列表"
            },
            "cwd": {
                "type": "string",
                "description": "工作目录（可选）"
            },
            "timeout": {
                "type": "integer",
                "description": f"进程运行超时时间（秒），默认{DEFAULT_TIMEOUT}秒，最大{MAX_TIMEOUT}秒"
            },
            "env": {
                "type": "object",
                "description": "环境变量字典（可选）"
            },
            "wait": {
                "type": "boolean",
                "description": "是否等待进程完成（默认False，异步启动）"
            }
        },
        "required": ["executable"]
    }

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        """异步执行：将同步 _execute 桥接到线程池，避免阻塞事件循环。"""
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._execute(**kwargs))

    def _execute(self, **kwargs) -> dict[str, Any]:
        """
        安全地启动进程

        Args:
            executable: 可执行文件路径或命令名
            args: 参数列表
            cwd: 工作目录
            timeout: 超时时间（秒）
            env: 环境变量
            wait: 是否等待进程完成

        Returns:
            包含执行结果的字典
        """
        executable = kwargs.get("executable", "")
        args = kwargs.get("args", [])
        cwd = kwargs.get("cwd")
        timeout = kwargs.get("timeout")
        env = kwargs.get("env")
        wait = kwargs.get("wait", False)

        # ============ 输入验证 ============

        if not executable:
            return format_error(INVALID_PARAMS, detail="executable 不能为空")

        # 验证命令在白名单中
        is_valid, error_msg = validate_command(executable)
        if not is_valid:
            allowed_list = ', '.join(sorted(ALLOWED_COMMANDS))
            return format_error(
                INVALID_PARAMS,
                detail=f"{error_msg}。允许的命令: {allowed_list}"
            )

        # 验证参数
        is_valid, error_msg = validate_args(args)
        if not is_valid:
            return format_error(INVALID_PARAMS, detail=f"参数验证失败: {error_msg}")

        # 验证工作目录
        is_valid, error_msg = validate_cwd(cwd)
        if not is_valid:
            return format_error(INVALID_PARAMS, detail=f"工作目录验证失败: {error_msg}")

        # 验证超时时间
        is_valid, validated_timeout, error_msg = validate_timeout(timeout)
        if not is_valid:
            return format_error(INVALID_PARAMS, detail=f"超时时间验证失败: {error_msg}")
        timeout = validated_timeout

        # ============ 路径解析 ============

        is_valid, resolved_executable, error_msg = resolve_executable(executable)
        if not is_valid:
            return format_error(FILE_NOT_FOUND, detail=error_msg)

        # ============ 环境变量处理 ============

        process_env = None
        if env:
            if not isinstance(env, dict):
                return format_error(INVALID_PARAMS, detail="env 必须是字典类型")
            # 复制当前环境并更新
            process_env = os.environ.copy()
            # 安全过滤：只允许特定的环境变量
            allowed_env_prefixes = ('PATH', 'PYTHON', 'NODE', 'HOME', 'USER', 'TMP', 'TEMP')
            for key, value in env.items():
                if (key.startswith(allowed_env_prefixes) or key in ['LANG', 'LC_ALL']) and isinstance(value, str) and not DANGEROUS_CHARS.search(value):
                    process_env[key] = value

        # ============ 启动进程 ============

        try:
            # 构建命令列表 - 使用列表形式而非字符串，避免 shell=True
            # 这是防止命令注入的关键！
            cmd_list = [resolved_executable] + [str(arg) for arg in args]

            # 验证构建的命令列表
            for cmd_part in cmd_list:
                if not isinstance(cmd_part, str):
                    return format_error(INVALID_PARAMS, detail="命令部分必须是字符串")

            # 准备启动参数
            popen_kwargs = {
                'shell': False,  # 关键安全设置：禁用 shell
            }

            if cwd:
                popen_kwargs['cwd'] = cwd

            if process_env:
                popen_kwargs['env'] = process_env

            # 启动进程
            proc = subprocess.Popen(cmd_list, **popen_kwargs)

            # 如果需要等待进程完成
            if wait:
                try:
                    stdout, stderr = proc.communicate(timeout=timeout)
                    return {
                        "success": True,
                        "data": {
                            "pid": proc.pid,
                            "returncode": proc.returncode,
                            "message": f"进程已完成，PID: {proc.pid}, 返回码: {proc.returncode}"
                        }
                    }
                except subprocess.TimeoutExpired:
                    # 超时，终止进程
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    return format_error(
                        TOOL_EXECUTION_ERROR,
                        detail=f"进程执行超时（{timeout}秒），已终止"
                    )
            else:
                # 异步启动
                return {
                    "success": True,
                    "error_code": None,
                    "user_message": f"进程已启动，PID: {proc.pid}",
                    "data": {
                        "pid": proc.pid
                    }
                }

        except FileNotFoundError:
            return format_error(FILE_NOT_FOUND, detail=f"找不到可执行文件: {executable}")
        except PermissionError:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"没有权限执行: {executable}")
        except OSError as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"系统错误: {e}")
        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"启动进程失败: {e}")


# 兼容性：保持原有函数接口
def process_start(executable: str, args: list[str] | None = None,
                  cwd: str | None = None, timeout: int | None = None,
                  env: dict[str, str] | None = None,
                  wait: bool = False) -> dict[str, Any]:
    """
    函数式接口，保持向后兼容
    """
    tool = ProcessStart()
    return tool.run(
        executable=executable,
        args=args or [],
        cwd=cwd,
        timeout=timeout,
        env=env,
        wait=wait
    )
