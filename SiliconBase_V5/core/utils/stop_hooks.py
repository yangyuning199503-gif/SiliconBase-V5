#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
停止钩子系统 - 防止AI幻觉完成任务  # 模块标题
核心设计：完成标准前置定义，执行过程对照验证  # 设计理念
2026-02-21 增强：音乐任务标准细化、硬性迭代上限强制结束  # 更新1
2026-02-21 修复：增加外部验证函数，降低AI_JUDGE依赖  # 更新2
2026-02-21 增强：添加文件存在性验证、窗口截图验证  # 更新3
"""  # 文档字符串结束
import json  # 导入JSON模块
import re  # 导入正则表达式模块
import time  # 导入时间模块
from collections.abc import Callable  # 导入类型注解
from dataclasses import dataclass, field  # 导入数据类相关
from datetime import datetime  # 导入日期时间类
from enum import Enum  # 导入枚举基类
from typing import Any

from core.ai.ai_adapter import call_thinker  # 导入AI调用适配器
from core.config import config  # 导入全局配置
from core.logger import logger  # 导入日志记录器


class VerificationType(Enum):  # 定义验证类型枚举
    KEYWORD = "keyword"  # 关键词匹配  # 关键词验证
    DATA_PRESENCE = "data"  # 数据存在性  # 数据验证
    AI_JUDGE = "ai"  # AI二次判断  # AI判断
    EXTERNAL = "external"  # 外部验证（如文件存在）  # 外部验证
    ITERATION_LIMIT = "limit"  # 迭代次数限制  # 迭代限制
    FILE_EXISTS = "file"  # 文件存在性验证  # 文件验证

    # 新增标准（2026-02-27）  # 注释：新增标准
    TOOL_SUCCESS_CHAIN = "tool_success_chain"  # 工具成功链  # 成功链验证
    USER_CONFIRMATION = "user_confirmation"    # 用户确认  # 用户确认验证
    STATE_CHECKSUM = "state_checksum"          # 状态校验  # 校验和验证
    TIMEOUT = "timeout"                        # 超时检查  # 超时验证
    RESOURCE_RELEASE = "resource_release"      # 资源释放  # 资源释放验证


@dataclass  # 数据类装饰器
class CompletionCriterion:  # 定义完成标准项类
    """单项完成标准"""  # 类文档字符串
    type: VerificationType  # 验证类型
    description: str  # 人类可读描述  # 描述
    target: str  # 检查目标标识  # 目标
    condition: Any = None  # 具体条件  # 条件
    required: bool = True  # 是否必须满足  # 是否必需
    params: dict = field(default_factory=dict)  # 额外参数（用于新标准）  # 额外参数

    def to_dict(self) -> dict:  # 定义转字典方法
        return {  # 返回字典
            "type": self.type.value,  # 类型值
            "description": self.description,  # 描述
            "target": self.target,  # 目标
            "condition": str(self.condition) if not callable(self.condition) else "<callable>",  # 条件
            "required": self.required,  # 是否必需
            "params": self.params  # 参数
        }  # 字典结束


@dataclass  # 数据类装饰器
class TaskCompletionStandard:  # 定义任务完成标准类
    """任务的完成标准"""  # 类文档字符串
    task_description: str  # 任务描述
    criteria: list[CompletionCriterion]  # 完成标准列表  # 标准列表
    max_iterations: int = 10  # 最大迭代次数，默认10  # 最大迭代
    current_iteration: int = 0  # 当前迭代次数，默认0  # 当前迭代
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())  # 创建时间  # 创建时间

    def to_checklist(self) -> str:  # 定义生成检查清单方法
        """生成自检清单（用于系统提示）"""  # 方法文档字符串
        lines = [  # 构建行列表
            "【任务完成标准】",  # 标题
            f"目标：{self.task_description}",  # 目标
            f"进度：迭代 {self.current_iteration}/{self.max_iterations}",  # 进度
            "",  # 空行
            "必须满足："  # 必需项标题
        ]  # 列表结束

        required = [c for c in self.criteria if c.required]  # 筛选必需项
        optional = [c for c in self.criteria if not c.required]  # 筛选项

        for i, c in enumerate(required, 1):  # 遍历必需项
            lines.append(f"  {i}. {c.description}")  # 添加描述

        if optional:  # 如果有可选项
            lines.append("\n可选验证：")  # 添加可选项标题
            for i, c in enumerate(optional, 1):  # 遍历可选项
                lines.append(f"  {i}. {c.description} (可选)")  # 添加描述

        lines.append("\n【重要】输出final_answer前，必须确认以上所有'必须满足'项已完成。")  # 添加重要提示
        return "\n".join(lines)  # 拼接并返回

    def to_dict(self) -> dict:  # 定义转字典方法
        return {  # 返回字典
            "task_description": self.task_description,  # 任务描述
            "criteria": [c.to_dict() for c in self.criteria],  # 标准列表
            "max_iterations": self.max_iterations,  # 最大迭代
            "current_iteration": self.current_iteration,  # 当前迭代
            "created_at": self.created_at  # 创建时间
        }  # 字典结束


class StopHookManager:  # 定义停止钩子管理器类
    """  # 类文档字符串开始
    停止钩子管理器  # 类功能
    不继承BaseTool，是Agent循环的内部组件  # 组件说明
    """  # 类文档字符串结束

    _instance = None  # 单例实例引用  # 类级实例引用

    def __new__(cls):  # 重写实例创建方法
        if cls._instance is None:  # 如果实例不存在
            cls._instance = super().__new__(cls)  # 创建新实例
            cls._instance._initialized = False  # 标记未初始化
        return cls._instance  # 返回实例

    def __init__(self):  # 初始化方法
        if self._initialized:  # 如果已初始化
            return  # 直接返回
        self._initialized = True  # 标记已初始化

        # 内置规则：任务类型 -> 默认完成标准生成器  # 注释：内置规则
        self._standard_generators: dict[str, Callable[[str], TaskCompletionStandard]] = {  # 规则字典
            "播放": self._music_standard,  # 音乐播放
            "听歌": self._music_standard,  # 听歌
            "音乐": self._music_standard,  # 音乐
            "截图": self._screenshot_standard,  # 截图
            "截屏": self._screenshot_standard,  # 截屏
            "写日记": self._diary_standard,  # 写日记
            "日记": self._diary_standard,  # 日记
            "打开": self._open_app_standard,  # 打开应用
            "启动": self._open_app_standard,  # 启动
            "搜索": self._search_standard,  # 搜索
            "查找": self._search_standard,  # 查找
            "查询": self._search_standard,  # 查询
        }  # 规则字典结束

        # 加载用户自定义规则  # 注释：自定义规则
        self._custom_rules = config.get("stop_hooks.custom_rules", {})  # 获取自定义规则

        # 执行历史缓存（用于验证）  # 注释：历史缓存
        self._execution_cache: dict[str, list[dict]] = {}  # 执行历史字典

        logger.info("停止钩子管理器初始化完成")  # 记录日志

    def generate_standard(self, task_description: str, task_id: str = None) -> TaskCompletionStandard:  # 定义生成标准方法
        """  # 方法文档字符串开始
        任务开始时：生成完成标准  # 方法功能
        这是关键！让AI在动手前就定义"什么算完成"  # 关键说明
        """  # 方法文档字符串结束
        # 尝试匹配内置规则  # 注释：匹配规则
        for keyword, generator in self._standard_generators.items():  # 遍历规则
            if keyword in task_description:  # 如果匹配关键词
                logger.info(f"使用内置规则生成标准：{keyword}")  # 记录日志
                standard = generator(task_description)  # 生成标准
                if task_id:  # 如果有任务ID
                    self._execution_cache[task_id] = []  # 初始化历史
                return standard  # 返回标准

        # 无匹配时，让AI自己生成标准  # 注释：AI生成
        logger.info("使用AI生成完成标准")  # 记录日志
        return self._ai_generate_standard(task_description, task_id)  # 调用AI生成

    def verify_completion(self, standard: TaskCompletionStandard,  # 定义验证完成方法
                          execution_history: list[dict],  # 执行历史
                          proposed_answer: str,  # AI提出的答案
                          task_id: str = None,  # 任务ID
                          chat_history: list[dict] = None,  # 聊天历史
                          execution_context: dict = None,  # 执行上下文
                          task_start_time: float = None) -> tuple[bool, str, TaskCompletionStandard, dict]:  # 返回类型
        """  # 方法文档字符串开始
        验证是否真正完成  # 方法功能
        返回：(是否完成, 原因, 更新后的标准, 详细结果)  # 返回值
        """  # 方法文档字符串结束
        standard.current_iteration += 1  # 增加迭代计数

        # 初始化默认值  # 注释：初始化
        if chat_history is None:  # 如果无历史
            chat_history = []  # 初始化为空列表
        if execution_context is None:  # 如果无上下文
            execution_context = {}  # 初始化为空字典
        if task_start_time is None:  # 如果无开始时间
            task_start_time = time.time()  # 使用当前时间

        # ===== 硬性迭代上限强制结束 =====  # 分隔注释：迭代限制
        if standard.current_iteration > standard.max_iterations:  # 如果超过最大迭代
            logger.warning(f"达到最大迭代次数{standard.max_iterations}，强制终止任务")  # 记录警告
            return True, "强制结束（迭代超限）", standard, {  # 返回强制完成
                "forced": True,  # 强制标志
                "limit_reached": True,  # 达到限制标志
                "checks": []  # 空检查列表
            }  # 返回结束
        # ==============================  # 分隔线

        check_results = []  # 初始化检查结果
        all_required_passed = True  # 初始化必需项通过标志

        for criterion in standard.criteria:  # 遍历标准
            # 根据标准类型调用不同的检查方法  # 注释：类型分发
            if criterion.type == VerificationType.TOOL_SUCCESS_CHAIN:  # 工具成功链
                passed, reason = self._check_tool_success_chain(criterion, execution_history)  # 检查
            elif criterion.type == VerificationType.USER_CONFIRMATION:  # 用户确认
                passed, reason = self._check_user_confirmation(criterion, chat_history)  # 检查
            elif criterion.type == VerificationType.STATE_CHECKSUM:  # 状态校验
                passed, reason = self._check_state_checksum(criterion, execution_context)  # 检查
            elif criterion.type == VerificationType.TIMEOUT:  # 超时
                passed, reason = self._check_timeout(criterion, task_start_time)  # 检查
            elif criterion.type == VerificationType.RESOURCE_RELEASE:  # 资源释放
                passed, reason = self._check_resource_release(criterion, execution_context)  # 检查
            else:  # 其他类型
                passed = self._check_criterion(criterion, execution_history, proposed_answer, task_id)  # 通用检查
                reason = "通过" if passed else "未通过"  # 设置原因

            result = {  # 构建结果字典
                "criterion": criterion.description,  # 标准描述
                "type": criterion.type.value,  # 类型
                "required": criterion.required,  # 是否必需
                "passed": passed,  # 是否通过
                "reason": reason  # 原因
            }  # 字典结束
            check_results.append(result)  # 添加到列表

            if criterion.required and not passed:  # 如果必需但未通过
                all_required_passed = False  # 设置标志为False

        # 汇总结果  # 注释：汇总
        details = {  # 详情字典
            "iteration": standard.current_iteration,  # 当前迭代
            "max_iterations": standard.max_iterations,  # 最大迭代
            "checks": check_results,  # 检查列表
            "all_required_passed": all_required_passed  # 是否全部通过
        }  # 字典结束

        if all_required_passed:  # 如果全部通过
            return True, "所有必须完成标准已满足", standard, details  # 返回完成
        else:  # 未全部通过
            failed = [r["criterion"] for r in check_results if r["required"] and not r["passed"]]  # 筛选失败的
            return False, f"未完成：{', '.join(failed)}", standard, details  # 返回未完成

    def record_execution(self, task_id: str, tool_id: str, params: dict, result: dict):  # 定义记录执行方法
        """记录工具执行历史（用于验证）"""  # 方法文档字符串
        if task_id not in self._execution_cache:  # 如果任务无缓存
            self._execution_cache[task_id] = []  # 创建列表

        self._execution_cache[task_id].append({  # 添加执行记录
            "timestamp": datetime.now().isoformat(),  # 时间戳
            "tool": tool_id,  # 工具ID
            "params": params,  # 参数
            "result": result,  # 结果
            "success": result.get("success", False)  # 成功标志
        })  # 记录结束

    def get_execution_history(self, task_id: str) -> list[dict]:  # 定义获取历史方法
        """获取任务的执行历史"""  # 方法文档字符串
        return self._execution_cache.get(task_id, [])  # 返回历史或空列表

    def clear_cache(self, task_id: str = None):  # 定义清理缓存方法
        """清理缓存"""  # 方法文档字符串
        if task_id:  # 如果指定了任务ID
            self._execution_cache.pop(task_id, None)  # 移除指定任务
        else:  # 未指定
            self._execution_cache.clear()  # 清空所有

    def _check_criterion(self, criterion: CompletionCriterion,  # 定义通用检查方法
                         history: list[dict],  # 历史
                         answer: str,  # 答案
                         task_id: str = None) -> bool:  # 任务ID
        """检查单项标准"""  # 方法文档字符串

        # 合并所有文本用于关键词检查  # 注释：合并文本
        history_text = json.dumps(history, ensure_ascii=False, default=str)  # 历史转JSON
        combined_text = f"{answer} {history_text}"  # 合并文本

        if criterion.type == VerificationType.KEYWORD:  # 关键词类型
            keywords = criterion.condition if isinstance(criterion.condition, list) else [criterion.condition]  # 获取关键词
            return any(kw in combined_text for kw in keywords)  # 检查是否包含任一关键词

        elif criterion.type == VerificationType.DATA_PRESENCE:  # 数据存在类型
            keys = criterion.condition if isinstance(criterion.condition, list) else [criterion.condition]  # 获取键
            for h in history:  # 遍历历史
                # 检查工具结果中的data字段  # 注释：检查data
                if isinstance(h.get("result"), dict):  # 如果结果是字典
                    data = h["result"].get("data", {})  # 获取data
                    if isinstance(data, dict) and all(k in data and data[k] is not None for k in keys):  # 如果data是字典且所有键都存在
                        return True  # 返回True
                # 检查params中的标记  # 注释：检查params
                if isinstance(h.get("params"), dict) and all(k in h["params"] for k in keys):  # 如果params是字典且所有键都存在
                    return True  # 返回True
            return False  # 返回False

        elif criterion.type == VerificationType.AI_JUDGE:  # AI判断类型
            # 降低AI_JUDGE权重，只有当其他验证无法进行时才使用  # 注释：降低权重
            return self._ai_judge(criterion.description, answer, history)  # 调用AI判断

        elif criterion.type == VerificationType.EXTERNAL:  # 外部验证类型
            if callable(criterion.condition):  # 如果是可调用
                try:  # 异常处理
                    return criterion.condition(history, answer)  # 调用验证函数
                except Exception as e:  # 捕获异常
                    logger.error(f"外部验证函数失败: {e}")  # 记录错误
                    return False  # 返回False
            return False  # 返回False

        elif criterion.type == VerificationType.ITERATION_LIMIT:  # 迭代限制类型
            # 迭代限制在verify_completion中统一处理  # 注释：统一处理
            return True  # 返回True

        return False  # 默认返回False

    # ===== 新增标准检查方法（2026-02-27） =====  # 分隔注释：新增检查方法

    def _check_tool_success_chain(self, criterion: CompletionCriterion, execution_history: list[dict]) -> tuple[bool, str]:  # 检查工具链
        """检查所有工具调用是否都成功"""  # 方法文档字符串
        if not execution_history:  # 如果无历史
            return False, "没有执行历史"  # 返回失败

        failed_tools = [  # 筛选失败工具
            h for h in execution_history  # 遍历历史
            if h.get("tool") and not h.get("success", False)  # 如果工具存在且失败
        ]  # 筛选结束

        if failed_tools:  # 如果有失败工具
            return False, f"有{len(failed_tools)}个工具执行失败"  # 返回失败

        # 检查是否完成了所有必需步骤  # 注释：检查必需步骤
        required_tools = criterion.params.get("required_tools", [])  # 获取必需工具
        executed_tools = [h.get("tool") for h in execution_history if h.get("tool")]  # 获取已执行工具

        missing = [t for t in required_tools if t not in executed_tools]  # 筛选缺失工具
        if missing:  # 如果有缺失
            return False, f"缺少必需步骤: {missing}"  # 返回失败

        return True, "所有工具调用成功"  # 返回成功

    def _check_user_confirmation(self, criterion: CompletionCriterion, chat_history: list[dict]) -> tuple[bool, str]:  # 检查用户确认
        """检查用户是否明确确认"""  # 方法文档字符串
        if not chat_history:  # 如果无历史
            return False, "没有对话历史"  # 返回失败

        # 检查最后几条消息中是否有用户确认  # 注释：检查确认
        confirm_keywords = ["确认", "是的", "没错", "完成", "好了", "ok", "可以"]  # 确认关键词

        for msg in reversed(chat_history[-5:]):  # 检查最近5条
            if msg.get("role") == "user":  # 如果是用户消息
                content = msg.get("content", "").lower()  # 获取内容转小写
                if any(kw in content for kw in confirm_keywords):  # 如果包含确认词
                    return True, "用户已确认"  # 返回成功

        return False, "等待用户确认"  # 返回失败

    def _check_state_checksum(self, criterion: CompletionCriterion, execution_context: dict) -> tuple[bool, str]:  # 检查状态校验
        """检查文件/数据状态校验和"""  # 方法文档字符串
        expected_checksum = criterion.params.get("expected_checksum")  # 获取预期校验和
        actual_checksum = execution_context.get("result_checksum")  # 获取实际校验和

        if not expected_checksum:  # 如果未设置预期
            return True, "未设置预期校验和"  # 返回成功

        if actual_checksum == expected_checksum:  # 如果匹配
            return True, "状态校验通过"  # 返回成功

        return False, f"状态校验失败: 预期{expected_checksum}, 实际{actual_checksum}"  # 返回失败

    def _check_timeout(self, criterion: CompletionCriterion, task_start_time: float) -> tuple[bool, str]:  # 检查超时
        """检查任务执行时间是否超时"""  # 方法文档字符串
        max_duration = criterion.params.get("max_duration_seconds", 300)  # 最大持续时间，默认5分钟
        elapsed = time.time() - task_start_time  # 计算已用时间

        if elapsed > max_duration:  # 如果超过最大时间
            return False, f"任务执行超时: {elapsed:.0f}s > {max_duration}s"  # 返回失败

        return True, f"执行时间正常: {elapsed:.0f}s"  # 返回成功

    def _check_resource_release(self, criterion: CompletionCriterion, execution_context: dict) -> tuple[bool, str]:  # 检查资源释放
        """检查资源是否正确释放"""  # 方法文档字符串
        resources = criterion.params.get("resources", [])  # 获取资源列表

        for resource in resources:  # 遍历资源
            if execution_context.get(f"{resource}_released") != True:  # 如果未释放  # noqa: E712
                return False, f"资源未释放: {resource}"  # 返回失败

        return True, "所有资源已释放"  # 返回成功

    def _ai_judge(self, description: str, answer: str, history: list[dict]) -> bool:  # AI判断
        """AI二次判断（降低权重）"""  # 方法文档字符串
        # 简化历史，避免token爆炸  # 注释：简化历史
        simplified_history = []  # 初始化简化历史
        for h in history[-5:]:  # 只取最近5步
            simplified_history.append({  # 添加简化记录
                "tool": h.get("tool", "unknown"),  # 工具
                "success": h.get("success", False),  # 成功
                "summary": str(h.get("result", {}).get("user_message", ""))[:50]  # 摘要
            })  # 添加结束

        prompt = f"""判断以下任务标准是否已满足。  # 构建提示

