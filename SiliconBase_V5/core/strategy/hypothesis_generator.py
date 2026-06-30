#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始标记
假设生成器 - RD-Agent核心组件  # 模块名称和定位
从Reflector的反思记录中提取可测试的优化假设  # 核心功能描述

功能：  # 功能列表标题
1. 分析反思记录，识别高置信度的改进建议  # 功能1：分析反思
2. 将建议形式化为可测试的假设  # 功能2：形式化假设
3. 生成相应的实验策略  # 功能3：生成策略
"""  # 多行文档字符串结束标记

import hashlib  # 导入哈希模块：用于生成唯一ID
import json  # 导入JSON模块：用于序列化/反序列化数据
import time  # 导入时间模块：用于时间戳和性能计算
from dataclasses import dataclass, field  # 从dataclasses导入数据类装饰器和字段
from enum import Enum  # 从enum导入枚举类基类
from typing import Any  # 从typing导入类型注解工具

from core.logger import logger  # 从core.logger导入日志记录器
from core.memory.memory_service import get_memory_service  # 【P1-迁移】使用新 MemoryService
from core.memory.memory_source import MemorySource  # Agent-4: 导入MemorySource枚举


class HypothesisStatus(Enum):  # 定义假设状态枚举类
    """假设状态"""  # 类文档字符串
    PENDING = "pending"      # 待实验状态：尚未开始验证
    RUNNING = "running"      # 实验中状态：正在进行验证
    VALIDATED = "validated"  # 已验证有效状态：假设被证实
    REJECTED = "rejected"    # 已验证无效状态：假设被证伪


@dataclass  # 使用数据类装饰器
class Hypothesis:  # 定义假设数据类
    """假设数据结构"""  # 类文档字符串
    id: str  # 假设唯一标识符
    description: str                    # 假设描述：自然语言描述
    confidence: float                   # 置信度 0-1：表示假设可靠程度
    source_reflection: str              # 来源反思ID：关联的反思记录
    applicable_scenario: str            # 适用场景：描述适用条件
    proposed_strategy: dict             # 建议策略：形式化的策略结构
    status: HypothesisStatus = HypothesisStatus.PENDING  # 状态，默认待实验
    created_at: float = field(default_factory=time.time)  # 创建时间戳
    tested_count: int = 0               # 测试次数：已进行的实验次数
    success_count: int = 0              # 成功次数：实验成功次数

    def to_dict(self) -> dict:  # 定义转换为字典的方法
        return {  # 返回字典表示
            "id": self.id,  # 假设ID字段
            "description": self.description,  # 描述字段
            "confidence": self.confidence,  # 置信度字段
            "source_reflection": self.source_reflection,  # 来源反思字段
            "applicable_scenario": self.applicable_scenario,  # 适用场景字段
            "proposed_strategy": self.proposed_strategy,  # 策略字段
            "status": self.status.value,  # 状态枚举值
            "created_at": self.created_at,  # 创建时间字段
            "tested_count": self.tested_count,  # 测试次数字段
            "success_count": self.success_count  # 成功次数字段
        }

    @classmethod  # 定义类方法装饰器
    def from_dict(cls, data: dict) -> 'Hypothesis':  # 从字典创建假设对象
        return cls(  # 返回新实例
            id=data["id"],  # ID字段
            description=data["description"],  # 描述字段
            confidence=data["confidence"],  # 置信度字段
            source_reflection=data["source_reflection"],  # 来源反思字段
            applicable_scenario=data["applicable_scenario"],  # 适用场景字段
            proposed_strategy=data["proposed_strategy"],  # 策略字段
            status=HypothesisStatus(data.get("status", "pending")),  # 状态字段（默认pending）
            created_at=data.get("created_at", time.time()),  # 创建时间（默认当前）
            tested_count=data.get("tested_count", 0),  # 测试次数（默认0）
            success_count=data.get("success_count", 0)  # 成功次数（默认0）
        )


class HypothesisGenerator:  # 定义假设生成器类
    """
    假设生成器 - 从反思中提取可测试的假设  # 类文档字符串标题

    工作原理：  # 工作原理列表
    1. 定期/批量获取Reflector的反思记录  # 步骤1：获取反思
    2. 筛选高置信度（>0.7）且有具体建议的反思  # 步骤2：筛选反思
    3. 将建议形式化为假设（包含可执行策略）  # 步骤3：形式化
    4. 去重并存储到假设库  # 步骤4：去重存储
    """  # 类文档字符串结束

    # 最小置信度阈值
    MIN_CONFIDENCE = 0.7  # 类常量：只有置信度>0.7的反思才会生成假设

    # 反思记录缓存大小
    REFLECTION_CACHE_SIZE = 100  # 类常量：缓存最多100条反思记录

    def __init__(self):  # 定义初始化方法
        self.reflection_cache: list[dict] = []  # 初始化反思缓存列表
        self.hypothesis_db: dict[str, Hypothesis] = {}  # 初始化假设数据库字典
        self._loaded = False  # 延迟加载标志
        logger.info("[HypothesisGenerator] 假设生成器已初始化")  # 记录初始化日志

    async def _ensure_loaded(self):
        """确保历史假设已加载"""
        if not self._loaded:
            await self._load_existing_hypotheses()
            self._loaded = True

    async def _load_existing_hypotheses(self):  # 定义加载历史假设的私有方法
        """从记忆系统加载已有假设"""  # 方法文档字符串
        try:  # 开始异常处理
            ms = await get_memory_service()
            records = await ms.query_memories(user_id="default_user", layer="evolve", mem_type="hypothesis", limit=100)  # 从记忆获取假设记录
            for record in records:  # 遍历记录
                try:  # 嵌套异常处理
                    content = json.loads(record["content"])  # 解析JSON内容
                    hypothesis = Hypothesis.from_dict(content)  # 从字典创建假设对象
                    self.hypothesis_db[hypothesis.id] = hypothesis  # 添加到数据库
                except Exception as e:  # 捕获异常
                    logger.debug(f"[HypothesisGenerator] 加载假设失败: {e}")  # 记录调试日志
            logger.info(f"[HypothesisGenerator] 已加载 {len(self.hypothesis_db)} 个历史假设")  # 记录加载数量
        except Exception as e:  # 捕获异常
            logger.warning(f"[HypothesisGenerator] 加载历史假设失败: {e}")  # 记录警告

    async def generate_hypotheses(self,  # 定义生成假设方法
                            recent_reflections: list[Any]  # 参数：最近的反思记录列表
                            ) -> list[Hypothesis]:  # 返回：生成的假设列表
        """
        从反思记录生成假设  # 方法文档字符串标题

        Args:  # 参数说明
            recent_reflections: 最近的反思记录列表 (Reflection对象或字典)  # 参数类型

        Returns:  # 返回值说明
            生成的假设列表  # 返回类型
        """  # 方法文档字符串结束
        await self._ensure_loaded()
        hypotheses = []  # 初始化假设结果列表

        for reflection in recent_reflections:  # 遍历反思记录
            # 兼容Reflection对象和字典
            if hasattr(reflection, 'suggestion'):  # 如果是Reflection对象
                # Reflection对象
                suggestion = reflection.suggestion  # 获取建议
                confidence = reflection.confidence  # 获取置信度
                reflection_id = getattr(reflection, 'id', f"refl_{int(time.time())}")  # 获取ID或生成
                context_summary = reflection.context_summary  # 获取上下文摘要
            else:  # 如果是字典格式
                # 字典格式
                suggestion = reflection.get("suggestion", "")  # 获取建议（默认空）
                confidence = reflection.get("confidence", 0.0)  # 获取置信度（默认0）
                reflection_id = reflection.get("id", f"refl_{int(time.time())}")  # 获取ID或生成
                context_summary = reflection.get("context_summary", "")  # 获取上下文摘要（默认空）

            # 筛选条件：有建议且置信度足够高
            if suggestion and confidence > self.MIN_CONFIDENCE:  # 检查筛选条件
                # 检查是否已存在相似假设（去重）
                if self._is_duplicate(suggestion):  # 如果是重复假设
                    logger.debug(f"[HypothesisGenerator] 跳过重复假设: {suggestion[:50]}...")  # 记录调试日志
                    continue  # 跳过本次循环

                hypothesis = self._create_hypothesis(  # 创建假设对象
                    reflection_id=reflection_id,  # 传入反思ID
                    suggestion=suggestion,  # 传入建议
                    confidence=confidence,  # 传入置信度
                    context_summary=context_summary  # 传入上下文摘要
                )

                self.hypothesis_db[hypothesis.id] = hypothesis  # 添加到数据库
                await self._store_hypothesis(hypothesis)  # 存储到记忆系统
                hypotheses.append(hypothesis)  # 添加到结果列表

                logger.info(f"[HypothesisGenerator] 生成新假设 [{hypothesis.id[:8]}]: {suggestion[:60]}...")  # 记录日志

        return hypotheses  # 返回生成的假设列表

    def _create_hypothesis(self,  # 定义创建假设的私有方法
                           reflection_id: str,  # 参数：反思ID
                           suggestion: str,  # 参数：建议内容
                           confidence: float,  # 参数：置信度
                           context_summary: str  # 参数：上下文摘要
                           ) -> Hypothesis:  # 返回：假设对象
        """创建假设对象"""  # 方法文档字符串
        # 生成唯一ID
        hash_input = f"{reflection_id}_{suggestion}_{time.time()}"  # 构建哈希输入
        hypothesis_id = f"hypo_{hashlib.md5(hash_input.encode()).hexdigest()[:12]}"  # 生成MD5哈希取前12位

        # 形式化策略
        strategy = self._formalize_strategy(suggestion)  # 调用方法将建议形式化为策略

        return Hypothesis(  # 返回新创建的假设对象
            id=hypothesis_id,  # 设置ID
            description=suggestion,  # 设置描述
            confidence=confidence,  # 设置置信度
            source_reflection=reflection_id,  # 设置来源反思
            applicable_scenario=context_summary,  # 设置适用场景
            proposed_strategy=strategy  # 设置策略
        )

    def _formalize_strategy(self,  # 定义形式化策略的私有方法
                            suggestion: str  # 参数：建议文本
                            ) -> dict:  # 返回：策略字典
        """
        将建议形式化为可执行策略  # 方法文档字符串标题

        解析建议文本，提取关键策略要素：  # 功能说明
        - 触发条件：何时应用此策略  # 要素1
        - 动作：具体要做什么  # 要素2
        - 参数：策略参数  # 要素3
        - 预期效果：成功标准  # 要素4
        """  # 方法文档字符串结束
        strategy = {  # 初始化策略字典
            "trigger_keywords": [],  # 触发关键词列表
            "actions": [],  # 动作列表
            "parameters": {},  # 参数字典
            "expected_outcome": "",  # 预期效果
            "fallback": None  # 回退策略
        }

        # 提取触发关键词（简单实现，可扩展为NLP解析）
        trigger_patterns = [  # 定义触发模式列表
            "当", "如果", "遇到", "在...情况下", "针对"  # 中文触发词
        ]
        for pattern in trigger_patterns:  # 遍历触发模式
            if pattern in suggestion:  # 如果建议中包含该模式
                # 提取pattern后面的内容作为关键词
                idx = suggestion.find(pattern)  # 查找模式位置
                if idx >= 0:  # 如果找到
                    keyword = suggestion[idx:idx+20].strip()  # 提取20个字符作为关键词
                    strategy["trigger_keywords"].append(keyword)  # 添加到触发关键词列表

        # 提取动作（通过动词识别）
        action_verbs = ["使用", "尝试", "优先", "避免", "增加", "减少", "调整"]  # 定义动作动词列表
        for verb in action_verbs:  # 遍历动词
            if verb in suggestion:  # 如果建议中包含该动词
                idx = suggestion.find(verb)  # 查找动词位置
                if idx >= 0:  # 如果找到
                    action = suggestion[idx:idx+30].strip()  # 提取30个字符作为动作
                    strategy["actions"].append(action)  # 添加到动作列表

        # 如果没有提取到动作，将整个建议作为动作
        if not strategy["actions"]:  # 如果动作列表为空
            strategy["actions"].append(suggestion)  # 将整个建议作为动作

        # 预期效果（通常包含"提高"、"改善"、"减少"等词）
        outcome_patterns = ["提高", "改善", "减少", "优化", "提升", "降低"]  # 定义效果模式列表
        for pattern in outcome_patterns:  # 遍历效果模式
            if pattern in suggestion:  # 如果建议中包含该模式
                idx = suggestion.find(pattern)  # 查找模式位置
                if idx >= 0:  # 如果找到
                    strategy["expected_outcome"] = suggestion[idx:idx+40].strip()  # 提取40个字符作为预期效果
                    break  # 找到第一个就跳出

        return strategy  # 返回策略字典

    def _is_duplicate(self,  # 定义检查重复的私有方法
                      suggestion: str  # 参数：建议文本
                      ) -> bool:  # 返回：是否重复
        """检查是否已存在相似假设（简单去重）"""  # 方法文档字符串
        suggestion_normalized = suggestion.lower().replace(" ", "").replace("，", "").replace("。", "")  # 规范化建议文本

        for existing in self.hypothesis_db.values():  # 遍历已有假设
            existing_normalized = existing.description.lower().replace(" ", "").replace("，", "").replace("。", "")  # 规范化已有描述
            # 计算相似度（简单包含关系）
            if suggestion_normalized in existing_normalized or existing_normalized in suggestion_normalized:  # 包含关系检查
                return True  # 是重复
            # 或者编辑距离足够小
            if self._similarity(suggestion_normalized, existing_normalized) > 0.8:  # Jaccard相似度>0.8
                return True  # 是重复

        return False  # 不是重复

    def _similarity(self,  # 定义计算相似度的私有方法
                    a: str,  # 参数：字符串a
                    b: str  # 参数：字符串b
                    ) -> float:  # 返回：相似度0-1
        """计算两个字符串的相似度（简单的Jaccard相似度）"""  # 方法文档字符串
        if not a or not b:  # 如果任一字符串为空
            return 0.0  # 返回0相似度

        set_a = set(a)  # 将字符串a转为字符集合
        set_b = set(b)  # 将字符串b转为字符集合
        intersection = len(set_a & set_b)  # 计算交集大小
        union = len(set_a | set_b)  # 计算并集大小

        return intersection / union if union > 0 else 0.0  # 返回Jaccard相似度

    async def _store_hypothesis(self,  # 定义存储假设的私有方法
                          hypothesis: Hypothesis  # 参数：假设对象
                          ):  # 返回：无
        """存储假设到记忆系统"""  # 方法文档字符串
        try:  # 开始异常处理
            ms = await get_memory_service()
            await ms.add_memory(  # 调用记忆系统添加方法
                user_id="default_user",
                content=json.dumps(hypothesis.to_dict(), ensure_ascii=False),  # 序列化为JSON
                memory_type="hypothesis",  # 记忆类型：假设
                layer="evolve",  # 存储层：进化层
                context={  # 上下文信息
                    "hypothesis_id": hypothesis.id,  # 假设ID
                    "confidence": hypothesis.confidence,  # 置信度
                    "status": hypothesis.status.value,  # 状态
                    "scenario": hypothesis.applicable_scenario  # 适用场景
                },
                expire_days=None,  # 假设不过期
                source=MemorySource.EVOLUTION  # Agent-4: 进化产生
            )
        except Exception as e:  # 捕获异常
            logger.warning(f"[HypothesisGenerator] 存储假设失败: {e}")  # 记录警告

    async def get_pending_hypotheses(self,  # 定义获取待实验假设的方法
                               limit: int = 10  # 参数：限制数量，默认10
                               ) -> list[Hypothesis]:  # 返回：假设列表
        """获取待实验的假设列表"""  # 方法文档字符串
        await self._ensure_loaded()
        pending = [h for h in self.hypothesis_db.values()  # 列表推导：筛选待实验假设
                   if h.status == HypothesisStatus.PENDING]  # 状态为PENDING
        # 按置信度排序
        pending.sort(key=lambda x: x.confidence, reverse=True)  # 降序排序
        return pending[:limit]  # 返回前limit个

    async def update_hypothesis_status(self,  # 定义更新假设状态的方法
                                 hypothesis_id: str,  # 参数：假设ID
                                 status: HypothesisStatus  # 参数：新状态
                                 ):  # 返回：无
        """更新假设状态"""  # 方法文档字符串
        await self._ensure_loaded()
        if hypothesis_id in self.hypothesis_db:  # 如果假设存在于数据库
            self.hypothesis_db[hypothesis_id].status = status  # 更新状态
            await self._store_hypothesis(self.hypothesis_db[hypothesis_id])  # 重新存储
            logger.info(f"[HypothesisGenerator] 假设 {hypothesis_id[:8]} 状态更新为 {status.value}")  # 记录日志

    async def record_test_result(self,  # 定义记录测试结果的方法
                           hypothesis_id: str,  # 参数：假设ID
                           success: bool  # 参数：是否成功
                           ):  # 返回：无
        """记录假设测试结果"""  # 方法文档字符串
        await self._ensure_loaded()
        if hypothesis_id in self.hypothesis_db:  # 如果假设存在于数据库
            hypothesis = self.hypothesis_db[hypothesis_id]  # 获取假设对象
            hypothesis.tested_count += 1  # 测试次数加1
            if success:  # 如果成功
                hypothesis.success_count += 1  # 成功次数加1

            # 根据成功率自动更新状态
            if hypothesis.tested_count >= 5:  # 至少测试5次
                success_rate = hypothesis.success_count / hypothesis.tested_count  # 计算成功率
                if success_rate >= 0.7:  # 成功率>=70%
                    hypothesis.status = HypothesisStatus.VALIDATED  # 设置为已验证
                elif success_rate < 0.3:  # 成功率<30%
                    hypothesis.status = HypothesisStatus.REJECTED  # 设置为已拒绝

            await self._store_hypothesis(hypothesis)  # 重新存储假设


# 全局实例
hypothesis_generator = HypothesisGenerator()  # 创建假设生成器全局单例


# ========== 便捷函数 ==========  # 分隔线：便捷函数区域开始

async def generate_from_reflections(reflections: list[Any]) -> list[dict]:  # 定义从反思生成假设的便捷函数
    """便捷函数：从反思生成假设"""  # 函数文档字符串
    hypotheses = await hypothesis_generator.generate_hypotheses(reflections)  # 调用生成器方法
    return [h.to_dict() for h in hypotheses]  # 转换为字典列表返回


async def get_top_hypotheses(n: int = 5) -> list[dict]:  # 定义获取前N个假设的便捷函数
    """获取前N个待测试假设"""  # 函数文档字符串
    hypotheses = await hypothesis_generator.get_pending_hypotheses(limit=n)  # 获取待实验假设
    return [h.to_dict() for h in hypotheses]  # 转换为字典列表返回


async def quick_hypothesis(suggestion: str,  # 定义快速创建假设的便捷函数（用于测试）
                     confidence: float = 0.8  # 参数：置信度，默认0.8
                     ) -> dict:  # 返回：假设字典
    """快速创建假设（用于测试）"""  # 函数文档字符串
    await hypothesis_generator._ensure_loaded()
    hypothesis = hypothesis_generator._create_hypothesis(  # 调用创建方法
        reflection_id="manual",  # 反思ID设为手动
        suggestion=suggestion,  # 传入建议
        confidence=confidence,  # 传入置信度
        context_summary="手动创建"  # 上下文摘要设为手动创建
    )
    hypothesis_generator.hypothesis_db[hypothesis.id] = hypothesis  # 添加到数据库
    await hypothesis_generator._store_hypothesis(hypothesis)  # 存储到记忆系统
    return hypothesis.to_dict()  # 返回字典表示


# =============================================================================
# 总结性注释：文件角色、关联关系与核心效果
# =============================================================================
#
# 【文件角色】
# 本文件（hypothesis_generator.py）是 SiliconBase V5 系统 RD-Agent
# 双闭环进化系统的核心组件之一，负责从 Reflector 的反思记录中提取
# 可测试的优化假设。是连接"反思"和"实验"的关键桥梁。
#
# 【核心职责】
# 1. 反思分析：从反思记录中识别高置信度(>0.7)的改进建议
# 2. 假设生成：将自然语言建议形式化为结构化的假设对象
# 3. 策略形式化：解析建议文本，提取触发条件、动作、预期效果
# 4. 去重机制：通过字符串相似度(Jaccard>0.8)避免重复假设
# 5. 状态跟踪：跟踪假设的实验状态（待实验/实验中/已验证/已拒绝）
# 6. 自动决策：根据测试结果自动更新假设状态（5次以上，成功率>70%验证，<30%拒绝）
#
# 【假设状态流转】
# PENDING(待实验) → RUNNING(实验中) → VALIDATED(已验证)
#                              ↘
#                                → REJECTED(已拒绝)
#
# 【核心数据结构】
# 1. HypothesisStatus(Enum): 假设状态枚举
#    - PENDING: 待实验，初始状态
#    - RUNNING: 实验中，正在进行验证
#    - VALIDATED: 已验证，假设被证实有效
#    - REJECTED: 已拒绝，假设被证伪无效
#
# 2. Hypothesis(dataclass): 假设数据类
#    - id: 唯一标识符（MD5哈希生成）
#    - description: 自然语言描述
#    - confidence: 置信度0-1
#    - source_reflection: 来源反思ID
#    - applicable_scenario: 适用场景
#    - proposed_strategy: 形式化策略结构
#    - status: 当前状态
#    - tested_count/success_count: 测试统计
#
# 3. proposed_strategy结构:
#    - trigger_keywords: 触发关键词列表
#    - actions: 动作列表
#    - parameters: 参数字典
#    - expected_outcome: 预期效果
#    - fallback: 回退策略
#
# 【关联文件】
# 1. core/reflector.py          - 反思系统
#    * 关系：上游数据来源，提供反思记录
#    * 交互：接收Reflection对象或字典，提取suggestion/confidence
#
# 2. core/experiment_manager.py - 实验管理器
#    * 关系：下游使用方，管理假设的实验验证
#    * 交互：get_pending_hypotheses()提供待实验假设
#    * 交互：update_hypothesis_status()更新实验状态
#    * 交互：record_test_result()记录测试结果
#
# 3. core/memory.py             - 记忆系统
#    * 关系：持久化存储
#    * 交互：存储和加载假设到进化层
#
# 4. core/evolution.py          - 进化引擎
#    * 关系：调用方
#    * 交互：调用generate_hypotheses()生成假设
#    * 交互：启动假设的实验验证
#
# 5. core/strategy_promoter.py  - 策略推广器
#    * 关系：验证后的使用方
#    * 交互：根据VALIDATED状态决策策略推广
#
# 【达到的效果】
# 1. 自动化假设生成：从反思自动提取可测试的优化方向
# 2. 置信度过滤：只处理高置信度(>0.7)的改进建议
# 3. 去重机制：避免对相同建议重复生成假设
# 4. 形式化策略：将自然语言转化为可执行的结构化策略
# 5. 状态自动流转：根据测试结果自动验证或拒绝假设
# 6. 持久化存储：假设数据保存到记忆系统，支持跨会话使用
#
# 【使用场景】
# - 任务反思后：Reflector生成反思，HypothesisGenerator提取假设
# - 批量处理：定期批量处理积累的历史反思记录
# - 实验启动：为PENDING状态的假设启动A/B实验验证
# - 结果记录：ExperimentManager测试后记录结果，更新状态
# - 策略推广：VALIDATED的假设被推广为系统默认策略
#
# =============================================================================
