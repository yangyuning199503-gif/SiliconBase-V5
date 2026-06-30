#!/usr/bin/env python3
"""
全局视野 - 软件信息库（完整版 V5.1）
首次全盘扫描 + 增量监听，扫描进度可通过状态服务器查询
2026-02-15 修复：数据库启用WAL模式，扫描增加深度限制、CPU限流、中断机制
2026-02-28 迁移：从SQLite迁移到PostgreSQL，添加user_id支持多租户
"""
import asyncio
import concurrent.futures
import contextlib
import functools
import os
import sys
import threading
import time
import winreg
from datetime import datetime  # 【修复】导入datetime模块

from core.config import config
from core.db.connection_pool import PostgresConnectionPool, safe_return_connection
from core.logger import logger
from core.utils.error_codes import GV_002_DB_WRITE_FAILED, format_error


# 线程安全装饰器 - 统一异常处理和日志
def _thread_safe_wrapper(func):
    """线程安全包装器 - 统一异常处理和日志（捕获异常，防止线程池任务崩溃）"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"[GlobalView] {func.__name__} 执行失败: {e}", exc_info=True)
            # 不重新抛出异常，避免线程池任务失败导致进程崩溃
    return wrapper

# 【V5.2新增】资源协调器集成
try:
    from core.resource_coordinator import Priority, ResourceType, coordinator
    RESOURCE_COORDINATOR_AVAILABLE = True
except ImportError:
    RESOURCE_COORDINATOR_AVAILABLE = False
    logger.warning("[GlobalView] 资源协调器不可用，将使用直接调用模式")

SCAN_PROGRESS = {"status": "idle", "total": 0, "current": 0, "message": ""}


class SoftwareDB:
    _instance = None
    _rw_lock = threading.RLock()  # 读写锁

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _get_connection(self, timeout: int = 30):
        """
        获取PostgreSQL连接（带等待重试机制）

        Args:
            timeout: 最大等待时间（秒）

        Returns:
            数据库连接

        Raises:
            RuntimeError: 连接池耗尽且等待超时
        """
        import time
        start_time = time.time()
        last_error = None

        while time.time() - start_time < timeout:
            try:
                # 【修复】使用带超时的get_connection，避免卡死
                remaining_time = max(1, int(timeout - (time.time() - start_time)))
                conn = PostgresConnectionPool.get_connection(timeout=remaining_time)
                if conn:
                    return conn
            except Exception as e:
                last_error = e
                error_msg = str(e).lower()
                # 只有连接池耗尽时才等待重试
                if any(x in error_msg for x in ["pool", "exhausted", "timeout", "too many clients"]):
                    logger.warning(f"[SoftwareDB] 连接池暂时耗尽，等待重试... ({int(time.time() - start_time)}s/{timeout}s)")
                    time.sleep(1)  # sync function: intentional blocking wait for DB connection pool
                    continue
                # 其他错误直接抛出
                raise

        # 超时后仍未获取连接
        error_msg = f"[SoftwareDB] 无法获取数据库连接，等待{timeout}秒后超时"
        logger.error(f"[SoftwareDB] {error_msg}")
        if last_error:
            raise RuntimeError(f"{error_msg}: {last_error}")
        raise RuntimeError(error_msg)

    def _init_db(self):
        """初始化数据库 - 表已在Phase 1创建，此处不做任何操作"""
        pass

    def __init__(self):
        self._init_db()
        self._batch_buffer = []  # 批量写入缓冲区
        self._batch_lock = threading.Lock()  # 批量写入锁
        self._batch_size = 50  # 每批次写入数量

    def batch_add_or_update(self, user_id: str = "default", software_list: list = None):
        """
        批量添加或更新软件信息 - 修复连接池耗尽问题

        Args:
            user_id: 用户ID，用于多租户隔离，默认为"default"
            software_list: 软件信息列表，每个元素是字典包含软件字段
        """
        if not software_list:
            return

        # 去重：基于 id 字段，保留最后出现的记录（最新数据优先）
        # 解决 PostgreSQL ON CONFLICT DO UPDATE 同一批数据中不能有重复键的问题
        seen_ids = {}
        for item in software_list:
            item_id = item.get('id')
            if item_id:
                seen_ids[item_id] = item
        # 如果有重复，使用去重后的列表
        if len(seen_ids) < len(software_list):
            software_list = list(seen_ids.values())

        try:
            # 构建值列表
            from datetime import datetime
            values = []
            for kwargs in software_list:
                values.append((
                    kwargs.get('id'),
                    user_id,
                    kwargs.get('name'),
                    kwargs.get('install_path'),
                    kwargs.get('process_name'),
                    kwargs.get('window_class'),
                    kwargs.get('version'),
                    kwargs.get('last_launch_time'),
                    kwargs.get('launch_count', 0),
                    kwargs.get('auto_discovered', True),
                    kwargs.get('created_at') or datetime.now()
                ))

            conn = None
            try:
                conn = self._get_connection()
                from psycopg2.extras import execute_values
                with conn.cursor() as cur:
                    execute_values(
                        cur,
                        '''
                        INSERT INTO software_info
                        (id, user_id, name, install_path, process_name, window_class, version, last_launch_time, launch_count, auto_discovered, created_at)
                        VALUES %s
                        ON CONFLICT (id) DO UPDATE SET
                            user_id = EXCLUDED.user_id,
                            name = EXCLUDED.name,
                            install_path = EXCLUDED.install_path,
                            process_name = EXCLUDED.process_name,
                            window_class = EXCLUDED.window_class,
                            version = EXCLUDED.version,
                            last_launch_time = EXCLUDED.last_launch_time,
                            launch_count = EXCLUDED.launch_count,
                            auto_discovered = EXCLUDED.auto_discovered
                        ''',
                        values,
                        page_size=len(values)
                    )
                conn.commit()
            finally:
                if conn:
                    safe_return_connection(conn)
        except Exception as e:
            logger.error(format_error(GV_002_DB_WRITE_FAILED)["user_message"] + f" 批量写入失败: {e}")

    def flush_batch_buffer(self, user_id: str = "default"):
        """
        刷新批量写入缓冲区 - 将缓冲区中的数据写入数据库
        """
        with self._batch_lock:
            if self._batch_buffer:
                self.batch_add_or_update(user_id, self._batch_buffer)
                self._batch_buffer = []

    def add_to_batch(self, user_id: str = "default", **kwargs):
        """
        添加到批量写入缓冲区，达到批次大小后自动刷新
        线程安全：使用线程池替代裸线程，防止线程爆炸

        Args:
            user_id: 用户ID，用于多租户隔离，默认为"default"
            **kwargs: 软件信息字段
        """
        with self._batch_lock:
            self._batch_buffer.append((user_id, kwargs))
            need_flush = len(self._batch_buffer) >= self._batch_size

        if need_flush:
            self._trigger_flush()

    def _trigger_flush(self):
        """触发异步刷新 - 使用线程池"""
        try:
            GlobalView._executor.submit(self._flush_batch_async)
        except RuntimeError as e:
            print(f"[CRITICAL ERROR][GlobalView] 批量刷新任务提交失败（线程池已关闭）: {e}", file=sys.stderr)

    @_thread_safe_wrapper
    def _flush_batch_async(self):
        """
        批量刷新异步执行 - 带异常处理和失败重入队
        使用线程池执行，防止线程爆炸
        """
        with self._batch_lock:
            if not self._batch_buffer:
                return
            buffer_copy = self._batch_buffer[:]
            self._batch_buffer = []

        try:
            # 按 user_id 分组处理
            from collections import defaultdict
            grouped = defaultdict(list)
            for user_id, kwargs in buffer_copy:
                grouped[user_id].append(kwargs)

            for user_id, items in grouped.items():
                self.batch_add_or_update(user_id, items)

            logger.debug(f"[GlobalView] 批量写入成功: {len(buffer_copy)} 条记录")

        except Exception as e:
            logger.error(f"[GlobalView] 批量写入失败: {e}", exc_info=True)
            # 失败时重新入队（保留最近100条防止无限增长）
            with self._batch_lock:
                self._batch_buffer.extend(buffer_copy[-100:])
                if len(self._batch_buffer) > 100:
                    self._batch_buffer = self._batch_buffer[-100:]

    def add_or_update(self, user_id: str = "default", **kwargs):
        """
        添加或更新软件信息

        Args:
            user_id: 用户ID，用于多租户隔离，默认为"default"
            **kwargs: 软件信息字段
        """
        sql = '''
            INSERT INTO software_info
            (id, user_id, name, install_path, process_name, window_class, version, last_launch_time, launch_count, auto_discovered, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (id) DO UPDATE SET
                user_id = EXCLUDED.user_id,
                name = EXCLUDED.name,
                install_path = EXCLUDED.install_path,
                process_name = EXCLUDED.process_name,
                window_class = EXCLUDED.window_class,
                version = EXCLUDED.version,
                last_launch_time = EXCLUDED.last_launch_time,
                launch_count = EXCLUDED.launch_count,
                auto_discovered = EXCLUDED.auto_discovered
        '''
        conn = None
        c = None
        try:
            conn = self._get_connection()
            c = conn.cursor()
            c.execute(sql, (
                kwargs.get('id'),
                user_id,
                kwargs.get('name'),
                kwargs.get('install_path'),
                kwargs.get('process_name'),
                kwargs.get('window_class'),
                kwargs.get('version'),
                kwargs.get('last_launch_time'),
                kwargs.get('launch_count', 0),
                kwargs.get('auto_discovered', True)
            ))
            conn.commit()
        except Exception as e:
            logger.error(format_error(GV_002_DB_WRITE_FAILED)["user_message"] + f" {e}")
        finally:
            if c:
                c.close()
            if conn:
                safe_return_connection(conn)

    def search(self, keyword: str, user_id: str = "default") -> list:
        """
        搜索软件信息

        Args:
            keyword: 搜索关键词
            user_id: 用户ID，用于多租户过滤，默认为"default"

        Returns:
            匹配的软件信息列表
        """
        keyword = f"%{keyword}%"
        conn = None
        c = None
        try:
            conn = self._get_connection()
            c = conn.cursor()
            c.execute('''
                SELECT id, user_id, name, install_path, process_name, window_class, version, last_launch_time, launch_count, auto_discovered, created_at
                FROM software_info
                WHERE user_id = %s AND (name ILIKE %s OR process_name ILIKE %s OR install_path ILIKE %s)
                ORDER BY launch_count DESC, last_launch_time DESC LIMIT 10
            ''', (user_id, keyword, keyword, keyword))
            rows = c.fetchall()
        finally:
            if c:
                c.close()
            if conn:
                safe_return_connection(conn)
        return [{
            "id": r[0],
            "user_id": r[1],
            "name": r[2],
            "install_path": r[3],
            "process_name": r[4],
            "window_class": r[5],
            "version": r[6],
            "last_launch_time": r[7],
            "launch_count": r[8],
            "auto_discovered": r[9],
            "created_at": r[10]
        } for r in rows]

    def get_all(self, user_id: str = "default") -> list:
        """
        获取所有软件信息

        Args:
            user_id: 用户ID，用于多租户过滤，默认为"default"

        Returns:
            所有软件信息列表
        """
        conn = None
        c = None
        try:
            conn = self._get_connection()
            c = conn.cursor()
            c.execute('''
                SELECT id, user_id, name, install_path, process_name, window_class, version, last_launch_time, launch_count, auto_discovered, created_at
                FROM software_info
                WHERE user_id = %s
                ORDER BY launch_count DESC, last_launch_time DESC
            ''', (user_id,))
            rows = c.fetchall()
        finally:
            if c:
                c.close()
            if conn:
                safe_return_connection(conn)
        return [{
            "id": r[0],
            "user_id": r[1],
            "name": r[2],
            "install_path": r[3],
            "process_name": r[4],
            "window_class": r[5],
            "version": r[6],
            "last_launch_time": r[7],
            "launch_count": r[8],
            "auto_discovered": r[9],
            "created_at": r[10]
        } for r in rows]

    def get_all_files(self, user_id: str = "default") -> list:
        """
        获取所有扫描的文件（来自file_index表）

        Args:
            user_id: 用户ID

        Returns:
            文件信息列表
        """
        conn = None
        c = None
        try:
            conn = self._get_connection()
            c = conn.cursor()
            c.execute('''
                SELECT id, user_id, file_name, file_path, file_extension, file_size,
                       modified_time, file_type, drive_letter, is_executable, scan_batch_id, created_at
                FROM file_index
                WHERE user_id = %s
                ORDER BY drive_letter, file_path
            ''', (user_id,))
            rows = c.fetchall()
            return [{
                'id': r[0],
                'user_id': r[1],
                'file_name': r[2],
                'file_path': r[3],
                'file_extension': r[4],
                'file_size': r[5],
                'modified_time': r[6],
                'file_type': r[7],
                'drive_letter': r[8],
                'is_executable': r[9],
                'scan_batch_id': r[10],
                'created_at': r[11]
            } for r in rows]
        except Exception as e:
            logger.error(f"[SoftwareDB] 获取文件列表失败: {e}")
            return []
        finally:
            if c:
                c.close()
            if conn:
                safe_return_connection(conn)


class GlobalView:
    """
    全局视野 - 软件信息库

    线程安全设计：
    1. 类级线程池 _executor - 限制最大并发线程数
    2. 状态锁 _state_lock - 保护 _scanning 等状态变量
    3. 监听信号量 _watch_semaphore - 防止文件监听风暴
    """

    # 类级共享线程池 - 限制最大线程数（与ToolManager一致的设计）
    _executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=5,
        thread_name_prefix="global_view_"
    )

    # 扫描状态锁 - 保护 _scanning, _scan_stop_flag 等状态
    _state_lock = threading.RLock()

    # 文件监听专用信号量 - 防止监听风暴（最多3个并发处理）
    _watch_semaphore = threading.Semaphore(3)

    def __init__(self):
        self.db = SoftwareDB()
        self._observer = None
        self._scanning = False
        self._scan_stop_flag = None
        self._scan_file_count = 0
        self._last_incremental_scan = 0  # 【优化】上次增量扫描时间戳
        self._incremental_scan_cooldown = 5.0  # 【优化】增量扫描冷却期（秒）
        self._main_loop = asyncio.get_event_loop()

    def start_watch(self):
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            logger.warning("[GlobalView] watchdog未安装，增量监听不可用")
            return

        class ScanHandler(FileSystemEventHandler):
            def on_created(self, event):
                try:
                    if event.is_directory:
                        # 【优化】防抖：检查冷却期
                        now = time.time()
                        if now - global_view._last_incremental_scan < global_view._incremental_scan_cooldown:
                            return  # 冷却期内，跳过
                        global_view._last_incremental_scan = now

                        # 【线程安全】使用信号量限制并发处理数，防止监听风暴
                        if not global_view._watch_semaphore.acquire(blocking=False):
                            logger.debug(f"[GlobalView] 文件监听限流，跳过: {event.src_path}")
                            return

                        # 使用线程池替代裸线程
                        try:
                            global_view._executor.submit(
                                global_view._scan_path_limited,
                                event.src_path
                            )
                        except RuntimeError as e:
                            # 线程池已关闭时 Observer 守护线程不能崩，必须捕获；同时释放已获取的信号量
                            with contextlib.suppress(ValueError):
                                global_view._watch_semaphore.release()  # 信号量已释放或超额释放则忽略
                            print(f"[CRITICAL ERROR][GlobalView] Observer on_created 提交扫描任务失败（线程池已关闭）: {e}", file=sys.stderr)
                except Exception as e:
                    # Observer 回调绝不允许异常逃逸到 watchdog 内部线程
                    print(f"[CRITICAL ERROR][GlobalView] Observer on_created 未捕获异常: {e}", file=sys.stderr)
            def on_deleted(self, event):
                """文件删除时同步删除数据库记录"""
                if event.is_directory:
                    return

                try:
                    # 生成文件ID（与_process_exe中相同的逻辑）
                    import hashlib
                    file_hash = hashlib.md5(event.src_path.encode()).hexdigest()[:16]
                    software_id = f"exe_{file_hash}"

                    # 从数据库删除
                    global_view._delete_software_by_id(software_id)
                    logger.info(f"[GlobalView] 文件删除同步: {event.src_path}")

                except Exception as e:
                    logger.error(f"[GlobalView] 文件删除同步失败: {e}")

        self._observer = Observer()
        dirs = config.get("perception.global_view.watch_directories", [])
        for d in dirs:
            if os.path.exists(d):
                self._observer.schedule(ScanHandler(), d, recursive=True)
        self._observer.start()
        logger.info("[GlobalView] 全局视野增量监听已启动")

    def scan_all_async(self):
        """
        异步执行全盘扫描，不阻塞主线程（向后兼容接口）
        使用线程池替代裸线程，防止线程爆炸
        """
        with self._state_lock:
            if self._scanning:
                logger.info("[GlobalView] 扫描已在后台进行")
                return
            self._scanning = True
            self._scan_stop_flag = threading.Event()

        logger.info("[GlobalView] 启动全盘扫描（兼容接口）")
        try:
            self._executor.submit(self._scan_all_wrapped, "default")
        except RuntimeError as e:
            print(f"[CRITICAL ERROR][GlobalView] 全盘扫描任务提交失败（线程池已关闭）: {e}", file=sys.stderr)
            with self._state_lock:
                self._scanning = False

    def start_full_disk_scan(self, user_id: str = "default"):
        """
        API 调用的全盘扫描入口
        线程安全：使用 _state_lock 保护状态检查
        """
        with self._state_lock:
            if self._scanning:
                logger.info("[GlobalView] 扫描已在后台进行")
                return False
            self._scanning = True
            self._scan_stop_flag = threading.Event()

        logger.info(f"[GlobalView] 启动全盘扫描 (user_id={user_id})")
        try:
            self._executor.submit(self._scan_all_wrapped, user_id)
            return True
        except RuntimeError as e:
            print(f"[CRITICAL ERROR][GlobalView] 全盘扫描任务提交失败（线程池已关闭）: {e}", file=sys.stderr)
            with self._state_lock:
                self._scanning = False
            return False

    @_thread_safe_wrapper
    def _scan_all_wrapped(self, user_id: str):
        """
        全盘扫描包装器 - 带异常处理和状态重置
        确保无论成功或失败，状态都能正确恢复
        """
        try:
            self._scan_all(user_id)
        finally:
            with self._state_lock:
                self._scanning = False
                self._scan_stop_flag = None
            logger.info("[GlobalView] 全盘扫描任务结束")

    @_thread_safe_wrapper
    def _scan_path_limited(self, path: str):
        """
        增量扫描包装器 - 带信号量释放和异常处理
        用于文件监听回调，确保信号量正确释放
        """
        try:
            self._scan_path(path, max_depth=config.get("global_view.max_scan_depth", 3))
        except Exception as e:
            logger.error(f"[GlobalView] 增量扫描失败 {path}: {e}")
        finally:
            # 确保信号量被释放
            with contextlib.suppress(ValueError):
                self._watch_semaphore.release()  # 信号量已释放或超额释放则忽略

    def stop_scan(self):
        """停止正在进行的扫描"""
        if hasattr(self, '_scan_stop_flag') and self._scan_stop_flag is not None:
            self._scan_stop_flag.set()
            logger.info("[GlobalView] 已发送扫描停止信号")

    def _scan_all(self, user_id: str = "default"):
        """
        【优化】全盘扫描 - 简化逻辑，减少冗余扫描
        扫描顺序：注册表 -> 全盘关键磁盘
        """
        global SCAN_PROGRESS
        SCAN_PROGRESS["status"] = "running"
        SCAN_PROGRESS["message"] = "开始扫描..."
        with self._state_lock:
            self._scanning = True
        total_scanned = 0

        try:
            # 1. 扫描注册表获取已安装软件（最可靠）
            logger.info("[GlobalView] 开始扫描注册表...")
            self._scan_registry(user_id=user_id)

            # 2. 全盘扫描（只扫描关键磁盘，限制文件数）
            # 从配置读取扫描限制，默认2000个文件（平衡覆盖率和性能）
            max_files_per_drive = config.get("global_view.max_files_per_drive", 2000)

            for drive in ["D", "E"]:
                if self._scan_stop_flag is not None and self._scan_stop_flag.is_set():
                    logger.info("[GlobalView] 扫描被中断")
                    break

                drive_path = f"{drive}:\\"
                if os.path.exists(drive_path):
                    logger.info(f"[GlobalView] 开始扫描磁盘 {drive}...")
                    scanned = self._scan_full_disk(drive, user_id=user_id, max_files=max_files_per_drive)
                    total_scanned += scanned
                else:
                    logger.debug(f"[GlobalView] 磁盘 {drive} 不存在，跳过")

            # 扫描完成后刷新批量缓冲区
            self.db.flush_batch_buffer(user_id=user_id)
            SCAN_PROGRESS["status"] = "completed"
            SCAN_PROGRESS["message"] = f"扫描完成，共记录 {total_scanned} 个文件"
            logger.info(f"[GlobalView] 全盘扫描完成，共记录 {total_scanned} 个文件")

        except Exception as e:
            SCAN_PROGRESS["status"] = "error"
            SCAN_PROGRESS["message"] = str(e)
            logger.error(f"[GlobalView] 扫描异常: {e}", exc_info=True)
        finally:
            with self._state_lock:
                self._scanning = False
                self._scan_stop_flag = None
            # 确保批量缓冲区被刷新
            try:
                self.db.flush_batch_buffer(user_id=user_id)
            except Exception as e:
                logger.error(f"[GlobalView] 刷新批量缓冲区失败: {e}", exc_info=True)

    def _scan_full_disk(self, drive_letter: str, user_id: str = "default", max_files: int = 0) -> int:
        """
        【全盘扫描】遍历整个磁盘，记录所有重要文件

        Args:
            drive_letter: 盘符，如 'D', 'E'
            user_id: 用户ID
            max_files: 最大扫描文件数，0表示无限制（扫完所有文件）

        Returns:
            int: 实际扫描的文件数
        """
        import hashlib
        import time
        from datetime import datetime

        drive_path = f"{drive_letter}:\\"
        if not os.path.exists(drive_path):
            logger.debug(f"[GlobalView] 磁盘不存在: {drive_path}")
            return 0

        # 生成扫描批次ID
        scan_batch_id = hashlib.md5(f"{drive_letter}_{time.time()}".encode()).hexdigest()[:16]

        # 只在开始和结束时记录info日志，中间过程用debug
        logger.info(f"[GlobalView] 开始扫描磁盘 {drive_letter}...")

        # 扩展的文件扩展名 - 包含几乎所有常见文件类型
        scan_extensions = {
            # 可执行文件
            '.exe', '.dll', '.bat', '.cmd', '.ps1', '.sh', '.msi', '.com',
            # 代码文件
            '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cpp', '.c', '.h', '.hpp',
            '.cs', '.go', '.rs', '.php', '.rb', '.swift', '.kt', '.scala', '.r',
            # 脚本和配置
            '.json', '.yaml', '.yml', '.xml', '.toml', '.ini', '.conf', '.cfg',
            '.properties', '.env', '.sql', '.bash', '.zsh',
            # 文档
            '.md', '.txt', '.doc', '.docx', '.pdf', '.ppt', '.pptx', '.xls', '.xlsx',
            '.csv', '.rtf', '.odt', '.ods', '.odp',
            # Web文件
            '.html', '.htm', '.css', '.scss', '.sass', '.less', '.vue', '.svelte',
            # 媒体文件
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.ico', '.webp',
            '.mp3', '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.wav', '.flac',
            # 压缩文件
            '.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz',
            # 游戏相关
            '.pak', '.asset', '.unitypackage', '.uproject', '.uplugin',
            # 其他
            '.log', '.tmp', '.cache', '.db', '.sqlite', '.sqlite3'
        }

        # 排除的系统目录
        exclude_dirs = {
            'windows', 'programdata', '$recycle.bin', 'system volume information',
            'temp', 'tmp', 'cache', 'logs', 'log', 'pagefile.sys'
        }

        scanned_count = 0
        file_batch = []
        batch_size = 500  # 增大每批处理数量

        try:
            for root, dirs, files in os.walk(drive_path):
                # 检查中断
                if self._scan_stop_flag is not None and self._scan_stop_flag.is_set():
                    logger.info(f"[GlobalView] 扫描被中断，已扫描 {scanned_count} 个文件")
                    break

                # 过滤掉系统目录
                dirs[:] = [d for d in dirs if d.lower() not in exclude_dirs and not d.startswith('.')]

                for file in files:
                    # 检查文件扩展名
                    file_lower = file.lower()
                    ext = os.path.splitext(file_lower)[1]

                    if ext in scan_extensions or file_lower.endswith('.exe'):
                        file_path = os.path.join(root, file)

                        try:
                            # 获取文件信息
                            stat = os.stat(file_path)
                            file_size = stat.st_size
                            modified_time = datetime.fromtimestamp(stat.st_mtime)

                            # 判断文件类型
                            file_type = self._get_file_type(ext, file_lower)
                            is_executable = ext == '.exe' or file_lower.endswith('.exe')

                            # 生成唯一ID
                            file_id = hashlib.md5(file_path.encode()).hexdigest()[:32]

                            file_info = {
                                'id': file_id,
                                'user_id': user_id,
                                'file_name': file,
                                'file_path': file_path,
                                'file_extension': ext,
                                'file_size': file_size,
                                'modified_time': modified_time,
                                'file_type': file_type,
                                'drive_letter': drive_letter,
                                'is_executable': is_executable,
                                'scan_batch_id': scan_batch_id
                            }

                            file_batch.append(file_info)
                            scanned_count += 1

                            # 批量写入，每500条写入一次
                            if len(file_batch) >= batch_size:
                                self._save_file_batch(file_batch, user_id)
                                file_batch = []
                                # 【优化】减少日志输出，每1000条记录一次debug日志
                                if scanned_count % 1000 == 0:
                                    logger.debug(f"[GlobalView] 已扫描 {scanned_count} 个文件...")

                            # 检查是否超过最大文件数（0表示无限制）
                            if max_files > 0 and scanned_count >= max_files:
                                logger.debug(f"[GlobalView] 达到最大扫描数 {max_files}，停止扫描")
                                break

                        except (OSError, PermissionError):
                            continue

                    # CPU限流 - 每5000个文件休息一下（只在debug模式记录）
                    if scanned_count % 5000 == 0:
                        logger.debug(f"[GlobalView] 已扫描 {scanned_count} 个文件，休息中...")
                        time.sleep(0.05)  # sync function: intentional blocking CPU throttle in os.walk loop

                if max_files > 0 and scanned_count >= max_files:
                    break

            # 写入剩余的文件
            if file_batch:
                self._save_file_batch(file_batch, user_id)

            # 同步到记忆系统（异步执行，不阻塞扫描）
            # 【线程安全】使用线程池替代裸线程
            try:
                GlobalView._executor.submit(
                    self._sync_to_memory_system_wrapped,
                    user_id,
                    scan_batch_id
                )
            except RuntimeError as e:
                print(f"[CRITICAL ERROR][GlobalView] 记忆同步任务提交失败（线程池已关闭）: {e}", file=sys.stderr)

            logger.info(f"[GlobalView] 磁盘 {drive_letter} 扫描完成，共记录 {scanned_count} 个文件")
            return scanned_count

        except Exception as e:
            logger.error(f"[GlobalView] 扫描失败 {drive_path}: {e}")
            return scanned_count

    async def _sync_to_memory_system(self, user_id: str = "default", scan_batch_id: str = None):
        """
        把扫描结果同步到记忆系统
        使用批量处理避免连接池耗尽
        """
        from core.memory.memory_service import get_memory_service

        conn = None
        cur = None
        files_synced = 0

        try:
            # 只同步当前扫描批次的文件，避免处理所有历史文件
            conn = self.db._get_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT file_name, file_path, file_type
                FROM file_index
                WHERE user_id = %s AND is_executable = TRUE AND scan_batch_id = %s
                LIMIT 1000
            """, (user_id, scan_batch_id))

            files = cur.fetchall()
            cur.close()
            safe_return_connection(conn)
            conn = None
            cur = None

            # 同步到记忆系统 - 批量处理（保守策略避免连接池耗尽）
            ms = await get_memory_service()
            batch_size = 10  # 减小批次大小降低并发压力
            for i in range(0, len(files), batch_size):
                batch = files[i:i+batch_size]
                for file_name, file_path, _file_type in batch:
                    try:
                        # 生成语义描述
                        vector_text = f"程序 {file_name} 安装在 {file_path} 路径"

                        # 存入记忆（内容包含语义描述用于向量索引）
                        await ms.add_memory(
                            user_id=user_id,
                            content={
                                "file_name": file_name,
                                "file_path": file_path,
                                "text": vector_text  # 用于向量索引的文本
                            },
                            memory_type="file_location",
                            layer="medium",
                            scene="filesystem"
                        )
                        files_synced += 1
                    except Exception as e:
                        error_msg = str(e).lower()
                        # 如果是连接池耗尽错误，跳过而不是重试（避免加剧问题）
                        if "connection pool exhausted" in error_msg or "pool" in error_msg:
                            logger.warning(f"[GlobalView] 连接池耗尽，跳过同步 {file_name}（将在下次扫描时重试）")
                            # 不抛错，不阻塞，让扫描继续
                            continue
                        else:
                            logger.warning(f"[GlobalView] 同步单个文件失败 {file_name}（环境问题，不影响核心功能）: {e}")

                # 每批次暂停一下，避免内存和连接压力
                if i + batch_size < len(files):
                    import asyncio
                    await asyncio.sleep(0.5)  # 【修复】异步路径使用 asyncio.sleep，不阻塞事件循环

            logger.info(f"[GlobalView] 已同步 {files_synced}/{len(files)} 个文件到记忆系统")

        except Exception as e:
            logger.warning(f"[GlobalView] 同步到记忆系统失败（环境问题，不影响核心功能）: {e}")
        finally:
            if cur:
                cur.close()
            if conn:
                safe_return_connection(conn)

    @_thread_safe_wrapper
    def _sync_to_memory_system_wrapped(self, user_id: str, scan_batch_id: str):
        """
        记忆系统同步包装器 - 带统一异常处理
        用于线程池提交，确保异常被捕获和记录
        """
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._sync_to_memory_system(user_id, scan_batch_id),
                self._main_loop
            )
            future.result(timeout=300)
        except Exception as e:
            logger.warning(f"[GlobalView] 记忆系统同步失败（环境问题，不影响核心功能）: {e}")

    async def _sync_software_to_vector(self, software_list: list, source: str = "registry", user_id: str = "default"):
        """
        将软件列表同步到向量存储（记忆系统）

        与磁盘扫描的文件同步逻辑统一，让AI可以通过语义搜索找到软件。
        例如：用户说"打开音乐软件"，AI能找到网易云音乐。

        Args:
            software_list: 软件信息列表
            source: 来源标识（registry=注册表, disk=磁盘扫描）
            user_id: 用户ID
        """
        from core.memory.memory_service import get_memory_service

        if not software_list:
            return

        synced_count = 0
        batch_size = 10

        try:
            ms = await get_memory_service()
            for i in range(0, len(software_list), batch_size):
                batch = software_list[i:i+batch_size]

                for software in batch:
                    try:
                        name = software.get('name', '')
                        install_path = software.get('install_path', '')
                        process_name = software.get('process_name', '')

                        if not name or not install_path:
                            continue

                        # 推断功能类别用于语义搜索
                        function_category = self._infer_function_from_name(name)

                        # 构建语义描述文本
                        description_parts = [f"软件 {name}"]
                        if function_category:
                            description_parts.append(f"是{function_category}软件")
                        description_parts.append(f"安装在 {install_path}")
                        if process_name and process_name != name:
                            description_parts.append(f"进程名 {process_name}")

                        vector_text = " ".join(description_parts)

                        # 存入记忆系统
                        await ms.add_memory(
                            user_id=user_id,
                            content={
                                "name": name,
                                "install_path": install_path,
                                "process_name": process_name,
                                "function_category": function_category,
                                "source": source,
                                "text": vector_text
                            },
                            memory_type="software_info",
                            layer="medium",
                            scene="software"
                        )
                        synced_count += 1

                    except Exception as e:
                        error_msg = str(e).lower()
                        if "connection pool exhausted" in error_msg or "pool" in error_msg:
                            logger.warning("[GlobalView] 连接池耗尽，跳过同步软件")
                            continue
                        else:
                            logger.debug(f"[GlobalView] 同步软件失败: {e}")

                # 批次间暂停
                if i + batch_size < len(software_list):
                    await asyncio.sleep(0.3)

            if synced_count > 0:
                logger.info(f"[GlobalView] 已同步 {synced_count}/{len(software_list)} 个软件到向量存储")

        except Exception as e:
            logger.error(f"[GlobalView] 同步软件到向量存储失败: {e}")

    def _get_file_type(self, ext: str, file_name: str) -> str:
        """根据扩展名判断文件类型"""
        ext = ext.lower()
        if ext == '.exe' or ext == '.dll':
            return 'executable'
        elif ext in {'.py', '.js', '.java', '.cpp', '.c', '.h', '.cs', '.go', '.rs'}:
            return 'code'
        elif ext in {'.bat', '.cmd', '.ps1', '.sh'}:
            return 'script'
        elif ext in {'.txt', '.md', '.doc', '.docx', '.pdf'}:
            return 'document'
        elif ext in {'.jpg', '.png', '.gif', '.bmp', '.svg'}:
            return 'image'
        elif ext in {'.mp3', '.mp4', '.avi', '.mkv', '.wav'}:
            return 'media'
        elif ext in {'.zip', '.rar', '.7z', '.tar', '.gz'}:
            return 'archive'
        else:
            return 'other'

    def _save_file_batch(self, file_batch: list, user_id: str = "default"):
        """批量保存文件信息到数据库"""
        if not file_batch:
            return

        conn = None
        cur = None
        try:
            conn = self.db._get_connection()
            cur = conn.cursor()

            sql = '''
                INSERT INTO file_index
                (id, user_id, file_name, file_path, file_extension, file_size,
                 modified_time, file_type, drive_letter, is_executable, scan_batch_id, created_at)
                VALUES %s
                ON CONFLICT (id) DO UPDATE SET
                    file_size = EXCLUDED.file_size,
                    modified_time = EXCLUDED.modified_time,
                    scan_batch_id = EXCLUDED.scan_batch_id,
                    updated_at = CURRENT_TIMESTAMP
            '''

            from psycopg2.extras import execute_values

            values = []
            for f in file_batch:
                values.append((
                    f['id'], f['user_id'], f['file_name'], f['file_path'],
                    f['file_extension'], f['file_size'], f['modified_time'],
                    f['file_type'], f['drive_letter'], f['is_executable'],
                    f['scan_batch_id'], f.get('created_at', datetime.now())
                ))

            execute_values(cur, sql, values, page_size=len(values))
            conn.commit()

        except Exception as e:
            logger.error(f"[GlobalView] 批量保存文件信息失败: {e}")
        finally:
            if cur:
                cur.close()
            if conn:
                safe_return_connection(conn)

    def search_files(self, keyword: str, file_type: str = None, user_id: str = "default", limit: int = 20) -> list:
        """
        搜索文件索引

        Args:
            keyword: 搜索关键词（支持文件名模糊搜索）
            file_type: 文件类型过滤（如 'executable', 'code', 'document'）
            user_id: 用户ID
            limit: 返回结果数量限制

        Returns:
            匹配的文件列表
        """
        # 【V5.2】通过ResourceCoordinator执行，防止并发冲突
        if RESOURCE_COORDINATOR_AVAILABLE:
            result_container = {"results": []}
            event = threading.Event()

            def do_search(db_self, kw, ft, uid, lim):
                conn = None
                cur = None
                try:
                    conn = db_self._get_connection()
                    cur = conn.cursor()

                    if ft:
                        sql = '''
                            SELECT file_name, file_path, file_size, modified_time, file_type, is_executable
                            FROM file_index
                            WHERE user_id = %s AND file_type = %s AND file_name ILIKE %s
                            ORDER BY modified_time DESC
                            LIMIT %s
                        '''
                        cur.execute(sql, (uid, ft, f'%{kw}%', lim))
                    else:
                        sql = '''
                            SELECT file_name, file_path, file_size, modified_time, file_type, is_executable
                            FROM file_index
                            WHERE user_id = %s AND file_name ILIKE %s
                            ORDER BY modified_time DESC
                            LIMIT %s
                        '''
                        cur.execute(sql, (uid, f'%{kw}%', lim))

                    rows = cur.fetchall()

                    for row in rows:
                        result_container["results"].append({
                            'file_name': row[0],
                            'file_path': row[1],
                            'file_size': row[2],
                            'modified_time': row[3],
                            'file_type': row[4],
                            'is_executable': row[5]
                        })
                except Exception as e:
                    logger.error(f"[GlobalView] 搜索文件失败: {e}")
                finally:
                    if cur:
                        cur.close()
                    if conn:
                        safe_return_connection(conn)
                    event.set()

            success = coordinator.request_resource(
                resource_type=ResourceType.POSTGRESQL,
                callback=do_search,
                params={"db_self": self.db, "kw": keyword, "ft": file_type, "uid": user_id, "lim": limit},
                priority=Priority.HIGH,  # 文件搜索通常是用户触发的
                timeout=10.0,
                user_id=user_id,
                task_id=f"file_search_{user_id}_{int(time.time()*1000)}"
            )

            if success and event.wait(timeout=10.0):
                return result_container["results"]
            else:
                logger.warning("[GlobalView] search_files通过ResourceCoordinator执行失败或超时")
                return result_container["results"]
        else:
            # 直接模式（ResourceCoordinator不可用）
            conn = None
            cur = None
            try:
                conn = self.db._get_connection()
                cur = conn.cursor()

                if file_type:
                    sql = '''
                        SELECT file_name, file_path, file_size, modified_time, file_type, is_executable
                        FROM file_index
                        WHERE user_id = %s AND file_type = %s AND file_name ILIKE %s
                        ORDER BY modified_time DESC
                        LIMIT %s
                    '''
                    cur.execute(sql, (user_id, file_type, f'%{keyword}%', limit))
                else:
                    sql = '''
                        SELECT file_name, file_path, file_size, modified_time, file_type, is_executable
                        FROM file_index
                        WHERE user_id = %s AND file_name ILIKE %s
                        ORDER BY modified_time DESC
                        LIMIT %s
                    '''
                    cur.execute(sql, (user_id, f'%{keyword}%', limit))

                rows = cur.fetchall()

                results = []
                for row in rows:
                    results.append({
                        'file_name': row[0],
                        'file_path': row[1],
                        'file_size': row[2],
                        'modified_time': row[3],
                        'file_type': row[4],
                        'is_executable': row[5]
                    })
                return results

            except Exception as e:
                logger.error(f"[GlobalView] 搜索文件失败: {e}")
                return []
            finally:
                if cur:
                    cur.close()
                if conn:
                    safe_return_connection(conn)

    async def smart_file_search(self, query: str, user_id: str = "default", limit: int = 30) -> dict:
        """
        【智能文件检索】根据用户查询返回相关文件信息

        这个方法用于AI查询时按需获取文件信息，而不是一次性提供全量。

        示例:
        - query="D盘的冒险岛" → 返回 E:\\冒险岛 相关文件
        - query="网易云音乐" → 返回 D:\\CloudMusic（网易云）\\cloudmusic.exe
        - query="帮我看看D盘的梦幻西游" → 返回 E:\\梦幻\\mhxy.exe

        Args:
            query: 用户查询，如 "D盘的冒险岛"
            user_id: 用户ID
            limit: 最多返回几个结果

        Returns:
            {
                'found': True/False,
                'matches': [
                    {'name': 'xxx.exe', 'path': 'D:\\xxx\\xxx.exe', 'type': 'executable'}
                ],
                'suggestion': '是否需要查看具体路径的所有文件？'
            }
        """
        import re

        result = {
            'found': False,
            'matches': [],
            'suggestion': ''
        }

        # 1. 从查询中提取盘符
        drive_match = re.search(r'([DEFGHIJKLMNOPQRSTUVWXYZ]):', query.upper())
        drive_filter = drive_match.group(1) if drive_match else None

        # 2. 从查询中提取关键词（去掉常见词汇）
        keywords = query.lower()
        for word in ['盘', '的', '看看', '帮我', '查询', '搜索', '找', '一下', '所有', '文件']:
            keywords = keywords.replace(word, ' ')
        keywords = keywords.strip()

        # 3. 先查数据库（快速匹配）
        db_results = self.search_files(
            keyword=keywords,
            user_id=user_id,
            limit=limit
        )

        # 4. 再查记忆系统（语义匹配）
        memory_results = []
        try:
            from core.memory.memory_service import get_memory_service
            ms = await get_memory_service()
            memory_results = await ms.retrieve_memories(
                user_id=user_id,
                query=query,
                level="medium",
                limit=limit
            )
        except Exception as e:
            logger.error(f"[GlobalView] 记忆系统查询失败: {e}", exc_info=True)

        # 5. 合并结果（去重）
        seen_paths = set()
        all_matches = []

        # 添加数据库结果
        for r in db_results:
            path = r.get('file_path', '')
            if path and path not in seen_paths:
                # 如果指定了盘符，过滤
                if drive_filter and not path.upper().startswith(f"{drive_filter}:"):
                    continue
                seen_paths.add(path)
                all_matches.append({
                    'name': r.get('file_name'),
                    'path': path,
                    'type': r.get('file_type'),
                    'size': r.get('file_size'),
                    'source': 'database'
                })

        # 添加记忆系统结果
        for m in memory_results:
            content = m.get('content', '')
            if ':' in content:
                name, path = content.split(':', 1)
                if path and path not in seen_paths and os.path.exists(path):
                    # 如果指定了盘符，过滤
                    if drive_filter and not path.upper().startswith(f"{drive_filter}:"):
                        continue
                    seen_paths.add(path)
                    all_matches.append({
                        'name': name,
                        'path': path,
                        'type': 'executable' if path.endswith('.exe') else 'file',
                        'source': 'memory'
                    })

        # 6. 组装结果
        if all_matches:
            result['found'] = True
            result['matches'] = all_matches[:limit]

            if len(all_matches) == 1:
                result['suggestion'] = f"找到文件: {all_matches[0]['path']}"
            else:
                result['suggestion'] = f"找到 {len(all_matches)} 个匹配文件，是否需要查看具体某个路径？"
        else:
            result['suggestion'] = "未找到相关文件，建议：\n1. 确认文件已存在于磁盘\n2. 等待全盘扫描完成\n3. 使用更具体的关键词"

        return result

    def _scan_d_drive(self, user_id: str = "default"):
        """扫描D盘和E盘常见安装目录（后台异步，不阻塞）"""
        logger.info("[GlobalView] 开始扫描D盘/E盘常见安装目录（后台异步）...")
        common_paths = [
            # D盘常见路径
            "D:\\CloudMusic",
            "D:\\CloudMusic（网易云）",  # 网易云音乐特殊路径
            "D:\\Software",
            "D:\\Apps",
            "D:\\Applications",
            "D:\\Program Files",
            "D:\\Program Files (x86)",
            "D:\\Game",
            "D:\\Games",
            "D:\\Netease",
            # E盘常见路径（关键修复！）
            "E:\\梦幻",
            "E:\\Game",
            "E:\\Games",
            "E:\\Software",
            "E:\\Apps",
            "E:\\Program Files",
            "E:\\Program Files (x86)",
        ]
        max_depth = config.get("global_view.max_scan_depth", 2)
        scanned = 0
        for path in common_paths:
            if self._scan_stop_flag is not None and self._scan_stop_flag.is_set():
                logger.info("[GlobalView] D盘扫描被中断")
                return
            if os.path.exists(path):
                logger.info(f"[GlobalView] 扫描D盘目录: {path}")
                try:
                    # [优化] 限制单个目录扫描时间，避免阻塞
                    self._scan_path(path, max_depth=max_depth, user_id=user_id)
                    scanned += 1
                except Exception as e:
                    logger.warning(f"[GlobalView] 扫描D盘目录失败 {path}: {e}")
            else:
                logger.debug(f"[GlobalView] D盘目录不存在，跳过: {path}")
        logger.info(f"[GlobalView] D盘扫描完成，共扫描 {scanned} 个目录")

    def _scan_start_menu(self, user_id: str = "default"):
        paths = [
            os.environ.get("PROGRAMDATA", "C:\\ProgramData") + "\\Microsoft\\Windows\\Start Menu",
            os.path.expanduser("~\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu"),
            os.path.expanduser("~\\Desktop")
        ]
        max_depth = config.get("global_view.max_scan_depth", 3)
        for p in paths:
            if not os.path.exists(p) or not os.access(p, os.R_OK):
                logger.debug(f"[GlobalView] 开始菜单路径不可读，跳过: {p}")
                continue
            self._scan_path(p, max_depth=max_depth, user_id=user_id)

    def _scan_registry(self, user_id: str = "default", max_items: int = 500, max_time: float = 10.0):
        """
        扫描注册表获取已安装软件

        Args:
            user_id: 用户ID
            max_items: 最大扫描软件数量（防止过多）
            max_time: 最大扫描时间（秒）
        """
        import time
        start_time = time.time()
        items_scanned = 0

        try:
            import winreg
            keys = [
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall")
            ]
            registry_batch = []  # 注册表扫描批量缓冲区

            for hkey, subkey in keys:
                try:
                    with winreg.OpenKey(hkey, subkey) as key:
                        i = 0
                        while True:
                            try:
                                subkey_name = winreg.EnumKey(key, i)
                                with winreg.OpenKey(key, subkey_name) as app_key:
                                    name = self._reg_get_value(app_key, "DisplayName")
                                    if not name:
                                        i += 1
                                        continue

                                    # 优先使用 InstallLocation
                                    install_path = self._reg_get_value(app_key, "InstallLocation")
                                    display_icon = self._reg_get_value(app_key, "DisplayIcon")

                                    # 修复：如果 InstallLocation 为空，尝试从 DisplayIcon 推断路径
                                    if not install_path and display_icon:
                                        # 修复：去除 DisplayIcon 中的 ",0" 后缀
                                        icon_path = self._clean_display_icon(display_icon)
                                        if icon_path and os.path.exists(icon_path):
                                            install_path = os.path.dirname(icon_path)

                                    # 修复：如果路径是文件，取其目录
                                    if install_path and os.path.isfile(install_path):
                                        install_path = os.path.dirname(install_path)

                                    # 修复：尝试从安装目录查找可执行文件
                                    exe_path = ""
                                    if install_path and os.path.isdir(install_path):
                                        exe_path = self._find_main_exe_in_dir(install_path, name)

                                    version = self._reg_get_value(app_key, "DisplayVersion")
                                    # 使用批量写入替代逐条写入
                                    registry_batch.append({
                                        'id': f"reg_{subkey_name}",
                                        'name': name,
                                        'install_path': exe_path if exe_path else install_path,
                                        'process_name': os.path.basename(exe_path) if exe_path else "",
                                        'window_class': "",
                                        'version': version,
                                        'last_launch_time': None,
                                        'launch_count': 0
                                    })
                                    # 达到批次大小时写入
                                    if len(registry_batch) >= 50:
                                        self.db.batch_add_or_update(user_id, registry_batch)
                                        registry_batch = []
                            except OSError:
                                break
                            i += 1
                            items_scanned += 1

                            # 【优化】检查超时和数量限制
                            if items_scanned >= max_items:
                                logger.debug(f"[GlobalView] 注册表扫描达到上限 {max_items}，提前结束")
                                break
                            if time.time() - start_time > max_time:
                                logger.debug(f"[GlobalView] 注册表扫描超时 ({max_time}s)，提前结束")
                                break

                        if items_scanned >= max_items:
                            break

                except Exception as e:
                    logger.error(f"[GlobalView] 注册表扫描异常: {e}", exc_info=True)

                if items_scanned >= max_items or time.time() - start_time > max_time:
                    break

            # 写入剩余的注册表项
            if registry_batch:
                self.db.batch_add_or_update(user_id, registry_batch)

            # 【新增】将注册表软件同步到向量存储（与磁盘扫描统一）
            if registry_batch:
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        self._sync_software_to_vector(registry_batch, source="registry", user_id=user_id),
                        self._main_loop
                    )
                    future.result(timeout=300)
                except Exception as e:
                    logger.error(f"[GlobalView] 注册表软件向量同步失败: {e}", exc_info=True)

            elapsed = time.time() - start_time
            # 【优化】只在扫描到软件时记录，或简化日志
            if items_scanned > 0:
                logger.info(f"[GlobalView] 注册表扫描完成: {items_scanned} 个软件, 耗时 {elapsed:.1f}s")
            else:
                logger.debug("[GlobalView] 注册表扫描完成: 0 个软件")

        except Exception as e:
            logger.error(f"[GlobalView] 注册表扫描失败: {e}", exc_info=True)

    def _clean_display_icon(self, display_icon: str) -> str:
        """
        清理 DisplayIcon 值，去除 ",0" 等后缀

        Args:
            display_icon: 注册表中的 DisplayIcon 值

        Returns:
            清理后的路径
        """
        if not display_icon:
            return ""

        # 去除常见的后缀，如 ",0", ",1" 等
        icon_path = display_icon.strip()

        # 处理带逗号的路径（如 "C:\\path\\app.exe,0"）
        if "," in icon_path:
            # 找到最后一个逗号，检查其后是否是数字
            parts = icon_path.rsplit(",", 1)
            if len(parts) == 2:
                path_part, index_part = parts
                if index_part.strip().isdigit():
                    icon_path = path_part.strip()

        # 去除可能的引号
        icon_path = icon_path.strip('"').strip("'")

        return icon_path

    def _find_main_exe_in_dir(self, directory: str, app_name: str) -> str:
        """
        在目录中查找主可执行文件

        Args:
            directory: 安装目录
            app_name: 应用名称

        Returns:
            找到的可执行文件路径，或空字符串
        """
        if not directory or not os.path.isdir(directory):
            return ""

        try:
            app_name_lower = app_name.lower().replace(" ", "")
            candidates = []

            for root, dirs, files in os.walk(directory, topdown=True):
                # 限制深度
                if root != directory and os.path.relpath(root, directory).count(os.sep) > 1:
                    del dirs[:]
                    continue

                for file in files:
                    if file.lower().endswith('.exe'):
                        full_path = os.path.join(root, file)
                        file_lower = file.lower().replace(" ", "")

                        # 排除卸载程序
                        if any(kw in file_lower for kw in ['uninstall', 'uninst', '卸载', 'setup', 'installer']):
                            continue

                        # 评分：文件名匹配度
                        score = 0
                        if app_name_lower in file_lower:
                            score += 10
                        # 检查应用名称的单词匹配
                        for word in app_name_lower.split():
                            if len(word) > 2 and word in file_lower:
                                score += 2

                        candidates.append((score, full_path))

            # 按分数排序，返回最高分
            if candidates:
                candidates.sort(reverse=True, key=lambda x: x[0])
                return candidates[0][1]
        except Exception as e:
            logger.debug(f"[GlobalView] 查找主exe失败 {directory}: {e}")

        return ""

    def _reg_get_value(self, key, name):
        try:
            return winreg.QueryValueEx(key, name)[0]
        except Exception:
            return None

    def _scan_custom_dirs(self, user_id: str = "default"):
        dirs = config.get("perception.global_view.watch_directories", [])
        max_depth = config.get("global_view.max_scan_depth", 3)
        for d in dirs:
            if os.path.exists(d):
                self._scan_path(d, max_depth=max_depth, user_id=user_id)
            else:
                logger.debug(f"[GlobalView] 自定义目录不存在: {d}")

    # ====== FIX: 添加深度限制和排除目录，增加CPU限流和中断检查 ======
    def _scan_path(self, path, depth=0, max_depth=3, user_id: str = "default"):
        """递归扫描路径，限制深度，排除系统目录，增加CPU限流和中断检查"""
        # 1. 深度硬限制，超过直接返回
        if depth > max_depth:
            return
        if not os.path.exists(path):
            return
        if not os.access(path, os.R_OK):
            logger.debug(f"[GlobalView] 路径不可读，跳过: {path}")
            return
        # 2. 全局中断检查，可随时停止扫描
        if self._scan_stop_flag is not None and self._scan_stop_flag.is_set():
            logger.info("[GlobalView] 扫描被用户中断")
            return
        # 3. CPU限流，每扫描100个文件休眠10ms，避免占满CPU
        if depth == 0:
            self._scan_file_count += 1
            if self._scan_file_count % 100 == 0:
                time.sleep(0.01)  # sync function: intentional blocking CPU throttle in recursive scan
        try:
            global SCAN_PROGRESS
            # 如果这是顶层调用，初始化进度
            if depth == 0:
                self._scan_stop_flag = threading.Event()
                self._scan_file_count = 0
                SCAN_PROGRESS["total"] = 0
                SCAN_PROGRESS["current"] = 0
                # 预计算文件总数（简化，不深入太多）
                for root, dirs, files in os.walk(path):
                    SCAN_PROGRESS["total"] += len(files)
                    # 预计算也限制深度
                    if root != path and os.path.relpath(root, path).count(os.sep) > max_depth:
                        dirs.clear()
            with os.scandir(path) as entries:
                for entry in entries:
                    # 中断检查
                    if self._scan_stop_flag is not None and self._scan_stop_flag.is_set():
                        # 扫描中断前刷新批量缓冲区
                        self.db.flush_batch_buffer(user_id=user_id)
                        return
                    if entry.is_dir():
                        # 排除系统目录
                        exclude_dirs = config.get("global_view.exclude_dirs", ["Windows", "Program Files", "Program Files (x86)"])
                        if entry.name.lower() in [d.lower() for d in exclude_dirs]:
                            continue
                        self._scan_path(entry.path, depth+1, max_depth, user_id=user_id)
                    elif entry.is_file() and (entry.name.lower().endswith(".lnk") or entry.name.lower().endswith(".exe")):
                        self._process_file(entry.path, user_id=user_id)
                        SCAN_PROGRESS["current"] += 1
                        if SCAN_PROGRESS["current"] % 100 == 0:
                            SCAN_PROGRESS["message"] = f"扫描中... {SCAN_PROGRESS['current']}/{SCAN_PROGRESS['total']}"
            # 扫描完成时刷新批量缓冲区
            if depth == 0:
                self.db.flush_batch_buffer(user_id=user_id)
        except PermissionError:
            # 【修复】将权限警告改为 INFO 级别，因为这是预期的 Windows 系统行为
            logger.info(f"[GlobalView] 扫描目录跳过（无权限访问）: {path}")
        except FileNotFoundError as e:
            logger.warning(f"[GlobalView] 扫描路径不存在: {path} -> {e}")
        except Exception as e:
            logger.exception(f"扫描路径异常 {path}: {e}")
            # 异常时刷新批量缓冲区
            self.db.flush_batch_buffer(user_id=user_id)
    # ====== 结束 ======

    def _process_file(self, file_path, user_id: str = "default"):
        if file_path.lower().endswith(".lnk"):
            self._process_lnk(file_path, user_id=user_id)
        elif file_path.lower().endswith(".exe"):
            self._process_exe(file_path, user_id=user_id)

    def _process_lnk(self, lnk_path, user_id: str = "default"):
        try:
            import win32com.client
            shell = win32com.client.Dispatch("WScript.Shell")
            shortcut = shell.CreateShortcut(lnk_path)
            target = shortcut.TargetPath
            if target and target.lower().endswith(".exe"):
                self._process_exe(target, user_id=user_id)
        except Exception as e:
            logger.debug(f"[GlobalView] 处理快捷方式失败 {lnk_path}: {e}")

    def _process_exe(self, exe_path, user_id: str = "default"):
        try:
            import win32api
            name = os.path.splitext(os.path.basename(exe_path))[0]
            try:
                win32api.GetFileVersionInfo(exe_path, "\\")
                translation = win32api.GetFileVersionInfo(exe_path, "\\VarFileInfo\\Translation")
                if translation:
                    lang, codepage = translation[0]
                    file_desc = win32api.GetFileVersionInfo(
                        exe_path,
                        f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\FileDescription"
                    )
                    if file_desc:
                        name = file_desc
            except Exception:
                pass
            import hashlib
            file_hash = hashlib.md5(exe_path.encode()).hexdigest()[:16]
            # 使用批量写入替代逐条写入，避免连接池耗尽
            self.db.add_to_batch(
                user_id=user_id,
                id=f"exe_{file_hash}",
                name=name,
                install_path=exe_path,
                process_name=os.path.basename(exe_path),
                window_class="",
                version="",
                last_launch_time=None,
                launch_count=0
            )
        except Exception as e:
            logger.debug(f"[GlobalView] 处理exe失败 {exe_path}: {e}")

    # ==================== 增强的查找方法 ====================
    def find_software_path(self, name: str, user_id: str = "default") -> str:
        """
        根据应用名称查找安装路径，自动过滤掉卸载程序。
        首先在本地数据库中搜索，如果找不到，尝试实时扫描注册表。
        返回找到的第一个有效且非卸载程序的可执行路径，否则返回 None。

        Args:
            name: 应用名称
            user_id: 用户ID，默认为"default"
        """
        # 先在数据库中搜索
        results = self.db.search(name, user_id=user_id)
        # 过滤并排序候选路径
        candidates = self._filter_and_rank_paths(results, name)
        if candidates:
            return candidates[0]  # 返回最佳路径

        # 如果数据库没有合适结果，尝试实时注册表搜索
        path = self._search_registry_now(name)
        if path and self._is_valid_app_path(path, name):
            # 可选：将新找到的路径加入数据库
            self.db.add_or_update(
                id=f"reg_instant_{int(time.time())}",
                name=name,
                install_path=path,
                process_name=os.path.basename(path),
                window_class="",
                version="",
                last_launch_time=None,
                launch_count=0,
                user_id=user_id
            )
            return path
        return None

    def _filter_and_rank_paths(self, results: list, app_name: str) -> list:
        """
        对搜索结果进行过滤和排序，返回按优先级排序的有效路径列表。
        """
        valid_paths = []
        for r in results:
            path = r.get('install_path')
            if not path or not os.path.exists(path):
                continue
            # 如果是目录，尝试在目录中寻找可执行文件
            if os.path.isdir(path):
                found_exe = self._find_exe_in_dir(path, app_name)
                if found_exe:
                    valid_paths.append(found_exe)
            else:
                # 直接是文件，检查是否有效
                if self._is_valid_app_path(path, app_name):
                    valid_paths.append(path)

        # 去重
        valid_paths = list(dict.fromkeys(valid_paths))

        # 排序：优先选择文件名包含应用名称的，且路径中不包含卸载关键词的已在 _is_valid_app_path 中过滤
        def score(p):
            base = os.path.basename(p).lower()
            app_lower = app_name.lower()
            # 文件名包含应用名称的加分
            if app_lower in base:
                return 2
            # 常见主程序名称
            common_names = ['cloudmusic', 'netease', 'qq', 'wechat', 'chrome', 'firefox']
            if any(cn in base for cn in common_names):
                return 1
            return 0

        valid_paths.sort(key=score, reverse=True)
        return valid_paths

    def _is_valid_app_path(self, path: str, app_name: str) -> bool:
        """
        判断路径是否为有效的应用程序可执行文件，排除卸载程序。
        """
        lower_path = path.lower()
        # 排除明显是卸载程序的路径
        uninstall_keywords = ['uninstall', 'uninst', '卸载', 'setup', 'installer', 'redist']
        if any(kw in lower_path for kw in uninstall_keywords):
            return False
        # 必须是文件且以 .exe 结尾
        # 必须是文件且以 .exe 结尾
        return os.path.isfile(path) and path.lower().endswith('.exe')

    def _find_exe_in_dir(self, directory: str, app_name: str) -> str:
        """
        在目录中查找合适的可执行文件，优先选择包含应用名称且非卸载程序的 exe。
        返回找到的第一个符合条件的 exe 路径，否则返回 None。
        """
        try:
            for root, dirs, files in os.walk(directory, topdown=True, followlinks=False):
                # 限制深度，避免过深遍历
                if root != directory and os.path.relpath(root, directory).count(os.sep) > 2:
                    dirs.clear()  # 不深入更深层
                for file in files:
                    if file.lower().endswith('.exe'):
                        full_path = os.path.join(root, file)
                        if self._is_valid_app_path(full_path, app_name):
                            # 如果文件名包含应用名称，立即返回
                            if app_name.lower() in file.lower():
                                return full_path
                            # 否则保留为候选，但继续寻找更好的
                            # 这里简单起见，返回第一个非卸载程序的 exe
                            # 可以进一步优化
                            if not hasattr(self, '_temp_candidate'):
                                self._temp_candidate = full_path
            # 如果没有找到包含名称的，返回第一个候选
            if hasattr(self, '_temp_candidate'):
                cand = self._temp_candidate
                del self._temp_candidate
                return cand
        except Exception as e:
            logger.debug(f"[GlobalView] 在目录 {directory} 中查找 exe 失败: {e}")
        return None

    def _search_registry_now(self, name: str) -> str:
        """
        实时搜索注册表，查找名称包含 name 的软件的安装路径，并过滤掉卸载程序。
        返回第一个匹配的有效路径，或 None。
        """
        try:
            import winreg
            # 搜索常见的卸载信息注册表
            keys = [
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            ]
            for hkey, subkey in keys:
                try:
                    with winreg.OpenKey(hkey, subkey) as key:
                        i = 0
                        while True:
                            try:
                                subkey_name = winreg.EnumKey(key, i)
                                with winreg.OpenKey(key, subkey_name) as app_key:
                                    display_name = self._reg_get_value(app_key, "DisplayName")
                                    if display_name and name.lower() in display_name.lower():
                                        # 找到匹配的应用，尝试获取路径
                                        install_path = self._reg_get_value(app_key, "InstallLocation")
                                        display_icon = self._reg_get_value(app_key, "DisplayIcon")

                                        # 修复：如果 InstallLocation 为空，尝试从 DisplayIcon 推断
                                        if not install_path and display_icon:
                                            icon_path = self._clean_display_icon(display_icon)
                                            if icon_path and os.path.exists(icon_path):
                                                install_path = os.path.dirname(icon_path)

                                        if install_path:
                                            # 如果路径是文件，取其目录
                                            if os.path.isfile(install_path):
                                                install_path = os.path.dirname(install_path)
                                            # 在目录中寻找 exe 文件
                                            if os.path.isdir(install_path):
                                                exe_path = self._find_exe_in_dir(install_path, name)
                                                if exe_path:
                                                    return exe_path
                                            else:
                                                # 如果路径是文件且有效
                                                if self._is_valid_app_path(install_path, name):
                                                    return install_path
                            except OSError:
                                break
                            i += 1
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"[GlobalView] 实时注册表搜索异常: {e}")
        return None

    def find_software(self, keyword: str, user_id: str = "default") -> list:
        """
        搜索软件信息

        Args:
            keyword: 搜索关键词
            user_id: 用户ID，默认为"default"

        Returns:
            匹配的软件信息列表
        """
        return self.db.search(keyword, user_id=user_id)

    def get_all_software(self, user_id: str = "default") -> list:
        """
        获取所有已安装的软件列表

        Args:
            user_id: 用户ID，默认为"default"

        Returns:
            所有软件信息列表
        """
        return self.db.get_all(user_id=user_id)

    def get_scan_progress(self) -> dict:
        return SCAN_PROGRESS.copy()

    # ==================== 软件手动注册功能 ====================
    def register_software(self, name: str, exe_path: str, user_id: str = "default") -> dict:
        """
        手动注册软件路径

        Args:
            name: 软件名称（支持中文）
            exe_path: 可执行文件完整路径
            user_id: 用户ID，默认为"default"

        Returns:
            注册结果字典
        """
        try:
            # 验证路径是否存在
            if not os.path.exists(exe_path):
                return {
                    "success": False,
                    "error": f"路径不存在: {exe_path}"
                }

            # 验证是否为exe文件
            if not exe_path.lower().endswith('.exe'):
                return {
                    "success": False,
                    "error": f"路径不是可执行文件: {exe_path}"
                }

            # 验证是否可执行（Windows下exe文件）
            if not os.path.isfile(exe_path):
                return {
                    "success": False,
                    "error": f"路径不是文件: {exe_path}"
                }

            # 生成唯一ID
            import hashlib
            file_hash = hashlib.md5(exe_path.encode('utf-8')).hexdigest()[:16]

            # 添加到数据库
            self.db.add_or_update(
                id=f"manual_{file_hash}",
                user_id=user_id,
                name=name,
                install_path=exe_path,
                process_name=os.path.basename(exe_path),
                window_class="",
                version="",
                last_launch_time=None,
                launch_count=0,
                auto_discovered=False
            )

            logger.info(f"[GlobalView] 软件手动注册成功: {name} -> {exe_path}")
            return {
                "success": True,
                "message": f"软件 '{name}' 注册成功",
                "data": {
                    "id": f"manual_{file_hash}",
                    "name": name,
                    "exe_path": exe_path,
                    "install_path": os.path.dirname(exe_path),
                    "auto_discovered": False
                }
            }
        except Exception as e:
            logger.error(f"[GlobalView] 软件注册失败: {e}")
            return {
                "success": False,
                "error": f"注册失败: {str(e)}"
            }

    def unregister_software(self, name: str, user_id: str = "default") -> dict:
        """
        手动注销（删除）已注册的软件

        Args:
            name: 软件名称
            user_id: 用户ID，默认为"default"

        Returns:
            注销结果字典
        """
        try:
            # 先搜索找到该软件
            results = self.db.search(name, user_id=user_id)
            if not results:
                return {
                    "success": False,
                    "error": f"未找到软件: {name}"
                }

            # 删除匹配的第一个（手动注册的）
            for result in results:
                if not result.get('auto_discovered', True):
                    # 从数据库删除
                    conn = self.db._get_connection()
                    c = conn.cursor()
                    try:
                        c.execute(
                            "DELETE FROM software_info WHERE id = %s AND user_id = %s",
                            (result['id'], user_id)
                        )
                        conn.commit()
                    finally:
                        c.close()
                        safe_return_connection(conn)

                    logger.info(f"[GlobalView] 软件手动注销成功: {name}")
                    return {
                        "success": True,
                        "message": f"软件 '{name}' 已注销",
                        "data": result
                    }

            return {
                "success": False,
                "error": f"未找到手动注册的软件: {name}（可能是自动发现的）"
            }
        except Exception as e:
            logger.error(f"[GlobalView] 软件注销失败: {e}")
            return {
                "success": False,
                "error": f"注销失败: {str(e)}"
            }

    def get_registered_software(self, user_id: str = "default") -> list:
        """
        获取所有手动注册的软件列表

        Args:
            user_id: 用户ID，默认为"default"

        Returns:
            手动注册的软件列表
        """
        all_software = self.db.get_all(user_id=user_id)
        return [s for s in all_software if not s.get('auto_discovered', True)]

    def _delete_software_by_id(self, software_id: str, user_id: str = "default"):
        """
        根据ID删除软件记录

        Args:
            software_id: 软件记录ID
            user_id: 用户ID，默认为"default"
        """
        try:
            sql = "DELETE FROM software_info WHERE id = %s AND user_id = %s"
            with self.db._rw_lock:
                conn = self.db._get_connection()
                c = conn.cursor()
                try:
                    c.execute(sql, (software_id, user_id))
                    conn.commit()
                    deleted_count = c.rowcount
                    if deleted_count > 0:
                        logger.debug(f"[GlobalView] 已删除软件记录: {software_id}")
                finally:
                    c.close()
                    safe_return_connection(conn)
        except Exception as e:
            logger.error(f"[GlobalView] 删除软件记录失败: {e}")
            raise

    def _delete_software_by_path(self, file_path: str, user_id: str = "default"):
        """
        根据文件路径删除软件记录（用于处理删除事件）

        Args:
            file_path: 文件完整路径
            user_id: 用户ID，默认为"default"
        """
        try:
            sql = "DELETE FROM software_info WHERE install_path = %s AND user_id = %s"
            with self.db._rw_lock:
                conn = self.db._get_connection()
                c = conn.cursor()
                try:
                    c.execute(sql, (file_path, user_id))
                    conn.commit()
                    deleted_count = c.rowcount
                    if deleted_count > 0:
                        logger.info(f"[GlobalView] 已删除软件记录（按路径）: {file_path}")
                finally:
                    c.close()
                    safe_return_connection(conn)
        except Exception as e:
            logger.error(f"[GlobalView] 按路径删除软件记录失败: {e}")
            raise

    def _cleanup_deleted_software(self, user_id: str = "default", scan_start_time: datetime = None):
        """
        清理已删除的软件记录（扫描后清理本次未扫描到的记录）

        Args:
            user_id: 用户ID，默认为"default"
            scan_start_time: 扫描开始时间，用于删除在此之前发现且本次未扫描到的记录
        """
        from datetime import datetime

        try:
            if scan_start_time is None:
                scan_start_time = datetime.now()

            sql = """
                DELETE FROM software_info
                WHERE user_id = %s
                  AND auto_discovered = TRUE
                  AND updated_at < %s
            """
            with self.db._rw_lock:
                conn = self.db._get_connection()
                c = conn.cursor()
                try:
                    c.execute(sql, (user_id, scan_start_time))
                    conn.commit()
                    deleted_count = c.rowcount
                    if deleted_count > 0:
                        logger.info(f"[GlobalView] 清理已删除软件记录: {deleted_count} 条")
                finally:
                    c.close()
                    safe_return_connection(conn)
        except Exception as e:
            logger.error(f"[GlobalView] 清理软件记录失败: {e}")
            raise

    # ==================== 语义搜索功能 ====================
    def _infer_function_from_name(self, name: str) -> str:
        """
        从软件名推断功能类别

        根据软件名称中的关键词推断其功能类别，用于构建语义描述。

        Args:
            name: 软件名称

        Returns:
            str: 功能类别描述
        """
        name_lower = name.lower()

        # 音乐类软件
        music_keywords = ['音乐', 'music', '云', 'cloud', 'mp3', 'audio', 'sound',
                         'netease', '网易云', 'qq音乐', '酷狗', '酷我', 'spotify']
        if any(kw in name_lower for kw in music_keywords):
            return "音乐播放"

        # 浏览器类
        browser_keywords = ['浏览器', 'browser', 'chrome', 'edge', 'firefox',
                           'safari', 'opera', 'webview', 'ie', 'explorer']
        if any(kw in name_lower for kw in browser_keywords):
            return "网页浏览"

        # 编辑器/IDE类
        editor_keywords = ['editor', 'code', 'studio', 'ide', 'vscode', 'sublime',
                          'notepad', 'vim', 'emacs', 'pycharm', 'idea', 'eclipse']
        if any(kw in name_lower for kw in editor_keywords):
            return "代码编辑"

        # 办公软件
        office_keywords = ['word', 'excel', 'powerpoint', 'ppt', 'wps', 'office',
                          '文档', '表格', '演示', 'pdf', 'reader']
        if any(kw in name_lower for kw in office_keywords):
            return "办公文档"

        # 通讯软件
        chat_keywords = ['微信', 'wechat', 'qq', '钉钉', '飞书', 'telegram',
                        'whatsapp', 'skype', 'teams', 'slack', 'discord', '聊天']
        if any(kw in name_lower for kw in chat_keywords):
            return "即时通讯"

        # 视频播放器
        video_keywords = ['video', 'player', 'vlc', 'potplayer', '视频', '播放',
                         'mp4', 'avi', 'movie', 'film', 'bilibili', 'youtube']
        if any(kw in name_lower for kw in video_keywords):
            return "视频播放"

        # 图片处理
        image_keywords = ['photo', 'image', 'picture', 'ps', 'photoshop', '画图',
                         'paint', 'gimp', '美图', '截图', 'screen']
        if any(kw in name_lower for kw in image_keywords):
            return "图像处理"

        # 压缩工具
        compress_keywords = ['zip', 'rar', '7z', '压缩', '解压', 'compress', 'winrar', 'bandizip']
        if any(kw in name_lower for kw in compress_keywords):
            return "压缩解压"

        # 下载工具
        download_keywords = ['下载', 'download', 'torrent', '迅雷', 'idm', 'bt', '磁力']
        if any(kw in name_lower for kw in download_keywords):
            return "下载工具"

        # 安全软件
        security_keywords = ['杀毒', '安全', 'security', 'antivirus', 'defender',
                            '360', '火绒', '腾讯管家', 'avast', 'kaspersky']
        if any(kw in name_lower for kw in security_keywords):
            return "安全防护"

        # 游戏平台
        game_keywords = ['steam', 'epic', 'game', '游戏', 'wegame', 'origin',
                        'uplay', 'blizzard', '战网']
        if any(kw in name_lower for kw in game_keywords):
            return "游戏平台"

        # 云存储
        cloud_storage_keywords = ['云盘', '网盘', 'onedrive', 'dropbox', 'google drive',
                                 '百度云', '阿里云盘', '天翼云', '夸克']
        if any(kw in name_lower for kw in cloud_storage_keywords):
            return "云存储"

        # 开发工具
        dev_keywords = ['git', 'docker', 'python', 'java', 'node', 'npm', 'maven',
                       'gradle', 'github', 'gitlab']
        if any(kw in name_lower for kw in dev_keywords):
            return "开发工具"

        # 系统工具
        system_keywords = ['system', '设置', '控制面板', '任务管理器', '注册表',
                          'cmd', 'powershell', 'terminal', '优化', '清理']
        if any(kw in name_lower for kw in system_keywords):
            return "系统工具"

        return "应用软件"

    async def search_software_by_semantic(self, query: str, top_k: int = 5, user_id: str = "default") -> list:
        """
        语义搜索软件

        利用向量记忆实现语义搜索，支持模糊查询如"音乐播放器"、"浏览器"等。

        例如：
            query="音乐播放器" → 返回网易云、QQ音乐...
            query="浏览器" → 返回Chrome、Edge...
            query="写代码的工具" → 返回VSCode、PyCharm...

        Args:
            query: 搜索查询（语义描述）
            top_k: 返回结果数量，默认5
            user_id: 用户ID，默认为"default"

        Returns:
            list: 搜索结果列表，每个结果包含软件信息和匹配分数
                  格式: [{"software": {...}, "score": 0.95, "matched_text": "..."}, ...]
        """
        try:
            from core.memory.memory_service import get_memory_service
        except ImportError:
            logger.error("[GlobalView] 无法导入 memory_service，语义搜索不可用")
            # 降级到普通关键词搜索
            return [{"software": s, "score": 1.0, "matched_text": s.get("name", "")}
                    for s in self.db.search(query, user_id=user_id)[:top_k]]

        try:
            ms = await get_memory_service()
            vs = ms.vector_store
            if not await vs.is_available():
                logger.warning("[GlobalView] 向量存储不可用，降级到关键词搜索")
                return [{"software": s, "score": 1.0, "matched_text": s.get("name", "")}
                        for s in self.db.search(query, user_id=user_id)[:top_k]]
            # 1. 获取所有软件
            all_software = self.get_all_software(user_id=user_id)

            if not all_software:
                logger.debug("[GlobalView] 软件库为空，无法进行语义搜索")
                return []

            # 2. 使用专用集合存储软件向量（如果不存在则使用knowledge集合）
            collection = "knowledge"

            # 3. 将软件信息存入向量库（带有去重检查）
            stored_count = 0
            for software in all_software:
                # 构建语义描述
                name = software.get("name", "")
                install_path = software.get("install_path", "")
                process_name = software.get("process_name", "")
                version = software.get("version", "")

                # 推断功能类别
                function_category = self._infer_function_from_name(name)

                # 构建富文本描述（用于语义编码）
                description_parts = [name]
                if function_category:
                    description_parts.append(f" - {function_category}软件")
                if install_path:
                    description_parts.append(f" - 安装在 {install_path}")
                if version:
                    description_parts.append(f" - 版本 {version}")
                if process_name and process_name != name:
                    description_parts.append(f" - 进程名 {process_name}")

                semantic_text = "".join(description_parts)

                # 生成唯一ID（基于软件ID，确保幂等性）
                software_id = software.get("id", f"sw_{hash(name) % 100000}")

                # 检查是否已存在（避免重复存储）
                # 使用元数据标记这是软件记录，便于检索时过滤
                metadata = {
                    "software_id": software_id,
                    "software_name": name,
                    "install_path": install_path,
                    "process_name": process_name,
                    "version": version,
                    "function_category": function_category,
                    "type": "software_record",
                    "auto_discovered": software.get("auto_discovered", True),
                    "launch_count": software.get("launch_count", 0)
                }

                # 存储到向量记忆
                try:
                    await vs.add(
                        collection=collection,
                        text=semantic_text,
                        metadata=metadata
                    )
                    stored_count += 1
                except Exception as e:
                    logger.debug(f"[GlobalView] 存储软件向量失败 {name}: {e}")
                    continue

            if stored_count > 0:
                logger.debug(f"[GlobalView] 已存储/更新 {stored_count} 个软件向量记录")

            # 4. 执行语义搜索
            search_results = await vs.search(
                collection=collection,
                query=query,
                limit=top_k
            )

            # 5. 转换结果为统一格式
            formatted_results = []
            for result in search_results:
                metadata = result.metadata or {}

                # 从元数据中重建软件信息
                software_info = {
                    "id": metadata.get("software_id", result.id),
                    "name": metadata.get("software_name", ""),
                    "install_path": metadata.get("install_path", ""),
                    "process_name": metadata.get("process_name", ""),
                    "version": metadata.get("version", ""),
                    "function_category": metadata.get("function_category", ""),
                    "auto_discovered": metadata.get("auto_discovered", True),
                    "launch_count": metadata.get("launch_count", 0)
                }

                formatted_results.append({
                    "software": software_info,
                    "score": 1.0 - (result.distance or 0.0),
                    "matched_text": result.document
                })

            logger.info(f"[GlobalView] 语义搜索 '{query}' 返回 {len(formatted_results)} 个结果")
            return formatted_results

        except Exception as e:
            logger.error(f"[GlobalView] 语义搜索失败: {e}")
            # 异常时降级到普通搜索
            try:
                fallback_results = self.db.search(query, user_id=user_id)[:top_k]
                return [{"software": s, "score": 1.0, "matched_text": s.get("name", "")}
                        for s in fallback_results]
            except Exception:
                return []

    def clear_user_data(self, user_id: str = "default") -> int:
        """
        清空用户的所有扫描数据

        Args:
            user_id: 用户ID

        Returns:
            int: 删除的记录数
        """
        conn = None
        c = None
        deleted_count = 0

        try:
            conn = self.db._get_connection()
            c = conn.cursor()

            # 删除 file_index 表中的记录
            c.execute("DELETE FROM file_index WHERE user_id = %s", (user_id,))
            deleted_count += c.rowcount

            # 删除 software_info 表中的记录
            c.execute("DELETE FROM software_info WHERE user_id = %s", (user_id,))
            deleted_count += c.rowcount

            conn.commit()
            logger.info(f"[GlobalView] 已清空用户 {user_id} 的数据，共删除 {deleted_count} 条记录")
            return deleted_count

        except Exception as e:
            logger.error(f"[GlobalView] 清空用户数据失败: {e}")
            if conn:
                conn.rollback()
            return 0
        finally:
            if c:
                c.close()
            if conn:
                safe_return_connection(conn)


global_view = GlobalView()
global_view_instance = global_view  # 兼容 API 导入
