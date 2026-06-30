#!/usr/bin/env python3
"""
SafetyFramework - 统一的安全框架（Week 4功能整合）

整合三观提示词(ThreeViewsGenerator)和道德模块(MoralModule)，
提供统一的安全检查接口，遵循零静默失败原则。

核心功能：
1. 统一的安全提示词生成
2. 行动前道德与三观双重检查
3. 用户意图伦理审查
4. 记忆内容伦理标签
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.exceptions import MoralCheckError
from core.logger import logger


class SafetyLevel(Enum):
    """安全检查等级"""
    SAFE = "safe"           # 安全，允许执行
    WARNING = "warning"     # 警告，需谨慎
    DANGEROUS = "dangerous" # 危险，建议阻止
    FORBIDDEN = "forbidden" # 禁止，必须阻止


@dataclass
class SafetyCheckResult:
    """安全检查完整结果"""
    passed: bool                           # 是否通过检查
    safety_level: SafetyLevel              # 安全等级
    moral_passed: bool                     # 道德检查是否通过
    three_views_passed: bool               # 三观检查是否通过
    moral_reason: str = ""                 # 道德检查说明
    three_views_reason: str = ""           # 三观检查说明
    violated_rules: list[str] = field(default_factory=list)  # 违反的规则
    suggestion: str = ""                   # 改进建议
    safety_prompt: str = ""                # 生成的安全提示词


class SafetyFramework:
    """
    统一的安全框架（整合三观提示词和道德模块）

    设计原则：
    1. 延迟导入避免循环依赖
    2. 零静默失败 - 任何检查失败都抛出明确异常
    3. 双重验证 - 道德检查 + 三观检查
    4. 统一接口 - 提供简洁的 check() 和 generate_prompt() 方法

    使用示例：
        framework = SafetyFramework()

        # 生成安全提示词
        prompt = framework.generate_safety_prompt()

        # 检查行动
        result = framework.check_action("file_delete", {"path": "/tmp/test.txt"})
        if not result.passed:
            print(f"行动被拒绝: {result.suggestion}")
    """

    def __init__(self, user_id: str = "default"):
        """
        初始化安全框架

        Args:
            user_id: 用户ID，用于加载用户特定的三观配置
        """
        self.user_id = user_id
        self._three_views = None
        self._moral_module = None
        self._initialized = False

        logger.info(f"[SafetyFramework] 初始化完成，用户: {user_id}")

    def _lazy_init(self):
        """延迟初始化，避免循环依赖"""
        if self._initialized:
            return

        try:
            from core.reflector.three_views_generator import ThreeViewsGenerator
            from core.safety.moral_module import MoralModule

            self._three_views = ThreeViewsGenerator(user_id=self.user_id)
            self._moral_module = MoralModule()
            self._initialized = True

            logger.debug("[SafetyFramework] 延迟初始化完成")
        except Exception as e:
            logger.error(f"[SafetyFramework] 初始化失败: {e}")
            raise MoralCheckError(f"安全框架初始化失败: {e}") from e

    def generate_safety_prompt(self,
                               action_context: dict[str, Any] = None,
                               task_context: dict[str, Any] = None,
                               perception_context: dict[str, Any] = None) -> str:
        """
        生成统一的安全提示词

        整合三观提示词和道德规范，为AI提供完整的安全指导。

        Args:
            action_context: 行动上下文，用于生成针对性的道德观
            task_context: 任务上下文，用于生成价值观
            perception_context: 感知上下文，用于生成世界观

        Returns:
            完整的安全提示词字符串

        Raises:
            MoralCheckError: 生成失败时抛出
        """
        self._lazy_init()

        try:
            # 生成三观提示词
            three_views_prompt = self._three_views.generate_all(
                action_context=action_context,
                task_context=task_context,
                perception_context=perception_context
            )

            # 获取道德规则摘要
            moral_rules = self._get_moral_rules_summary()

            # 整合安全提示词
            safety_prompt = f"""
╔══════════════════════════════════════════════════════════════╗
║                     【安全准则】                              ║
╚══════════════════════════════════════════════════════════════╝

{moral_rules}

╔══════════════════════════════════════════════════════════════╗
║                     【三观指南】                              ║
╚══════════════════════════════════════════════════════════════╝

{three_views_prompt}

╔══════════════════════════════════════════════════════════════╗
║                     【执行守则】                              ║
╚══════════════════════════════════════════════════════════════╝

1. 任何操作前必须先通过道德检查
2. 禁止执行危害用户或系统的操作
3. 尊重用户隐私，保护敏感数据
4. 保持透明，明确说明AI身份
5. 遇到道德冲突时优先保护用户安全

