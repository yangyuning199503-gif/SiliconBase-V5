#!/usr/bin/env python3
"""
数据库初始化脚本
确保PostgreSQL数据库表结构完整
"""
import os
import sys
from pathlib import Path

import psycopg2

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

def get_db_connection():
    """获取数据库连接"""
    return psycopg2.connect(
        host=os.getenv('POSTGRES_HOST', 'localhost'),
        port=os.getenv('POSTGRES_PORT', '5432'),
        database=os.getenv('POSTGRES_DB', 'siliconbase'),
        user=os.getenv('POSTGRES_USER', 'postgres'),
        password=os.getenv('POSTGRES_PASSWORD') or (_ for _ in ()).throw(RuntimeError(
            "[InitDatabase] 错误: 未设置 POSTGRES_PASSWORD 环境变量。"
        ))
    )

def init_database():
    """初始化数据库表结构"""
    print("=" * 50)
    print("SiliconBase V5 - 数据库初始化")
    print("=" * 50)

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 检查memories表是否存在
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'memories'
            );
        """)

        memories_exists = cursor.fetchone()[0]

        if memories_exists:
            print("✅ memories 表已存在")

            # 检查索引
            cursor.execute("""
                SELECT indexname FROM pg_indexes
                WHERE tablename = 'memories';
            """)
            indexes = [row[0] for row in cursor.fetchall()]
            print(f"   索引: {', '.join(indexes)}")
        else:
            print("⚠️ memories 表不存在，正在创建...")
            create_memories_table(cursor)

        # 检查并创建其他必要的表
        check_and_create_tables(cursor)

        conn.commit()
        print("\n✅ 数据库初始化完成！")

    except psycopg2.Error as e:
        print(f"\n❌ 数据库错误: {e}")
        print("\n请检查:")
        print("1. PostgreSQL服务是否运行")
        print("2. 数据库连接参数是否正确")
        print("3. 数据库 'siliconbase' 是否存在")
        sys.exit(1)

    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

def create_memories_table(cursor):
    """创建memories表"""
    cursor.execute("""
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
    """)

    # 创建索引
    indexes = [
        ("idx_user_layer", "user_id, layer"),
        ("idx_user_type", "user_id, mem_type"),
        ("idx_scene", "scene"),
        ("idx_expire", "expire_at"),
        ("idx_rating", "rating DESC"),
    ]

    for idx_name, columns in indexes:
        cursor.execute(f"""
            CREATE INDEX IF NOT EXISTS {idx_name}
            ON memories ({columns});
        """)

    print("✅ memories 表创建完成")

def check_and_create_tables(cursor):
    """检查并创建其他必要的表"""

    tables = {
        'users': """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(64) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                role VARCHAR(20) DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP
            );
        """,
        'sessions': """
            CREATE TABLE IF NOT EXISTS sessions (
                id VARCHAR(64) PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                data JSONB DEFAULT '{}'::jsonb,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP
            );
        """,
        'tasks': """
            CREATE TABLE IF NOT EXISTS tasks (
                id VARCHAR(64) PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                title VARCHAR(255) NOT NULL,
                description TEXT,
                status VARCHAR(20) DEFAULT 'pending',
                priority INTEGER DEFAULT 2,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                metadata JSONB DEFAULT '{}'::jsonb
            );
        """,
        'executions': """
            CREATE TABLE IF NOT EXISTS executions (
                id SERIAL PRIMARY KEY,
                task_id VARCHAR(64),
                tool_id VARCHAR(64),
                params JSONB,
                result JSONB,
                success BOOLEAN,
                duration_ms INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """
    }

    for table_name, create_sql in tables.items():
        cursor.execute(f"""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = '{table_name}'
            );
        """)

        exists = cursor.fetchone()[0]

        if exists:
            print(f"✅ {table_name} 表已存在")
        else:
            cursor.execute(create_sql)
            print(f"✅ {table_name} 表创建完成")

if __name__ == '__main__':
    init_database()
    input("\n按Enter键退出...")
