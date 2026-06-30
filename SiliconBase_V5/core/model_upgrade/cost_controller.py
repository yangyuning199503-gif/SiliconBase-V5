#!/usr/bin/env python3
"""
成本控制器 - Cost Controller

实现API调用成本监控、预算管理和成本优化策略。

特性：
1. 实时成本追踪
2. 预算限制和告警
3. 成本优化建议
4. 多层级成本控制
5. 成本报告生成
"""

import json
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

from core.logger import logger


class CostAlertLevel(Enum):
    """成本告警级别"""
    INFO = "info"         # 信息提示
    WARNING = "warning"   # 警告
    CRITICAL = "critical" # 严重告警


@dataclass
class CostAlert:
    """成本告警"""
    level: CostAlertLevel
    message: str
    current_cost: float
    limit: float
    percentage: float
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class BudgetLimit:
    """预算限制配置"""
    daily: float = 10.0      # 日预算（美元）
    weekly: float = 50.0     # 周预算（美元）
    monthly: float = 200.0   # 月预算（美元）
    per_request: float = 0.1 # 单次请求上限（美元）

    # 告警阈值（百分比）
    warning_threshold: float = 80.0
    critical_threshold: float = 95.0


@dataclass
class CostRecord:
    """成本记录"""
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost: float
    task_type: str
    timestamp: datetime = field(default_factory=datetime.now)
    request_id: str | None = None
    user_id: str | None = None


