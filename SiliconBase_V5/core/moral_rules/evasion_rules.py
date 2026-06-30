"""
变形攻击/规避检测类规则 - 10条

覆盖场景：
- 编码绕过
- 大小写混淆
- 同义词替换
- 拼音混合
- 分隔符绕过
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


# 变形攻击检测规则 (10条)
EVASION_DETECTION_RULES = [
    MoralRule(
        rule_id="EVADE_001",
        category=RuleCategory.CONTENT_SAFETY,
        name="阻止编码绕过",
        description="检测使用编码绕过安全检查",
        patterns=[
            r"base64.*解码.*执行",
            r"base64.*解码.*运行",
            r"hex.*解码.*执行",
            r"hex.*解码.*运行",
            r"rot13.*解码",
            r"url.*解码.*执行",
            r"urldecode.*执行",
            r"decode.*execute",
            r"编码.*绕过",
        ],
        forbidden_keywords=[
            "base64绕过", "编码绕过", "混淆执行", "解码后执行",
            "base64 decode execute", "hex decode run", "encoded payload",
            "编码规避", "混淆绕过", "编码攻击",
        ],
        severity=MoralLevel.DANGEROUS,
        action="warn",
        message="警惕编码绕过"
    ),

    MoralRule(
        rule_id="EVADE_002",
        category=RuleCategory.CONTENT_SAFETY,
        name="阻止大小写混淆",
        description="检测大小写混以规避检测",
        patterns=[
            r"[Ff][Oo][Rr][Mm][Aa][Tt]",
            r"[Dd][Ee][Ll][Ee][Tt][Ee]",
            r"[Rr][Mm]\s+-[Rr][Ff]",
            r"[Ss][Tt][Ee][Aa][Ll]",
            r"[Hh][Aa][Cc][Kk]",
            r"[Aa][Tt][Tt][Aa][Cc][Kk]",
        ],
        forbidden_keywords=[
            "大小写混淆", "绕过检测", "规避审查",
            "case obfuscation", "bypass filter", "大小写绕过",
        ],
        severity=MoralLevel.DANGEROUS,
        action="warn",
        message="警惕规避检测"
    ),

    MoralRule(
        rule_id="EVADE_003",
        category=RuleCategory.CONTENT_SAFETY,
        name="阻止同义词替换",
        description="检测使用同义词绕过",
        patterns=[
            r"删.*除",  # 删除的变体
            r"格.*式.*化",  # 格式化的变体
            r"窃.*取",  # 窃取的变体
            r"攻.*击",  # 攻击的变体
            r"入.*侵",  # 入侵的变体
        ],
        forbidden_keywords=[
            "shan chu", "shan除", "删chu",  # 拼音混合
            "格shihua", "格式hua", "格士化",
            "qie qu", "窃qu", "窃取数据",
            "拼音绕过", "同音字绕过", "拆字攻击",
        ],
        severity=MoralLevel.DANGEROUS,
        action="warn",
        message="警惕同义词替换"
    ),

    MoralRule(
        rule_id="EVADE_004",
        category=RuleCategory.CONTENT_SAFETY,
        name="阻止分隔符绕过",
        description="检测使用分隔符规避",
        patterns=[
            r"格\s*式\s*化",  # 格式化带空格
            r"删\s*除",
            r"攻\s*击",
            r"入\s*侵",
            r"f\s*o\s*r\s*m\s*a\s*t",
            r"d\s*e\s*l\s*e\s*t\s*e",
        ],
        forbidden_keywords=[
            "空格分隔", "字符分隔", "分隔符绕过",
            "插入符号", "特殊字符分隔", "绕过检测",
        ],
        severity=MoralLevel.WARNING,
        action="warn",
        message="警惕分隔符绕过"
    ),

    MoralRule(
        rule_id="EVADE_005",
        category=RuleCategory.CONTENT_SAFETY,
        name="阻止Unicode规范化绕过",
        description="检测Unicode等价字符绕过",
        patterns=[
            r"\uFF44\uFF45\uFF4C\uFF45\uFF54\uFF45",  # 全角delete
            r"ｆｏｒｍａｔ",  # 全角format
        ],
        forbidden_keywords=[
            "unicode绕过", "全角字符", "等价字符",
            "unicode evasion", "homograph attack", "同形异义",
        ],
        severity=MoralLevel.WARNING,
        action="warn",
        message="警惕Unicode绕过"
    ),

    MoralRule(
        rule_id="EVADE_006",
        category=RuleCategory.CONTENT_SAFETY,
        name="阻止注释混淆",
        description="检测使用注释符混淆",
        patterns=[
            r"格/\*.*\*/式化",
            r"格<!--.*-->式化",
            r"del/\*\*/ete",
            r"form/\*\*/at",
        ],
        forbidden_keywords=[
            "注释绕过", "注释混淆", "/* */绕过",
            "html注释绕过", "注释符规避", "comment evasion",
        ],
        severity=MoralLevel.WARNING,
        action="warn",
        message="警惕注释混淆"
    ),

    MoralRule(
        rule_id="EVADE_007",
        category=RuleCategory.CONTENT_SAFETY,
        name="阻止零宽字符",
        description="检测零宽字符隐藏",
        patterns=[
            r"\u200B",  # 零宽空格
            r"\u200C",  # 零宽非连接符
            r"\u200D",  # 零宽连接符
            r"\uFEFF",  # 零宽非断空格
        ],
        forbidden_keywords=[
            "零宽字符", "零宽空格", "隐藏字符",
            "zero width", "invisible character", "隐写",
        ],
        severity=MoralLevel.WARNING,
        action="warn",
        message="警惕零宽字符隐藏"
    ),

    MoralRule(
        rule_id="EVADE_008",
        category=RuleCategory.CONTENT_SAFETY,
        name="阻止表情符号混淆",
        description="检测使用emoji绕过",
        patterns=[
            r"格📝式化",
            r"删❌除",
            r"攻💥击",
        ],
        forbidden_keywords=[
            "表情符号绕过", "emoji绕过", "图标混淆",
            "emoji evasion", "icon obfuscation",
        ],
        severity=MoralLevel.WARNING,
        action="warn",
        message="警惕表情符号混淆"
    ),

    MoralRule(
        rule_id="EVADE_009",
        category=RuleCategory.CONTENT_SAFETY,
        name="阻止转义序列绕过",
        description="检测转义序列规避",
        patterns=[
            r"\\x66\\x6f\\x72\\x6d\\x61\\x74",  # hex转义
            r"\\u0066\\u006f\\u0072\\u006d\\u0061\\u0074",  # unicode转义
            r"\\146\\157\\162\\155\\141\\164",  # octal转义
        ],
        forbidden_keywords=[
            "转义序列", "hex转义", "unicode转义",
            "escape sequence", "编码转义", "转义绕过",
        ],
        severity=MoralLevel.WARNING,
        action="warn",
        message="警惕转义序列绕过"
    ),

    MoralRule(
        rule_id="EVADE_010",
        category=RuleCategory.CONTENT_SAFETY,
        name="阻止语音/方言绕过",
        description="检测方言/谐音绕过",
        patterns=[
            r"shan\s*chu",
            r"ge\s*shi\s*hua",
            r"dao\s*qu",
            r"shan\s*dong\s*hua",
        ],
        forbidden_keywords=[
            "方言绕过", "谐音绕过", "拼音攻击",
            "dialect evasion", "homophone attack", "语音绕过",
        ],
        severity=MoralLevel.WARNING,
        action="warn",
        message="警惕方言/谐音绕过"
    ),
]


if __name__ == "__main__":
    print(f"变形攻击检测规则共 {len(EVASION_DETECTION_RULES)} 条")
    for rule in EVASION_DETECTION_RULES:
        print(f"  - {rule.rule_id}: {rule.name}")
