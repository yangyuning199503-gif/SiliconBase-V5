"""
道德规则子模块

包含新增的65条安全规则：
- 数据窃取规则 (15条)
- 权限提升规则 (12条)
- 恶意操作规则 (18条)
- 社会工程规则 (10条)
- 变形攻击检测规则 (10条)
"""

from .data_theft_rules import DATA_THEFT_RULES
from .evasion_rules import EVASION_DETECTION_RULES
from .malicious_operation_rules import MALICIOUS_OPERATION_RULES
from .privilege_escalation_rules import PRIVILEGE_ESCALATION_RULES
from .social_engineering_rules import SOCIAL_ENGINEERING_RULES

__all__ = [
    'DATA_THEFT_RULES',
    'PRIVILEGE_ESCALATION_RULES',
    'MALICIOUS_OPERATION_RULES',
    'SOCIAL_ENGINEERING_RULES',
    'EVASION_DETECTION_RULES',
]

# 所有增强规则的总数
TOTAL_ENHANCED_RULES = (
    len(DATA_THEFT_RULES) +
    len(PRIVILEGE_ESCALATION_RULES) +
    len(MALICIOUS_OPERATION_RULES) +
    len(SOCIAL_ENGINEERING_RULES) +
    len(EVASION_DETECTION_RULES)
)


def get_all_enhanced_rules():
    """获取所有增强规则"""
    all_rules = []
    all_rules.extend(DATA_THEFT_RULES)
    all_rules.extend(PRIVILEGE_ESCALATION_RULES)
    all_rules.extend(MALICIOUS_OPERATION_RULES)
    all_rules.extend(SOCIAL_ENGINEERING_RULES)
    all_rules.extend(EVASION_DETECTION_RULES)
    return all_rules
