#!/usr/bin/env python3
"""
Schema-1A/B/C: PostgreSQL Table Creation Script
Creates three tables for Phase 1: experiences, software_info, monitoring_metrics
"""

# Database connection config
import os
import sys
from datetime import datetime

import psycopg2

DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'siliconbase',
    'user': 'postgres',
    'password': os.environ.get('POSTGRES_PASSWORD') or (_ for _ in ()).throw(RuntimeError(
        "[CreateTables] 错误: 未设置 POSTGRES_PASSWORD 环境变量。"
    ))
}

# SQL statements for table creation
SQL_CREATE_TABLES = """
-- 1. experiences table (replaces evolution.py SQLite)
CREATE TABLE IF NOT EXISTS experiences (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    task_type VARCHAR(100) NOT NULL,
    scene_fingerprint VARCHAR(255),
    content TEXT NOT NULL,
    experience_type VARCHAR(20) NOT NULL CHECK (experience_type IN ('success', 'failure')),
    steps JSONB,
    value_assessment JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. software_info table (replaces global_view.py SQLite)
CREATE TABLE IF NOT EXISTS software_info (
    id VARCHAR(255) PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    install_path TEXT,
    process_name VARCHAR(255),
    window_class VARCHAR(255),
    version VARCHAR(50),
    last_launch_time TIMESTAMP,
    launch_count INTEGER DEFAULT 0,
    auto_discovered BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. monitoring_metrics table (replaces monitoring.py SQLite)
CREATE TABLE IF NOT EXISTS monitoring_metrics (
    id SERIAL PRIMARY KEY,
    metric_name VARCHAR(100) NOT NULL,
    metric_value JSONB,
    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. hallucination_stats table (幻觉检测统计)
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
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5. hallucination_daily_summary table (幻觉检测每日汇总)
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
    calculated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
"""

# SQL statements for index creation
SQL_CREATE_INDEXES = """
-- experiences table indexes
CREATE INDEX IF NOT EXISTS idx_exp_user ON experiences(user_id);
CREATE INDEX IF NOT EXISTS idx_exp_type ON experiences(user_id, experience_type);
CREATE INDEX IF NOT EXISTS idx_exp_scene ON experiences(scene_fingerprint);

-- software_info table indexes
CREATE INDEX IF NOT EXISTS idx_sw_user ON software_info(user_id);
CREATE INDEX IF NOT EXISTS idx_sw_name ON software_info(user_id, name);

-- monitoring_metrics table indexes
CREATE INDEX IF NOT EXISTS idx_metric_name ON monitoring_metrics(metric_name);
CREATE INDEX IF NOT EXISTS idx_metric_time ON monitoring_metrics(recorded_at);

-- hallucination_stats table indexes
CREATE INDEX IF NOT EXISTS idx_halluc_session ON hallucination_stats(session_id);
CREATE INDEX IF NOT EXISTS idx_halluc_user ON hallucination_stats(user_id);
CREATE INDEX IF NOT EXISTS idx_halluc_timestamp ON hallucination_stats(timestamp);
CREATE INDEX IF NOT EXISTS idx_halluc_level ON hallucination_stats(hallucination_level);
CREATE INDEX IF NOT EXISTS idx_halluc_flagged ON hallucination_stats(flagged);

-- hallucination_daily_summary table indexes
CREATE INDEX IF NOT EXISTS idx_halluc_daily_date ON hallucination_daily_summary(date);
"""

