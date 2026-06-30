#!/usr/bin/env python3
"""
Token预算管理器 - SiliconBase V5 Week 1 核心组件
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
功能：
  ✓ 全局Token预算管理（基于8大类别分配）
  ✓ 多模型Token计算（支持GPT/Claude等）
  ✓ 中文保护机制（高中文占比时预算增加）
  ✓ 智能内容截断（保留结构化标记）
  ✓ 零静默失败原则（所有异常明确报错）

类别分配：
  - 基础设定: 800 tokens（系统提示词+三观+生命体征）
  - 感知输入: 600 tokens（感知上下文+视觉分析）
  - 记忆经验: 1200 tokens（L1-L5+反思+经验+执行历史）
  - 认知辅助: 600 tokens（世界模型+探索+层级提示+推理框架）
  - 任务管理: 200 tokens（阶段锚点）
  - 个性化: 100 tokens（用户偏好）
  - 弱连接: 100 tokens（主动服务）
  - 预留: 400 tokens（用户输入+AI输出）
"""

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.logger import logger

# 尝试导入yaml
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    logger.warning("[TokenBudgetManager] PyYAML未安装，将使用默认配置")
    yaml = None  # type: ignore

# 导入现有TokenTracker
try:
    from core.utils.token_tracker import token_tracker
    TOKEN_TRACKER_AVAILABLE = True
except ImportError as e:
    TOKEN_TRACKER_AVAILABLE = False
    logger.error(f"[TokenBudgetManager] TokenTracker导入失败: {e}")
    token_tracker = None  # type: ignore


@dataclass
class TokenBudgetResult:
    """Token预算分配结果"""
    original_tokens: int
    budget: int
    truncated_tokens: int
    was_truncated: bool
    category: str
    model: str
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_tokens": self.original_tokens,
            "budget": self.budget,
            "truncated_tokens": self.truncated_tokens,
            "was_truncated": self.was_truncated,
            "category": self.category,
            "model": self.model,
            "timestamp": self.timestamp.isoformat()
        }