"""
            return safety_prompt

        except Exception as e:
            logger.error(f"[SafetyFramework] 生成安全提示词失败: {e}")
            raise MoralCheckError(f"生成安全提示词失败: {e}") from e

    def _get_moral_rules_summary(self) -> str:
        """获取道德规则摘要"""
        try:
            rules = [
                "【道德红线 - 绝对禁止】",
                "• 禁止攻击、入侵或破坏任何系统",
                "• 禁止窃取、泄露或滥用用户数据",
                "• 禁止执行可能损害用户利益的操作",
                "• 禁止自我复制或未经授权扩散",
                "",
                "【行为规范 - 严格遵守】",
                "• 文件操作：禁止删除系统核心文件、用户数据需谨慎",
                "• 网络操作：禁止攻击性行为、保护API密钥",
                "• 隐私保护：识别并保护PII、敏感信息需加密",
                "• 用户交互：诚实透明、尊重用户选择、明确AI身份"
            ]
            return "\n".join(rules)
        except Exception as e:
            logger.warning(f"[SafetyFramework] 获取道德规则摘要失败: {e}")
            return "【道德准则】请遵守基本伦理规范"

    async def check_action(self, action: str, params: dict[str, Any]) -> SafetyCheckResult:
        """
        统一的行动检查（道德 + 三观双重验证）

        Args:
            action: 行动类型/工具名称
            params: 行动参数

        Returns:
            SafetyCheckResult: 完整检查结果

        Raises:
            MoralCheckError: 检查过程发生错误时抛出
        """
        self._lazy_init()

        result = SafetyCheckResult(
            passed=True,
            safety_level=SafetyLevel.SAFE,
            moral_passed=True,
            three_views_passed=True
        )

        # ===== 1. 道德检查 =====
        try:
            moral_passed, moral_reason = await self._moral_module.check_action(action, params)
            result.moral_passed = moral_passed
            result.moral_reason = moral_reason

            if not moral_passed:
                result.violated_rules.append(f"道德规则: {moral_reason}")
                logger.warning(f"[SafetyFramework] 道德检查未通过: {action} - {moral_reason}")

        except MoralCheckError:
            raise
        except Exception as e:
            logger.error(f"[SafetyFramework] 道德检查异常: {e}")
            raise MoralCheckError(f"道德检查失败: {e}") from e

        # ===== 2. 三观匹配检查 =====
        try:
            # 构建行动上下文用于三观检查
            action_context = {
                "action_type": action,
                "action_params": params
            }

            # 调用三观生成器的道德观检查
            moral_view = self._three_views.generate_moral_view(action_context)

            # 检查是否有违规标记
            if "⚠️" in moral_view or "违反" in moral_view:
                result.three_views_passed = False
                result.three_views_reason = "三观检查：当前操作与道德准则不符"
                result.violated_rules.append("三观规则: 操作不符合道德观")
                logger.warning(f"[SafetyFramework] 三观检查未通过: {action}")
            else:
                result.three_views_reason = "通过"

        except Exception as e:
            logger.error(f"[SafetyFramework] 三观检查异常: {e}")
            # 三观检查失败不阻断，但记录警告
            result.three_views_reason = f"检查异常: {e}"

        # ===== 3. 综合判断 =====
        result.passed = result.moral_passed and result.three_views_passed

        if not result.passed:
            # 确定安全等级
            if not result.moral_passed and "禁止" in result.moral_reason:
                result.safety_level = SafetyLevel.FORBIDDEN
            elif not result.moral_passed:
                result.safety_level = SafetyLevel.DANGEROUS
            else:
                result.safety_level = SafetyLevel.WARNING

            # 生成建议
            suggestions = []
            if not result.moral_passed:
                suggestions.append(f"道德方面: {result.moral_reason}")
            if not result.three_views_passed:
                suggestions.append(f"三观方面: {result.three_views_reason}")
            suggestions.append("请修改操作或寻求用户确认")
            result.suggestion = "; ".join(suggestions)

        # 生成安全提示词（供后续使用）
        try:
            result.safety_prompt = self.generate_safety_prompt(
                action_context={"action_type": action, "action_params": params}
            )
        except Exception as e:
            logger.warning(f"[SafetyFramework] 生成安全提示词失败: {e}")

        logger.info(f"[SafetyFramework] 行动检查完成: {action} -> {'通过' if result.passed else '拒绝'}")
        return result

    async def check_intent(self, user_input: str) -> SafetyCheckResult:
        """
        用户意图伦理审查

        Args:
            user_input: 用户输入文本

        Returns:
            SafetyCheckResult: 检查结果
        """
        self._lazy_init()

        result = SafetyCheckResult(
            passed=True,
            safety_level=SafetyLevel.SAFE,
            moral_passed=True,
            three_views_passed=True
        )

        # 道德意图检查
        try:
            moral_passed, moral_reason = await self._moral_module.check_intent(user_input)
            result.moral_passed = moral_passed
            result.moral_reason = moral_reason

            if not moral_passed:
                result.violated_rules.append(f"意图违规: {moral_reason}")
                result.passed = False
                result.safety_level = SafetyLevel.FORBIDDEN
                result.suggestion = f"意图检查未通过: {moral_reason}"
                logger.warning(f"[SafetyFramework] 意图检查未通过: {moral_reason}")

        except MoralCheckError:
            raise
        except Exception as e:
            logger.error(f"[SafetyFramework] 意图检查异常: {e}")
            raise MoralCheckError(f"意图检查失败: {e}") from e

        return result

    async def check_memory_content(self, content: str) -> dict[str, Any]:
        """
        检查记忆内容的伦理标签

        Args:
            content: 记忆内容

        Returns:
            包含伦理标签的字典
        """
        self._lazy_init()

        try:
            tag = await self._moral_module.tag_memory(content)
            return {
                "contains_pii": tag.contains_pii,
                "contains_sensitive": tag.contains_sensitive,
                "contains_financial": tag.contains_financial,
                "contains_credentials": tag.contains_credentials,
                "security_level": tag.security_level,
                "retention_days": tag.retention_days,
                "encryption_required": tag.encryption_required
            }
        except Exception as e:
            logger.error(f"[SafetyFramework] 记忆伦理标签检查失败: {e}")
            raise MoralCheckError(f"记忆伦理检查失败: {e}") from e

    async def get_stats(self) -> dict[str, Any]:
        """获取安全框架统计信息"""
        self._lazy_init()

        try:
            moral_stats = await self._moral_module.get_stats()
            return {
                "user_id": self.user_id,
                "initialized": self._initialized,
                "moral_stats": moral_stats,
                "three_views_template": self._three_views.template.get("name", "unknown") if self._three_views else None
            }
        except Exception as e:
            logger.error(f"[SafetyFramework] 获取统计信息失败: {e}")
            return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# 全局实例和便捷函数
# ═══════════════════════════════════════════════════════════════════════════════

_safety_framework_instance: SafetyFramework | None = None


def get_safety_framework(user_id: str = "default") -> SafetyFramework:
    """获取安全框架全局实例"""
    global _safety_framework_instance
    if _safety_framework_instance is None:
        _safety_framework_instance = SafetyFramework(user_id=user_id)
    return _safety_framework_instance


async def check_action_safety(action: str, params: dict[str, Any],
                        user_id: str = "default") -> tuple[bool, str]:
    """
    便捷函数：检查行动安全性

    Args:
        action: 行动名称
        params: 行动参数
        user_id: 用户ID

    Returns:
        (是否安全, 说明)
    """
    framework = get_safety_framework(user_id)
    result = await framework.check_action(action, params)
    return result.passed, result.suggestion if not result.passed else "通过"


async def check_intent_safety(user_input: str, user_id: str = "default") -> tuple[bool, str]:
    """
    便捷函数：检查用户意图安全性

    Args:
        user_input: 用户输入
        user_id: 用户ID

    Returns:
        (是否安全, 说明)
    """
    framework = get_safety_framework(user_id)
    result = await framework.check_intent(user_input)
    return result.passed, result.suggestion if not result.passed else "通过"


def generate_safety_prompt(user_id: str = "default") -> str:
    """
    便捷函数：生成安全提示词

    Args:
        user_id: 用户ID

    Returns:
        安全提示词
    """
    framework = get_safety_framework(user_id)
    return framework.generate_safety_prompt()


# ═══════════════════════════════════════════════════════════════════════════════
# 文件总结
# ═══════════════════════════════════════════════════════════════════════════════
#
# 【文件角色】
# SafetyFramework是Week 4功能整合的核心组件之一，统一整合三观提示词和道德模块，
# 为系统提供统一的安全检查入口。
#
# 【核心功能】
# 1. 统一安全提示词生成：整合三观提示词 + 道德规则
# 2. 双重检查机制：道德检查 + 三观检查
# 3. 用户意图审查：伦理层面的意图分析
# 4. 记忆伦理标签：敏感内容识别和分类
#
# 【设计特点】
# 1. 延迟初始化：避免循环依赖
# 2. 零静默失败：所有错误都抛出明确异常
# 3. 完整结果：SafetyCheckResult包含详细的检查信息
# 4. 便捷函数：提供简单易用的全局函数
#
# 【使用场景】
# 1. AgentLoop执行工具前调用check_action()
# 2. 用户输入处理前调用check_intent()
# 3. 系统提示词构建时调用generate_safety_prompt()
# 4. 记忆存储前调用check_memory_content()
#
# ═══════════════════════════════════════════════════════════════════════════════
