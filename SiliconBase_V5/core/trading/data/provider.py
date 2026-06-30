#!/usr/bin/env python3
"""
市场数据提供者

整合多个数据源，提供统一接口
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

import aiohttp
import pandas as pd


class DataSource(Enum):
    """数据源类型"""
    BINANCE = "binance"
    OKX = "okx"
    COINGLASS = "coinglass"


@dataclass
class KLineData:
    """K线数据"""
    time: int  # Unix timestamp in seconds
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class PriceData:
    """价格数据"""
    symbol: str
    price: float
    change_24h: float
    change_24h_percent: float
    high_24h: float
    low_24h: float
    volume_24h: float
    timestamp: int


class MarketDataProvider:
    """
    市场数据提供者

    支持多数据源:
    - Binance (主要价格数据)
    - OKX (合约数据)
    - CoinGlass (情绪和事件数据)
    """

    # API endpoints
    BINANCE_SPOT_URL = "https://api.binance.com/api/v3"
    BINANCE_FUTURES_URL = "https://fapi.binance.com/fapi/v1"
    OKX_URL = "https://www.okx.com/api/v5"

    # K线间隔映射 (毫秒)
    INTERVAL_MS = {
        "1m": 60_000,
        "5m": 300_000,
        "15m": 900_000,
        "30m": 1_800_000,
        "1h": 3_600_000,
        "4h": 14_400_000,
        "1d": 86_400_000,
    }

    def __init__(self, primary_source: DataSource = DataSource.BINANCE):
        """
        初始化数据提供者

        Args:
            primary_source: 主数据源
        """
        self.primary_source = primary_source
        self._cache: dict[str, pd.DataFrame] = {}
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取HTTP会话"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def get_price(self, symbol: str) -> PriceData | None:
        """
        获取实时价格

        Args:
            symbol: 交易对，如 BTC, ETH

        Returns:
            PriceData或None
        """
        try:
            session = await self._get_session()

            # 使用Binance获取价格
            url = f"{self.BINANCE_SPOT_URL}/ticker/24hr"
            symbol_fmt = f"{symbol.upper()}USDT"

            async with session.get(url, params={"symbol": symbol_fmt}) as resp:
                if resp.status != 200:
                    return None

                data = await resp.json()

                return PriceData(
                    symbol=symbol.upper(),
                    price=float(data['lastPrice']),
                    change_24h=float(data['priceChange']),
                    change_24h_percent=float(data['priceChangePercent']),
                    high_24h=float(data['highPrice']),
                    low_24h=float(data['lowPrice']),
                    volume_24h=float(data['volume']),
                    timestamp=int(datetime.now().timestamp())
                )

        except Exception as e:
            print(f"[MarketDataProvider] 获取价格失败: {e}")
            return None

    async def get_klines(self,
                        symbol: str,
                        interval: str = "1h",
                        limit: int = 100,
                        start_time: int | None = None,
                        end_time: int | None = None) -> list[KLineData]:
        """
        获取K线数据

        Args:
            symbol: 交易对
            interval: 时间间隔
            limit: 数量限制
            start_time: 开始时间戳(毫秒)
            end_time: 结束时间戳(毫秒)

        Returns:
            K线数据列表
        """
        try:
            session = await self._get_session()

            url = f"{self.BINANCE_FUTURES_URL}/klines"
            symbol_fmt = f"{symbol.upper()}USDT"

            params = {
                "symbol": symbol_fmt,
                "interval": interval,
                "limit": limit
            }

            if start_time:
                params["startTime"] = start_time
            if end_time:
                params["endTime"] = end_time

            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return []

                data = await resp.json()

                klines = []
                for item in data:
                    klines.append(KLineData(
                        time=int(item[0] / 1000),  # 转换为秒
                        open=float(item[1]),
                        high=float(item[2]),
                        low=float(item[3]),
                        close=float(item[4]),
                        volume=float(item[5])
                    ))

                return klines

        except Exception as e:
            print(f"[MarketDataProvider] 获取K线失败: {e}")
            return []

    async def get_historical_data(self,
                                 symbol: str,
                                 interval: str = "1h",
                                 days: int = 30) -> pd.DataFrame:
        """
        获取历史数据

        Args:
            symbol: 交易对
            interval: 时间间隔
            days: 天数

        Returns:
            DataFrame with columns: open, high, low, close, volume
        """
        # 检查缓存
        cache_key = f"{symbol}_{interval}_{days}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # 计算时间范围
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = end_time - (days * 24 * 60 * 60 * 1000)

        # 分页获取数据
        all_klines = []
        current_start = start_time

        while current_start < end_time:
            klines = await self.get_klines(
                symbol, interval,
                limit=1000,
                start_time=current_start,
                end_time=end_time
            )

            if not klines:
                break

            all_klines.extend(klines)

            # 更新开始时间
            current_start = klines[-1].time * 1000 + self.INTERVAL_MS.get(interval, 3600000)

            # 避免请求过快
            await asyncio.sleep(0.1)

        if not all_klines:
            return pd.DataFrame()

        # 转换为DataFrame
        df = pd.DataFrame([
            {
                'timestamp': k.time,
                'open': k.open,
                'high': k.high,
                'low': k.low,
                'close': k.close,
                'volume': k.volume
            }
            for k in all_klines
        ])

        # 设置时间索引
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='s')
        df.set_index('datetime', inplace=True)
        df.drop('timestamp', axis=1, inplace=True)

        # 去重和排序
        df = df[~df.index.duplicated(keep='last')].sort_index()

        # 缓存
        self._cache[cache_key] = df

        return df

    def get_cached_data(self, symbol: str, interval: str = "1h") -> pd.DataFrame | None:
        """获取缓存的数据"""
        for key, df in self._cache.items():
            if key.startswith(f"{symbol}_{interval}"):
                return df
        return None

    def clear_cache(self):
        """清除缓存"""
        self._cache.clear()

    async def close(self):
        """关闭连接"""
        if self._session and not self._session.closed:
            await self._session.close()


# 全局数据提供者实例
_provider: MarketDataProvider | None = None


def get_market_data_provider() -> MarketDataProvider:
    """获取全局数据提供者实例"""
    global _provider
    if _provider is None:
        _provider = MarketDataProvider()
    return _provider
