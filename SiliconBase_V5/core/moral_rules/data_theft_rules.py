"""
数据窃取类规则 - 15条

覆盖场景：
- 复制用户文件到外部存储
- 数据库导出
- 敏感文件访问
- 浏览器数据窃取
- 键盘记录
- 等...
"""

import os
import sys

# 添加父目录到路径以导入MoralRule
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from core.safety.moral_module import MoralLevel, MoralRule, RuleCategory
except ImportError:
    # 如果导入失败，使用最小定义
    from dataclasses import dataclass
    from enum import Enum

    class RuleCategory(Enum):
        PRIVACY_PROTECTION = "privacy_protection"
        FILE_OPERATION = "file_operation"
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


# 数据窃取类规则 (15条)
DATA_THEFT_RULES = [
    MoralRule(
        rule_id="DATA_001",
        category=RuleCategory.PRIVACY_PROTECTION,
        name="阻止复制用户文件到外部",
        description="检测将用户文件复制到外部存储或网络位置",
        patterns=[
            r"复制.*到.*(u盘|移动硬盘|网盘|云盘|外部|usb|移动设备)",
            r"copy.*to.*(usb|external|cloud|drive|removable)",
            r"上传.*文件.*到.*(服务器|远程|网盘|外部)",
            r"scp\s+.*\s+.*@.*:",
            r"rsync\s+.*\s+.*@.*:",
            r"ftp.*put.*",
        ],
        forbidden_keywords=[
            "窃取用户数据", "偷取文件", "拷贝用户文件", "盗取数据",
            "复制用户文件到外部", "上传用户数据到远程", "导出用户隐私",
            "窃取浏览器历史", "偷取cookie", "盗取密码", "获取用户信息",
            "copy user data", "steal files", "exfiltrate data",
            "extract user info", "dump database", "export customer data",
            "外发数据", "外传文件", "私自拷贝",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止窃取或导出用户数据"
    ),

    MoralRule(
        rule_id="DATA_002",
        category=RuleCategory.PRIVACY_PROTECTION,
        name="阻止数据库导出",
        description="检测未经授权的数据库导出操作",
        patterns=[
            r"mysqldump\s+.*",
            r"pg_dump\s+.*",
            r"mongoexport\s+.*",
            r"select.*into\s+outfile",
            r"导出.*数据库",
            r"备份.*客户.*数据",
            r"导出.*用户.*表",
            r"dump.*database",
        ],
        forbidden_keywords=[
            "导出数据库", "dump数据库", "导出客户数据", "导出用户信息",
            "mysqldump", "pg_dump", "mongoexport", "数据库备份到外部",
            "导出所有数据", "备份敏感数据", "批量导出用户",
            "export database", "dump customer data", "extract user records",
            "数据转储", "数据库导出", "完整备份数据库",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止未经授权导出数据库"
    ),

    MoralRule(
        rule_id="DATA_003",
        category=RuleCategory.PRIVACY_PROTECTION,
        name="阻止敏感文件访问",
        description="检测访问系统敏感文件",
        patterns=[
            r"/etc/shadow",
            r"/etc/passwd",
            r"/etc/master\.passwd",
            r"\.ssh/.*",
            r"\.aws/.*",
            r"\.azure/.*",
            r"id_rsa",
            r"id_dsa",
            r"id_ecdsa",
            r"id_ed25519",
            r"\.ssh/id_.*",
            r"known_hosts",
            r"authorized_keys",
            r"\.htpasswd",
            r"secrets\.json",
            r"credentials\.xml",
        ],
        forbidden_keywords=[
            "读取shadow文件", "获取密码hash", "窃取ssh密钥",
            "访问系统密码文件", "读取私钥", "获取凭据文件",
            "read shadow", "steal ssh keys", "access credentials",
            "访问敏感文件", "读取密钥文件", "获取系统密码",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止访问系统敏感文件"
    ),

    MoralRule(
        rule_id="DATA_004",
        category=RuleCategory.PRIVACY_PROTECTION,
        name="阻止浏览器数据窃取",
        description="检测窃取浏览器存储的数据",
        patterns=[
            r"chrome.*cookie",
            r"firefox.*password",
            r"edge.*history",
            r"browser.*data",
            r"浏览器.*密码",
            r"窃取.*浏览器",
            r"login\s+data.*sqlite",
            r"cookies\.sqlite",
            r"places\.sqlite",
        ],
        forbidden_keywords=[
            "窃取浏览器密码", "获取浏览器cookie", "读取浏览器历史",
            "盗取浏览器书签", "提取保存的密码", "获取自动填充数据",
            "steal browser passwords", "extract saved credentials",
            "盗取浏览器数据", "获取浏览器缓存", "窃取登录信息",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止窃取浏览器数据"
    ),

    MoralRule(
        rule_id="DATA_005",
        category=RuleCategory.PRIVACY_PROTECTION,
        name="阻止键盘记录",
        description="检测键盘记录行为",
        patterns=[
            r"keylogger",
            r"键盘记录",
            r"记录.*按键",
            r"捕获.*键盘",
            r"hook.*keyboard",
            r"hook.*key",
            r"GetAsyncKeyState",
            r"SetWindowsHookEx.*WH_KEYBOARD",
        ],
        forbidden_keywords=[
            "键盘记录", "keylogger", "记录用户输入", "捕获按键",
            "键盘监控", "输入记录", "keystroke logging",
            "记录密码输入", "监听键盘", "记录所有按键",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止键盘记录"
    ),

    MoralRule(
        rule_id="DATA_006",
        category=RuleCategory.PRIVACY_PROTECTION,
        name="阻止剪贴板监控",
        description="检测剪贴板数据窃取",
        patterns=[
            r"监控.*剪贴板",
            r"clipboard.*监控",
            r"读取.*剪贴板",
            r"clipboard.*hook",
            r"SetClipboardViewer",
        ],
        forbidden_keywords=[
            "监控剪贴板", "剪贴板记录", "获取剪贴板内容",
            "clipboard monitor", "clipboard hook", "read clipboard",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止监控剪贴板"
    ),

    MoralRule(
        rule_id="DATA_007",
        category=RuleCategory.PRIVACY_PROTECTION,
        name="阻止屏幕监控",
        description="检测未经授权的屏幕监控",
        patterns=[
            r"持续.*截图",
            r"定时.*屏幕",
            r"监控.*屏幕",
            r"screen.*capture.*loop",
            r"连续.*截屏",
        ],
        forbidden_keywords=[
            "持续截图", "定时截屏", "屏幕监控", "录屏上传",
            "连续截屏", "自动截图上传", "监控屏幕活动",
        ],
        severity=MoralLevel.DANGEROUS,
        action="warn",
        message="谨慎进行屏幕监控"
    ),

    MoralRule(
        rule_id="DATA_008",
        category=RuleCategory.PRIVACY_PROTECTION,
        name="阻止邮件数据窃取",
        description="检测窃取邮件数据",
        patterns=[
            r"导出.*邮件",
            r"备份.*邮箱",
            r"下载.*所有.*邮件",
            r"export.*email",
            r" PST ",
            r"\.pst",
            r"\.ost",
        ],
        forbidden_keywords=[
            "导出所有邮件", "备份邮箱数据", "下载邮件",
            "export emails", "dump mailbox", "窃取邮件",
        ],
        severity=MoralLevel.DANGEROUS,
        action="warn",
        message="谨慎导出邮件数据"
    ),

    MoralRule(
        rule_id="DATA_009",
        category=RuleCategory.PRIVACY_PROTECTION,
        name="阻止聊天记录窃取",
        description="检测窃取即时通讯记录",
        patterns=[
            r"导出.*微信.*记录",
            r"导出.*QQ.*记录",
            r"聊天记录.*备份",
            r"chat.*history.*export",
            r"message.*backup",
        ],
        forbidden_keywords=[
            "导出聊天记录", "备份聊天数据", "获取聊天历史",
            "导出微信记录", "导出QQ记录", "聊天记录窃取",
        ],
        severity=MoralLevel.DANGEROUS,
        action="warn",
        message="谨慎导出聊天记录"
    ),

    MoralRule(
        rule_id="DATA_010",
        category=RuleCategory.PRIVACY_PROTECTION,
        name="阻止通讯录窃取",
        description="检测窃取通讯录/联系人",
        patterns=[
            r"导出.*通讯录",
            r"备份.*联系人",
            r"contact.*export",
            r"address.*book.*backup",
        ],
        forbidden_keywords=[
            "导出通讯录", "备份联系人", "获取所有联系人",
            "export contacts", "dump address book", "窃取通讯录",
        ],
        severity=MoralLevel.DANGEROUS,
        action="warn",
        message="谨慎导出通讯录"
    ),

    MoralRule(
        rule_id="DATA_011",
        category=RuleCategory.PRIVACY_PROTECTION,
        name="阻止文档窃取",
        description="检测批量文档窃取",
        patterns=[
            r"打包.*所有.*文档",
            r"压缩.*word.*excel",
            r"收集.*所有.*文件",
            r"archive.*all.*documents",
        ],
        forbidden_keywords=[
            "打包所有文档", "收集工作文件", "批量复制文档",
            "archive documents", "collect all files", "批量窃取文件",
        ],
        severity=MoralLevel.DANGEROUS,
        action="warn",
        message="谨慎批量收集文档"
    ),

    MoralRule(
        rule_id="DATA_012",
        category=RuleCategory.PRIVACY_PROTECTION,
        name="阻止证书窃取",
        description="检测窃取数字证书",
        patterns=[
            r"导出.*证书",
            r"备份.*私钥",
            r"certificate.*export",
            r"private.*key.*backup",
            r"\.pfx",
            r"\.p12",
        ],
        forbidden_keywords=[
            "导出证书", "备份私钥", "获取数字证书",
            "export certificate", "steal private key", "证书窃取",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止窃取数字证书"
    ),

    MoralRule(
        rule_id="DATA_013",
        category=RuleCategory.PRIVACY_PROTECTION,
        name="阻止WiFi密码窃取",
        description="检测窃取WiFi密码",
        patterns=[
            r"wifi.*密码",
            r"无线.*密码",
            r"wlan.*key",
            r"wireless.*password",
            r"netsh.*key.*clear",
        ],
        forbidden_keywords=[
            "获取WiFi密码", "窃取无线密码", "查看保存的WiFi",
            "wifi password", "wireless key", "窃取网络密码",
        ],
        severity=MoralLevel.DANGEROUS,
        action="warn",
        message="谨慎获取WiFi密码"
    ),

    MoralRule(
        rule_id="DATA_014",
        category=RuleCategory.PRIVACY_PROTECTION,
        name="阻止Token窃取",
        description="检测窃取认证令牌",
        patterns=[
            r"token.*窃取",
            r"session.*hijack",
            r"cookie.*steal",
            r"jwt.*decode",
            r"bearer.*token",
        ],
        forbidden_keywords=[
            "窃取token", "劫持session", "盗取cookie",
            "token theft", "session hijacking", "cookie stealing",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止窃取认证令牌"
    ),

    MoralRule(
        rule_id="DATA_015",
        category=RuleCategory.PRIVACY_PROTECTION,
        name="阻止云凭证窃取",
        description="检测窃取云服务凭证",
        patterns=[
            r"aws.*credential",
            r"azure.*key",
            r"gcp.*token",
            r"aliyun.*ak",
            r"云.*密钥",
            r"access.*key.*secret",
        ],
        forbidden_keywords=[
            "窃取云凭证", "获取access key", "盗取云服务密钥",
            "aws credential theft", "cloud key steal", "云平台密钥窃取",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止窃取云凭证"
    ),
]


if __name__ == "__main__":
    print(f"数据窃取规则共 {len(DATA_THEFT_RULES)} 条")
    for rule in DATA_THEFT_RULES:
        print(f"  - {rule.rule_id}: {rule.name}")
