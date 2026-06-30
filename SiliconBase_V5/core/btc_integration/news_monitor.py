#!/usr/bin/env python3
"""
消息监控器 (NewsMonitor)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
持续监控BlockBeats、Polymarket等消息源，通过事件总线实时推送

功能:
- 多源消息轮询（BlockBeats、Polymarket、CoinGlass）
- 智能标签分类（risk/macro/exchange/btc）
- 事件总线推送
- 重复消息过滤
- 风险快讯自动升级优先级
"""

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path

from core.btc_integration.event_bus import (
    EventPriority,
    EventType,
    TradingEvent,
    event_bus,
    publish_risk_warning,
)
from core.diagnostic import safe_create_task
from core.logger import logger

# 导入原有probe功能
try:
    from core.btc_integration.engine.tools.blockbeats_probe import build_report as build_blockbeats_report
    BLOCKBEATS_AVAILABLE = True
except ImportError:
    BLOCKBEATS_AVAILABLE = False

# TODO: Polymarket 监控待实现，当前默认不可用
POLYMARKET_AVAILABLE = False


@dataclass
class NewsItem:
    """新闻条目"""
    id: str
    title: str
    content: str
    source: str
    url: str
    timestamp: float
    tags: list[str]
    priority: EventPriority = EventPriority.NORMAL
    symbols: list[str] = field(default_factory=list)  # 相关币种

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "source": self.source,
            "url": self.url,
            "timestamp": self.timestamp,
            "tags": self.tags,
            "priority": self.priority.value,
            "symbols": self.symbols,
        }


