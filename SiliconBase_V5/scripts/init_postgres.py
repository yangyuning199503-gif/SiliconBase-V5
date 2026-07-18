#!/usr/bin/env python3
"""
PostgreSQL 数据库初始化脚本
- 创建数据库
- 创建表结构
- 验证连接
"""
import sys

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT


def init_postgres():
    """初始化 PostgreSQL 数据库"""

    # 连接配置
    import os
    password = os.environ.get('POSTGRES_PASSWORD', '')
    if not password:
        raise RuntimeError(
            "[InitPostgres] 错误: 未设置 POSTGRES_PASSWORD 环境变量。"
        )
    config = {
        'host': 'localhost',
        'port': 5432,
        'user': 'postgres',
        'password': password
    }

    try:
        # 1. 连接到默认 postgres 数据库
        print("[1/4] 正在连接 PostgreSQL...")
        conn = psycopg2.connect(**config, database='postgres')
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()

        # 2. 创建数据库
        print("[2/4] 正在创建数据库 siliconbase...")
        cur.execute("DROP DATABASE IF EXISTS siliconbase;")
        cur.execute("CREATE DATABASE siliconbase ENCODING='UTF8';")
        cur.close()
        conn.close()

        # 3. 连接到新数据库并创建表
        print("[3/4] 正在创建表结构...")
        conn = psycopg2.connect(**config, database='siliconbase')
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id VARCHAR(64) PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                layer VARCHAR(20) NOT NULL,
                mem_type VARCHAR(50) NOT NULL,
                content TEXT NOT NULL,
                scene VARCHAR(255),
                rating INTEGER DEFAULT 0,
                value_assessment JSONB DEFAULT '{\"emotional_temperature\":3,\"ethical_safety\":3,\"self_growth\":3,\"execution_effectiveness\":3,\"sustainability\":3,\"inspiration_innovation\":3,\"overall\":3.0,\"grade\":\"C\"}',
                context JSONB,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                expire_at TIMESTAMP WITH TIME ZONE,
                compressed INTEGER DEFAULT 0,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                source VARCHAR(20) DEFAULT 'system',
                creator VARCHAR(20) DEFAULT 'system'
            );

            CREATE INDEX IF NOT EXISTS idx_user_layer ON memories(user_id, layer);
            CREATE INDEX IF NOT EXISTS idx_user_type ON memories(user_id, mem_type);
            CREATE INDEX IF NOT EXISTS idx_scene ON memories(scene);
            CREATE INDEX IF NOT EXISTS idx_expire ON memories(expire_at);
            CREATE INDEX IF NOT EXISTS idx_rating ON memories(rating);
        """)

        conn.commit()

        # 4. 验证
        print("[4/4] 验证安装...")
        cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';")
        table_count = cur.fetchone()[0]

        cur.close()
        conn.close()

        print("\n" + "="*50)
        print("✅ PostgreSQL 数据库初始化成功！")
        print("="*50)
        print("数据库名: siliconbase")
        print("用户名: postgres")
        print("密码: ******** (从环境变量读取)")
        print("主机: localhost")
        print("端口: 5432")
        print(f"表数量: {table_count}")
        print("="*50)

        return True

    except psycopg2.Error as e:
        print(f"\n❌ 错误: {e}")
        print("\n请确认:")
        print("1. PostgreSQL 服务是否已启动")
        print("2. 用户名密码是否正确")
        print("3. 端口 5432 是否被占用")
        return False

if __name__ == "__main__":
    success = init_postgres()
    sys.exit(0 if success else 1)
