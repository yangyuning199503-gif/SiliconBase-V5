#!/usr/bin/env python3
"""
SiliconBase V5 - 服务管理器

功能：
- 一键启动/停止所有服务
- 健康检查
- 自动重启
- 日志聚合
- Windows 服务注册

使用方法：
    python scripts/service_manager.py start    # 启动服务
    python scripts/service_manager.py stop     # 停止服务
    python scripts/service_manager.py restart  # 重启服务
    python scripts/service_manager.py status   # 查看状态
    python scripts/service_manager.py install  # 安装为Windows服务
    python scripts/service_manager.py uninstall # 卸载Windows服务

作者: SiliconBase Team
版本: 1.0.0
"""

import logging
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/service_manager.log', encoding='utf-8')
    ]
)
logger = logging.getLogger('ServiceManager')

# 配置
BASE_DIR = Path(__file__).parent.parent
BACKEND_DIR = BASE_DIR
FRONTEND_DIR = BASE_DIR / "frontend"
VENV_PYTHON = BACKEND_DIR / ".venv" / "Scripts" / "python.exe"

# 端口配置
BACKEND_PORT = 8600
FRONTEND_PORT = 5173
WS_PORT = 8600  # WebSocket 已统一由 FastAPI 在 8600 端口处理
STATUS_PORT = 8701
REDIS_PORT = 6379

# 进程跟踪
_processes: dict[str, subprocess.Popen] = {}
_shutdown_event = threading.Event()


