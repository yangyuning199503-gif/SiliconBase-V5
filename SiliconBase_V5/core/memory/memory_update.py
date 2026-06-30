#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""
原子工具：更新记忆 - 允许AI修改已有记忆的内容或评分（保持原ID不变）

【功能说明】
  - 支持更新记忆内容
  - 支持更新记忆评分（-1到1之间）
  - 支持更新记忆过期时间
  - 自动同步更新向量库（AI笔记和用户偏好类型）

【使用场景】
  - AI发现记忆内容需要修正时
  - 用户反馈需要调整记忆评分时
  - 需要延长或缩短记忆有效期时
"""
import contextlib
from datetime import datetime, timedelta  # 导入日期时间类，用于计算过期时间

from core.logger import logger  # 导入日志记录器
from core.memory.memory_service import get_memory_service
from core.tool.base_tool import BaseTool  # 导入基础工具类
from core.utils.error_codes import TOOL_EXECUTION_ERROR, format_error  # 导入错误码格式化函数和常量


class MemoryUpdate(BaseTool):  # 定义记忆更新工具类，继承自BaseTool
    tool_id = "memory_update"  # 工具唯一标识符
    name = "更新记忆"  # 工具中文名称
    description = "更新已有记忆的内容或评分（保持原ID不变）。"  # 工具功能描述
    input_schema = {  # 输入参数模式定义（JSON Schema格式）
        "type": "object",  # 类型为对象
        "properties": {  # 属性定义开始
            "memory_id": {"type": "string", "description": "要更新的记忆ID"},  # 记忆ID参数
            "content": {"type": "string", "description": "新内容"},  # 新内容参数
            "rating": {"type": "integer", "minimum": -1, "maximum": 1, "description": "新评分"},  # 新评分参数（范围-1到1）
            "expire_days": {"type": "integer", "minimum": 1, "description": "新过期天数"}  # 新过期天数参数
        },  # 属性定义结束
        "required": ["memory_id"],  # 必需参数：memory_id
        "anyOf": [  # 至少满足以下条件之一
            {"required": ["content"]},  # 条件1：必须提供content
            {"required": ["rating"]},  # 条件2：必须提供rating
            {"required": ["expire_days"]}  # 条件3：必须提供expire_days
        ]  # 条件结束
    }  # input_schema结束

    async def run(self, **kwargs):  # 运行方法，接收任意关键字参数
        mem_id = kwargs["memory_id"]  # 获取记忆ID参数

        # 先获取原记录，确认存在并获取必要信息  # 前置检查注释
        ms = await get_memory_service()
        old_list = await ms.get_memories_by_ids([mem_id])  # 通过ID查询原记忆记录
        if not old_list:  # 如果记录不存在
            return {  # 返回错误结果
                "success": False,  # 失败标志
                "error_code": "MEMORY_NOT_FOUND",  # 错误码：记忆不存在
                "user_message": f"记忆 {mem_id} 不存在"  # 用户友好的错误消息
            }  # 返回结束
        old = old_list[0]  # 获取原记录（查询返回列表，取第一个元素）

        # 构建更新字段  # 构建更新字段注释
        update_fields = {}  # 初始化更新字段字典
        if "content" in kwargs:  # 如果提供了content参数
            update_fields["content"] = kwargs["content"]  # 添加到更新字段
        if "rating" in kwargs:  # 如果提供了rating参数
            update_fields["rating"] = kwargs["rating"]  # 添加到更新字段
        if "expire_days" in kwargs:  # 如果提供了expire_days参数
            # 计算过期时间戳  # 过期时间计算注释
            expire_at = (datetime.now() + timedelta(days=kwargs["expire_days"])).strftime("%Y-%m-%d %H:%M:%S")  # 当前时间加天数，格式化为字符串
            update_fields["expire_at"] = expire_at  # 添加到更新字段

        if not update_fields:  # 如果没有需要更新的字段
            return {  # 返回错误结果
                "success": False,  # 失败标志
                "error_code": "NO_CHANGE",  # 错误码：无变更
                "user_message": "未提供任何要更新的字段"  # 用户友好的错误消息
            }  # 返回结束

        # 使用 memory.update() 方法更新记忆  # 调用核心更新方法
        try:  # 异常处理开始
            result = await ms.update_memory(mem_id, update_fields)  # 调用记忆更新方法
            if not result:  # 如果更新失败（返回False或None）
                return {  # 返回错误结果
                    "success": False,  # 失败标志
                    "error_code": "MEMORY_NOT_FOUND",  # 错误码：记忆不存在
                    "user_message": f"记忆 {mem_id} 不存在"  # 用户友好的错误消息
                }  # 返回结束

            # 【修复】同步更新向量库（如果该类型需要）  # 向量库同步注释
            # 注意：此代码块已修复缩进，现在在更新成功后执行  # 修复说明
            if old["mem_type"] in ["ai_note", "user_preference"]:  # 检查记忆类型是否需要同步向量库
                # 尝试更新向量库：先删除原文档，再添加新文档
                try:
                    for collection in ["chat", "knowledge", "experience"]:
                        with contextlib.suppress(Exception):
                            await ms.vector_store.delete(collection, [mem_id])
                except Exception as e:
                    logger.warning(f"向量库删除旧文档失败: {e}")

                # 添加新文档
                try:
                    new_content = kwargs.get("content", old["content"])
                    await ms.vector_store.add("chat", new_content, {"mem_id": mem_id, "source": "ai_updated"})
                except Exception as e:
                    logger.warning(f"向量库添加新文档失败: {e}")

            logger.info(f"AI更新记忆: {mem_id} 成功")  # 记录成功日志
            return {  # 返回成功结果
                "success": True,  # 成功标志
                "data": {"memory_id": mem_id},  # 返回数据
                "user_message": f"记忆 {mem_id} 已更新"  # 用户友好的成功消息
            }  # 返回结束

        except Exception as e:  # 捕获所有异常
            return format_error(TOOL_EXECUTION_ERROR, detail=str(e))  # 格式化并返回错误


# =============================================================================
# 总结性注释：文件角色、关联关系与核心效果
# =============================================================================
#
# 【文件角色】
# 本文件（memory_update.py）是 SiliconBase V5 系统的"记忆更新原子工具"，
# 属于AI工具层（Tool Layer）的核心组件。它提供标准接口供AI Agent调用，
# 用于修改已存在的记忆记录（内容、评分、过期时间），并保持向量库同步。
#
# 【核心定位】
# - 原子工具：遵循BaseTool规范，可被Agent自动识别和调用
# - 双存储同步：PostgreSQL（结构化）+ ChromaDB（向量语义）同步更新
# - 记忆修正：支持AI自我纠错和用户反馈驱动的记忆更新
#
# 【类结构】
# MemoryUpdate(BaseTool)
# ├── tool_id = "memory_update"          # 工具唯一标识
# ├── name = "更新记忆"                  # 中文名称
# ├── description                        # 功能描述
# ├── input_schema                       # JSON Schema参数校验
# └── run(**kwargs)                      # 执行入口
#     ├── 查询原记录                      # 验证记忆存在
#     ├── 构建更新字段                    # 处理content/rating/expire_days
#     ├── 执行PostgreSQL更新              # memory.update()
#     ├── 【条件】同步向量库              # ai_note/user_preference类型
#     │   ├── 删除旧向量                  # 从多个集合中删除
#     │   └── 添加新向量                  # 重新嵌入新内容
#     └── 返回结果                        # 成功/失败统一格式
#
# 【本次修复说明】
# 修复了第87-108行的缩进错误：
# - 原问题：向量同步代码缩进在 "if not result:" 块内，但位于return之后，永不可达
# - 修复后：向量同步代码移出if块，在更新成功(result为True)后正确执行
# - 影响：ai_note和user_preference类型的记忆更新现在会正确同步到向量库
#
# 【关联文件】
# 1. core/base_tool.py              - 基础工具类定义
#    * 关系：继承基类
#    * 交互：遵循工具注册和调用规范
#
# 2. core/memory.py                 - PostgreSQL记忆核心
#    * 关系：核心依赖
#    * 交互：memory.update(), memory.get_by_ids()
#
# 3. core/vector_memory.py          - 向量记忆管理
#    * 关系：条件依赖（仅特定类型使用）
#    * 交互：vector_memory._chat_collection.add(), 各集合delete()
#
# 4. core/error_codes.py            - 错误码系统
#    * 关系：错误处理
#    * 交互：format_error(), TOOL_EXECUTION_ERROR
#
# 5. core/logger.py                 - 日志系统
#    * 关系：日志记录
#    * 交互：logger.info(), logger.warning()
#
# 6. core/agent_loop.py             - Agent主循环
#    * 关系：调用方
#    * 交互：Agent决策后调用此工具
#
# 【达到的效果】
# 1. 记忆修正能力：AI可以纠正错误或过时的记忆内容
# 2. 评分调整：支持根据用户反馈调整记忆重要性（-1到1）
# 3. 生命周期管理：支持动态调整记忆过期时间
# 4. 向量同步：特定类型（ai_note/user_preference）自动同步向量库
# 5. 数据一致性：结构化存储和语义向量保持一致
# 6. 安全验证：先查询确认存在，避免无效操作
# 7. 错误处理：完善的错误码和用户友好消息
# 8. 原子操作：单条记忆的完整更新流程
#
# 【适用记忆类型】
# - ai_note: AI自主生成的笔记，需要语义检索
# - user_preference: 用户偏好设置，需要语义匹配
# - 其他类型：仅更新PostgreSQL，不同步向量库
#
# 【使用场景】
# - 用户纠正AI的错误记忆时
# - AI自我反思发现记忆需要更新时
# - 用户反馈调整记忆重要性（评分）时
# - 延长重要记忆的保留时间（过期时间）时
# - 修正过时信息时
#
# 【数据流】
# User/AI触发 -> Agent决策 -> MemoryUpdate.run()
#                    |
#                    ├──> memory.get_by_ids() [查询验证]
#                    ├──> memory.update() [PostgreSQL更新]
#                    └──> vector_memory操作 [ChromaDB同步，条件触发]
#                    |
#              返回统一格式结果
#
# =============================================================================
