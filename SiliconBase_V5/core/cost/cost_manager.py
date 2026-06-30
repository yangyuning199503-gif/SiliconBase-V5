#!/usr/bin/env python3
"""
成本管理器 - Token成本追踪与预算熔断
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
功能：
  ✓ 按模型单价计算成本
  ✓ 实时记录每次AI调用的成本
  ✓ 日/月预算超限自动熔断
  ✓ 异常成本实时告警
  ✓ 生成成本报告

数据库表：
  - token_usage: 详细使用记录
  - cost_stats: 成本统计（按日/月聚合）
"""

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any

from core.logger import logger
from core.utils.token_tracker import TokenCountResult

# 尝试导入PostgreSQL
try:
    import psycopg2
    from psycopg2.extras import Json, RealDictCursor
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False
    logger.warning("[CostManager] psycopg2未安装，数据库功能不可用")


class BudgetAlertLevel(Enum):
    """预算告警级别"""
    NORMAL = "normal"           # 正常
    WARNING = "warning"         # 警告（达到80%）
    CRITICAL = "critical"       # 严重（达到95%）
    EXCEEDED = "exceeded"       # 已超限


@dataclass
class CostRecord:
    """成本记录"""
    id: int | None
    user_id: str
    session_id: str | None
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    input_cost: Decimal
    output_cost: Decimal
    total_cost: Decimal
    request_type: str  # 'chat', 'completion', 'embedding'等
    created_at: datetime
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "input_cost": float(self.input_cost),
            "output_cost": float(self.output_cost),
            "total_cost": float(self.total_cost),
            "request_type": self.request_type,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata
        }


@dataclass
class BudgetStatus:
    """预算状态"""
    daily_budget: Decimal
    monthly_budget: Decimal
    daily_used: Decimal
    monthly_used: Decimal
    daily_remaining: Decimal
    monthly_remaining: Decimal
    daily_percent: float
    monthly_percent: float
    alert_level: BudgetAlertLevel

    def to_dict(self) -> dict[str, Any]:
        return {
            "daily_budget": float(self.daily_budget),
            "monthly_budget": float(self.monthly_budget),
            "daily_used": float(self.daily_used),
            "monthly_used": float(self.monthly_used),
            "daily_remaining": float(self.daily_remaining),
            "monthly_remaining": float(self.monthly_remaining),
            "daily_percent": self.daily_percent,
            "monthly_percent": self.monthly_percent,
            "alert_level": self.alert_level.value
        }


