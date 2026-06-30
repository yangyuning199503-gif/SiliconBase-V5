#!/usr/bin/env python3
"""
幻觉率统计与持久化模块
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
负责：
1. 幻觉检测结果的数据库存储
2. 幻觉率统计指标计算
3. 趋势分析与报告生成

数据表结构：
- hallucination_stats: 每次检测的详细记录
- hallucination_summary: 按会话/日期的汇总统计
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from core.logger import logger

# 尝试导入 asyncpg 池
try:
    from core.memory.postgres_pool import AsyncPostgresPool
    ASYNC_POOL_AVAILABLE = True
except Exception:
    AsyncPostgresPool = None  # type: ignore[misc,assignment]
    ASYNC_POOL_AVAILABLE = False

# 尝试导入数据库相关依赖
try:
    from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String, Text, create_engine
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import sessionmaker
    SQLALCHEMY_AVAILABLE = True
    Base = declarative_base()
except ImportError:
    SQLALCHEMY_AVAILABLE = False
    Base = object


# ========== 数据模型 ==========

if SQLALCHEMY_AVAILABLE:
    class HallucinationStatsModel(Base):
        """幻觉检测统计表 - SQLAlchemy模型"""
        __tablename__ = 'hallucination_stats'

        id = Column(Integer, primary_key=True, autoincrement=True)
        session_id = Column(String(255), index=True, nullable=False)
        user_id = Column(String(255), index=True, nullable=True)

        # 输入输出
        query_text = Column(Text, nullable=True)
        response_text = Column(Text, nullable=False)
        response_snippet = Column(String(500), nullable=True)  # 摘要

        # 检测结果
        uncertainty_score = Column(Float, nullable=False, default=0.0)
        hallucination_level = Column(String(20), nullable=False, default='none')
        flagged = Column(Boolean, nullable=False, default=False)

        # 详细数据 (JSON格式)
        detected_claims = Column(Text, nullable=True)  # JSON
        uncertain_phrases = Column(Text, nullable=True)  # JSON
        verification_notes = Column(Text, nullable=True)  # JSON
        knowledge_matches = Column(Text, nullable=True)  # JSON

        # 上下文
        context_summary = Column(Text, nullable=True)  # 上下文摘要

        # 元信息
        timestamp = Column(DateTime, default=datetime.utcnow)
        created_at = Column(DateTime, default=datetime.utcnow)

        # 索引
        __table_args__ = (
            Index('idx_halluc_timestamp', 'timestamp'),
            Index('idx_halluc_level', 'hallucination_level'),
            Index('idx_halluc_score', 'uncertainty_score'),
        )


    class HallucinationDailySummary(Base):
        """每日幻觉统计汇总"""
        __tablename__ = 'hallucination_daily_summary'

        id = Column(Integer, primary_key=True, autoincrement=True)
        date = Column(String(10), unique=True, nullable=False)  # YYYY-MM-DD

        # 统计指标
        total_checks = Column(Integer, default=0)
        high_uncertainty_count = Column(Integer, default=0)  # score >= 0.5
        critical_count = Column(Integer, default=0)  # level = critical

        # 分布
        none_count = Column(Integer, default=0)
        low_count = Column(Integer, default=0)
        medium_count = Column(Integer, default=0)
        high_count = Column(Integer, default=0)

        # 平均分数
        avg_uncertainty_score = Column(Float, default=0.0)

        # 计算时间
        calculated_at = Column(DateTime, default=datetime.utcnow)
else:
    # SQLAlchemy不可用时的占位类
    HallucinationStatsModel = None
    HallucinationDailySummary = None


@dataclass
class HallucinationMetrics:
    """幻觉率指标数据类"""
    total_checks: int = 0
    high_uncertainty_count: int = 0
    critical_count: int = 0

    # 百分比
    high_uncertainty_rate: float = 0.0  # 高不确定率
    hallucination_rate: float = 0.0     # 疑似幻觉率

    # 等级分布
    level_distribution: dict[str, int] = None

    # 趋势 (与上一周期对比)
    trend_vs_last_period: float = 0.0

    # 时间范围
    period_start: datetime | None = None
    period_end: datetime | None = None

    def __post_init__(self):
        if self.level_distribution is None:
            self.level_distribution = {
                "none": 0, "low": 0, "medium": 0, "high": 0, "critical": 0
            }


# ========== 统计管理器 ==========

class HallucinationStatsManager:
    """
    幻觉统计管理器

    负责幻觉检测数据的持久化和统计分析
    """

    def __init__(self, db_url: str | None = None):
        """
        初始化统计管理器

        Args:
            db_url: 数据库连接URL，None则使用内存存储
        """
        self.db_url = db_url
        self.engine = None
        self.Session = None
        self._memory_storage: list[dict] = []  # 内存存储备用

        if SQLALCHEMY_AVAILABLE and db_url:
            try:
                self.engine = create_engine(db_url)
                Base.metadata.create_all(self.engine)
                self.Session = sessionmaker(bind=self.engine)
                logger.info("[HallucinationStats] 数据库连接成功")
            except Exception as e:
                logger.error(f"[HallucinationStats] 数据库连接失败: {e}，使用内存存储")
                self.engine = None

    async def _get_pool(self):
        """获取 asyncpg 连接池（优先），否则返回 None"""
        if not ASYNC_POOL_AVAILABLE:
            return None
        try:
            return await AsyncPostgresPool.get_pool()
        except Exception as e:
            logger.debug(f"[HallucinationStats] asyncpg 池不可用: {e}")
            return None

    async def save_check_result(
        self,
        session_id: str,
        result: Any,  # HallucinationCheckResult
        query_text: str = "",
        user_id: str = "",
        context: dict | None = None
    ) -> bool:
        """
        保存检测结果

        Args:
            session_id: 会话ID
            result: 检测结果对象
            query_text: 用户查询文本
            user_id: 用户ID
            context: 上下文信息

        Returns:
            是否保存成功
        """
        pool = await self._get_pool()
        if pool is not None:
            return await self._save_check_result_async(
                pool, session_id, result, query_text, user_id, context
            )
        return await asyncio.to_thread(
            self._save_check_result_sync,
            session_id, result, query_text, user_id, context
        )

    async def _save_check_result_async(
        self,
        pool,
        session_id: str,
        result: Any,
        query_text: str = "",
        user_id: str = "",
        context: dict | None = None
    ) -> bool:
        """保存检测结果（原生 asyncpg 实现）"""
        try:
            flagged = result.hallucination_level.value in ['high', 'critical']
            query_text_val = query_text[:500] if query_text else None
            response_snippet = result.response_snippet or ""
            snippet_short = response_snippet[:200] if response_snippet else None
            detected_claims = json.dumps([
                {"text": c.text, "type": c.claim_type, "has_source": c.has_source}
                for c in result.detected_claims
            ], ensure_ascii=False) if result.detected_claims else None
            uncertain_phrases = json.dumps(result.uncertain_phrases, ensure_ascii=False) if result.uncertain_phrases else None
            verification_notes = json.dumps(result.verification_notes, ensure_ascii=False) if result.verification_notes else None
            knowledge_matches = json.dumps(result.knowledge_matches, ensure_ascii=False) if result.knowledge_matches else None
            context_summary = json.dumps({
                "has_memory_refs": bool(context.get("memory_references")) if context else False,
                "has_tool_results": bool(context.get("tool_results")) if context else False,
            }, ensure_ascii=False) if context else None
            ts = datetime.fromtimestamp(result.timestamp)

            sql = """
                INSERT INTO hallucination_stats (
                    session_id, user_id, query_text, response_text, response_snippet,
                    uncertainty_score, hallucination_level, flagged,
                    detected_claims, uncertain_phrases, verification_notes, knowledge_matches,
                    context_summary, timestamp, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, NOW())
            """
            await pool.execute(
                sql, session_id, user_id, query_text_val, response_snippet, snippet_short,
                result.uncertainty_score, result.hallucination_level.value, flagged,
                detected_claims, uncertain_phrases, verification_notes, knowledge_matches,
                context_summary, ts
            )
            return True
        except Exception as e:
            logger.error(f"[HallucinationStats] async 保存失败: {e}")
            return False

    def _save_check_result_sync(
        self,
        session_id: str,
        result: Any,  # HallucinationCheckResult
        query_text: str = "",
        user_id: str = "",
        context: dict | None = None
    ) -> bool:
        """
        保存检测结果（同步实现）
        """
        try:
            flagged = result.hallucination_level.value in ['high', 'critical']

            record = {
                "session_id": session_id,
                "user_id": user_id,
                "query_text": query_text[:500] if query_text else None,
                "response_text": result.response_snippet or "",
                "response_snippet": result.response_snippet[:200] if result.response_snippet else None,
                "uncertainty_score": result.uncertainty_score,
                "hallucination_level": result.hallucination_level.value,
                "flagged": flagged,
                "detected_claims": json.dumps([
                    {"text": c.text, "type": c.claim_type, "has_source": c.has_source}
                    for c in result.detected_claims
                ], ensure_ascii=False) if result.detected_claims else None,
                "uncertain_phrases": json.dumps(result.uncertain_phrases, ensure_ascii=False) if result.uncertain_phrases else None,
                "verification_notes": json.dumps(result.verification_notes, ensure_ascii=False) if result.verification_notes else None,
                "knowledge_matches": json.dumps(result.knowledge_matches, ensure_ascii=False) if result.knowledge_matches else None,
                "context_summary": json.dumps({
                    "has_memory_refs": bool(context.get("memory_references")) if context else False,
                    "has_tool_results": bool(context.get("tool_results")) if context else False,
                }, ensure_ascii=False) if context else None,
                "timestamp": datetime.fromtimestamp(result.timestamp),
            }

            if self.Session:
                with self.Session() as session:
                    db_record = HallucinationStatsModel(**record)
                    session.add(db_record)
                    session.commit()
            else:
                # 使用内存存储
                record["id"] = len(self._memory_storage) + 1
                record["created_at"] = datetime.utcnow()
                self._memory_storage.append(record)

            return True

        except Exception as e:
            logger.error(f"[HallucinationStats] 保存失败: {e}")
            return False

    async def get_metrics(
        self,
        period_days: int = 7,
        user_id: str | None = None
    ) -> HallucinationMetrics:
        """
        获取统计指标

        Args:
            period_days: 统计周期天数
            user_id: 指定用户，None则统计全部

        Returns:
            HallucinationMetrics
        """
        pool = await self._get_pool()
        if pool is not None:
            return await self._get_metrics_async(pool, period_days, user_id)
        return await asyncio.to_thread(
            self._get_metrics_sync,
            period_days, user_id
        )

    async def _get_metrics_async(
        self,
        pool,
        period_days: int = 7,
        user_id: str | None = None
    ) -> HallucinationMetrics:
        """获取统计指标（原生 asyncpg 实现）"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=period_days)
        metrics = HallucinationMetrics(period_start=start_date, period_end=end_date)
        try:
            if user_id:
                sql = """
                    SELECT hallucination_level, uncertainty_score
                    FROM hallucination_stats
                    WHERE timestamp >= $1 AND timestamp <= $2 AND user_id = $3
                """
                rows = await pool.fetch(sql, start_date, end_date, user_id)
            else:
                sql = """
                    SELECT hallucination_level, uncertainty_score
                    FROM hallucination_stats
                    WHERE timestamp >= $1 AND timestamp <= $2
                """
                rows = await pool.fetch(sql, start_date, end_date)

            metrics.total_checks = len(rows)
            total_score = 0.0
            for row in rows:
                level = row["hallucination_level"]
                metrics.level_distribution[level] = metrics.level_distribution.get(level, 0) + 1
                score = row["uncertainty_score"] or 0.0
                total_score += score
                if score >= 0.5:
                    metrics.high_uncertainty_count += 1
                if level == 'critical':
                    metrics.critical_count += 1

            if metrics.total_checks > 0:
                metrics.avg_uncertainty_score = total_score / metrics.total_checks
                metrics.high_uncertainty_rate = metrics.high_uncertainty_count / metrics.total_checks
                metrics.hallucination_rate = (
                    metrics.level_distribution.get("high", 0) +
                    metrics.level_distribution.get("critical", 0)
                ) / metrics.total_checks

            return metrics
        except Exception as e:
            logger.error(f"[HallucinationStats] async 统计失败: {e}")
            return metrics

    def _get_metrics_sync(
        self,
        period_days: int = 7,
        user_id: str | None = None
    ) -> HallucinationMetrics:
        """
        获取统计指标（同步实现）
        """
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=period_days)

        metrics = HallucinationMetrics(period_start=start_date, period_end=end_date)

        try:
            if self.Session:
                with self.Session() as session:
                    query = session.query(HallucinationStatsModel).filter(
                        HallucinationStatsModel.timestamp >= start_date,
                        HallucinationStatsModel.timestamp <= end_date
                    )

                    if user_id:
                        query = query.filter(HallucinationStatsModel.user_id == user_id)

                    records = query.all()

                    metrics.total_checks = len(records)

                    for r in records:
                        metrics.level_distribution[r.hallucination_level] = \
                            metrics.level_distribution.get(r.hallucination_level, 0) + 1

                        if r.uncertainty_score >= 0.5:
                            metrics.high_uncertainty_count += 1

                        if r.hallucination_level == 'critical':
                            metrics.critical_count += 1

                    if records:
                        avg_score = sum(r.uncertainty_score for r in records) / len(records)
                        metrics.avg_uncertainty_score = avg_score
            else:
                # 内存存储查询
                records = [
                    r for r in self._memory_storage
                    if start_date <= r.get("timestamp", datetime.utcnow()) <= end_date
                    and (not user_id or r.get("user_id") == user_id)
                ]

                metrics.total_checks = len(records)

                for r in records:
                    level = r.get("hallucination_level", "none")
                    metrics.level_distribution[level] = metrics.level_distribution.get(level, 0) + 1

                    if r.get("uncertainty_score", 0) >= 0.5:
                        metrics.high_uncertainty_count += 1

                    if level == "critical":
                        metrics.critical_count += 1

            # 计算比率
            if metrics.total_checks > 0:
                metrics.high_uncertainty_rate = metrics.high_uncertainty_count / metrics.total_checks
                metrics.hallucination_rate = (
                    metrics.level_distribution.get("high", 0) +
                    metrics.level_distribution.get("critical", 0)
                ) / metrics.total_checks

            return metrics

        except Exception as e:
            logger.error(f"[HallucinationStats] 统计失败: {e}")
            return metrics

    async def get_recent_flags(
        self,
        limit: int = 10,
        min_level: str = "high"
    ) -> list[dict]:
        """
        获取最近标记的幻觉记录

        Args:
            limit: 返回数量
            min_level: 最低等级 (high/critical)

        Returns:
            记录列表
        """
        pool = await self._get_pool()
        if pool is not None:
            return await self._get_recent_flags_async(pool, limit, min_level)
        return await asyncio.to_thread(
            self._get_recent_flags_sync,
            limit, min_level
        )

    async def _get_recent_flags_async(
        self,
        pool,
        limit: int = 10,
        min_level: str = "high"
    ) -> list[dict]:
        """获取最近标记的幻觉记录（原生 asyncpg 实现）"""
        try:
            level_priority = {"low": 1, "medium": 2, "high": 3, "critical": 4}
            min_priority = level_priority.get(min_level, 3)
            # 由于 asyncpg 不直接支持 CASE 排序的字符串映射，先取所有 flagged 记录再过滤
            sql = """
                SELECT id, session_id, hallucination_level, uncertainty_score,
                       response_snippet, timestamp
                FROM hallucination_stats
                WHERE flagged = TRUE
                ORDER BY timestamp DESC
                LIMIT $1
            """
            rows = await pool.fetch(sql, limit * 3)  # 多取一些用于过滤
            result = []
            for row in rows:
                level = row["hallucination_level"]
                if level_priority.get(level, 0) >= min_priority:
                    result.append({
                        "id": row["id"],
                        "session_id": row["session_id"],
                        "level": level,
                        "score": row["uncertainty_score"],
                        "snippet": row["response_snippet"],
                        "timestamp": row["timestamp"].isoformat() if row["timestamp"] else ""
                    })
                if len(result) >= limit:
                    break
            return result
        except Exception as e:
            logger.error(f"[HallucinationStats] async 查询失败: {e}")
            return []

    def _get_recent_flags_sync(
        self,
        limit: int = 10,
        min_level: str = "high"
    ) -> list[dict]:
        """
        获取最近标记的幻觉记录（同步实现）
        """
        try:
            level_priority = {"low": 1, "medium": 2, "high": 3, "critical": 4}
            min_priority = level_priority.get(min_level, 3)

            if self.Session:
                with self.Session() as session:
                    records = session.query(HallucinationStatsModel).filter(
                        HallucinationStatsModel.flagged
                    ).order_by(
                        HallucinationStatsModel.timestamp.desc()
                    ).limit(limit).all()

                    return [
                        {
                            "id": r.id,
                            "session_id": r.session_id,
                            "level": r.hallucination_level,
                            "score": r.uncertainty_score,
                            "snippet": r.response_snippet,
                            "timestamp": r.timestamp.isoformat()
                        }
                        for r in records
                    ]
            else:
                # 内存存储
                filtered = [
                    r for r in self._memory_storage
                    if level_priority.get(r.get("hallucination_level"), 0) >= min_priority
                ]
                filtered.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

                return [
                    {
                        "id": r.get("id"),
                        "session_id": r.get("session_id"),
                        "level": r.get("hallucination_level"),
                        "score": r.get("uncertainty_score"),
                        "snippet": r.get("response_snippet"),
                        "timestamp": r.get("timestamp", "").isoformat() if isinstance(r.get("timestamp"), datetime) else str(r.get("timestamp", ""))
                    }
                    for r in filtered[:limit]
                ]

        except Exception as e:
            logger.error(f"[HallucinationStats] 查询失败: {e}")
            return []

    async def generate_report(self, period_days: int = 7) -> dict[str, Any]:
        """
        生成幻觉检测报告

        Args:
            period_days: 统计周期

        Returns:
            报告数据
        """
        metrics = await self.get_metrics(period_days)
        recent_flags = await self.get_recent_flags(limit=5)

        report = {
            "period_days": period_days,
            "generated_at": datetime.utcnow().isoformat(),
            "summary": {
                "total_checks": metrics.total_checks,
                "high_uncertainty_rate": f"{metrics.high_uncertainty_rate:.1%}",
                "hallucination_rate": f"{metrics.hallucination_rate:.1%}",
                "critical_count": metrics.critical_count
            },
            "level_distribution": metrics.level_distribution,
            "recent_flags": recent_flags,
            "recommendations": self._generate_recommendations(metrics)
        }

        return report

    def _generate_recommendations(self, metrics: HallucinationMetrics) -> list[str]:
        """生成改进建议"""
        recommendations = []

        if metrics.hallucination_rate > 0.1:
            recommendations.append("⚠️ 疑似幻觉率超过10%，建议加强提示词约束")

        if metrics.high_uncertainty_rate > 0.2:
            recommendations.append("⚠️ 高不确定率超过20%，建议优化知识库覆盖")

        if metrics.level_distribution.get("critical", 0) > 5:
            recommendations.append("🚨 检测到多次严重幻觉，需要立即检查模型配置")

        if not recommendations:
            recommendations.append("✅ 幻觉控制状况良好，继续保持")

        return recommendations