@dataclass
class ServiceStatus:
    """服务状态"""
    name: str
    running: bool
    pid: int | None = None
    port: int | None = None
    url: str | None = None
    last_check: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class ServiceManager:
    """服务管理器"""

    def __init__(self):
        self.processes = {}
        self.log_dir = BASE_DIR / "logs"
        self.log_dir.mkdir(exist_ok=True)

    def _check_port(self, port: int) -> bool:
        """检查端口是否被占用"""
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                result = s.connect_ex(('localhost', port))
                return result == 0
        except Exception:
            return False

    def _kill_port_process(self, port: int):
        """杀死占用端口的进程"""
        try:
            if sys.platform == 'win32':
                # Windows: 使用 netstat 查找 PID 然后 taskkill
                result = subprocess.run(
                    ['netstat', '-ano', '-p', 'tcp'],
                    capture_output=True,
                    text=True
                )
                for line in result.stdout.split('\n'):
                    if f':{port}' in line and 'LISTENING' in line:
                        parts = line.split()
                        if len(parts) >= 5:
                            pid = parts[-1]
                            subprocess.run(['taskkill', '/F', '/PID', pid],
                                         capture_output=True)
                            logger.info(f"已杀死占用端口 {port} 的进程 PID={pid}")
        except Exception as e:
            logger.warning(f"清理端口 {port} 失败: {e}")

    def _wait_for_service(self, url: str, timeout: int = 60) -> bool:
        """等待服务启动"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                req = urllib.request.Request(url, method='HEAD')
                req.add_header('User-Agent', 'SiliconBase-ServiceManager/1.0')
                with urllib.request.urlopen(req, timeout=2) as response:
                    if response.status == 200:
                        return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def start_redis(self) -> bool:
        """启动 Redis 服务"""
        logger.info("启动 Redis 服务...")

        # 检查端口是否已被占用
        if self._check_port(REDIS_PORT):
            logger.info(f"Redis 已在端口 {REDIS_PORT} 运行")
            return True

        # 按优先级查找 redis-server.exe
        redis_paths = [
            BASE_DIR.parent / "tools" / "redis" / "redis-server.exe",
            BASE_DIR / "redis" / "redis-server.exe",
            Path("C:/Program Files/Redis/redis-server.exe"),
            Path("C:/Redis/redis-server.exe"),
        ]

        redis_server = None
        redis_conf = None
        for path in redis_paths:
            if path.exists():
                redis_server = path
                conf = path.parent / "redis.windows.conf"
                if conf.exists():
                    redis_conf = conf
                else:
                    conf2 = path.parent / "redis.conf"
                    if conf2.exists():
                        redis_conf = conf2
                break

        if not redis_server:
            logger.warning("未找到 redis-server.exe，跳过 Redis 启动")
            return False

        try:
            log_file = open(self.log_dir / 'redis.log', 'a', encoding='utf-8')  # noqa: SIM115

            cmd = [str(redis_server)]
            if redis_conf:
                cmd.append(str(redis_conf))

            process = subprocess.Popen(
                cmd,
                cwd=str(redis_server.parent),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0
            )

            self.processes['redis'] = process

            # 等待 Redis 启动
            time.sleep(3)
            if self._check_port(REDIS_PORT):
                logger.info(f"Redis 已启动 (PID={process.pid})")
                return True
            else:
                logger.error("Redis 启动超时")
                return False

        except Exception as e:
            logger.error(f"启动 Redis 失败: {e}")
            return False

    def start_backend(self) -> bool:
        """启动后端服务"""
        logger.info("启动后端服务...")

        # 检查虚拟环境
        if not VENV_PYTHON.exists():
            logger.error(f"虚拟环境未找到: {VENV_PYTHON}")
            return False

        # 清理端口
        if self._check_port(BACKEND_PORT):
            logger.warning(f"端口 {BACKEND_PORT} 被占用，尝试清理...")
            self._kill_port_process(BACKEND_PORT)
            time.sleep(2)

        # 启动后端
        try:
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'

            log_file = open(self.log_dir / 'backend.log', 'a', encoding='utf-8')  # noqa: SIM115

            process = subprocess.Popen(
                [str(VENV_PYTHON), 'api/run.py', '--host', '0.0.0.0', '--port', str(BACKEND_PORT)],
                cwd=str(BACKEND_DIR),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0
            )

            self.processes['backend'] = process

            # 等待服务启动
            if self._wait_for_service(f'http://localhost:{BACKEND_PORT}/api/health', timeout=60):
                logger.info(f"后端服务已启动 (PID={process.pid})")
                return True
            else:
                logger.error("后端服务启动超时")
                return False

        except Exception as e:
            logger.error(f"启动后端服务失败: {e}")
            return False

    def start_frontend(self) -> bool:
        """启动前端服务"""
        logger.info("启动前端服务...")

        # 检查 node_modules
        if not (FRONTEND_DIR / "node_modules").exists():
            logger.error("前端依赖未安装，请先运行 npm install")
            return False

        # 清理端口
        if self._check_port(FRONTEND_PORT):
            logger.warning(f"端口 {FRONTEND_PORT} 被占用，尝试清理...")
            self._kill_port_process(FRONTEND_PORT)
            time.sleep(2)

        # 启动前端
        try:
            log_file = open(self.log_dir / 'frontend.log', 'a', encoding='utf-8')  # noqa: SIM115

            process = subprocess.Popen(
                ['npm', 'run', 'dev', '--', '--port', str(FRONTEND_PORT)],
                cwd=str(FRONTEND_DIR),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                shell=True,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0
            )

            self.processes['frontend'] = process

            # 等待服务启动
            if self._wait_for_service(f'http://localhost:{FRONTEND_PORT}', timeout=60):
                logger.info(f"前端服务已启动 (PID={process.pid})")
                return True
            else:
                logger.error("前端服务启动超时")
                return False

        except Exception as e:
            logger.error(f"启动前端服务失败: {e}")
            return False

    def stop_service(self, name: str) -> bool:
        """停止服务"""
        if name not in self.processes:
            logger.warning(f"服务 {name} 未运行")
            return False

        process = self.processes[name]
        logger.info(f"停止 {name} 服务 (PID={process.pid})...")

        try:
            if sys.platform == 'win32':
                # Windows: 发送 CTRL_BREAK_EVENT
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                process.terminate()

            # 等待进程结束
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning(f"服务 {name} 未正常退出，强制终止")
                process.kill()
                process.wait()

            del self.processes[name]
            logger.info(f"服务 {name} 已停止")
            return True

        except Exception as e:
            logger.error(f"停止服务 {name} 失败: {e}")
            return False

    def stop_all(self):
        """停止所有服务"""
        logger.info("停止所有服务...")
        for name in list(self.processes.keys()):
            self.stop_service(name)

    def get_status(self) -> dict[str, ServiceStatus]:
        """获取所有服务状态"""
        status = {}

        # 检查后端
        backend_running = self._check_port(BACKEND_PORT)
        backend_pid = self.processes.get('backend', subprocess.Popen).__dict__.get('pid') if 'backend' in self.processes else None
        status['backend'] = ServiceStatus(
            name='后端API',
            running=backend_running,
            pid=backend_pid,
            port=BACKEND_PORT,
            url=f'http://localhost:{BACKEND_PORT}',
            last_check=datetime.now().isoformat()
        )

        # 检查前端
        frontend_running = self._check_port(FRONTEND_PORT)
        frontend_pid = self.processes.get('frontend', subprocess.Popen).__dict__.get('pid') if 'frontend' in self.processes else None
        status['frontend'] = ServiceStatus(
            name='前端界面',
            running=frontend_running,
            pid=frontend_pid,
            port=FRONTEND_PORT,
            url=f'http://localhost:{FRONTEND_PORT}',
            last_check=datetime.now().isoformat()
        )

        # 检查WebSocket
        ws_running = self._check_port(WS_PORT)
        status['websocket'] = ServiceStatus(
            name='WebSocket',
            running=ws_running,
            port=WS_PORT,
            last_check=datetime.now().isoformat()
        )

        # 检查Redis
        redis_running = self._check_port(REDIS_PORT)
        redis_pid = self.processes.get('redis', subprocess.Popen).__dict__.get('pid') if 'redis' in self.processes else None
        status['redis'] = ServiceStatus(
            name='Redis缓存',
            running=redis_running,
            pid=redis_pid,
            port=REDIS_PORT,
            last_check=datetime.now().isoformat()
        )

        return status

    def print_status(self):
        """打印状态"""
        status = self.get_status()
        print("\n" + "="*60)
        print("SiliconBase V5 - 服务状态")
        print("="*60)
        for _key, svc in status.items():
            status_icon = "🟢" if svc.running else "🔴"
            print(f"{status_icon} {svc.name}")
            print(f"   状态: {'运行中' if svc.running else '已停止'}")
            if svc.pid:
                print(f"   PID: {svc.pid}")
            if svc.port:
                print(f"   端口: {svc.port}")
            if svc.url:
                print(f"   地址: {svc.url}")
            print()
        print("="*60)

    def start_all(self) -> bool:
        """启动所有服务"""
        logger.info("="*60)
        logger.info("SiliconBase V5 - 启动所有服务")
        logger.info("="*60)

        # 启动 Redis
        self.start_redis()

        # 启动后端
        if not self.start_backend():
            logger.error("后端启动失败，停止启动")
            return False

        time.sleep(3)  # 等待后端完全启动

        # 启动前端
        if not self.start_frontend():
            logger.error("前端启动失败")
            # 但不停止后端，让用户可以手动调试

        logger.info("="*60)
        logger.info("所有服务启动完成")
        logger.info(f"前端地址: http://localhost:{FRONTEND_PORT}")
        logger.info(f"API地址: http://localhost:{BACKEND_PORT}")
        logger.info("="*60)

        return True

    def monitor(self):
        """监控服务状态，自动重启"""
        logger.info("启动服务监控...")

        while not _shutdown_event.is_set():
            status = self.get_status()

            for name, svc in status.items():
                if name in ['backend', 'frontend'] and not svc.running:
                    logger.warning(f"检测到 {name} 服务停止，尝试重启...")
                    if name == 'backend':
                        self.start_backend()
                    elif name == 'frontend':
                        self.start_frontend()

            _shutdown_event.wait(10)  # 每10秒检查一次


def install_windows_service():
    """安装为 Windows 服务"""
    if sys.platform != 'win32':
        logger.error("Windows 服务只能在 Windows 系统上安装")
        return False

    try:
        import importlib.util
        if importlib.util.find_spec("win32serviceutil") is None:
            raise ImportError("pywin32 not found")
    except ImportError:
        logger.error("请先安装 pywin32: pip install pywin32")
        return False

    # 创建服务安装脚本
    service_script = BASE_DIR / "scripts" / "siliconbase_service.py"
    service_script.write_text('''#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import win32serviceutil
import win32service
import win32event
import servicemanager
from scripts.service_manager import ServiceManager, _shutdown_event

class SiliconBaseService(win32serviceutil.ServiceFramework):
    _svc_name_ = "SiliconBaseV5"
    _svc_display_name_ = "SiliconBase V5 Service"
    _svc_description_ = "SiliconBase V5 AI Assistant Service"

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.manager = ServiceManager()

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)
        _shutdown_event.set()
        self.manager.stop_all()

    def SvcDoRun(self):
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, '')
        )
        self.manager.start_all()
        self.manager.monitor()

if __name__ == '__main__':
    win32serviceutil.HandleCommandLine(SiliconBaseService)
''', encoding='utf-8')

    logger.info(f"服务脚本已创建: {service_script}")
    logger.info("请使用管理员权限运行以下命令安装服务:")
    logger.info(f"  python {service_script} install")
    logger.info(f"  python {service_script} start")

    return True


def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("""
SiliconBase V5 - 服务管理器

