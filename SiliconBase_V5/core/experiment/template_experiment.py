#!/usr/bin/env python3
"""
模板效果A/B测试框架 - Agent-5: 权重验证实验师

功能：
1. 管理5个模板的A/B测试（guardian/explorer/geek/artist/balanced）
2. 追踪任务成功率、用户满意度、记忆利用率、反思质量
3. 自动推荐最优模板组合
4. 生成每周实验报告
5. 提供Dashboard数据支持

数据隐私合规：
- 所有用户数据匿名化处理
- 仅收集任务执行统计，不收集敏感内容
- 数据本地存储，支持导出删除
"""

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

from core.logger import logger


class TemplateType(Enum):
    """模板类型枚举"""
    GUARDIAN = "guardian"      # 守护者：安全稳定导向
    EXPLORER = "explorer"      # 探索者：创新好奇导向
    GEEK = "geek"              # 极客：技术效率导向
    ARTIST = "artist"          # 艺术家：创意美学导向
    BALANCED = "balanced"      # 均衡者：平衡全面导向


class ExperimentMetric(Enum):
    """实验指标枚举"""
    TASK_SUCCESS_RATE = "task_success_rate"      # 任务成功率
    USER_SATISFACTION = "user_satisfaction"      # 用户满意度
    MEMORY_UTILIZATION = "memory_utilization"    # 记忆利用率
    REFLECTION_QUALITY = "reflection_quality"    # 反思质量
    EXECUTION_SPEED = "execution_speed"          # 执行速度
    TOOL_ACCURACY = "tool_accuracy"              # 工具调用准确率


@dataclass
class TaskResult:
    """任务执行结果记录"""
    task_id: str
    template_name: str
    success: bool
    user_rating: int = 0                      # 1-5星评分
    user_feedback: str = ""                   # 简短文字反馈
    execution_time_ms: int = 0                # 执行耗时（毫秒）
    steps_count: int = 0                      # 执行步骤数
    tool_calls_count: int = 0                 # 工具调用次数
    reflection_depth: int = 0                 # 反思深度（1-3）
    memory_hits: int = 0                      # 记忆命中次数
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TemplateStats:
    """模板统计数据"""
    template_name: str
    total_tasks: int = 0
    successful_tasks: int = 0
    total_rating: int = 0
    rating_count: int = 0
    total_execution_time_ms: int = 0
    total_steps: int = 0
    total_tool_calls: int = 0
    total_memory_hits: int = 0

    @property
    def success_rate(self) -> float:
        return self.successful_tasks / self.total_tasks if self.total_tasks > 0 else 0.0

    @property
    def avg_rating(self) -> float:
        return self.total_rating / self.rating_count if self.rating_count > 0 else 0.0

    @property
    def avg_execution_time_ms(self) -> float:
        return self.total_execution_time_ms / self.total_tasks if self.total_tasks > 0 else 0.0

    @property
    def avg_steps(self) -> float:
        return self.total_steps / self.total_tasks if self.total_tasks > 0 else 0.0

    @property
    def avg_tool_calls(self) -> float:
        return self.total_tool_calls / self.total_tasks if self.total_tasks > 0 else 0.0

    @property
    def avg_memory_hits(self) -> float:
        return self.total_memory_hits / self.total_tasks if self.total_tasks > 0 else 0.0

    def to_dict(self) -> dict:
        """转换为字典（仅保存数据字段，排除计算属性）"""
        return {
            "template_name": self.template_name,
            "total_tasks": self.total_tasks,
            "successful_tasks": self.successful_tasks,
            "total_rating": self.total_rating,
            "rating_count": self.rating_count,
            "total_execution_time_ms": self.total_execution_time_ms,
            "total_steps": self.total_steps,
            "total_tool_calls": self.total_tool_calls,
            "total_memory_hits": self.total_memory_hits,
        }