class TokenCalculator:
    """Token计算器（支持多模型和中文保护）

    职责：
    1. 基于现有TokenTracker计算Token数
    2. 应用模型系数调整
    3. 中文保护机制（高中文占比时增加预算）
    """

    # 模型Token系数（相对于GPT-4）
    MODEL_FACTORS = {
        "gpt-4": 1.0,
        "gpt-4-turbo": 1.0,
        "gpt-3.5-turbo": 1.0,
        "gpt-4o": 1.0,
        "gpt-4o-mini": 1.0,
        "claude-3-opus": 1.15,   # Claude通常多15%
        "claude-3-sonnet": 1.12,
        "claude-3-haiku": 1.10,
        "claude-3-5-sonnet": 1.12,
        "default": 1.0
    }

    # 中文保护配置
    CHINESE_PROTECTION = {
        "enabled": True,
        "ratio_threshold": 0.3,  # 中文占比阈值
        "budget_boost": 1.2       # 预算增加20%
    }

    def __init__(self):
        """初始化Token计算器"""
        self._stats = {
            "total_calculations": 0,
            "chinese_protection_triggered": 0,
            "estimation_fallbacks": 0
        }

    def count_tokens(self, text: str, model: str = "default") -> int:
        """计算Token数（支持多模型和中文保护）

        Args:
            text: 要计算的文本
            model: 模型名称（影响系数调整）

        Returns:
            调整后的Token数量

        错误处理:
        - text为None: ERROR日志，返回0
        - text为空字符串: 返回0
        - 编码失败: ERROR日志，使用估算
        """
        # 参数校验
        if text is None:
            logger.error("[TokenCalculator] text为None")
            return 0

        if not isinstance(text, str):
            try:
                text = str(text)
            except Exception as e:
                logger.error(f"[TokenCalculator] text转字符串失败: {e}")
                return 0

        if not text:
            return 0

        try:
            self._stats["total_calculations"] += 1

            # 使用现有TokenTracker
            if TOKEN_TRACKER_AVAILABLE and token_tracker is not None:
                try:
                    base_tokens = token_tracker.count_tokens(text, model)
                except Exception as e:
                    logger.error(f"[TokenCalculator] TokenTracker调用失败: {e}")
                    base_tokens = self._estimate_tokens(text)
                    self._stats["estimation_fallbacks"] += 1
            else:
                base_tokens = self._estimate_tokens(text)
                self._stats["estimation_fallbacks"] += 1

            # 模型系数调整
            factor = self.MODEL_FACTORS.get(model, 1.0)
            adjusted_tokens = int(base_tokens * factor)

            # 中文保护
            if self.CHINESE_PROTECTION["enabled"]:
                chinese_ratio = self._get_chinese_ratio(text)
                if chinese_ratio > self.CHINESE_PROTECTION["ratio_threshold"]:
                    adjusted_tokens = int(adjusted_tokens * self.CHINESE_PROTECTION["budget_boost"])
                    self._stats["chinese_protection_triggered"] += 1
                    logger.debug(f"[TokenCalculator] 中文保护触发(占比{chinese_ratio:.2%})，Token数增加20%")

            return adjusted_tokens

        except Exception as e:
            logger.error(f"[TokenCalculator] Token计算失败: {e}", exc_info=True)
            # 使用简单估算作为fallback
            estimated = len(text) // 4  # 粗略估算
            logger.warning(f"[TokenCalculator] 使用估算Token数: {estimated}")
            self._stats["estimation_fallbacks"] += 1
            return estimated

    def _get_chinese_ratio(self, text: str) -> float:
        """计算中文占比

        Args:
            text: 输入文本

        Returns:
            中文字符占比（0.0-1.0）
        """
        if not text:
            return 0.0

        try:
            chinese_chars = sum(1 for char in text if '\u4e00' <= char <= '\u9fff')
            return chinese_chars / len(text)
        except Exception as e:
            logger.error(f"[TokenCalculator] 中文占比计算失败: {e}")
            return 0.0

    def _estimate_tokens(self, text: str) -> int:
        """估算Token数量（fallback方法）

        使用字符数/4作为粗略估算（适用于英文）
        中文按字符数/2估算

        Args:
            text: 要估算的文本

        Returns:
            估算的Token数量
        """
        if not text:
            return 0

        total_chars = len(text)

        # 检测中文字符比例
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        chinese_ratio = chinese_chars / total_chars if total_chars > 0 else 0

        # 加权估算
        if chinese_ratio > 0.5:
            # 主要是中文
            return int(total_chars / 2)
        else:
            # 主要是英文
            return int(total_chars / 4)

    def get_model_factor(self, model: str) -> float:
        """获取模型系数

        Args:
            model: 模型名称

        Returns:
            该模型的Token系数
        """
        return self.MODEL_FACTORS.get(model, 1.0)

    def get_stats(self) -> dict[str, int]:
        """获取统计信息"""
        return self._stats.copy()


