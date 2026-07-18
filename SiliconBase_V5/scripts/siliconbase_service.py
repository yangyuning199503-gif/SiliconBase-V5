#!/usr/bin/env python3
"""
SiliconBase V5 - Windows 服务脚本
"""
import os
import sys

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import servicemanager
    import win32event
    import win32service
    import win32serviceutil
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False
    print("警告: pywin32 未安装，无法作为Windows服务运行")

import logging
import time

from scripts.service_manager import ServiceManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('logs/service.log'), logging.StreamHandler()]
)
logger = logging.getLogger('SiliconBaseService')


class SiliconBaseService(win32serviceutil.ServiceFramework if HAS_WIN32 else object):
    _svc_name_ = "SiliconBaseV5"
    _svc_display_name_ = "SiliconBase V5 AI服务"
    _svc_description_ = "SiliconBase V5 AI智能助手后台服务 - 开机自动启动"

    def __init__(self, args):
        if HAS_WIN32:
            win32serviceutil.ServiceFramework.__init__(self, args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.manager = ServiceManager()

    def SvcStop(self):
        if not HAS_WIN32:
            return
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)
        logger.info("服务停止信号 received")
        self.manager.stop_all()
        self.ReportServiceStatus(win32service.SERVICE_STOPPED)

    def SvcDoRun(self):
        if not HAS_WIN32:
            logger.error("pywin32 未安装，无法运行服务")
            return
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, '')
        )
        logger.info("SiliconBase V5 服务启动")
        try:
            self.manager.start_all()
            while True:
                time.sleep(10)
                status = self.manager.get_status()
                backend_status = status.get('backend')
                if backend_status and not backend_status.running:
                    logger.warning("后端服务停止，尝试重启...")
                    self.manager.start_backend()
        except Exception as e:
            logger.error(f"服务运行错误: {e}")


def main():
    if not HAS_WIN32:
        print("错误: pywin32 未安装")
        print("请运行: pip install pywin32")
        sys.exit(1)

    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(SiliconBaseService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(SiliconBaseService)


if __name__ == '__main__':
    main()