@dataclass
class UserProfile:
    """用户画像（匿名化）"""
    profile_id: str                           # 匿名化ID
    developer_score: float = 0.0              # 开发者倾向（0-1）
    creative_score: float = 0.0               # 创意倾向（0-1）
    efficiency_score: float = 0.0             # 效率倾向（0-1）
    safety_score: float = 0.0                 # 安全倾向（0-1）
    aesthetic_score: float = 0.0              # 美学倾向（0-1）
    interaction_count: int = 0                # 交互次数
    preferred_template: str | None = None  # 偏好的模板

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WeeklyReport:
    """每周实验报告"""
    week_start: str                           # 周开始日期 (YYYY-MM-DD)
    week_end: str                             # 周结束日期
    generated_at: float = field(default_factory=time.time)
    template_comparison: dict[str, TemplateStats] = field(default_factory=dict)
    winner_template: str | None = None
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "week_start": self.week_start,
            "week_end": self.week_end,
            "generated_at": self.generated_at,
            "template_comparison": {k: v.to_dict() for k, v in self.template_comparison.items()},
            "winner_template": self.winner_template,
            "recommendations": self.recommendations,
        }


class TemplateExperiment:
    """
    模板效果A/B测试管理器

    管理5个模板的效果测试：
    - guardian: 守护者（安全稳定）
    - explorer: 探索者（创新好奇）
    - geek: 极客（技术效率）
    - artist: 艺术家（创意美学）
    - balanced: 均衡者（平衡全面）
    """

    # 默认模板列表
    DEFAULT_TEMPLATES = ["guardian", "explorer", "geek", "artist", "balanced"]

    # 数据存储路径
    DATA_DIR = Path("data/template_experiments")

    def __init__(self):
        self.experiments: dict[str, dict] = {
            "task_success_rate": {},
            "user_satisfaction": {},
            "memory_utilization": {},
            "reflection_quality": {},
            "execution_speed": {},
            "tool_accuracy": {},
        }

        # 模板统计数据
        self.template_stats: dict[str, TemplateStats] = {
            name: TemplateStats(template_name=name)
            for name in self.DEFAULT_TEMPLATES
        }

        # 用户画像（匿名化存储）
        self.user_profiles: dict[str, UserProfile] = {}

        # 任务结果历史
        self.task_history: list[TaskResult] = []

        # 每周报告
        self.weekly_reports: list[WeeklyReport] = []

        # 确保数据目录存在
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)

        # 加载历史数据
        self._load_data()

        logger.info("[TemplateExperiment] 模板实验管理器已初始化")
        logger.info(f"[TemplateExperiment] 可用模板: {self.DEFAULT_TEMPLATES}")

    def _get_user_profile_id(self, user_id: str) -> str:
        """
        生成匿名化用户画像ID
        使用SHA256哈希确保隐私
        """
        return hashlib.sha256(f"siliconbase_{user_id}".encode()).hexdigest()[:16]

    def _load_data(self):
        """加载历史实验数据"""
        try:
            # 加载模板统计
            stats_file = self.DATA_DIR / "template_stats.json"
            if stats_file.exists():
                with open(stats_file, encoding='utf-8') as f:
                    data = json.load(f)
                    for name, stats_data in data.items():
                        if name in self.template_stats:
                            # 过滤计算属性字段，只保留数据类字段
                            valid_fields = {
                                'template_name', 'total_tasks', 'successful_tasks',
                                'total_rating', 'rating_count', 'total_execution_time_ms',
                                'total_steps', 'total_tool_calls', 'total_memory_hits'
                            }
                            filtered_data = {k: v for k, v in stats_data.items() if k in valid_fields}
                            self.template_stats[name] = TemplateStats(**filtered_data)
                logger.info(f"[TemplateExperiment] 已加载 {len(data)} 个模板统计数据")

            # 加载任务历史（最近1000条）
            history_file = self.DATA_DIR / "task_history.json"
            if history_file.exists():
                with open(history_file, encoding='utf-8') as f:
                    data = json.load(f)
                    self.task_history = [TaskResult(**item) for item in data[-1000:]]
                logger.info(f"[TemplateExperiment] 已加载 {len(self.task_history)} 条任务历史")

            # 加载用户画像
            profiles_file = self.DATA_DIR / "user_profiles.json"
            if profiles_file.exists():
                with open(profiles_file, encoding='utf-8') as f:
                    data = json.load(f)
                    self.user_profiles = {
                        k: UserProfile(**v) for k, v in data.items()
                    }
                logger.info(f"[TemplateExperiment] 已加载 {len(self.user_profiles)} 个用户画像")

            # 加载每周报告
            reports_file = self.DATA_DIR / "weekly_reports.json"
            if reports_file.exists():
                with open(reports_file, encoding='utf-8') as f:
                    data = json.load(f)
                    self.weekly_reports = [WeeklyReport(**item) for item in data]
                logger.info(f"[TemplateExperiment] 已加载 {len(self.weekly_reports)} 份周报告")

        except Exception as e:
            logger.warning(f"[TemplateExperiment] 加载历史数据失败: {e}")

    def _save_data(self):
        """保存实验数据到本地"""
        try:
            # 保存模板统计
            stats_file = self.DATA_DIR / "template_stats.json"
            with open(stats_file, 'w', encoding='utf-8') as f:
                json.dump(
                    {k: v.to_dict() for k, v in self.template_stats.items()},
                    f, ensure_ascii=False, indent=2
                )

            # 保存任务历史
            history_file = self.DATA_DIR / "task_history.json"
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(
                    [t.to_dict() for t in self.task_history[-1000:]],
                    f, ensure_ascii=False, indent=2
                )

            # 保存用户画像
            profiles_file = self.DATA_DIR / "user_profiles.json"
            with open(profiles_file, 'w', encoding='utf-8') as f:
                json.dump(
                    {k: v.to_dict() for k, v in self.user_profiles.items()},
                    f, ensure_ascii=False, indent=2
                )

            # 保存每周报告
            reports_file = self.DATA_DIR / "weekly_reports.json"
            with open(reports_file, 'w', encoding='utf-8') as f:
                json.dump(
                    [r.to_dict() for r in self.weekly_reports],
                    f, ensure_ascii=False, indent=2
                )

        except Exception as e:
            logger.warning(f"[TemplateExperiment] 保存数据失败: {e}")

    def track_task(self, template_name: str, task_result: dict) -> str:
        """
        追踪任务结果

        Args:
            template_name: 使用的模板名称
            task_result: 任务结果字典，包含:
                - task_id: 任务ID
                - success: 是否成功 (bool)
                - user_rating: 用户评分 1-5 (可选)
                - user_feedback: 用户反馈文字 (可选)
                - execution_time_ms: 执行耗时毫秒 (可选)
                - steps_count: 执行步骤数 (可选)
                - tool_calls_count: 工具调用次数 (可选)
                - reflection_depth: 反思深度 (可选)
                - memory_hits: 记忆命中次数 (可选)

        Returns:
            result_id: 结果记录ID
        """
        # 验证模板名称
        if template_name not in self.DEFAULT_TEMPLATES:
            logger.warning(f"[TemplateExperiment] 未知模板: {template_name}")
            template_name = "balanced"  # 默认使用均衡模板

        # 创建任务结果记录
        result = TaskResult(
            task_id=task_result.get("task_id", str(uuid.uuid4())),
            template_name=template_name,
            success=task_result.get("success", False),
            user_rating=task_result.get("user_rating", 0),
            user_feedback=task_result.get("user_feedback", ""),
            execution_time_ms=task_result.get("execution_time_ms", 0),
            steps_count=task_result.get("steps_count", 0),
            tool_calls_count=task_result.get("tool_calls_count", 0),
            reflection_depth=task_result.get("reflection_depth", 0),
            memory_hits=task_result.get("memory_hits", 0),
        )

        # 更新模板统计
        stats = self.template_stats[template_name]
        stats.total_tasks += 1
        if result.success:
            stats.successful_tasks += 1
        if result.user_rating > 0:
            stats.total_rating += result.user_rating
            stats.rating_count += 1
        stats.total_execution_time_ms += result.execution_time_ms
        stats.total_steps += result.steps_count
        stats.total_tool_calls += result.tool_calls_count
        stats.total_memory_hits += result.memory_hits

        # 添加到历史记录
        self.task_history.append(result)

        # 记录到实验指标
        self._record_experiment_metric(template_name, result)

        # 保存数据
        self._save_data()

        logger.debug(
            f"[TemplateExperiment] 记录任务: {template_name} "
            f"成功={result.success}, 评分={result.user_rating}"
        )

        return result.task_id

    def _record_experiment_metric(self, template_name: str, result: TaskResult):
        """记录实验指标"""
        # 任务成功率
        self.experiments["task_success_rate"].setdefault(template_name, []).append(
            1.0 if result.success else 0.0
        )

        # 用户满意度
        if result.user_rating > 0:
            self.experiments["user_satisfaction"].setdefault(template_name, []).append(
                result.user_rating
            )

        # 记忆利用率
        self.experiments["memory_utilization"].setdefault(template_name, []).append(
            result.memory_hits
        )

        # 反思质量
        self.experiments["reflection_quality"].setdefault(template_name, []).append(
            result.reflection_depth
        )

        # 执行速度
        self.experiments["execution_speed"].setdefault(template_name, []).append(
            result.execution_time_ms
        )

        # 工具准确率
        tool_accuracy = 1.0 if result.success else 0.0
        self.experiments["tool_accuracy"].setdefault(template_name, []).append(
            tool_accuracy
        )

    def get_template_report(self) -> dict[str, dict]:
        """
        生成各模板效果报告

        Returns:
            包含各模板统计数据的字典
        """
        return {name: stats.to_dict() for name, stats in self.template_stats.items()}

    def get_experiment_comparison(self) -> dict[str, Any]:
        """
        获取实验对比数据（用于Dashboard）

        Returns:
            包含对比图表数据的字典
        """
        return {
            "templates": self.DEFAULT_TEMPLATES,
            "success_rates": [
                self.template_stats[name].success_rate
                for name in self.DEFAULT_TEMPLATES
            ],
            "avg_ratings": [
                self.template_stats[name].avg_rating
                for name in self.DEFAULT_TEMPLATES
            ],
            "avg_execution_times": [
                self.template_stats[name].avg_execution_time_ms
                for name in self.DEFAULT_TEMPLATES
            ],
            "total_tasks": [
                self.template_stats[name].total_tasks
                for name in self.DEFAULT_TEMPLATES
            ],
            "last_updated": time.time(),
        }

    def update_user_profile(self, user_id: str, interaction_data: dict):
        """
        更新用户画像（匿名化）

        Args:
            user_id: 用户ID（将被匿名化）
            interaction_data: 交互数据，包含:
                - task_type: 任务类型
                - template_used: 使用的模板
                - success: 是否成功
                - complexity: 任务复杂度
        """
        profile_id = self._get_user_profile_id(user_id)

        if profile_id not in self.user_profiles:
            self.user_profiles[profile_id] = UserProfile(profile_id=profile_id)

        profile = self.user_profiles[profile_id]
        profile.interaction_count += 1

        # 根据交互数据更新画像分数
        task_type = interaction_data.get("task_type", "")
        template_used = interaction_data.get("template_used", "")
        success = interaction_data.get("success", False)

        # 更新开发者倾向（技术相关任务）
        if any(kw in task_type.lower() for kw in ["code", "script", "api", "debug", "dev"]):
            profile.developer_score = min(1.0, profile.developer_score + 0.1)

        # 更新创意倾向（创意相关任务）
        if any(kw in task_type.lower() for kw in ["design", "creative", "art", "write", "idea"]):
            profile.creative_score = min(1.0, profile.creative_score + 0.1)

        # 更新效率倾向（快速完成任务）
        if success and interaction_data.get("execution_time_ms", 0) < 5000:
            profile.efficiency_score = min(1.0, profile.efficiency_score + 0.05)

        # 更新安全倾向（使用guardian模板且成功）
        if template_used == "guardian" and success:
            profile.safety_score = min(1.0, profile.safety_score + 0.05)

        # 更新美学倾向（使用artist模板且成功）
        if template_used == "artist" and success:
            profile.aesthetic_score = min(1.0, profile.aesthetic_score + 0.05)

        # 更新偏好模板
        if success and template_used in self.DEFAULT_TEMPLATES:
            profile.preferred_template = template_used

        self._save_data()

        logger.debug(f"[TemplateExperiment] 更新用户画像: {profile_id}")

    def recommend_template(self, user_profile: dict) -> str:
        """
        根据用户画像推荐模板

        Args:
            user_profile: 用户画像字典，可包含:
                - developer: 开发者倾向 (bool/float)
                - creative: 创意倾向 (bool/float)
                - efficiency: 效率倾向 (bool/float)
                - safety: 安全倾向 (bool/float)
                - aesthetic: 美学倾向 (bool/float)

        Returns:
            推荐的模板名称
        """
        # 提取各项分数
        dev_score = float(user_profile.get("developer", 0))
        creative_score = float(user_profile.get("creative", 0))
        efficiency_score = float(user_profile.get("efficiency", 0))
        safety_score = float(user_profile.get("safety", 0))
        aesthetic_score = float(user_profile.get("aesthetic", 0))

        # 归一化布尔值
        if isinstance(user_profile.get("developer"), bool):
            dev_score = 1.0 if dev_score else 0.0
        if isinstance(user_profile.get("creative"), bool):
            creative_score = 1.0 if creative_score else 0.0
        if isinstance(user_profile.get("safety"), bool):
            safety_score = 1.0 if safety_score else 0.0

        # 评分系统
        scores = {
            "geek": dev_score * 2.0 + efficiency_score * 1.5,
            "explorer": creative_score * 1.5 + efficiency_score * 0.5,
            "guardian": safety_score * 2.0 + dev_score * 0.5,
            "artist": aesthetic_score * 2.0 + creative_score * 1.0,
            "balanced": 0.5,  # 基础分数
        }

        # 根据历史效果调整分数
        for template in self.DEFAULT_TEMPLATES:
            stats = self.template_stats[template]
            if stats.total_tasks >= 10:  # 有足够样本
                # 成功率加权
                scores[template] += stats.success_rate * 0.5
                # 用户评分加权
                scores[template] += (stats.avg_rating / 5.0) * 0.3

        # 选择最高分
        recommended = max(scores, key=scores.get)

        logger.info(
            f"[TemplateExperiment] 推荐模板: {recommended} "
            f"(geek={scores['geek']:.2f}, explorer={scores['explorer']:.2f}, "
            f"guardian={scores['guardian']:.2f}, artist={scores['artist']:.2f}, "
            f"balanced={scores['balanced']:.2f})"
        )

        return recommended

    def generate_weekly_report(self) -> WeeklyReport:
        """
        生成每周实验报告

        Returns:
            WeeklyReport 对象
        """
        # 计算本周日期范围
        today = datetime.now()
        week_end = today - timedelta(days=today.weekday())
        week_start = week_end - timedelta(days=7)

        week_start_str = week_start.strftime("%Y-%m-%d")
        week_end_str = week_end.strftime("%Y-%m-%d")

        # 筛选本周的任务
        week_start_ts = week_start.timestamp()
        week_end_ts = week_end.timestamp()

        weekly_tasks = [
            t for t in self.task_history
            if week_start_ts <= t.timestamp < week_end_ts
        ]

        # 计算本周各模板的统计
        weekly_stats: dict[str, TemplateStats] = {
            name: TemplateStats(template_name=name)
            for name in self.DEFAULT_TEMPLATES
        }

        for task in weekly_tasks:
            if task.template_name in weekly_stats:
                stats = weekly_stats[task.template_name]
                stats.total_tasks += 1
                if task.success:
                    stats.successful_tasks += 1
                if task.user_rating > 0:
                    stats.total_rating += task.user_rating
                    stats.rating_count += 1

        # 找出获胜模板（综合评分）
        best_template = None
        best_score = -1

        for name, stats in weekly_stats.items():
            if stats.total_tasks >= 5:  # 至少5个样本
                # 综合评分 = 成功率 * 0.4 + 用户评分 * 0.3 + 样本数标准化 * 0.3
                score = (
                    stats.success_rate * 0.4 +
                    (stats.avg_rating / 5.0) * 0.3 +
                    min(stats.total_tasks / 20, 1.0) * 0.3
                )
                if score > best_score:
                    best_score = score
                    best_template = name

        # 生成建议
        recommendations = []

        if best_template:
            recommendations.append(f"本周最佳模板: {best_template} (综合评分: {best_score:.2f})")

            # 根据表现给出具体建议
            best_stats = weekly_stats[best_template]
            if best_stats.success_rate > 0.9:
                recommendations.append(f"{best_template}模板成功率极高({best_stats.success_rate:.1%})，建议推广使用")
            if best_stats.avg_rating > 4.0:
                recommendations.append(f"{best_template}模板用户满意度优秀({best_stats.avg_rating:.1f}/5)")

        # 分析需要改进的模板
        for name, stats in weekly_stats.items():
            if stats.total_tasks >= 5 and stats.success_rate < 0.7:
                recommendations.append(f"{name}模板成功率较低({stats.success_rate:.1%})，建议优化")
            if stats.total_tasks >= 5 and stats.avg_rating < 3.0:
                recommendations.append(f"{name}模板用户评分较低({stats.avg_rating:.1f}/5)，建议改进")

        # 样本量不足的提醒
        low_sample_templates = [
            name for name, stats in weekly_stats.items()
            if stats.total_tasks < 5
        ]
        if low_sample_templates:
            recommendations.append(
                f"以下模板本周样本不足: {', '.join(low_sample_templates)}，建议增加测试"
            )

        # 创建报告
        report = WeeklyReport(
            week_start=week_start_str,
            week_end=week_end_str,
            template_comparison=weekly_stats,
            winner_template=best_template,
            recommendations=recommendations,
        )

        # 保存报告
        self.weekly_reports.append(report)
        self._save_data()

        logger.info(
            f"[TemplateExperiment] 生成周报告: {week_start_str} ~ {week_end_str}, "
            f"获胜模板: {best_template}"
        )

        return report

    def get_latest_weekly_report(self) -> dict | None:
        """获取最新的周报告"""
        if not self.weekly_reports:
            return None
        return self.weekly_reports[-1].to_dict()

    def get_all_weekly_reports(self) -> list[dict]:
        """获取所有周报告"""
        return [r.to_dict() for r in self.weekly_reports]

    def get_user_recommendation(self, user_id: str) -> dict[str, Any]:
        """
        获取针对特定用户的模板推荐

        Args:
            user_id: 用户ID

        Returns:
            包含推荐信息和理由的字典
        """
        profile_id = self._get_user_profile_id(user_id)

        if profile_id not in self.user_profiles:
            # 新用户，返回默认推荐
            return {
                "recommended_template": "balanced",
                "confidence": 0.3,
                "reason": "新用户，使用均衡模板开始",
                "alternatives": ["explorer", "geek"],
            }

        profile = self.user_profiles[profile_id]

        # 根据画像生成推荐
        recommended = self.recommend_template({
            "developer": profile.developer_score,
            "creative": profile.creative_score,
            "efficiency": profile.efficiency_score,
            "safety": profile.safety_score,
            "aesthetic": profile.aesthetic_score,
        })

        # 生成推荐理由
        reasons = []
        if profile.developer_score > 0.5:
            reasons.append("技术导向")
        if profile.creative_score > 0.5:
            reasons.append("创意导向")
        if profile.efficiency_score > 0.5:
            reasons.append("效率导向")
        if profile.safety_score > 0.5:
            reasons.append("安全导向")
        if profile.aesthetic_score > 0.5:
            reasons.append("美学导向")

        if not reasons:
            reasons.append("均衡全面")

        # 计算置信度
        confidence = min(0.9, profile.interaction_count * 0.1 + 0.3)

        # 备选模板
        alternatives = [t for t in self.DEFAULT_TEMPLATES if t != recommended][:2]

        return {
            "recommended_template": recommended,
            "confidence": round(confidence, 2),
            "reason": f"根据您的{', '.join(reasons)}倾向推荐",
            "alternatives": alternatives,
            "interaction_count": profile.interaction_count,
        }

    def export_data(self, format: str = "json") -> str:
        """
        导出实验数据（用于备份或分析）

        Args:
            format: 导出格式，目前支持 "json"

        Returns:
            导出文件路径
        """
        if format == "json":
            export_file = self.DATA_DIR / f"export_{int(time.time())}.json"
            data = {
                "export_time": time.time(),
                "export_date": datetime.now().isoformat(),
                "template_stats": {k: v.to_dict() for k, v in self.template_stats.items()},
                "weekly_reports": [r.to_dict() for r in self.weekly_reports],
                "total_tasks": len(self.task_history),
            }
            with open(export_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"[TemplateExperiment] 数据已导出到: {export_file}")
            return str(export_file)
        else:
            raise ValueError(f"不支持的导出格式: {format}")

    def clear_user_data(self, user_id: str) -> bool:
        """
        清除特定用户的数据（隐私合规）

        Args:
            user_id: 用户ID

        Returns:
            是否成功清除
        """
        profile_id = self._get_user_profile_id(user_id)

        if profile_id in self.user_profiles:
            del self.user_profiles[profile_id]
            self._save_data()
            logger.info(f"[TemplateExperiment] 已清除用户数据: {profile_id}")
            return True
        return False


