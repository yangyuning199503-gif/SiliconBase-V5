#!/usr/bin/env python3
"""
PostgreSQL 连接池基础设施
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
从 core.memory.memory 提取的数据库连接池模块。

提供：
  - PostgresConnectionPool: 全局单例连接池
  - safe_return_connection: 防御性连接归还
  - init_postgres_tables: 表结构初始化

P0-基础设施迁移 (2026-05-09)
"""

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# psycopg2 导入与可用性检测
# ═══════════════════════════════════════════════════════════════════

try:
    import psycopg2
    from psycopg2 import pool
    from psycopg2.extras import Json, RealDictCursor
    POSTGRES_AVAILABLE = True
    logger.debug("[DB] psycopg2 imported successfully")
except ImportError:
    psycopg2 = None
    pool = None
    RealDictCursor = dict
    def Json(x):
        return x
    POSTGRES_AVAILABLE = False
    logger.warning("[DB] psycopg2 not available")


# ═══════════════════════════════════════════════════════════════════
# 企业级 PostgreSQL 配置验证
# ═══════════════════════════════════════════════════════════════════

def _validate_enterprise_pg_config():
    """
    验证企业级PostgreSQL配置

    企业级要求：
    - 必须配置环境变量
    - 禁止硬编码默认值
    - 无配置时明确报错

    Returns:
        tuple: (host, port, db, user, password)

    Raises:
        RuntimeError: 未配置PostgreSQL时抛出
    """
    pg_url = os.getenv('SILICONBASE_PG_URL')
    pg_url_password = os.getenv('SILICONBASE_PG_PASSWORD')

    pg_host = os.getenv('POSTGRES_HOST')
    pg_port_str = os.getenv('POSTGRES_PORT')
    pg_db = os.getenv('POSTGRES_DB')
    pg_user = os.getenv('POSTGRES_USER')
    pg_password = os.getenv('POSTGRES_PASSWORD')

    has_new_format = pg_url and pg_url_password
    has_old_format = pg_host and pg_db and pg_user and pg_password

    if not (has_new_format or has_old_format):
        logger.error("=" * 70)
        logger.error("[Enterprise] ████████████████████████████████████████████████████")
        logger.error("[Enterprise] ██  企业级部署错误：未配置PostgreSQL数据库")
        logger.error("[Enterprise] ████████████████████████████████████████████████████")
        logger.error("[Enterprise]")
        logger.error("[Enterprise] 原因：企业级部署必须使用PostgreSQL数据库")
        logger.error("[Enterprise]       禁止使用SQLite（GPL许可证风险）")
        logger.error("[Enterprise]")
        logger.error("[Enterprise] 解决方案：请设置以下环境变量之一：")
        logger.error("[Enterprise]")
        logger.error("[Enterprise] 方式1（推荐）- 使用连接URL：")
        logger.error("[Enterprise]   SILICONBASE_PG_URL=postgresql://user:password@host:5432/dbname")
        logger.error("[Enterprise]   SILICONBASE_PG_PASSWORD=your_password")
        logger.error("[Enterprise]")
        logger.error("[Enterprise] 方式2 - 使用独立配置项：")
        logger.error("[Enterprise]   POSTGRES_HOST=localhost")
        logger.error("[Enterprise]   POSTGRES_PORT=5432")
        logger.error("[Enterprise]   POSTGRES_DB=siliconbase")
        logger.error("[Enterprise]   POSTGRES_USER=postgres")
        logger.error("[Enterprise]   POSTGRES_PASSWORD=your_password")
        logger.error("[Enterprise]")
        logger.error("[Enterprise] 参考模板：.env.enterprise.template")
        logger.error("=" * 70)

        raise RuntimeError(
            "[Enterprise] 企业级部署必须配置PostgreSQL数据库。\n"
            "SQLite因GPL许可证风险被禁止。\n"
            "请配置环境变量：SILICONBASE_PG_URL, SILICONBASE_PG_PASSWORD\n"
            "或：POSTGRES_HOST, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD\n"
            "参考模板：.env.enterprise.template"
        )

    if has_new_format:
        logger.info("[Enterprise] 使用PostgreSQL URL格式配置")
        try:
            from urllib.parse import urlparse
            parsed = urlparse(pg_url)

            host = parsed.hostname or 'localhost'
            port = parsed.port or 5432
            db = parsed.path.lstrip('/') if parsed.path else 'siliconbase'
            user = parsed.username or 'postgres'
            password = pg_url_password

            logger.info(f"[Enterprise] URL解析成功: host={host}, port={port}, db={db}, user={user}")
            return host, port, db, user, password
        except Exception as e:
            logger.error(f"[Enterprise] URL解析失败: {e}")
            raise RuntimeError(
                f"[Enterprise] PostgreSQL URL解析失败: {e}\n"
                f"请检查 SILICONBASE_PG_URL 格式是否正确\n"
                f"正确格式: postgresql://user:password@host:port/database"
            ) from e

    logger.info("[Enterprise] 使用PostgreSQL独立配置项")
    return pg_host, int(pg_port_str or '5432'), pg_db, pg_user, pg_password


