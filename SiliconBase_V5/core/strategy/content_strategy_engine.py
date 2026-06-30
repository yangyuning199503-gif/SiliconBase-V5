#!/usr/bin/env python3
"""
ContentStrategyEngine — 内容策略引擎
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
职责：决定布道师 AI "说什么、什么时候说、对谁说"。

约束：
  - 全 async，禁止同步阻塞
  - 初期规则引擎（硬编码时段表、关键词匹配），保留接口方便后续接 LLM
  - 异常内部捕获并记录，不向上抛出
"""

from datetime import datetime
from typing import Any

from core.logger import logger


class ContentStrategyEngine:
    """
    内容策略引擎 —— 规则驱动，可插拔 LLM 升级。
    """

    # ── 话术风格规则表 ─────────────────────────────────────────────────────────
    TONE_RULES: list[dict[str, Any]] = [
        {"keywords": ["暴跌", "崩盘", "rug", "骗局", "诈骗", "警惕"], "tone": "激进", "priority": 10},
        {"keywords": ["稳健", "长线", "定投", "配置", "diversify", "保守"], "tone": "稳健", "priority": 8},
        {"keywords": ["哈哈", "搞笑", "meme", "乐子", "笑死", "娱乐"], "tone": "幽默", "priority": 7},
        {"keywords": ["教程", "怎么", "如何", "什么是", "科普", "解析"], "tone": "专业", "priority": 6},
    ]

    # ── 平台活跃时段表（UTC+8）──────────────────────────────────────────────────
    PLATFORM_PEAK_HOURS: dict[str, list[int]] = {
        "discord": [12, 13, 19, 20, 21, 22],
        "telegram": [8, 9, 12, 13, 18, 19, 20, 21],
        "twitter": [8, 9, 12, 13, 18, 19, 20, 21, 22],
        "wechat": [7, 8, 12, 13, 18, 19, 20, 21],
    }

    # ── 平台内容适配规则 ───────────────────────────────────────────────────────
    PLATFORM_ADAPTERS: dict[str, dict[str, Any]] = {
        "discord": {
            "max_length": 2000,
            "emoji_boost": True,
            "markdown_style": "bold_asterisk",
        },
        "telegram": {
            "max_length": 4096,
            "emoji_boost": False,
            "markdown_style": "native",
        },
        "twitter": {
            "max_length": 280,
            "emoji_boost": True,
            "markdown_style": "none",
        },
        "wechat": {
            "max_length": 2000,
            "emoji_boost": False,
            "markdown_style": "none",
        },
    }

    # ── 质量门禁规则 ───────────────────────────────────────────────────────────
    QUALITY_RULES = {
        "min_length": 5,
        "max_length": 4000,
        "blocked_keywords": ["内部消息", "保证收益", "稳赚不赔", "官方合作未公布"],
    }

    def __init__(self, llm_adapter: Any | None = None) -> None:
        """
        Args:
            llm_adapter: 可选的 LLM 适配器，预留升级接口
        """
        self.llm_adapter = llm_adapter

    # ═════════════════════════════════════════════════════════════════════════════
    # 公开 API
    # ═════════════════════════════════════════════════════════════════════════════

    async def select_tone(self, topic: str, audience: str) -> str:
        """
        根据话题与受众选择话术风格。

        Returns:
            str: "激进" | "稳健" | "幽默" | "专业"
        """
        if self.llm_adapter is not None:
            return await self._llm_select_tone(topic, audience)

        topic_lower = topic.lower()
        matched: list[dict[str, Any]] = []
        for rule in self.TONE_RULES:
            if any(kw in topic_lower for kw in rule["keywords"]):
                matched.append(rule)

        if not matched:
            # 按 audience 兜底
            if "专家" in audience or "开发者" in audience:
                return "专业"
            if "新手" in audience or "散户" in audience:
                return "稳健"
            return "稳健"

        matched.sort(key=lambda r: r["priority"], reverse=True)
        return matched[0]["tone"]

    async def decide_timing(self, platform: str, content_type: str = "general") -> str:
        """
        返回最佳发布时间建议。

        Returns:
            str: 人类可读的时间建议
        """
        now = datetime.now()
        current_hour = now.hour
        peak_hours = self.PLATFORM_PEAK_HOURS.get(platform.lower(), [])

        if peak_hours and current_hour in peak_hours:
            return f"当前 {current_hour}:00 正处于 {platform} 活跃高峰，建议立即发布"

        # 找下一个高峰
        next_peak: int | None = None
        for h in range(24):
            check_hour = (current_hour + h) % 24
            if check_hour in peak_hours:
                next_peak = check_hour
                break

        if next_peak is not None:
            return f"建议 {next_peak}:00 发布（{platform} 活跃时段）"

        return "建议在工作日晚间 19:00-22:00 发布"

    async def should_distribute(self, content: str, platform: str) -> bool:
        """
        质量门禁：判断内容是否适合分发到目标平台。

        Returns:
            bool: True 表示通过门禁
        """
        if not content or not isinstance(content, str):
            logger.warning("[ContentStrategy] 质量门禁失败：内容为空或类型错误")
            return False

        rules = self.QUALITY_RULES
        if len(content) < rules["min_length"]:
            logger.warning(
                f"[ContentStrategy] 质量门禁失败：内容长度 {len(content)} < {rules['min_length']}"
            )
            return False

        if len(content) > rules["max_length"]:
            logger.warning(
                f"[ContentStrategy] 质量门禁失败：内容长度 {len(content)} > {rules['max_length']}"
            )
            return False

        content_lower = content.lower()
        for blocked in rules["blocked_keywords"]:
            if blocked in content_lower:
                logger.warning(f"[ContentStrategy] 质量门禁失败：命中敏感词 '{blocked}'")
                return False

        # 平台特定长度检查
        adapter = self.PLATFORM_ADAPTERS.get(platform.lower())
        if adapter and len(content) > adapter["max_length"]:
            logger.warning(
                f"[ContentStrategy] 质量门禁失败：内容长度 {len(content)} 超过 {platform} 上限 {adapter['max_length']}"
            )
            return False

        return True

    async def adapt_message(self, content: str, platform: str) -> str:
        """
        平台适配：根据目标平台调整文本格式。

        Returns:
            str: 适配后的文本
        """
        platform_lower = platform.lower()
        adapter = self.PLATFORM_ADAPTERS.get(platform_lower, {})

        if not adapter:
            return content

        adapted = content

        # Discord：加 emoji 增强
        if platform_lower == "discord" and adapter.get("emoji_boost"):
            adapted = self._add_discord_emojis(adapted)

        # Telegram：加原生 Markdown
        if platform_lower == "telegram" and adapter.get("markdown_style") == "native":
            adapted = self._add_telegram_markdown(adapted)

        # Twitter：截断
        if platform_lower == "twitter":
            adapted = self._truncate_for_twitter(adapted, adapter.get("max_length", 280))

        # 通用长度截断
        max_len = adapter.get("max_length")
        if max_len and len(adapted) > max_len:
            adapted = adapted[: max_len - 3] + "..."

        return adapted

    # ═════════════════════════════════════════════════════════════════════════════
    # 内部规则实现
    # ═════════════════════════════════════════════════════════════════════════════

    def _add_discord_emojis(self, text: str) -> str:
        """为 Discord 添加相关 emoji（每类关键词仅替换一次）"""
        emoji_map = {
            "涨": "📈",
            "跌": "📉",
            "警告": "⚠️",
            "注意": "👉",
            "成功": "✅",
            "失败": "❌",
            "重要": "🔴",
            "提示": "💡",
            "新闻": "📰",
        }
        result = text
        for word, emoji in emoji_map.items():
            if word in result:
                result = result.replace(word, f"{emoji} {word}", 1)
        return result

    def _add_telegram_markdown(self, text: str) -> str:
        """为 Telegram 添加 Markdown 粗体格式"""
        lines = text.split("\n")
        new_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(("注意", "重要", "提示")):
                new_lines.append(f"*{stripped}*")
            else:
                new_lines.append(line)
        return "\n".join(new_lines)

    def _truncate_for_twitter(self, text: str, max_len: int = 280) -> str:
        """为 Twitter 截断文本"""
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."

    async def _llm_select_tone(self, topic: str, audience: str) -> str:
        """LLM 适配接口（占位，后续接入 LLM）"""
        logger.info("[ContentStrategy] LLM 话术选择（占位）")
        return "专业"