# =============================================================================
# 全局实例
# =============================================================================

# 全局单例
template_experiment = TemplateExperiment()


# =============================================================================
# 便捷函数
# =============================================================================

def track_task_result(template_name: str, task_result: dict) -> str:
    """便捷函数：记录任务结果"""
    return template_experiment.track_task(template_name, task_result)


def get_template_report() -> dict[str, dict]:
    """便捷函数：获取模板报告"""
    return template_experiment.get_template_report()


def recommend_template(user_profile: dict) -> str:
    """便捷函数：推荐模板"""
    return template_experiment.recommend_template(user_profile)


def update_user_feedback(user_id: str, template_name: str, rating: int, feedback: str = ""):
    """便捷函数：更新用户反馈"""
    template_experiment.update_user_profile(user_id, {
        "template_used": template_name,
        "user_rating": rating,
        "user_feedback": feedback,
    })


def generate_weekly_report() -> dict:
    """便捷函数：生成周报告"""
    report = template_experiment.generate_weekly_report()
    return report.to_dict()


def get_user_template_recommendation(user_id: str) -> dict[str, Any]:
    """便捷函数：获取用户模板推荐"""
    return template_experiment.get_user_recommendation(user_id)


# =============================================================================
# 总结性注释
# =============================================================================
#
# 【文件角色】
# 本文件是 SiliconBase V5 系统中 Agent-5（权重验证实验师）的核心交付物，
# 负责建立和管理模板效果的A/B测试框架，为系统选择最优模板组合提供数据支持。
#
# 【核心职责】
# 1. 多模板效果追踪：追踪5个模板（guardian/explorer/geek/artist/balanced）的表现
# 2. 多维指标评估：任务成功率、用户满意度、记忆利用率、反思质量等
# 3. 智能推荐：基于用户画像自动推荐最适合的模板
# 4. 周报告生成：每周自动生成模板效果对比报告
# 5. 数据隐私保护：用户数据匿名化，支持数据导出和删除
#
# 【5个模板特性】
# - guardian: 守护者，安全稳定导向，适合风险敏感用户
# - explorer: 探索者，创新好奇导向，适合喜欢尝试新功能的用户
# - geek: 极客，技术效率导向，适合开发者和技术用户
# - artist: 艺术家，创意美学导向，适合设计和创意工作者
# - balanced: 均衡者，平衡全面导向，适合大多数普通用户
#
# 【关联文件】
# 1. core/experiment_manager.py - 策略AB测试管理器
#    * 关系：本文件专注于模板效果，experiment_manager专注于策略实验
#    * 交互：可共享用户反馈数据
#
# 2. frontend/src/components/FeedbackDialog.tsx - 前端反馈组件
#    * 关系：前端收集用户评分，本文件处理后端存储和分析
#    * 交互：通过API传递用户评分数据
#
# 3. frontend/src/pages/DashboardPage.tsx - 效果Dashboard
#    * 关系：本文件提供数据，Dashboard可视化展示
#    * 交互：通过API获取实验对比数据
#
# 【数据隐私合规】
# 1. 用户ID使用SHA256哈希匿名化
# 2. 仅收集任务执行统计，不收集敏感内容
# 3. 数据本地存储，不上传云端
# 4. 提供数据导出和删除功能
#
# 【典型使用场景】
# - 新用户首次使用，根据画像推荐初始模板
# - 任务完成后，弹出评分组件收集用户反馈
# - 每周一生成上周实验报告，供开发者优化
# - Dashboard实时展示各模板效果对比
#
