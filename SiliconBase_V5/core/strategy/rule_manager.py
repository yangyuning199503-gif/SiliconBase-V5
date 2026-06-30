#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
"""  # 多行文档字符串开始
规则管理器 - 存储、检索和应用元学习规则  # 模块标题和功能概述
"""  # 文档字符串结束
import json  # 导入JSON模块，用于序列化规则
import logging  # 导入日志模块，用于类型标注
import threading  # 导入线程模块，用于实现单例模式
from typing import Any, cast  # 导入类型注解

from core.logger import logger as _logger  # 导入日志记录器
from core.memory.memory_service import get_memory_service  # 【P1-迁移】使用新 MemoryService
from core.memory.memory_source import MemorySource  # Agent-4: 导入MemorySource枚举

# 为 strict 类型检查提供明确类型
logger: logging.Logger = cast(logging.Logger, _logger)


class RuleManager:  # 规则管理器主类
    _instance = None  # 类变量：单例实例引用
    _lock = threading.Lock()  # 类变量：线程锁

    def __new__(cls):  # 重写new方法实现单例
        with cls._lock:  # 获取锁
            if cls._instance is None:  # 如果实例不存在
                cls._instance = super().__new__(cls)  # 创建实例
        return cls._instance  # 返回实例

    def __init__(self):  # 构造函数
        if '_initialized' in self.__dict__:  # 如果已初始化
            return  # 直接返回
        self._initialized = True  # 标记已初始化
        # 从向量库中加载所有规则（可选）  # 初始化加载
        self._load_rules()  # 调用加载方法

    def _load_rules(self):  # 从记忆库加载规则
        """从记忆库加载所有规则（用于预热）"""  # 方法文档字符串
        # 不需要主动加载，每次检索时直接查库  # 懒加载策略
        pass  # 空实现

    async def add_rule(self, rule: dict[str, Any]) -> str:  # 添加规则
        """添加一条规则，返回规则ID"""  # 方法文档字符串
        ms = await get_memory_service()
        rule_id = await ms.add_memory(
            user_id="default_user",
            content=json.dumps(rule, ensure_ascii=False),
            memory_type="rule",
            layer="evolve",
            context={"source": "external", "timestamp": __import__('time').time()},
            scene="rule",
            rating=int(rule.get("confidence", 0.5) * 10),
            expire_days=None,
            source=MemorySource.SYSTEM
        )
        # 同时存入向量库用于语义检索  # 向量存储
        ms = await get_memory_service()
        await ms.vector_store.add(
            collection="rules",
            text=f"条件：{rule.get('condition','')} 动作：{rule.get('action','')}",
            metadata={"rule_id": rule_id, "confidence": rule.get("confidence",0.5)},
        )
        return rule_id  # 返回规则ID

    async def search_rules(self, query: str, limit: int = 5) -> list[dict[str, Any]]:  # 搜索规则
        """根据当前任务描述和感知信息检索相关规则"""  # 方法文档字符串
        try:  # 异常处理
            ms = await get_memory_service()
            results: list[Any] = await ms.vector_store.search(
                collection="rules",
                query=query,
                limit=limit,
            )
            if not results:  # 如果无结果
                return []  # 返回空列表
            rule_ids: list[str] = []
            for r in results:
                metadata: dict[str, Any] = getattr(r, "metadata", {})
                rid = metadata.get("rule_id", getattr(r, "id", ""))
                if isinstance(rid, str):
                    rule_ids.append(rid)
            # 从记忆库获取完整规则  # 查询记忆系统
            memories: list[dict[str, Any]] = await ms.get_memories_by_ids(rule_ids)  # 根据ID获取记忆
            rules: list[dict[str, Any]] = []  # 规则列表
            for m in memories:  # 遍历记忆
                try:  # 异常处理
                    rule: dict[str, Any] = json.loads(m["content"])  # 解析JSON
                    rule["id"] = m["id"]  # 添加ID字段
                    rules.append(rule)  # 添加到列表
                except Exception as e:  # 解析失败
                    logger.warning(f"规则解析失败: {e}")  # 记录警告
                    continue  # 跳过
            return rules  # 返回规则列表
        except Exception as e:  # 查询失败
            logger.error(f"规则检索失败: {e}")  # 记录错误
            return []  # 返回空列表

    async def update_confidence(self, rule_id: str, delta: float):  # 更新置信度
        """根据规则应用效果调整置信度"""  # 方法文档字符串
        ms = await get_memory_service()
        mem = await ms.get_memories_by_ids([rule_id])  # 获取记忆
        if not mem:  # 如果不存在
            return  # 直接返回
        mem = mem[0]  # 取第一条
        try:  # 异常处理
            rule = json.loads(mem["content"])  # 解析规则
            old_conf = rule.get("confidence", 0.5)  # 获取旧置信度
            new_conf = max(0.0, min(1.0, old_conf + delta))  # 调整并限制在0-1
            rule["confidence"] = new_conf  # 更新置信度
            # 更新记忆库
            await ms.add_memory(  # 添加新记录
                user_id="default_user",
                content=json.dumps(rule, ensure_ascii=False),  # 序列化
                memory_type="rule",  # 类型为规则
                layer="evolve",  # L5进化层
                context=mem.get("context", {}),  # 保留原上下文
                scene="rule",  # 场景
                rating=int(new_conf * 10),  # 新评分
                expire_days=None,  # 不过期
                source=MemorySource.SYSTEM  # Agent-4: 系统写入
            )  # 添加结束
            logger.debug(f"规则 {rule_id} 置信度更新为 {new_conf}")  # 记录调试
        except Exception as e:  # 更新失败
            logger.error(f"更新规则置信度失败: {e}")  # 记录错误


# =============================================================================  # 分隔线
# 【文件总结】  # 总结区域标题
# =============================================================================  # 分隔线
# 文件角色：规则管理器，负责元学习规则的存储、检索和更新  # 角色说明
# 核心功能：  # 功能列表
#   1. 规则添加 - 将新规则保存到记忆系统和向量库  # 功能1
#   2. 规则检索 - 基于语义相似度检索相关规则  # 功能2
#   3. 置信度更新 - 根据规则应用效果调整置信度  # 功能3
# 存储策略：  # 存储说明
#   - 记忆系统(L5进化层)：存储完整的规则JSON  # 存储1
#   - 向量库：存储规则的语义表示，用于相似度检索  # 存储2
# 规则格式：  # 格式说明
#   {  # 示例
#       "condition": "触发条件描述",  # 条件
#       "action": "执行动作描述",  # 动作
#       "confidence": 0.8  # 置信度0-1
#   }  # 示例结束
# 关联文件：  # 关联说明
#   - core/memory.py: 记忆系统（规则持久化）  # 关联1
#   - core/vector_memory.py: 向量记忆（语义检索）  # 关联2
#   - core/meta_learner.py: 元学习器（规则生成和评估）  # 关联3
# 达到效果：  # 效果说明
#   - 支持AI从经验中提取规则并存储  # 效果1
#   - 支持基于任务描述的规则检索  # 效果2
#   - 支持规则置信度的动态调整  # 效果3
#   - 为经验复用提供基础设施  # 效果4
# =============================================================================  # 分隔线结束
