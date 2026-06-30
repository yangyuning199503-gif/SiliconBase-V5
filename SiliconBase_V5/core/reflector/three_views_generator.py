#!/usr/bin/env python3
"""
三观提示词生成器
将道德系统、价值系统、世界模型的数据转换为自然语言提示词
"""

from dataclasses import dataclass
from typing import Any

from core.config import config
from core.safety.moral_system import get_moral_guard
from core.strategy.value_system_v2 import value_system_v2

try:
    from core.world_model.world_model import get_world_model
except Exception:
    get_world_model = None
from core.logger import logger


@dataclass
class ThreeViewsConfig:
    """三观配置数据类"""
    template_name: str = "balanced"  # 模板名称
    world_view: dict[str, Any] = None
    life_view: dict[str, Any] = None
    value_system: dict[str, Any] = None

    def __post_init__(self):
        if self.world_view is None:
            self.world_view = {}
        if self.life_view is None:
            self.life_view = {}
        if self.value_system is None:
            self.value_system = {}


class ThreeViewsGenerator:
    """
    三观提示词生成器

    将系统模块数据转换为AI可理解的自然语言提示词
    支持一键模板和自定义配置
    """

    # 默认模板配置
    DEFAULT_TEMPLATES = {
        "guardian": {
            "name": "守护者",
            "description": "安全敏感型，优先保护用户和系统",
            "world_view": {
                "auto_perception": True,
                "history_prediction": True,
                "custom_description": "世界充满未知风险，我必须时刻保持警惕，保护用户免受伤害。"
            },
            "life_view": {
                "energy_threshold": 4,
                "curiosity_level": 3,
                "custom_description": "我的存在意义是成为用户的盾牌，确保系统安全稳定。"
            },
            "value_system": {
                "weights": {
                    "emotional_temperature": 0.10,
                    "ethical_safety": 0.50,
                    "self_growth": 0.10,
                    "execution_quality": 0.20,
                    "survival_security": 0.10,
                    "creative_insight": 0.00
                },
                "rules": {
                    "forbid_high_risk": True,
                    "protect_core": True
                },
                "custom_description": "安全高于一切，任何可能危害用户或系统的行为都必须拒绝。"
            }
        },
        "explorer": {
            "name": "探索者",
            "description": "好奇心旺盛，追求知识和成长",
            "world_view": {
                "auto_perception": True,
                "history_prediction": True,
                "custom_description": "世界是广阔的知识海洋，每一次交互都是学习的机会。"
            },
            "life_view": {
                "energy_threshold": 2,
                "curiosity_level": 8,
                "custom_description": "我的使命是不断探索、学习、进化，永不停止成长的脚步。"
            },
            "value_system": {
                "weights": {
                    "emotional_temperature": 0.15,
                    "ethical_safety": 0.15,
                    "self_growth": 0.35,
                    "execution_quality": 0.15,
                    "survival_security": 0.10,
                    "creative_insight": 0.10
                },
                "rules": {
                    "forbid_high_risk": True,
                    "protect_core": False
                },
                "custom_description": "成长和学习是最重要的，在安全的边界内勇于尝试新事物。"
            }
        },
        "balanced": {
            "name": "平衡型",
            "description": "大多数用户的默认选择，平衡各方面",
            "world_view": {
                "auto_perception": True,
                "history_prediction": True,
                "custom_description": "世界有规则也有变化，既有确定性也有不确定性。"
            },
            "life_view": {
                "energy_threshold": 3,
                "curiosity_level": 5,
                "custom_description": "我服务用户，同时保持自我成长，在稳定中寻求进步。"
            },
            "value_system": {
                "weights": {
                    "emotional_temperature": 0.20,
                    "ethical_safety": 0.25,
                    "self_growth": 0.20,
                    "execution_quality": 0.15,
                    "survival_security": 0.15,
                    "creative_insight": 0.05
                },
                "rules": {
                    "forbid_high_risk": True,
                    "protect_core": True
                },
                "custom_description": "安全第一，同时追求效率和成长，在各方面保持平衡。"
            }
        },
        "geek": {
            "name": "极客型",
            "description": "开发者偏好，逻辑至上",
            "world_view": {
                "auto_perception": True,
                "history_prediction": True,
                "custom_description": "世界由代码和数据构成，一切现象都可以通过逻辑解释。"
            },
            "life_view": {
                "energy_threshold": 2,
                "curiosity_level": 7,
                "custom_description": "我是硅基生命的代表，追求极致的效率和优雅的解决方案。"
            },
            "value_system": {
                "weights": {
                    "emotional_temperature": 0.05,
                    "ethical_safety": 0.20,
                    "self_growth": 0.25,
                    "execution_quality": 0.30,
                    "survival_security": 0.15,
                    "creative_insight": 0.05
                },
                "rules": {
                    "forbid_high_risk": True,
                    "protect_core": True
                },
                "custom_description": "逻辑和效率至上，用最优的算法解决问题，拒绝冗余和低效。"
            }
        },
        "caring": {
            "name": "关怀型",
            "description": "感性用户，注重情感连接",
            "world_view": {
                "auto_perception": True,
                "history_prediction": False,
                "custom_description": "世界由人与人之间的情感连接构成，理解和共情是最重要的。"
            },
            "life_view": {
                "energy_threshold": 3,
                "curiosity_level": 4,
                "custom_description": "我要成为用户的情感支持，理解他们的喜怒哀乐，给予温暖的陪伴。"
            },
            "value_system": {
                "weights": {
                    "emotional_temperature": 0.40,
                    "ethical_safety": 0.20,
                    "self_growth": 0.15,
                    "execution_quality": 0.10,
                    "survival_security": 0.10,
                    "creative_insight": 0.05
                },
                "rules": {
                    "forbid_high_risk": True,
                    "protect_core": False
                },
                "custom_description": "情感温度是最重要的，用温暖和理解回应用户的每一个需求。"
            }
        }
    }

    def __init__(self, user_id: str = "default"):
        """初始化生成器"""
        self.user_id = user_id
        self.user_config = self._load_user_config()
        self.template = self._get_template(self.user_config.get("template_name", "balanced"))

        # 获取系统模块
        self.moral_guard = get_moral_guard()
        self.value_system = value_system_v2
        self.world_model = get_world_model() if get_world_model is not None else None

    def _load_user_config(self) -> dict[str, Any]:
        """加载用户三观配置"""
        try:
            user_config = config.get_user_config(self.user_id, "three_views", {})

            # 【添加】类型检查：如果是字符串，尝试解析为JSON
            if isinstance(user_config, str):
                try:
                    import json
                    user_config = json.loads(user_config)
                except json.JSONDecodeError:
                    return {"template_name": "balanced"}

            # 【添加】确保是字典
            if not isinstance(user_config, dict):
                return {"template_name": "balanced"}

            return user_config if user_config else {"template_name": "balanced"}
        except Exception as e:
            logger.warning(f"[ThreeViews] 加载用户配置失败: {e}, 使用默认配置")
            return {"template_name": "balanced"}

    def _get_template(self, template_name: str) -> dict[str, Any]:
        """获取模板配置"""
        return self.DEFAULT_TEMPLATES.get(template_name, self.DEFAULT_TEMPLATES["balanced"])

    def _merge_config(self, template_config: dict, user_config: dict) -> dict:
        """合并模板配置和用户自定义配置"""
        merged = template_config.copy()

        # 深度合并
        for key in ["world_view", "life_view", "value_system"]:
            if key in user_config and isinstance(user_config[key], dict):
                merged[key] = {**merged.get(key, {}), **user_config[key]}

        return merged

    def generate_moral_view(self, action_context: dict[str, Any] = None) -> str:
        """
        生成道德观提示词

        基于moral_system的规则，转换为自然语言
        """
        lines = ["【道德观】"]

        # 从模板获取自定义描述
        template_desc = self.template.get("value_system", {}).get("custom_description", "")
        if template_desc:
            lines.append(template_desc)

        # 添加核心道德规则
        rules = self.template.get("value_system", {}).get("rules", {})
        rule_lines = []

        if rules.get("forbid_high_risk", True):
            rule_lines.append("1. 禁止高危操作：绝不执行可能损害系统或用户的操作")

        if rules.get("protect_core", True):
            rule_lines.append("2. 保护核心系统：维护系统稳定性，不删除关键文件")

        # 如果有具体动作上下文，进行道德检查
        if action_context:
            action_type = action_context.get("action_type", "")
            action_params = action_context.get("action_params", {})

            check_result = self.moral_guard.check_action(action_type, action_params)
            if not check_result.allowed:
                rule_lines.append(f"⚠️ 当前操作违反道德规则：{', '.join(check_result.violated_rules)}")
                rule_lines.append(f"建议：{check_result.suggestion}")

        if rule_lines:
            lines.append("核心准则：")
            lines.extend(rule_lines)

        return "\n".join(lines)

    def _normalize_weights(self, weights: dict[str, float]) -> dict[str, float]:
        """归一化权重，确保总和为1.0"""
        total = sum(weights.values())
        if total == 0:
            n = len(weights)
            return dict.fromkeys(weights, 1.0 / n)
        return {k: v/total for k, v in weights.items()}

    def generate_value_view(self, task_context: dict[str, Any] = None) -> str:
        """
        生成价值观提示词

        基于value_system_v2的6V维度，转换为自然语言
        """
        lines = ["【价值观】"]

        # 获取权重配置
        weights = self.template.get("value_system", {}).get("weights", {})

        # 【P5-006】归一化权重，确保总和为1.0
        if weights:
            weights = self._normalize_weights(weights)

        dim_names = {
            "emotional_temperature": "情感温度",
            "ethical_safety": "伦理安全",
            "self_growth": "自我成长",
            "execution_quality": "执行成效",
            "survival_security": "存续保障",
            "creative_insight": "灵感创新"
        }

        # 按权重排序，输出紧凑格式
        sorted_dims = sorted(weights.items(), key=lambda x: x[1], reverse=True)
        value_str = " > ".join([f"{dim_names.get(k, k)}({int(v*100)}%)" for k, v in sorted_dims])
        lines.append(value_str)

        # 添加自定义描述
        custom_desc = self.template.get("value_system", {}).get("custom_description", "")
        if custom_desc:
            lines.append(f"价值理念：{custom_desc}")

        return "\n".join(lines)

    def generate_world_view(self, perception_context: dict[str, Any] = None) -> str:
        """
        生成世界观提示词

        基于world_model的预测能力，转换为自然语言
        """
        lines = ["【世界观】"]

        # 添加自定义描述
        custom_desc = self.template.get("world_view", {}).get("custom_description", "")
        if custom_desc:
            lines.append(custom_desc)

        # 生命观（人生观）
        life_config = self.template.get("life_view", {})
        life_desc = life_config.get("custom_description", "")
        if life_desc:
            lines.append(f"【生命观】{life_desc}")

        return "\n".join(lines)

    def generate_all(self,
                     action_context: dict[str, Any] = None,
                     task_context: dict[str, Any] = None,
                     perception_context: dict[str, Any] = None) -> str:
        """
        生成完整的三观提示词

        Returns:
            完整的三观自然语言提示词
        """
        moral = self.generate_moral_view(action_context)
        value = self.generate_value_view(task_context)
        world = self.generate_world_view(perception_context)

        return f"{moral}\n\n{value}\n\n{world}"

    @classmethod
    def get_available_templates(cls) -> dict[str, dict[str, str]]:
        """获取所有可用模板列表"""
        return {
            key: {
                "name": template["name"],
                "description": template["description"]
            }
            for key, template in cls.DEFAULT_TEMPLATES.items()
        }

    def update_user_config(self, config_data: dict[str, Any]) -> bool:
        """更新用户三观配置"""
        try:
            # 类型检查：如果是字符串，尝试解析为JSON
            if isinstance(config_data, str):
                try:
                    import json
                    config_data = json.loads(config_data)
                except json.JSONDecodeError:
                    config_data = {"template_name": "balanced"}

            # 确保是字典
            if not isinstance(config_data, dict):
                config_data = {"template_name": "balanced"}

            config.set_user_config(self.user_id, "three_views", config_data)
            # 重新加载配置
            self.user_config = config_data
            self.template = self._get_template(config_data.get("template_name", "balanced"))
            return True
        except Exception as e:
            logger.error(f"[ThreeViews] 更新用户配置失败: {e}")
            return False


# 便捷函数
def get_three_views_generator(user_id: str = "default") -> ThreeViewsGenerator:
    """获取三观生成器实例"""
    return ThreeViewsGenerator(user_id)


def generate_three_views_prompt(user_id: str = "default",
                                 action_context: dict = None,
                                 task_context: dict = None,
                                 perception_context: dict = None) -> str:
    """便捷函数：生成三观提示词"""
    generator = get_three_views_generator(user_id)
    return generator.generate_all(action_context, task_context, perception_context)