使用方法:
  python service_manager.py start      # 启动所有服务
  python service_manager.py stop       # 停止所有服务
  python service_manager.py restart    # 重启所有服务
  python service_manager.py status     # 查看状态
  python service_manager.py monitor    # 监控模式（自动重启）
  python service_manager.py install    # 安装为Windows服务
  python service_manager.py uninstall  # 卸载Windows服务
        """)
        return

    command = sys.argv[1].lower()
    manager = ServiceManager()

    if command == 'start':
        manager.start_all()
        # 保持运行
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("收到停止信号...")
            manager.stop_all()

    elif command == 'stop':
        manager.stop_all()

    elif command == 'restart':
        manager.stop_all()
        time.sleep(2)
        manager.start_all()

    elif command == 'status':
        manager.print_status()

    elif command == 'monitor':
        manager.start_all()
        try:
            manager.monitor()
        except KeyboardInterrupt:
            logger.info("收到停止信号...")
            manager.stop_all()

    elif command == 'install':
        install_windows_service()

    elif command == 'uninstall':
        if sys.platform == 'win32':
            service_script = BASE_DIR / "scripts" / "siliconbase_service.py"
            if service_script.exists():
                os.system(f'python "{service_script}" remove')
            else:
                logger.error("服务脚本不存在")
        else:
            logger.error("Windows 服务只能在 Windows 系统上卸载")

    else:
        logger.error(f"未知命令: {command}")


if __name__ == '__main__':
    main()