# ========== 便捷函数 ==========

_stats_manager: HallucinationStatsManager | None = None


async def get_stats_manager(db_url: str | None = None) -> HallucinationStatsManager:
    """获取统计管理器实例"""
    global _stats_manager
    if _stats_manager is None:
        _stats_manager = HallucinationStatsManager(db_url)
    return _stats_manager


async def save_hallucination_result(
    session_id: str,
    result: Any,
    query_text: str = "",
    user_id: str = "",
    context: dict | None = None
) -> bool:
    """便捷函数：保存检测结果"""
    manager = await get_stats_manager()
    return await manager.save_check_result(session_id, result, query_text, user_id, context)


async def get_hallucination_metrics(period_days: int = 7) -> HallucinationMetrics:
    """便捷函数：获取统计指标"""
    manager = await get_stats_manager()
    return await manager.get_metrics(period_days)


async def generate_hallucination_report(period_days: int = 7) -> dict[str, Any]:
    """便捷函数：生成报告"""
    manager = await get_stats_manager()
    return await manager.generate_report(period_days)


# ========== SQL 建表语句 ==========

CREATE_TABLE_SQL = """
-- 幻觉检测详细记录表
CREATE TABLE IF NOT EXISTS hallucination_stats (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(255),

    query_text TEXT,
    response_text TEXT NOT NULL,
    response_snippet VARCHAR(500),

    uncertainty_score FLOAT NOT NULL DEFAULT 0.0,
    hallucination_level VARCHAR(20) NOT NULL DEFAULT 'none',
    flagged BOOLEAN NOT NULL DEFAULT FALSE,

    detected_claims TEXT,  -- JSON格式
    uncertain_phrases TEXT,  -- JSON格式
    verification_notes TEXT,  -- JSON格式
    knowledge_matches TEXT,  -- JSON格式

    context_summary TEXT,

    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_halluc_session ON hallucination_stats(session_id);
CREATE INDEX IF NOT EXISTS idx_halluc_user ON hallucination_stats(user_id);
CREATE INDEX IF NOT EXISTS idx_halluc_timestamp ON hallucination_stats(timestamp);
CREATE INDEX IF NOT EXISTS idx_halluc_level ON hallucination_stats(hallucination_level);
CREATE INDEX IF NOT EXISTS idx_halluc_flagged ON hallucination_stats(flagged);

-- 每日汇总表
CREATE TABLE IF NOT EXISTS hallucination_daily_summary (
    id SERIAL PRIMARY KEY,
    date VARCHAR(10) UNIQUE NOT NULL,

    total_checks INTEGER DEFAULT 0,
    high_uncertainty_count INTEGER DEFAULT 0,
    critical_count INTEGER DEFAULT 0,

    none_count INTEGER DEFAULT 0,
    low_count INTEGER DEFAULT 0,
    medium_count INTEGER DEFAULT 0,
    high_count INTEGER DEFAULT 0,

    avg_uncertainty_score FLOAT DEFAULT 0.0,
    calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


if __name__ == "__main__":
    print("=== 幻觉统计模块 ===")
    print("\n建表SQL:")
    print(CREATE_TABLE_SQL)

    # 测试内存存储
    manager = HallucinationStatsManager()
    print("\n=== 内存存储测试 ===")
    print(f"统计管理器初始化: {'成功' if manager else '失败'}")