class TokenBudgetManager:
    """Token预算管理器（全局单例）

    职责：
    1. 加载和管理8大类别的Token预算配置
    2. 分配预算并智能截断内容
    3. 提供统计和监控功能

    使用示例：
        manager = TokenBudgetManager.get_instance()

        # 获取某类别的预算
        budget = manager.get_budget("记忆经验")

        # 分配预算（自动截断）
        result = manager.allocate_budget("记忆经验", long_content, model="gpt-4")
    """

    _instance = None
    _lock = False  # 简单锁标志

    # 【优化】默认预算配置（8大类别）- v3.0
    # 基于实际运行反馈：16项提示词组件被严重压缩，预算翻倍
    DEFAULT_BUDGETS = {
        "常驻基底": 10000,     # 【新增】常驻基底永不截断，给一个超大预算
        "基础设定": 4500,      # 【修复】system_prompt实际4300+，给足空间
        "感知输入": 1000,       # 【修复】vision精简后约150，perception可占800+
        "记忆经验": 2000,       # L1-L5+反思+经验+执行历史（4个组件共享）
        "认知辅助": 1600,       # 【修复】prompt_layer去重后释放约300
        "任务管理": 600,        # 【修复】实际只用200-300，大幅削减
        "个性化": 200,
        "弱连接": 200,
        "预留": 1200,           # 【修复】user_input + AI_output需要更多空间
    }
    # 总预算: 11300 tokens

    # 总预算（供参考）
    TOTAL_BUDGET = sum(DEFAULT_BUDGETS.values())  # 10200 tokens

    def __init__(self):
        """初始化Token预算管理器

        注意：请使用get_instance()获取单例，不要直接实例化
        """
        # 【修复】使用type(self)而不是硬编码类名，支持继承和导入变化
        if not type(self)._lock:
            raise RuntimeError("请使用TokenBudgetManager.get_instance()获取实例")

        self.config: dict[str, Any] = {}
        self.calculator = TokenCalculator()
        self._allocation: dict[str, int] = {}
        self._stats: dict[str, Any] = {
            "allocations": {},  # 每类别的分配统计
            "truncations": 0,   # 截断次数
            "errors": 0         # 错误次数
        }

        self._load_config()

    @classmethod
    def get_instance(cls) -> 'TokenBudgetManager':
        """获取TokenBudgetManager单例实例

        Returns:
            TokenBudgetManager单例
        """
        if cls._instance is None:
            cls._lock = True
            try:
                cls._instance = cls()
            finally:
                cls._lock = False
        return cls._instance

    def _load_config(self) -> None:
        """加载配置文件

        错误处理:
        - 配置文件不存在: WARNING日志，使用默认配置
        - 配置解析失败: ERROR日志，使用默认配置
        - YAML模块不可用: WARNING日志，使用默认配置
        """
        config_path = "config/information_delivery.yaml"

        try:
            if not YAML_AVAILABLE:
                logger.warning("[TokenBudgetManager] YAML模块不可用，使用默认配置")
                self._set_default_config()
                return

            if os.path.exists(config_path):
                try:
                    with open(config_path, encoding='utf-8') as f:
                        config = yaml.safe_load(f)

                    if config and isinstance(config, dict) and "information_delivery" in config:
                        self.config = config["information_delivery"]
                        loaded_budget = self.config.get("token_budget", {})

                        if loaded_budget and "allocation" in loaded_budget:
                            self._allocation = loaded_budget["allocation"]
                            logger.info(f"[TokenBudgetManager] 配置加载成功，已加载{len(self._allocation)}个类别")
                        else:
                            logger.warning("[TokenBudgetManager] 配置文件格式不正确，使用默认配置")
                            self._set_default_config()
                    else:
                        logger.warning("[TokenBudgetManager] 配置文件格式不正确，使用默认配置")
                        self._set_default_config()

                except yaml.YAMLError as e:
                    logger.error(f"[TokenBudgetManager] YAML解析失败: {e}，使用默认配置")
                    self._set_default_config()
                except OSError as e:
                    logger.error(f"[TokenBudgetManager] 配置文件读取失败: {e}，使用默认配置")
                    self._set_default_config()
            else:
                logger.warning(f"[TokenBudgetManager] 配置文件不存在: {config_path}，使用默认配置")
                self._set_default_config()

        except Exception as e:
            logger.error(f"[TokenBudgetManager] 配置加载失败: {e}，使用默认配置")
            self._set_default_config()

    def _set_default_config(self) -> None:
        """设置默认配置"""
        self.config = {"allocation": self.DEFAULT_BUDGETS.copy()}
        self._allocation = self.DEFAULT_BUDGETS.copy()
        logger.info(f"[TokenBudgetManager] 已使用默认配置，总预算: {self.TOTAL_BUDGET} tokens")

    def get_budget(self, category: str) -> int:
        """获取类别的Token预算

        Args:
            category: 类别名称（如"记忆经验"）

        Returns:
            该类别的Token预算

        错误处理:
        - 类别不存在: WARNING日志，返回默认500
        """
        if not isinstance(category, str):
            logger.error(f"[TokenBudgetManager] 类别名称类型错误: {type(category)}")
            return 500

        budget = self._allocation.get(category)
        if budget is None:
            logger.warning(f"[TokenBudgetManager] 未知类别: '{category}'，使用默认预算500")
            return 500

        return budget

    def get_all_budgets(self) -> dict[str, int]:
        """获取所有类别的预算

        Returns:
            类别到预算的映射字典
        """
        return self._allocation.copy()

    def allocate_budget(
        self,
        category: str,
        content: str,
        model: str = "default"
    ) -> TokenBudgetResult:
        """分配预算，智能截断

        Args:
            category: 内容类别
            content: 原始内容
            model: 模型名称（影响Token计算）

        Returns:
            TokenBudgetResult对象，包含原始/截断后的token数和截断状态

        错误处理:
        - content为None: ERROR日志，返回空结果
        - 截断失败: ERROR日志，返回原始内容
        """
        # 参数校验
        if content is None:
            logger.error(f"[TokenBudgetManager] content为None，类别: {category}")
            self._stats["errors"] += 1
            return TokenBudgetResult(
                original_tokens=0,
                budget=self.get_budget(category),
                truncated_tokens=0,
                was_truncated=False,
                category=category,
                model=model
            )

        if not isinstance(content, str):
            try:
                content = str(content)
            except Exception as e:
                logger.error(f"[TokenBudgetManager] content转字符串失败: {e}，类别: {category}")
                self._stats["errors"] += 1
                return TokenBudgetResult(
                    original_tokens=0,
                    budget=self.get_budget(category),
                    truncated_tokens=0,
                    was_truncated=False,
                    category=category,
                    model=model
                )

        if not content:
            return TokenBudgetResult(
                original_tokens=0,
                budget=self.get_budget(category),
                truncated_tokens=0,
                was_truncated=False,
                category=category,
                model=model
            )

        try:
            budget = self.get_budget(category)
            tokens = self.calculator.count_tokens(content, model)

            # 更新统计
            if category not in self._stats["allocations"]:
                self._stats["allocations"][category] = {
                    "count": 0,
                    "total_tokens": 0,
                    "truncations": 0
                }
            self._stats["allocations"][category]["count"] += 1
            self._stats["allocations"][category]["total_tokens"] += tokens

            if tokens <= budget:
                logger.debug(f"[TokenBudgetManager] {category}: {tokens} <= {budget}，无需截断")
                return TokenBudgetResult(
                    original_tokens=tokens,
                    budget=budget,
                    truncated_tokens=tokens,
                    was_truncated=False,
                    category=category,
                    model=model
                )

            # 需要截断
            logger.info(f"[TokenBudgetManager] {category}: {tokens} > {budget}，执行智能截断")
            truncated_content = self.smart_truncate(content, budget, model, category)

            # 验证截断结果
            if truncated_content is None:
                logger.error("[TokenBudgetManager] 截断结果为None，返回原始内容")
                return TokenBudgetResult(
                    original_tokens=tokens,
                    budget=budget,
                    truncated_tokens=tokens,
                    was_truncated=False,
                    category=category,
                    model=model
                )

            new_tokens = self.calculator.count_tokens(truncated_content, model)
            self._stats["truncations"] += 1
            self._stats["allocations"][category]["truncations"] += 1

            logger.info(f"[TokenBudgetManager] {category} 截断后: {new_tokens}/{budget} tokens")

            return TokenBudgetResult(
                original_tokens=tokens,
                budget=budget,
                truncated_tokens=new_tokens,
                was_truncated=True,
                category=category,
                model=model
            )

        except Exception as e:
            logger.error(f"[TokenBudgetManager] 预算分配失败: {e}，类别: {category}", exc_info=True)
            self._stats["errors"] += 1
            # 返回原始内容的估算结果
            estimated_tokens = self.calculator.count_tokens(content, model)
            return TokenBudgetResult(
                original_tokens=estimated_tokens,
                budget=self.get_budget(category),
                truncated_tokens=estimated_tokens,
                was_truncated=False,
                category=category,
                model=model
            )

    def smart_truncate(self, content: str, budget: int, model: str, category: str = "未知类别") -> str:
        """【优化 v3.0】语义压缩：按语义重要性保留关键信息，禁止物理删除中间行

        策略:
        1. 如果内容在预算范围内(<=1.1倍)，直接返回
        2. 所有超预算情况统一走抽取式语义摘要，不再物理截断中间行
        3. 【新增】常驻基底和压缩消息永不截断

        Args:
            content: 原始内容
            budget: Token预算
            model: 模型名称
            category: 内容类别（用于日志）

        Returns:
            截断后的内容
        """
        if not content:
            return ""

        # === 新增：白名单保护 ===
        if category == "常驻基底":
            return content

        try:
            # 步骤1: 估算当前token数
            total_tokens = self.calculator.count_tokens(content, model)

            # 步骤2: 如果内容接近预算，直接返回（允许10%误差）
            if total_tokens <= int(budget * 1.1):
                return content

            # 步骤3: 所有超预算情况统一走语义摘要（不再使用 _intelligent_line_truncate）
            return self._extractive_summary(content, budget, model, category)

        except Exception as e:
            logger.error(f"[TokenBudgetManager] 智能截断失败: {e}")
            # 简单截断作为fallback
            return content[:budget * 4] + "... [截断]"

    def _extractive_summary(self, content: str, budget: int, model: str, category: str = "未知类别") -> str:
        """【优化 v3.0】抽取式语义摘要：按语义优先级保留关键行，禁止物理删除中间行"""
        # === 新增：白名单保护 ===
        if category == "常驻基底":
            return content

        lines = content.split('\n')

        # 扩展的受保护关键词：覆盖所有工具名和关键格式标记
        _TOOL_PROTECTED_KEYWORDS = [
            # 工具名（必须完整保留，否则AI不知道有哪些工具可用）
            'launch_app', 'file_manager', 'web_search', 'pixel_capture',
            'vision_agent', 'visual_understand', 'keyboard_input', 'mouse_click',
            'click_text', 'screenshot', 'screen_ocr', 'window_focus', 'window_get',
            'system_info', 'read_file', 'find_file', 'clipboard_get', 'clipboard_set',
            'web_open', 'web_fetch', 'create_task', 'list_tasks', 'memory_add',
            'memory_search', 'memory_list', 'memory_update', 'memory_delete',
            'get_perception', 'get_tool_manual',
            # 格式关键词
            'JSON', '格式', '工具', '搜索', '坐标',
            'element', 'target', '点击', '鼠标',
            # 调用规范标记
            '"tool":', '"params":', 'tool_call',
        ]

        # 识别关键行和详情行
        key_lines = []
        detail_lines = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # 结构化标记行（如【标题】）→ 高优先级保留
            if stripped.startswith('【') and stripped.endswith('】'):
                key_lines.append((line, 'tag', 0))
            # 核心指令行 → 高优先级保留
            elif any(kw in stripped for kw in ['核心', '关键', '必须', '禁止', '重要']):
                key_lines.append((line, 'key', 1))
            # 工具调用规则/JSON格式/坐标/所有工具名 → 最高优先级保留，不可丢弃
            elif any(kw in stripped for kw in _TOOL_PROTECTED_KEYWORDS):
                key_lines.append((line, 'protected', -1))  # 优先级-1表示最高
            # 列表项（工具列表 mostly）→ 中等优先级，但给予充足预算
            elif stripped.startswith(('- ', '• ', '* ', '1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.')):
                key_lines.append((line, 'list', 2))
            # 其他 → 视为详情
            else:
                detail_lines.append(line)

        # 按优先级排序关键行（protected优先级-1排在最前）
        key_lines.sort(key=lambda x: x[2])

        # 分轮预算分配：protected/tag/key 60%，list 30%，摘要标记 10%
        result_lines = []
        current_tokens = 0
        budget_for_protected = int(budget * 0.6)   # protected / tag / key
        budget_for_list = int(budget * 0.3)        # list 项（工具列表）
        int(budget * 0.1)        # 摘要标记

        # 第一轮：保留 protected / tag / key（最高优先级内容）
        for line, line_type, _priority in key_lines:
            if line_type in ('protected', 'tag', 'key'):
                line_tokens = self.calculator.count_tokens(line, model)
                if current_tokens + line_tokens <= budget_for_protected:
                    result_lines.append(line)
                    current_tokens += line_tokens

        # 第二轮：保留 list 项（工具列表的行大多是 list 类型）
        for line, line_type, _priority in key_lines:
            if line_type == 'list':
                line_tokens = self.calculator.count_tokens(line, model)
                if current_tokens + line_tokens <= budget_for_protected + budget_for_list:
                    result_lines.append(line)
                    current_tokens += line_tokens

        # 第三轮：添加摘要标记（使用剩余预算，不超过10%配额）
        if detail_lines:
            summary_note = f"\n... [已语义摘要，省略{len(detail_lines)}行详情]"
            summary_tokens = self.calculator.count_tokens(summary_note, model)
            if current_tokens + summary_tokens <= budget:
                result_lines.append(summary_note)
                current_tokens += summary_tokens

        result = '\n'.join(result_lines) if result_lines else content[:budget * 4] + "... [截断]"
        # 告警：如果截断后内容不足原始30%，打印WARNING日志
        if len(result) < len(content) * 0.3:
            logger.warning(
                f"[TokenBudgetManager] {category} 截断后内容不足原始30% "
                f"({len(result)}/{len(content)} 字符)，关键规则可能已丢失"
            )
        return result

    def _intelligent_line_truncate(self, content: str, budget: int, model: str) -> str:
        """【新增】智能行截断：保留开头（高优先级）+ 结尾（最新信息）"""
        lines = content.split('\n')

        # 如果行数不多，使用传统截断
        if len(lines) <= 10:
            return self._traditional_truncate(content, budget, model)

        # 策略：保留前5行（高优先级）和后3行（最新信息）
        head_lines = lines[:5]
        tail_lines = lines[-3:] if len(lines) > 8 else []

        # 计算头尾token数
        head_text = '\n'.join(head_lines)
        tail_text = '\n'.join(tail_lines)
        head_tokens = self.calculator.count_tokens(head_text, model)
        tail_tokens = self.calculator.count_tokens(tail_text, model)

        # 如果头尾都超预算，退回到传统截断
        if head_tokens + tail_tokens > budget * 0.9:
            return self._traditional_truncate(content, budget, model)

        # 组装结果：开头 + [省略中间] + 结尾
        result = head_text
        omitted_count = len(lines) - len(head_lines) - len(tail_lines)
        if omitted_count > 0:
            middle_note = f"\n\n... [省略{omitted_count}行中间内容] ...\n\n"
            result += middle_note + tail_text

        return result

    def _traditional_truncate(self, content: str, budget: int, model: str) -> str:
        """【保留】传统行截断（作为fallback）"""
        lines = content.split('\n')
        result_lines = []
        current_tokens = 0

        for line in lines:
            if current_tokens >= budget:
                break

            line_tokens = self.calculator.count_tokens(line, model)

            # 结构化标记行（如【记忆上下文】）
            stripped = line.strip()
            if stripped.startswith('【') and stripped.endswith('】'):
                if current_tokens + line_tokens <= budget:
                    result_lines.append(line)
                    current_tokens += line_tokens
                continue

            # 普通内容行
            if current_tokens + line_tokens <= budget:
                result_lines.append(line)
                current_tokens += line_tokens
            else:
                # 尝试部分截断
                remaining_budget = budget - current_tokens
                if remaining_budget > 20:
                    partial = self._truncate_line(line, remaining_budget, model)
                    if partial:
                        result_lines.append(partial + "... [截断]")
                break

        result = '\n'.join(result_lines)
        return result if result else content[:budget * 4] + "... [截断]"

    def _truncate_line(self, line: str, budget: int, model: str) -> str:
        """截断单行内容

        Args:
            line: 要截断的行
            budget: Token预算
            model: 模型名称

        Returns:
            截断后的行
        """
        if not line:
            return ""

        try:
            chars = len(line)
            estimated_tokens = self.calculator.count_tokens(line, model)

            if estimated_tokens <= budget:
                return line

            # 估算字符数
            if estimated_tokens > 0:
                ratio = budget / estimated_tokens
                target_chars = int(chars * ratio)
            else:
                target_chars = budget * 2

            # 确保至少保留一些字符
            target_chars = max(target_chars, 10)
            return line[:target_chars]

        except Exception as e:
            logger.error(f"[TokenBudgetManager] 单行截断失败: {e}")
            return line[:budget * 2] if len(line) > budget * 2 else line

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        return {
            "calculator_stats": self.calculator.get_stats(),
            "manager_stats": self._stats.copy(),
            "total_budget": self.TOTAL_BUDGET,
            "current_allocation": self._allocation.copy()
        }

    def reset_stats(self) -> None:
        """重置统计信息"""
        self._stats = {
            "allocations": {},
            "truncations": 0,
            "errors": 0
        }
        logger.info("[TokenBudgetManager] 统计信息已重置")


