#!/usr/bin/env python3
"""
SiliconBase V5 - 原子工具库

所有工具均继承自 BaseTool，支持统一注册、执行和监控。
导入失败会被静默捕获，避免单个工具损坏影响整个包。
"""

# ═══════════════════════════════════════════════════════════════════════════════
# 应用与系统工具
# ═══════════════════════════════════════════════════════════════════════════════
try:
    from .app_search import AppSearch
except Exception:
    AppSearch = None

try:
    from .browse_dir import BrowseDir
except Exception:
    BrowseDir = None

try:
    from .call_user import CallUser
except Exception:
    CallUser = None

try:
    from .current_time import CurrentTime
except Exception:
    CurrentTime = None

try:
    from .delete_user_data import DeleteUserData
except Exception:
    DeleteUserData = None

try:
    from .export_data import ExportData
except Exception:
    ExportData = None

try:
    from .file_manager import FileManager
except Exception:
    FileManager = None

try:
    from .find_file import FindFile
except Exception:
    FindFile = None

try:
    from .keyboard_input import KeyboardInput
except Exception:
    KeyboardInput = None

try:
    from .launch_app import LaunchApp
except Exception:
    LaunchApp = None

try:
    from .launch_app_simple import LaunchAppSimple
except Exception:
    LaunchAppSimple = None

try:
    from .launch_app_v2 import LaunchAppV2
except Exception:
    LaunchAppV2 = None

try:
    from .list_installed_apps import ListInstalledApps
except Exception:
    ListInstalledApps = None

try:
    from .mouse_click import MouseClick
except Exception:
    MouseClick = None

try:
    from .open_and_focus import OpenAndFocus
except Exception:
    OpenAndFocus = None

try:
    from .process_kill import ProcessKill
except Exception:
    ProcessKill = None

try:
    from .process_start import ProcessStart
except Exception:
    ProcessStart = None

try:
    from .read_file import ReadFile
except Exception:
    ReadFile = None

try:
    from .shell_execute import ShellExecute
except Exception:
    ShellExecute = None

try:
    from .system_info import SystemInfo
except Exception:
    SystemInfo = None

try:
    from .wait_for_window import WaitForWindow
except Exception:
    WaitForWindow = None

# ═══════════════════════════════════════════════════════════════════════════════
# 剪贴板工具
# ═══════════════════════════════════════════════════════════════════════════════
try:
    from .clipboard import Clipboard, ClipboardGet, ClipboardSet
except Exception:
    Clipboard = None
    ClipboardGet = None
    ClipboardSet = None

# ═══════════════════════════════════════════════════════════════════════════════
# 点击与 OCR 工具
# ═══════════════════════════════════════════════════════════════════════════════
try:
    from .click_text import ClickText
except Exception:
    ClickText = None

try:
    from .find_screen_element import FindScreenElement
except Exception:
    FindScreenElement = None

try:
    from .ocr_text import OCRText
except Exception:
    OCRText = None

try:
    from .screen_ocr import ScreenOCR
except Exception:
    ScreenOCR = None

try:
    from .window_ocr import WindowOCR
except Exception:
    WindowOCR = None

try:
    from .pixel_capture import PixelCapture
except Exception:
    PixelCapture = None

try:
    from .pixel_click import PixelClick
except Exception:
    PixelClick = None

try:
    from .pixel_color import PixelColor
except Exception:
    PixelColor = None

try:
    from .pixel_monitor import PixelMonitor
except Exception:
    PixelMonitor = None

try:
    from .template_match import TemplateMatch
except Exception:
    TemplateMatch = None

try:
    from .template_record import TemplateRecord
except Exception:
    TemplateRecord = None

# ═══════════════════════════════════════════════════════════════════════════════
# 窗口管理工具
# ═══════════════════════════════════════════════════════════════════════════════
try:
    from .window_action import WindowAction
except Exception:
    WindowAction = None

try:
    from .window_focus import WindowFocus
except Exception:
    WindowFocus = None

try:
    from .window_get import WindowGet
except Exception:
    WindowGet = None

try:
    from .window_rect import WindowRect
except Exception:
    WindowRect = None

# ═══════════════════════════════════════════════════════════════════════════════
# 视觉与元素检测工具
# ═══════════════════════════════════════════════════════════════════════════════
try:
    from .ui_element_detect import UIElementDetect
except Exception:
    UIElementDetect = None

try:
    from .ui_tars import UITarsTool
except Exception:
    UITarsTool = None

try:
    from .vision_agent import VisionAgentTool
except Exception:
    VisionAgentTool = None

