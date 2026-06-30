#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 文档字符串开始
策略决策器 - RD-Agent核心组件  # 模块名称
根据实验结果决策：固化策略到核心配置 或 淘汰  # 核心职责

功能：  # 功能列表
1. 评估实验结果，决策策略去向  # 功能1：实验评估
2. 固化有效策略到核心配置  # 功能2：策略固化
3. 记录失败教训  # 功能3：失败记录
4. 维护策略库  # 功能4：策略管理
"""  # 文档字符串结束

import json  # JSON模块：用于策略数据的序列化和反序列化
import time  # 时间模块：用于时间戳记录
from dataclasses import dataclass, field  # dataclass装饰器和field函数
from enum import Enum  # Enum类：用于定义策略状态枚举
from pathlib import Path  # Path类：跨平台路径处理
from typing import Any  # 类型注解

from core.logger import logger  # 日志记录器
from core.memory.memory_service import get_memory_service  # 【P1-迁移】使用新 MemoryService
from core.memory.memory_source import MemorySource  # Agent-4: 导入MemorySource枚举


class StrategyStatus(Enum):  # 策略状态枚举类
    """策略状态"""  # 类文档字符串
    EXPERIMENTAL = "experimental"  # 实验阶段：正在测试中的策略
    PROMOTED = "promoted"          # 已固化：通过实验验证的有效策略
    REJECTED = "rejected"          # 已淘汰：实验失败的策略
    DEPRECATED = "deprecated"      # 已弃用：曾经固化但不再推荐的策略


@dataclass  # 使用@dataclass自动生成__init__等方法
class Strategy:  # 策略数据类：封装策略的完整信息
    """策略数据结构"""  # 类文档字符串
    id: str  # 策略ID：唯一标识符
    description: str  # 策略描述：人类可读的说明
    trigger_conditions: list[str]  # 触发条件：哪些条件下激活此策略
    actions: list[str]  # 执行动作：策略的具体操作列表
    parameters: dict[str, Any]  # 参数：策略的附加参数
    expected_outcome: str  # 预期结果：策略期望达成的效果
    status: StrategyStatus  # 状态：当前策略的状态
    created_at: float = field(default_factory=time.time)  # 创建时间：策略创建的时间戳
    promoted_at: float | None = None  # 固化时间：策略被固化的时间戳（如适用）
    experiment_id: str | None = None  # 实验ID：关联的实验标识
    success_rate: float = 0.0  # 成功率：策略的历史成功率
    usage_count: int = 0  # 使用次数：策略被使用的总次数
    source_hypothesis: str | None = None  # 来源假设：生成此策略的原始假设ID

    def to_dict(self) -> dict:  # 转换为字典方法
        """转换为字典"""  # 方法文档字符串
        return {  # 返回包含所有字段的字典
            "id": self.id,
            "description": self.description,
            "trigger_conditions": self.trigger_conditions,
            "actions": self.actions,
            "parameters": self.parameters,
            "expected_outcome": self.expected_outcome,
            "status": self.status.value,  # 枚举转字符串
            "created_at": self.created_at,
            "promoted_at": self.promoted_at,
            "experiment_id": self.experiment_id,
            "success_rate": self.success_rate,
            "usage_count": self.usage_count,
            "source_hypothesis": self.source_hypothesis
        }

    @classmethod  # 类方法装饰器
    def from_dict(cls, data: dict) -> 'Strategy':  # 从字典创建实例方法
        """从字典创建Strategy对象"""  # 方法文档字符串
        return cls(  # 创建新实例
            id=data["id"],  # 策略ID（必填）
            description=data["description"],  # 描述（必填）
            trigger_conditions=data.get("trigger_conditions", []),  # 触发条件，默认为空列表
            actions=data.get("actions", []),  # 动作，默认为空列表
            parameters=data.get("parameters", {}),  # 参数，默认为空字典
            expected_outcome=data.get("expected_outcome", ""),  # 预期结果，默认为空
            status=StrategyStatus(data.get("status", "experimental")),  # 状态，默认实验阶段
            created_at=data.get("created_at", time.time()),  # 创建时间，默认当前
            promoted_at=data.get("promoted_at"),  # 固化时间
            experiment_id=data.get("experiment_id"),  # 实验ID
            success_rate=data.get("success_rate", 0.0),  # 成功率，默认0
            usage_count=data.get("usage_count", 0),  # 使用次数，默认0
            source_hypothesis=data.get("source_hypothesis")  # 来源假设
        )


class StrategyPromoter:  # 策略决策器类：策略生命周期管理核心
    """
    策略决策器 - 策略生命周期管理

    工作原理：
    1. 接收ExperimentManager的实验结果
    2. 根据结果决定策略去向（固化/淘汰/继续实验）
    3. 固化策略：写入核心配置文件
    4. 淘汰策略：记录到失败经验库
    5. 维护策略库，跟踪策略效果
    """  # 类文档字符串

    # 固化的配置路径
    CONFIG_DIR = Path(__file__).parent.parent / "data" / "evolution_config"  # 配置目录路径
    PROMOTED_STRATEGIES_FILE = CONFIG_DIR / "promoted_strategies.json"  # 固化策略文件路径
    REJECTED_STRATEGIES_FILE = CONFIG_DIR / "rejected_strategies.json"  # 淘汰策略文件路径

    # 固化阈值
    PROMOTE_THRESHOLD = 0.7      # 成功率阈值：达到此成功率可考虑固化
    MIN_TEST_COUNT = 5           # 最小测试次数：至少测试5次才做决策

    def __init__(self):  # 初始化方法
        """初始化策略决策器"""  # 方法文档字符串
        self.strategy_db: dict[str, Strategy] = {}  # 策略数据库：存储已固化的策略
        self.rejected_db: dict[str, Strategy] = {}  # 淘汰数据库：存储已淘汰的策略
        self._ensure_config_dir()  # 确保配置目录存在
        self._load_strategies()  # 加载已有策略
        logger.info("[StrategyPromoter] 策略决策器已初始化")  # 记录初始化日志

    def _ensure_config_dir(self):  # 确保配置目录存在方法
        """确保配置目录存在"""  # 方法文档字符串
        self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)  # 递归创建目录（如果不存在）

    def _load_strategies(self):  # 加载策略方法
        """加载已固化策略"""  # 方法文档字符串
        try:  # 异常处理块
            if self.PROMOTED_STRATEGIES_FILE.exists():  # 检查固化策略文件是否存在
                with open(self.PROMOTED_STRATEGIES_FILE, encoding='utf-8') as f:  # 打开文件
                    data = json.load(f)  # 解析JSON
                    for item in data.get("strategies", []):  # 遍历策略列表
                        strategy = Strategy.from_dict(item)  # 从字典创建策略对象
                        self.strategy_db[strategy.id] = strategy  # 添加到策略库

            if self.REJECTED_STRATEGIES_FILE.exists():  # 检查淘汰策略文件是否存在
                with open(self.REJECTED_STRATEGIES_FILE, encoding='utf-8') as f:  # 打开文件
                    data = json.load(f)  # 解析JSON
                    for item in data.get("strategies", []):  # 遍历策略列表
                        strategy = Strategy.from_dict(item)  # 从字典创建策略对象
                        self.rejected_db[strategy.id] = strategy  # 添加到淘汰库

            logger.info(f"[StrategyPromoter] 已加载 {len(self.strategy_db)} 个固化策略，"
                       f"{len(self.rejected_db)} 个淘汰策略")  # 记录加载数量
        except Exception as e:  # 捕获异常
            logger.warning(f"[StrategyPromoter] 加载策略失败: {e}")  # 记录警告

    def _save_strategies(self):  # 保存策略方法
        """保存策略到文件"""  # 方法文档字符串
        try:  # 异常处理块
            # 保存固化策略
            promoted_data = {  # 构建固化策略数据
                "updated_at": time.time(),  # 更新时间戳
                "strategies": [s.to_dict() for s in self.strategy_db.values()]  # 所有策略转字典
            }
            with open(self.PROMOTED_STRATEGIES_FILE, 'w', encoding='utf-8') as f:  # 打开文件写入
                json.dump(promoted_data, f, ensure_ascii=False, indent=2)  # 保存JSON（格式化）

            # 保存淘汰策略
            rejected_data = {  # 构建淘汰策略数据
                "updated_at": time.time(),  # 更新时间戳
                "strategies": [s.to_dict() for s in self.rejected_db.values()]  # 所有策略转字典
            }
            with open(self.REJECTED_STRATEGIES_FILE, 'w', encoding='utf-8') as f:  # 打开文件写入
                json.dump(rejected_data, f, ensure_ascii=False, indent=2)  # 保存JSON（格式化）
        except Exception as e:  # 捕获异常
            logger.error(f"[StrategyPromoter] 保存策略失败: {e}")  # 记录错误

    async def promote_to_config(self, experiment_result: dict, hypothesis: dict) -> Strategy | None:  # 固化策略方法
        """
        策略有效，固化到核心配置
        Args:
            experiment_result: 实验结果
            hypothesis: 原始假设
        Returns:
            固化后的策略对象
        """  # 方法文档字符串
        strategy_id = f"strategy_{int(time.time())}_{hash(hypothesis.get('id', '')) % 10000}"  # 生成策略ID

        # 创建策略对象
        strategy = Strategy(
            id=strategy_id,
            description=hypothesis.get("description", ""),  # 从假设获取描述
            trigger_conditions=hypothesis.get("proposed_strategy", {}).get("trigger_keywords", []),  # 触发关键词
            actions=hypothesis.get("proposed_strategy", {}).get("actions", []),  # 动作列表
            parameters=hypothesis.get("proposed_strategy", {}).get("parameters", {}),  # 参数
            expected_outcome=hypothesis.get("proposed_strategy", {}).get("expected_outcome", ""),  # 预期结果
            status=StrategyStatus.PROMOTED,  # 状态设为已固化
            promoted_at=time.time(),  # 记录固化时间
            experiment_id=experiment_result.get("experiment_id"),  # 关联实验ID
            success_rate=experiment_result.get("test_success_rate", 0),  # 记录成功率
            source_hypothesis=hypothesis.get("id")  # 记录来源假设ID
        )

        # 添加到策略库
        self.strategy_db[strategy_id] = strategy

        # 保存到文件
        self._save_strategies()

        # 记录到记忆系统
        await self._store_promoted_strategy(strategy)

        logger.info(f"[Evolution] 策略已固化: {strategy.description[:60]}...")  # 记录固化日志
        logger.info(f"[StrategyPromoter] 策略 {strategy_id} 已写入核心配置")  # 记录详情

        return strategy  # 返回固化的策略

    async def reject_strategy(self, experiment_result: dict, hypothesis: dict) -> Strategy | None:  # 淘汰策略方法
        """
        策略无效，记录失败教训
        Args:
            experiment_result: 实验结果
            hypothesis: 原始假设
        Returns:
            淘汰的策略对象
        """  # 方法文档字符串
        strategy_id = f"rejected_{int(time.time())}_{hash(hypothesis.get('id', '')) % 10000}"  # 生成淘汰策略ID

        # 创建淘汰策略记录
        strategy = Strategy(
            id=strategy_id,
            description=hypothesis.get("description", ""),  # 从假设获取描述
            trigger_conditions=hypothesis.get("proposed_strategy", {}).get("trigger_keywords", []),  # 触发关键词
            actions=hypothesis.get("proposed_strategy", {}).get("actions", []),  # 动作列表
            parameters=hypothesis.get("proposed_strategy", {}).get("parameters", {}),  # 参数
            expected_outcome=hypothesis.get("proposed_strategy", {}).get("expected_outcome", ""),  # 预期结果
            status=StrategyStatus.REJECTED,  # 状态设为已淘汰
            experiment_id=experiment_result.get("experiment_id"),  # 关联实验ID
            success_rate=experiment_result.get("test_success_rate", 0),  # 记录成功率（失败的）
            source_hypothesis=hypothesis.get("id")  # 记录来源假设ID
        )

        # 添加到淘汰库
        self.rejected_db[strategy_id] = strategy

        # 保存到文件
        self._save_strategies()

        # 记录失败教训到记忆系统
        await self._store_rejected_strategy(strategy, experiment_result)

        logger.info(f"[Evolution] 策略已淘汰: {strategy.description[:60]}...")  # 记录淘汰日志
        logger.info(f"[StrategyPromoter] 失败教训已记录: {strategy_id}")  # 记录详情

        return strategy  # 返回淘汰的策略

    async def evaluate_and_decide(self, experiment_result: dict) -> dict:  # 评估实验并决策方法（核心）
        """
        评估实验结果并做出决策

        新策略固化阈值：
        - 实验组overall评分 >= 4.0 (A级)
        - 实验组成功率 > 对照组成功率 * 1.1

        Args:
            experiment_result: 包含hypothesis和结果的完整数据
        Returns:
            决策结果
        """  # 方法文档字符串
        hypothesis = experiment_result.get("hypothesis", {})  # 获取假设
        result_data = experiment_result.get("result", {})  # 获取结果数据

        # 提取关键指标
        test_rate = result_data.get("test_success_rate", 0)  # 实验组成功率
        control_rate = result_data.get("control_success_rate", 0)  # 对照组成功率
        test_count = result_data.get("test_tasks", 0)  # 测试次数
        score_improvement = result_data.get("score_improvement", 0)  # 评分提升
        test_avg_score = result_data.get("test_avg_score", 0)  # 实验组平均评分

        # 初始化决策结果
        decision = {
            "action": "continue",  # 默认继续实验
            "strategy": None,  # 策略对象
            "reason": "",  # 决策原因
            "timestamp": time.time()  # 决策时间
        }

        # 样本量检查
        if test_count < self.MIN_TEST_COUNT:  # 测试次数不足
            decision["action"] = "continue"  # 继续实验
            decision["reason"] = f"样本量不足（{test_count}/{self.MIN_TEST_COUNT}），继续收集数据"
            return decision  # 返回决策

        # 综合评估：成功率提升 + 价值评分提升
        success_improvement = test_rate - control_rate  # 计算成功率提升

        # ====== 新策略固化阈值 ======
        # 实验组overall >= 4.0 (A级) 且 成功率 > 对照组 * 1.1
        meets_score_threshold = test_avg_score >= 4.0  # 是否达到A级评分
        meets_success_threshold = test_rate > control_rate * 1.1 if control_rate > 0 else test_rate > 0.7  # 是否达到成功率阈值

        if meets_score_threshold and meets_success_threshold:  # 达到新阈值
            # 达到新阈值，固化策略
            strategy = await self.promote_to_config(result_data, hypothesis)
            decision["action"] = "promote"  # 设为固化
            decision["strategy"] = strategy.to_dict() if strategy else None
            decision["reason"] = f"实验策略达到A级标准（评分{test_avg_score:.2f}，成功率+{(test_rate/control_rate-1)*100:.1f}%）"

        elif success_improvement >= 0.1 and score_improvement > 0:  # 显著优于对照组但未到A级
            # 显著优于对照组但未到A级，也固化策略（兼容性考虑）
            strategy = await self.promote_to_config(result_data, hypothesis)
            decision["action"] = "promote"  # 设为固化
            decision["strategy"] = strategy.to_dict() if strategy else None
            decision["reason"] = f"实验策略优于默认策略（成功率+{success_improvement*100:.1f}%，评分+{score_improvement:.2f}）"

        elif test_rate < control_rate - 0.1 or score_improvement < -0.5:  # 明显劣于对照组
            # 明显劣于对照组，淘汰策略
            strategy = await self.reject_strategy(result_data, hypothesis)
            decision["action"] = "reject"  # 设为淘汰
            decision["strategy"] = strategy.to_dict() if strategy else None
            decision["reason"] = f"实验策略效果不佳（成功率{success_improvement*100:+.1f}%，评分{score_improvement:+.2f}）"

        elif test_count >= 20:  # 测试足够多但效果一般
            # 测试足够多，但效果一般，也固化为可选策略
            strategy = await self.promote_to_config(result_data, hypothesis)
            decision["action"] = "promote"  # 设为固化
            decision["strategy"] = strategy.to_dict() if strategy else None
            decision["reason"] = f"经过{test_count}次测试，策略稳定可用"

        else:  # 效果不明显
            # 效果不明显，继续实验
            decision["action"] = "continue"  # 继续实验
            decision["reason"] = f"效果不明显（成功率{success_improvement*100:+.1f}%，评分{score_improvement:+.2f}），继续观察"

        # 记录决策
        await self._store_decision(decision, experiment_result)

        logger.info(f"[StrategyPromoter] 决策: {decision['action']} - {decision['reason']}")  # 记录决策

        return decision  # 返回决策结果

    async def _store_promoted_strategy(self, strategy: Strategy):  # 存储固化策略到记忆方法
        """存储固化策略到记忆系统"""  # 方法文档字符串
        try:  # 异常处理块
            ms = await get_memory_service()
            await ms.add_memory(  # 添加到记忆系统
                user_id="default_user",
                content=json.dumps(strategy.to_dict(), ensure_ascii=False),  # 策略转JSON
                memory_type="promoted_strategy",  # 记忆类型
                layer="evolve",  # 进化层：长期保存
                context={  # 元数据
                    "strategy_id": strategy.id,
                    "trigger_conditions": strategy.trigger_conditions,
                    "success_rate": strategy.success_rate
                },
                expire_days=None,  # 永不过期
                source=MemorySource.EVOLUTION  # Agent-4: 进化产生
            )
        except Exception as e:  # 捕获异常
            logger.warning(f"[StrategyPromoter] 存储固化策略失败: {e}")  # 记录警告

    async def _store_rejected_strategy(self, strategy: Strategy, experiment_result: dict):  # 存储失败策略到记忆方法
        """存储失败策略到记忆系统"""  # 方法文档字符串
        try:  # 异常处理块
            ms = await get_memory_service()
            await ms.add_memory(  # 添加到记忆系统
                user_id="default_user",
                content=json.dumps({  # 构建内容JSON
                    "strategy": strategy.to_dict(),
                    "failure_analysis": experiment_result
                }, ensure_ascii=False),
                memory_type="failed_strategy",  # 记忆类型
                layer="medium",  # 中期记忆层
                context={  # 元数据
                    "strategy_id": strategy.id,
                    "experiment_id": strategy.experiment_id,
                    "failure_reason": "实验效果不佳"
                },
                expire_days=90,  # 失败经验保留90天
                source=MemorySource.EVOLUTION  # Agent-4: 进化产生
            )
        except Exception as e:  # 捕获异常
            logger.warning(f"[StrategyPromoter] 存储失败策略失败: {e}")  # 记录警告

    async def _store_decision(self, decision: dict, experiment_result: dict):  # 存储决策记录方法
        """存储决策记录"""  # 方法文档字符串
        try:  # 异常处理块
            ms = await get_memory_service()
            await ms.add_memory(  # 添加到记忆系统
                user_id="default_user",
                content=json.dumps({  # 构建内容JSON
                    "decision": decision,
                    "experiment": experiment_result
                }, ensure_ascii=False),
                memory_type="strategy_decision",  # 记忆类型
                layer="medium",  # 中期记忆层
                context={  # 元数据
                    "action": decision["action"],
                    "experiment_id": experiment_result.get("experiment_id")
                },
                expire_days=180,  # 决策记录保留180天
                source=MemorySource.EVOLUTION  # Agent-4: 进化产生
            )
        except Exception as e:  # 捕获异常
            logger.warning(f"[StrategyPromoter] 存储决策失败: {e}")  # 记录警告

    def get_promoted_strategies(self, limit: int = 50) -> list[Strategy]:  # 获取固化策略方法
        """获取所有已固化策略"""  # 方法文档字符串
        strategies = list(self.strategy_db.values())  # 获取所有策略
        strategies.sort(key=lambda x: x.promoted_at or 0, reverse=True)  # 按固化时间降序
        return strategies[:limit]  # 返回前limit个

    def find_applicable_strategies(self, context: str) -> list[Strategy]:  # 查找适用策略方法
        """根据上下文查找适用的策略"""  # 方法文档字符串
        applicable = []  # 适用策略列表
        for strategy in self.strategy_db.values():  # 遍历所有策略
            if strategy.status != StrategyStatus.PROMOTED:  # 只考虑已固化的
                continue
            # 检查触发条件
            for condition in strategy.trigger_conditions:  # 遍历触发条件
                if condition.lower() in context.lower():  # 条件匹配上下文（不区分大小写）
                    applicable.append(strategy)  # 添加到适用列表
                    break  # 匹配一个条件即可
        # 按成功率排序
        applicable.sort(key=lambda x: x.success_rate, reverse=True)
        return applicable  # 返回适用策略列表

    def update_strategy_stats(self, strategy_id: str, success: bool):  # 更新策略统计方法
        """更新策略使用统计"""  # 方法文档字符串
        if strategy_id in self.strategy_db:  # 策略存在
            strategy = self.strategy_db[strategy_id]
            strategy.usage_count += 1  # 使用次数+1
            # 更新成功率（滑动平均）
            if success:  # 执行成功
                strategy.success_rate = (strategy.success_rate * (strategy.usage_count - 1) + 1) / strategy.usage_count
            else:  # 执行失败
                strategy.success_rate = (strategy.success_rate * (strategy.usage_count - 1)) / strategy.usage_count

            self._save_strategies()  # 保存更新

    def deprecate_strategy(self, strategy_id: str, reason: str = ""):  # 弃用策略方法
        """弃用已固化的策略"""  # 方法文档字符串
        if strategy_id in self.strategy_db:  # 策略存在
            strategy = self.strategy_db[strategy_id]
            strategy.status = StrategyStatus.DEPRECATED  # 状态改为已弃用
            self._save_strategies()  # 保存
            logger.info(f"[StrategyPromoter] 策略 {strategy_id} 已弃用: {reason}")  # 记录日志


# 全局实例
strategy_promoter = StrategyPromoter()  # 创建模块级单例实例


# ========== 便捷函数 ==========

async def evaluate_experiment(experiment_result: dict) -> dict:  # 评估实验便捷函数
    """便捷函数：评估实验结果"""  # 函数文档字符串
    return await strategy_promoter.evaluate_and_decide(experiment_result)  # 调用决策器方法


def get_active_strategies() -> list[dict]:  # 获取活跃策略便捷函数
    """便捷函数：获取活跃策略"""  # 函数文档字符串
    strategies = strategy_promoter.get_promoted_strategies()  # 获取固化策略
    return [s.to_dict() for s in strategies]  # 转字典列表


def find_strategies_for_context(context: str) -> list[dict]:  # 查找适用策略便捷函数
    """便捷函数：查找适用策略"""  # 函数文档字符串
    strategies = strategy_promoter.find_applicable_strategies(context)  # 查找适用策略
    return [s.to_dict() for s in strategies]  # 转字典列表


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase_V5 系统 RD-Agent 双闭环进化系统的核心组件之一，
# 负责根据实验结果决策策略的去向（固化/淘汰/继续实验）。是连接"实验"和
# "策略库"的关键桥梁，实现策略的生命周期管理。
#
# 【策略状态流转】
# EXPERIMENTAL(实验阶段) → evaluate_and_decide()决策
#   ├─ 达到A级标准（评分>=4.0且成功率>对照组*1.1） → PROMOTED(已固化)
#   ├─ 显著优于对照组（成功率提升>=10%且评分提升>0） → PROMOTED(已固化)
#   ├─ 明显劣于对照组（成功率<对照组-10%或评分<-0.5） → REJECTED(已淘汰)
#   ├─ 测试>=20次且效果一般 → PROMOTED(已固化)
#   └─ 效果不明显 → 继续EXPERIMENTAL
#
# 【新策略固化阈值】
# - 实验组overall评分 >= 4.0 (A级)
# - 实验组成功率 > 对照组成功率 * 1.1
# - 最小测试次数 >= 5
#
# 【架构设计】
# - StrategyStatus: 策略状态枚举（实验/固化/淘汰/弃用）
# - Strategy: 策略数据类，封装策略完整信息
# - StrategyPromoter: 策略决策器核心，管理策略生命周期
# - 双库设计: strategy_db（固化库）+ rejected_db（淘汰库）
# - 持久化: JSON文件存储 + 记忆系统备份
#
# 【关联文件】
# - core/experiment_manager.py : 提供实验结果数据
# - core/hypothesis_generator.py: 提供原始假设数据
# - core/evolution.py          : 调用策略决策进行进化
# - core/memory.py             : 存储策略到分层记忆
# - core/logger.py             : 记录决策日志
#
# 【核心功能效果】
# 1. 实验评估: 根据成功率、评分、样本量综合评估实验结果
# 2. 策略固化: 将有效策略写入核心配置，长期生效
# 3. 失败记录: 记录淘汰策略和失败教训，避免重复尝试
# 4. 适用匹配: 根据上下文关键词查找适用策略
# 5. 效果跟踪: 统计策略使用次数和成功率，支持动态评估
# 6. 决策持久化: 决策记录保存到记忆系统，支持审计
#
# 【数据流向】
# 实验结果: experiment_manager → evaluate_and_decide() → 决策
# 策略固化: promote_to_config() → strategy_db → JSON文件 + 记忆系统
# 策略淘汰: reject_strategy() → rejected_db → JSON文件 + 记忆系统
# 策略查找: find_applicable_strategies() → 关键词匹配 → 适用策略列表
#
# 【使用场景】
# 场景1: 实验完成 → evaluate_experiment() → 自动决策固化/淘汰/继续
# 场景2: 任务执行前 → find_strategies_for_context() → 查找适用策略
# 场景3: 策略使用后 → update_strategy_stats() → 更新成功率统计
# 场景4: 策略过时 → deprecate_strategy() → 标记为弃用
# =============================================================================