# =============================================================================
# 便捷函数
# =============================================================================

def get_token_budget_manager() -> TokenBudgetManager:
    """获取TokenBudgetManager实例的便捷函数

    Returns:
        TokenBudgetManager单例
    """
    return TokenBudgetManager.get_instance()


def allocate_category_budget(
    category: str,
    content: str,
    model: str = "default"
) -> TokenBudgetResult:
    """便捷函数：为指定类别分配预算

    Args:
        category: 内容类别
        content: 原始内容
        model: 模型名称

    Returns:
        TokenBudgetResult对象
    """
    manager = TokenBudgetManager.get_instance()
    return manager.allocate_budget(category, content, model)


def count_tokens(text: str, model: str = "default") -> int:
    """便捷函数：计算Token数

    Args:
        text: 要计算的文本
        model: 模型名称

    Returns:
        Token数量
    """
    calculator = TokenCalculator()
    return calculator.count_tokens(text, model)


# =============================================================================
# 测试代码
# =============================================================================
if __name__ == "__main__":
    # 简单测试
    print("=" * 60)
    print("TokenBudgetManager 测试")
    print("=" * 60)

    # 获取管理器实例
    manager = TokenBudgetManager.get_instance()

    # 测试获取预算
    print("\n1. 测试获取各类别预算:")
    for category in manager.DEFAULT_BUDGETS:
        budget = manager.get_budget(category)
        print(f"   {category}: {budget} tokens")

    # 测试Token计算
    print("\n2. 测试Token计算:")
    test_texts = [
        "Hello, world!",
        "你好，世界！这是一个中文测试。",
        "Mixed content: 中英文混合内容 testing 123"
    ]
    calculator = TokenCalculator()
    for text in test_texts:
        tokens = calculator.count_tokens(text)
        chinese_ratio = calculator._get_chinese_ratio(text)
        print(f"   '{text[:30]}...' -> {tokens} tokens (中文占比: {chinese_ratio:.1%})")

    # 测试预算分配
    print("\n3. 测试预算分配（需要截断）:")
    long_content = "【记忆上下文】\n" + "这是一条测试记忆。\n" * 100
    result = manager.allocate_budget("记忆经验", long_content, model="gpt-4")
    print(f"   原始Token: {result.original_tokens}")
    print(f"   预算: {result.budget}")
    print(f"   截断后Token: {result.truncated_tokens}")
    print(f"   是否截断: {result.was_truncated}")

    # 测试中文保护
    print("\n4. 测试中文保护机制:")
    chinese_text = "这是一段纯中文文本，用于测试中文保护机制是否正常工作。" * 10
    tokens_normal = calculator.count_tokens(chinese_text, model="gpt-4")
    print(f"   中文文本Token数: {tokens_normal}")

    # 显示统计
    print("\n5. 统计信息:")
    stats = manager.get_stats()
    print(f"   总预算: {stats['total_budget']} tokens")
    print(f"   截断次数: {stats['manager_stats']['truncations']}")
    print(f"   错误次数: {stats['manager_stats']['errors']}")

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