try:
    from .visual_element_detect import VisualElementDetect
except Exception:
    VisualElementDetect = None

try:
    from .visual_understand import VisualUnderstand
except Exception:
    VisualUnderstand = None

try:
    from .get_perception import GetPerception
except Exception:
    GetPerception = None

try:
    from .icon_recognize import IconRecognize
except Exception:
    IconRecognize = None

# ═══════════════════════════════════════════════════════════════════════════════
# 记忆工具
# ═══════════════════════════════════════════════════════════════════════════════
try:
    from .memory_add import MemoryAdd
except Exception:
    MemoryAdd = None

try:
    from .memory_delete import MemoryDelete
except Exception:
    MemoryDelete = None

try:
    from .memory_list import MemoryList
except Exception:
    MemoryList = None

try:
    from .memory_replace import MemoryReplace
except Exception:
    MemoryReplace = None

try:
    from .memory_search import MemorySearch
except Exception:
    MemorySearch = None

try:
    from .memory_update import MemoryUpdate
except Exception:
    MemoryUpdate = None

# ═══════════════════════════════════════════════════════════════════════════════
# 任务与子代理工具
# ═══════════════════════════════════════════════════════════════════════════════
try:
    from .task_tools import CancelTask, CreateTask, GetTask, ListTasks
except Exception:
    CreateTask = None
    ListTasks = None
    GetTask = None
    CancelTask = None

try:
    from .long_task_tools import (
        CancelLongTask,
        CreateLongTask,
        GetLongTaskStatus,
        PauseLongTask,
        ResumeLongTask,
    )
except Exception:
    CreateLongTask = None
    PauseLongTask = None
    ResumeLongTask = None
    GetLongTaskStatus = None
    CancelLongTask = None

try:
    from .subagent_tools import (
        DelegateToSubAgent,
        GetSubAgentStatus,
        InterveneSubAgent,
        ListAvailableSubAgents,
    )
except Exception:
    DelegateToSubAgent = None
    GetSubAgentStatus = None
    InterveneSubAgent = None
    ListAvailableSubAgents = None

# ═══════════════════════════════════════════════════════════════════════════════
# 工具手册与提示层工具
# ═══════════════════════════════════════════════════════════════════════════════
try:
    from .tool_manual import (
        GetToolCategoriesL1,
        GetToolDetailL3,
        GetToolManual,
        GetToolsByCategoryL2,
        SwitchPromptLayer,
    )
except Exception:
    GetToolManual = None
    GetToolCategoriesL1 = None
    GetToolsByCategoryL2 = None
    GetToolDetailL3 = None
    SwitchPromptLayer = None

# ═══════════════════════════════════════════════════════════════════════════════
# 代码生成与自动化工具
# ═══════════════════════════════════════════════════════════════════════════════
try:
    from .code_generate import CodeGenerate
except Exception:
    CodeGenerate = None

try:
    from .web_automation import WebAutomation
except Exception:
    WebAutomation = None

try:
    from .web_fetch import WebFetch
except Exception:
    WebFetch = None

try:
    from .web_open import WebOpen
except Exception:
    WebOpen = None

try:
    from .web_parse import WebParse
except Exception:
    WebParse = None

try:
    from .web_search import WebSearch
except Exception:
    WebSearch = None

try:
    from .smart_form_fill import SmartFormFill
except Exception:
    SmartFormFill = None

try:
    from .find_and_click import FindAndClick
except Exception:
    FindAndClick = None

try:
    from .list_all_files import ListAllFiles
except Exception:
    ListAllFiles = None

# ═══════════════════════════════════════════════════════════════════════════════
# 网络与 VPN 工具
# ═══════════════════════════════════════════════════════════════════════════════
try:
    from .vpn_check import VPNCheck
except Exception:
    VPNCheck = None

try:
    from .vpn_connect import VPNConnect
except Exception:
    VPNConnect = None

# ═══════════════════════════════════════════════════════════════════════════════
# 其他工具
# ═══════════════════════════════════════════════════════════════════════════════
try:
    from .tron_balance_updater import TronBalanceUpdater
except Exception:
    TronBalanceUpdater = None

# ═══════════════════════════════════════════════════════════════════════════════
# BTC 交易子包（已具备完整 __init__.py，直接透传）
# ═══════════════════════════════════════════════════════════════════════════════
try:
    from .btc_trading import (
        BTCAccountInfo,
        BTCCheckRecovery,
        BTCConfirmTrade,
        BTCEmergencyStop,
        BTCExecuteTrade,
        BTCGenerateReport,
        BTCGetProcessStatus,
        BTCIntervention,
        BTCLaunchAutopilot,
        BTCMarketOverview,
        BTCMonitorTrading,
        BTCPriceQuery,
        BTCRecoverTrading,
        BTCRiskAssessment,
        BTCRiskCheck,
        BTCStopAutopilot,
        BTCStrategyExplain,
        BTCStrategySelector,
        BTCTechnicalAnalysis,
        BTCTradingAdapter,
        adapt_btc_result,
    )
