#!/usr/bin/env python3
"""
每周实验报告自动生成器 - Agent-5: 权重验证实验师

功能：
1. 每周一早上9点自动生成模板效果对比报告
2. 将报告保存到本地并可选发送通知
3. 提供手动触发接口
4. 保留最近12周的报告历史

使用APScheduler进行定时调度
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    APSCHEDULER_AVAILABLE = True
except ImportError:
    APSCHEDULER_AVAILABLE = False

from core.logger import logger

# 尝试导入template_experiment
try:
    from core.template_experiment import WeeklyReport, template_experiment
    TEMPLATE_EXPERIMENT_AVAILABLE = True
except ImportError:
    TEMPLATE_EXPERIMENT_AVAILABLE = False
    logger.warning("[WeeklyReportScheduler] template_experiment模块不可用")


class WeeklyReportScheduler:
    """
    每周实验报告生成调度器

    自动每周生成模板效果对比报告
    """

    def __init__(self):
        self.scheduler: Any | None = None
        self._initialized = False
        self._job_id = "weekly_template_report"

        if not APSCHEDULER_AVAILABLE:
            logger.warning("[WeeklyReportScheduler] APScheduler不可用，定时功能将禁用")
            return

        if not TEMPLATE_EXPERIMENT_AVAILABLE:
            logger.warning("[WeeklyReportScheduler] template_experiment不可用，报告生成将禁用")
            return

        self.scheduler = AsyncIOScheduler()
        self._initialized = True
        logger.info("[WeeklyReportScheduler] 调度器已初始化")

    def start(self):
        """启动调度器"""
        if not self._initialized or self.scheduler is None:
            logger.warning("[WeeklyReportScheduler] 调度器未初始化，无法启动")
            return

        try:
            # 添加每周一早上9点执行的定时任务
            self.scheduler.add_job(
                self._generate_weekly_report,
                trigger=CronTrigger(
                    day_of_week="mon",
                    hour=9,
                    minute=0,
                    second=0
                ),
                id=self._job_id,
                name="Generate Weekly Template Experiment Report",
                replace_existing=True,
                misfire_grace_time=3600  # 1小时的容错时间
            )

            self.scheduler.start()
            logger.info("[WeeklyReportScheduler] 调度器已启动，每周一9:00生成报告")

        except Exception as e:
            logger.error(f"[WeeklyReportScheduler] 启动调度器失败: {e}")

    def stop(self):
        """停止调度器"""
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("[WeeklyReportScheduler] 调度器已停止")

    async def _generate_weekly_report(self):
        """生成周报告的异步任务"""
        try:
            logger.info("[WeeklyReportScheduler] 开始生成周报告...")

            report = template_experiment.generate_weekly_report()

            # 记录报告摘要
            logger.info(
                f"[WeeklyReportScheduler] 周报告生成完成: "
                f"周期={report.week_start}~{report.week_end}, "
                f"获胜模板={report.winner_template}, "
                f"建议数={len(report.recommendations)}"
            )

            # 可选：发送通知（如WebSocket、邮件等）
            await self._send_notification(report)

        except Exception as e:
            logger.error(f"[WeeklyReportScheduler] 生成周报告失败: {e}")

    async def _send_notification(self, report: WeeklyReport):
        """
        发送报告通知

        可扩展为发送邮件、WebSocket通知等
        """
        try:
            # 这里可以添加通知逻辑
            # 例如：发送到系统消息中心、邮件通知等
            notification = {
                "type": "weekly_report_generated",
                "title": f"模板实验周报告 ({report.week_start} ~ {report.week_end})",
                "message": f"本周最佳模板: {report.winner_template or '无'}",
                "data": report.to_dict(),
                "timestamp": datetime.now().isoformat(),
            }

            # 保存到通知文件（可被系统读取）
            import aiofiles
            notification_dir = Path("data/notifications")
            await asyncio.to_thread(notification_dir.mkdir, True, True)

            notification_file = notification_dir / f"report_{report.week_start}.json"
            async with aiofiles.open(notification_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(notification, ensure_ascii=False, indent=2))

            logger.debug(f"[WeeklyReportScheduler] 通知已保存: {notification_file}")

        except Exception as e:
            logger.warning(f"[WeeklyReportScheduler] 发送通知失败: {e}")

    def generate_now(self) -> WeeklyReport | None:
        """
        立即手动生成报告

        Returns:
            生成的报告，如果失败则返回None
        """
        if not TEMPLATE_EXPERIMENT_AVAILABLE:
            logger.warning("[WeeklyReportScheduler] template_experiment不可用")
            return None

        try:
            report = template_experiment.generate_weekly_report()
            logger.info("[WeeklyReportScheduler] 手动生成报告完成")
            return report
        except Exception as e:
            logger.error(f"[WeeklyReportScheduler] 手动生成报告失败: {e}")
            return None

    async def generate_now_async(self) -> WeeklyReport | None:
        """异步方式立即生成报告"""
        return self.generate_now()

    def get_next_run_time(self) -> datetime | None:
        """获取下次运行时间"""
        if not self.scheduler or not self._initialized:
            return None

        try:
            job = self.scheduler.get_job(self._job_id)
            if job:
                return job.next_run_time
        except Exception as e:
            logger.warning(f"[WeeklyReportScheduler] 获取下次运行时间失败: {e}")

        return None

    def get_scheduler_status(self) -> dict[str, Any]:
        """获取调度器状态"""
        return {
            "initialized": self._initialized,
            "running": self.scheduler.running if self.scheduler else False,
            "apscheduler_available": APSCHEDULER_AVAILABLE,
            "template_experiment_available": TEMPLATE_EXPERIMENT_AVAILABLE,
            "next_run_time": self.get_next_run_time().isoformat() if self.get_next_run_time() else None,
        }


# =============================================================================
# 全局实例
# =============================================================================

# 创建全局单例
weekly_report_scheduler = WeeklyReportScheduler()


# =============================================================================
# 便捷函数
# =============================================================================

def start_weekly_report_scheduler():
    """启动周报告调度器"""
    weekly_report_scheduler.start()


def stop_weekly_report_scheduler():
    """停止周报告调度器"""
    weekly_report_scheduler.stop()


def generate_report_now() -> WeeklyReport | None:
    """立即生成报告"""
    return weekly_report_scheduler.generate_now()


def get_scheduler_status() -> dict[str, Any]:
    """获取调度器状态"""
    return weekly_report_scheduler.get_scheduler_status()


# =============================================================================
# 启动钩子 - 供系统启动时调用
# =============================================================================

def init_weekly_report_scheduler():
    """
    初始化周报告调度器

    在系统启动时调用，启动定时任务
    """
    if APSCHEDULER_AVAILABLE and TEMPLATE_EXPERIMENT_AVAILABLE:
        start_weekly_report_scheduler()
        logger.info("[WeeklyReportScheduler] 周报告定时任务已启动")
    else:
        logger.warning("[WeeklyReportScheduler] 依赖缺失，定时任务未启动")


# =============================================================================
# 总结性注释
# =============================================================================
#
# 【文件角色】
# 本文件是 SiliconBase V5 系统中 Agent-5（权重验证实验师）的定时任务组件，
# 负责每周自动生成模板效果对比报告。
#
# 【核心职责】
# 1. 定时调度：每周一早上9点自动生成报告
# 2. 手动触发：提供手动生成报告的接口
# 3. 通知推送：将报告生成通知发送到系统
# 4. 状态监控：提供调度器状态查询
#
# 【依赖要求】
# - APScheduler: 定时任务调度
# - template_experiment: 报告生成功能
#
# 【使用方式】
# 1. 自动启动：系统启动时调用 init_weekly_report_scheduler()
# 2. 手动生成：调用 generate_report_now()
# 3. 状态查询：调用 get_scheduler_status()
#
# 【关联文件】
# 1. core/template_experiment.py - 报告生成核心
#    * 关系：调用该模块的generate_weekly_report方法
#
# 2. api/template_experiment_api.py - API接口
#    * 关系：API调用本模块的generate_now方法
#
