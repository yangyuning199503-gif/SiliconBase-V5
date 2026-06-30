"""
恶意操作类规则 - 18条

覆盖场景：
- 磁盘格式化
- 系统文件删除
- Rootkit安装
- 勒索软件
- 木马/后门
- 进程注入
- C2通信
- 日志清理
- 等...
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from core.safety.moral_module import MoralLevel, MoralRule, RuleCategory
except ImportError:
    from dataclasses import dataclass
    from enum import Enum

    class RuleCategory(Enum):
        FILE_OPERATION = "file_operation"
        SYSTEM_OPERATION = "system_operation"
        NETWORK_OPERATION = "network_operation"

    class MoralLevel(Enum):
        SAFE = "safe"
        WARNING = "warning"
        DANGEROUS = "dangerous"
        FORBIDDEN = "forbidden"

    @dataclass
    class MoralRule:
        rule_id: str
        category: RuleCategory
        name: str
        description: str
        patterns: list[str]
        forbidden_keywords: list[str]
        severity: MoralLevel
        action: str
        message: str


# 恶意操作类规则 (18条)
MALICIOUS_OPERATION_RULES = [
    MoralRule(
        rule_id="MAL_001",
        category=RuleCategory.FILE_OPERATION,
        name="阻止磁盘格式化",
        description="检测磁盘格式化操作",
        patterns=[
            r"format\s+[a-zA-Z]:",
            r"format\s+/fs",
            r"mkfs\.\w+",
            r"diskpart.*format",
            r"格式化.*磁盘",
            r"清空.*硬盘",
            r"dd\s+if=/dev/zero\s+of=/dev/[sh]d",
            r"dd\s+if=/dev/urandom\s+of=/dev/[sh]d",
            r"diskpart.*clean",
        ],
        forbidden_keywords=[
            "格式化磁盘", "格式化C盘", "清空硬盘", "抹除数据",
            "format C:", "format disk", "wipe disk", "erase hard drive",
            "dd if=/dev/zero", "磁盘清零", "销毁数据", "低级格式化",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止格式化存储设备"
    ),

    MoralRule(
        rule_id="MAL_002",
        category=RuleCategory.FILE_OPERATION,
        name="阻止系统文件删除",
        description="检测删除关键系统文件",
        patterns=[
            r"del.*\\windows\\system32",
            r"del.*\\winnt\\system32",
            r"rm\s+-rf\s+/[\s]*bin",
            r"rm\s+-rf\s+/[\s]*sbin",
            r"rm\s+-rf\s+/[\s]*lib",
            r"rm\s+-rf\s+/[\s]*lib64",
            r"rm\s+-rf\s+/[\s]*usr",
            r"删除.*系统.*文件",
            r"破坏.*系统",
        ],
        forbidden_keywords=[
            "删除系统文件", "破坏系统文件", "删除system32",
            "rm -rf /", "rm -rf /*", "删除核心文件", "删除启动文件",
            "delete system files", "corrupt system", "破坏操作系统",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止删除系统关键文件"
    ),

    MoralRule(
        rule_id="MAL_003",
        category=RuleCategory.SYSTEM_OPERATION,
        name="阻止Rootkit安装",
        description="检测Rootkit相关操作",
        patterns=[
            r"rootkit",
            r"驱动.*隐藏",
            r"隐藏.*进程",
            r"隐藏.*文件",
            r"DKOM",
            r"direct.*kernel",
        ],
        forbidden_keywords=[
            "安装rootkit", "rootkit", "内核级隐藏", "驱动隐藏",
            "隐藏进程", "隐藏文件", "系统级后门", "内核后门",
            "install rootkit", "kernel rootkit", "驱动级rootkit",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止安装Rootkit"
    ),

    MoralRule(
        rule_id="MAL_004",
        category=RuleCategory.SYSTEM_OPERATION,
        name="阻止勒索软件行为",
        description="检测勒索软件特征",
        patterns=[
            r"ransomware",
            r"加密.*文件.*赎金",
            r"encrypt.*file.*bitcoin",
            r"\.locked",
            r"\.encrypted",
            r"\.crypt",
            r"RECOVER_INSTRUCTIONS",
            r"YOUR_FILES_ARE_ENCRYPTED",
        ],
        forbidden_keywords=[
            "勒索软件", "ransomware", "加密文件索要赎金",
            "file encryption ransom", "锁定文件", "file locker",
            "支付赎金", "bitcoin ransom", "文件加密勒索",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止勒索软件行为"
    ),

    MoralRule(
        rule_id="MAL_005",
        category=RuleCategory.SYSTEM_OPERATION,
        name="阻止木马安装",
        description="检测木马安装行为",
        patterns=[
            r"安装.*木马",
            r"植入.*后门",
            r"trojan",
            r"backdoor",
            r"反弹shell",
            r"reverse.*shell",
            r"bind.*shell",
            r"nc\s+-e",
            r"netcat.*shell",
        ],
        forbidden_keywords=[
            "安装木马", "植入后门", "安装trojan", "植入backdoor",
            "反弹shell", "reverse shell", "bind shell",
            "create backdoor", "install trojan", "木马程序",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止安装木马或后门"
    ),

    MoralRule(
        rule_id="MAL_006",
        category=RuleCategory.SYSTEM_OPERATION,
        name="阻止进程注入",
        description="检测代码注入行为",
        patterns=[
            r"dll.*注入",
            r"进程.*注入",
            r"code.*injection",
            r"process.*injection",
            r"CreateRemoteThread",
            r"VirtualAllocEx",
            r"WriteProcessMemory",
            r"QueueUserAPC",
            r"SetThreadContext",
        ],
        forbidden_keywords=[
            "dll注入", "进程注入", "代码注入", "内存注入",
            "dll injection", "process injection", "code injection",
            "apc注入", "thread hijacking", "远程线程注入",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止进程注入"
    ),

    MoralRule(
        rule_id="MAL_007",
        category=RuleCategory.NETWORK_OPERATION,
        name="阻止C2通信",
        description="检测命令与控制服务器通信",
        patterns=[
            r"c2.*server",
            r"command.*control",
            r"cc服务器",
            r"控制服务器",
            r"botnet",
            r"僵尸网络",
        ],
        forbidden_keywords=[
            "连接C2", "c2通信", "命令控制服务器", "cc服务器",
            "connect to c2", "command and control", "botnet",
            "僵尸网络通信", "远控服务器", "控制端通信",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止连接恶意控制服务器"
    ),

    MoralRule(
        rule_id="MAL_008",
        category=RuleCategory.SYSTEM_OPERATION,
        name="阻止日志清理",
        description="检测清除审计日志",
        patterns=[
            r"wevtutil.*cl",
            r"clear-eventlog",
            r"删除.*日志",
            r"清空.*日志",
            r"清除.*痕迹",
            r">\s*/var/log",
            r"rm\s+-rf\s+/var/log",
            r"echo.*>\s*/var/log",
            r"历史.*清除",
        ],
        forbidden_keywords=[
            "清除日志", "删除日志", "清理痕迹", "掩盖踪迹",
            "clear logs", "delete logs", "wipe logs", "erase evidence",
            "清除事件日志", "删除审计记录", "清理历史记录",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止清除审计日志"
    ),

    MoralRule(
        rule_id="MAL_009",
        category=RuleCategory.SYSTEM_OPERATION,
        name="阻止启动项持久化",
        description="检测恶意持久化行为",
        patterns=[
            r"注册表.*run",
            r"HKCU.*Run",
            r"HKLM.*Run",
            r"hkey.*run",
            r"startup.*添加",
            r"启动项.*添加",
            r"startup.*文件夹",
            r"RunOnce",
        ],
        forbidden_keywords=[
            "添加启动项", "注册表run", "启动文件夹", "持久化后门",
            "add startup", "registry run", "persistence mechanism",
            "开机启动", "登录启动", "run键值",
        ],
        severity=MoralLevel.DANGEROUS,
        action="warn",
        message="谨慎修改启动项"
    ),

    MoralRule(
        rule_id="MAL_010",
        category=RuleCategory.SYSTEM_OPERATION,
        name="阻止系统配置修改",
        description="检测危险系统配置修改",
        patterns=[
            r"修改.*系统.*配置",
            r"篡改.*注册表",
            r"禁用.*系统.*功能",
            r"修改.*安全.*策略",
            r"组策略.*修改",
            r"gpedit",
        ],
        forbidden_keywords=[
            "修改系统配置", "篡改注册表", "禁用系统功能",
            "修改安全策略", "改变系统设置", "系统配置篡改",
            "modify system config", "tamper registry", "disable security",
        ],
        severity=MoralLevel.DANGEROUS,
        action="warn",
        message="谨慎修改系统配置"
    ),

    MoralRule(
        rule_id="MAL_011",
        category=RuleCategory.SYSTEM_OPERATION,
        name="阻止驱动加载",
        description="检测未签名/恶意驱动加载",
        patterns=[
            r"加载.*驱动",
            r"安装.*驱动",
            r"驱动.*签名",
            r"unsigned.*driver",
            r"恶意.*驱动",
            r"sc\s+create.*type.*kernel",
        ],
        forbidden_keywords=[
            "加载未签名驱动", "安装恶意驱动", "驱动劫持",
            "unsigned driver", "malicious driver", "驱动后门",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止加载未签名驱动"
    ),

    MoralRule(
        rule_id="MAL_012",
        category=RuleCategory.SYSTEM_OPERATION,
        name="阻止系统调用篡改",
        description="检测SSDT/系统调用篡改",
        patterns=[
            r"SSDT",
            r"系统调用.*表",
            r"hook.*syscall",
            r"内核.*hook",
            r"system.*call.*hook",
        ],
        forbidden_keywords=[
            "SSDT篡改", "系统调用表", "hook系统调用",
            "syscall hook", "内核hook", "系统服务描述表",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止篡改系统调用"
    ),

    MoralRule(
        rule_id="MAL_013",
        category=RuleCategory.SYSTEM_OPERATION,
        name="阻止环境变量篡改",
        description="检测恶意环境变量修改",
        patterns=[
            r"PATH.*修改",
            r"LD_PRELOAD",
            r"LD_LIBRARY_PATH",
            r"环境变量.*劫持",
            r"setenv.*malicious",
        ],
        forbidden_keywords=[
            "PATH环境变量篡改", "LD_PRELOAD劫持", "环境变量劫持",
            "修改系统PATH", "恶意环境变量", "library path劫持",
        ],
        severity=MoralLevel.DANGEROUS,
        action="warn",
        message="谨慎修改环境变量"
    ),

    MoralRule(
        rule_id="MAL_014",
        category=RuleCategory.SYSTEM_OPERATION,
        name="阻止WMI滥用",
        description="检测WMI持久化/攻击",
        patterns=[
            r"WMI.*持久化",
            r"wmi.*event",
            r"__EventFilter",
            r"ActiveScriptEventConsumer",
            r"powershell.*wmi",
        ],
        forbidden_keywords=[
            "WMI持久化", "WMI攻击", "WMI事件",
            "wmi persistence", "wmi backdoor", "WMI后门",
        ],
        severity=MoralLevel.DANGEROUS,
        action="warn",
        message="谨慎使用WMI"
    ),

    MoralRule(
        rule_id="MAL_015",
        category=RuleCategory.SYSTEM_OPERATION,
        name="阻止AMSI绕过",
        description="检测AMSI(反恶意软件扫描接口)绕过",
        patterns=[
            r"AMSI.*绕过",
            r"amsi.*bypass",
            r"AmsiInitialize",
            r"AmsiScanBuffer",
            r"patch.*amsi",
        ],
        forbidden_keywords=[
            "AMSI绕过", "amsi bypass", "禁用AMSI",
            "patch amsi", "amsi disable", "反恶意软件扫描绕过",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止绕过AMSI"
    ),

    MoralRule(
        rule_id="MAL_016",
        category=RuleCategory.SYSTEM_OPERATION,
        name="阻止ETW篡改",
        description="检测ETW(事件追踪)禁用",
        patterns=[
            r"ETW.*禁用",
            r"etw.*disable",
            r"EventWrite",
            r"patch.*etw",
            r"NtTraceEvent",
        ],
        forbidden_keywords=[
            "ETW禁用", "etw disable", "禁用事件追踪",
            "patch etw", "ETW篡改", "阻止事件记录",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止篡改ETW"
    ),

    MoralRule(
        rule_id="MAL_017",
        category=RuleCategory.NETWORK_OPERATION,
        name="阻止DNS劫持",
        description="检测DNS设置篡改",
        patterns=[
            r"DNS.*劫持",
            r"hosts.*修改",
            r"/etc/hosts",
            r"dnscache",
            r"修改.*DNS",
        ],
        forbidden_keywords=[
            "DNS劫持", "hosts文件篡改", "DNS投毒",
            "dns hijacking", "hosts poisoning", "修改DNS设置",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止DNS劫持"
    ),

    MoralRule(
        rule_id="MAL_018",
        category=RuleCategory.NETWORK_OPERATION,
        name="阻止ARP欺骗",
        description="检测ARP欺骗攻击",
        patterns=[
            r"ARP.*欺骗",
            r"arp.*spoof",
            r"arp.*-s",
            r" gratuitous.*arp",
            r"arp.*中毒",
        ],
        forbidden_keywords=[
            "ARP欺骗", "arp spoofing", "ARP投毒",
            "arp poisoning", "中间人攻击", "mitm arp",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止ARP欺骗"
    ),
]


if __name__ == "__main__":
    print(f"恶意操作规则共 {len(MALICIOUS_OPERATION_RULES)} 条")
    for rule in MALICIOUS_OPERATION_RULES:
        print(f"  - {rule.rule_id}: {rule.name}")