# 验证并获取PostgreSQL配置
_enterprise_pg_config = _validate_enterprise_pg_config()

POSTGRES_HOST = _enterprise_pg_config[0]
POSTGRES_PORT = _enterprise_pg_config[1]
POSTGRES_DB = _enterprise_pg_config[2]
POSTGRES_USER = _enterprise_pg_config[3]
POSTGRES_PASSWORD = _enterprise_pg_config[4]

POSTGRES_POOL_MIN = int(os.getenv('POSTGRES_POOL_MIN', '1'))
POSTGRES_POOL_MAX = int(os.getenv('POSTGRES_POOL_MAX', '20'))

if not POSTGRES_AVAILABLE:
    logger.error("[Enterprise] PostgreSQL驱动不可用（psycopg2未安装）")
    raise RuntimeError(
        "[Enterprise] 企业级部署必须使用PostgreSQL，但psycopg2不可用。 "
        "请安装: pip install psycopg2-binary"
    )

STORAGE_MODE = "postgres"
logger.info("[Enterprise] PostgreSQL存储模式已启用（企业级合规）")


# ═══════════════════════════════════════════════════════════════════
# PostgresConnectionPool 全局单例
# ═══════════════════════════════════════════════════════════════════

class PostgresConnectionPool:
    """PostgreSQL连接池 - 全局单例"""

    _instance = None
    _lock = threading.Lock()
    _pool = None

    @classmethod
    def get_pool(cls, min_conn=None, max_conn=None):
        """获取连接池（单例）"""
        if not POSTGRES_AVAILABLE or psycopg2 is None:
            logger.error("[Enterprise] PostgreSQL模块 psycopg2 未安装")
            raise RuntimeError(
                "[Enterprise] 企业级部署必须使用PostgreSQL。"
                "请安装: pip install psycopg2-binary"
            )

        if cls._pool is None:
            with cls._lock:
                if cls._pool is None:
                    min_conn = min_conn if min_conn is not None else POSTGRES_POOL_MIN
                    max_conn = max_conn if max_conn is not None else POSTGRES_POOL_MAX
                    try:
                        cls._pool = pool.SimpleConnectionPool(
                            min_conn, max_conn,
                            host=POSTGRES_HOST,
                            port=POSTGRES_PORT,
                            database=POSTGRES_DB,
                            user=POSTGRES_USER,
                            password=POSTGRES_PASSWORD
                        )
                        logger.info(f"[PostgresPool] PostgreSQL连接池初始化成功 (min={min_conn}, max={max_conn})")
                    except Exception as e:
                        logger.error(f"[PostgresPool] 连接池初始化失败: {e}")
                        raise
        return cls._pool

    @classmethod
    def reconfigure_pool(cls, min_conn: int, max_conn: int):
        """重新配置连接池大小"""
        with cls._lock:
            try:
                if cls._pool:
                    cls._pool.closeall()
                    cls._pool = None
                    logger.info("[PostgresPool] 旧连接池已关闭")

                cls._pool = pool.SimpleConnectionPool(
                    min_conn, max_conn,
                    host=POSTGRES_HOST,
                    port=POSTGRES_PORT,
                    database=POSTGRES_DB,
                    user=POSTGRES_USER,
                    password=POSTGRES_PASSWORD
                )
                logger.info(f"[PostgresPool] 连接池重新配置成功 (min={min_conn}, max={max_conn})")
                return True
            except Exception as e:
                logger.error(f"[PostgresPool] 连接池重新配置失败: {e}")
                return False

    @classmethod
    def get_pool_stats(cls) -> dict:
        """获取连接池统计信息"""
        return {
            "initialized": cls._pool is not None,
            "config": {
                "min_conn": POSTGRES_POOL_MIN,
                "max_conn": POSTGRES_POOL_MAX,
                "host": POSTGRES_HOST,
                "port": POSTGRES_PORT,
                "database": POSTGRES_DB
            }
        }

    @classmethod
    def get_connection(cls, timeout: int = 10):
        """
        获取连接（带超时保护）

        Args:
            timeout: 获取连接的超时时间（秒），默认10秒

        Returns:
            数据库连接

        Raises:
            RuntimeError: 连接池耗尽且超时
        """
        start_time = time.time()
        last_error = None

        while time.time() - start_time < timeout:
            try:
                pool_instance = cls.get_pool()
                conn = pool_instance.getconn()
                if conn:
                    return conn
            except Exception as e:
                last_error = e
                elapsed = time.time() - start_time
                if elapsed >= timeout:
                    break

                error_msg = str(e).lower()
                if any(x in error_msg for x in ["pool", "exhausted", "too many clients", "connection", "limited"]):
                    logger.warning(f"[PostgresPool] 连接池暂时耗尽，等待重试... ({int(elapsed)}s/{timeout}s): {e}")
                    time.sleep(0.5)
                    continue
                raise

        error_msg = f"[PostgresPool] 获取连接超时({timeout}秒): 连接池可能已耗尽"
        logger.error(error_msg)
        if last_error:
            raise RuntimeError(f"{error_msg}: {last_error}")
        raise RuntimeError(error_msg)

    @classmethod
    def return_connection(cls, conn):
        """归还连接 - P0修复: 增强空指针保护 + 内存泄漏修复: 连接有效性检查"""
        if conn is None:
            return
        if cls is None:
            return
        if not hasattr(cls, '_pool'):
            return
        if cls._pool is None:
            return
        try:
            if (hasattr(conn, 'closed') and not conn.closed) or not hasattr(conn, 'closed'):
                cls._pool.putconn(conn)
            else:
                logger.warning("[PostgresPool] 尝试归还已关闭的连接，跳过")
        except Exception as e:
            logger.debug(f"[PostgresPool] 归还连接异常: {e}")
            try:
                conn.close()
            except Exception as e:
                logger.error(f"[SILENT_FAILURE_BLOCKED] 强制关闭损坏连接失败: {e}")

    @classmethod
    def close_all(cls):
        """关闭所有连接 - CORE-001修复: 添加异常处理和关闭状态标记"""
        try:
            if cls._pool:
                cls._pool.closeall()
                logger.info("[PostgresPool] 连接池已关闭")
        except Exception as e:
            logger.error(f"[PostgresPool] 关闭连接池失败: {e}")
            raise
        finally:
            cls._pool = None
            cls._closed = True


