#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""
实验管理器 - RD-Agent核心组件
管理策略实验的AB测试系统

功能：
1. 启动假设验证实验
2. 分配任务到实验组/对照组
3. 收集多维反馈（使用ValueSystemV2的六维度）
4. 分析实验结果
"""

import json  # 导入JSON模块：用于序列化/反序列化数据
import time  # 导入时间模块：用于获取时间戳
import uuid  # 导入UUID模块：用于生成唯一标识符
from dataclasses import dataclass, field  # 从dataclasses导入数据类装饰器和字段
from enum import Enum  # 从enum导入枚举类基类

from core.logger import logger  # 从core.logger导入日志记录器
from core.memory.memory_service import get_memory_service  # 【P1-迁移】使用新 MemoryService
from core.memory.memory_source import MemorySource  # Agent-4: 导入MemorySource枚举
from core.strategy.value_system_v2 import ValueAssessmentV2, ValueDimension, ValueSystemV2  # 导入价值系统V2相关类


class ExperimentStatus(Enum):  # 定义实验状态枚举类
    """实验状态"""  # 类文档字符串：描述实验的各种状态
    PENDING = "pending"  # 待启动状态：实验已创建但未开始
    RUNNING = "running"  # 进行中状态：实验正在运行
    COMPLETED = "completed"  # 已完成状态：实验已结束
    CANCELLED = "cancelled"  # 已取消状态：实验被手动取消


class ExperimentGroup(Enum):  # 定义实验分组枚举类
    """实验分组"""  # 类文档字符串：描述AB测试的两组
    CONTROL = "control"  # 对照组（使用默认策略）
    TEST = "test"  # 实验组（使用新策略）


@dataclass  # 使用数据类装饰器自动生成特殊方法
class TaskAssignment:  # 定义任务分配记录数据类
    """任务分配记录"""  # 类文档字符串：记录任务与实验的关联
    task_id: str  # 任务ID：唯一标识一个任务
    experiment_id: str  # 实验ID：标识所属实验
    group: ExperimentGroup  # 分配到的组别：CONTROL或TEST
    assigned_at: float = field(default_factory=time.time)  # 分配时间戳：默认为当前时间
    completed: bool = False  # 完成标志：任务是否已完成
    value_assessment: dict | None = None  # 价值评估结果：六维度评估数据
    execution_result: dict | None = None  # 执行结果：任务执行详情

    def to_dict(self) -> dict:  # 定义转换为字典的方法
        return {  # 返回字典表示形式
            "task_id": self.task_id,  # 任务ID字段
            "experiment_id": self.experiment_id,  # 实验ID字段
            "group": self.group.value,  # 组别枚举值
            "assigned_at": self.assigned_at,  # 分配时间字段
            "completed": self.completed,  # 完成状态字段
            "value_assessment": self.value_assessment,  # 价值评估字段
            "execution_result": self.execution_result  # 执行结果字段
        }


@dataclass  # 使用数据类装饰器
class ExperimentResult:  # 定义实验结果统计数据类
    """实验结果统计"""  # 类文档字符串：存储实验分析结果
    total_tasks: int = 0  # 总任务数：对照组+实验组
    control_tasks: int = 0  # 对照组任务数
    test_tasks: int = 0  # 实验组任务数
    control_success: int = 0  # 对照组成功数
    test_success: int = 0  # 实验组成功数
    control_avg_score: float = 0.0  # 对照组平均价值分数
    test_avg_score: float = 0.0  # 实验组平均价值分数
    dimension_comparison: dict = field(default_factory=dict)  # 各维度对比数据
    conclusion: str = ""  # 实验结论文字描述
    recommendation: str = ""  # 策略建议：promote/continue/reject/observe

    def to_dict(self) -> dict:  # 定义转换为字典的方法
        return {  # 返回字典表示形式
            "total_tasks": self.total_tasks,  # 总任务数字段
            "control_tasks": self.control_tasks,  # 对照组任务数字段
            "test_tasks": self.test_tasks,  # 实验组任务数字段
            "control_success": self.control_success,  # 对照组成功数字段
            "test_success": self.test_success,  # 实验组成功数字段
            "control_success_rate": self.control_success / self.control_tasks if self.control_tasks > 0 else 0,
            # 对照组成功率计算
            "test_success_rate": self.test_success / self.test_tasks if self.test_tasks > 0 else 0,  # 实验组成功率计算
            "control_avg_score": round(self.control_avg_score, 2),  # 对照组平均分（保留2位小数）
            "test_avg_score": round(self.test_avg_score, 2),  # 实验组平均分（保留2位小数）
            "score_improvement": round(self.test_avg_score - self.control_avg_score, 2),  # 分数提升值计算
            "dimension_comparison": self.dimension_comparison,  # 维度对比数据字段
            "conclusion": self.conclusion,  # 结论字段
            "recommendation": self.recommendation  # 建议字段
        }


class ExperimentManager:  # 定义实验管理器类
    """
    实验管理器 - 策略AB测试系统  # 类文档字符串标题

    工作原理：  # 工作原理列表
    1. 接收来自HypothesisGenerator的假设  # 步骤1：接收假设
    2. 创建实验（实验组 vs 对照组）  # 步骤2：创建实验
    3. 将任务随机分配到两组  # 步骤3：分配任务
    4. 收集执行结果和价值评估  # 步骤4：收集反馈
    5. 统计分析得出结论  # 步骤5：分析结果
    """  # 类文档字符串结束

    def __init__(self):  # 初始化方法
        self.active_experiments: dict[str, dict] = {}  # 活跃实验字典：存储正在进行的实验
        self.experiment_history: dict[str, dict] = {}  # 实验历史字典：存储已完成的实验
        self.task_assignments: dict[str, TaskAssignment] = {}  # 任务分配记录字典
        self.value_system = ValueSystemV2()  # 创建价值系统实例用于评估
        self._loaded = False  # 延迟加载标志
        logger.info("[ExperimentManager] 实验管理器已初始化")  # 记录初始化完成日志

    async def _ensure_loaded(self):
        """确保历史实验已加载"""
        if not self._loaded:
            await self._load_existing_experiments()
            self._loaded = True

    async def _load_existing_experiments(self):  # 定义私有方法：加载历史实验
        """加载历史实验"""  # 方法文档字符串
        try:  # 开始异常处理块
            ms = await get_memory_service()
            records = await ms.query_memories(user_id="default_user", layer="evolve", mem_type="experiment", limit=50)  # 从记忆系统获取实验记录，最多50条
            for record in records:  # 遍历获取到的记录列表
                try:  # 嵌套异常处理
                    content = json.loads(record["content"])  # 解析JSON格式的记录内容
                    exp_id = content.get("id")  # 从内容中获取实验ID
                    if exp_id:  # 如果实验ID存在
                        self.experiment_history[exp_id] = content  # 将实验添加到历史字典
                except Exception as e:  # 捕获解析异常
                    logger.debug(f"[ExperimentManager] 加载实验失败: {e}")  # 记录调试级别的错误日志
            logger.info(f"[ExperimentManager] 已加载 {len(self.experiment_history)} 个历史实验")  # 记录加载数量
        except Exception as e:  # 捕获整体异常
            logger.warning(f"[ExperimentManager] 加载历史实验失败: {e}")  # 记录警告日志

    async def start_experiment(self, hypothesis: dict, duration_tasks: int = 10) -> str:  # 定义启动实验方法
        """
        启动新实验  # 方法文档字符串标题

        Args:  # 参数说明
            hypothesis: 假设数据（来自HypothesisGenerator）  # 假设参数
            duration_tasks: 计划测试的任务数量  # 任务数量参数

        Returns:  # 返回值说明
            实验ID  # 返回唯一实验标识符
        """  # 方法文档字符串结束
        exp_id = f"exp_{int(time.time())}_{uuid.uuid4().hex[:8]}"  # 生成唯一实验ID：前缀+时间戳+UUID前8位

        experiment = {  # 创建实验数据字典
            "id": exp_id,  # 实验ID字段
            "hypothesis": hypothesis,  # 假设数据字段
            "status": ExperimentStatus.RUNNING.value,  # 状态设为进行中
            "created_at": time.time(),  # 创建时间戳
            "duration_tasks": duration_tasks,  # 计划任务数量
            "test_group": [],  # 实验组任务ID列表（初始为空）
            "control_group": [],  # 对照组任务ID列表（初始为空）
            "results": {  # 结果统计数据
                "test": {  # 实验组结果数据
                    "count": 0,  # 任务计数初始为0
                    "success": 0,  # 成功计数初始为0
                    "value_scores": [],  # 价值分数列表（初始为空）
                    "dimension_scores": {dim.value: [] for dim in ValueDimension}  # 各维度分数字典
                },
                "control": {  # 对照组结果数据
                    "count": 0,  # 任务计数初始为0
                    "success": 0,  # 成功计数初始为0
                    "value_scores": [],  # 价值分数列表（初始为空）
                    "dimension_scores": {dim.value: [] for dim in ValueDimension}  # 各维度分数字典
                }
            }
        }

        self.active_experiments[exp_id] = experiment  # 将实验添加到活跃实验字典
        await self._store_experiment(experiment)  # 调用存储方法保存到记忆系统

        logger.info(
            f"[ExperimentManager] 启动实验 [{exp_id}]: {hypothesis.get('description', '无描述')[:60]}...")  # 记录启动日志
        logger.info(f"[ExperimentManager] 计划测试 {duration_tasks} 个任务")  # 记录计划任务数

        return exp_id  # 返回实验ID

    def assign_task(self,  # 定义分配任务方法
                    exp_id: str,  # 参数：实验ID
                    task_id: str,  # 参数：任务ID
                    is_test: bool | None = None  # 参数：是否分配到实验组，None则随机分配
                    ) -> ExperimentGroup:  # 返回：分配到的组别枚举
        """
        将任务分配到实验组或对照组  # 方法文档字符串标题

        Args:  # 参数说明
            exp_id: 实验ID  # 实验标识符
            task_id: 任务ID  # 任务标识符
            is_test: 是否分配到实验组，None则随机分配  # 组别指定参数

        Returns:  # 返回值说明
            分配到的组别  # 返回CONTROL或TEST
        """  # 方法文档字符串结束
        if exp_id not in self.active_experiments:  # 检查实验是否存在
            logger.warning(f"[ExperimentManager] 实验 {exp_id} 不存在")  # 记录警告日志
            return ExperimentGroup.CONTROL  # 实验不存在时默认返回对照组

        experiment = self.active_experiments[exp_id]  # 获取实验数据字典

        # 随机分配（如果未指定）
        if is_test is None:  # 如果未指定组别
            # 简单的交替分配，保持两组数量均衡
            test_count = len(experiment["test_group"])  # 获取实验组当前任务数量
            control_count = len(experiment["control_group"])  # 获取对照组当前任务数量
            is_test = test_count <= control_count  # 哪组数量少就分配到哪组

        group = ExperimentGroup.TEST if is_test else ExperimentGroup.CONTROL  # 根据布尔值确定组别
        group_key = "test_group" if is_test else "control_group"  # 确定字典键名

        # 记录分配
        experiment[group_key].append(task_id)  # 将任务ID添加到对应组的列表

        assignment = TaskAssignment(  # 创建任务分配记录对象
            task_id=task_id,  # 设置任务ID
            experiment_id=exp_id,  # 设置实验ID
            group=group  # 设置组别
        )
        self.task_assignments[task_id] = assignment  # 保存分配记录到字典

        logger.debug(f"[ExperimentManager] 任务 {task_id[:8]} 分配到 {group.value} 组")  # 记录调试日志

        return group  # 返回分配到的组别

    async def collect_feedback(self,  # 定义收集反馈方法
                         exp_id: str,  # 参数：实验ID
                         task_id: str,  # 参数：任务ID
                         value_assessment: ValueAssessmentV2,  # 参数：价值评估结果（六维度）
                         execution_success: bool = True,  # 参数：任务是否执行成功（默认为是）
                         execution_result: dict | None = None  # 参数：执行结果详情（可选）
                         ):  # 方法定义结束
        """
        收集实验反馈  # 方法文档字符串标题

        Args:  # 参数说明
            exp_id: 实验ID  # 实验标识符
            task_id: 任务ID  # 任务标识符
            value_assessment: 价值评估结果（六维度）  # 价值评估对象
            execution_success: 任务是否执行成功  # 成功标志
            execution_result: 执行结果详情  # 执行详情字典
        """  # 方法文档字符串结束
        if exp_id not in self.active_experiments:  # 检查实验是否存在
            logger.warning(f"[ExperimentManager] 实验 {exp_id} 不存在，无法收集反馈")  # 记录警告
            return  # 直接返回，不执行后续操作

        experiment = self.active_experiments[exp_id]  # 获取实验数据

        # 确定任务属于哪一组
        if task_id in experiment["test_group"]:  # 检查任务是否在实验组
            group_key = "test"  # 设置组键为test
        elif task_id in experiment["control_group"]:  # 检查任务是否在对照组
            group_key = "control"  # 设置组键为control
        else:  # 任务不在任何组
            logger.warning(f"[ExperimentManager] 任务 {task_id} 不在实验 {exp_id} 中")  # 记录警告
            return  # 直接返回

        results = experiment["results"][group_key]  # 获取该组的结果字典
        results["count"] += 1  # 增加任务计数
        if execution_success:  # 如果执行成功
            results["success"] += 1  # 增加成功计数
        results["value_scores"].append(value_assessment.overall_score)  # 添加价值总分到列表

        # 收集各维度评分
        for dim, score in value_assessment.dimension_scores.items():  # 遍历维度分数字典
            results["dimension_scores"][dim.value].append(score)  # 将分数添加到对应维度列表

        # 更新任务分配记录
        if task_id in self.task_assignments:  # 检查是否存在分配记录
            assignment = self.task_assignments[task_id]  # 获取分配记录
            assignment.completed = True  # 标记任务为已完成
            assignment.value_assessment = value_assessment.to_dict() if hasattr(value_assessment,
                                                                                'to_dict') else value_assessment  # 保存评估结果
            assignment.execution_result = execution_result  # 保存执行结果

        # 更新存储
        await self._store_experiment(experiment)  # 调用存储方法更新记忆系统

        logger.debug(f"[ExperimentManager] 实验 {exp_id[:8]} 收集反馈: "  # 记录调试日志开始
                     f"{group_key}组 task={task_id[:8]}, score={value_assessment.overall_score}")  # 日志内容

        # 检查实验是否完成
        self._check_experiment_completion(exp_id)  # 调用方法检查完成条件

    def _check_experiment_completion(self, exp_id: str):  # 定义检查实验完成方法
        """检查实验是否达到完成条件"""  # 方法文档字符串
        experiment = self.active_experiments[exp_id]  # 获取实验数据
        test_count = experiment["results"]["test"]["count"]  # 获取实验组任务数
        control_count = experiment["results"]["control"]["count"]  # 获取对照组任务数
        total = test_count + control_count  # 计算总任务数

        # 完成条件：达到计划数量或两组都有足够样本
        if total >= experiment["duration_tasks"] or (test_count >= 5 and control_count >= 5):  # 检查完成条件
            logger.info(f"[ExperimentManager] 实验 {exp_id} 达到完成条件，准备分析...")  # 记录日志
            # 不自动结束，等待显式调用analyze_experiment

    async def analyze_experiment(self, exp_id: str) -> ExperimentResult:  # 定义分析实验方法
        """
        分析实验结果  # 方法文档字符串标题

        Args:  # 参数说明
            exp_id: 实验ID  # 实验标识符

        Returns:  # 返回值说明
            实验结果分析  # 返回ExperimentResult对象
        """  # 方法文档字符串结束
        if exp_id not in self.active_experiments:  # 检查实验是否存在
            raise ValueError(f"实验 {exp_id} 不存在")  # 抛出值错误异常

        experiment = self.active_experiments[exp_id]  # 获取实验数据
        results = experiment["results"]  # 获取结果数据

        result = ExperimentResult()  # 创建实验结果对象

        # 对照组统计
        control = results["control"]  # 获取对照组数据
        result.control_tasks = control["count"]  # 设置对照组任务数
        result.control_success = control["success"]  # 设置对照组成功数
        if control["value_scores"]:  # 如果对照组有价值分数
            result.control_avg_score = sum(control["value_scores"]) / len(control["value_scores"])  # 计算平均分

        # 实验组统计
        test = results["test"]  # 获取实验组数据
        result.test_tasks = test["count"]  # 设置实验组任务数
        result.test_success = test["success"]  # 设置实验组成功数
        if test["value_scores"]:  # 如果实验组有价值分数
            result.test_avg_score = sum(test["value_scores"]) / len(test["value_scores"])  # 计算平均分

        result.total_tasks = result.control_tasks + result.test_tasks  # 计算总任务数

        # 各维度对比
        for dim in ValueDimension:  # 遍历所有价值维度枚举
            control_scores = control["dimension_scores"].get(dim.value, [])  # 获取对照组该维度分数列表
            test_scores = test["dimension_scores"].get(dim.value, [])  # 获取实验组该维度分数列表

            control_avg = sum(control_scores) / len(control_scores) if control_scores else 0  # 计算对照组平均分
            test_avg = sum(test_scores) / len(test_scores) if test_scores else 0  # 计算实验组平均分

            result.dimension_comparison[dim.value] = {  # 保存维度对比数据
                "control_avg": round(control_avg, 2),  # 对照组平均分（保留2位）
                "test_avg": round(test_avg, 2),  # 实验组平均分（保留2位）
                "improvement": round(test_avg - control_avg, 2)  # 提升值（实验组-对照组）
            }

        # 得出结论
        result.conclusion = self._generate_conclusion(result)  # 调用方法生成结论
        result.recommendation = self._generate_recommendation(result, experiment["hypothesis"])  # 调用方法生成建议

        # 更新实验状态
        experiment["status"] = ExperimentStatus.COMPLETED.value  # 将状态设为已完成
        experiment["analysis"] = result.to_dict()  # 将分析结果保存到实验数据
        experiment["completed_at"] = time.time()  # 记录完成时间戳

        await self._store_experiment(experiment)  # 存储更新后的实验数据

        # 移动到历史记录
        self.experiment_history[exp_id] = experiment  # 将实验添加到历史字典

        logger.info(f"[ExperimentManager] 实验 {exp_id} 分析完成")  # 记录分析完成日志
        logger.info(f"[ExperimentManager] 结论: {result.conclusion}")  # 记录结论日志

        return result  # 返回实验结果对象

    def _generate_conclusion(self, result: ExperimentResult) -> str:  # 定义生成结论的私有方法
        """生成实验结论"""  # 方法文档字符串
        if result.test_tasks < 3 or result.control_tasks < 3:  # 检查样本量是否充足
            return "样本量不足，无法得出可靠结论"  # 返回样本不足提示

        test_rate = result.test_success / result.test_tasks if result.test_tasks > 0 else 0  # 计算实验组成功率
        control_rate = result.control_success / result.control_tasks if result.control_tasks > 0 else 0  # 计算对照组成功率
        score_diff = result.test_avg_score - result.control_avg_score  # 计算分数差值

        if test_rate > control_rate and score_diff > 0.5:  # 成功率和分数都显著提升
            return f"实验策略显著优于默认策略（成功率提升{(test_rate - control_rate) * 100:.1f}%）"
        elif test_rate > control_rate:  # 成功率更高但分数提升有限
            return f"实验策略成功率更高，但价值评分提升有限（{score_diff:+.2f}）"
        elif score_diff > 0.5:  # 分数显著提升但成功率相近
            return f"实验策略价值评分显著提升（{score_diff:+.2f}），但成功率相近"
        elif abs(score_diff) < 0.3 and abs(test_rate - control_rate) < 0.1:  # 效果相当
            return "实验策略与默认策略效果相当"
        else:  # 无明显优势
            return f"实验策略未显示出明显优势（成功率{(test_rate - control_rate) * 100:+.1f}%，评分{score_diff:+.2f}）"

    def _generate_recommendation(self, result: ExperimentResult, hypothesis: dict) -> str:  # 定义生成建议的私有方法
        """生成策略建议"""  # 方法文档字符串
        score_diff = result.test_avg_score - result.control_avg_score  # 计算分数差值

        if score_diff > 1.0:  # 如果分数提升超过1.0（显著提升）
            return "promote"  # 建议：固化到核心配置
        elif score_diff > 0.3:  # 如果分数提升超过0.3（有一定提升）
            return "continue"  # 建议：继续实验
        elif score_diff < -0.5:  # 如果分数下降超过0.5（显著下降）
            return "reject"  # 建议：淘汰
        else:  # 其他情况（变化不大）
            return "observe"  # 建议：继续观察

    async def _store_experiment(self, experiment: dict):  # 定义存储实验的私有方法
        """存储实验到记忆系统"""  # 方法文档字符串
        try:  # 开始异常处理
            ms = await get_memory_service()
            await ms.add_memory(  # 调用记忆系统的add方法
                user_id="default_user",
                content=json.dumps(experiment, ensure_ascii=False),  # 将实验数据序列化为JSON字符串
                memory_type="experiment",  # 记忆类型：实验
                layer="evolve",  # 存储层：进化层
                context={  # 上下文信息字典
                    "experiment_id": experiment["id"],  # 实验ID
                    "status": experiment["status"],  # 实验状态
                    "hypothesis_id": experiment["hypothesis"].get("id", "unknown"),  # 假设ID（默认unknown）
                    "test_tasks": len(experiment["test_group"]),  # 实验组任务数量
                    "control_tasks": len(experiment["control_group"])  # 对照组任务数量
                },
                expire_days=None,  # 不过期
                source=MemorySource.EVOLUTION  # Agent-4: 进化产生
            )
        except Exception as e:  # 捕获异常
            logger.warning(f"[ExperimentManager] 存储实验失败: {e}")  # 记录警告日志

    def get_experiment_status(self, exp_id: str) -> dict | None:  # 定义获取实验状态方法
        """获取实验状态"""  # 方法文档字符串
        if exp_id in self.active_experiments:  # 检查实验是否在活跃字典中
            exp = self.active_experiments[exp_id]  # 获取实验数据
            return {  # 返回状态信息字典
                "id": exp_id,  # 实验ID
                "status": exp["status"],  # 当前状态
                "test_count": exp["results"]["test"]["count"],  # 实验组任务数
                "control_count": exp["results"]["control"]["count"],  # 对照组任务数
                "progress": (exp["results"]["test"]["count"] + exp["results"]["control"]["count"]) / exp[
                    # 计算进度分子
                    "duration_tasks"]  # 计算进度分母
            }
        return None  # 实验不存在返回None

    def get_task_experiment_group(self, task_id: str) -> ExperimentGroup | None:  # 定义查询任务组别方法
        """查询任务所属的实验组"""  # 方法文档字符串
        if task_id in self.task_assignments:  # 检查任务是否有分配记录
            return self.task_assignments[task_id].group  # 返回组别枚举值
        return None  # 无记录返回None

    def list_active_experiments(self) -> list[dict]:  # 定义列出活跃实验方法
        """列出所有活跃实验"""  # 方法文档字符串
        return [  # 返回列表推导结果
            {
                "id": exp_id,  # 实验ID
                "hypothesis": exp["hypothesis"].get("description", "")[:50],  # 假设描述（截取前50字符）
                "status": exp["status"],  # 实验状态
                "progress": (exp["results"]["test"]["count"] + exp["results"]["control"]["count"]) / exp[
                    # 计算进度分子
                    "duration_tasks"]  # 计算进度分母
            }
            for exp_id, exp in self.active_experiments.items()  # 遍历活跃实验字典
            if exp["status"] == ExperimentStatus.RUNNING.value  # 只返回进行中的实验
        ]

    async def cancel_experiment(self, exp_id: str):  # 定义取消实验方法
        """取消实验"""  # 方法文档字符串
        if exp_id in self.active_experiments:  # 检查实验是否存在
            self.active_experiments[exp_id]["status"] = ExperimentStatus.CANCELLED.value  # 将状态设为已取消
            await self._store_experiment(self.active_experiments[exp_id])  # 存储更新后的状态
            logger.info(f"[ExperimentManager] 实验 {exp_id} 已取消")  # 记录取消日志


# 全局实例
experiment_manager = ExperimentManager()  # 创建全局单例实例


# ========== 便捷函数 ==========

async def start_hypothesis_test(hypothesis: dict, duration: int = 10) -> str:  # 定义启动假设测试便捷函数
    """便捷函数：启动假设测试"""  # 函数文档字符串
    return await experiment_manager.start_experiment(hypothesis, duration)  # 调用管理器方法并返回结果


def assign_to_experiment(exp_id: str, task_id: str) -> str:  # 定义分配任务便捷函数
    """便捷函数：分配任务到实验"""  # 函数文档字符串
    group = experiment_manager.assign_task(exp_id, task_id)  # 调用管理器方法获取组别
    return group.value  # 返回组别字符串值


async def submit_experiment_feedback(exp_id: str,  # 定义提交反馈便捷函数
                               task_id: str,  # 参数：任务ID
                               value_assessment: dict,  # 参数：价值评估字典
                               success: bool = True  # 参数：成功标志（默认为是）
                               ):  # 函数定义结束
    """便捷函数：提交实验反馈"""  # 函数文档字符串
    # 将字典转换回ValueAssessmentV2
    if isinstance(value_assessment, dict):  # 检查参数是否为字典类型
        from core.strategy.value_system_v2 import ValueAssessmentV2, ValueDimension  # 导入必要类
        assessment = ValueAssessmentV2(  # 创建价值评估对象
            overall_score=value_assessment.get("overall_score", 3),  # 获取总分（默认3）
            overall_grade=value_assessment.get("overall_grade", "B"),  # 获取等级（默认B）
            dimension_scores={  # 构建维度分数字典
                ValueDimension(k): v  # 将字符串键转换为枚举键
                for k, v in value_assessment.get("dimension_scores", {}).items()  # 遍历维度分数
            },
            emotional_impact=value_assessment.get("emotional_impact", {}),  # 获取情感影响
            growth_insights=value_assessment.get("growth_insights", []),  # 获取成长洞察列表
            ethical_notes=value_assessment.get("ethical_notes", []),  # 获取伦理记录列表
            suggested_reflection=value_assessment.get("suggested_reflection", ""),  # 获取反思建议
            will_affect_behavior=value_assessment.get("will_affect_behavior", False)  # 获取行为影响标志
        )
    else:  # 如果参数不是字典（已是对象）
        assessment = value_assessment  # 直接使用传入的对象

    await experiment_manager.collect_feedback(exp_id, task_id, assessment, success)  # 调用管理器方法收集反馈


# =============================================================================
# 总结性注释：文件角色、关联关系与核心效果
# =============================================================================
#
# 【文件角色】
# 本文件（experiment_manager.py）是 SiliconBase V5 系统的"实验管理器"核心模块，
# 属于 RD-Agent（研发智能体）的关键组件。它负责建立和管理完整的策略实验AB测试体系，
# 是系统实现数据驱动自我进化的基础设施。
#
# 【核心职责】
# 1. 实验生命周期管理：创建、运行、完成、取消实验
# 2. 任务分配：将任务随机或指定分配到实验组和对照组
# 3. 反馈收集：接收并存储任务的价值评估和执行结果
# 4. 统计分析：对比两组数据，计算成功率、价值分数、各维度表现
# 5. 结论生成：根据统计结果生成文字结论和策略建议
# 6. 数据持久化：将实验数据保存到记忆系统供后续分析
#
# 【关联文件】
# 1. core/value_system_v2.py       - 价值系统V2，提供六维度评估框架
#    * 关系：被本文件导入，用于评估任务价值
#    * 交互：接收 ValueAssessmentV2 对象作为反馈数据
#
# 2. core/memory.py                - 记忆系统，持久化存储
#    * 关系：被本文件导入，用于存储实验记录
#    * 交互：调用 memory.add() 保存实验数据到进化层
#
# 3. core/hypothesis_generator.py  - 假设生成器
#    * 关系：假设生成器生成假设，本文件执行验证
#    * 交互：接收假设数据作为实验输入
#
# 4. core/rd_agent.py              - 研发智能体主模块
#    * 关系：RD-Agent调用本模块进行策略验证
#    * 交互：通过全局实例 experiment_manager 或便捷函数调用
#
# 5. core/logger.py                - 日志系统
#    * 关系：被本文件导入，用于记录运行日志
#    * 交互：各方法中调用 logger 记录信息
#
# 【达到的效果】
# 1. 数据驱动决策：通过AB测试科学验证新策略效果，避免主观判断
# 2. 风险控制：对照组机制确保即使实验策略失败，系统也能正常运行
# 3. 多维度评估：不仅看任务成功率，还评估价值、情感、成长、伦理等维度
# 4. 自动化演进：实验流程自动运行，无需人工干预，支持系统自我改进
# 5. 可追溯性：所有实验数据持久化存储，便于回顾分析和模式发现
# 6. 策略迭代：根据实验结论自动给出建议（promote/continue/reject/observe）
#
# 【典型使用场景】
# - 新策略上线前的效果验证：确保新策略优于旧策略再全面推广
# - 系统参数的自动优化：通过实验找到最优参数配置
# - AI行为的持续迭代改进：不断尝试新行为策略并验证效果
# - 假设验证：验证研发智能体生成的各种改进假设
#
# =============================================================================