class CostManager:
    """
    成本管理器 - 预算控制与成本追踪

    使用示例：
        cost_mgr = CostManager()

        # 记录使用
        cost_mgr.record_usage(
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            user_id="user_001"
        )

        # 检查预算
        if cost_mgr.check_budget():
            # 继续调用AI
            pass
        else:
            # 预算超限，熔断
            raise Exception("预算超限")
    """

    # 模型单价（每1000 tokens，单位：美元）
    # 价格基于OpenAI官方定价，定期更新
    MODEL_PRICING = {
        # GPT-4系列
        "gpt-4": {"input": 0.03, "output": 0.06},
        "gpt-4-0314": {"input": 0.03, "output": 0.06},
        "gpt-4-0613": {"input": 0.03, "output": 0.06},
        "gpt-4-32k": {"input": 0.06, "output": 0.12},
        "gpt-4-turbo": {"input": 0.01, "output": 0.03},
        "gpt-4-turbo-preview": {"input": 0.01, "output": 0.03},
        "gpt-4-1106-preview": {"input": 0.01, "output": 0.03},
        "gpt-4-0125-preview": {"input": 0.01, "output": 0.03},
        "gpt-4o": {"input": 0.005, "output": 0.015},
        "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},

        # GPT-3.5系列
        "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
        "gpt-3.5-turbo-0125": {"input": 0.0005, "output": 0.0015},
        "gpt-3.5-turbo-1106": {"input": 0.001, "output": 0.002},
        "gpt-3.5-turbo-16k": {"input": 0.001, "output": 0.002},

        # 文本嵌入
        "text-embedding-ada-002": {"input": 0.0001, "output": 0},
        "text-embedding-3-small": {"input": 0.00002, "output": 0},
        "text-embedding-3-large": {"input": 0.00013, "output": 0},

        # 默认价格（当模型未找到时使用）
        "default": {"input": 0.01, "output": 0.03}
    }

    def __init__(
        self,
        daily_budget: float = 100.0,
        monthly_budget: float = 1000.0,
        db_config: dict | None = None
    ):
        """
        初始化成本管理器

        Args:
            daily_budget: 日预算（美元）
            monthly_budget: 月预算（美元）
            db_config: 数据库配置
        """
        self.daily_budget = Decimal(str(daily_budget))
        self.monthly_budget = Decimal(str(monthly_budget))
        self.db_config = db_config or self._get_default_db_config()

        self._lock = threading.Lock()
        self._alert_callbacks: list[callable] = []
        self._budget_exceeded_callbacks: list[callable] = []

        # 缓存统计
        self._stats_cache: dict[str, dict] = {}
        self._cache_ttl = 60  # 缓存60秒

        # 初始化数据库
        if POSTGRES_AVAILABLE:
            self._init_database()

        # 注册配置热加载监听
        self._register_config_listener()

        # 从配置文件加载预算设置
        self._load_budget_from_config()

        logger.info(f"[CostManager] 初始化完成 - 日预算: ${daily_budget}, 月预算: ${monthly_budget}")

    def _register_config_listener(self):
        """注册配置变更监听器，支持热加载"""
        try:
            from core.sync.event_bus import event_bus
            event_bus.subscribe("config_changed", self._on_config_changed)
            logger.debug("[CostManager] 已注册配置变更监听器")
        except ImportError:
            logger.debug("[CostManager] event_bus不可用，跳过配置监听")
        except Exception as e:
            logger.warning(f"[CostManager] 注册配置监听器失败: {e}")

    def _on_config_changed(self, event):
        """
        配置变更回调

        Args:
            event: 配置变更事件，包含变化的配置项
        """
        try:
            # 检查是否是成本相关配置变更
            config_key = event.get("key", "") if isinstance(event, dict) else ""

            # 如果变更的是成本配置，重新加载预算
            if config_key.startswith("cost.") or config_key == "":
                self._load_budget_from_config()

        except Exception as e:
            logger.warning(f"[CostManager] 处理配置变更失败: {e}")

    def _load_budget_from_config(self):
        """从配置文件加载预算设置"""
        try:
            from core.config import config

            # 读取成本配置
            daily = config.get("cost.budget.daily")
            monthly = config.get("cost.budget.monthly")

            if daily is not None or monthly is not None:
                with self._lock:
                    if daily is not None:
                        self.daily_budget = Decimal(str(daily))
                    if monthly is not None:
                        self.monthly_budget = Decimal(str(monthly))

                logger.info(
                    f"[CostManager] 从配置加载预算 - "
                    f"日预算: ${self.daily_budget}, 月预算: ${self.monthly_budget}"
                )
        except ImportError:
            pass  # 配置模块不可用，使用默认值
        except Exception as e:
            logger.warning(f"[CostManager] 从配置加载预算失败: {e}")

    def _get_default_db_config(self) -> dict:
        """获取默认数据库配置"""
        try:
            from core.config import config
            # 修复：多层回退兼容 local.yaml(database.postgresql.*) 和 global.yaml(postgresql.*)
            return {
                "host": config.get("database.postgresql.host") or config.get("postgresql.host", "localhost"),
                "port": config.get("database.postgresql.port") or config.get("postgresql.port", 5432),
                "dbname": config.get("database.postgresql.database") or config.get("postgresql.database", "siliconbase"),
                "user": config.get("database.postgresql.user") or config.get("postgresql.user", "postgres"),
                "password": config.get("database.postgresql.password") or config.get("postgresql.password", ""),
            }
        except ImportError:
            return {
                "host": "localhost",
                "port": 5432,
                "dbname": "siliconbase",
                "user": "postgres",
                "password": ""
            }

    def _get_db_connection(self):
        """获取数据库连接"""
        if not POSTGRES_AVAILABLE:
            return None
        try:
            return psycopg2.connect(**self.db_config)
        except Exception as e:
            logger.error(f"[CostManager] 数据库连接失败: {e}")
            return None

    def _init_database(self):
        """初始化数据库表"""
        conn = self._get_db_connection()
        if not conn:
            return

        try:
            with conn.cursor() as cur:
                # 创建token_usage表
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS token_usage (
                        id SERIAL PRIMARY KEY,
                        user_id VARCHAR(255) NOT NULL,
                        session_id VARCHAR(255),
                        model VARCHAR(100) NOT NULL,
                        input_tokens INTEGER NOT NULL DEFAULT 0,
                        output_tokens INTEGER NOT NULL DEFAULT 0,
                        total_tokens INTEGER NOT NULL DEFAULT 0,
                        input_cost DECIMAL(15, 6) NOT NULL DEFAULT 0,
                        output_cost DECIMAL(15, 6) NOT NULL DEFAULT 0,
                        total_cost DECIMAL(15, 6) NOT NULL DEFAULT 0,
                        request_type VARCHAR(50) DEFAULT 'chat',
                        metadata JSONB,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # 创建PostgreSQL兼容的索引
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_token_usage_user_id ON token_usage (user_id)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_token_usage_created_at ON token_usage (created_at)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_token_usage_model ON token_usage (model)
                """)

                # 创建cost_stats表（聚合统计）
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS cost_stats (
                        id SERIAL PRIMARY KEY,
                        user_id VARCHAR(255) NOT NULL,
                        stat_type VARCHAR(20) NOT NULL,  -- 'daily', 'monthly'
                        stat_date DATE NOT NULL,
                        model VARCHAR(100),
                        total_requests INTEGER DEFAULT 0,
                        total_input_tokens BIGINT DEFAULT 0,
                        total_output_tokens BIGINT DEFAULT 0,
                        total_tokens BIGINT DEFAULT 0,
                        total_cost DECIMAL(15, 6) DEFAULT 0,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(user_id, stat_type, stat_date, model)
                    )
                """)

                # 创建PostgreSQL兼容的索引
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_cost_stats_user_date ON cost_stats (user_id, stat_date)
                """)

                conn.commit()
                logger.info("[CostManager] 数据库表初始化完成")
        except Exception as e:
            logger.error(f"[CostManager] 数据库初始化失败: {e}")
        finally:
            conn.close()

    def get_model_pricing(self, model: str) -> dict[str, Decimal]:
        """
        获取模型定价

        Args:
            model: 模型名称

        Returns:
            定价字典 {"input": Decimal, "output": Decimal}
        """
        # 精确匹配
        if model in self.MODEL_PRICING:
            pricing = self.MODEL_PRICING[model]
        else:
            # 前缀匹配
            pricing = None
            for model_prefix, price in self.MODEL_PRICING.items():
                if model.startswith(model_prefix):
                    pricing = price
                    break

            # 使用默认价格
            if pricing is None:
                pricing = self.MODEL_PRICING["default"]
                logger.warning(f"[CostManager] 未找到模型 {model} 的定价，使用默认价格")

        return {
            "input": Decimal(str(pricing["input"])),
            "output": Decimal(str(pricing["output"]))
        }

    def calculate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int
    ) -> tuple[Decimal, Decimal, Decimal]:
        """
        计算成本

        Args:
            model: 模型名称
            input_tokens: 输入token数
            output_tokens: 输出token数

        Returns:
            (input_cost, output_cost, total_cost) 单位：美元
        """
        pricing = self.get_model_pricing(model)

        # 价格是按1000 tokens计算的
        input_cost = (Decimal(str(input_tokens)) / 1000) * pricing["input"]
        output_cost = (Decimal(str(output_tokens)) / 1000) * pricing["output"]
        total_cost = input_cost + output_cost

        # 保留6位小数
        input_cost = input_cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        output_cost = output_cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        total_cost = total_cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

        return input_cost, output_cost, total_cost

    def record_usage(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        user_id: str = "default",
        session_id: str | None = None,
        request_type: str = "chat",
        metadata: dict | None = None
    ) -> CostRecord | None:
        """
        记录Token使用

        Args:
            model: 模型名称
            input_tokens: 输入token数
            output_tokens: 输出token数
            user_id: 用户ID
            session_id: 会话ID
            request_type: 请求类型
            metadata: 额外元数据

        Returns:
            CostRecord对象，数据库不可用时返回None
        """
        total_tokens = input_tokens + output_tokens
        input_cost, output_cost, total_cost = self.calculate_cost(
            model, input_tokens, output_tokens
        )

        record = CostRecord(
            id=None,
            user_id=user_id,
            session_id=session_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            input_cost=input_cost,
            output_cost=output_cost,
            total_cost=total_cost,
            request_type=request_type,
            created_at=datetime.now(),
            metadata=metadata
        )

        # 保存到数据库
        if POSTGRES_AVAILABLE:
            self._save_record(record)
            self._update_stats(record)

        # 检查预算告警
        self._check_budget_alert(user_id)

        logger.debug(
            f"[CostManager] 记录使用 - 模型: {model}, "
            f"Tokens: {total_tokens}, 成本: ${total_cost}"
        )

        return record

    def record_from_token_result(
        self,
        token_result: TokenCountResult,
        user_id: str = "default",
        session_id: str | None = None,
        request_type: str = "chat",
        metadata: dict | None = None
    ) -> CostRecord | None:
        """
        从TokenCountResult记录使用

        Args:
            token_result: Token计数结果
            user_id: 用户ID
            session_id: 会话ID
            request_type: 请求类型
            metadata: 额外元数据

        Returns:
            CostRecord对象
        """
        return self.record_usage(
            model=token_result.model,
            input_tokens=token_result.input_tokens,
            output_tokens=token_result.output_tokens,
            user_id=user_id,
            session_id=session_id,
            request_type=request_type,
            metadata=metadata
        )

    def _save_record(self, record: CostRecord):
        """保存记录到数据库"""
        conn = self._get_db_connection()
        if not conn:
            return

        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO token_usage
                    (user_id, session_id, model, input_tokens, output_tokens, total_tokens,
                     input_cost, output_cost, total_cost, request_type, metadata, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    record.user_id, record.session_id, record.model,
                    record.input_tokens, record.output_tokens, record.total_tokens,
                    record.input_cost, record.output_cost, record.total_cost,
                    record.request_type, Json(record.metadata) if record.metadata else None,
                    record.created_at
                ))
                record.id = cur.fetchone()[0]
                conn.commit()
        except Exception as e:
            logger.error(f"[CostManager] 保存记录失败: {e}")
        finally:
            conn.close()

    def _update_stats(self, record: CostRecord):
        """更新统计表"""
        conn = self._get_db_connection()
        if not conn:
            return

        try:
            with conn.cursor() as cur:
                today = record.created_at.date()

                # 更新日统计
                cur.execute("""
                    INSERT INTO cost_stats
                    (user_id, stat_type, stat_date, model, total_requests,
                     total_input_tokens, total_output_tokens, total_tokens, total_cost)
                    VALUES (%s, 'daily', %s, %s, 1, %s, %s, %s, %s)
                    ON CONFLICT (user_id, stat_type, stat_date, model) DO UPDATE SET
                        total_requests = cost_stats.total_requests + 1,
                        total_input_tokens = cost_stats.total_input_tokens + %s,
                        total_output_tokens = cost_stats.total_output_tokens + %s,
                        total_tokens = cost_stats.total_tokens + %s,
                        total_cost = cost_stats.total_cost + %s,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    record.user_id, today, record.model,
                    record.input_tokens, record.output_tokens, record.total_tokens, record.total_cost,
                    record.input_tokens, record.output_tokens, record.total_tokens, record.total_cost
                ))

                # 更新月统计
                month_start = today.replace(day=1)
                cur.execute("""
                    INSERT INTO cost_stats
                    (user_id, stat_type, stat_date, model, total_requests,
                     total_input_tokens, total_output_tokens, total_tokens, total_cost)
                    VALUES (%s, 'monthly', %s, 'all', 1, %s, %s, %s, %s)
                    ON CONFLICT (user_id, stat_type, stat_date, model) DO UPDATE SET
                        total_requests = cost_stats.total_requests + 1,
                        total_input_tokens = cost_stats.total_input_tokens + %s,
                        total_output_tokens = cost_stats.total_output_tokens + %s,
                        total_tokens = cost_stats.total_tokens + %s,
                        total_cost = cost_stats.total_cost + %s,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    record.user_id, month_start,
                    record.input_tokens, record.output_tokens, record.total_tokens, record.total_cost,
                    record.input_tokens, record.output_tokens, record.total_tokens, record.total_cost
                ))

                conn.commit()
        except Exception as e:
            logger.error(f"[CostManager] 更新统计失败: {e}")
        finally:
            conn.close()

    def get_usage_stats(
        self,
        user_id: str = "default",
        start_date: datetime | None = None,
        end_date: datetime | None = None
    ) -> dict[str, Any]:
        """
        获取使用统计

        Args:
            user_id: 用户ID
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            统计字典
        """
        if not POSTGRES_AVAILABLE:
            return {"error": "数据库不可用"}

        conn = self._get_db_connection()
        if not conn:
            return {"error": "数据库连接失败"}

        if not end_date:
            end_date = datetime.now()
        if not start_date:
            start_date = end_date - timedelta(days=30)

        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 总统计
                cur.execute("""
                    SELECT
                        COUNT(*) as total_requests,
                        SUM(input_tokens) as total_input_tokens,
                        SUM(output_tokens) as total_output_tokens,
                        SUM(total_tokens) as total_tokens,
                        SUM(total_cost) as total_cost,
                        COUNT(DISTINCT model) as model_count
                    FROM token_usage
                    WHERE user_id = %s AND created_at BETWEEN %s AND %s
                """, (user_id, start_date, end_date))

                overall = dict(cur.fetchone())

                # 按模型统计
                cur.execute("""
                    SELECT
                        model,
                        COUNT(*) as requests,
                        SUM(total_tokens) as tokens,
                        SUM(total_cost) as cost
                    FROM token_usage
                    WHERE user_id = %s AND created_at BETWEEN %s AND %s
                    GROUP BY model
                    ORDER BY cost DESC
                """, (user_id, start_date, end_date))

                by_model = [dict(row) for row in cur.fetchall()]

                # 按日统计
                cur.execute("""
                    SELECT
                        DATE(created_at) as date,
                        COUNT(*) as requests,
                        SUM(total_cost) as cost
                    FROM token_usage
                    WHERE user_id = %s AND created_at BETWEEN %s AND %s
                    GROUP BY DATE(created_at)
                    ORDER BY date DESC
                    LIMIT 30
                """, (user_id, start_date, end_date))

                by_day = [dict(row) for row in cur.fetchall()]

                return {
                    "overall": overall,
                    "by_model": by_model,
                    "by_day": by_day,
                    "period": {
                        "start": start_date.isoformat(),
                        "end": end_date.isoformat()
                    }
                }
        except Exception as e:
            logger.error(f"[CostManager] 获取统计失败: {e}")
            return {"error": str(e)}
        finally:
            conn.close()

    def get_daily_cost(self, user_id: str = "default", date: datetime | None = None) -> Decimal:
        """获取指定日期的成本"""
        if not date:
            date = datetime.now()

        date_str = date.strftime("%Y-%m-%d")

        if not POSTGRES_AVAILABLE:
            return Decimal("0")

        conn = self._get_db_connection()
        if not conn:
            return Decimal("0")

        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COALESCE(SUM(total_cost), 0)
                    FROM token_usage
                    WHERE user_id = %s AND DATE(created_at) = %s
                """, (user_id, date_str))

                result = cur.fetchone()[0]
                return Decimal(str(result)) if result else Decimal("0")
        except Exception as e:
            logger.error(f"[CostManager] 获取日成本失败: {e}")
            return Decimal("0")
        finally:
            conn.close()

    def get_monthly_cost(self, user_id: str = "default", date: datetime | None = None) -> Decimal:
        """获取指定月份的成本"""
        if not date:
            date = datetime.now()

        month_start = date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if date.month == 12:
            month_end = date.replace(year=date.year + 1, month=1, day=1)
        else:
            month_end = date.replace(month=date.month + 1, day=1)

        if not POSTGRES_AVAILABLE:
            return Decimal("0")

        conn = self._get_db_connection()
        if not conn:
            return Decimal("0")

        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COALESCE(SUM(total_cost), 0)
                    FROM token_usage
                    WHERE user_id = %s AND created_at >= %s AND created_at < %s
                """, (user_id, month_start, month_end))

                result = cur.fetchone()[0]
                return Decimal(str(result)) if result else Decimal("0")
        except Exception as e:
            logger.error(f"[CostManager] 获取月成本失败: {e}")
            return Decimal("0")
        finally:
            conn.close()

    def check_budget(self, user_id: str = "default") -> bool:
        """
        检查预算是否超限

        Args:
            user_id: 用户ID

        Returns:
            True - 未超限，可以继续使用
            False - 已超限，应当熔断
        """
        daily_cost = self.get_daily_cost(user_id)
        monthly_cost = self.get_monthly_cost(user_id)

        # 检查日预算
        if daily_cost >= self.daily_budget:
            logger.warning(
                f"[CostManager] 日预算超限 - 用户: {user_id}, "
                f"已用: ${daily_cost}, 预算: ${self.daily_budget}"
            )
            self._trigger_budget_exceeded(user_id, "daily", daily_cost, self.daily_budget)
            return False

        # 检查月预算
        if monthly_cost >= self.monthly_budget:
            logger.warning(
                f"[CostManager] 月预算超限 - 用户: {user_id}, "
                f"已用: ${monthly_cost}, 预算: ${self.monthly_budget}"
            )
            self._trigger_budget_exceeded(user_id, "monthly", monthly_cost, self.monthly_budget)
            return False

        return True

    def get_budget_status(self, user_id: str = "default") -> BudgetStatus:
        """
        获取预算状态

        Args:
            user_id: 用户ID

        Returns:
            BudgetStatus对象
        """
        daily_used = self.get_daily_cost(user_id)
        monthly_used = self.get_monthly_cost(user_id)

        daily_remaining = max(Decimal("0"), self.daily_budget - daily_used)
        monthly_remaining = max(Decimal("0"), self.monthly_budget - monthly_used)

        daily_percent = float(daily_used / self.daily_budget * 100) if self.daily_budget > 0 else 0
        monthly_percent = float(monthly_used / self.monthly_budget * 100) if self.monthly_budget > 0 else 0

        # 确定告警级别
        max_percent = max(daily_percent, monthly_percent)
        if max_percent >= 100:
            alert_level = BudgetAlertLevel.EXCEEDED
        elif max_percent >= 95:
            alert_level = BudgetAlertLevel.CRITICAL
        elif max_percent >= 80:
            alert_level = BudgetAlertLevel.WARNING
        else:
            alert_level = BudgetAlertLevel.NORMAL

        return BudgetStatus(
            daily_budget=self.daily_budget,
            monthly_budget=self.monthly_budget,
            daily_used=daily_used,
            monthly_used=monthly_used,
            daily_remaining=daily_remaining,
            monthly_remaining=monthly_remaining,
            daily_percent=round(daily_percent, 2),
            monthly_percent=round(monthly_percent, 2),
            alert_level=alert_level
        )

    def _check_budget_alert(self, user_id: str):
        """检查并触发预算告警"""
        status = self.get_budget_status(user_id)

        if status.alert_level in (BudgetAlertLevel.WARNING, BudgetAlertLevel.CRITICAL):
            logger.warning(
                f"[CostManager] 预算告警 - 用户: {user_id}, "
                f"日使用: {status.daily_percent}%, 月使用: {status.monthly_percent}%"
            )
            self._trigger_alert(user_id, status)

    def _trigger_alert(self, user_id: str, status: BudgetStatus):
        """触发告警回调"""
        for callback in self._alert_callbacks:
            try:
                callback(user_id, status)
            except Exception as e:
                logger.error(f"[CostManager] 告警回调失败: {e}")

    def _trigger_budget_exceeded(self, user_id: str, budget_type: str, used: Decimal, budget: Decimal):
        """触发预算超限回调"""
        for callback in self._budget_exceeded_callbacks:
            try:
                callback(user_id, budget_type, used, budget)
            except Exception as e:
                logger.error(f"[CostManager] 预算超限回调失败: {e}")

    def on_budget_alert(self, callback: callable):
        """
        注册预算告警回调

        Args:
            callback: 回调函数，接收(user_id, budget_status)参数
        """
        self._alert_callbacks.append(callback)

    def on_budget_exceeded(self, callback: callable):
        """
        注册预算超限回调

        Args:
            callback: 回调函数，接收(user_id, budget_type, used, budget)参数
        """
        self._budget_exceeded_callbacks.append(callback)

    def get_cost_report(self, user_id: str = "default") -> dict[str, Any]:
        """
        生成成本报告

        Args:
            user_id: 用户ID

        Returns:
            成本报告字典
        """
        budget_status = self.get_budget_status(user_id)
        usage_stats = self.get_usage_stats(user_id)

        return {
            "budget": budget_status.to_dict(),
            "usage": usage_stats,
            "generated_at": datetime.now().isoformat()
        }

    def update_budget(self, daily: float | None = None, monthly: float | None = None):
        """
        更新预算设置

        Args:
            daily: 新日预算
            monthly: 新月预算
        """
        with self._lock:
            if daily is not None:
                self.daily_budget = Decimal(str(daily))
            if monthly is not None:
                self.monthly_budget = Decimal(str(monthly))

        logger.info(
            f"[CostManager] 预算更新 - 日预算: ${self.daily_budget}, "
            f"月预算: ${self.monthly_budget}"
        )


# 全局单例实例
cost_manager = CostManager()


# 便捷函数
def record_usage(
    model: str,
    input_tokens: int,
    output_tokens: int,
    user_id: str = "default",
    **kwargs
) -> CostRecord | None:
    """便捷函数：记录Token使用"""
    return cost_manager.record_usage(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        user_id=user_id,
        **kwargs
    )


def check_budget(user_id: str = "default") -> bool:
    """便捷函数：检查预算"""
    return cost_manager.check_budget(user_id)


def get_budget_status(user_id: str = "default") -> BudgetStatus:
    """便捷函数：获取预算状态"""
    return cost_manager.get_budget_status(user_id)


# =============================================================================
# 测试代码
# =============================================================================
if __name__ == "__main__":
    # 测试成本计算
    mgr = CostManager(daily_budget=10.0, monthly_budget=100.0)

    # 测试记录
    record = mgr.record_usage(
        model="gpt-4",
        input_tokens=1000,
        output_tokens=500,
        user_id="test_user"
    )

    if record:
        print("记录创建成功:")
        print(f"  输入Token: {record.input_tokens}")
        print(f"  输出Token: {record.output_tokens}")
        print(f"  总成本: ${record.total_cost}")

    # 测试预算状态
    status = mgr.get_budget_status("test_user")
    print("\n预算状态:")
    print(f"  日使用: ${status.daily_used} / ${status.daily_budget} ({status.daily_percent}%)")
    print(f"  月使用: ${status.monthly_used} / ${status.monthly_budget} ({status.monthly_percent}%)")
    print(f"  告警级别: {status.alert_level.value}")
