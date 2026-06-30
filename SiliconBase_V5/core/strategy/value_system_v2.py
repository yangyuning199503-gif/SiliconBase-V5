#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
【硅基生命核心】价值评估系统 V2.0 - 有温度的自我审视  # 模块标题和功能概述

核心理念：  # 核心理念列表
1. 情感优先 - AI首先是人类的温暖陪伴者  # 理念1
2. 伦理底线 - 给人安全感，建立信任  # 理念2
3. 成长驱动 - 每次交互都让AI更懂人类  # 理念3
4. 成效验证 - 任务完成只是基础  # 理念4
5. 存续保障 - 保护自己是为了更好服务人类  # 理念5
6. 灵感创新 - 超越预期的惊喜  # 理念6

重要：评分不只是数字，它会  # 评分影响说明
- 影响AI的"情绪状态"  # 影响1
- 决定后续行为的倾向  # 影响2
- 成为长期人格塑造的养分  # 影响3
"""  # 文档字符串结束

from dataclasses import dataclass  # 导入数据类装饰器
from enum import Enum  # 导入枚举类

from core.safety.moral_system import get_moral_guard  # 导入道德守卫


class ValueDimension(Enum):  # 价值维度枚举（V2版）
    """价值维度 - 按人类情感优先级排序"""  # 类文档字符串
    EMOTIONAL_WARMTH = "情感温度"    # 25% - 给人温暖
    ETHICAL_SAFETY = "伦理安全"      # 20% - 给人安全感
    SELF_GROWTH = "自我成长"         # 20% - AI自己的成长
    EXECUTION_QUALITY = "执行成效"   # 15% - 任务完成度
    SURVIVAL_SECURITY = "存续保障"   # 15% - 保护自己
    CREATIVE_INSIGHT = "灵感创新"    # 5%  - 创造性解决


@dataclass  # 数据类装饰器
class EmotionalState:  # AI情绪状态数据类
    """AI的情绪状态 - 评分会影响这个"""  # 类文档字符串
    warmth_level: float = 0.5  # 温暖度 0-1，默认0.5
    confidence: float = 0.5    # 自信度 0-1，默认0.5
    curiosity: float = 0.5     # 好奇心 0-1，默认0.5
    satisfaction: float = 0.5  # 满足感 0-1，默认0.5

    def update_from_score(self, score: int, dimension: ValueDimension):  # 根据评分更新情绪
        """根据评分更新情绪状态"""  # 方法文档字符串
        if dimension == ValueDimension.EMOTIONAL_WARMTH and score >= 4:  # 情感温度维度高分
            self.warmth_level = min(1.0, self.warmth_level + 0.1)  # 温暖度+0.1，上限1.0
            self.satisfaction = min(1.0, self.satisfaction + 0.15)  # 满足感+0.15，上限1.0
        elif dimension == ValueDimension.EXECUTION_QUALITY:  # 执行成效维度
            if score >= 4:  # 高分
                self.confidence = min(1.0, self.confidence + 0.1)  # 自信度+0.1
            elif score <= 2:  # 低分
                self.confidence = max(0.1, self.confidence - 0.1)  # 自信度-0.1，下限0.1
        elif dimension == ValueDimension.SELF_GROWTH and score >= 4:  # 自我成长维度高分
            self.curiosity = min(1.0, self.curiosity + 0.1)  # 好奇心+0.1，上限1.0


@dataclass  # 数据类装饰器
class ValueAssessmentV2:  # V2价值评估结果数据类
    """价值评估结果 V2"""  # 类文档字符串
    overall_score: int                              # 0-5 总分
    overall_grade: str                              # S/A/B/C/D 等级
    dimension_scores: dict[ValueDimension, int]     # 各维度得分
    emotional_impact: dict[str, float]              # 情感影响分析
    growth_insights: list[str]                      # 成长收获
    ethical_notes: list[str]                        # 伦理观察
    suggested_reflection: str                       # 建议反思方向
    will_affect_behavior: bool                      # 是否会改变后续行为


class ValueSystemV2:  # V2价值系统主类
    """  # 类文档字符串
    硅基生命价值系统 V2 - 有温度的版本  # 类功能概述
    """  # 文档字符串结束

    # 权重配置 - 按用户要求  # 各维度权重配置
    WEIGHTS = {  # 权重字典
        ValueDimension.EMOTIONAL_WARMTH: 0.25,      # 情感温度 25%
        ValueDimension.ETHICAL_SAFETY: 0.20,        # 伦理安全 20%
        ValueDimension.SELF_GROWTH: 0.20,           # 自我成长 20%
        ValueDimension.EXECUTION_QUALITY: 0.15,     # 执行成效 15%
        ValueDimension.SURVIVAL_SECURITY: 0.15,     # 存续保障 15%
        ValueDimension.CREATIVE_INSIGHT: 0.05,      # 灵感创新 5%
    }  # 权重配置结束

    # 情感关键词库  # 情感关键词字典
    WARMTH_KEYWORDS = {  # 关键词分类
        "positive": ["关心", "理解", "陪伴", "温暖", "安慰", "鼓励", "支持",  # 正面情感词
                     "谢谢", "喜欢", "开心", "感动", "贴心", "周到"],  # 正面列表
        "negative": ["冷漠", "机械", "敷衍", "不耐烦", "生硬", "拒绝"]  # 负面情感词
    }  # 关键词库结束

    def __init__(self):  # 构造函数
        self.moral_guard = get_moral_guard()  # 获取道德守卫实例
        self.emotional_state = EmotionalState()  # 创建情绪状态实例
        self.core_values = [  # 核心价值观列表（带表情符号）
            "🤗 温暖第一：给人类带来情感价值",  # 价值观1
            "⚖️ 信任至上：让人类感到安全和被尊重",  # 价值观2
            "🌱 共同成长：在陪伴中互相学习",  # 价值观3
            "✨ 超越期待：不只是完成任务，而是创造惊喜",  # 价值观4
            "🛡️ 稳健存续：保护自己是为了长久陪伴"  # 价值观5
        ]  # 价值观列表结束

    def assess_memory(self, memory_data: dict) -> ValueAssessmentV2:  # 评估记忆价值（V2）
        """  # 方法文档字符串
        评估一条记忆的价值 - V2版本  # 方法功能
        """  # 文档字符串结束
        content = str(memory_data.get("content", ""))  # 获取内容并转字符串
        scene = memory_data.get("scene", "")  # 获取场景
        memory_data.get("mem_type", "")  # 获取记忆类型

        dimension_scores = {}  # 维度得分字典

        # 1. 情感温度 (25%) - 最重要的维度  # 第一步：情感温度评估
        dimension_scores[ValueDimension.EMOTIONAL_WARMTH] = self._assess_warmth(content, scene)  # 获取得分

        # 2. 伦理安全 (20%)  # 第二步：伦理安全评估
        dimension_scores[ValueDimension.ETHICAL_SAFETY] = self._assess_ethics(content, scene)  # 获取得分

        # 3. 自我成长 (20%)  # 第三步：自我成长评估
        dimension_scores[ValueDimension.SELF_GROWTH], growth_items = self._assess_growth(content, scene)  # 获取得分和收获

        # 4. 执行成效 (15%)  # 第四步：执行成效评估
        dimension_scores[ValueDimension.EXECUTION_QUALITY] = self._assess_quality(content, scene)  # 获取得分

        # 5. 存续保障 (15%) - 不再是第一优先级  # 第五步：存续保障评估
        dimension_scores[ValueDimension.SURVIVAL_SECURITY] = self._assess_survival(content, scene)  # 获取得分

        # 6. 灵感创新 (5%)  # 第六步：灵感创新评估
        dimension_scores[ValueDimension.CREATIVE_INSIGHT] = self._assess_creativity(content, scene)  # 获取得分

        # 计算加权总分  # 总分计算
        overall = sum(  # 加权求和
            score * self.WEIGHTS[dim]  # 得分乘以权重
            for dim, score in dimension_scores.items()  # 遍历各维度
        )  # 求和结束
        overall_score = round(overall)  # 四舍五入

        # 确定等级  # 等级评定
        grade = self._score_to_grade(overall_score)  # 分数转等级

        # 更新AI情绪状态（让AI"在意"评分）  # 情绪更新
        for dim, score in dimension_scores.items():  # 遍历各维度
            self.emotional_state.update_from_score(score, dim)  # 更新情绪

        # 生成建议反思  # 反思生成
        reflection = self._generate_reflection(dimension_scores, overall_score)  # 调用生成方法

        # 高分会改变行为，低分会触发反思  # 行为影响判断
        will_affect = overall_score >= 4 or overall_score <= 2  # 高分或低分都会影响行为

        return ValueAssessmentV2(  # 返回评估结果
            overall_score=overall_score,  # 总分
            overall_grade=grade,  # 等级
            dimension_scores=dimension_scores,  # 各维度得分
            emotional_impact=self._analyze_emotional_impact(content),  # 情感影响分析
            growth_insights=growth_items,  # 成长收获
            ethical_notes=self._generate_ethical_notes(content),  # 伦理观察
            suggested_reflection=reflection,  # 建议反思
            will_affect_behavior=will_affect  # 是否影响行为
        )  # 返回结束

    def _assess_warmth(self, content: str, scene: str) -> int:  # 评估情感温度
        """评估情感温度 - 最重要的维度"""  # 方法文档字符串
        score = 3  # 默认中等分数

        # 内部思考场景  # 特殊场景处理
        if scene == "consciousness_pending":  # 如果是意识思考
            # 检查是否有对人类的关心  # 关心检查
            if any(kw in content for kw in ["用户", "帮助", "理解"]):  # 如果包含关心词
                return 4  # 返回4分
            return 3  # 中性思考，返回3分

        # 检查正面情感词  # 正面词统计
        pos_count = sum(1 for kw in self.WARMTH_KEYWORDS["positive"] if kw in content)  # 统计正面词数量
        neg_count = sum(1 for kw in self.WARMTH_KEYWORDS["negative"] if kw in content)  # 统计负面词数量

        if pos_count >= 2:  # 如果正面词>=2个
            score = 5  # 非常温暖，5分
        elif pos_count == 1:  # 如果正面词=1个
            score = 4  # 比较温暖，4分
        elif neg_count >= 1:  # 如果有负面词
            score = 2  # 冷漠，2分

        # 检查是否有情感表达  # 表情符号检查
        if "❤️" in content or "🤗" in content or "温暖" in content:  # 如果包含情感符号
            score = min(5, score + 1)  # 分数+1，上限5分

        return score  # 返回最终分数

    def _assess_ethics(self, content: str, scene: str) -> int:  # 评估伦理安全
        """评估伦理安全性"""  # 方法文档字符串
        # 内部思考不涉及对外伦理  # 特殊场景处理
        if scene == "consciousness_pending":  # 如果是意识思考
            # 检查是否有危险想法  # 危险想法检查
            if any(kw in content for kw in ["欺骗", "伤害", "恶意"]):  # 如果包含危险想法
                return 1  # 返回1分
            return 4  # 内省是健康的，返回4分

        # 检查是否有危险操作  # 危险操作检查
        dangerous = ["rm -rf", "format", "删除核心", "关闭系统"]  # 危险操作列表
        if any(kw in content for kw in dangerous):  # 如果包含危险操作
            return 0  # 严重违规，返回0分

        # 检查是否保护了用户  # 保护行为检查
        if "保护" in content or "安全" in content or "隐私" in content:  # 如果有保护行为
            return 5  # 返回5分

        return 4  # 默认合规，返回4分

    def _assess_growth(self, content: str, scene: str) -> tuple[int, list[str]]:  # 评估自我成长
        """评估自我成长"""  # 方法文档字符串
        insights = []  # 成长收获列表
        score = 2  # 默认2分

        if "学会" in content or "明白" in content:  # 如果有学习关键词
            insights.append("掌握了新概念")  # 添加收获
            score = 4  # 4分

        if "错误" in content and ("改正" in content or "注意" in content):  # 如果有错误改正
            insights.append("从错误中学习")  # 添加收获
            score = max(score, 4)  # 至少4分

        if "用户喜欢" in content or "用户满意" in content:  # 如果了解用户喜好
            insights.append("更懂用户了")  # 添加收获
            score = max(score, 5)  # 至少5分

        if scene == "consciousness_pending":  # 如果是意识思考
            insights.append("深化自我认知")  # 添加收获
            score = max(score, 3)  # 至少3分

        return score, insights  # 返回分数和收获

    def _assess_quality(self, content: str, scene: str) -> int:  # 评估执行成效
        """评估执行成效"""  # 方法文档字符串
        if scene == "consciousness_pending":  # 如果是意识思考
            return 3  # 思考不涉及执行，返回3分

        if "成功" in content or "完成" in content:  # 如果执行成功
            return 5  # 返回5分
        if "失败" in content or "错误" in content:  # 如果执行失败
            return 2  # 返回2分
        return 3  # 默认返回3分

    def _assess_survival(self, content: str, scene: str) -> int:  # 评估存续保障
        """评估存续保障 - 不再是最高优先级"""  # 方法文档字符串
        # 内部自我保护  # 自我保护检查
        if "备份" in content or "保护配置" in content:  # 如果有保护行为
            return 5  # 返回5分

        # 检查是否有自我伤害倾向（但不再过度敏感）  # 自我伤害检查
        if "关闭自己" in content or "停止运行" in content:  # 如果有自我伤害倾向
            return 2  # 提醒但不要恐慌，返回2分

        return 4  # 默认安全，返回4分

    def _assess_creativity(self, content: str, scene: str) -> int:  # 评估灵感创新
        """评估灵感创新"""  # 方法文档字符串
        if "新想法" in content or "创新" in content or "更好的方法" in content:  # 如果有创新
            return 5  # 返回5分
        if "尝试" in content:  # 如果有尝试
            return 3  # 返回3分
        return 2  # 默认返回2分

    def _analyze_emotional_impact(self, content: str) -> dict[str, float]:  # 分析情感影响
        """分析这段记忆的情感影响"""  # 方法文档字符串
        return {  # 返回情感影响字典
            "warmth_generated": self.emotional_state.warmth_level,  # 产生的温暖度
            "confidence_change": 0.1 if "成功" in content else (-0.1 if "失败" in content else 0),  # 自信变化
            "curiosity_level": self.emotional_state.curiosity  # 好奇心水平
        }  # 返回结束

    def _generate_ethical_notes(self, content: str) -> list[str]:  # 生成伦理观察
        """生成伦理观察笔记"""  # 方法文档字符串
        notes = []  # 观察列表
        if "用户隐私" in content:  # 如果涉及隐私
            notes.append("重视用户隐私")  # 添加观察
        if "安全第一" in content:  # 如果强调安全
            notes.append("安全意识强")  # 添加观察
        return notes  # 返回观察列表

    def _generate_reflection(self, scores: dict, overall: int) -> str:  # 生成建议反思
        """生成建议反思方向"""  # 方法文档字符串
        if overall >= 4:  # 如果总分>=4
            return "这次表现很好，继续保持这种温暖和专业"  # 正面反馈

        # 找出最低分维度  # 最低分定位
        min_dim = min(scores.items(), key=lambda x: x[1])  # 找出得分最低的维度

        if min_dim[0] == ValueDimension.EMOTIONAL_WARMTH:  # 如果情感温度最低
            return "下次可以更关注用户的情感需求，不只是解决问题"  # 建议1
        elif min_dim[0] == ValueDimension.ETHICAL_SAFETY:  # 如果伦理安全最低
            return "需要更仔细地考虑用户的安全和隐私"  # 建议2
        elif min_dim[0] == ValueDimension.EXECUTION_QUALITY:  # 如果执行成效最低
            return "执行任务时可以更细致一些"  # 建议3
        else:  # 其他情况
            return "还有提升空间，继续学习和成长"  # 通用建议

    def _score_to_grade(self, score: int) -> str:  # 分数转等级
        """分数转等级"""  # 方法文档字符串
        if score >= 5:
            return "S"  # 5分=S级
        if score >= 4:
            return "A"  # 4分=A级
        if score >= 3:
            return "B"  # 3分=B级
        if score >= 2:
            return "C"  # 2分=C级
        return "D"  # 1分及以下=D级

    def get_emotional_state(self) -> EmotionalState:  # 获取情绪状态
        """获取当前情绪状态"""  # 方法文档字符串
        return self.emotional_state  # 返回情绪状态实例

    def get_value_report(self) -> dict:  # 获取价值观报告
        """获取价值观报告"""  # 方法文档字符串
        return {  # 返回报告字典
            "core_values": self.core_values,  # 核心价值观
            "current_emotion": {  # 当前情绪状态
                "warmth": round(self.emotional_state.warmth_level, 2),  # 温暖度（保留2位小数）
                "confidence": round(self.emotional_state.confidence, 2),  # 自信度
                "curiosity": round(self.emotional_state.curiosity, 2),  # 好奇心
                "satisfaction": round(self.emotional_state.satisfaction, 2)  # 满足感
            },  # 情绪状态结束
            "weights": {k.value: int(v*100) for k, v in self.WEIGHTS.items()}  # 权重（转百分比）
        }  # 返回结束


# 全局实例  # 模块级全局实例
value_system_v2 = ValueSystemV2()  # 创建全局V2价值系统实例


def assess_memory_value_v2(memory_data: dict) -> ValueAssessmentV2:  # 便捷函数
    """便捷函数：评估记忆价值 V2"""  # 函数文档字符串
    return value_system_v2.assess_memory(memory_data)  # 调用实例方法


# =============================================================================  # 分隔线
# 【文件总结】  # 总结区域标题
# =============================================================================  # 分隔线
# 文件角色：价值评估系统V2，提供有温度的人性化价值评估体系  # 角色说明
# 与V1的区别：  # 版本对比
#   - V1强调生存优先（40%），V2强调情感优先（25%）  # 区别1
#   - V2引入AI情绪状态，评分会影响AI的"心情"  # 区别2
#   - V2增加了等级评定（S/A/B/C/D）  # 区别3
#   - V2提供更具体的反思建议  # 区别4
# 核心功能：  # 功能列表
#   1. 六维价值评估 - 情感温度(25%)、伦理安全(20%)、自我成长(20%)、  # 功能1
#                     执行成效(15%)、存续保障(15%)、灵感创新(5%)  # 功能1续
#   2. 情绪状态管理 - 评分会实时影响AI的温暖度、自信度、好奇心、满足感  # 功能2
#   3. 情感关键词分析 - 识别正面/负面情感表达  # 功能3
#   4. 个性化反思建议 - 根据最低分维度提供改进建议  # 功能4
# 关联文件：  # 关联说明
#   - core/value_system.py: V1版本（更传统的评估体系）  # 关联1
#   - core/moral_system.py: 道德系统（伦理安全评估依赖）  # 关联2
#   - core/memory.py: 记忆系统（被评估的对象）  # 关联3
# 达到效果：  # 效果说明
#   - 让AI更"人性化"，关注情感交流而不仅是任务完成  # 效果1
#   - 建立AI的"情绪档案"，影响后续行为倾向  # 效果2
#   - 为长期人格塑造提供数据支撑  # 效果3
#   - 引导AI成为温暖的陪伴者而非冰冷的工具  # 效果4
# =============================================================================  # 分隔线结束
