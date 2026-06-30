#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
Prompt Builder V2 - 模块化提示词构建器  # 模块标题
支持：  # 支持功能列表
1. roles.yaml 热编辑  # 功能1：配置文件热重载
2. 前端模块选择  # 功能2：前端界面模块选择
3. 动态提示词组合  # 功能3：动态组合提示词
4. 角色切换  # 功能4：多角色切换

Author: AI Assistant  # 作者
Version: 2.0.0  # 版本号
"""  # 多行文档字符串结束

import threading  # 导入线程模块
from dataclasses import dataclass  # 从dataclasses导入数据类装饰器和字段
from pathlib import Path  # 从pathlib导入路径类
from typing import Any  # 从typing导入类型注解

import yaml  # 导入YAML解析库
from watchdog.events import FileSystemEventHandler  # 从watchdog导入文件系统事件处理器
from watchdog.observers import Observer  # 从watchdog导入文件观察者

from core.config import config  # 从core.config导入配置对象
from core.logger import logger  # 从core.logger导入日志记录器


@dataclass  # 使用数据类装饰器
class PromptModule:  # 定义提示词模块数据类
    """提示词模块"""  # 类文档字符串
    name: str  # 模块显示名称  # 字段1
    description: str  # 模块描述  # 字段2
    content: str  # 模块内容（提示词文本）  # 字段3
    optional: bool = True  # 是否可选，默认可选  # 字段4
    default: bool = False  # 默认是否启用，默认False  # 字段5
    order: int = 100  # 排序权重，默认100  # 字段6


@dataclass  # 使用数据类装饰器
class RoleConfig:  # 定义角色配置数据类
    """角色配置"""  # 类文档字符串
    name: str  # 角色显示名称  # 字段1
    description: str  # 角色描述  # 字段2
    base_modules: list[str]  # 基础模块ID列表（始终包含）  # 字段3
    optional_modules: list[str]  # 可选模块ID列表  # 字段4
    system_prompt: str = ""  # 角色专属系统提示词，默认空  # 字段5


class RolesConfigHandler(FileSystemEventHandler):  # 定义roles.yaml文件变更处理器类
    """roles.yaml 文件变更处理器"""  # 类文档字符串

    def __init__(self, builder):  # 初始化方法
        self.builder = builder  # 保存提示词构建器实例引用  # 属性

    def on_modified(self, event):  # 定义文件修改时的处理方法
        if event.src_path.endswith('roles.yaml'):  # 如果修改的是roles.yaml文件
            logger.info("[PromptBuilderV2] roles.yaml 已修改，重新加载...")  # 记录日志
            self.builder.reload_config()  # 调用构建器的热重载方法


class PromptBuilderV2:  # 定义模块化提示词构建器V2类
    """  # 类文档字符串开始
    模块化提示词构建器 V2  # 类标题

    使用示例:  # 使用示例
        builder = PromptBuilderV2()  # 创建实例（单例）

        # 获取所有可用模块（给前端展示）  # 获取模块示例
        modules = builder.get_available_modules()  # 获取模块列表

        # 前端选择模块后构建提示词  # 构建提示词示例
        prompt = builder.build_prompt(  # 调用构建方法
            role="assistant",  # 指定角色
            selected_modules=["memory_strategy", "tool_list"],  # 选择模块
            variables={"current_time": "2026-02-27"}  # 变量替换
        )  # 调用结束
    """  # 类文档字符串结束

    _instance = None  # 类属性：单例实例，初始为None  # 属性1
    _lock = threading.Lock()  # 类属性：线程锁，用于单例线程安全  # 属性2

    def __new__(cls):  # 定义创建实例方法（实现单例模式）
        if cls._instance is None:  # 如果实例为None
            with cls._lock:  # 获取线程锁
                if cls._instance is None:  # 双重检查
                    cls._instance = super().__new__(cls)  # 创建实例
        return cls._instance  # 返回实例

    def __init__(self):  # 定义初始化方法
        if '_initialized' in self.__dict__:  # 如果已经初始化过
            return  # 直接返回，避免重复初始化
        self._initialized = True  # 标记为已初始化

        # 配置存储  # 配置存储注释
        self._system_modules: dict[str, PromptModule] = {}  # 系统模块字典  # 属性3
        self._optional_modules: dict[str, PromptModule] = {}  # 可选模块字典  # 属性4
        self._roles: dict[str, RoleConfig] = {}  # 角色配置字典  # 属性5

        # 用户模块选择缓存  # 用户选择缓存注释
        self._user_module_selections: dict[str, set[str]] = {}  # 用户ID到模块选择集合的映射  # 属性6

        # 加载配置  # 配置加载注释
        self._load_config()  # 调用配置加载方法

        # 启动文件监控  # 文件监控注释
        self._start_watch()  # 启动文件监控

    def _load_config(self):  # 定义加载配置方法
        """加载 roles.yaml 配置"""  # 方法文档字符串
        config_path = Path(__file__).parent.parent.parent / "config" / "roles.yaml"  # 构建配置文件路径（项目根目录）

        if not config_path.exists():  # 如果配置文件不存在
            logger.warning(f"[PromptBuilderV2] roles.yaml 不存在: {config_path}")  # 记录警告
            return  # 返回

        try:  # 异常捕获块开始
            with open(config_path, encoding='utf-8') as f:  # 打开配置文件
                data = yaml.safe_load(f) or {}  # 解析YAML，失败返回空字典

            # 加载系统模块（始终包含）  # 系统模块加载注释
            self._system_modules = {}  # 重置系统模块字典
            for key, module_data in data.get('system', {}).items():  # 遍历system节
                self._system_modules[key] = PromptModule(  # 创建PromptModule实例
                    name=module_data.get('name', key),  # 名称，默认使用key
                    description=module_data.get('description', ''),  # 描述，默认空
                    content=module_data.get('content', ''),  # 内容，默认空
                    optional=module_data.get('optional', False),  # 是否可选，默认False（系统模块通常必选）
                    default=module_data.get('default', False),  # 默认启用，默认False
                    order=module_data.get('order', 10)  # 排序权重，默认10（系统模块优先级高）
                )  # PromptModule创建结束

            # 加载可选模块  # 可选模块加载注释
            self._optional_modules = {}  # 重置可选模块字典
            for key, module_data in data.get('modules', {}).items():  # 遍历modules节
                self._optional_modules[key] = PromptModule(  # 创建PromptModule实例
                    name=module_data.get('name', key),  # 名称，默认使用key
                    description=module_data.get('description', ''),  # 描述，默认空
                    content=module_data.get('content', ''),  # 内容，默认空
                    optional=module_data.get('optional', True),  # 是否可选，默认True
                    default=module_data.get('default', False),  # 默认启用，默认False
                    order=module_data.get('order', 100)  # 排序权重，默认100
                )  # PromptModule创建结束

            # 加载角色配置  # 角色配置加载注释
            self._roles = {}  # 重置角色配置字典
            for key, role_data in data.get('roles', {}).items():  # 遍历roles节
                self._roles[key] = RoleConfig(  # 创建RoleConfig实例
                    name=role_data.get('name', key),  # 名称，默认使用key
                    description=role_data.get('description', ''),  # 描述，默认空
                    base_modules=role_data.get('base_modules', []),  # 基础模块列表，默认空
                    optional_modules=role_data.get('optional_modules', []),  # 可选模块列表，默认空
                    system_prompt=role_data.get('system_prompt', '')  # 系统提示词，默认空
                )  # RoleConfig创建结束

            logger.info(f"[PromptBuilderV2] 配置加载完成: "  # 记录成功日志
                        f"{len(self._system_modules)} 系统模块, "  # 系统模块数量
                        f"{len(self._optional_modules)} 可选模块, "  # 可选模块数量
                        f"{len(self._roles)} 角色")  # 角色数量

        except Exception as e:  # 捕获异常
            logger.error(f"[PromptBuilderV2] 加载配置失败: {e}")  # 记录错误日志

    def _start_watch(self):  # 定义启动文件监控方法
        """启动文件监控"""  # 方法文档字符串
        config_dir = Path(__file__).parent.parent.parent / "config"  # 获取配置目录路径（项目根目录）
        if not config_dir.exists():  # 如果配置目录不存在
            logger.warning(f"[PromptBuilderV2] 配置目录不存在，跳过监控: {config_dir}")  # 记录警告
            return  # 直接返回，不启动监控
        event_handler = RolesConfigHandler(self)  # 创建文件变更处理器实例
        self._observer = Observer()  # 创建观察者实例
        self._observer.schedule(event_handler, str(config_dir), recursive=False)  # 调度监控
        self._observer.start()  # 启动监控
        logger.info("[PromptBuilderV2] 已启动 roles.yaml 监控")  # 记录日志

    def reload_config(self):  # 定义热重载配置方法
        """热重载配置"""  # 方法文档字符串
        with self._lock:  # 获取线程锁
            self._load_config()  # 调用配置加载方法

    # ==================== 前端API ====================  # 前端API分隔线

    def get_available_modules(self, role: str = "assistant") -> list[dict[str, Any]]:  # 定义获取可用模块方法
        """  # 方法文档字符串开始
        获取所有可用的提示词模块（供前端展示）  # 方法标题

        Returns:  # 返回值说明
            模块列表，每个模块包含：  # 返回结构说明
            - id: 模块ID  # 字段1
            - name: 显示名称  # 字段2
            - description: 描述  # 字段3
            - content: 模块内容（提示词文本）  # 字段4
            - optional: 是否可选  # 字段5
            - default: 默认是否选中  # 字段6
            - order: 排序权重  # 字段7
            - category: 分类（system/modules）  # 字段8
        """  # 方法文档字符串结束
        result = []  # 初始化结果列表

        # 添加系统模块  # 系统模块添加注释
        for key, module in self._system_modules.items():  # 遍历系统模块
            result.append({  # 添加模块信息字典
                "id": key,  # 模块ID
                "name": module.name,  # 显示名称
                "description": module.description,  # 描述
                "content": module.content,  # 模块内容（提示词文本）
                "optional": module.optional,  # 是否可选
                "default": module.default,  # 默认选中
                "order": module.order,  # 排序权重
                "category": "system"  # 分类为system
            })  # 添加结束

        # 添加可选模块  # 可选模块添加注释
        for key, module in self._optional_modules.items():  # 遍历可选模块
            result.append({  # 添加模块信息字典
                "id": key,  # 模块ID
                "name": module.name,  # 显示名称
                "description": module.description,  # 描述
                "content": module.content,  # 模块内容（提示词文本）
                "optional": module.optional,  # 是否可选
                "default": module.default,  # 默认选中
                "order": module.order,  # 排序权重
                "category": "optional"  # 分类为optional
            })  # 添加结束

        # 根据角色过滤  # 角色过滤注释
        if role in self._roles:  # 如果角色存在
            role_config = self._roles[role]  # 获取角色配置
            allowed_modules = set(role_config.base_modules + role_config.optional_modules)  # 允许的模块集合
            # 保留系统模块和角色允许的模块  # 过滤逻辑
            result = [m for m in result if m["category"] == "system" or m["id"] in allowed_modules]  # 列表推导过滤

        # 按order排序  # 排序注释
        result.sort(key=lambda x: x["order"])  # 按order字段排序

        return result  # 返回结果列表

    def get_roles(self) -> list[dict[str, str]]:  # 定义获取所有角色方法
        """获取所有可用角色（供前端选择）"""  # 方法文档字符串
        return [  # 返回列表
            {  # 角色信息字典
                "id": key,  # 角色ID
                "name": role.name,  # 显示名称
                "description": role.description  # 描述
            }  # 字典结束
            for key, role in self._roles.items()  # 遍历所有角色
        ]  # 列表推导结束

    def get_role_default_modules(self, role: str) -> list[str]:  # 定义获取角色默认模块方法
        """获取角色的默认模块选择"""  # 方法文档字符串
        if role not in self._roles:  # 如果角色不存在
            return []  # 返回空列表

        role_config = self._roles[role]  # 获取角色配置
        default_modules = []  # 初始化默认模块列表

        # 基础模块始终包含  # 基础模块注释
        for module_id in role_config.base_modules:  # 遍历基础模块
            if module_id in self._system_modules or module_id in self._optional_modules:  # 如果模块存在
                default_modules.append(module_id)  # 添加到列表

        # 可选模块按default设置  # 可选模块注释
        for module_id in role_config.optional_modules:  # 遍历可选模块
            module = self._optional_modules.get(module_id)  # 获取模块
            if module and module.default:  # 如果模块存在且默认启用
                default_modules.append(module_id)  # 添加到列表

        return default_modules  # 返回默认模块列表

    def save_user_selection(self, user_id: str, selected_modules: list[str], role: str = None):  # 定义保存用户选择方法
        """  # 方法文档字符串开始
        保存用户的模块选择偏好  # 方法标题

        Args:  # 参数说明
            user_id: 用户ID  # 参数1
            selected_modules: 选中的模块ID列表  # 参数2
            role: 角色（可选）  # 参数3
        """  # 方法文档字符串结束
        self._user_module_selections[user_id] = set(selected_modules)  # 保存到内存缓存

        # 持久化到config系统  # 持久化注释
        config.set_user_config(user_id, "prompt.selected_modules", selected_modules)  # 保存到配置系统

        # 保存角色信息  # 角色保存注释
        if role:  # 如果有角色
            config.set_user_config(user_id, "prompt.role", role)  # 保存角色

        logger.info(f"[PromptBuilderV2] 已保存用户 {user_id} 的模块选择: {selected_modules}, role={role}")  # 记录日志

    def get_user_selection(self, user_id: str, role: str = "assistant") -> list[str]:  # 定义获取用户选择方法
        """  # 方法文档字符串开始
        获取用户的模块选择  # 方法标题

        优先级：  # 优先级说明
        1. 用户已保存的选择  # 优先级1
        2. 角色默认选择  # 优先级2
        3. 所有默认选中的模块  # 优先级3
        """  # 方法文档字符串结束
        # 从config系统读取  # 读取注释
        saved = config.get_user_config(user_id, "prompt.selected_modules", None)  # 获取保存的选择
        if saved:  # 如果有保存的选择
            return saved  # 返回保存的选择

        # 使用角色默认  # 角色默认注释
        return self.get_role_default_modules(role)  # 返回角色默认模块

    # ==================== 提示词构建 ====================  # 提示词构建分隔线

    def _safe_format(self, template: str, variables: dict[str, Any]) -> str:  # 定义安全格式化方法
        """  # 方法文档字符串开始
        安全的字符串格式化  # 方法标题

        特点：  # 特点说明
        - 只替换已定义的变量  # 特点1
        - 未定义的变量保留原样（包括大括号）  # 特点2
        - 支持转义的大括号 {{ 和 }}  # 特点3

        Args:  # 参数说明
            template: 模板字符串  # 参数1
            variables: 变量字典  # 参数2

        Returns:  # 返回值说明
            格式化后的字符串  # 返回类型
        """  # 方法文档字符串结束
        result = template  # 复制模板

        # 先处理转义的大括号 {{ 和 }}  # 转义处理注释
        # 用临时占位符替换  # 占位符注释
        result = result.replace('{{', '\x00LBRACE\x00')  # 替换左双大括号为占位符
        result = result.replace('}}', '\x00RBRACE\x00')  # 替换右双大括号为占位符

        # 替换已定义的变量  # 变量替换注释
        for key in sorted(variables.keys(), key=len, reverse=True):  # 按长度降序遍历，避免短名破坏长名
            placeholder = '{' + key + '}'  # 构建占位符
            result = result.replace(placeholder, str(variables[key]))  # 替换为变量值

        # 恢复转义的大括号  # 恢复注释
        result = result.replace('\x00LBRACE\x00', '{')  # 恢复左大括号
        result = result.replace('\x00RBRACE\x00', '}')  # 恢复右大括号

        return result  # 返回格式化后的字符串

    def build_prompt(self,  # 定义构建提示词方法
                     role: str = "assistant",  # 参数：角色ID，默认assistant
                     selected_modules: list[str] | None = None,  # 参数：显式指定的模块选择
                     user_id: str | None = None,  # 参数：用户ID
                     variables: dict[str, Any] | None = None  # 参数：变量替换字典
                     ) -> str:  # 返回：组合后的提示词
        """  # 方法文档字符串开始
        构建完整的提示词  # 方法标题

        Args:  # 参数说明
            role: 角色ID  # 参数1
            selected_modules: 显式指定的模块选择（优先级最高）  # 参数2
            user_id: 用户ID（用于获取保存的偏好）  # 参数3
            variables: 变量替换字典  # 参数4

        Returns:  # 返回值说明
            组合后的提示词  # 返回类型
        """  # 方法文档字符串结束
        # 确定模块选择  # 模块选择注释
        if selected_modules is not None:  # 如果有显式指定
            modules_to_use = selected_modules  # 使用显式指定
        elif user_id:  # 否则如果有用户ID
            modules_to_use = self.get_user_selection(user_id, role)  # 获取用户选择
        else:  # 否则
            modules_to_use = self.get_role_default_modules(role)  # 使用角色默认

        modules_to_use = set(modules_to_use)  # 转换为集合去重

        # 收集所有启用的模块内容  # 内容收集注释
        enabled_contents = []  # 初始化内容列表

        # === 新增：强制插入常驻基底（不受模块选择影响，永远置顶）===
        if "permanent_basement" in self._system_modules:
            pb_module = self._system_modules["permanent_basement"]
            pb_content = self.get_module_content("permanent_basement", user_id) or pb_module.content
            enabled_contents.append((-1, pb_content))

        # 1. 系统模块（始终包含，除非显式排除）  # 系统模块注释
        for key, module in sorted(self._system_modules.items(), key=lambda x: x[1].order):  # 按order排序遍历
            if key == "permanent_basement":
                continue  # 已强制插入，跳过避免重复
            if key in modules_to_use or not module.optional:  # 如果在选择中或必选
                # 优先使用用户级覆盖内容
                module_content = self.get_module_content(key, user_id) or module.content
                enabled_contents.append((module.order, module_content))  # 添加（排序权重，内容）

        # 2. 可选模块  # 可选模块注释
        for key, module in sorted(self._optional_modules.items(), key=lambda x: x[1].order):  # 按order排序遍历
            if key in modules_to_use:  # 如果在选择中
                # 优先使用用户级覆盖内容
                module_content = self.get_module_content(key, user_id) or module.content
                enabled_contents.append((module.order, module_content))  # 添加（排序权重，内容）

        # 3. 角色专属system_prompt  # 角色提示词注释
        if role in self._roles:  # 如果角色存在
            role_config = self._roles[role]  # 获取角色配置
            if role_config.system_prompt:  # 如果有专属提示词
                enabled_contents.append((1, role_config.system_prompt))  # 角色提示词 order=1，确保在常驻基底(-1)之后

        # 按order排序并组合  # 排序组合注释
        enabled_contents.sort(key=lambda x: x[0])  # 按order排序
        combined_content = "\n\n".join([content for _, content in enabled_contents])  # 用双换行连接

        # 变量替换（安全模式：未定义的变量保留原样）  # 变量替换注释
        if variables:  # 如果有变量
            try:  # 异常捕获
                # 使用自定义替换逻辑，保留未定义变量  # 自定义替换注释
                combined_content = self._safe_format(combined_content, variables)  # 调用安全格式化
            except Exception as e:  # 捕获异常
                logger.warning(f"[PromptBuilderV2] 变量替换失败: {e}")  # 记录警告

        return combined_content.strip()  # 去除首尾空白后返回

    def build_prompt_with_metadata(self,  # 定义构建带元数据提示词方法
                                   role: str = "assistant",  # 参数：角色ID
                                   selected_modules: list[str] | None = None,  # 参数：模块选择
                                   user_id: str | None = None,  # 参数：用户ID
                                   variables: dict[str, Any] | None = None  # 参数：变量字典
                                   ) -> dict[str, Any]:  # 返回：包含元数据的字典
        """  # 方法文档字符串开始
        构建提示词并返回元数据（供前端预览）  # 方法标题

        Returns:  # 返回值说明
            {  # 返回结构
                "prompt": "完整提示词",  # 提示词内容
                "modules_used": ["模块ID列表"],  # 使用的模块
                "estimated_tokens": 1234,  # 估算token数
                "variables_used": {"key": "value"}  # 使用的变量
            }  # 结构结束
        """  # 方法文档字符串结束
        prompt = self.build_prompt(role, selected_modules, user_id, variables)  # 调用构建方法

        # 计算使用的模块  # 模块计算注释
        if selected_modules is not None:  # 如果有显式指定
            modules_used = selected_modules  # 使用显式指定
        elif user_id:  # 否则如果有用户ID
            modules_used = self.get_user_selection(user_id, role)  # 获取用户选择
        else:  # 否则
            modules_used = self.get_role_default_modules(role)  # 使用角色默认

        # 估算Token数（简单估算：2字符/token）  # token估算注释
        estimated_tokens = len(prompt) // 2  # 字符数除以2

        return {  # 返回结果字典
            "prompt": prompt,  # 提示词内容
            "modules_used": modules_used,  # 使用的模块
            "estimated_tokens": estimated_tokens,  # 估算token数
            "variables_used": variables or {}  # 使用的变量（如果为None返回空字典）
        }  # 返回结束

    def preview_module(self, module_id: str) -> str | None:  # 定义预览模块方法
        """预览单个模块的内容"""  # 方法文档字符串
        if module_id in self._system_modules:  # 如果是系统模块
            return self._system_modules[module_id].content  # 返回内容
        if module_id in self._optional_modules:  # 如果是可选模块
            return self._optional_modules[module_id].content  # 返回内容
        return None  # 不存在返回None

    def get_module_content(self, module_id: str, user_id: str | None = None) -> str | None:  # 定义获取模块内容方法（支持用户级覆盖）
        """
        获取模块内容，优先使用用户级覆盖

        Args:
            module_id: 模块ID
            user_id: 用户ID，如果提供则优先获取用户级覆盖

        Returns:
            模块内容，如果不存在返回None

        优先级:
            1. 用户级覆盖 (data/user_prompts/{user_id}/modules/{module_id}.txt)
            2. 全局默认 (roles.yaml)
        """
        # 1. 优先检查用户级覆盖
        if user_id and user_id != "default_user":
            user_content = config.get_user_prompt_module(user_id, module_id)
            if user_content is not None:
                logger.debug(f"[PromptBuilderV2] 使用用户 {user_id} 的模块 {module_id} 覆盖")
                return user_content

        # 2. 使用全局默认
        return self.preview_module(module_id)


# 全局单例  # 全局单例注释
prompt_builder_v2 = PromptBuilderV2()  # 创建全局单例实例


# 便捷函数  # 便捷函数注释
def get_prompt_builder() -> PromptBuilderV2:  # 定义获取提示词构建器函数
    """获取提示词构建器实例"""  # 函数文档字符串
    return prompt_builder_v2  # 返回全局单例实例


# =============================================================================
# 总结性注释：文件角色、关联关系与核心效果
# =============================================================================
#
# 【文件角色】
# 本文件（prompt_builder_v2.py）是 SiliconBase V5 系统的"模块化提示词构建器V2"核心模块，
# 实现了基于YAML配置、支持热重载、模块化组合的提示词构建系统。
# 这是Prompt Builder的第二代实现，相比V1版本提供了更灵活的配置方式和前端支持。
#
# 【核心定位】
# - 模块化设计：将系统提示词拆分为独立的模块（系统模块+可选模块）
# - 角色系统：支持多角色配置，不同角色有不同的模块组合
# - 用户偏好：保存用户的模块选择偏好，支持个性化配置
# - 热重载：配置文件修改后自动重载，无需重启
# - 变量替换：支持模板变量安全替换
# - 前端支持：提供API供前端展示模块列表、角色选择、预览功能
#
# 【核心类说明】
# 1. PromptModule(dataclass): 提示词模块
#    - name/description/content: 基本信息和内容
#    - optional/default/order: 可选性、默认启用、排序权重
#
# 2. RoleConfig(dataclass): 角色配置
#    - name/description: 角色信息
#    - base_modules: 基础模块列表（始终包含）
#    - optional_modules: 可选模块列表
#    - system_prompt: 角色专属系统提示词
#
# 3. RolesConfigHandler(FileSystemEventHandler): 文件变更处理器
#    - on_modified(): roles.yaml修改时触发重载
#
# 4. PromptBuilderV2: 提示词构建器核心（单例模式）
#    - __new__(): 实现线程安全的单例模式
#    - _load_config(): 从roles.yaml加载系统模块/可选模块/角色配置
#    - _start_watch(): 启动watchdog文件监控
#    - reload_config(): 热重载配置
#    - 前端API:
#      - get_available_modules(): 获取可用模块列表
#      - get_roles(): 获取角色列表
#      - get_role_default_modules(): 获取角色默认模块
#      - save_user_selection(): 保存用户选择
#      - get_user_selection(): 获取用户选择（支持优先级回退）
#    - 构建API:
#      - build_prompt(): 构建完整提示词
#      - build_prompt_with_metadata(): 构建带元数据的提示词
#      - preview_module(): 预览单个模块内容
#    - _safe_format(): 安全字符串格式化（保留未定义变量）
#
# 【关联文件】
# 1. config/roles.yaml                        - 配置文件
#    * 关系：核心配置源
#    * 结构：
#      system: {...}      # 系统模块定义
#      modules: {...}     # 可选模块定义
#      roles: {...}       # 角色配置定义
#    * 交互：被PromptBuilderV2加载和监控
#
# 2. core/config.py                          - 配置系统
#    * 关系：持久化依赖
#    * 交互：save_user_selection调用config.set_user_config()
#           get_user_selection调用config.get_user_config()
#
# 3. core/logger.py                          - 日志系统
#    * 关系：记录操作日志
#    * 交互：logger.info/warning/error
#
# 4. watchdog库                            - 文件监控
#    * 关系：热重载实现依赖
#    * 交互：Observer监控roles.yaml变更
#
# 5. PyYAML库                              - YAML解析
#    * 关系：配置解析依赖
#    * 交互：yaml.safe_load()解析roles.yaml
#
# 6. core/prompt_builder.py                - 第一代提示词构建器
#    * 关系：功能替代/并存
#    * 区别：V1使用代码硬编码模板，V2使用YAML配置
#
# 【配置文件结构(roles.yaml)】
# system:                    # 系统模块（高优先级，通常必选）
#   core_identity:
#     name: "核心身份"
#     content: "你是AI助手..."
#     order: 10
#
# modules:                   # 可选模块
#   memory_strategy:
#     name: "记忆策略"
#     content: "记忆使用指南..."
#     optional: true
#     default: true
#     order: 100
#
# roles:                     # 角色定义
#   assistant:
#     name: "通用助手"
#     base_modules: ["core_identity"]
#     optional_modules: ["memory_strategy", "tool_list"]
#     system_prompt: "额外角色提示..."
#
# 【达到的效果】
# 1. 模块化提示词：将庞大的系统提示词拆分为可复用的小模块
# 2. 角色定制：不同角色（助手/专家/顾问）有不同的提示词组合
# 3. 用户个性化：保存用户的模块偏好，提供个性化体验
# 4. 热更新：修改roles.yaml后立即生效，无需重启服务
# 5. 安全格式化：_safe_format()保留未定义变量，避免KeyError
# 6. 前端友好：提供完整的API供前端展示和选择
# 7. 优先级回退：用户选择 → 角色默认 → 系统默认
# 8. Token估算：build_prompt_with_metadata()预估提示词长度
# 9. 线程安全：单例模式+锁机制保证并发安全
# 10. 灵活组合：通过order控制模块顺序，支持任意组合
#
# 【使用场景】
# - Agent初始化时构建系统提示词
# - 用户在前端界面选择/取消模块
# - 用户切换角色（助手/专家/顾问等）
# - 开发者修改roles.yaml热更新提示词
# - 前端预览各模块内容和完整提示词
#
# 【数据流】
# 启动时: _load_config() -> 解析roles.yaml -> _system_modules/_optional_modules/_roles
#     |
# 文件变更: watchdog -> RolesConfigHandler -> reload_config() -> _load_config()
#     |
# 前端请求: get_available_modules()/get_roles() -> 返回模块/角色列表
#     |
# 保存偏好: save_user_selection() -> config.set_user_config() + 内存缓存
#     |
# 构建提示词: build_prompt() -> 确定模块选择 -> 收集内容 -> 排序 -> 变量替换
#     |
# 带元数据: build_prompt_with_metadata() -> build_prompt() + 计算metadata
#
# =============================================================================