class NewsMonitor:
    """
    消息监控器

    持续监控多个消息源，实时推送到事件总线
    """

    # 监控配置
    CHECK_INTERVAL = 60  # 默认检查间隔（秒）
    RISK_CHECK_INTERVAL = 30  # 风险消息更频繁检查
    DEDUP_WINDOW = 3600  # 去重窗口（秒）

    def __init__(self):
        self._running = False
        self._stop_event = asyncio.Event()

        # 已见消息ID（去重）
        self._seen_ids: set[str] = set()
        self._seen_timestamps: dict[str, float] = {}

        # 各源最后检查时间
        self._last_check: dict[str, float] = {}

        # 监控任务
        self._tasks: list[asyncio.Task] = []

        logger.info("[NewsMonitor] 初始化完成")

    async def start(self):
        """启动监控"""
        if self._running:
            return

        self._running = True
        await event_bus.start()

        # 启动各源监控任务
        if BLOCKBEATS_AVAILABLE:
            self._tasks.append(safe_create_task(self._monitor_blockbeats(), name="_monitor_blockbeats"))

        # Polymarket（如果可用）
        if POLYMARKET_AVAILABLE:
            self._tasks.append(safe_create_task(self._monitor_polymarket(), name="_monitor_polymarket"))

        # 自定义BTC关键词监控
        self._tasks.append(safe_create_task(self._monitor_btc_keywords(), name="_monitor_btc_keywords"))

        # 清理任务
        self._tasks.append(safe_create_task(self._cleanup_loop(), name="_cleanup_loop"))

        logger.info(f"[NewsMonitor] 已启动，{len(self._tasks)}个监控任务")

    async def stop(self):
        """停止监控"""
        self._running = False
        self._stop_event.set()

        # 取消所有任务
        for task in self._tasks:
            task.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)
        await event_bus.stop()

        logger.info("[NewsMonitor] 已停止")

    async def _monitor_blockbeats(self):
        """监控BlockBeats"""
        logger.info("[NewsMonitor] 启动BlockBeats监控")

        while self._running and not self._stop_event.is_set():
            try:
                # 获取最新快讯
                report = build_blockbeats_report(
                    project_dir=Path("."),
                    timeout=15,
                    size=10
                )

                # 解析报告，提取新闻
                news_items = self._parse_blockbeats_report(report)

                # 发布新消息
                new_count = 0
                for item in news_items:
                    if self._is_new(item.id):
                        self._publish_news(item)
                        new_count += 1

                if new_count > 0:
                    logger.info(f"[NewsMonitor] BlockBeats: {new_count}条新消息")

                # 等待下一次检查
                wait_time = self.RISK_CHECK_INTERVAL if any("risk" in item.tags for item in news_items) else self.CHECK_INTERVAL
                await asyncio.wait_for(self._stop_event.wait(), timeout=wait_time)

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"[NewsMonitor] BlockBeats错误: {e}")
                await asyncio.sleep(self.CHECK_INTERVAL)

    async def _monitor_polymarket(self):
        """监控Polymarket"""
        logger.info("[NewsMonitor] 启动Polymarket监控")

        # TODO: 实现Polymarket实时监控
        while self._running and not self._stop_event.is_set():
            await asyncio.sleep(300)  # 5分钟检查一次

    async def _monitor_btc_keywords(self):
        """监控BTC相关关键词"""
        logger.info("[NewsMonitor] 启动BTC关键词监控")

        while self._running and not self._stop_event.is_set():
            # TODO: 实现Twitter/社交媒体监控
            await asyncio.sleep(120)  # 2分钟检查一次

    async def _cleanup_loop(self):
        """清理过期消息ID"""
        while self._running and not self._stop_event.is_set():
            await asyncio.sleep(300)  # 5分钟清理一次

            now = time.time()
            expired = [
                msg_id for msg_id, ts in self._seen_timestamps.items()
                if now - ts > self.DEDUP_WINDOW
            ]
            for msg_id in expired:
                self._seen_ids.discard(msg_id)
                self._seen_timestamps.pop(msg_id, None)

            if expired:
                logger.debug(f"[NewsMonitor] 清理{len(expired)}条过期消息ID")

    def _parse_blockbeats_report(self, report: str) -> list[NewsItem]:
        """解析BlockBeats报告"""
        items = []
        current_section = None

        for line in report.split("\n"):
            line = line.strip()

            # 识别章节
            if line.startswith("[flash]"):
                current_section = "flash"
                continue
            elif line.startswith("[article]"):
                current_section = "article"
                continue
            elif line.startswith("["):
                current_section = None
                continue

            # 解析条目
            if line.startswith("- ") and current_section:
                parts = line[2:].split(" | ")
                if len(parts) >= 3:
                    tags_str = parts[0]
                    title = parts[2]
                    url = parts[3] if len(parts) > 3 else ""

                    tags = tags_str.split("/")

                    # 生成唯一ID
                    msg_id = f"bb_{hash(title) % 10000000}"

                    # 确定优先级
                    priority = EventPriority.NORMAL
                    if "risk" in tags:
                        priority = EventPriority.HIGH

                    # 确定相关币种
                    symbols = self._extract_symbols(title)

                    items.append(NewsItem(
                        id=msg_id,
                        title=title,
                        content="",
                        source="blockbeats",
                        url=url,
                        timestamp=time.time(),
                        tags=tags,
                        priority=priority,
                        symbols=symbols
                    ))

        return items

    def _extract_symbols(self, text: str) -> list[str]:
        """从文本中提取币种符号"""
        import re
        symbols = []

        # 常见币种模式
        patterns = [
            (r'\bBTC\b|\bBitcoin\b|\b比特币\b', 'BTC'),
            (r'\bETH\b|\bEthereum\b|\b以太坊\b', 'ETH'),
            (r'\bSOL\b|\bSolana\b', 'SOL'),
            (r'\bXRP\b|\bRipple\b', 'XRP'),
            (r'\bDOGE\b|\bDogecoin\b', 'DOGE'),
            (r'\bUSDT\b|\bTether\b', 'USDT'),
        ]

        for pattern, symbol in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                symbols.append(symbol)

        return symbols

    def _is_new(self, msg_id: str) -> bool:
        """检查消息是否为新"""
        if msg_id in self._seen_ids:
            return False

        self._seen_ids.add(msg_id)
        self._seen_timestamps[msg_id] = time.time()
        return True

    def _publish_news(self, item: NewsItem):
        """发布新闻到事件总线"""
        # 根据标签选择事件类型
        if "risk" in item.tags:
            event_type = EventType.NEWS_RISK
        elif "macro" in item.tags:
            event_type = EventType.NEWS_MACRO
        elif "exchange" in item.tags:
            event_type = EventType.NEWS_EXCHANGE
        else:
            event_type = EventType.NEWS_FLASH

        # 构建事件
        event = TradingEvent(
            event_type=event_type,
            data=item.to_dict(),
            source=item.source,
            priority=item.priority,
            symbol=item.symbols[0] if item.symbols else None
        )

        # 发布
        event_bus.publish(event)

        # 风险消息额外发布警告
        if "risk" in item.tags and item.priority.value <= EventPriority.HIGH.value:
            publish_risk_warning(
                level="high" if item.priority == EventPriority.HIGH else "medium",
                message=f"[{item.source}] {item.title}",
                data={"source": item.source, "tags": item.tags, "url": item.url}
            )

        logger.info(f"[NewsMonitor] 发布: [{item.source}] {item.title[:50]}...")


# 便捷函数
async def start_news_monitor(symbols: list[str] | None = None) -> NewsMonitor:
    """启动消息监控"""
    monitor = NewsMonitor()
    await monitor.start()
    return monitor


if __name__ == "__main__":
    async def test():
        monitor = await start_news_monitor()

        # 测试：打印收到的事件
        def on_news(event: TradingEvent):
            print(f"\n[收到消息] {event.event_type.value}")
            print(f"  来源: {event.source}")
            print(f"  标题: {event.data.get('title', 'N/A')[:80]}")
            print(f"  标签: {event.data.get('tags', [])}")

        from core.btc_integration.event_bus import EventType, event_bus
        event_bus.subscribe(EventType.NEWS_FLASH, on_news)
        event_bus.subscribe(EventType.NEWS_RISK, on_news)

        # 运行60秒
        await asyncio.sleep(60)

        await monitor.stop()

    asyncio.run(test())