def create_tables(conn):
    """Create all tables"""
    results = {}
    cursor = conn.cursor()

    try:
        print("=" * 60)
        print("Creating tables...")
        print("=" * 60)

        cursor.execute(SQL_CREATE_TABLES)
        conn.commit()

        # Verify tables were created
        tables = ['experiences', 'software_info', 'monitoring_metrics', 'hallucination_stats', 'hallucination_daily_summary']
        for table in tables:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = %s
                );
            """, (table,))
            exists = cursor.fetchone()[0]
            results[table] = 'OK' if exists else 'FAILED'
            print(f"Table {table}: {results[table]}")

        return results
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()

def create_indexes(conn):
    """Create all indexes"""
    results = {}
    cursor = conn.cursor()

    try:
        print("\n" + "=" * 60)
        print("Creating indexes...")
        print("=" * 60)

        cursor.execute(SQL_CREATE_INDEXES)
        conn.commit()

        # Verify indexes were created
        indexes = [
            'idx_exp_user', 'idx_exp_type', 'idx_exp_scene',
            'idx_sw_user', 'idx_sw_name',
            'idx_metric_name', 'idx_metric_time',
            'idx_halluc_session', 'idx_halluc_user', 'idx_halluc_timestamp',
            'idx_halluc_level', 'idx_halluc_flagged',
            'idx_halluc_daily_date'
        ]

        for index in indexes:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM pg_indexes
                    WHERE indexname = %s
                );
            """, (index,))
            exists = cursor.fetchone()[0]
            results[index] = 'OK' if exists else 'FAILED'
            print(f"Index {index}: {results[index]}")

        return results
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()

def describe_table(conn, table_name):
    """Get table schema information"""
    cursor = conn.cursor()

    try:
        # Get column info
        cursor.execute("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = %s
            ORDER BY ordinal_position;
        """, (table_name,))
        columns = cursor.fetchall()

        # Get constraint info
        cursor.execute("""
            SELECT conname, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = %s::regclass;
        """, (table_name,))
        constraints = cursor.fetchall()

        # Get index info
        cursor.execute("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename = %s;
        """, (table_name,))
        indexes = cursor.fetchall()

        return {
            'columns': columns,
            'constraints': constraints,
            'indexes': indexes
        }
    finally:
        cursor.close()

def main():
    print("=" * 60)
    print("Schema-1A/B/C: PostgreSQL Table Creation")
    print("Time: {}".format(datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    print("=" * 60)

    conn = None
    try:
        # Connect to database
        print("\nConnecting to database 'siliconbase'...")
        conn = psycopg2.connect(**DB_CONFIG)
        print("[OK] Database connected")

        # Create tables
        table_results = create_tables(conn)

        # Create indexes
        index_results = create_indexes(conn)

        # Show table schema
        print("\n" + "=" * 60)
        print("Table Schema Details")
        print("=" * 60)

        tables = ['experiences', 'software_info', 'monitoring_metrics', 'hallucination_stats', 'hallucination_daily_summary']
        for table in tables:
            schema = describe_table(conn, table)
            print(f"\n[Table: {table}]")
            print("-" * 40)
            print("Columns:")
            for col in schema['columns']:
                col_name, data_type, is_nullable, default = col
                nullable = "NULL" if is_nullable == "YES" else "NOT NULL"
                default_str = f" DEFAULT {default}" if default else ""
                print(f"  {col_name} {data_type}{nullable}{default_str}")

            print("\nConstraints:")
            for con in schema['constraints']:
                print(f"  {con[0]}: {con[1]}")

            print("\nIndexes:")
            for idx in schema['indexes']:
                print(f"  {idx[0]}")

        # Final report
        print("\n" + "=" * 60)
        print("Execution Report")
        print("=" * 60)

        table_ok = sum(1 for v in table_results.values() if v == 'OK')
        index_ok = sum(1 for v in index_results.values() if v == 'OK')
        all_success = table_ok == len(table_results) and index_ok == len(index_results)

        print(f"\nTables: {table_ok}/{len(table_results)} created successfully")
        print(f"Indexes: {index_ok}/{len(index_results)} created successfully")
        print("\nOverall Status: {}".format('ALL OK' if all_success else 'ERRORS FOUND'))

        if all_success:
            print("\nAll tables and indexes created successfully!")
        else:
            print("\nSome operations failed. Check logs above.")
            return 1

    except psycopg2.Error as e:
        print(f"\n[ERROR] Database error: {e}")
        return 1
    except Exception as e:
        print(f"\n[ERROR] Execution error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        if conn:
            conn.close()
            print("\nDatabase connection closed")

    return 0

if __name__ == '__main__':
    sys.exit(main())
