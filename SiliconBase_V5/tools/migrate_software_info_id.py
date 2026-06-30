#!/usr/bin/env python3
"""
修复 software_info.id 字段长度不足导致的批量写入失败。

问题：注册表某些子键名很长，生成的 `reg_<subkey>` 超过 64 字符，
      写入 PostgreSQL 时触发 "值太长了(64)"。

解决：将 id 列从 VARCHAR(64) 扩展到 VARCHAR(255)。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 确保能导入 core 模块
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.db.connection_pool import (  # noqa: E402
    PostgresConnectionPool,
    safe_return_connection,
)


def migrate() -> None:
    conn = None
    try:
        conn = PostgresConnectionPool.get_connection(timeout=10)
        with conn.cursor() as cur:
            cur.execute("""
                ALTER TABLE software_info
                ALTER COLUMN id TYPE VARCHAR(255),
                ALTER COLUMN user_id TYPE VARCHAR(255);
            """)
        conn.commit()
        print("[migrate] software_info.id / user_id 已扩展为 VARCHAR(255)")
    except Exception as e:
        error_msg = str(e).lower()
        if "already" in error_msg or "does not exist" in error_msg:
            print(f"[migrate] 无需修改: {e}")
        else:
            print(f"[migrate] 失败: {e}")
            raise
    finally:
        if conn:
            safe_return_connection(conn)


if __name__ == "__main__":
    migrate()