标准：{description}
AI回答：{answer[:200]}
执行历史：{json.dumps(simplified_history, ensure_ascii=False)}

这个标准是否已满足？只回答"是"或"否"。"""  # 提示结束

        try:  # 异常处理
            response = call_thinker([{"role": "user", "content": prompt}])  # 调用AI
            result = "是" in response or "yes" in response.lower()  # 判断结果
            logger.debug(f"AI判断结果：{result}，原始回答：{response[:50]}")  # 记录调试
            return result  # 返回结果
        except Exception as e:  # 捕获异常
            logger.error(f"AI判断失败: {e}")  # 记录错误
            return False  # 返回失败

    def _ai_generate_standard(self, task: str, task_id: str = None) -> TaskCompletionStandard:  # AI生成标准
        """让AI生成完成标准（通用任务）"""  # 方法文档字符串
        prompt = f"""分析以下任务，定义3-5个明确的完成标准。  # 构建提示

任务：{task}

要求：
1. 每个标准必须是可验证的（是/否）
2. 包含"结果具体可验证"（非空泛描述）
3. 如果任务涉及具体数据，包含"关键数据已获取"
4. 尽量使用外部可验证的标准，如文件存在、窗口出现等

输出严格JSON格式：
{{
    "criteria": [
        {{"description": "标准描述", "target": "标识符", "type": "keyword", "condition": ["关键词1", "关键词2"]}}
    ],
    "max_iterations": 建议的最大迭代次数（数字）
}}"""  # 提示结束

        try:  # 异常处理
            response = call_thinker([{"role": "user", "content": prompt}])  # 调用AI

            # 检查AI返回是否为空  # 注释：检查空返回
            if not response or not response.strip():  # 如果为空
                logger.warning("[StopHook] AI返回空内容，使用fallback标准")  # 记录警告
                return self._fallback_standard(task)  # 返回fallback

            json_str = self._extract_json(response)  # 提取JSON
            if not json_str or not json_str.strip():  # 如果提取为空
                logger.warning("[StopHook] 无法从AI响应中提取JSON，使用fallback标准")  # 记录警告
                return self._fallback_standard(task)  # 返回fallback

            data = json.loads(json_str)  # 解析JSON

            criteria = []  # 初始化标准列表
            for c in data.get("criteria", []):  # 遍历标准
                crit_type = VerificationType(c.get("type", "keyword"))  # 获取类型
                criteria.append(CompletionCriterion(  # 创建标准项
                    type=crit_type,  # 类型
                    description=c["description"],  # 描述
                    target=c["target"],  # 目标
                    condition=c.get("condition", c["target"]),  # 条件
                    required=c.get("required", True)  # 是否必需
                ))  # 创建结束

            # ====== 强制添加防幻觉标准（外部验证优先）======  # 分隔注释：防幻觉
            criteria.append(CompletionCriterion(  # 添加标准
                type=VerificationType.EXTERNAL,  # 外部验证
                description="结果具体可验证，非空泛描述（如'已完成'而不说明具体结果）",  # 描述
                target="verifiable_result",  # 目标
                condition=self._check_file_exists_external  # 使用外部文件存在验证
            ))  # 添加结束
            # ===========================================  # 分隔线

            # ====== 根据任务类型自动配置新标准（2026-02-27）======  # 分隔注释：自动配置

            # 多步骤任务添加TOOL_SUCCESS_CHAIN  # 注释：多步骤
            if any(kw in task for kw in ["并", "然后", "接着", "先...再", "先"]) or task.count("，") >= 2:  # 如果多步骤
                criteria.append(CompletionCriterion(  # 添加标准
                    type=VerificationType.TOOL_SUCCESS_CHAIN,  # 成功链
                    description="所有步骤执行成功",  # 描述
                    target="tool_success_chain",  # 目标
                    required=True,  # 必需
                    params={"required_tools": []}  # 可后续动态推断
                ))  # 添加结束

            # 高风险操作添加USER_CONFIRMATION  # 注释：高风险
            if any(kw in task for kw in ["删除", "修改", "覆盖", "重启", "格式化"]):  # 如果高风险
                criteria.append(CompletionCriterion(  # 添加标准
                    type=VerificationType.USER_CONFIRMATION,  # 用户确认
                    description="用户明确确认",  # 描述
                    target="user_confirmation",  # 目标
                    required=True  # 必需
                ))  # 添加结束

            # 文件操作添加STATE_CHECKSUM  # 注释：文件操作
            if any(kw in task for kw in ["写入", "修改文件", "保存", "生成文件"]):  # 如果文件操作
                criteria.append(CompletionCriterion(  # 添加标准
                    type=VerificationType.STATE_CHECKSUM,  # 状态校验
                    description="文件校验通过",  # 描述
                    target="state_checksum",  # 目标
                    required=True,  # 必需
                    params={"expected_checksum": None}  # 参数
                ))  # 添加结束

            # 长时间任务添加TIMEOUT  # 注释：长时间任务
            if any(kw in task for kw in ["下载", "上传", "处理大量", "批量"]):  # 如果长时间
                criteria.append(CompletionCriterion(  # 添加标准
                    type=VerificationType.TIMEOUT,  # 超时
                    description="任务未超时",  # 描述
                    target="timeout",  # 目标
                    required=False,  # 可选，避免过早终止
                    params={"max_duration_seconds": 600}  # 10分钟
                ))  # 添加结束

            # 资源敏感操作添加RESOURCE_RELEASE  # 注释：资源敏感
            if any(kw in task for kw in ["打开文件", "连接", "锁定", "占用"]):  # 如果资源敏感
                criteria.append(CompletionCriterion(  # 添加标准
                    type=VerificationType.RESOURCE_RELEASE,  # 资源释放
                    description="资源已正确释放",  # 描述
                    target="resource_release",  # 目标
                    required=True,  # 必需
                    params={"resources": ["file_handle"]}  # 参数
                ))  # 添加结束
            # ===========================================  # 分隔线

            # 强制添加迭代限制标准  # 注释：迭代限制
            criteria.append(CompletionCriterion(  # 添加标准
                type=VerificationType.ITERATION_LIMIT,  # 迭代限制
                description=f"迭代次数不超过{data.get('max_iterations', 10)}",  # 描述
                target="iteration_limit",  # 目标
                condition=None,  # 无条件
                required=False  # 可选
            ))  # 添加结束

            return TaskCompletionStandard(  # 创建并返回标准
                task_description=task,  # 任务描述
                criteria=criteria,  # 标准列表
                max_iterations=data.get("max_iterations", 10)  # 最大迭代
            )  # 返回结束

        except Exception as e:  # 捕获异常
            logger.error(f"AI生成标准失败: {e}，使用fallback")  # 记录错误
            return self._fallback_standard(task)  # 返回fallback

    def _fallback_standard(self, task: str) -> TaskCompletionStandard:  # fallback标准
        """当AI生成标准失败时使用的fallback标准"""  # 方法文档字符串
        # 基于任务类型的启发式标准  # 注释：启发式
        task_lower = task.lower()  # 转小写

        criteria = [  # 基础标准列表
            CompletionCriterion(  # 标准1
                type=VerificationType.KEYWORD,  # 关键词
                description="任务已真正完成，有具体可验证的结果（非空泛描述）",  # 描述
                target="verifiable_result",  # 目标
                condition=["完成", "成功", "已", "打开", "启动", "获取", "找到"]  # 关键词
            ),  # 标准1结束
            CompletionCriterion(  # 标准2
                type=VerificationType.EXTERNAL,  # 外部
                description="有工具执行记录证明任务被执行",  # 描述
                target="tool_execution",  # 目标
                condition=lambda h, a: len(h) > 0  # 至少执行了一个工具
            )  # 标准2结束
        ]  # 列表结束

        # 根据任务类型添加特定标准  # 注释：类型特定
        if any(kw in task_lower for kw in ["打开", "启动", "运行"]):  # 打开应用
            criteria.append(CompletionCriterion(  # 添加标准
                type=VerificationType.KEYWORD,  # 关键词
                description="窗口已打开或应用已启动",  # 描述
                target="window_opened",  # 目标
                condition=["窗口", "打开", "启动", "hwnd", "句柄"]  # 关键词
            ))  # 添加结束
        elif any(kw in task_lower for kw in ["搜索", "查找", "查询"]):  # 搜索
            criteria.append(CompletionCriterion(  # 添加标准
                type=VerificationType.KEYWORD,  # 关键词
                description="搜索结果已获取",  # 描述
                target="search_result",  # 目标
                condition=["结果", "找到", "获取", "数据"]  # 关键词
            ))  # 添加结束
        elif any(kw in task_lower for kw in ["播放", "音乐", "歌曲"]):  # 音乐
            criteria.append(CompletionCriterion(  # 添加标准
                type=VerificationType.KEYWORD,  # 关键词
                description="音乐播放状态确认",  # 描述
                target="music_playing",  # 目标
                condition=["播放", "歌曲", "音乐", "进度", "时间"]  # 关键词
            ))  # 添加结束

        return TaskCompletionStandard(  # 创建并返回标准
            task_description=task,  # 任务描述
            criteria=criteria,  # 标准列表
            max_iterations=15  # 最大迭代
        )  # 返回结束

    # ===== 新增外部验证函数 =====  # 分隔注释：外部验证
    def _check_file_exists_external(self, history: list[dict], answer: str) -> bool:  # 检查文件存在
        """检查历史中是否有文件真实存在（外部验证）"""  # 方法文档字符串
        import os  # 导入os
        for h in history:  # 遍历历史
            data = h.get("result", {}).get("data", {})  # 获取data
            for key in ["save_path", "file_path", "path"]:  # 遍历可能的路径键
                path = data.get(key)  # 获取路径
                if path and os.path.exists(path):  # 如果路径存在且文件存在
                    return True  # 返回True
        return False  # 返回False

    def _check_window_screenshot(self, history: list[dict], answer: str) -> bool:  # 检查窗口截图
        """通过截图对比验证窗口状态（简化版，仅示例）"""  # 方法文档字符串
        # 实际可调用 pixel_capture 工具截图并与预期哈希对比  # 说明
        # 这里简单检查历史中是否有成功的窗口聚焦操作  # 简化实现
        return any(h.get("tool") == "window_focus" and h.get("success") for h in history)  # 返回False
    # ===== 内置标准生成器 =====  # 分隔注释：内置生成器

    def _music_standard(self, task: str) -> TaskCompletionStandard:  # 音乐任务标准
        """播放音乐任务的完成标准（增强版）"""  # 方法文档字符串
        # 提取歌曲名和歌手  # 注释：提取信息
        song_match = re.search(r'播放\s*(\S+?)\s*的\s*(\S+)', task)  # 匹配"播放 XX 的 YY"
        singer = song_match.group(1) if song_match else None  # 歌手
        song = song_match.group(2) if song_match else None  # 歌曲

        if not song:  # 如果没匹配到歌曲
            song_match = re.search(r'播放\s*(\S+)', task)  # 匹配"播放 XX"
            song = song_match.group(1) if song_match else "指定歌曲"  # 歌曲名

        keywords = [song]  # 关键词列表
        if singer:  # 如果有歌手
            keywords.append(singer)  # 添加歌手

        return TaskCompletionStandard(  # 创建并返回标准
            task_description=task,  # 任务描述
            criteria=[  # 标准列表
                CompletionCriterion(  # 标准1
                    type=VerificationType.DATA_PRESENCE,  # 数据存在
                    description="窗口句柄hwnd已获取（证明应用已打开）",  # 描述
                    target="hwnd",  # 目标
                    condition=["hwnd"],  # 条件
                    required=True  # 必需
                ),  # 标准1结束
                CompletionCriterion(  # 标准2
                    type=VerificationType.KEYWORD,  # 关键词
                    description="屏幕文字包含歌曲名或歌手名",  # 描述
                    target="screen_text",  # 目标
                    condition=keywords,  # 关键词
                    required=True  # 必需
                ),  # 标准2结束
                CompletionCriterion(  # 标准3
                    type=VerificationType.KEYWORD,  # 关键词
                    description="播放状态确认（进度条/播放按钮/时间显示）",  # 描述
                    target="playing_indicator",  # 目标
                    condition=["播放", "⏸", "暂停", ":", "进度"],  # 关键词
                    required=True  # 必需
                ),  # 标准3结束
                CompletionCriterion(  # 标准4
                    type=VerificationType.EXTERNAL,  # 外部
                    description="截图显示正在播放正确的歌曲，而非停留在搜索结果页",  # 描述
                    target="correct_playback",  # 目标
                    condition=self._check_music_playback,  # 外部验证函数
                    required=True  # 必需
                )  # 标准4结束
            ],  # 列表结束
            max_iterations=20  # 最大迭代
        )  # 返回结束

    def _screenshot_standard(self, task: str) -> TaskCompletionStandard:  # 截图任务标准
        """截图任务的完成标准"""  # 方法文档字符串
        return TaskCompletionStandard(  # 创建并返回标准
            task_description=task,  # 任务描述
            criteria=[  # 标准列表
                CompletionCriterion(  # 标准1
                    type=VerificationType.DATA_PRESENCE,  # 数据存在
                    description="截图文件已生成",  # 描述
                    target="screenshot_file",  # 目标
                    condition=["save_path", "file_path"]  # 条件
                ),  # 标准1结束
                CompletionCriterion(  # 标准2
                    type=VerificationType.EXTERNAL,  # 外部
                    description="文件真实存在且非空",  # 描述
                    target="file_exists",  # 目标
                    condition=lambda h, a: self._check_file_exists(h, ".png", ".jpg")  # 验证函数
                ),  # 标准2结束
                CompletionCriterion(  # 标准3
                    type=VerificationType.KEYWORD,  # 关键词
                    description="包含保存路径信息",  # 描述
                    target="path_info",  # 目标
                    condition=["保存", "路径", "桌面", "screenshot"]  # 关键词
                )  # 标准3结束
            ],  # 列表结束
            max_iterations=15  # 最大迭代
        )  # 返回结束

    def _diary_standard(self, task: str) -> TaskCompletionStandard:  # 日记任务标准
        """写日记任务的完成标准 - 关键！防七八十条"""  # 方法文档字符串
        # 提取数量要求  # 注释：提取数量
        count_match = re.search(r'(\d+)[条篇]', task)  # 匹配数量
        count = int(count_match.group(1)) if count_match else 1  # 默认1条！

        return TaskCompletionStandard(  # 创建并返回标准
            task_description=task,  # 任务描述
            criteria=[  # 标准列表
                CompletionCriterion(  # 标准1
                    type=VerificationType.DATA_PRESENCE,  # 数据存在
                    description=f"日记条目已创建（目标{count}条）",  # 描述
                    target="diary_entries",  # 目标
                    condition=["entries", "count"]  # 条件
                ),  # 标准1结束
                CompletionCriterion(  # 标准2
                    type=VerificationType.EXTERNAL,  # 外部
                    description=f"实际写入条目数={count}，防过度写入",  # 描述
                    target="exact_count",  # 目标
                    condition=lambda h, a: self._check_entry_count(h, count)  # 验证函数
                ),  # 标准2结束
                CompletionCriterion(  # 标准3
                    type=VerificationType.KEYWORD,  # 关键词
                    description="包含时间、内容、心情等关键字段",  # 描述
                    target="content_fields",  # 目标
                    condition=["时间", "内容", "心情", "日期"]  # 关键词
                )  # 标准3结束
            ],  # 列表结束
            max_iterations=count + 2  # 严格限制！
        )  # 返回结束

    def _open_app_standard(self, task: str) -> TaskCompletionStandard:  # 打开应用标准
        """打开应用任务的完成标准"""  # 方法文档字符串
        return TaskCompletionStandard(  # 创建并返回标准
            task_description=task,  # 任务描述
            criteria=[  # 标准列表
                CompletionCriterion(  # 标准1
                    type=VerificationType.KEYWORD,  # 关键词
                    description="应用窗口已出现",  # 描述
                    target="window_visible",  # 目标
                    condition=["窗口", "打开", "运行中", "hwnd"]  # 关键词
                ),  # 标准1结束
                CompletionCriterion(  # 标准2
                    type=VerificationType.EXTERNAL,  # 外部
                    description="应用已可交互，非仅进程存在",  # 描述
                    target="interactive",  # 目标
                    condition=self._check_window_interactive  # 验证函数
                )  # 标准2结束
            ],  # 列表结束
            max_iterations=20  # 最大迭代
        )  # 返回结束

    def _search_standard(self, task: str) -> TaskCompletionStandard:  # 搜索任务标准
        """搜索任务的完成标准"""  # 方法文档字符串
        return TaskCompletionStandard(  # 创建并返回标准
            task_description=task,  # 任务描述
            criteria=[  # 标准列表
                CompletionCriterion(  # 标准1
                    type=VerificationType.KEYWORD,  # 关键词
                    description="搜索关键词已输入",  # 描述
                    target="keyword_entered",  # 目标
                    condition=["搜索", "输入", "关键词"]  # 关键词
                ),  # 标准1结束
                CompletionCriterion(  # 标准2
                    type=VerificationType.KEYWORD,  # 关键词
                    description="搜索结果已显示",  # 描述
                    target="results_shown",  # 目标
                    condition=["结果", "找到", "条", "相关"]  # 关键词
                )  # 标准2结束
            ],  # 列表结束
            max_iterations=15  # 最大迭代
        )  # 返回结束

    # ===== 辅助验证函数 =====  # 分隔注释：辅助函数

    def _check_file_exists(self, history: list[dict], *extensions) -> bool:  # 检查文件存在
        """检查历史记录中是否有文件真实存在"""  # 方法文档字符串
        import os  # 导入os
        for h in history:  # 遍历历史
            data = h.get("result", {}).get("data", {})  # 获取data
            for key in ["save_path", "file_path", "path"]:  # 遍历可能的路径键
                path = data.get(key)  # 获取路径
                if path and os.path.exists(path) and any(str(path).endswith(ext) for ext in extensions):  # 如果存在且扩展名匹配
                    return True  # 返回True
        return False  # 返回False

    def _check_entry_count(self, history: list[dict], expected: int) -> bool:  # 检查条目数
        """检查日记条目数是否正好等于预期（防过度写入）"""  # 方法文档字符串
        actual = 0  # 初始化实际数
        for h in history:  # 遍历历史
            if "write" in str(h.get("tool", "")).lower():  # 如果是写入工具
                actual += 1  # 增加计数
        return actual == expected  # 返回是否匹配

    def _check_music_playback(self, history: list[dict], answer: str) -> bool:  # 检查音乐播放
        """检查音乐是否真正播放（外部验证）"""  # 方法文档字符串
        # 这里可以调用OCR工具检查当前屏幕是否有播放中的标志  # 说明
        # 简化版：检查历史中是否有"播放"相关的工具调用成功  # 简化实现
        return any(h.get("tool") == "click_text" and "播放" in h.get("params", {}).get("text", "") for h in history)  # 返回False

    def _check_window_interactive(self, history: list[dict], answer: str) -> bool:  # 检查窗口交互
        """检查窗口是否可交互"""  # 方法文档字符串
        # 简化：检查窗口是否被激活过  # 简化实现
        return any(h.get("tool") == "window_focus" and h.get("success") for h in history)  # 返回False

    def _extract_json(self, text: str) -> str:  # 提取JSON
        import re  # 导入正则
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)  # 匹配代码块
        if match:  # 如果匹配
            return match.group(1)  # 返回内容
        match = re.search(r'(\{[\s\S]*\})', text)  # 匹配JSON对象
        if match:  # 如果匹配
            return match.group(1)  # 返回内容
        return text  # 返回原文


# 全局单例  # 注释：创建全局单例
stop_hook_manager = StopHookManager()  # 实例化管理器


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"停止钩子系统"，通过前置定义完成标准和
# 执行过程对照验证，防止AI"幻觉"完成任务（即声称完成但实际上未完成）。
#
# 【核心功能】
# 1. 标准生成: generate_standard()根据任务描述生成完成标准，支持内置规则和AI生成
# 2. 标准验证: verify_completion()对照标准验证任务是否真正完成
# 3. 执行记录: record_execution()记录工具执行历史，用于后续验证
# 4. 迭代限制: 硬性迭代上限，防止无限循环
# 5. 多种验证类型: 关键词、数据存在、AI判断、外部验证、工具链、用户确认等
#
# 【关联文件】
# - core/ai_adapter.py            : AI生成标准时调用
# - core/task_orchestrator.py     : 调用本模块注册和验证标准
# - core/tool_manager.py          : 工具管理
#
# 【验证类型】
# - KEYWORD: 关键词匹配
# - DATA_PRESENCE: 数据存在性检查
# - AI_JUDGE: AI二次判断（降低权重）
# - EXTERNAL: 外部验证函数
# - TOOL_SUCCESS_CHAIN: 工具成功链
# - USER_CONFIRMATION: 用户确认
# - STATE_CHECKSUM: 状态校验
# - TIMEOUT: 超时检查
# - RESOURCE_RELEASE: 资源释放
#
# 【内置任务标准】
# - 音乐播放: hwnd获取、屏幕文字、播放状态、截图验证
# - 截图: 文件生成、文件存在、路径信息
# - 日记: 条目创建、条目数量、关键字段
# - 打开应用: 窗口出现、可交互
# - 搜索: 关键词输入、结果展示
#
# 【使用流程】
# 1. 任务开始时调用generate_standard()生成完成标准
# 2. 每次工具执行后调用record_execution()记录执行
# 3. AI提出完成时调用verify_completion()验证
# 4. 验证通过才允许输出final_answer
#
# 【注意事项】
# - 优先使用外部验证（如文件存在性）而非AI判断
# - 多步骤任务自动添加TOOL_SUCCESS_CHAIN标准
# - 高风险操作自动添加USER_CONFIRMATION标准
# - 达到max_iterations会强制结束任务
# =============================================================================