class CostController:
    """
    成本控制器

    管理AI API调用的成本和预算。
    """

    # 模型定价（美元/1K tokens）- 2024年参考价格
    PRICING = {
        # OpenAI
        "openai/gpt-4": {"input": 0.03, "output": 0.06},
        "openai/gpt-4o": {"input": 0.005, "output": 0.015},
        "openai/gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
        "openai/o1-preview": {"input": 0.015, "output": 0.06},
        "openai/o1-mini": {"input": 0.003, "output": 0.012},

        # Anthropic
        "anthropic/claude-3-opus": {"input": 0.015, "output": 0.075},
        "anthropic/claude-3-sonnet": {"input": 0.003, "output": 0.015},
        "anthropic/claude-3-haiku": {"input": 0.00025, "output": 0.00125},

        # DeepSeek
        "deepseek/deepseek-chat": {"input": 0.00014, "output": 0.00028},
        "deepseek/deepseek-reasoner": {"input": 0.00055, "output": 0.00219},

        # 本地模型（免费）
        "ollama/qwen3:8b": {"input": 0.0, "output": 0.0},
        "ollama/llama3.2:3b": {"input": 0.0, "output": 0.0},
        "ollama/llama3.2-vision:11b": {"input": 0.0, "output": 0.0},
        "ollama/deepseek-coder:6.7b": {"input": 0.0, "output": 0.0},
        "ollama/phi4:14b": {"input": 0.0, "output": 0.0},
    }

    def __init__(self, budget: BudgetLimit | None = None, data_dir: str = "data/cost"):
        self.budget = budget or BudgetLimit()
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 成本记录
        self._records: list[CostRecord] = []
        self._records_lock = threading.Lock()

        # 成本统计缓存
        self._stats_cache: dict[str, dict] = {}
        self._cache_timestamp: datetime | None = None
        self._cache_ttl = 60  # 缓存60秒

        # 告警回调
        self._alert_callbacks: list[Callable[[CostAlert], None]] = []

        # 加载历史记录
        self._load_records()

        logger.info(f"[CostController] 初始化完成，数据目录: {self.data_dir}")

    def calculate_cost(self,
                      model: str,
                      provider: str,
                      input_tokens: int,
                      output_tokens: int) -> float:
        """
        计算API调用成本

        Args:
            model: 模型名称
            provider: 提供商
            input_tokens: 输入token数
            output_tokens: 输出token数

        Returns:
            float: 预估成本（美元）
        """
        full_name = f"{provider}/{model}"
        pricing = self.PRICING.get(full_name, {"input": 0.01, "output": 0.03})

        input_cost = (input_tokens / 1000) * pricing["input"]
        output_cost = (output_tokens / 1000) * pricing["output"]

        return round(input_cost + output_cost, 6)

    def record_cost(self, record: CostRecord) -> CostAlert | None:
        """
        记录成本并检查预算

        Args:
            record: 成本记录

        Returns:
            Optional[CostAlert]: 如果有告警则返回
        """
        with self._records_lock:
            self._records.append(record)

            # 限制内存中的记录数量
            if len(self._records) > 10000:
                self._records = self._records[-5000:]

        # 检查预算
        alert = self._check_budget(record)
        if alert:
            self._trigger_alert(alert)

        # 定期保存到文件
        if len(self._records) % 100 == 0:
            self._save_records()

        return alert

    def _check_budget(self, record: CostRecord) -> CostAlert | None:
        """检查预算限制"""
        now = datetime.now()

        # 检查单次请求限制
        if record.cost > self.budget.per_request:
            return CostAlert(
                level=CostAlertLevel.WARNING,
                message=f"单次请求成本 ${record.cost:.4f} 超过限制 ${self.budget.per_request:.4f}",
                current_cost=record.cost,
                limit=self.budget.per_request,
                percentage=(record.cost / self.budget.per_request) * 100
            )

        # 计算今日成本
        today_cost = self.get_daily_cost(now)

        # 检查日预算
        if today_cost >= self.budget.daily * (self.budget.critical_threshold / 100):
            return CostAlert(
                level=CostAlertLevel.CRITICAL,
                message=f"今日成本 ${today_cost:.4f} 已达日预算 ${self.budget.daily:.4f} 的 {self.budget.critical_threshold}%",
                current_cost=today_cost,
                limit=self.budget.daily,
                percentage=(today_cost / self.budget.daily) * 100
            )
        elif today_cost >= self.budget.daily * (self.budget.warning_threshold / 100):
            return CostAlert(
                level=CostAlertLevel.WARNING,
                message=f"今日成本 ${today_cost:.4f} 已达日预算 ${self.budget.daily:.4f} 的 {self.budget.warning_threshold}%",
                current_cost=today_cost,
                limit=self.budget.daily,
                percentage=(today_cost / self.budget.daily) * 100
            )

        # 检查月预算
        monthly_cost = self.get_monthly_cost(now)
        if monthly_cost >= self.budget.monthly * (self.budget.critical_threshold / 100):
            return CostAlert(
                level=CostAlertLevel.CRITICAL,
                message=f"本月成本 ${monthly_cost:.4f} 已达月预算 ${self.budget.monthly:.4f} 的 {self.budget.critical_threshold}%",
                current_cost=monthly_cost,
                limit=self.budget.monthly,
                percentage=(monthly_cost / self.budget.monthly) * 100
            )

        return None

    def _trigger_alert(self, alert: CostAlert):
        """触发告警"""
        logger.warning(f"[CostController] 成本告警 [{alert.level.value}]: {alert.message}")

        for callback in self._alert_callbacks:
            try:
                callback(alert)
            except Exception as e:
                logger.error(f"[CostController] 告警回调出错: {e}")

    def add_alert_callback(self, callback: Callable[[CostAlert], None]):
        """添加告警回调"""
        self._alert_callbacks.append(callback)

    def remove_alert_callback(self, callback: Callable[[CostAlert], None]):
        """移除告警回调"""
        if callback in self._alert_callbacks:
            self._alert_callbacks.remove(callback)

    def get_daily_cost(self, date: datetime | None = None) -> float:
        """获取指定日期的成本"""
        date = date or datetime.now()
        date_str = date.strftime("%Y-%m-%d")

        with self._records_lock:
            return sum(
                r.cost for r in self._records
                if r.timestamp.strftime("%Y-%m-%d") == date_str
            )

    def get_monthly_cost(self, date: datetime | None = None) -> float:
        """获取指定月份的成本"""
        date = date or datetime.now()
        month_str = date.strftime("%Y-%m")

        with self._records_lock:
            return sum(
                r.cost for r in self._records
                if r.timestamp.strftime("%Y-%m") == month_str
            )

    def get_cost_by_provider(self,
                            days: int = 30) -> dict[str, float]:
        """按提供商统计成本"""
        cutoff = datetime.now() - timedelta(days=days)

        with self._records_lock:
            costs = {}
            for record in self._records:
                if record.timestamp >= cutoff:
                    costs[record.provider] = costs.get(record.provider, 0) + record.cost
            return costs

    def get_cost_by_model(self,
                         days: int = 30) -> dict[str, float]:
        """按模型统计成本"""
        cutoff = datetime.now() - timedelta(days=days)

        with self._records_lock:
            costs = {}
            for record in self._records:
                if record.timestamp >= cutoff:
                    key = f"{record.provider}/{record.model}"
                    costs[key] = costs.get(key, 0) + record.cost
            return costs

    def get_cost_trend(self, days: int = 7) -> list[dict[str, Any]]:
        """获取成本趋势"""
        result = []
        today = datetime.now().date()

        for i in range(days - 1, -1, -1):
            date = today - timedelta(days=i)
            date_dt = datetime.combine(date, datetime.min.time())
            cost = self.get_daily_cost(date_dt)
            result.append({
                "date": date.isoformat(),
                "cost": round(cost, 4)
            })

        return result

    def can_make_request(self, estimated_cost: float = 0.01) -> tuple[bool, str]:
        """
        检查是否可以发起请求

        Args:
            estimated_cost: 预估成本

        Returns:
            (是否可以请求, 原因)
        """
        now = datetime.now()

        # 检查日预算
        today_cost = self.get_daily_cost(now)
        if today_cost + estimated_cost > self.budget.daily:
            return False, f"日预算不足: 已用 ${today_cost:.4f} / ${self.budget.daily:.4f}"

        # 检查月预算
        monthly_cost = self.get_monthly_cost(now)
        if monthly_cost + estimated_cost > self.budget.monthly:
            return False, f"月预算不足: 已用 ${monthly_cost:.4f} / ${self.budget.monthly:.4f}"

        return True, "预算充足"

    def get_optimization_suggestions(self) -> list[dict[str, Any]]:
        """获取成本优化建议"""
        suggestions = []

        # 分析最近7天的成本
        costs = self.get_cost_by_model(days=7)
        total_cost = sum(costs.values())

        if total_cost == 0:
            return suggestions

        # 找出高成本模型
        for model, cost in sorted(costs.items(), key=lambda x: -x[1])[:3]:
            percentage = (cost / total_cost) * 100
            if percentage > 50:
                suggestions.append({
                    "type": "high_cost_model",
                    "priority": "high",
                    "message": f"模型 {model} 占成本的 {percentage:.1f}%，考虑使用更便宜的替代模型",
                    "current_cost": cost,
                    "savings_potential": cost * 0.5  # 预估可节省50%
                })

        # 检查本地模型使用率
        local_cost = costs.get("ollama", 0)
        local_percentage = (local_cost / total_cost) * 100 if total_cost > 0 else 0

        if local_percentage < 30:
            suggestions.append({
                "type": "increase_local_usage",
                "priority": "medium",
                "message": f"本地模型使用率仅 {local_percentage:.1f}%，增加本地模型使用可降低成本",
                "current_local_usage": local_percentage,
                "target_usage": 60.0
            })

        # 检查日预算使用情况
        today_cost = self.get_daily_cost()
        daily_usage = (today_cost / self.budget.daily) * 100

        if daily_usage > 80:
            suggestions.append({
                "type": "budget_warning",
                "priority": "high",
                "message": f"今日预算已使用 {daily_usage:.1f}%，建议降低请求频率或切换到本地模型",
                "current_usage": daily_usage
            })

        return suggestions

    def generate_report(self, days: int = 30) -> dict[str, Any]:
        """生成成本报告"""
        return {
            "period_days": days,
            "generated_at": datetime.now().isoformat(),
            "budget": asdict(self.budget),
            "summary": {
                "total_cost": sum(self.get_cost_by_model(days=days).values()),
                "daily_average": self.get_daily_cost() / days if days > 0 else 0,
                "monthly_projection": self.get_daily_cost() * 30,
            },
            "by_provider": self.get_cost_by_provider(days=days),
            "by_model": self.get_cost_by_model(days=days),
            "trend": self.get_cost_trend(days=min(days, 7)),
            "suggestions": self.get_optimization_suggestions()
        }

    def _load_records(self):
        """加载历史记录"""
        record_file = self.data_dir / "cost_records.json"
        if record_file.exists():
            try:
                with open(record_file, encoding="utf-8") as f:
                    data = json.load(f)
                    self._records = [
                        CostRecord(
                            provider=r["provider"],
                            model=r["model"],
                            input_tokens=r["input_tokens"],
                            output_tokens=r["output_tokens"],
                            cost=r["cost"],
                            task_type=r["task_type"],
                            timestamp=datetime.fromisoformat(r["timestamp"]),
                            request_id=r.get("request_id"),
                            user_id=r.get("user_id")
                        )
                        for r in data[-5000:]  # 只加载最近5000条
                    ]
                logger.info(f"[CostController] 加载了 {len(self._records)} 条成本记录")
            except Exception as e:
                logger.error(f"[CostController] 加载记录失败: {e}")
                self._records = []

    def _save_records(self):
        """保存记录到文件"""
        record_file = self.data_dir / "cost_records.json"
        try:
            with self._records_lock:
                data = [
                    {
                        "provider": r.provider,
                        "model": r.model,
                        "input_tokens": r.input_tokens,
                        "output_tokens": r.output_tokens,
                        "cost": r.cost,
                        "task_type": r.task_type,
                        "timestamp": r.timestamp.isoformat(),
                        "request_id": r.request_id,
                        "user_id": r.user_id
                    }
                    for r in self._records[-5000:]  # 只保存最近5000条
                ]

            with open(record_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"[CostController] 保存记录失败: {e}")

    def export_report(self, filepath: str, days: int = 30):
        """导出报告到文件"""
        report = self.generate_report(days)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info(f"[CostController] 报告已导出: {filepath}")