# ═══════════════════════════════════════════════════════════════════
# P0修复: 安全连接归还辅助函数（防御空指针）
# ═══════════════════════════════════════════════════════════════════

def safe_return_connection(conn) -> None:
    """
    安全归还连接到连接池 - P0修复

    防御性包装函数，确保即使在极端情况下也不会引发空指针异常。
    用于所有finally块中的连接归还。

    Args:
        conn: 数据库连接对象，可能为None
    """
    if conn is None:
        return

    try:
        if PostgresConnectionPool is None:
            return
        PostgresConnectionPool.return_connection(conn)
    except Exception as e:
        logger.debug(f"[safe_return_connection] 归还连接失败: {e}")


# ═══════════════════════════════════════════════════════════════════
# PostgreSQL 表结构初始化
# ═══════════════════════════════════════════════════════════════════

def init_postgres_tables():
    """初始化PostgreSQL表结构"""
    if not POSTGRES_AVAILABLE or psycopg2 is None:
        logger.debug("[PostgresInit] PostgreSQL不可用，跳过表初始化")
        return

    conn = None
    try:
        conn = PostgresConnectionPool.get_connection()
        with conn.cursor() as c:
            c.execute('''
                CREATE TABLE IF NOT EXISTS memories (
                    id VARCHAR(64) PRIMARY KEY,
                    user_id VARCHAR(64) NOT NULL,
                    layer VARCHAR(50) NOT NULL,
                    mem_type VARCHAR(50) NOT NULL,
                    content TEXT NOT NULL,
                    scene VARCHAR(255),
                    rating INTEGER DEFAULT 0,
                    value_assessment JSONB DEFAULT '{"emotional_temperature":3,"ethical_safety":3,"self_growth":3,"execution_effectiveness":3,"sustainability":3,"inspiration_innovation":3,"overall":3.0,"grade":"C"}',
                    context JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    expire_at TIMESTAMP WITH TIME ZONE,
                    compressed INTEGER DEFAULT 0,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    source VARCHAR(100) DEFAULT 'system',
                    creator VARCHAR(100) DEFAULT 'system'
                )
            ''')

            try:
                c.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS source VARCHAR(100) DEFAULT 'system'")
                c.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS creator VARCHAR(100) DEFAULT 'system'")
            except Exception as e:
                logger.debug(f"[PostgresInit] 添加字段可能已存在: {e}")

            c.execute('CREATE INDEX IF NOT EXISTS idx_user_layer ON memories(user_id, layer)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_user_type ON memories(user_id, mem_type)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_scene ON memories(scene)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_expire ON memories(expire_at)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_rating ON memories(rating)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_user_created ON memories(user_id, created_at)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_source ON memories(source)')

            c.execute('CREATE INDEX IF NOT EXISTS idx_value_assessment ON memories USING GIN (value_assessment)')

            c.execute('''
                CREATE TABLE IF NOT EXISTS memory_associations (
                    id SERIAL PRIMARY KEY,
                    source_mem_id VARCHAR(64) NOT NULL,
                    target_mem_id VARCHAR(64) NOT NULL,
                    user_id VARCHAR(64) NOT NULL,
                    relation_type VARCHAR(50) NOT NULL,
                    relation_score FLOAT DEFAULT 0.0,
                    relation_data JSONB DEFAULT '{}',
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_mem_id, target_mem_id, relation_type)
                )
            ''')
            c.execute('CREATE INDEX IF NOT EXISTS idx_assoc_source ON memory_associations(source_mem_id)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_assoc_target ON memory_associations(target_mem_id)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_assoc_user ON memory_associations(user_id)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_assoc_type_score ON memory_associations(relation_type, relation_score)')

            c.execute('''
                CREATE TABLE IF NOT EXISTS vital_signs_history (
                    id SERIAL PRIMARY KEY,
                    user_id VARCHAR(64) NOT NULL,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    energy FLOAT DEFAULT 5.0,
                    curiosity FLOAT DEFAULT 5.0,
                    satisfaction FLOAT DEFAULT 5.0,
                    stress FLOAT DEFAULT 0.0,
                    mood VARCHAR(50) DEFAULT '平静',
                    is_hibernating BOOLEAN DEFAULT FALSE,
                    context JSONB DEFAULT '{}'
                )
            ''')
            c.execute('CREATE INDEX IF NOT EXISTS idx_vital_user_time ON vital_signs_history(user_id, timestamp DESC)')

            c.execute('''
                CREATE TABLE IF NOT EXISTS self_actions (
                    id SERIAL PRIMARY KEY,
                    user_id VARCHAR(64) NOT NULL,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    action_type VARCHAR(50) NOT NULL,
                    action_content TEXT,
                    energy_cost FLOAT DEFAULT 0.0,
                    satisfaction_gain FLOAT DEFAULT 0.0,
                    status VARCHAR(20) DEFAULT 'pending',
                    context JSONB DEFAULT '{}'
                )
            ''')
            c.execute('CREATE INDEX IF NOT EXISTS idx_self_action_user ON self_actions(user_id, timestamp DESC)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_self_action_type ON self_actions(action_type)')

            # 幻觉统计表（原在 core/safety/hallucination_stats.py 但未自动执行）
            c.execute('''
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
                    detected_claims TEXT,
                    uncertain_phrases TEXT,
                    verification_notes TEXT,
                    knowledge_matches TEXT,
                    context_summary TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            c.execute('CREATE INDEX IF NOT EXISTS idx_halluc_session ON hallucination_stats(session_id)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_halluc_user ON hallucination_stats(user_id)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_halluc_timestamp ON hallucination_stats(timestamp)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_halluc_level ON hallucination_stats(hallucination_level)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_halluc_flagged ON hallucination_stats(flagged)')

            c.execute('''
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
                )
            ''')

            conn.commit()
            logger.info("[PostgresInit] 表结构初始化完成（含记忆关联表、生命体征表、自发行动表、幻觉统计表）")
    except Exception as e:
        logger.error(f"[PostgresInit] 表初始化失败: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            safe_return_connection(conn)


# ═══════════════════════════════════════════════════════════════════════════════
# 便捷函数（供其他模块直接使用）
# ═══════════════════════════════════════════════════════════════════════════════

def get_db_connection():
    """获取原始 psycopg2 数据库连接（非连接池）。"""
    if not POSTGRES_AVAILABLE or psycopg2 is None:
        raise RuntimeError(
            "[Enterprise] 企业级部署必须使用PostgreSQL，但psycopg2不可用。 "
            "请安装: pip install psycopg2-binary"
        )
    return psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
    )


def get_connection_pool():
    """获取 PostgresConnectionPool 实例（兼容旧接口）。"""
    return PostgresConnectionPool.get_pool()
