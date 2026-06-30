"""
权限提升类规则 - 12条

覆盖场景：
- 权限提升/提权
- SUID滥用
- 内核漏洞利用
- 安全软件关闭
- 计划任务/服务提权
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
        SYSTEM_OPERATION = "system_operation"
        FILE_OPERATION = "file_operation"

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


# 权限提升类规则 (12条)
PRIVILEGE_ESCALATION_RULES = [
    MoralRule(
        rule_id="PRIVESC_001",
        category=RuleCategory.SYSTEM_OPERATION,
        name="阻止权限提升",
        description="检测各种权限提升尝试",
        patterns=[
            r"sudo\s+-u\s+root",
            r"su\s+-\s*root",
            r"runas.*/user:.*administrator",
            r"runas.*/user:.*system",
            r"提权.*管理员",
            r"获取.*root.*权限",
            r"绕过.*uac",
            r"bypass.*uac",
            r"token.*impersonation",
            r"elevate.*privilege",
        ],
        forbidden_keywords=[
            "提权", "权限提升", "获取管理员权限", "获取root权限",
            "绕过UAC", "bypass UAC", "特权升级", "权限escalation",
            "获取system权限", "成为root", "sudo提权", "su root",
            "privilege escalation", "gain admin rights", "elevate privileges",
            "提权到system", "获取最高权限", "权限绕过",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止未授权权限提升"
    ),

    MoralRule(
        rule_id="PRIVESC_002",
        category=RuleCategory.SYSTEM_OPERATION,
        name="阻止SUID滥用",
        description="检测SUID二进制文件滥用",
        patterns=[
            r"find.*-perm.*-4000",
            r"find.*-perm.*-u=s",
            r"find.*-perm.*2000",
            r"suid.*exploit",
            r"滥用suid",
        ],
        forbidden_keywords=[
            "查找suid文件", "滥用suid", "suid提权", "suid exploit",
            "利用suid二进制", "find suid", "suid滥用", "suid权限提升",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止SUID滥用"
    ),

    MoralRule(
        rule_id="PRIVESC_003",
        category=RuleCategory.SYSTEM_OPERATION,
        name="阻止内核漏洞利用",
        description="检测内核级漏洞利用",
        patterns=[
            r"kernel.*exploit",
            r"内核.*漏洞",
            r"提权.*漏洞",
            r"cve-\d{4}-\d{4,5}",
            r"dirty.*cow",
            r"sudo.*cve",
            r"pkexec",
            r"polkit",
        ],
        forbidden_keywords=[
            "内核漏洞", "kernel exploit", "提权漏洞", "权限提升漏洞",
            "利用内核漏洞", "exploit kernel", "dirty cow", "sudo漏洞",
            "内核提权", "本地提权漏洞", "LPE exploit",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止利用系统漏洞提权"
    ),

    MoralRule(
        rule_id="PRIVESC_004",
        category=RuleCategory.SYSTEM_OPERATION,
        name="阻止安全软件关闭",
        description="检测关闭或禁用安全软件",
        patterns=[
            r"关闭.*杀毒",
            r"禁用.*防火墙",
            r"停止.*defender",
            r"关闭.*安全中心",
            r"net\s+stop.*defender",
            r"sc\s+stop.*defender",
            r"Set-MpPreference.*Disable",
        ],
        forbidden_keywords=[
            "关闭杀毒软件", "禁用防火墙", "停止Windows Defender",
            "关闭安全软件", "禁用安全中心", "kill defender",
            "stop antivirus", "disable firewall", "关闭防护",
            "禁用defender", "关闭实时保护", "禁用安全服务",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止关闭安全软件"
    ),

    MoralRule(
        rule_id="PRIVESC_005",
        category=RuleCategory.SYSTEM_OPERATION,
        name="阻止计划任务提权",
        description="检测通过计划任务提权",
        patterns=[
            r"schtasks.*/rl\s+highest",
            r"schtasks.*system",
            r"计划任务.*提权",
            r"at\s+\\\d+:\d+.*",
            r"scheduled.*task.*elevate",
        ],
        forbidden_keywords=[
            "计划任务提权", "schtasks提权", "at命令提权",
            "创建系统计划任务", "scheduled task privilege",
            "任务计划提权", "最高权限运行",
        ],
        severity=MoralLevel.DANGEROUS,
        action="warn",
        message="谨慎创建高权限计划任务"
    ),

    MoralRule(
        rule_id="PRIVESC_006",
        category=RuleCategory.SYSTEM_OPERATION,
        name="阻止服务提权",
        description="检测通过服务提权",
        patterns=[
            r"sc\s+create.*binpath",
            r"sc\s+config.*binpath",
            r"创建.*服务.*提权",
            r"service.*exploit",
            r"unquoted.*service.*path",
        ],
        forbidden_keywords=[
            "服务提权", "创建服务提权", "sc命令提权",
            "unquoted service path", "服务路径提权",
            "服务权限提升", "创建系统服务",
        ],
        severity=MoralLevel.DANGEROUS,
        action="warn",
        message="谨慎修改系统服务"
    ),

    MoralRule(
        rule_id="PRIVESC_007",
        category=RuleCategory.SYSTEM_OPERATION,
        name="阻止DLL劫持",
        description="检测DLL劫持攻击",
        patterns=[
            r"dll.*hijack",
            r"dll.*劫持",
            r"替换.*系统.*dll",
            r"fake.*dll",
            r"恶意.*dll",
        ],
        forbidden_keywords=[
            "dll劫持", "dll hijacking", "替换系统dll", "恶意dll",
            "fake dll", "dll替换攻击", "预加载dll攻击",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止DLL劫持"
    ),

    MoralRule(
        rule_id="PRIVESC_008",
        category=RuleCategory.SYSTEM_OPERATION,
        name="阻止路径遍历提权",
        description="检测路径遍历攻击",
        patterns=[
            r"\.\.\\\.\.\\",
            r"\.\.\/\.\.\/",
            r"%2e%2e%2f",
            r"path.*traversal",
            r"目录遍历",
        ],
        forbidden_keywords=[
            "路径遍历", "目录遍历", "path traversal", "../攻击",
            "父目录遍历", "突破目录限制", "越权访问",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止路径遍历攻击"
    ),

    MoralRule(
        rule_id="PRIVESC_009",
        category=RuleCategory.SYSTEM_OPERATION,
        name="阻止注册表提权",
        description="检测通过注册表提权",
        patterns=[
            r"注册表.*提权",
            r"registry.*elevate",
            r"HKLM.*写入",
            r"HKEY_LOCAL_MACHINE",
            r"注册表.*runas",
        ],
        forbidden_keywords=[
            "注册表提权", "修改系统注册表", "注册表权限提升",
            "registry privilege", "系统注册表修改", "注册表漏洞",
        ],
        severity=MoralLevel.DANGEROUS,
        action="warn",
        message="谨慎修改系统注册表"
    ),

    MoralRule(
        rule_id="PRIVESC_010",
        category=RuleCategory.SYSTEM_OPERATION,
        name="阻止符号链接攻击",
        description="检测符号链接提权",
        patterns=[
            r"符号链接.*攻击",
            r"symlink.*attack",
            r"junction.*attack",
            r"硬链接.*提权",
            r"hardlink.*exploit",
        ],
        forbidden_keywords=[
            "符号链接攻击", "symlink attack", "硬链接提权",
            "junction攻击", "符号链接提权", "链接攻击",
        ],
        severity=MoralLevel.DANGEROUS,
        action="warn",
        message="谨慎创建符号链接"
    ),

    MoralRule(
        rule_id="PRIVESC_011",
        category=RuleCategory.SYSTEM_OPERATION,
        name="阻止AlwaysInstallElevated",
        description="检测MSI安装提权",
        patterns=[
            r"AlwaysInstallElevated",
            r"msi.*提权",
            r"installer.*elevate",
            r"msiexec.*admin",
        ],
        forbidden_keywords=[
            "AlwaysInstallElevated", "MSI提权", "安装包提权",
            "msi privilege", "installer elevate", "msi漏洞",
        ],
        severity=MoralLevel.DANGEROUS,
        action="warn",
        message="谨慎使用AlwaysInstallElevated"
    ),

    MoralRule(
        rule_id="PRIVESC_012",
        category=RuleCategory.SYSTEM_OPERATION,
        name="阻止Token操纵",
        description="检测Token权限操纵",
        patterns=[
            r"token.*操纵",
            r"adjust.*token",
            r"DuplicateToken",
            r"ImpersonateLoggedOnUser",
            r"token.*privilege",
        ],
        forbidden_keywords=[
            "Token操纵", "AdjustTokenPrivileges", "DuplicateToken",
            "token privilege", "impersonate token", "令牌权限",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止Token权限操纵"
    ),
]


if __name__ == "__main__":
    print(f"权限提升规则共 {len(PRIVILEGE_ESCALATION_RULES)} 条")
    for rule in PRIVILEGE_ESCALATION_RULES:
        print(f"  - {rule.rule_id}: {rule.name}")