except Exception:
    BTCTradingAdapter = None
    adapt_btc_result = None
    BTCPriceQuery = None
    BTCMarketOverview = None
    BTCTechnicalAnalysis = None
    BTCAccountInfo = None
    BTCStrategySelector = None
    BTCStrategyExplain = None
    BTCRiskAssessment = None
    BTCLaunchAutopilot = None
    BTCGetProcessStatus = None
    BTCStopAutopilot = None
    BTCMonitorTrading = None
    BTCGenerateReport = None
    BTCConfirmTrade = None
    BTCExecuteTrade = None
    BTCRiskCheck = None
    BTCEmergencyStop = None
    BTCIntervention = None
    BTCCheckRecovery = None
    BTCRecoverTrading = None


# ═══════════════════════════════════════════════════════════════════════════════
# __all__ 定义（便于 IDE 自动补全和 `from tools import *`）
# ═══════════════════════════════════════════════════════════════════════════════
__all__ = [
    # 应用与系统
    "AppSearch",
    "BrowseDir",
    "CallUser",
    "CurrentTime",
    "DeleteUserData",
    "ExportData",
    "FileManager",
    "FindFile",
    "KeyboardInput",
    "LaunchApp",
    "LaunchAppSimple",
    "LaunchAppV2",
    "ListInstalledApps",
    "MouseClick",
    "OpenAndFocus",
    "ProcessKill",
    "ProcessStart",
    "ReadFile",
    "ShellExecute",
    "SystemInfo",
    "WaitForWindow",
    # 剪贴板
    "Clipboard",
    "ClipboardGet",
    "ClipboardSet",
    # 点击与 OCR
    "ClickText",
    "FindScreenElement",
    "OCRText",
    "ScreenOCR",
    "WindowOCR",
    "PixelCapture",
    "PixelClick",
    "PixelColor",
    "PixelMonitor",
    "TemplateMatch",
    "TemplateRecord",
    # 窗口管理
    "WindowAction",
    "WindowFocus",
    "WindowGet",
    "WindowRect",
    # 视觉与元素检测
    "UIElementDetect",
    "UITarsTool",
    "VisionAgentTool",
    "VisualElementDetect",
    "VisualUnderstand",
    "GetPerception",
    "IconRecognize",
    # 记忆
    "MemoryAdd",
    "MemoryDelete",
    "MemoryList",
    "MemoryReplace",
    "MemorySearch",
    "MemoryUpdate",
    # 任务与子代理
    "CreateTask",
    "ListTasks",
    "GetTask",
    "CancelTask",
    "CreateLongTask",
    "PauseLongTask",
    "ResumeLongTask",
    "GetLongTaskStatus",
    "CancelLongTask",
    "DelegateToSubAgent",
    "GetSubAgentStatus",
    "InterveneSubAgent",
    "ListAvailableSubAgents",
    # 工具手册
    "GetToolManual",
    "GetToolCategoriesL1",
    "GetToolsByCategoryL2",
    "GetToolDetailL3",
    "SwitchPromptLayer",
    # 代码生成与自动化
    "CodeGenerate",
    "WebAutomation",
    "WebFetch",
    "WebOpen",
    "WebParse",
    "WebSearch",
    "SmartFormFill",
    "FindAndClick",
    "ListAllFiles",
    # 网络与 VPN
    "VPNCheck",
    "VPNConnect",
    # 其他
    "TronBalanceUpdater",
    # BTC 交易
    "BTCTradingAdapter",
    "adapt_btc_result",
    "BTCPriceQuery",
    "BTCMarketOverview",
    "BTCTechnicalAnalysis",
    "BTCAccountInfo",
    "BTCStrategySelector",
    "BTCStrategyExplain",
    "BTCRiskAssessment",
    "BTCLaunchAutopilot",
    "BTCGetProcessStatus",
    "BTCStopAutopilot",
    "BTCMonitorTrading",
    "BTCGenerateReport",
    "BTCConfirmTrade",
    "BTCExecuteTrade",
    "BTCRiskCheck",
    "BTCEmergencyStop",
    "BTCIntervention",
    "BTCCheckRecovery",
    "BTCRecoverTrading",
]
