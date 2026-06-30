#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""
安全合规层 - 权限检测、操作审计
最终版：严格拦截管理员 + 开发者环境变量绕过 + 免责提示
2026-02-22 恢复：开发者可通过 SILICON_DEV_MODE=1 绕过管理员检查
"""  # 模块文档字符串：说明本模块的核心功能和版本信息
import ctypes  # ctypes模块：用于调用Windows系统API检测管理员权限
import os  # os模块：用于获取环境变量
import sys  # sys模块：提供系统相关功能，如sys.exit()退出程序
import threading  # threading模块：提供线程锁实现单例模式
import time  # time模块：用于优雅退出时的延迟等待

from core.logger import logger  # 导入日志记录器：记录安全事件和调试信息

try:  # 尝试导入tkinter的messagebox模块（用于显示图形界面提示）
    from tkinter import messagebox  # 导入消息框：用于显示权限错误弹窗
except ImportError:  # 如果导入失败（如服务器环境无GUI）
    messagebox = None  # 将messagebox设为None，后续使用print代替


class SecurityManager:  # 安全管理器类：负责权限检测、优雅退出和清理管理
    """安全管理器 - 权限控制、安全检测、优雅退出管理"""  # 类文档字符串
    _instance = None  # 单例实例引用：用于实现单例模式
    _lock = threading.Lock()  # 线程锁：用于单例创建的线程安全
    _cleanup_callbacks = []  # 清理回调列表：存储退出时需要执行的清理函数

    def __new__(cls):  # 重写new方法实现单例模式
        if cls._instance is None:  # 检查实例是否已存在
            with cls._lock:  # 获取线程锁
                # 双重检查锁定：确保多线程环境下只有一个实例
                if cls._instance is None:  # 再次检查（防止多个线程同时通过第一次检查）
                    cls._instance = super().__new__(cls)  # 创建实例
        return cls._instance  # 返回单例实例

    def register_cleanup(self, callback):  # 注册清理回调函数
        """注册退出时清理的回调函数"""  # 方法文档字符串
        self._cleanup_callbacks.append(callback)  # 将回调函数添加到列表

    def graceful_exit(self, exit_code: int = 0, reason: str = ""):  # 优雅退出方法
        """
        优雅退出，执行所有清理回调，然后退出
        Args:
            exit_code: 退出码，0表示正常退出，非0表示异常
            reason: 退出原因描述，用于日志记录
        """  # 方法文档字符串
        logger.info(f"正在优雅退出，原因: {reason or '正常退出'}")  # 记录退出日志
        for cb in self._cleanup_callbacks:  # 遍历所有注册的清理回调
            try:  # 异常处理：确保一个回调失败不影响其他回调
                cb()  # 执行回调函数
            except Exception as e:  # 捕获回调执行异常
                logger.error(f"清理回调执行失败: {e}")  # 记录错误但不中断退出流程
        # 给清理操作一点时间（500毫秒）确保资源释放完成
        time.sleep(0.5)
        sys.exit(exit_code)  # 调用sys.exit()终止程序

    def check_admin(self):  # 检查管理员权限方法
        """
        检测管理员权限。
        如果以管理员运行，显示免责提示并退出。
        开发者可通过设置 SILICON_DEV_MODE=1 绕过此限制。
        Returns:
            bool: 检查通过返回True，否则退出程序
        """  # 方法文档字符串
        # 开发者模式绕过：允许开发者以管理员身份运行进行调试
        if os.environ.get("SILICON_DEV_MODE") == "1":  # 检查环境变量SILICON_DEV_MODE
            logger.info("开发者模式已启用，跳过管理员权限检查")  # 记录日志
            return True  # 直接通过检查

        try:  # 异常处理块
            if ctypes.windll.shell32.IsUserAnAdmin():  # 调用Windows API检测是否管理员
                # 拒绝运行并显示免责提示：构建提示消息
                msg = (
                    "本程序设计为以普通用户权限运行，以获得最佳安全性和兼容性。\n"
                    "检测到您以管理员身份运行，这可能导致功能异常或系统风险。\n"
                    "请以普通用户权限重新启动。\n\n"
                    '（点击"确定"将退出程序）'
                )
                if messagebox:  # 如果有GUI环境
                    messagebox.showerror("权限错误", msg)  # 显示错误弹窗
                else:  # 无GUI环境（如服务器）
                    print("\n" + msg + "\n")  # 打印到控制台
                self.graceful_exit(1, "管理员权限不允许")  # 优雅退出，返回码1表示错误
            return True  # 非管理员，检查通过
        except Exception as e:  # 捕获检测异常
            logger.warning(f"管理员权限检测失败: {e}")  # 记录警告
            return True  # 如果检测失败，默认允许运行（保守策略，避免误杀）

    def start_blacklist_monitor(self):  # 启动黑名单进程监控（已禁用）
        """黑名单进程监控已禁用，请使用操作审计替代"""  # 方法文档字符串
        logger.info("黑名单进程监控已禁用，请使用操作审计替代")  # 记录日志
        pass  # 空实现，功能已移除

    def stop_blacklist_monitor(self):  # 停止黑名单进程监控（已禁用）
        """停止黑名单监控（空实现）"""  # 方法文档字符串
        pass  # 空实现，功能已移除

    def run_elevated(self, cmd: list) -> bool:  # 以提升权限运行命令
        """
        以管理员权限运行命令（使用runas）
        Args:
            cmd: 命令参数列表
        Returns:
            bool: 执行成功返回True，失败返回False
        """  # 方法文档字符串
        try:  # 异常处理块
            import subprocess  # 导入subprocess模块：用于执行系统命令
            subprocess.run(["runas", "/user:Administrator"] + cmd, check=True)  # 使用runas提权执行
            return True  # 执行成功
        except Exception as e:  # 捕获执行异常
            logger.error(f"提权失败: {e}")  # 记录错误
            return False  # 执行失败


security = SecurityManager()  # 创建模块级单例实例，供全系统使用


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase_V5 系统的"安全合规层"，负责权限检测、安全策略执行和优雅退出管理。
# 主要目标是确保程序以普通用户权限运行，避免管理员权限带来的安全风险，同时提供开发者调试绕过机制。
#
# 【架构设计】
# - 单例模式: SecurityManager使用双重检查锁定实现线程安全的单例
# - 权限检测: 通过Windows API检测管理员权限，拒绝管理员运行
# - 开发者绕过: 通过SILICON_DEV_MODE环境变量允许开发者调试
# - 优雅退出: 注册清理回调，确保资源正确释放后再退出
# - 提权执行: 提供run_elevated方法在需要时临时提权执行命令
#
# 【关联文件】
# - core/logger.py           : 记录安全事件和调试信息
# - core/config.py           : 系统配置（当前预留扩展）
# - main.py / 启动脚本        : 启动时调用security.check_admin()进行权限检查
# - core/safety_guard.py     : 运行时风险评估（与本文件的启动时权限检测互补）
#
# 【核心功能效果】
# 1. 权限保护: 防止程序以管理员权限运行，降低系统风险
# 2. 免责提示: 管理员运行时显示明确提示，避免用户误操作
# 3. 开发者友好: SILICON_DEV_MODE=1环境变量允许开发者绕过检查
# 4. 优雅退出: 确保清理回调执行完成后再退出，避免资源泄漏
# 5. 临时提权: run_elevated()方法支持需要时临时获取管理员权限执行特定命令
#
# 【数据流向】
# 启动时: main.py → security.check_admin() → ctypes.windll.shell32.IsUserAnAdmin()
# 退出时: graceful_exit() → 执行_cleanup_callbacks列表 → sys.exit()
# 提权时: run_elevated(cmd) → subprocess.run(["runas", ...])
#
# 【使用场景】
# 场景1: 程序启动 → check_admin() → 检测到管理员 → 显示弹窗 → graceful_exit(1)
# 场景2: 程序启动 → check_admin() → SILICON_DEV_MODE=1 → 跳过检查 → 继续启动
# 场景3: 需要提权操作 → run_elevated(["command"]) → 弹出UAC → 执行命令
# 场景4: 程序退出前 → register_cleanup(callback) → graceful_exit() → 执行callback
#
# 【注意事项】
# - 生产环境必须普通用户运行，管理员运行可能导致沙箱失效、权限过大等风险
# - 开发者绕过仅用于调试，不应在生产环境使用
# - 优雅退出的0.5秒延迟确保资源释放，可根据需要调整
# =============================================================================
