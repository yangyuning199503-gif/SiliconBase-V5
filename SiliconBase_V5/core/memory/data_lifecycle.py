#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""
数据生命周期管理模块 V5.1
第十层基础设施：管理记忆数据的生命周期，包括压缩、归档和清理

功能:
- 按计划压缩记忆数据（将详细记录摘要为关键信息）
- 归档冷数据到廉价存储
- 清理过期数据
- 提供存储统计监控

版本历史:
- 2026-02-26: 初始版本，实现基础生命周期管理
"""

import gzip  # 导入gzip模块：用于压缩归档
import json  # 导入JSON模块
import logging  # 导入日志模块
import threading  # 导入线程模块
from collections.abc import Callable  # 导入类型注解工具
from dataclasses import dataclass, field  # 导入数据类装饰器
from datetime import datetime, timedelta  # 从datetime导入日期时间和时间差类
from enum import Enum  # 导入枚举类
from pathlib import Path  # 导入路径类

logger = logging.getLogger(__name__)  # 获取本模块的日志记录器


class CompressionLevel(Enum):  # 定义压缩级别枚举类
    """压缩级别"""  # 类文档字符串
    LIGHT = "light"  # 轻度压缩，保留关键信息
    MEDIUM = "medium"  # 中度压缩，摘要处理
    HEAVY = "heavy"  # 重度压缩，仅保留元数据


@dataclass  # 使用数据类装饰器
class MemoryLayerConfig:  # 定义记忆层级配置数据类
    """记忆层级配置"""  # 类文档字符串
    layer: str  # 层级名称 (L5, L2, L3)
    keep_days: int  # 保留天数
    compress_after: int  # 压缩触发天数
    compression_level: CompressionLevel = CompressionLevel.MEDIUM  # 压缩级别，默认中度
    archive_after: int | None = None  # 归档触发天数（可选）
    archive_storage: str = "local"  # 归档存储位置 (local, s3, glacier)


@dataclass  # 使用数据类装饰器
class CompressionTask:  # 定义压缩任务数据类
    """压缩任务"""  # 类文档字符串
    task_id: str  # 任务ID
    user_id: str  # 用户ID
    layer: str  # 层级
    before_date: datetime  # 压缩该日期之前的数据
    status: str = "pending"  # 状态：pending, running, completed, failed
    created_at: datetime = field(default_factory=datetime.now)  # 创建时间
    started_at: datetime | None = None  # 开始时间
    completed_at: datetime | None = None  # 完成时间
    result: dict | None = None  # 结果
    error: str | None = None  # 错误信息


@dataclass  # 使用数据类装饰器
class StorageStats:  # 定义存储统计数据类
    """存储统计"""  # 类文档字符串
    user_id: str  # 用户ID
    layer: str  # 层级
    total_records: int  # 总记录数
    total_size_bytes: int  # 总大小（字节）
    compressed_records: int  # 已压缩记录数
    archived_records: int  # 已归档记录数
    oldest_record: datetime | None = None  # 最早记录时间
    newest_record: datetime | None = None  # 最新记录时间
    compression_ratio: float = 0.0  # 压缩率 (0-1)

    def to_dict(self) -> dict:  # 定义转换为字典方法
        """转换为字典"""  # 方法文档字符串
        return {  # 返回字典
            "user_id": self.user_id,  # 用户ID
            "layer": self.layer,  # 层级
            "total_records": self.total_records,  # 总记录数
            "total_size_bytes": self.total_size_bytes,  # 总大小（字节）
            "total_size_mb": round(self.total_size_bytes / (1024 * 1024), 4),  # 总大小（MB）
            "compressed_records": self.compressed_records,  # 已压缩记录数
            "archived_records": self.archived_records,  # 已归档记录数
            "oldest_record": self.oldest_record.isoformat() if self.oldest_record else None,  # 最早记录
            "newest_record": self.newest_record.isoformat() if self.newest_record else None,  # 最新记录
            "compression_ratio": self.compression_ratio  # 压缩率
        }


class DataLifecycleManager:  # 定义数据生命周期管理器类
    """
    管理记忆数据的生命周期  # 类文档字符串标题

    提供自动压缩、归档和清理功能，优化存储使用  # 功能说明
    """  # 类文档字符串结束

    # 默认压缩规则
    DEFAULT_COMPRESSION_RULES = {  # 类常量：默认压缩规则字典
        "L5": {  # L5层级（短期记忆）规则
            "keep_days": 30,  # 保留30天
            "compress_after": 7,  # 7天后压缩
            "compression_level": CompressionLevel.LIGHT,  # 轻度压缩
            "archive_after": None  # 不归档
        },
        "L2": {  # L2层级（中期记忆）规则
            "keep_days": 90,  # 保留90天
            "compress_after": 30,  # 30天后压缩
            "compression_level": CompressionLevel.MEDIUM,  # 中度压缩
            "archive_after": 60  # 60天后归档
        },
        "L3": {  # L3层级（长期记忆）规则
            "keep_days": 365,  # 保留365天
            "compress_after": 90,  # 90天后压缩
            "compression_level": CompressionLevel.HEAVY,  # 重度压缩
            "archive_after": 180  # 180天后归档
        }
    }

    def __init__(self,  # 初始化方法
                 data_dir: str | None = None,  # 参数：数据目录（可选）
                 archive_dir: str | None = None,  # 参数：归档目录（可选）
                 compression_rules: dict | None = None  # 参数：压缩规则（可选）
                 ):
        """
        初始化数据生命周期管理器  # 方法文档字符串标题

        Args:  # 参数说明
            data_dir: 数据存储目录  # 参数1
            archive_dir: 归档存储目录  # 参数2
            compression_rules: 自定义压缩规则  # 参数3
        """  # 方法文档字符串结束
        # 设置目录
        base_dir = Path(__file__).parent.parent  # 获取项目根目录
        self._data_dir = Path(data_dir) if data_dir else base_dir / "data" / "lifecycle"  # 数据目录
        self._archive_dir = Path(archive_dir) if archive_dir else base_dir / "data" / "archive"  # 归档目录

        # 确保目录存在
        self._data_dir.mkdir(parents=True, exist_ok=True)  # 创建数据目录（如果不存在）
        self._archive_dir.mkdir(parents=True, exist_ok=True)  # 创建归档目录（如果不存在）

        # 加载压缩规则
        self.compression_rules = compression_rules or self.DEFAULT_COMPRESSION_RULES.copy()  # 使用默认或自定义规则

        # 初始化锁
        self._lock = threading.RLock()  # 创建可重入锁

        # 任务队列
        self._task_queue: list[CompressionTask] = []  # 初始化任务队列
        self._task_counter = 0  # 任务计数器

        # 压缩处理器映射
        self._compression_handlers: dict[str, Callable] = {  # 压缩处理器字典
            "L5": self._compress_l5_memory,  # L5处理器
            "L2": self._compress_l2_memory,  # L2处理器
            "L3": self._compress_l3_memory  # L3处理器
        }

        # 统计信息
        self._stats = {  # 统计字典
            "total_compressed": 0,  # 总计压缩数
            "total_archived": 0,  # 总计归档数
            "total_cleaned": 0,  # 总计清理数
            "space_saved_bytes": 0  # 节省空间（字节）
        }

        # 日志保留天数配置（默认365天）
        self._max_retention_days = 365  # 最大保留天数

        logger.info("[DataLifecycleManager] 初始化完成")  # 记录日志

    def schedule_compression(self,  # 定义计划压缩方法
                             user_id: str,  # 参数：用户ID
                             layer: str,  # 参数：层级
                             before_date: datetime | None = None  # 参数：压缩日期（可选）
                             ) -> str:  # 返回：任务ID
        """
        计划压缩任务  # 方法文档字符串标题

        Args:  # 参数说明
            user_id: 用户ID  # 参数1
            layer: 记忆层级 (L5, L2, L3)  # 参数2
            before_date: 压缩该日期之前的数据，默认使用规则中的 compress_after  # 参数3

        Returns:  # 返回值说明
            任务ID  # 返回类型
        """  # 方法文档字符串结束
        with self._lock:  # 获取锁
            self._task_counter += 1  # 计数器加1
            task_id = f"compress_{user_id}_{layer}_{self._task_counter}"  # 生成任务ID

            if before_date is None:  # 如果没有指定日期
                # 使用规则计算日期
                rule = self.compression_rules.get(layer, {})  # 获取规则
                compress_after = rule.get("compress_after", 30)  # 获取压缩触发天数（默认30）
                before_date = datetime.now() - timedelta(days=compress_after)  # 计算日期

            task = CompressionTask(  # 创建压缩任务
                task_id=task_id,  # 任务ID
                user_id=user_id,  # 用户ID
                layer=layer,  # 层级
                before_date=before_date  # 日期
            )

            self._task_queue.append(task)  # 添加到任务队列
            logger.info(f"[DataLifecycleManager] 计划压缩任务: {task_id}")  # 记录日志
            return task_id  # 返回任务ID

    def compress_memory(self,  # 定义压缩记忆方法
                        user_id: str,  # 参数：用户ID
                        layer: str,  # 参数：层级
                        before_date: datetime  # 参数：压缩日期
                        ) -> dict:  # 返回：结果字典
        """
        压缩指定日期之前的记忆  # 方法文档字符串标题

        Args:  # 参数说明
            user_id: 用户ID  # 参数1
            layer: 记忆层级  # 参数2
            before_date: 压缩该日期之前的数据  # 参数3

        Returns:  # 返回值说明
            压缩结果统计  # 返回类型
        """  # 方法文档字符串结束
        with self._lock:  # 获取锁
            handler = self._compression_handlers.get(layer, self._compress_default)  # 获取处理器

            try:  # 尝试压缩
                result = handler(user_id, layer, before_date)  # 调用处理器
                self._stats["total_compressed"] += result.get("compressed_count", 0)  # 更新统计
                self._stats["space_saved_bytes"] += result.get("space_saved", 0)  # 更新节省空间
                logger.info(f"[DataLifecycleManager] 压缩完成: {user_id}/{layer}, "
                            f"压缩 {result.get('compressed_count', 0)} 条记录")  # 记录日志
                return result  # 返回结果
            except Exception as e:  # 捕获异常
                logger.error(f"[DataLifecycleManager] 压缩失败: {e}")  # 记录错误
                return {"error": str(e), "compressed_count": 0, "space_saved": 0}  # 返回错误结果

    def archive_cold_data(self,  # 定义归档冷数据方法
                          user_id: str,  # 参数：用户ID
                          layer: str,  # 参数：层级
                          before_date: datetime | None = None  # 参数：归档日期（可选）
                          ) -> dict:  # 返回：结果字典
        """
        归档冷数据到廉价存储  # 方法文档字符串标题

        Args:  # 参数说明
            user_id: 用户ID  # 参数1
            layer: 记忆层级  # 参数2
            before_date: 归档该日期之前的数据  # 参数3

        Returns:  # 返回值说明
            归档结果统计  # 返回类型
        """  # 方法文档字符串结束
        with self._lock:  # 获取锁
            if before_date is None:  # 如果没有指定日期
                rule = self.compression_rules.get(layer, {})  # 获取规则
                archive_after = rule.get("archive_after")  # 获取归档触发天数
                if archive_after:  # 如果配置了归档
                    before_date = datetime.now() - timedelta(days=archive_after)  # 计算日期
                else:  # 如果没有配置
                    return {"archived_count": 0, "message": "该层级未配置归档规则"}  # 返回提示

            try:  # 尝试归档
                result = self._archive_data(user_id, layer, before_date)  # 调用归档方法
                self._stats["total_archived"] += result.get("archived_count", 0)  # 更新统计
                logger.info(f"[DataLifecycleManager] 归档完成: {user_id}/{layer}, "
                            f"归档 {result.get('archived_count', 0)} 条记录")  # 记录日志
                return result  # 返回结果
            except Exception as e:  # 捕获异常
                logger.error(f"[DataLifecycleManager] 归档失败: {e}")  # 记录错误
                return {"error": str(e), "archived_count": 0}  # 返回错误结果

    def cleanup_expired(self,  # 定义清理过期数据方法
                        user_id: str,  # 参数：用户ID
                        layer: str  # 参数：层级
                        ) -> dict:  # 返回：结果字典
        """
        清理过期数据  # 方法文档字符串标题

        Args:  # 参数说明
            user_id: 用户ID  # 参数1
            layer: 记忆层级  # 参数2

        Returns:  # 返回值说明
            清理结果统计  # 返回类型
        """  # 方法文档字符串结束
        with self._lock:  # 获取锁
            rule = self.compression_rules.get(layer, {})  # 获取规则
            keep_days = rule.get("keep_days", 30)  # 获取保留天数（默认30）
            expiry_date = datetime.now() - timedelta(days=keep_days)  # 计算过期日期

            try:  # 尝试清理
                result = self._delete_expired(user_id, layer, expiry_date)  # 调用删除方法
                self._stats["total_cleaned"] += result.get("deleted_count", 0)  # 更新统计
                logger.info(f"[DataLifecycleManager] 清理完成: {user_id}/{layer}, "
                            f"清理 {result.get('deleted_count', 0)} 条记录")  # 记录日志
                return result  # 返回结果
            except Exception as e:  # 捕获异常
                logger.error(f"[DataLifecycleManager] 清理失败: {e}")  # 记录错误
                return {"error": str(e), "deleted_count": 0}  # 返回错误结果

    def cleanup_old_logs(self,  # 定义清理旧日志方法
                         days: int | None = None  # 参数：保留天数（可选）
                         ) -> dict:  # 返回：结果字典
        """
        清理旧日志文件  # 方法文档字符串标题

        Args:  # 参数说明
            days: 保留天数，默认使用初始化时的设置  # 参数

        Returns:  # 返回值说明
            清理结果  # 返回类型
        """  # 方法文档字符串结束
        retention_days = days or self._max_retention_days  # 获取保留天数
        cutoff_date = datetime.now() - timedelta(days=retention_days)  # 计算截止日期

        deleted_count = 0  # 删除计数
        freed_space = 0  # 释放空间

        # 遍历所有用户日志目录
        for user_dir in self._data_dir.iterdir():  # 遍历数据目录
            if not user_dir.is_dir():  # 如果不是目录
                continue  # 跳过

            for log_file in user_dir.rglob("*.json*"):  # 遍历JSON文件
                try:  # 尝试处理
                    # 从文件名或修改时间判断
                    file_date = self._parse_log_file_date(log_file.name)  # 解析日期
                    if file_date is None:  # 如果解析失败
                        # 使用文件修改时间
                        import os  # 导入os模块
                        mtime = os.path.getmtime(log_file)  # 获取修改时间
                        file_date = datetime.fromtimestamp(mtime)  # 转为日期时间

                    if file_date < cutoff_date:  # 如果文件已过期
                        file_size = log_file.stat().st_size  # 获取文件大小
                        log_file.unlink()  # 删除文件
                        deleted_count += 1  # 计数加1
                        freed_space += file_size  # 累加释放空间
                except Exception as e:  # 捕获异常
                    logger.warning(f"[DataLifecycleManager] 清理日志失败 {log_file}: {e}")  # 记录警告

        return {  # 返回结果
            "deleted_files": deleted_count,  # 删除文件数
            "freed_space_bytes": freed_space,  # 释放空间（字节）
            "freed_space_mb": round(freed_space / (1024 * 1024), 2)  # 释放空间（MB）
        }

    def get_storage_stats(self,  # 定义获取存储统计方法
                          user_id: str,  # 参数：用户ID
                          layer: str | None = None  # 参数：层级（可选）
                          ) -> dict:  # 返回：统计字典
        """
        获取存储统计（用于监控）  # 方法文档字符串标题

        Args:  # 参数说明
            user_id: 用户ID  # 参数1
            layer: 记忆层级，为None时返回所有层级统计  # 参数2

        Returns:  # 返回值说明
            存储统计字典  # 返回类型
        """  # 方法文档字符串结束
        with self._lock:  # 获取锁
            if layer:  # 如果指定了层级
                return self._get_layer_stats(user_id, layer).to_dict()  # 返回该层统计

            # 获取所有层级统计
            all_stats = {}  # 初始化统计字典
            total_size = 0  # 总大小
            total_records = 0  # 总记录数

            for layer_name in self.compression_rules:  # 遍历所有层级
                stats = self._get_layer_stats(user_id, layer_name)  # 获取统计
                all_stats[layer_name] = stats.to_dict()  # 添加到字典
                total_size += stats.total_size_bytes  # 累加大小
                total_records += stats.total_records  # 累加记录数

            return {  # 返回汇总统计
                "user_id": user_id,  # 用户ID
                "layers": all_stats,  # 各层统计
                "total_size_bytes": total_size,  # 总大小
                "total_records": total_records,  # 总记录数
                "total_size_mb": round(total_size / (1024 * 1024), 2)  # 总大小（MB）
            }

    def run_scheduled_tasks(self) -> list[dict]:  # 定义执行计划任务方法
        """
        执行所有计划的任务  # 方法文档字符串标题

        Returns:  # 返回值说明
            任务执行结果列表  # 返回类型
        """  # 方法文档字符串结束
        results = []  # 初始化结果列表

        with self._lock:  # 获取锁
            # 复制任务列表并清空原队列
            tasks_to_run = self._task_queue.copy()  # 复制任务列表
            self._task_queue.clear()  # 清空原队列

        for task in tasks_to_run:  # 遍历任务
            try:  # 尝试执行
                task.started_at = datetime.now()  # 设置开始时间
                task.status = "running"  # 设置状态为运行中

                result = self.compress_memory(task.user_id, task.layer, task.before_date)  # 执行压缩

                task.status = "completed"  # 设置状态为完成
                task.completed_at = datetime.now()  # 设置完成时间
                task.result = result  # 保存结果

                results.append({  # 添加结果
                    "task_id": task.task_id,  # 任务ID
                    "status": "completed",  # 状态
                    "result": result  # 结果
                })
            except Exception as e:  # 捕获异常
                task.status = "failed"  # 设置状态为失败
                task.error = str(e)  # 保存错误
                results.append({  # 添加错误结果
                    "task_id": task.task_id,  # 任务ID
                    "status": "failed",  # 状态
                    "error": str(e)  # 错误信息
                })

        return results  # 返回结果列表

    def auto_cleanup_all(self) -> dict:  # 定义自动清理所有方法
        """
        对所有用户和层级执行自动清理  # 方法文档字符串标题

        Returns:  # 返回值说明
            清理结果汇总  # 返回类型
        """  # 方法文档字符串结束
        summary = {  # 初始化汇总字典
            "compressed": {},  # 压缩结果
            "archived": {},  # 归档结果
            "cleaned": {},  # 清理结果
            "total_space_saved_bytes": 0  # 总节省空间
        }

        # 扫描所有用户目录
        user_dirs = [d for d in self._data_dir.iterdir() if d.is_dir()]  # 获取用户目录列表

        for user_dir in user_dirs:  # 遍历用户目录
            user_id = user_dir.name  # 获取用户ID

            for layer in self.compression_rules:  # 遍历所有层级
                # 压缩
                compress_result = self.compress_memory(  # 执行压缩
                    user_id, layer,  # 传入参数
                    datetime.now() - timedelta(  # 计算日期
                        days=self.compression_rules[layer].get("compress_after", 30)  # 获取压缩触发天数
                    )
                )
                summary["compressed"][f"{user_id}_{layer}"] = compress_result  # 保存结果
                summary["total_space_saved_bytes"] += compress_result.get("space_saved", 0)  # 累加节省空间

                # 归档
                archive_result = self.archive_cold_data(user_id, layer)  # 执行归档
                summary["archived"][f"{user_id}_{layer}"] = archive_result  # 保存结果

                # 清理
                cleanup_result = self.cleanup_expired(user_id, layer)  # 执行清理
                summary["cleaned"][f"{user_id}_{layer}"] = cleanup_result  # 保存结果

        return summary  # 返回汇总

    def get_global_stats(self) -> dict:  # 定义获取全局统计方法
        """获取全局统计"""  # 方法文档字符串
        with self._lock:  # 获取锁
            return {  # 返回统计字典
                "total_compressed": self._stats["total_compressed"],  # 总计压缩数
                "total_archived": self._stats["total_archived"],  # 总计归档数
                "total_cleaned": self._stats["total_cleaned"],  # 总计清理数
                "space_saved_mb": round(self._stats["space_saved_bytes"] / (1024 * 1024), 2),  # 节省空间（MB）
                "compression_rules": {  # 压缩规则
                    k: {  # 每层规则
                        "keep_days": v.get("keep_days"),  # 保留天数
                        "compress_after": v.get("compress_after"),  # 压缩触发天数
                        "archive_after": v.get("archive_after")  # 归档触发天数
                    }
                    for k, v in self.compression_rules.items()  # 遍历规则
                }
            }

    # ========== 内部压缩方法 ==========  # 分隔线：内部压缩方法

    def _compress_l5_memory(self,  # 定义压缩L5记忆私有方法
                            user_id: str,  # 参数：用户ID
                            layer: str,  # 参数：层级
                            before_date: datetime  # 参数：日期
                            ) -> dict:  # 返回：结果字典
        """压缩L5层级记忆（短期记忆）"""  # 方法文档字符串
        records = self._load_memory_records(user_id, layer)  # 加载记录
        compressed_count = 0  # 压缩计数
        space_saved = 0  # 节省空间

        for record in records:  # 遍历记录
            if record.get("timestamp") and \
                    datetime.fromisoformat(record["timestamp"]) < before_date and \
                    not record.get("compressed"):  # 如果符合条件
                # L5轻度压缩：保留关键信息，去除冗余
                compressed = self._light_compress(record)  # 轻度压缩
                original_size = len(json.dumps(record, ensure_ascii=False))  # 原始大小
                compressed_size = len(json.dumps(compressed, ensure_ascii=False))  # 压缩后大小

                self._save_compressed_record(user_id, layer, record["id"], compressed)  # 保存
                compressed_count += 1  # 计数加1
                space_saved += (original_size - compressed_size)  # 累加节省空间

        return {  # 返回结果
            "compressed_count": compressed_count,  # 压缩数
            "space_saved": space_saved,  # 节省空间
            "layer": layer  # 层级
        }

    def _compress_l2_memory(self,  # 定义压缩L2记忆私有方法
                            user_id: str,  # 参数：用户ID
                            layer: str,  # 参数：层级
                            before_date: datetime  # 参数：日期
                            ) -> dict:  # 返回：结果字典
        """压缩L2层级记忆（中期记忆）"""  # 方法文档字符串
        records = self._load_memory_records(user_id, layer)  # 加载记录
        compressed_count = 0  # 压缩计数
        space_saved = 0  # 节省空间

        # 按会话分组摘要
        sessions = self._group_by_session(records, before_date)  # 分组

        for _session_id, session_records in sessions.items():  # 遍历会话
            if len(session_records) > 5:  # 只有会话记录足够多才摘要
                summary = self._generate_session_summary(session_records)  # 生成摘要

                # 计算节省的空间
                original_size = sum(  # 原始大小
                    len(json.dumps(r, ensure_ascii=False)) for r in session_records
                )
                summary_size = len(json.dumps(summary, ensure_ascii=False))  # 摘要大小

                # 标记原记录为已归档，保存摘要
                for record in session_records:  # 遍历记录
                    self._mark_archived(user_id, layer, record["id"], summary)  # 标记归档

                compressed_count += len(session_records)  # 累加计数
                space_saved += (original_size - summary_size)  # 累加节省空间

        return {  # 返回结果
            "compressed_count": compressed_count,  # 压缩数
            "space_saved": space_saved,  # 节省空间
            "layer": layer  # 层级
        }

    def _compress_l3_memory(self,  # 定义压缩L3记忆私有方法
                            user_id: str,  # 参数：用户ID
                            layer: str,  # 参数：层级
                            before_date: datetime  # 参数：日期
                            ) -> dict:  # 返回：结果字典
        """压缩L3层级记忆（长期记忆）"""  # 方法文档字符串
        records = self._load_memory_records(user_id, layer)  # 加载记录
        compressed_count = 0  # 压缩计数
        space_saved = 0  # 节省空间

        # 按主题聚类摘要
        topics = self._cluster_by_topic(records, before_date)  # 聚类

        for _topic, topic_records in topics.items():  # 遍历主题
            # 重度压缩：仅保留元数据
            metadata = self._extract_metadata(topic_records)  # 提取元数据

            original_size = sum(  # 原始大小
                len(json.dumps(r, ensure_ascii=False)) for r in topic_records
            )
            metadata_size = len(json.dumps(metadata, ensure_ascii=False))  # 元数据大小

            for record in topic_records:  # 遍历记录
                self._mark_archived(user_id, layer, record["id"], metadata)  # 标记归档

            compressed_count += len(topic_records)  # 累加计数
            space_saved += (original_size - metadata_size)  # 累加节省空间

        return {  # 返回结果
            "compressed_count": compressed_count,  # 压缩数
            "space_saved": space_saved,  # 节省空间
            "layer": layer  # 层级
        }

    def _compress_default(self,  # 定义默认压缩私有方法
                          user_id: str,  # 参数：用户ID
                          layer: str,  # 参数：层级
                          before_date: datetime  # 参数：日期
                          ) -> dict:  # 返回：结果字典
        """默认压缩方法"""  # 方法文档字符串
        return self._compress_l5_memory(user_id, layer, before_date)  # 调用L5压缩

    # ========== 内部归档方法 ==========  # 分隔线：内部归档方法

    def _archive_data(self,  # 定义归档数据私有方法
                      user_id: str,  # 参数：用户ID
                      layer: str,  # 参数：层级
                      before_date: datetime  # 参数：日期
                      ) -> dict:  # 返回：结果字典
        """归档数据"""  # 方法文档字符串
        records = self._load_memory_records(user_id, layer)  # 加载记录
        archived_count = 0  # 归档计数

        user_archive_dir = self._archive_dir / user_id / layer  # 构建归档目录
        user_archive_dir.mkdir(parents=True, exist_ok=True)  # 创建目录

        for record in records:  # 遍历记录
            if record.get("timestamp") and \
                    datetime.fromisoformat(record["timestamp"]) < before_date and \
                    not record.get("archived"):  # 如果符合条件
                # 保存到归档目录
                archive_file = user_archive_dir / f"{record['id']}.json.gz"  # 构建文件路径
                with gzip.open(archive_file, 'wt', encoding='utf-8') as f:  # 打开gzip文件
                    json.dump(record, f, ensure_ascii=False)  # 写入JSON

                # 标记为已归档
                self._mark_archived(user_id, layer, record["id"])  # 标记
                archived_count += 1  # 计数加1

        return {  # 返回结果
            "archived_count": archived_count,  # 归档数
            "archive_location": str(user_archive_dir)  # 归档位置
        }

    def _delete_expired(self,  # 定义删除过期数据私有方法
                        user_id: str,  # 参数：用户ID
                        layer: str,  # 参数：层级
                        expiry_date: datetime  # 参数：过期日期
                        ) -> dict:  # 返回：结果字典
        """删除过期数据"""  # 方法文档字符串
        records = self._load_memory_records(user_id, layer)  # 加载记录
        deleted_count = 0  # 删除计数

        for record in records:  # 遍历记录
            if record.get("timestamp") and \
                    datetime.fromisoformat(record["timestamp"]) < expiry_date:  # 如果已过期
                self._delete_record(user_id, layer, record["id"])  # 删除记录
                deleted_count += 1  # 计数加1

        return {  # 返回结果
            "deleted_count": deleted_count,  # 删除数
            "expiry_date": expiry_date.isoformat()  # 过期日期
        }

    # ========== 辅助方法 ==========  # 分隔线：辅助方法

    def _load_memory_records(self,  # 定义加载记忆记录私有方法
                             user_id: str,  # 参数：用户ID
                             layer: str  # 参数：层级
                             ) -> list[dict]:  # 返回：记录列表
        """加载记忆记录"""  # 方法文档字符串
        user_layer_dir = self._data_dir / user_id / layer  # 构建目录路径
        if not user_layer_dir.exists():  # 如果目录不存在
            return []  # 返回空列表

        records = []  # 初始化记录列表
        for file_path in user_layer_dir.glob("*.json"):  # 遍历JSON文件
            try:  # 尝试加载
                with open(file_path, encoding='utf-8') as f:  # 打开文件
                    record = json.load(f)  # 加载JSON
                    record["id"] = file_path.stem  # 设置ID为文件名
                    records.append(record)  # 添加到列表
            except Exception as e:  # 捕获异常
                logger.warning(f"[DataLifecycleManager] 加载记录失败 {file_path}: {e}")  # 记录警告

        return records  # 返回记录列表

    def _save_compressed_record(self,  # 定义保存压缩记录私有方法
                                user_id: str,  # 参数：用户ID
                                layer: str,  # 参数：层级
                                record_id: str,  # 参数：记录ID
                                data: dict  # 参数：数据
                                ):  # 返回：无
        """保存压缩后的记录"""  # 方法文档字符串
        user_layer_dir = self._data_dir / user_id / layer  # 构建目录路径
        user_layer_dir.mkdir(parents=True, exist_ok=True)  # 创建目录

        file_path = user_layer_dir / f"{record_id}.json"  # 构建文件路径
        data["compressed"] = True  # 标记为已压缩
        data["compressed_at"] = datetime.now().isoformat()  # 设置压缩时间

        with open(file_path, 'w', encoding='utf-8') as f:  # 打开文件
            json.dump(data, f, ensure_ascii=False)  # 写入JSON

    def _mark_archived(self,  # 定义标记归档私有方法
                       user_id: str,  # 参数：用户ID
                       layer: str,  # 参数：层级
                       record_id: str,  # 参数：记录ID
                       summary: dict | None = None  # 参数：摘要（可选）
                       ):  # 返回：无
        """标记记录为已归档"""  # 方法文档字符串
        user_layer_dir = self._data_dir / user_id / layer  # 构建目录路径
        file_path = user_layer_dir / f"{record_id}.json"  # 构建文件路径

        if file_path.exists():  # 如果文件存在
            try:  # 尝试标记
                with open(file_path, encoding='utf-8') as f:  # 打开文件
                    record = json.load(f)  # 加载JSON

                record["archived"] = True  # 标记为已归档
                record["archived_at"] = datetime.now().isoformat()  # 设置归档时间

                if summary:  # 如果有摘要
                    record["summary"] = summary  # 保存摘要

                with open(file_path, 'w', encoding='utf-8') as f:  # 打开文件
                    json.dump(record, f, ensure_ascii=False)  # 写入JSON
            except Exception as e:  # 捕获异常
                logger.warning(f"[DataLifecycleManager] 标记归档失败 {file_path}: {e}")  # 记录警告

    def _delete_record(self,  # 定义删除记录私有方法
                       user_id: str,  # 参数：用户ID
                       layer: str,  # 参数：层级
                       record_id: str  # 参数：记录ID
                       ):  # 返回：无
        """删除记录"""  # 方法文档字符串
        user_layer_dir = self._data_dir / user_id / layer  # 构建目录路径
        file_path = user_layer_dir / f"{record_id}.json"  # 构建文件路径

        if file_path.exists():  # 如果文件存在
            file_path.unlink()  # 删除文件

    def _get_layer_stats(self,  # 定义获取层级统计私有方法
                         user_id: str,  # 参数：用户ID
                         layer: str  # 参数：层级
                         ) -> StorageStats:  # 返回：统计对象
        """获取层级统计"""  # 方法文档字符串
        records = self._load_memory_records(user_id, layer)  # 加载记录

        total_size = 0  # 总大小
        compressed_count = 0  # 压缩计数
        archived_count = 0  # 归档计数
        timestamps = []  # 时间戳列表
        original_sizes = []  # 原始大小列表

        for record in records:  # 遍历记录
            size = len(json.dumps(record, ensure_ascii=False))  # 计算大小
            total_size += size  # 累加大小

            if record.get("compressed"):  # 如果已压缩
                compressed_count += 1  # 计数加1
            if record.get("archived"):  # 如果已归档
                archived_count += 1  # 计数加1

            if record.get("timestamp"):  # 如果有时间戳
                timestamps.append(datetime.fromisoformat(record["timestamp"]))  # 添加时间
            if record.get("original_size"):  # 如果有原始大小
                original_sizes.append(record["original_size"])  # 添加大小

        # 计算压缩率
        compression_ratio = 0.0  # 初始化压缩率
        if original_sizes:  # 如果有原始大小数据
            original_total = sum(original_sizes)  # 计算原始总大小
            if original_total > 0:  # 如果大于0
                compression_ratio = 1 - (total_size / original_total)  # 计算压缩率

        return StorageStats(  # 返回统计对象
            user_id=user_id,  # 用户ID
            layer=layer,  # 层级
            total_records=len(records),  # 总记录数
            total_size_bytes=total_size,  # 总大小
            compressed_records=compressed_count,  # 压缩数
            archived_records=archived_count,  # 归档数
            oldest_record=min(timestamps) if timestamps else None,  # 最早记录
            newest_record=max(timestamps) if timestamps else None,  # 最新记录
            compression_ratio=round(compression_ratio, 4)  # 压缩率
        )

    def _light_compress(self,  # 定义轻度压缩私有方法
                        record: dict  # 参数：记录
                        ) -> dict:  # 返回：压缩后记录
        """轻度压缩：保留关键信息"""  # 方法文档字符串
        return {  # 返回压缩后字典
            "id": record.get("id"),  # ID
            "timestamp": record.get("timestamp"),  # 时间戳
            "type": record.get("type"),  # 类型
            "content_preview": record.get("content", "")[:200] if record.get("content") else "",  # 内容预览（200字）
            "keywords": record.get("keywords", []),  # 关键词
            "importance": record.get("importance", 0),  # 重要性
            "compressed": True  # 标记已压缩
        }

    def _group_by_session(self,  # 定义按会话分组私有方法
                          records: list[dict],  # 参数：记录列表
                          before_date: datetime  # 参数：日期
                          ) -> dict[str, list[dict]]:  # 返回：分组字典
        """按会话分组"""  # 方法文档字符串
        sessions: dict[str, list[dict]] = {}  # 初始化分组字典

        for record in records:  # 遍历记录
            if record.get("timestamp") and \
                    datetime.fromisoformat(record["timestamp"]) < before_date and \
                    not record.get("archived"):  # 如果符合条件
                session_id = record.get("session_id", "default")  # 获取会话ID
                if session_id not in sessions:  # 如果会话不存在
                    sessions[session_id] = []  # 创建列表
                sessions[session_id].append(record)  # 添加到列表

        return sessions  # 返回分组字典

    def _generate_session_summary(self,  # 定义生成会话摘要私有方法
                                  records: list[dict]  # 参数：记录列表
                                  ) -> dict:  # 返回：摘要字典
        """生成会话摘要"""  # 方法文档字符串
        topics = set()  # 主题集合
        key_points = []  # 关键点列表

        for record in records:  # 遍历记录
            if record.get("topic"):  # 如果有主题
                topics.add(record["topic"])  # 添加到集合
            if record.get("key_point"):  # 如果有关键点
                key_points.append(record["key_point"])  # 添加到列表

        return {  # 返回摘要字典
            "type": "session_summary",  # 类型
            "record_count": len(records),  # 记录数
            "topics": list(topics),  # 主题列表
            "key_points": key_points[:10],  # 关键点（最多10个）
            "time_range": {  # 时间范围
                "start": records[0].get("timestamp") if records else None,  # 开始时间
                "end": records[-1].get("timestamp") if records else None  # 结束时间
            }
        }

    def _cluster_by_topic(self,  # 定义按主题聚类私有方法
                          records: list[dict],  # 参数：记录列表
                          before_date: datetime  # 参数：日期
                          ) -> dict[str, list[dict]]:  # 返回：聚类字典
        """按主题聚类"""  # 方法文档字符串
        topics: dict[str, list[dict]] = {}  # 初始化聚类字典

        for record in records:  # 遍历记录
            if record.get("timestamp") and \
                    datetime.fromisoformat(record["timestamp"]) < before_date and \
                    not record.get("archived"):  # 如果符合条件
                topic = record.get("topic", "uncategorized")  # 获取主题（默认未分类）
                if topic not in topics:  # 如果主题不存在
                    topics[topic] = []  # 创建列表
                topics[topic].append(record)  # 添加到列表

        return topics  # 返回聚类字典

    def _extract_metadata(self,  # 定义提取元数据私有方法
                          records: list[dict]  # 参数：记录列表
                          ) -> dict:  # 返回：元数据字典
        """提取元数据"""  # 方法文档字符串
        topics = set()  # 主题集合
        entities = set()  # 实体集合

        for record in records:  # 遍历记录
            if record.get("topic"):  # 如果有主题
                topics.add(record["topic"])  # 添加到集合
            if record.get("entities"):  # 如果有实体
                entities.update(record["entities"])  # 添加到集合

        return {  # 返回元数据字典
            "type": "metadata",  # 类型
            "record_count": len(records),  # 记录数
            "topics": list(topics)[:20],  # 主题（最多20个）
            "entities": list(entities)[:50],  # 实体（最多50个）
            "time_range": {  # 时间范围
                "start": records[0].get("timestamp") if records else None,  # 开始时间
                "end": records[-1].get("timestamp") if records else None  # 结束时间
            }
        }


# 全局实例
_lifecycle_manager: DataLifecycleManager | None = None  # 全局管理器实例
_lifecycle_lock = threading.Lock()  # 全局锁


def get_lifecycle_manager() -> DataLifecycleManager:  # 定义获取生命周期管理器函数
    """获取全局数据生命周期管理器实例（单例）"""  # 函数文档字符串
    global _lifecycle_manager  # 声明全局变量

    if _lifecycle_manager is None:  # 如果实例不存在
        with _lifecycle_lock:  # 获取锁
            if _lifecycle_manager is None:  # 双重检查
                _lifecycle_manager = DataLifecycleManager()  # 创建实例

    return _lifecycle_manager  # 返回实例


def init_lifecycle_manager(data_dir: str | None = None,  # 定义初始化生命周期管理器函数
                           archive_dir: str | None = None,  # 参数：归档目录
                           compression_rules: dict | None = None  # 参数：压缩规则
                           ) -> DataLifecycleManager:  # 返回：管理器实例
    """
    初始化数据生命周期管理器  # 函数文档字符串标题

    Args:  # 参数说明
        data_dir: 数据存储目录  # 参数1
        archive_dir: 归档存储目录  # 参数2
        compression_rules: 自定义压缩规则  # 参数3

    Returns:  # 返回值说明
        DataLifecycleManager 实例  # 返回类型
    """  # 函数文档字符串结束
    global _lifecycle_manager  # 声明全局变量

    with _lifecycle_lock:  # 获取锁
        _lifecycle_manager = DataLifecycleManager(  # 创建实例
            data_dir=data_dir,  # 数据目录
            archive_dir=archive_dir,  # 归档目录
            compression_rules=compression_rules  # 压缩规则
        )

    return _lifecycle_manager  # 返回实例


# =============================================================================
# 总结性注释：文件角色、关联关系与核心效果
# =============================================================================
#
# 【文件角色】
# 本文件（data_lifecycle.py）是 SiliconBase V5 系统的"数据生命周期管理器"核心模块。
# 属于系统的"第十层基础设施"，专门负责管理记忆数据的生命周期，包括压缩、归档和清理。
# 是系统长期运行后保持存储效率的关键组件。
#
# 【核心职责】
# 1. 数据压缩：按计划压缩记忆数据，将详细记录摘要为关键信息
# 2. 数据归档：将冷数据归档到廉价存储（gzip压缩）
# 3. 数据清理：自动清理过期数据，释放存储空间
# 4. 存储统计：提供存储使用统计和监控
# 5. 任务调度：支持计划压缩任务的队列管理
#
# 【核心类说明】
# 1. CompressionLevel(Enum): 压缩级别枚举
#    - LIGHT: 轻度压缩，保留关键信息（适用于L5短期记忆）
#    - MEDIUM: 中度压缩，摘要处理（适用于L2中期记忆）
#    - HEAVY: 重度压缩，仅保留元数据（适用于L3长期记忆）
#
# 2. MemoryLayerConfig(dataclass): 记忆层级配置
#    - layer: 层级名称
#    - keep_days: 保留天数
#    - compress_after: 压缩触发天数
#    - compression_level: 压缩级别
#    - archive_after: 归档触发天数
#    - archive_storage: 归档存储位置
#
# 3. CompressionTask(dataclass): 压缩任务
#    - 任务状态管理：pending -> running -> completed/failed
#    - 支持任务队列和异步执行
#
# 4. StorageStats(dataclass): 存储统计
#    - 记录数、大小、压缩率等统计信息
#    - 支持转换为字典格式
#
# 5. DataLifecycleManager: 数据生命周期管理器（主类）
#    - 默认压缩规则：L5(30天/7天压缩)、L2(90天/30天压缩/60天归档)、L3(365天/90天压缩/180天归档)
#    - 压缩处理器映射：L5/L2/L3各自的处理方法
#    - 线程安全：使用RLock保护共享数据
#
# 【压缩策略】
# L5（短期记忆）- 轻度压缩：
#   - 保留：id, timestamp, type, content_preview(200字), keywords, importance
#   - 去除：完整内容、详细元数据
#
# L2（中期记忆）- 中度压缩：
#   - 按会话分组摘要
#   - 生成：topics列表、key_points列表、time_range
#   - 标记原记录为已归档
#
# L3（长期记忆）- 重度压缩：
#   - 按主题聚类
#   - 仅保留：topics(最多20个)、entities(最多50个)、record_count、time_range
#
# 【关联文件】
# 1. core/memory.py                - 记忆系统
#    * 关系：数据来源
#    * 交互：读取记忆记录进行压缩/归档/清理
#
# 2. core/logger.py                - 日志系统
#    * 关系：记录操作日志
#    * 交互：logger.info/debug/error/warning
#
# 3. 其他使用日志的模块            - 日志清理
#    * 关系：cleanup_old_logs()清理旧日志文件
#    * 交互：遍历日志目录，删除过期文件
#
# 【使用场景】
# - 系统运行一段时间后，存储空间不足时执行压缩
# - 定期执行自动清理任务，保持存储健康
# - 监控存储使用情况，预测存储需求
# - 长期任务完成后归档相关数据
#
# 【达到的效果】
# 1. 存储优化：通过压缩和归档减少存储占用
# 2. 自动管理：按计划自动执行压缩和清理
# 3. 分级处理：不同层级采用不同的压缩策略
# 4. 数据安全：归档使用gzip压缩，保留原始数据
# 5. 可监控：提供详细的存储统计信息
# 6. 可配置：支持自定义压缩规则和保留策略
#
# =============================================================================
