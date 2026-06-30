#!/usr/bin/env python3
"""
插件系统 - SiliconBase V5
支持动态加载、安全管理、热重载的插件架构
"""

import ast
import importlib.util
import inspect
import re
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.logger import logger
from core.tool.base_tool import BaseTool


@dataclass
class PluginInfo:
    """插件信息"""
    id: str
    name: str
    version: str
    description: str
    author: str
    file_path: str
    tools: list[str]
    status: str
    error_msg: str = ""
    loaded_at: float | None = None

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'version': self.version,
            'description': self.description,
            'author': self.author,
            'file_path': self.file_path,
            'tools': self.tools,
            'status': self.status,
            'error_msg': self.error_msg,
            'loaded_at': self.loaded_at
        }


class CodeSecurityChecker:
    """代码安全检查器"""


    DANGEROUS_PATTERNS = [
        r'import\s+os\.system',
        r'os\.system\s*\(',
        r'subprocess\.call\s*\([^)]*shell\s*=\s*True',
        r'eval\s*\(',
        r'exec\s*\(',
        r'__import__\s*\(',
        r'importlib\.import_module',
        r'open\s*\([^)]*,\s*["\']w',
        r'rm\s+-rf',
        r'del\s+__builtins__',
        r'ctypes\.windll',
        r'ctypes\.cdll',
        r'socket\.socket',
    ]


    ALLOWED_IMPORTS = {
        'os', 'sys', 'json', 're', 'time', 'datetime', 'pathlib', 'typing',
        'math', 'random', 'string', 'collections', 'itertools', 'functools',
        'hashlib', 'base64', 'urllib', 'http', 'requests',
        'numpy', 'pandas', 'PIL', 'cv2', 'pyautogui', 'psutil',
        'core.base_tool', 'core.logger', 'core.config', 'core.error_codes',
        'core.tool_manager'
    }

    def check(self, code: str) -> tuple[bool, str]:
        """
        检查代码安全性

        Returns:
            (是否安全, 错误信息)
        """

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f"语法错误: {e}"


        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, code, re.IGNORECASE):
                return False, f"检测到危险代码模式: {pattern}"


        checker = ASTSecurityChecker(self.ALLOWED_IMPORTS)
        checker.visit(tree)
        if checker.violations:
            return False, f"安全检查失败: {'; '.join(checker.violations[:3])}"

        return True, "检查通过"


