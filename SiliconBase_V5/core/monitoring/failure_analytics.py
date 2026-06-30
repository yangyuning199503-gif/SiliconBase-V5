#!/usr/bin/env python3
"""
失败分析仪表盘 - SiliconBase V5
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
功能：
  ✓ 统计失败模式分布
  ✓ 按提示词版本对比失败率
  ✓ 识别高风险任务类型
  ✓ 提供优化建议

Author: SiliconBase Team
"""

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from core.logger import logger


@dataclass
class FailurePattern:
    """失败模式记录"""
    id: str
    task_type: str
    task_name: str
    root_cause: str  # 1=提示词, 2=工具选择, 3=参数错误, 4=缺少技能, 5=其他
    confidence: float
    explanation: str
    prompt_version: str
    timestamp: datetime
    suggested_fix: str | None = None
    prompt_patch: str | None = None


class FailureAnalytics:
    """
    失败分析器

    职责：
    1. 收集和存储失败模式
    2. 生成统计分析报告
    3. 识别高风险模式
    4. 提供优化建议
    """

    # 根因代码映射
    ROOT_CAUSE_MAP = {
        "1": ("提示词描述不清", "提示词需要更清晰描述任务要求"),
        "2": ("工具选择错误", "AI选择了不合适的工具"),
        "3": ("参数配置错误", "工具参数填写有误"),
        "4": ("缺少必要技能", "没有合适的工具完成任务"),
        "5": ("环境/外部因素", "系统或外部问题"),
    }

    def __init__(self, db_connection=None):
        """初始化失败分析器"""
        self.db = db_connection
        self._patterns: list[FailurePattern] = []
        self._load_recent_patterns()

    def _load_recent_patterns(self, days: int = 7):
        """加载最近N天的失败模式"""
        # TODO: 从PostgreSQL加载
        # 现在使用内存存储，后续迁移到数据库
        pass

    def record_failure(self,
                       task_type: str,
                       task_name: str,
                       root_cause: str,
                       confidence: float,
                       explanation: str,
                       prompt_version: str,
                       suggested_fix: str = None,
                       prompt_patch: str = None) -> str:
        """
        记录一次失败

        Returns:
            失败记录ID
        """
        pattern = FailurePattern(
            id=f"fail_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self._patterns)}",
            task_type=task_type,
            task_name=task_name,
            root_cause=root_cause,
            confidence=confidence,
            explanation=explanation,
            prompt_version=prompt_version,
            timestamp=datetime.now(),
            suggested_fix=suggested_fix,
            prompt_patch=prompt_patch
        )

        self._patterns.append(pattern)

        # 记录到日志
        cause_name, _ = self.ROOT_CAUSE_MAP.get(root_cause, ("未知", ""))
        logger.info(
            f"[FailureAnalytics] 记录失败: {task_name} | "
            f"根因: {cause_name} (置信度{confidence:.2f}) | "
            f"版本: {prompt_version}"
        )

        # 检查是否需要告警
        self._check_alert_threshold(pattern)

        return pattern.id

    def _check_alert_threshold(self, pattern: FailurePattern):
        """检查是否需要触发告警"""
        # 高风险条件：置信度>0.8 + 根因严重
        if pattern.confidence > 0.8 and pattern.root_cause in ["1", "4"]:
            cause_name, _ = self.ROOT_CAUSE_MAP.get(pattern.root_cause)
            logger.warning(
                f"[FailureAnalytics] ⚠️ 高风险失败告警!\n"
                f"  任务: {pattern.task_name}\n"
                f"  根因: {cause_name}\n"
                f"  建议: {pattern.suggested_fix or '无'}"
            )
            # TODO: 发送到Telegram/Discord

    def get_stats(self, days: int = 7) -> dict[str, Any]:
        """
        获取失败统计报告

        Args:
            days: 统计最近N天

        Returns:
            统计报告字典
        """
        cutoff = datetime.now() - timedelta(days=days)
        recent = [p for p in self._patterns if p.timestamp > cutoff]

        if not recent:
            return {"message": f"最近{days}天无失败记录"}

        # 按根因统计
        by_cause = defaultdict(lambda: {"count": 0, "examples": []})
        for p in recent:
            cause_name, _ = self.ROOT_CAUSE_MAP.get(p.root_cause, ("未知", ""))
            by_cause[cause_name]["count"] += 1
            if len(by_cause[cause_name]["examples"]) < 3:
                example = {
                    "task": p.task_name,
                    "explanation": p.explanation[:100] + "..." if len(p.explanation) > 100 else p.explanation
                }
                if p.prompt_patch:
                    example["patch"] = p.prompt_patch
                if p.suggested_fix:
                    example["suggested_fix"] = p.suggested_fix
                by_cause[cause_name]["examples"].append(example)

        # 按提示词版本统计
        by_version = defaultdict(lambda: {"total": 0, "failures": 0})
        for p in recent:
            by_version[p.prompt_version]["failures"] += 1

        # 按任务类型统计
        by_task_type = defaultdict(int)
        for p in recent:
            by_task_type[p.task_type] += 1

        # 计算失败率最高的任务
        top_failing_tasks = sorted(
            [(task, count) for task, count in by_task_type.items()],
            key=lambda x: x[1],
            reverse=True
        )[:10]

        return {
            "period_days": days,
            "total_failures": len(recent),
            "by_cause": dict(by_cause),
            "by_version": dict(by_version),
            "top_failing_tasks": top_failing_tasks,
            "generated_at": datetime.now().isoformat()
        }

    def generate_daily_report(self) -> str:
        """生成每日失败分析报告（Markdown格式）"""
        stats = self.get_stats(days=1)

        if "message" in stats:
            return f"# 每日失败分析报告\n\n{stats['message']}"

        report = f"""# 📊 每日失败分析报告

> 统计时间: {stats['generated_at']}
> 统计周期: 最近24小时
> 总失败数: {stats['total_failures']}

---

## 🔍 失败根因分布

"""

        # 按根因排序
        sorted_causes = sorted(
            stats['by_cause'].items(),
            key=lambda x: x[1]['count'],
            reverse=True
        )

        for cause_name, data in sorted_causes:
            report += f"### {cause_name}: {data['count']}次\n\n"
            if data['examples']:
                report += "**典型案例:**\n"
                for ex in data['examples']:
                    report += f"- `{ex['task']}`: {ex['explanation']}\n"
            report += "\n"

        report += "---\n\n## 📈 按提示词版本统计\n\n"
        for version, data in stats['by_version'].items():
            report += f"- **{version}**: {data['failures']}次失败\n"

        report += """

---

## 🎯 失败最多的任务类型

"""
        for task, count in stats['top_failing_tasks']:
            report += f"- {task}: {count}次\n"

        report += """

---

## 💡 优化建议

基于今日失败模式，建议：

"""

        # 根据最高频的根因给出建议
        if sorted_causes:
            top_cause = sorted_causes[0][0]
            if "提示词" in top_cause:
                report += "1. **提示词优化**: 提示词描述不清是最主要问题，建议检查最近修改的提示词模块\n"
            elif "工具" in top_cause:
                report += "1. **工具选择**: AI经常选错工具，建议在提示词中更明确描述工具用途\n"
            elif "参数" in top_cause:
                report += "1. **参数规范**: 参数错误频发，建议为常用工具添加参数示例\n"
            elif "技能" in top_cause:
                report += "1. **技能扩展**: 缺少必要技能，建议为高频失败任务开发新工具\n"

        report += "\n---\n\n*报告由 FailureAnalytics 自动生成*"

        return report

    def export_to_json(self, filepath: str, days: int = 7):
        """导出统计报告到JSON文件"""
        stats = self.get_stats(days=days)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
        logger.info(f"[FailureAnalytics] 报告已导出: {filepath}")


# 全局实例
failure_analytics = FailureAnalytics()


# 便捷函数
def record_failure(task_type: str, task_name: str, root_cause: str,
                   confidence: float, explanation: str, **kwargs) -> str:
    """记录失败的便捷函数"""
    return failure_analytics.record_failure(
        task_type=task_type,
        task_name=task_name,
        root_cause=root_cause,
        confidence=confidence,
        explanation=explanation,
        **kwargs
    )


def get_failure_stats(days: int = 7) -> dict[str, Any]:
    """获取失败统计的便捷函数"""
    return failure_analytics.get_stats(days=days)


def generate_daily_report() -> str:
    """生成每日报告的便捷函数"""
    return failure_analytics.generate_daily_report()
