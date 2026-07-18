#!/usr/bin/env python3
"""
Phase 1 Week 1 - Task 1: 创建Session管理相关数据库表

功能:
1. 执行SQL创建脚本
2. 在现有PostgreSQL连接中创建表
3. 验证表结构正确性
4. 输出创建成功的确认信息

异常处理:
- 创建失败记录ERROR日志
- 不允许静默失败
- 表已存在时妥善处理
"""

import sys
from pathlib import Path

import psycopg2

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.db.connection_pool import get_db_connection
from core.logger import logger


class SessionTableCreator:
    """Session表创建器"""

    def __init__(self):
        self.sql_file = Path(__file__).parent / "create_session_tables.sql"
        self.tables = ['sessions', 'session_messages']
        self.required_columns = {
            'sessions': [
                'id', 'user_id', 'title', 'mode', 'status',
                'created_at', 'updated_at', 'last_message_at',
                'message_count', 'metadata'
            ],
            'session_messages': [
                'id', 'session_id', 'role', 'content', 'content_type',
                'created_at', 'memory_id', 'tool_calls', 'thinking', 'metadata'
            ]
        }

    def read_sql_script(self) -> str:
        """读取SQL脚本文件"""
        try:
            with open(self.sql_file, encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            logger.error(f"[SessionTableCreator] SQL脚本文件不存在: {self.sql_file}")
            raise
        except Exception as e:
            logger.error(f"[SessionTableCreator] 读取SQL脚本失败: {e}")
            raise

    def execute_sql(self, sql_content: str) -> tuple[bool, str]:
        """
        执行SQL脚本

        Returns:
            (是否成功, 错误信息)
        """
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()

                # 分割SQL语句并执行
                # 注意: 这里我们执行整个脚本，因为psycopg2支持多语句执行
                cursor.execute(sql_content)
                conn.commit()
                cursor.close()

                logger.info("[SessionTableCreator] SQL脚本执行成功")
                return True, ""

        except psycopg2.Error as e:
            error_msg = f"数据库错误: {e}"
            logger.error(f"[SessionTableCreator] {error_msg}")
            return False, error_msg
        except Exception as e:
            error_msg = f"执行异常: {e}"
            logger.error(f"[SessionTableCreator] {error_msg}")
            return False, error_msg

    def check_tables_exist(self) -> dict:
        """
        检查表是否已存在

        Returns:
            字典 {表名: 是否存在}
        """
        result = {}
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                for table_name in self.tables:
                    cursor.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'public'
                            AND table_name = %s
                        );
                    """, (table_name,))
                    exists = cursor.fetchone()[0]
                    result[table_name] = exists
                cursor.close()
        except Exception as e:
            logger.error(f"[SessionTableCreator] 检查表存在性失败: {e}")
            # 如果检查失败，假设表都不存在
            result = dict.fromkeys(self.tables, False)
        return result

    def verify_table_structure(self) -> tuple[bool, list[str]]:
        """
        验证表结构正确性

        Returns:
            (是否验证通过, 错误信息列表)
        """
        errors = []

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()

                for table_name, required_cols in self.required_columns.items():
                    # 检查表是否存在
                    cursor.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'public'
                            AND table_name = %s
                        );
                    """, (table_name,))

                    if not cursor.fetchone()[0]:
                        errors.append(f"表 {table_name} 不存在")
                        continue

                    # 获取表的列信息
                    cursor.execute("""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                        AND table_name = %s;
                    """, (table_name,))

                    existing_cols = {row[0] for row in cursor.fetchall()}

                    # 检查必需的列
                    for col in required_cols:
                        if col not in existing_cols:
                            errors.append(f"表 {table_name} 缺少列: {col}")

                # 检查索引
                cursor.execute("""
                    SELECT indexname
                    FROM pg_indexes
                    WHERE tablename IN ('sessions', 'session_messages');
                """)
                existing_indexes = {row[0] for row in cursor.fetchall()}

                required_indexes = [
                    'idx_sessions_user_id',
                    'idx_sessions_updated_at',
                    'idx_sessions_user_status',
                    'idx_sessions_user_mode',
                    'idx_sessions_last_message',
                    'idx_messages_session_created',
                    'idx_messages_session_role',
                    'idx_messages_memory_id',
                    'idx_messages_created_at',
                    'idx_messages_metadata',
                    'idx_messages_tool_calls'
                ]

                for idx in required_indexes:
                    if idx not in existing_indexes:
                        errors.append(f"缺少索引: {idx}")

                cursor.close()

        except Exception as e:
            errors.append(f"验证过程发生异常: {e}")
            logger.error(f"[SessionTableCreator] 验证表结构时发生异常: {e}")

        return len(errors) == 0, errors

    def get_table_stats(self) -> dict:
        """
        获取表统计信息

        Returns:
            表统计信息字典
        """
        stats = {}
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()

                for table_name in self.tables:
                    # 检查表是否存在
                    cursor.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'public'
                            AND table_name = %s
                        );
                    """, (table_name,))

                    if cursor.fetchone()[0]:
                        # 获取列数
                        cursor.execute("""
                            SELECT COUNT(*)
                            FROM information_schema.columns
                            WHERE table_schema = 'public'
                            AND table_name = %s;
                        """, (table_name,))
                        col_count = cursor.fetchone()[0]

                        # 获取索引数
                        cursor.execute("""
                            SELECT COUNT(*)
                            FROM pg_indexes
                            WHERE tablename = %s;
                        """, (table_name,))
                        idx_count = cursor.fetchone()[0]

                        stats[table_name] = {
                            'columns': col_count,
                            'indexes': idx_count,
                            'status': '已创建'
                        }
                    else:
                        stats[table_name] = {
                            'status': '未创建'
                        }

                cursor.close()
        except Exception as e:
            logger.error(f"[SessionTableCreator] 获取表统计信息失败: {e}")

        return stats

    def create_tables(self) -> tuple[bool, str]:
        """
        创建Session表的主入口方法

        Returns:
            (是否成功, 结果信息)
        """
        logger.info("=" * 60)
        logger.info("[SessionTableCreator] 开始创建Session管理表")
        logger.info("=" * 60)

        # 1. 检查表是否已存在
        existing_tables = self.check_tables_exist()
        if all(existing_tables.values()):
            msg = "所有表已存在，跳过创建"
            logger.info(f"[SessionTableCreator] {msg}")

            # 即使已存在也验证结构
            valid, errors = self.verify_table_structure()
            if not valid:
                msg = f"表已存在但结构验证失败: {', '.join(errors)}"
                logger.error(f"[SessionTableCreator] {msg}")
                return False, msg

            return True, msg

        # 2. 读取SQL脚本
        try:
            sql_content = self.read_sql_script()
        except Exception as e:
            return False, f"读取SQL脚本失败: {e}"

        # 3. 执行SQL脚本
        success, error = self.execute_sql(sql_content)
        if not success:
            return False, f"执行SQL脚本失败: {error}"

        # 4. 验证表结构
        valid, errors = self.verify_table_structure()
        if not valid:
            error_msg = f"表结构验证失败: {', '.join(errors)}"
            logger.error(f"[SessionTableCreator] {error_msg}")
            return False, error_msg

        # 5. 获取统计信息
        stats = self.get_table_stats()

        logger.info("=" * 60)
        logger.info("[SessionTableCreator] Session表创建成功!")
        logger.info("=" * 60)
        for table_name, stat in stats.items():
            if stat.get('status') == '已创建':
                logger.info(f"  - {table_name}: {stat['columns']}列, {stat['indexes']}个索引")
        logger.info("=" * 60)

        return True, "表创建成功"


def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("Phase 1 Week 1 - Task 1: 创建Session管理数据库表")
    print("=" * 60 + "\n")

    creator = SessionTableCreator()
    success, message = creator.create_tables()

    if success:
        print("\n✅ 成功:")
        print(f"   {message}")

        # 输出表统计信息
        stats = creator.get_table_stats()
        print("\n📊 表结构统计:")
        for table_name, stat in stats.items():
            if stat.get('status') == '已创建':
                print(f"   • {table_name}:")
                print(f"     - 列数: {stat['columns']}")
                print(f"     - 索引数: {stat['indexes']}")

        print("\n" + "=" * 60)
        return 0
    else:
        print("\n❌ 失败:")
        print(f"   {message}")
        print("\n" + "=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
