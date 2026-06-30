#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
任务模板系统 - SiliconBase V5  # 模块标题
支持定时任务、监控任务、自动化任务等预定义模板  # 功能概述
"""  # 文档字符串结束

import json  # 导入JSON模块
from dataclasses import asdict, dataclass  # 导入数据类相关
from pathlib import Path  # 导入路径模块

import yaml  # 导入YAML模块，用于配置文件

from core.logger import logger  # 导入日志记录器


@dataclass  # 数据类装饰器
class TaskTemplate:  # 定义任务模板数据类
    """任务模板"""  # 类文档字符串
    id: str  # 模板ID
    name: str  # 模板名称
    description: str  # 模板描述
    category: str  # 分类：定时、监控、自动化等  # 分类
    parameters: dict  # 参数定义  # 参数
    workflow: list[dict]  # 工作流步骤  # 工作流
    triggers: list[dict]  # 触发条件（可选）  # 触发器
    created_at: float  # 创建时间  # 创建时间戳
    usage_count: int = 0  # 使用次数，默认0  # 使用计数


class TaskTemplateManager:  # 定义任务模板管理器类
    """任务模板管理器"""  # 类文档字符串

    def __init__(self):  # 初始化方法
        self.templates_dir = Path("data/templates")  # 设置模板目录  # 模板目录
        self.templates_dir.mkdir(parents=True, exist_ok=True)  # 确保目录存在
        self._templates: dict[str, TaskTemplate] = {}  # 初始化模板字典
        self._load_templates()  # 加载模板

    def _load_templates(self):  # 定义加载模板方法
        """从YAML文件加载模板"""  # 方法文档字符串
        for template_file in self.templates_dir.glob("*.yaml"):  # 遍历YAML文件
            try:  # 异常处理
                with open(template_file, encoding='utf-8') as f:  # 打开文件
                    data = yaml.safe_load(f)  # 解析YAML
                    template = TaskTemplate(**data)  # 创建模板对象
                    self._templates[template.id] = template  # 添加到字典
            except Exception as e:  # 捕获异常
                logger.error(f"加载模板失败 {template_file}: {e}")  # 记录错误

        # 如果没有模板，初始化预定义模板  # 注释：初始化默认模板
        if not self._templates:  # 如果模板为空
            self._init_predefined_templates()  # 初始化预定义模板

        logger.info(f"[TemplateManager] 加载了 {len(self._templates)} 个模板")  # 记录日志

    def _init_predefined_templates(self):  # 定义初始化预定义模板方法
        """初始化预定义模板"""  # 方法文档字符串
        for template_data in PREDEFINED_TEMPLATES:  # 遍历预定义模板
            template = TaskTemplate(**template_data)  # 创建模板对象
            self.register_template(template)  # 注册模板
            logger.info(f"[TemplateManager] 初始化模板: {template.id}")  # 记录日志

    def register_template(self, template: TaskTemplate) -> bool:  # 定义注册模板方法
        """注册新模板"""  # 方法文档字符串
        try:  # 异常处理
            self._templates[template.id] = template  # 添加到字典

            # 保存到文件  # 注释：持久化
            file_path = self.templates_dir / f"{template.id}.yaml"  # 构建文件路径
            with open(file_path, 'w', encoding='utf-8') as f:  # 打开文件
                yaml.dump(asdict(template), f, allow_unicode=True)  # 写入YAML

            logger.info(f"[TemplateManager] 注册模板: {template.id}")  # 记录日志
            return True  # 返回成功
        except Exception as e:  # 捕获异常
            logger.error(f"注册模板失败: {e}")  # 记录错误
            return False  # 返回失败

    def get_template(self, template_id: str) -> TaskTemplate | None:  # 定义获取模板方法
        """获取模板"""  # 方法文档字符串
        return self._templates.get(template_id)  # 返回模板

    def list_templates(self, category: str = None) -> list[TaskTemplate]:  # 定义列出模板方法
        """列出所有模板"""  # 方法文档字符串
        templates = list(self._templates.values())  # 获取所有模板
        if category:  # 如果指定了分类
            templates = [t for t in templates if t.category == category]  # 筛选
        return templates  # 返回模板列表

    def delete_template(self, template_id: str) -> bool:  # 定义删除模板方法
        """删除模板"""  # 方法文档字符串
        if template_id in self._templates:  # 如果模板存在
            del self._templates[template_id]  # 删除模板
            file_path = self.templates_dir / f"{template_id}.yaml"  # 构建文件路径
            if file_path.exists():  # 如果文件存在
                file_path.unlink()  # 删除文件
            return True  # 返回成功
        return False  # 返回失败

    def instantiate_template(self, template_id: str, params: dict) -> dict | None:  # 定义实例化模板方法
        """  # 方法文档字符串开始
        实例化模板为可执行任务  # 方法功能

        Returns:  # 返回值说明
            任务配置字典，可直接用于创建Task  # 返回类型
        """  # 方法文档字符串结束
        template = self._templates.get(template_id)  # 获取模板
        if not template:  # 如果模板不存在
            return None  # 返回None

        # 验证参数  # 注释：参数验证
        validated_params = self._validate_params(template.parameters, params)  # 验证参数
        if not validated_params:  # 如果验证失败
            logger.error(f"模板参数验证失败: {template_id}")  # 记录错误
            return None  # 返回None

        # 构建任务  # 注释：构建任务
        task = {  # 任务字典
            'type': 'template_instance',  # 类型
            'template_id': template_id,  # 模板ID
            'name': template.name,  # 名称
            'params': validated_params,  # 参数
            'workflow': self._substitute_workflow(template.workflow, validated_params),  # 替换参数后的工作流
            'triggers': template.triggers  # 触发器
        }  # 任务字典结束

        # 更新使用计数  # 注释：更新计数
        template.usage_count += 1  # 增加使用计数

        return task  # 返回任务配置

    def _validate_params(self, param_defs: dict, provided: dict) -> dict | None:  # 定义验证参数方法
        """验证并填充参数"""  # 方法文档字符串
        validated = {}  # 初始化验证结果

        for name, definition in param_defs.items():  # 遍历参数定义
            if name in provided:  # 如果提供了该参数
                validated[name] = provided[name]  # 使用提供的值
            elif definition.get('required', False):  # 如果是必需参数
                if 'default' in definition:  # 如果有默认值
                    validated[name] = definition['default']  # 使用默认值
                else:  # 没有默认值
                    logger.error(f"缺少必需参数: {name}")  # 记录错误
                    return None  # 返回None

        return validated  # 返回验证后的参数

    def _substitute_workflow(self, workflow: list[dict], params: dict) -> list[dict]:  # 定义替换工作流参数方法
        """替换工作流中的参数占位符"""  # 方法文档字符串
        workflow_str = json.dumps(workflow)  # 转为JSON字符串

        for key, value in params.items():  # 遍历参数
            placeholder = f"{{{{{key}}}}}"  # 构建占位符 {{key}}
            workflow_str = workflow_str.replace(placeholder, str(value))  # 替换

        return json.loads(workflow_str)  # 转回对象并返回

    def search_templates(self, query: str) -> list[TaskTemplate]:  # 定义搜索模板方法
        """搜索模板"""  # 方法文档字符串
        query_lower = query.lower()  # 转为小写
        results = []  # 初始化结果列表

        for template in self._templates.values():  # 遍历模板
            if (query_lower in template.name.lower() or  # 匹配名称
                query_lower in template.description.lower() or  # 匹配描述
                query_lower in template.category.lower()):  # 匹配分类
                results.append(template)  # 添加到结果

        return results  # 返回结果

    def get_template_stats(self) -> dict:  # 定义获取统计方法
        """获取模板统计信息"""  # 方法文档字符串
        categories = {}  # 分类统计
        total_usage = 0  # 总使用次数

        for template in self._templates.values():  # 遍历模板
            categories[template.category] = categories.get(template.category, 0) + 1  # 统计分类
            total_usage += template.usage_count  # 累加使用次数

        return {  # 返回统计字典
            'total_templates': len(self._templates),  # 总模板数
            'categories': categories,  # 分类统计
            'total_usage': total_usage  # 总使用次数
        }  # 返回结束


# 预定义常用模板  # 注释：预定义模板
PREDEFINED_TEMPLATES = [  # 预定义模板列表
    {  # 模板1：定时提醒
        'id': 'timer_reminder',  # ID
        'name': '定时提醒',  # 名称
        'description': '在指定时间发送提醒',  # 描述
        'category': '定时任务',  # 分类
        'parameters': {  # 参数定义
            'message': {'type': 'string', 'required': True, 'description': '提醒内容'},  # 消息参数
            'delay_minutes': {'type': 'integer', 'required': False, 'default': 5, 'description': '延迟分钟数'},  # 延迟参数
            'repeat': {'type': 'boolean', 'required': False, 'default': False, 'description': '是否重复'}  # 重复参数
        },  # 参数结束
        'workflow': [  # 工作流
            {'tool': 'timer', 'params': {'duration': '{{delay_minutes}}', 'unit': 'minutes'}},  # 步骤1：定时
            {'tool': 'notify', 'params': {'message': '{{message}}'}}  # 步骤2：通知
        ],  # 工作流结束
        'triggers': [],  # 触发器
        'created_at': 0,  # 创建时间
        'usage_count': 0  # 使用计数
    },  # 模板1结束
    {  # 模板2：系统监控
        'id': 'system_monitor',  # ID
        'name': '系统监控',  # 名称
        'description': '监控系统资源并在异常时提醒',  # 描述
        'category': '监控',  # 分类
        'parameters': {  # 参数定义
            'cpu_threshold': {'type': 'number', 'required': False, 'default': 80, 'description': 'CPU使用率阈值'},  # CPU阈值
            'memory_threshold': {'type': 'number', 'required': False, 'default': 85, 'description': '内存使用率阈值'},  # 内存阈值
            'interval': {'type': 'integer', 'required': False, 'default': 60, 'description': '检查间隔(秒)'}  # 间隔参数
        },  # 参数结束
        'workflow': [  # 工作流
            {'tool': 'system_info', 'params': {}},  # 步骤1：获取系统信息
            {'tool': 'conditional', 'params': {'condition': 'cpu > {{cpu_threshold}} or memory > {{memory_threshold}}',  # 步骤2：条件判断
                                              'then': [{'tool': 'notify', 'params': {'message': '系统资源告警'}}]}}  # 条件满足时通知
        ],  # 工作流结束
        'triggers': [{'type': 'interval', 'seconds': '{{interval}}'}],  # 触发器：定时触发
        'created_at': 0,  # 创建时间
        'usage_count': 0  # 使用计数
    },  # 模板2结束
    {  # 模板3：文件备份
        'id': 'file_backup',  # ID
        'name': '文件备份',  # 名称
        'description': '自动备份指定目录',  # 描述
        'category': '自动化',  # 分类
        'parameters': {  # 参数定义
            'source_dir': {'type': 'string', 'required': True, 'description': '源目录'},  # 源目录
            'backup_dir': {'type': 'string', 'required': True, 'description': '备份目录'},  # 备份目录
            'schedule': {'type': 'string', 'required': False, 'default': 'daily', 'description': '备份频率(daily/weekly)'}  # 频率
        },  # 参数结束
        'workflow': [  # 工作流
            {'tool': 'file_copy', 'params': {'source': '{{source_dir}}', 'destination': '{{backup_dir}}/backup_{{timestamp}}'}},  # 复制
            {'tool': 'notify', 'params': {'message': '备份完成'}}  # 通知
        ],  # 工作流结束
        'triggers': [{'type': 'schedule', 'cron': '0 2 * * *'}],  # 触发器：每天2点
        'created_at': 0,  # 创建时间
        'usage_count': 0  # 使用计数
    },  # 模板3结束
    {  # 模板4：日报生成
        'id': 'daily_report',  # ID
        'name': '日报生成',  # 名称
        'description': '自动生成每日工作报告',  # 描述
        'category': '自动化',  # 分类
        'parameters': {  # 参数定义
            'output_format': {'type': 'string', 'required': False, 'default': 'markdown', 'description': '输出格式'},  # 格式
            'include_tasks': {'type': 'boolean', 'required': False, 'default': True, 'description': '包含任务统计'}  # 任务统计
        },  # 参数结束
        'workflow': [  # 工作流
            {'tool': 'collect_daily_data', 'params': {}},  # 步骤1：收集数据
            {'tool': 'generate_report', 'params': {'format': '{{output_format}}', 'include_tasks': '{{include_tasks}}'}}  # 步骤2：生成报告
        ],  # 工作流结束
        'triggers': [{'type': 'schedule', 'cron': '0 18 * * *'}],  # 触发器：每天18点
        'created_at': 0,  # 创建时间
        'usage_count': 0  # 使用计数
    },  # 模板4结束
    {  # 模板5：网站状态检查
        'id': 'website_checker',  # ID
        'name': '网站状态检查',  # 名称
        'description': '定期检查网站可访问性',  # 描述
        'category': '监控',  # 分类
        'parameters': {  # 参数定义
            'url': {'type': 'string', 'required': True, 'description': '网站URL'},  # URL
            'check_interval': {'type': 'integer', 'required': False, 'default': 300, 'description': '检查间隔(秒)'}  # 间隔
        },  # 参数结束
        'workflow': [  # 工作流
            {'tool': 'http_request', 'params': {'url': '{{url}}', 'method': 'GET'}},  # 步骤1：HTTP请求
            {'tool': 'conditional', 'params': {'condition': 'status != 200',  # 步骤2：条件判断
                                              'then': [{'tool': 'notify', 'params': {'message': '网站异常: {{url}}'}}]}}  # 异常通知
        ],  # 工作流结束
        'triggers': [{'type': 'interval', 'seconds': '{{check_interval}}'}],  # 触发器：定时触发
        'created_at': 0,  # 创建时间
        'usage_count': 0  # 使用计数
    }  # 模板5结束
]  # 预定义模板列表结束


# 全局实例  # 注释：创建全局实例
template_manager = TaskTemplateManager()  # 实例化管理器


# 便捷函数  # 注释：便捷函数
def get_template(template_id: str) -> TaskTemplate | None:  # 定义获取模板函数
    """获取模板的便捷函数"""  # 函数文档字符串
    return template_manager.get_template(template_id)  # 调用管理器方法


def list_templates(category: str = None) -> list[TaskTemplate]:  # 定义列出模板函数
    """列出模板的便捷函数"""  # 函数文档字符串
    return template_manager.list_templates(category)  # 调用管理器方法


def instantiate_template(template_id: str, params: dict) -> dict | None:  # 定义实例化模板函数
    """实例化模板的便捷函数"""  # 函数文档字符串
    return template_manager.instantiate_template(template_id, params)  # 调用管理器方法


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"任务模板系统"，提供预定义的任务模板，
# 支持定时任务、监控任务、自动化任务等场景的快速创建和执行。
#
# 【核心功能】
# 1. 模板管理: 支持模板的CRUD操作，模板持久化存储在data/templates/目录
# 2. 参数化配置: 模板支持参数定义，包括类型、必需性、默认值等
# 3. 工作流定义: 每个模板定义完整的工作流步骤，支持工具调用
# 4. 触发器配置: 支持定时、间隔等触发方式
# 5. 参数替换: instantiate_template()方法将模板参数替换为实际值
# 6. 统计功能: 记录模板使用次数和分类统计
#
# 【关联文件】
# - data/templates/*.yaml         : 模板持久化文件
# - core/logger.py                : 日志记录
#
# 【预定义模板】
# - timer_reminder: 定时提醒，延迟指定分钟后发送通知
# - system_monitor: 系统监控，CPU/内存超过阈值时告警
# - file_backup: 文件备份，自动备份指定目录
# - daily_report: 日报生成，自动生成每日工作报告
# - website_checker: 网站检查，定期检查网站可访问性
#
# 【模板结构】
# {
#     'id': '模板ID',
#     'name': '模板名称',
#     'description': '描述',
#     'category': '分类',
#     'parameters': {'参数名': {'type': '类型', 'required': true/false, 'default': '默认值'}},
#     'workflow': [{'tool': '工具名', 'params': {...}}],
#     'triggers': [{'type': '触发类型', ...}]
# }
#
# 【使用示例】
# from core.task.task_templates import template_manager
# template = template_manager.get_template('timer_reminder')
# task = template_manager.instantiate_template('timer_reminder', {
#     'message': '开会提醒',
#     'delay_minutes': 30
# })
# =============================================================================
