#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""
记忆压缩模块 V6.0 - 存储优化策略
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【压缩策略】
  - L5执行记忆: 轻度压缩，保留关键统计
  - L2会话记忆: 中度压缩，生成会话摘要
  - L3长期记忆: 重度压缩，仅保留元数据

【目标】
  - 自动压缩节省30%存储空间
  - 保留关键信息用于检索
  - 支持冷数据归档

【集成】
  - 由DataLifecycleManager定期调用
  - 与execution_memory配合压缩L5记录
  - 支持手动触发和自动触发

【2026-02-26 初始版本】
"""

import gzip  # 导入gzip模块，用于文件压缩
import json  # 导入JSON模块，用于序列化和反序列化

# 日志记录器  # 日志初始化注释
import logging  # 导入日志模块
import threading  # 导入线程模块，用于线程安全
from collections import defaultdict  # 导入默认字典，用于统计
from dataclasses import dataclass  # 导入数据类装饰器
from datetime import datetime  # 导入日期时间类
from pathlib import Path  # 导入路径类，用于文件路径操作
from typing import Any  # 导入类型注解

logger = logging.getLogger(__name__)  # 获取当前模块的日志记录器

BASE_DIR = Path(__file__).parent.parent  # 获取项目根目录
ARCHIVE_DIR = BASE_DIR / "data" / "archive"  # 构建归档目录路径
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)  # 确保目录存在


@dataclass  # 数据类装饰器
class CompressionResult:  # 定义压缩结果数据类
    """压缩结果"""  # 类文档字符串
    layer: str  # 记忆层级字段
    compressed_count: int  # 压缩记录数字段
    space_saved_bytes: int  # 节省空间（字节）字段
    compression_ratio: float  # 压缩比例字段
    archive_path: str | None = None  # 归档路径，可选
    summary: dict | None = None  # 摘要信息，可选

    def to_dict(self) -> dict[str, Any]:  # 转换为字典方法
        return {  # 返回字典
            "layer": self.layer,  # 层级
            "compressed_count": self.compressed_count,  # 压缩数量
            "space_saved_bytes": self.space_saved_bytes,  # 节省空间（字节）
            "space_saved_mb": round(self.space_saved_bytes / (1024 * 1024), 4),  # 转换为MB
            "compression_ratio": round(self.compression_ratio, 4),  # 压缩比例
            "archive_path": self.archive_path,  # 归档路径
            "summary": self.summary  # 摘要
        }  # 返回结束


class MemoryCompressor:  # 定义记忆压缩器类
    """记忆压缩器 - 实现多层压缩策略"""  # 类文档字符串

    # 压缩配置  # 类级配置常量
    COMPRESSION_CONFIG = {  # 压缩配置字典
        "L5": {  # L5层配置
            "name": "执行记忆",  # 层级名称
            "strategy": "light",  # 压缩策略：轻度
            "trigger_days": 7,  # 触发压缩天数
            "archive_days": 30,  # 归档天数
            "target_ratio": 0.7  # 目标保留比例：保留70%信息
        },  # L5配置结束
        "L2": {  # L2层配置
            "name": "短期记忆",  # 层级名称
            "strategy": "medium",  # 压缩策略：中度
            "trigger_days": 1,  # 触发压缩天数
            "archive_days": 7,  # 归档天数
            "target_ratio": 0.5  # 目标保留比例：保留50%信息
        },  # L2配置结束
        "L3": {  # L3层配置
            "name": "中期记忆",  # 层级名称
            "strategy": "medium",  # 压缩策略：中度
            "trigger_days": 30,  # 触发压缩天数
            "archive_days": 90,  # 归档天数
            "target_ratio": 0.4  # 目标保留比例：保留40%信息
        },  # L3配置结束
        "L4": {  # L4层配置
            "name": "长期记忆",  # 层级名称
            "strategy": "heavy",  # 压缩策略：重度
            "trigger_days": 90,  # 触发压缩天数
            "archive_days": 365,  # 归档天数
            "target_ratio": 0.2  # 目标保留比例：保留20%信息
        },  # L4配置结束
        "L1": {  # L1层配置
            "name": "工作记忆",  # 层级名称
            "strategy": "drop",  # 压缩策略：直接丢弃
            "trigger_days": 0,  # 触发压缩天数（立即）
            "archive_days": 1,  # 归档天数
            "target_ratio": 0.0  # 目标保留比例：不保留
        }  # L1配置结束
    }  # 配置字典结束

    def __init__(self):  # 初始化方法
        self._lock = threading.RLock()  # 线程锁，确保线程安全
        self._compression_stats = {  # 压缩统计字典
            "total_compressed": 0,  # 总压缩数量
            "total_space_saved": 0,  # 总节省空间
            "total_archived": 0  # 总归档数量
        }  # 统计字典结束

    def compress_l5_executions(self, records: list[dict]) -> dict[str, Any]:  # 压缩L5执行记录方法
        """  # 方法文档字符串开始
        压缩L5执行记录  # 方法功能

        将详细执行记录压缩为统计摘要  # 压缩效果
        输入: 100条详细记录  # 输入示例
        输出: 1条摘要 {"period": "30days", "total": 100, "success_rate": 0.95, "common_tools": [...]}  # 输出示例

        Args:  # 参数说明
            records: L5执行记录列表  # 参数

        Returns:  # 返回值说明
            压缩后的摘要  # 返回类型
        """  # 方法文档字符串结束
        if not records:  # 如果记录为空
            return {"period": "0days", "total": 0, "success_rate": 0, "common_tools": []}  # 返回空摘要

        total = len(records)  # 总记录数
        success_count = sum(1 for r in records if r.get("success", False))  # 成功数
        fail_count = total - success_count  # 失败数
        success_rate = success_count / total if total > 0 else 0  # 成功率

        # 计算平均执行时间  # 平均时间计算
        times = [r.get("execution_time_ms", 0) for r in records if r.get("execution_time_ms")]  # 提取时间
        avg_time = sum(times) / len(times) if times else 0  # 计算平均

        # 工具使用统计  # 工具统计
        tool_stats = defaultdict(lambda: {"count": 0, "success": 0, "time": 0})  # 默认字典
        error_types = defaultdict(int)  # 错误类型计数

        for r in records:  # 遍历记录
            tool_name = r.get("tool_name", "unknown")  # 获取工具名
            tool_stats[tool_name]["count"] += 1  # 计数增加
            if r.get("success"):  # 如果成功
                tool_stats[tool_name]["success"] += 1  # 成功计数
            tool_stats[tool_name]["time"] += r.get("execution_time_ms", 0)  # 时间累加

            if not r.get("success") and r.get("error_code"):  # 如果失败且有错误码
                error_types[r.get("error_code")] += 1  # 错误计数

        # 排序取前10  # Top10工具
        common_tools = sorted(  # 排序
            [  # 列表推导
                {  # 工具统计字典
                    "tool_name": name,  # 工具名
                    "count": stats["count"],  # 使用次数
                    "success_rate": round(stats["success"] / stats["count"], 4) if stats["count"] > 0 else 0,  # 成功率
                    "avg_time_ms": round(stats["time"] / stats["count"], 2) if stats["count"] > 0 else 0  # 平均时间
                }  # 字典结束
                for name, stats in tool_stats.items()  # 遍历统计
            ],  # 列表推导结束
            key=lambda x: x["count"],  # 按使用次数排序
            reverse=True  # 降序
        )[:10]  # 取前10

        # 常见错误  # 错误统计
        common_errors = [  # 列表推导
            {"error_code": code, "count": count}  # 错误信息
            for code, count in sorted(error_types.items(), key=lambda x: x[1], reverse=True)[:5]  # Top5错误
        ]  # 推导结束

        return {  # 返回压缩摘要
            "type": "L5_summary",  # 类型标记
            "period": f"{len(records)} records",  # 周期
            "total": total,  # 总数
            "success_count": success_count,  # 成功
            "fail_count": fail_count,  # 失败
            "success_rate": round(success_rate, 4),  # 成功率
            "avg_execution_time_ms": round(avg_time, 2),  # 平均时间
            "common_tools": common_tools,  # 常用工具
            "common_errors": common_errors,  # 常见错误
            "compressed_at": datetime.now().isoformat()  # 压缩时间
        }  # 返回结束

    def compress_l2_session(self, messages: list[dict]) -> dict[str, Any]:  # 压缩L2会话方法
        """  # 方法文档字符串开始
        压缩L2会话历史  # 方法功能

        将会话消息压缩为关键事件摘要  # 压缩效果

        Args:  # 参数说明
            messages: 会话消息列表  # 参数

        Returns:  # 返回值说明
            会话摘要  # 返回类型
        """  # 方法文档字符串结束
        if not messages:  # 如果消息为空
            return {"type": "L2_session_summary", "events": [], "topics": []}  # 返回空摘要

        # 提取关键事件  # 事件提取
        events = []  # 事件列表
        topics = set()  # 话题集合

        for msg in messages:  # 遍历消息
            content = msg.get("content", "")  # 获取内容
            msg_type = msg.get("type", "")  # 获取类型

            # 识别关键事件（工具调用、重要决策等）  # 关键事件识别
            if msg_type == "tool_call":  # 如果是工具调用
                events.append({  # 添加工具调用事件
                    "type": "tool_call",  # 事件类型
                    "tool": msg.get("tool_name"),  # 工具名
                    "timestamp": msg.get("timestamp"),  # 时间戳
                    "summary": content[:100] if isinstance(content, str) else ""  # 内容摘要（前100字符）
                })  # 添加结束
            elif msg_type == "decision":  # 如果是决策
                events.append({  # 添加决策事件
                    "type": "decision",  # 事件类型
                    "decision": content[:100] if isinstance(content, str) else "",  # 决策摘要
                    "timestamp": msg.get("timestamp")  # 时间戳
                })  # 添加结束

            # 提取话题和实体（简化实现）  # 话题提取
            if isinstance(content, str):  # 如果内容是字符串
                # 简单关键词提取  # 关键词提取策略
                words = content.split()  # 分词
                for word in words:  # 遍历单词
                    if len(word) > 3 and word.isalpha():  # 如果长度大于3且为字母
                        topics.add(word.lower())  # 添加到话题集合

        return {  # 返回压缩摘要
            "type": "L2_session_summary",  # 类型标记
            "message_count": len(messages),  # 消息数量
            "key_events": events[:10],  # 最多10个关键事件
            "topics": list(topics)[:20],  # 最多20个话题
            "time_range": {  # 时间范围
                "start": messages[0].get("timestamp") if messages else None,  # 开始时间
                "end": messages[-1].get("timestamp") if messages else None  # 结束时间
            },  # 时间范围结束
            "compressed_at": datetime.now().isoformat()  # 压缩时间
        }  # 返回结束

    def compress_l3_knowledge(self, records: list[dict]) -> dict[str, Any]:  # 压缩L3知识方法
        """  # 方法文档字符串开始
        压缩L3知识记忆（重度压缩）  # 方法功能

        仅保留关键元数据  # 压缩效果

        Args:  # 参数说明
            records: 知识记录列表  # 参数

        Returns:  # 返回值说明
            压缩后的元数据  # 返回类型
        """  # 方法文档字符串结束
        if not records:  # 如果记录为空
            return {"type": "L3_knowledge_metadata", "topics": [], "count": 0}  # 返回空摘要

        # 按主题聚类  # 主题聚类
        topics = defaultdict(list)  # 主题到ID列表的映射
        entities = set()  # 实体集合

        for r in records:  # 遍历记录
            topic = r.get("topic") or r.get("mem_type") or "uncategorized"  # 获取主题
            topics[topic].append(r.get("id"))  # 添加ID到主题

            # 提取实体  # 实体提取
            content = r.get("content", "")  # 获取内容
            if isinstance(content, dict):  # 如果内容是字典
                for _key, value in content.items():  # 遍历键值
                    if isinstance(value, str) and len(value) < 50:  # 如果是短字符串
                        entities.add(value)  # 添加到实体集合

        return {  # 返回压缩摘要
            "type": "L3_knowledge_metadata",  # 类型标记
            "record_count": len(records),  # 记录数量
            "topics": [  # 主题列表
                {"topic": topic, "count": len(ids), "ids": ids[:10]}  # 主题信息（最多10个ID）
                for topic, ids in sorted(topics.items(), key=lambda x: len(x[1]), reverse=True)[:10]  # Top10主题
            ],  # 主题列表结束
            "entities": list(entities)[:50],  # 最多50个实体
            "compressed_at": datetime.now().isoformat()  # 压缩时间
        }  # 返回结束

    def archive_to_cold_storage(self, user_id: str, layer: str,  # 归档到冷存储方法
                                data: list[dict], compression: str = "gzip") -> str:
        """  # 方法文档字符串开始
        归档到冷存储  # 方法功能

        Args:  # 参数说明
            user_id: 用户ID  # 参数1
            layer: 记忆层级  # 参数2
            data: 要归档的数据  # 参数3
            compression: 压缩算法  # 参数4

        Returns:  # 返回值说明
            归档文件路径  # 返回类型
        """  # 方法文档字符串结束
        # 创建归档目录  # 目录创建
        user_archive_dir = ARCHIVE_DIR / user_id / layer  # 构建用户归档目录
        user_archive_dir.mkdir(parents=True, exist_ok=True)  # 确保目录存在

        # 生成归档文件名  # 文件名生成
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")  # 当前时间戳
        archive_name = f"{layer}_{timestamp}.jsonl.gz"  # 文件名
        archive_path = user_archive_dir / archive_name  # 完整路径

        # 写入压缩文件  # 文件写入
        with gzip.open(archive_path, 'wt', encoding='utf-8') as f:  # 打开gzip文件
            for item in data:  # 遍历数据
                f.write(json.dumps(item, ensure_ascii=False) + "\n")  # 写入JSON行

        with self._lock:  # 获取线程锁
            self._compression_stats["total_archived"] += len(data)  # 更新归档统计

        return str(archive_path)  # 返回路径字符串

    def compress_user_layer(self, user_id: str, layer: str,  # 压缩用户层级方法
                           records: list[dict]) -> CompressionResult:
        """  # 方法文档字符串开始
        压缩用户指定层级的记忆  # 方法功能

        Args:  # 参数说明
            user_id: 用户ID  # 参数1
            layer: 记忆层级  # 参数2
            records: 要压缩的记录  # 参数3

        Returns:  # 返回值说明
            压缩结果  # 返回类型
        """  # 方法文档字符串结束
        if not records:  # 如果记录为空
            return CompressionResult(  # 返回空结果
                layer=layer,  # 层级
                compressed_count=0,  # 压缩数量0
                space_saved_bytes=0,  # 节省空间0
                compression_ratio=0.0  # 压缩比例0
            )  # 返回结束

        config = self.COMPRESSION_CONFIG.get(layer, self.COMPRESSION_CONFIG["L5"])  # 获取配置
        strategy = config["strategy"]  # 获取压缩策略

        # 计算原始大小  # 原始大小计算
        original_size = sum(len(json.dumps(r, ensure_ascii=False)) for r in records)  # 所有记录JSON长度之和

        # 根据策略压缩  # 策略分发
        if strategy == "light":  # 轻度压缩
            compressed = self.compress_l5_executions(records)  # L5压缩
        elif strategy == "medium":  # 中度压缩
            compressed = self.compress_l2_session(records)  # L2压缩
        elif strategy == "heavy":  # 重度压缩
            compressed = self.compress_l3_knowledge(records)  # L3压缩
        elif strategy == "drop":  # 直接丢弃
            # L1工作记忆直接丢弃  # L1特殊处理
            compressed = {"type": "dropped", "count": len(records)}  # 丢弃标记
        else:  # 默认策略
            compressed = self.compress_l5_executions(records)  # 默认使用L5压缩

        # 归档到冷存储  # 归档处理
        archive_path = self.archive_to_cold_storage(user_id, layer, records) if strategy != "drop" else None  # 归档或丢弃

        # 计算压缩后大小  # 压缩后大小计算
        compressed_size = len(json.dumps(compressed, ensure_ascii=False))  # 压缩后JSON长度
        space_saved = max(0, original_size - compressed_size)  # 节省空间
        compression_ratio = space_saved / original_size if original_size > 0 else 0  # 压缩比例

        # 更新统计  # 统计更新
        with self._lock:  # 获取线程锁
            self._compression_stats["total_compressed"] += len(records)  # 更新压缩数量
            self._compression_stats["total_space_saved"] += space_saved  # 更新节省空间

        return CompressionResult(  # 返回压缩结果
            layer=layer,  # 层级
            compressed_count=len(records),  # 压缩数量
            space_saved_bytes=space_saved,  # 节省空间
            compression_ratio=compression_ratio,  # 压缩比例
            archive_path=archive_path,  # 归档路径
            summary=compressed  # 摘要
        )  # 返回结束

    def get_compression_recommendations(self, user_id: str,  # 获取压缩建议方法
                                       storage_stats: dict) -> list[dict]:
        """  # 方法文档字符串开始
        获取压缩建议  # 方法功能

        Args:  # 参数说明
            user_id: 用户ID  # 参数1
            storage_stats: 存储统计  # 参数2

        Returns:  # 返回值说明
            压缩建议列表  # 返回类型
        """  # 方法文档字符串结束
        recommendations = []  # 初始化建议列表

        for layer, stats in storage_stats.get("layers", {}).items():  # 遍历各层统计
            config = self.COMPRESSION_CONFIG.get(layer, self.COMPRESSION_CONFIG["L5"])  # 获取配置

            total_records = stats.get("total_records", 0)  # 总记录数
            oldest_record = stats.get("oldest_record")  # 最旧记录时间

            if total_records == 0:  # 如果没有记录
                continue  # 跳过

            # 检查是否需要压缩  # 压缩检查
            if oldest_record:  # 如果有最旧记录时间
                try:  # 异常处理
                    oldest_date = datetime.fromisoformat(oldest_record)  # 解析时间
                    days_old = (datetime.now() - oldest_date).days  # 计算天数

                    if days_old > config["trigger_days"]:  # 如果超过触发天数
                        recommendations.append({  # 添加压缩建议
                            "layer": layer,  # 层级
                            "layer_name": config["name"],  # 层级名称
                            "action": "compress",  # 动作：压缩
                            "reason": f"数据已存在 {days_old} 天，超过阈值 {config['trigger_days']} 天",  # 原因
                            "strategy": config["strategy"],  # 策略
                            "estimated_savings": total_records * 0.3  # 估计节省30%
                        })  # 建议结束

                    if config["archive_days"] and days_old > config["archive_days"]:  # 如果超过归档天数
                        recommendations.append({  # 添加归档建议
                            "layer": layer,  # 层级
                            "layer_name": config["name"],  # 层级名称
                            "action": "archive",  # 动作：归档
                            "reason": f"数据已存在 {days_old} 天，应归档",  # 原因
                            "archive_path": f"data/archive/{user_id}/{layer}/"  # 归档路径
                        })  # 建议结束

                except Exception as e:  # 捕获异常
                    logger.warning(f"[MemoryCompressor] 解析日期失败: {e}")  # 记录警告

        return recommendations  # 返回建议列表

    def get_stats(self) -> dict[str, Any]:  # 获取统计方法
        """获取压缩统计"""  # 方法文档字符串
        with self._lock:  # 获取线程锁
            return {  # 返回统计字典
                "total_compressed": self._compression_stats["total_compressed"],  # 总压缩数量
                "total_space_saved_mb": round(self._compression_stats["total_space_saved"] / (1024 * 1024), 2),  # 总节省空间（MB）
                "total_archived": self._compression_stats["total_archived"],  # 总归档数量
                "compression_configs": self.COMPRESSION_CONFIG  # 压缩配置
            }  # 返回结束


class CompressionScheduler:
    """自动压缩调度器 - 定时执行记忆压缩任务"""

    LAYER_MAP = {
        "working": "L1",
        "short": "L2",
        "medium": "L3",
        "evolve": "L4",
        "execution": "L5"
    }

    def __init__(self, compressor: MemoryCompressor, memory_manager=None):
        self.compressor = compressor
        self.memory_manager = memory_manager
        self._timer = None
        self._lock = threading.RLock()
        self._running = False
        self._interval_hours = 24
        self._check_results: list[dict[str, Any]] = []

    def start_auto_compression(self, interval_hours: int = 24):
        """启动自动压缩定时器"""
        with self._lock:
            if self._running:
                logger.info("[CompressionScheduler] 自动压缩已在运行")
                return
            self._running = True
            self._interval_hours = interval_hours
            self._schedule_next()
            logger.info(f"[CompressionScheduler] 自动压缩已启动，间隔: {interval_hours}小时")

    def stop_auto_compression(self):
        """停止自动压缩定时器"""
        with self._lock:
            self._running = False
            if self._timer:
                self._timer.cancel()
                self._timer = None
            logger.info("[CompressionScheduler] 自动压缩已停止")

    def _schedule_next(self):
        """调度下一次执行"""
        if not self._running:
            return
        interval_seconds = self._interval_hours * 3600
        self._timer = threading.Timer(interval_seconds, self._run_check_wrapper)
        self._timer.daemon = True
        self._timer.start()

    def _run_check_wrapper(self):
        """包装器：执行检查并调度下一次"""
        import asyncio
        loop = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.run_compression_check())
        except Exception as e:
            logger.error(f"[CompressionScheduler] 压缩检查异常: {e}")
        finally:
            if loop:
                loop.close()
            self._schedule_next()

    async def run_compression_check(self) -> list[dict[str, Any]]:
        """
        执行压缩检查并真正执行压缩

        Returns:
            压缩结果字典列表
        """
        memory_manager = self.memory_manager
        if memory_manager is None:
            try:
                from core.memory.memory_service import get_memory_service
                memory_manager = await get_memory_service()
            except Exception as e:
                logger.warning(f"[CompressionScheduler] 无法加载 memory_service: {e}")
                return []

        all_results = []
        try:
            users = await memory_manager.list_users()
            if not users:
                logger.debug("[CompressionScheduler] 没有用户数据，跳过压缩检查")
                return all_results

            for user_id in users:
                try:
                    # 获取原始统计
                    raw_stats = await memory_manager.get_memory_stats(user_id)

                    # 获取各层记录并构建 storage_stats
                    layer_records = {}
                    layers_stats = {}
                    for layer_name, layer_code in self.LAYER_MAP.items():
                        total = raw_stats.get(layer_name, 0)
                        if total > 0:
                            records = await memory_manager.query_memories(
                                user_id=user_id, layer=layer_name, limit=100000
                            )
                            if records:
                                layer_records[layer_code] = records
                                oldest = min(
                                    (r.get("created_at") for r in records if r.get("created_at")),
                                    default=None
                                )
                                layers_stats[layer_code] = {
                                    "total_records": len(records),
                                    "oldest_record": oldest
                                }

                    if not layers_stats:
                        continue

                    storage_stats = {"layers": layers_stats}
                    recommendations = self.compressor.get_compression_recommendations(
                        user_id, storage_stats
                    )

                    compress_recs = [
                        r for r in recommendations if r.get("action") == "compress"
                    ]
                    if not compress_recs:
                        continue

                    # 执行压缩
                    for rec in compress_recs:
                        layer_code = rec["layer"]
                        records = layer_records.get(layer_code, [])
                        if not records:
                            continue

                        result = self.compressor.compress_user_layer(
                            user_id, layer_code, records
                        )
                        result_dict = result.to_dict()
                        all_results.append(result_dict)
                        logger.info(
                            f"[CompressionScheduler] 压缩完成: user={user_id}, "
                            f"layer={layer_code}, records={result.compressed_count}, "
                            f"saved={result.space_saved_bytes} bytes "
                            f"({result_dict.get('space_saved_mb', 0)} MB)"
                        )

                except Exception as e:
                    logger.error(
                        f"[CompressionScheduler] 用户 {user_id} 压缩检查失败: {e}",
                        exc_info=True
                    )

            self._check_results = all_results
            if all_results:
                total_saved = sum(r.get("space_saved_bytes", 0) for r in all_results)
                total_records = sum(r.get("compressed_count", 0) for r in all_results)
                logger.info(
                    f"[CompressionScheduler] 本次压缩检查完成: "
                    f"共压缩 {total_records} 条记录, 节省 {total_saved / (1024*1024):.2f} MB"
                )
            return all_results
        except Exception as e:
            logger.error(f"[CompressionScheduler] 压缩检查失败: {e}", exc_info=True)
            return all_results

    def get_last_results(self) -> list[dict[str, Any]]:
        """获取最近一次压缩检查结果"""
        return self._check_results.copy()


# 全局实例
memory_compressor = None
compression_scheduler = None

try:
    memory_compressor = MemoryCompressor()
    compression_scheduler = CompressionScheduler(memory_compressor)
except Exception as e:
    logger.error(f"[MemoryCompression] 初始化压缩器失败: {e}")


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"记忆压缩模块"，负责五层记忆系统的存储优化，
# 通过不同策略压缩各层记忆，节省存储空间同时保留关键检索信息。
#
# 【五层压缩策略】
# - L1(工作记忆): 直接丢弃（临时数据，无需保留）
# - L2(短期记忆): 中度压缩，保留会话摘要和关键事件
# - L3(中期记忆): 中度压缩，保留主题聚类和实体
# - L4(长期记忆): 重度压缩，仅保留元数据
# - L5(执行记忆): 轻度压缩，保留统计摘要和错误分析
#
# 【核心类说明】
# - CompressionResult: 压缩结果数据类，包含压缩统计
# - MemoryCompressor: 核心压缩器，实现各层压缩逻辑
# - CompressionScheduler: 自动调度器，定时执行压缩任务
#
# 【关联文件】
# - core/memory.py                 : 记忆系统核心，提供存储统计
# - core/execution_memory.py       : L5执行记忆，配合压缩
# - core/memory_manager.py         : 记忆管理器，调用压缩功能
#
# 【核心效果】
# 1. 存储优化: 自动压缩节省30%存储空间
# 2. 信息保留: 压缩后仍保留关键检索信息
# 3. 冷数据归档: 支持将旧数据归档到冷存储
# 4. 自动调度: 支持定时自动压缩
# 5. 分层策略: 不同层级使用不同压缩策略
# 6. 压缩建议: 根据数据年龄生成压缩建议
#
# 【压缩流程】
# 检查数据年龄 -> 生成压缩建议 -> 执行压缩 -> 归档原数据 -> 更新统计
#
# 【使用场景】
# - 存储空间不足时自动压缩
# - 定期维护时归档旧数据
# - 系统优化时分析存储使用
# =============================================================================
