#!/usr/bin/env python3
"""
成本追踪模块数据库初始化脚本
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
创建表：
  - token_usage: Token使用明细表
  - cost_stats: 成本统计聚合表

使用方法：
  python scripts/init_cost_tables.py

环境变量：
  DB_HOST: 数据库主机（默认：localhost）
  DB_PORT: 数据库端口（默认：5432）
  DB_NAME: 数据库名（默认：siliconbase）
  DB_USER: 数据库用户（默认：postgres）
  DB_PASSWORD: 数据库密码
"""

import logging
import os
import sys

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# SQL语句
CREATE_TOKEN_USAGE_TABLE = """
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
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_token_usage_user_id ON token_usage(user_id);
CREATE INDEX IF NOT EXISTS idx_token_usage_created_at ON token_usage(created_at);
CREATE INDEX IF NOT EXISTS idx_token_usage_model ON token_usage(model);
CREATE INDEX IF NOT EXISTS idx_token_usage_user_created ON token_usage(user_id, created_at);
"""

CREATE_COST_STATS_TABLE = """
CREATE TABLE IF NOT EXISTS cost_stats (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    stat_type VARCHAR(20) NOT NULL,
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
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_cost_stats_user_date ON cost_stats(user_id, stat_date);
CREATE INDEX IF NOT EXISTS idx_cost_stats_type_date ON cost_stats(stat_type, stat_date);
"""


def get_db_config() -> dict:
    """获取数据库配置"""
    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "5432")),
        "dbname": os.getenv("DB_NAME", "siliconbase"),
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD", ""),
    }


def init_database():
    """初始化数据库表"""
    try:
        import psycopg2
        from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
    except ImportError:
        logger.error("错误：未安装psycopg2，请运行: pip install psycopg2-binary")
        return False

    config = get_db_config()

    try:
        logger.info(f"连接到数据库: {config['host']}:{config['port']}/{config['dbname']}")
        conn = psycopg2.connect(**config)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)

        with conn.cursor() as cur:
            # 创建token_usage表
            logger.info("创建 token_usage 表...")
            cur.execute(CREATE_TOKEN_USAGE_TABLE)
            logger.info("✓ token_usage 表创建成功")

            # 创建cost_stats表
            logger.info("创建 cost_stats 表...")
            cur.execute(CREATE_COST_STATS_TABLE)
            logger.info("✓ cost_stats 表创建成功")

        conn.close()
        logger.info("数据库初始化完成！")
        return True

    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")
        return False


def verify_tables():
    """验证表是否创建成功"""
    try:
        import psycopg2
    except ImportError:
        return False

    config = get_db_config()

    try:
        conn = psycopg2.connect(**config)
        with conn.cursor() as cur:
            # 检查表是否存在
            cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name IN ('token_usage', 'cost_stats')
            """)
            tables = [row[0] for row in cur.fetchall()]

            logger.info(f"已创建的表: {', '.join(tables)}")

            # 检查索引
            for table in ['token_usage', 'cost_stats']:
                cur.execute("""
                    SELECT indexname
                    FROM pg_indexes
                    WHERE tablename = %s
                """, (table,))
                indexes = [row[0] for row in cur.fetchall()]
                logger.info(f"{table} 表索引: {', '.join(indexes)}")

        conn.close()
        return True
    except Exception as e:
        logger.error(f"验证表失败: {e}")
        return False


def insert_sample_data():
    """插入示例数据"""
    try:
        import psycopg2
    except ImportError:
        return False

    config = get_db_config()

    try:
        conn = psycopg2.connect(**config)
        with conn.cursor() as cur:
            # 插入示例使用记录
            cur.execute("""
                INSERT INTO token_usage
                (user_id, session_id, model, input_tokens, output_tokens, total_tokens,
                 input_cost, output_cost, total_cost, request_type, metadata)
                VALUES
                ('test_user', 'test_session', 'gpt-4', 1000, 500, 1500,
                 0.03, 0.03, 0.06, 'chat', '{"test": true}')
            """)

            conn.commit()
            logger.info("✓ 示例数据插入成功")

        conn.close()
        return True
    except Exception as e:
        logger.error(f"插入示例数据失败: {e}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("SiliconBase V5 Token成本追踪模块数据库初始化")
    print("=" * 60)

    # 初始化数据库
    if init_database():
        print("\n验证表结构...")
        verify_tables()

        # 询问是否插入示例数据
        response = input("\n是否插入示例数据? (y/n): ").lower()
        if response == 'y':
            insert_sample_data()

        print("\n✓ 初始化完成！")
    else:
        print("\n✗ 初始化失败，请检查数据库配置")
        sys.exit(1)