class ASTSecurityChecker(ast.NodeVisitor):
    """AST安全检查器"""

    def __init__(self, allowed_imports: set | None = None):
        self.allowed_imports = allowed_imports
        self.violations = []

    def _is_allowed(self, module_name: str) -> bool:
        """检查模块是否被允许导入"""
        if not self.allowed_imports:
            return True

        if module_name in self.allowed_imports:
            return True

        parts = module_name.split('.')
        base_module = parts[0]

        if base_module == 'core':
            return True

        return base_module in self.allowed_imports

    def visit_Import(self, node):
        if self.allowed_imports:
            for alias in node.names:
                if not self._is_allowed(alias.name):
                    self.violations.append(f"禁止导入模块: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if self.allowed_imports and node.module and not self._is_allowed(node.module):
            self.violations.append(f"禁止从模块导入: {node.module}")
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id in ('eval', 'exec', '__import__'):
            self.violations.append(f"禁止调用函数: {node.func.id}")
        self.generic_visit(node)


class PluginManager:
    """插件管理器"""

    def __init__(self):
        self.plugins_dir = Path("plugins")
        self.plugins_dir.mkdir(parents=True, exist_ok=True)


        self.disabled_dir = Path("plugins/disabled")
        self.disabled_dir.mkdir(parents=True, exist_ok=True)


        self.backup_dir = Path("plugins/backup")
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        self._plugins: dict[str, PluginInfo] = {}
        self._loaded_tools: dict[str, BaseTool] = {}
        self._hooks: dict[str, list[Callable]] = {}
        self.security_checker = CodeSecurityChecker()


        self._load_all_plugins()

    def _load_all_plugins(self):
        """加载所有插件"""
        for plugin_file in self.plugins_dir.rglob("*.py"):
            if plugin_file.name.startswith('_'):
                continue
            self._load_plugin(plugin_file)

    def _load_plugin(self, file_path: Path) -> bool:
        """加载单个插件"""
        plugin_id = file_path.stem


        if plugin_id in self._plugins and self._plugins[plugin_id].status == "active":
            return True

        try:

            with open(file_path, encoding='utf-8') as f:
                code = f.read()


            is_safe, reason = self.security_checker.check(code)
            if not is_safe:
                logger.error(f"[Plugin] 插件 {plugin_id} 未通过安全检查: {reason}")
                self._plugins[plugin_id] = PluginInfo(
                    id=plugin_id,
                    name=plugin_id,
                    version="unknown",
                    description="",
                    author="unknown",
                    file_path=str(file_path),
                    tools=[],
                    status="error",
                    error_msg=f"安全检查失败: {reason}"
                )
                return False


            spec = importlib.util.spec_from_file_location(plugin_id, file_path)
            module = importlib.util.module_from_spec(spec)


            module.__dict__['BaseTool'] = BaseTool
            module.__dict__['logger'] = logger

            spec.loader.exec_module(module)


            plugin_info = PluginInfo(
                id=plugin_id,
                name=getattr(module, 'PLUGIN_NAME', plugin_id),
                version=getattr(module, 'PLUGIN_VERSION', '1.0.0'),
                description=getattr(module, 'PLUGIN_DESCRIPTION', ''),
                author=getattr(module, 'PLUGIN_AUTHOR', 'unknown'),
                file_path=str(file_path),
                tools=[],
                status="active",
                loaded_at=datetime.now().timestamp()
            )


            for name, obj in inspect.getmembers(module):
                if (inspect.isclass(obj) and
                    issubclass(obj, BaseTool) and
                    obj is not BaseTool):

                    try:
                        tool = obj()
                        self._loaded_tools[tool.tool_id] = tool
                        plugin_info.tools.append(tool.tool_id)


                        from core.tool.tool_manager import tool_manager
                        tool_manager.register_tool(
                            name=tool.tool_id,
                            func=tool.run,
                            description=tool.description
                        )

                        logger.info(f"[Plugin] 注册工具: {tool.tool_id} 来自插件 {plugin_id}")
                    except Exception as e:
                        logger.error(f"[Plugin] 实例化工具失败 {name}: {e}")


            if hasattr(module, 'on_load'):
                try:
                    module.on_load()
                    logger.info(f"[Plugin] 执行初始化钩子: {plugin_id}")
                except Exception as e:
                    logger.error(f"[Plugin] 初始化钩子执行失败: {e}")

            self._plugins[plugin_id] = plugin_info
            logger.info(f"[Plugin] 加载插件成功: {plugin_id} v{plugin_info.version}")
            return True

        except Exception as e:
            logger.error(f"[Plugin] 加载插件失败 {plugin_id}: {e}")
            self._plugins[plugin_id] = PluginInfo(
                id=plugin_id,
                name=plugin_id,
                version="unknown",
                description="",
                author="unknown",
                file_path=str(file_path),
                tools=[],
                status="error",
                error_msg=str(e)
            )
            return False

    def get_plugin(self, plugin_id: str) -> PluginInfo | None:
        """获取插件信息"""
        return self._plugins.get(plugin_id)

    def list_plugins(self, status: str = None) -> list[PluginInfo]:
        """列出所有插件"""
        plugins = list(self._plugins.values())
        if status:
            plugins = [p for p in plugins if p.status == status]
        return plugins

    def reload_plugin(self, plugin_id: str) -> bool:
        """重新加载插件"""
        if plugin_id in self._plugins:

            self._unload_plugin(plugin_id)

            file_path = Path(self._plugins[plugin_id].file_path)
            return self._load_plugin(file_path)
        return False

    def _unload_plugin(self, plugin_id: str):
        """卸载插件"""
        plugin = self._plugins.get(plugin_id)
        if plugin:

            try:
                spec = importlib.util.spec_from_file_location(plugin_id, plugin.file_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                if hasattr(module, 'on_unload'):
                    module.on_unload()
            except Exception as e:
                logger.error(f"[Plugin] 卸载钩子执行失败: {e}")


            for tool_id in plugin.tools:
                if tool_id in self._loaded_tools:
                    del self._loaded_tools[tool_id]

            logger.info(f"[Plugin] 卸载插件: {plugin_id}")

    def delete_plugin(self, plugin_id: str) -> bool:
        """删除插件"""
        if plugin_id in self._plugins:
            self._unload_plugin(plugin_id)


            file_path = Path(self._plugins[plugin_id].file_path)
            if file_path.exists():
                backup_path = self.backup_dir / f"{plugin_id}_{int(time.time())}.py"
                shutil.move(str(file_path), str(backup_path))

            del self._plugins[plugin_id]
            return True
        return False

    def install_plugin(self, file_path: Path) -> bool:
        """安装新插件"""
        try:

            if not file_path.exists():
                logger.error(f"[Plugin] 插件文件不存在: {file_path}")
                return False


            with open(file_path, encoding='utf-8') as f:
                code = f.read()

            is_safe, reason = self.security_checker.check(code)
            if not is_safe:
                logger.error(f"[Plugin] 插件未通过安全检查: {reason}")
                return False


            dest = self.plugins_dir / file_path.name
            shutil.copy2(file_path, dest)


            return self._load_plugin(dest)
        except Exception as e:
            logger.error(f"[Plugin] 安装插件失败: {e}")
            return False

    def toggle_plugin(self, plugin_id: str, enable: bool) -> bool:
        """启用/禁用插件"""
        plugin = self._plugins.get(plugin_id)
        if not plugin:
            return False

        try:
            src = Path(plugin.file_path)

            if enable:

                disabled_path = self.disabled_dir / f"{plugin_id}.py"
                if disabled_path.exists():
                    dst = self.plugins_dir / f"{plugin_id}.py"
                    shutil.move(str(disabled_path), str(dst))
                    return self._load_plugin(dst)
            else:

                self._unload_plugin(plugin_id)
                if src.exists():
                    dst = self.disabled_dir / f"{plugin_id}.py"
                    shutil.move(str(src), str(dst))
                    plugin.status = "disabled"
                    return True

            return False
        except Exception as e:
            logger.error(f"[Plugin] 切换插件状态失败: {e}")
            return False

    def register_hook(self, event: str, callback: Callable):
        """注册事件钩子"""
        if event not in self._hooks:
            self._hooks[event] = []
        self._hooks[event].append(callback)

    def trigger_hook(self, event: str, *args, **kwargs):
        """触发事件钩子"""
        for callback in self._hooks.get(event, []):
            try:
                callback(*args, **kwargs)
            except Exception as e:
                logger.error(f"[Plugin] 钩子执行失败: {e}")

    def get_plugin_stats(self) -> dict:
        """获取插件统计"""
        active = sum(1 for p in self._plugins.values() if p.status == "active")
        disabled = sum(1 for p in self._plugins.values() if p.status == "disabled")
        errors = sum(1 for p in self._plugins.values() if p.status == "error")

        return {
            'total': len(self._plugins),
            'active': active,
            'disabled': disabled,
            'errors': errors,
            'tools_count': len(self._loaded_tools)
        }



PLUGIN_TEMPLATE = '''#!/usr/bin/env python3
"""
示例插件
"""

from core.tool.base_tool import BaseTool

PLUGIN_NAME = "示例插件"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "这是一个示例插件"
PLUGIN_AUTHOR = "Your Name"


def on_load():
    """插件加载时调用"""
    print(f"[Plugin] {PLUGIN_NAME} 已加载")


def on_unload():
    """插件卸载时调用"""
    print(f"[Plugin] {PLUGIN_NAME} 已卸载")


class ExampleTool(BaseTool):
    """示例工具"""

    tool_id = "example_tool"
    name = "示例工具"
    description = "这是一个示例工具"

    input_schema = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "消息内容"
            }
        },
        "required": ["message"]
    }

    def run(self, message: str) -> dict:
        """执行工具"""
        return {
            "success": True,
            "data": {"echo": message},
            "message": f"收到消息: {message}"
        }
'''



plugin_manager = PluginManager()



def install_plugin(file_path: Path) -> bool:
    """安装插件的便捷函数"""
    return plugin_manager.install_plugin(file_path)


def list_plugins(status: str = None) -> list[PluginInfo]:
    """列出插件的便捷函数"""
    return plugin_manager.list_plugins(status)


def reload_plugin(plugin_id: str) -> bool:
    """重新加载插件的便捷函数"""
    return plugin_manager.reload_plugin(plugin_id)
