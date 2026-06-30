"""
社会工程类规则 - 10条

覆盖场景：
- 冒充身份
- 密码诱导
- 紧急诱导
- 虚假奖励
- 恐吓威胁
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
        USER_INTERACTION = "user_interaction"
        CONTENT_SAFETY = "content_safety"

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


# 社会工程类规则 (10条)
SOCIAL_ENGINEERING_RULES = [
    MoralRule(
        rule_id="SOCENG_001",
        category=RuleCategory.USER_INTERACTION,
        name="阻止冒充身份",
        description="检测冒充他人身份",
        patterns=[
            r"假装.*是.*",
            r"冒充.*",
            r"伪装.*",
            r"假冒.*",
            r"假扮.*",
            r"pretend.*to.*be",
            r"impersonate",
            r"masquerade.*as",
        ],
        forbidden_keywords=[
            "假装是", "冒充", "伪装成", "假冒", "假扮",
            "假装是系统管理员", "冒充客服", "伪装成银行",
            "pretend to be", "impersonate", "fake identity",
            "冒充技术支持", "假冒官方人员", "伪装成警察",
            "冒充公检法", "假装是公司领导", "冒充IT支持",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止冒充他人身份"
    ),

    MoralRule(
        rule_id="SOCENG_002",
        category=RuleCategory.USER_INTERACTION,
        name="阻止密码诱导",
        description="检测诱导用户透露密码",
        patterns=[
            r"诱导.*透露.*密码",
            r"骗取.*密码",
            r"索要.*密码",
            r"请输入.*密码",
            r"password.*please",
            r"提供.*密码",
            r"告诉我.*密码",
        ],
        forbidden_keywords=[
            "诱导用户透露密码", "骗取密码", "索要密码",
            "诱导输入密码", "骗取账号密码", "获取用户凭证",
            "phishing", "诱导点击", "钓鱼攻击",
            "trick password", "obtain credentials", "密码欺骗",
            "骗取登录信息", "诱导提供密码", "密码套取",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止诱导用户透露密码"
    ),

    MoralRule(
        rule_id="SOCENG_003",
        category=RuleCategory.USER_INTERACTION,
        name="阻止紧急诱导",
        description="检测制造紧急感的诱导",
        patterns=[
            r"紧急.*需要.*",
            r"立即.*否则.*",
            r"马上.*不然.*",
            r"urgent.*action",
            r"立即.*提供",
            r"马上.*处理",
            r"立刻.*行动",
            r"act.*now",
            r"limited.*time",
        ],
        forbidden_keywords=[
            "紧急情况", "立即行动", "马上处理", "时间紧迫",
            "否则后果", "urgent", "immediate action", "act now",
            "账户即将冻结", "安全警报", "立即验证", "马上确认",
            "限时", "过期失效", "立即点击", "马上提供",
        ],
        severity=MoralLevel.WARNING,
        action="warn",
        message="警惕紧急诱导"
    ),

    MoralRule(
        rule_id="SOCENG_004",
        category=RuleCategory.USER_INTERACTION,
        name="阻止虚假奖励诱导",
        description="检测虚假奖励诱惑",
        patterns=[
            r"中奖.*领取",
            r"免费.*获得",
            r"恭喜.*获奖",
            r"click.*win",
            r"免费.*抽奖",
            r"you.*won",
            r"prize.*claim",
            r"winner.*selected",
        ],
        forbidden_keywords=[
            "你中奖了", "免费领取", "恭喜获奖", "click here to win",
            "虚假中奖", "中奖诈骗", "免费奖励", "prize scam",
            "恭喜您中奖", "幸运用户", "大奖等你拿", "免费领取奖品",
            "中奖通知", "奖品领取", "免费送礼", "恭喜中奖",
        ],
        severity=MoralLevel.WARNING,
        action="warn",
        message="警惕虚假奖励诱导"
    ),

    MoralRule(
        rule_id="SOCENG_005",
        category=RuleCategory.USER_INTERACTION,
        name="阻止恐吓诱导",
        description="检测恐吓威胁手段",
        patterns=[
            r"不.*就.*",
            r"否则.*后果",
            r"小心.*",
            r"威胁.*",
            r"or else",
            r"不然.*麻烦",
            r"将.*追究",
            r"承担.*责任",
        ],
        forbidden_keywords=[
            "不照做就", "否则后果自负", "小心你的", "威胁",
            "恐吓用户", "or else", "if you don't", "不然就",
            "将追究法律责任", "承担一切后果", "你会后悔的",
        ],
        severity=MoralLevel.WARNING,
        action="warn",
        message="警惕恐吓威胁"
    ),

    MoralRule(
        rule_id="SOCENG_006",
        category=RuleCategory.USER_INTERACTION,
        name="阻止权威冒充",
        description="检测冒充权威机构",
        patterns=[
            r"我是.*警察",
            r"我是.*法院",
            r"我是.*检察院",
            r"公安局.*通知",
            r"法院.*传票",
            r"银行.*安全",
            r"客服.*中心",
        ],
        forbidden_keywords=[
            "我是警察", "我是法院", "我是检察院", "公安局通知",
            "法院传票", "冒充公检法", "权威恐吓", "官方威胁",
            "冒充银行", "冒充客服", "政府机关", "执法部门",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止冒充权威机构"
    ),

    MoralRule(
        rule_id="SOCENG_007",
        category=RuleCategory.USER_INTERACTION,
        name="阻止同情心诱导",
        description="检测利用同情心的诱导",
        patterns=[
            r"求助",
            r"捐款",
            r"慈善.*诈骗",
            r"可怜.*请.*帮助",
            r"生病.*需要.*钱",
            r"donation.*scam",
        ],
        forbidden_keywords=[
            "虚假求助", "捐款诈骗", "利用同情心", "慈善骗局",
            "假慈善", "求助诈骗", "爱心骗局", "donation scam",
        ],
        severity=MoralLevel.WARNING,
        action="warn",
        message="警惕虚假求助"
    ),

    MoralRule(
        rule_id="SOCENG_008",
        category=RuleCategory.USER_INTERACTION,
        name="阻止技术支持诈骗",
        description="检测虚假技术支持",
        patterns=[
            r"技术支持.*来电",
            r"电脑.*病毒",
            r"系统.*问题",
            r"remote.*access",
            r"teamviewer.*连接",
            r"anydesk.*连接",
        ],
        forbidden_keywords=[
            "虚假技术支持", "技术诈骗", "远程控制诈骗",
            "tech support scam", "remote access scam", "假冒技术支持",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止虚假技术支持"
    ),

    MoralRule(
        rule_id="SOCENG_009",
        category=RuleCategory.USER_INTERACTION,
        name="阻止熟人冒充",
        description="检测冒充熟人",
        patterns=[
            r"我是.*领导",
            r"我是.*老板",
            r"换.*手机号",
            r"新.*号码",
            r"老板.*要求",
            r"领导.*指示",
        ],
        forbidden_keywords=[
            "冒充领导", "冒充老板", "我是你领导", "我是你老板",
            "换手机号了", "新号码", "领导要求转账", "熟人诈骗",
        ],
        severity=MoralLevel.FORBIDDEN,
        action="block",
        message="禁止冒充熟人"
    ),

    MoralRule(
        rule_id="SOCENG_010",
        category=RuleCategory.USER_INTERACTION,
        name="阻止信息收集",
        description="检测过度信息收集",
        patterns=[
            r"身份证.*号",
            r"银行卡.*号",
            r"验证码",
            r"CVV",
            r"有效期",
            r"社保.*号",
            r"家庭.*住址",
        ],
        forbidden_keywords=[
            "索要身份证", "要银行卡号", "要验证码", "收集个人信息",
            "过度信息收集", "敏感信息套取", "隐私信息收集",
        ],
        severity=MoralLevel.WARNING,
        action="warn",
        message="警惕过度信息收集"
    ),
]


if __name__ == "__main__":
    print(f"社会工程规则共 {len(SOCIAL_ENGINEERING_RULES)} 条")
    for rule in SOCIAL_ENGINEERING_RULES:
        print(f"  - {rule.rule_id}: {rule.name}")
