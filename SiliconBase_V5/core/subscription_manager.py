#!/usr/bin/env python3
"""
会员订阅管理器 - 商业化控制层
基于现有 UserSessionManager 扩展
"""

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path


class MembershipLevel(Enum):
    """会员等级"""
    FREE = 0       # 免费版
    BASIC = 1      # 基础版
    PRO = 2        # 专业版
    ENTERPRISE = 3 # 企业版


@dataclass
class Subscription:
    """订阅信息"""
    user_id: str
    level: MembershipLevel
    expires_at: datetime | None
    monthly_quota: int      # 月度调用次数
    monthly_used: int = 0
    features: dict[str, bool] = field(default_factory=dict)  # 功能开关


class SubscriptionManager:
    """
    会员订阅管理器 - 单例

    职责：
    1. 管理用户会员等级和过期时间
    2. 控制功能访问权限
    3. 统计用量配额
    4. 支持激活码兑换（离线模式）
    """

    _instance = None

    # 功能权限映射表
    FEATURE_REQUIREMENTS = {
        # 基础功能 - 免费
        "basic_chat": MembershipLevel.FREE,
        "voice_input": MembershipLevel.FREE,

        # 基础版功能
        "advanced_models": MembershipLevel.BASIC,
        "subagent": MembershipLevel.BASIC,
        "long_tasks": MembershipLevel.BASIC,

        # 专业版功能
        "cloud_sync": MembershipLevel.PRO,
        "mcp_tools": MembershipLevel.PRO,
        "custom_prompts": MembershipLevel.PRO,

        # 企业版功能
        "api_access": MembershipLevel.ENTERPRISE,
        "team_collaboration": MembershipLevel.ENTERPRISE,
    }

    # 各等级配额
    LEVEL_QUOTAS = {
        MembershipLevel.FREE: 100,        # 免费：100次/月
        MembershipLevel.BASIC: 1000,      # 基础：1000次/月
        MembershipLevel.PRO: 10000,       # 专业：10000次/月
        MembershipLevel.ENTERPRISE: -1,   # 企业：不限
    }

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._db_path = Path(__file__).parent.parent / "data" / "subscription.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_db()

    def _init_db(self):
        """初始化数据库"""
        with sqlite3.connect(self._db_path) as conn:
            # 订阅表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    user_id TEXT PRIMARY KEY,
                    level INTEGER DEFAULT 0,
                    expires_at TIMESTAMP,
                    monthly_quota INTEGER DEFAULT 100,
                    monthly_used INTEGER DEFAULT 0,
                    reset_date DATE,  -- 配额重置日期
                    features TEXT,    -- JSON格式功能开关
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 激活码表（离线模式使用）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS activation_codes (
                    code TEXT PRIMARY KEY,
                    level INTEGER NOT NULL,
                    days INTEGER NOT NULL,
                    is_used BOOLEAN DEFAULT 0,
                    used_by TEXT,
                    used_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 用量记录表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS usage_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    feature TEXT NOT NULL,
                    tokens_used INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.commit()

    def get_subscription(self, user_id: str) -> Subscription:
        """获取用户订阅信息"""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "SELECT level, expires_at, monthly_quota, monthly_used, reset_date, features "
                "FROM subscriptions WHERE user_id=?",
                (user_id,)
            )
            row = cursor.fetchone()

            if not row:
                # 新用户，创建免费订阅
                return self._create_free_subscription(user_id)

            level, expires_at, quota, used, reset_date, features_json = row

            # 检查是否需要重置月度配额
            if reset_date and datetime.now().date() > datetime.fromisoformat(reset_date).date():
                used = 0
                conn.execute(
                    "UPDATE subscriptions SET monthly_used=0, reset_date=? WHERE user_id=?",
                    (datetime.now().date().isoformat(), user_id)
                )
                conn.commit()

            # 检查是否过期
            if expires_at:
                expires = datetime.fromisoformat(expires_at)
                if datetime.now() > expires:
                    level = MembershipLevel.FREE.value  # 降级为免费

            features = json.loads(features_json) if features_json else {}

            return Subscription(
                user_id=user_id,
                level=MembershipLevel(level),
                expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
                monthly_quota=quota,
                monthly_used=used,
                features=features
            )

    def _create_free_subscription(self, user_id: str) -> Subscription:
        """创建免费订阅"""
        sub = Subscription(
            user_id=user_id,
            level=MembershipLevel.FREE,
            expires_at=None,
            monthly_quota=self.LEVEL_QUOTAS[MembershipLevel.FREE],
            monthly_used=0,
            features={}
        )

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT INTO subscriptions
                   (user_id, level, monthly_quota, reset_date, features)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, sub.level.value, sub.monthly_quota,
                 datetime.now().date().isoformat(), json.dumps(sub.features))
            )
            conn.commit()

        return sub

    def check_permission(self, user_id: str, feature: str) -> tuple[bool, str]:
        """
        检查用户是否有权限使用某功能

        Returns:
            (has_permission, reason)
        """
        sub = self.get_subscription(user_id)
        required = self.FEATURE_REQUIREMENTS.get(feature, MembershipLevel.FREE)

        if sub.level.value < required.value:
            level_names = ["免费版", "基础版", "专业版", "企业版"]
            return False, f"该功能需要 {level_names[required.value]}，请升级会员"

        if sub.expires_at and datetime.now() > sub.expires_at:
            return False, "会员已过期，请续费"

        if sub.monthly_quota > 0 and sub.monthly_used >= sub.monthly_quota:
            return False, "本月用量已用完，请等待下月重置或升级会员"

        return True, ""

    def consume_quota(self, user_id: str, feature: str, tokens: int = 0) -> bool:
        """消费一次调用配额"""
        sub = self.get_subscription(user_id)

        # 企业版不限量
        if sub.monthly_quota < 0:
            self._log_usage(user_id, feature, tokens)
            return True

        if sub.monthly_used >= sub.monthly_quota:
            return False

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "UPDATE subscriptions SET monthly_used = monthly_used + 1 WHERE user_id=?",
                (user_id,)
            )
            conn.commit()

        self._log_usage(user_id, feature, tokens)
        return True

    def _log_usage(self, user_id: str, feature: str, tokens: int):
        """记录用量"""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO usage_logs (user_id, feature, tokens_used) VALUES (?, ?, ?)",
                (user_id, feature, tokens)
            )
            conn.commit()

    def upgrade_subscription(self, user_id: str, level: MembershipLevel,
                            days: int, features: dict = None):
        """升级订阅（支付回调用）"""
        expires = datetime.now() + timedelta(days=days)
        quota = self.LEVEL_QUOTAS[level]

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO subscriptions
                   (user_id, level, expires_at, monthly_quota, reset_date, features)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, level.value, expires.isoformat(), quota,
                 datetime.now().date().isoformat(), json.dumps(features or {}))
            )
            conn.commit()

    # ==================== 激活码模式（离线使用） ====================

    def generate_activation_code(self, level: MembershipLevel, days: int) -> str:
        """生成激活码（管理员使用）"""
        import secrets
        code = secrets.token_hex(8).upper()  # 16位大写激活码

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO activation_codes (code, level, days) VALUES (?, ?, ?)",
                (code, level.value, days)
            )
            conn.commit()

        return code

    def redeem_code(self, user_id: str, code: str) -> tuple[bool, str]:
        """兑换激活码"""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "SELECT level, days, is_used FROM activation_codes WHERE code=?",
                (code,)
            )
            row = cursor.fetchone()

            if not row:
                return False, "激活码无效"

            level, days, is_used = row

            if is_used:
                return False, "激活码已被使用"

            # 升级用户订阅
            self.upgrade_subscription(user_id, MembershipLevel(level), days)

            # 标记激活码已使用
            conn.execute(
                "UPDATE activation_codes SET is_used=1, used_by=?, used_at=CURRENT_TIMESTAMP WHERE code=?",
                (user_id, code)
            )
            conn.commit()

        level_name = MembershipLevel(level).name
        return True, f"激活成功！已升级至 {level_name}，有效期 {days} 天"

    def get_usage_stats(self, user_id: str) -> dict:
        """获取用户用量统计"""
        sub = self.get_subscription(user_id)

        with sqlite3.connect(self._db_path) as conn:
            # 本月各功能使用统计
            cursor = conn.execute(
                """SELECT feature, COUNT(*) as count, SUM(tokens_used) as tokens
                   FROM usage_logs
                   WHERE user_id=? AND strftime('%Y-%m', created_at)=?
                   GROUP BY feature""",
                (user_id, datetime.now().strftime('%Y-%m'))
            )
            feature_stats = {row[0]: {"calls": row[1], "tokens": row[2]} for row in cursor.fetchall()}

        return {
            "level": sub.level.name,
            "expires_at": sub.expires_at.isoformat() if sub.expires_at else None,
            "quota": {
                "total": sub.monthly_quota,
                "used": sub.monthly_used,
                "remaining": sub.monthly_quota - sub.monthly_used if sub.monthly_quota > 0 else -1
            },
            "feature_usage": feature_stats
        }


# 全局实例
subscription_manager = SubscriptionManager()
