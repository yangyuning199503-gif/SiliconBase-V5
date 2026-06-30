#!/usr/bin/env python3
"""
OKX 异步客户端
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
继承 OKXMarketDataProvider，复用行情获取能力 + 缓存逻辑。
补全交易接口（下单/查单），全部使用 aiohttp 异步请求 + HMAC 签名。

设计意图
--------
- 扩展而非包装：在架构层异步模块上直接扩展，不从引擎层同步代码包装
- 零冗余：get_price / get_klines 完全继承或基于父类缓存转换，不重复实现请求逻辑
- 全异步：所有网络 I/O 使用 aiohttp，禁止 requests / run_in_executor
- 安全优先：默认 demo 模式（x-simulated-trading: 1），凭证缺失时降级为仅行情

License: MIT
Copyright (c) 2026 SiliconBase Team
"""

import json
from typing import Any

import aiohttp

from core.btc_integration.engine.tools.okx_demo_common import (
    Credentials,
    now_iso_ms,
    sign_rest,
)
from core.btc_integration.market_data import KLineData, OKXMarketDataProvider
from core.logger import logger

# ═══════════════════════════════════════════════════════════════
# 凭证加载（私有）
# ═══════════════════════════════════════════════════════════════

def _load_credentials_from_env() -> Credentials | None:
    """从环境变量加载 OKX 凭证。"""
    import os

    api_key = os.environ.get("OKX_API_KEY", "")
    api_secret = os.environ.get("OKX_API_SECRET", "")
    passphrase = os.environ.get("OKX_API_PASSPHRASE", "")

    if api_key and api_secret and passphrase:
        return Credentials(
            api_key=api_key,
            api_secret=api_secret,
            api_passphrase=passphrase,
        )
    return None


def _load_credentials_from_config() -> Credentials | None:
    """
    从 exchange_configs.json 加载第一个可用的 OKX 活跃配置。
    复用 exchange_config.py 的解密逻辑，不重复解析文件。
    """
    try:
        from core.btc_integration.exchange_config import (
            ExchangeType,
            get_exchange_config_manager,
        )

        mgr = get_exchange_config_manager()
        for user_id in list(mgr._configs.keys()):
            for cfg in mgr.get_user_configs(user_id):
                if (
                    cfg.exchange == ExchangeType.OKX
                    and cfg.is_active
                    and cfg.api_key
                    and cfg.api_secret
                    and cfg.passphrase
                ):
                    return Credentials(
                        api_key=cfg.api_key,
                        api_secret=cfg.api_secret,
                        api_passphrase=cfg.passphrase,
                    )
    except Exception as e:
        logger.warning(f"[OKXClient] 从配置加载凭证失败: {e}")
    return None


# ═══════════════════════════════════════════════════════════════
# OKXClient
# ═══════════════════════════════════════════════════════════════

class OKXClient(OKXMarketDataProvider):
    """
    完整的 OKX 异步客户端。

    继承自 OKXMarketDataProvider，复用其价格/K线获取能力 + 缓存逻辑。
    补全交易接口（下单/查单），全部使用 aiohttp 异步请求。
    """

    def __init__(
        self,
        credentials: Credentials | None = None,
        demo: bool = True,
    ):
        super().__init__()
        self.credentials = credentials
        self.demo = demo
        self._session: aiohttp.ClientSession | None = None

    # ------------------------------------------------------------------
    # 会话生命周期
    # ------------------------------------------------------------------

    def _ensure_session(self) -> aiohttp.ClientSession:
        """确保可复用的 ClientSession 存在。"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """关闭 aiohttp 会话。调用方应在生命周期结束时调用。"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _get_inst_id(symbol: str) -> str:
        """symbol → inst_id 转换（BTC → BTC-USDT-SWAP）。"""
        return f"{symbol.upper()}-USDT-SWAP"

    def _make_auth_headers(
        self,
        method: str,
        request_path: str,
        body_text: str = "",
    ) -> dict[str, str]:
        """
        构造 OKX 认证头（HMAC-SHA256）。

        使用 engine/tools/okx_demo_common.py 的 sign_rest()（纯字符串计算，无 I/O）。
        """
        if not self.credentials:
            raise RuntimeError(
                "[OKXClient] 未配置凭证，无法构造认证头。"
                "请检查环境变量 OKX_API_KEY / OKX_API_SECRET / OKX_API_PASSPHRASE，"
                "或在 data/exchange_configs.json 中添加 OKX 配置。"
            )

        ts = now_iso_ms()
        signature = sign_rest(
            ts=ts,
            method=method.upper(),
            request_path=request_path,
            body=body_text,
            secret=self.credentials.api_secret,
        )

        headers: dict[str, str] = {
            "OK-ACCESS-KEY": self.credentials.api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": self.credentials.api_passphrase,
            "Content-Type": "application/json",
        }
        if self.demo:
            headers["x-simulated-trading"] = "1"
        return headers

    # ------------------------------------------------------------------
    # 行情接口（覆盖 get_klines 以兼容 api_bridge.py 的原始列表访问方式）
    # ------------------------------------------------------------------

    async def get_klines(
        self,
        symbol: str,
        interval: str = "1H",
        limit: int = 100,
    ) -> list[list[float]]:
        """
        获取K线数据。

        内部完全复用父类的缓存、请求、错误处理、mock 回退逻辑，
        返回 api_bridge.py / trade_executor.py 期望的原始列表格式：
        ``[[ts, open, high, low, close, volume], ...]``
        """
        klines_data: list[KLineData] = await super().get_klines(symbol, interval, limit)
        if not klines_data:
            return []

        # 将 KLineData 转换为原始列表格式，保持索引访问兼容性
        return [
            [k.time, k.open, k.high, k.low, k.close, k.volume]
            for k in klines_data
        ]

    # ------------------------------------------------------------------
    # 交易接口（新增）
    # ------------------------------------------------------------------

    async def create_order(
        self,
        symbol: str,
        side: str,
        qty: str,
        td_mode: str = "cross",
        ord_type: str = "market",
        reduce_only: bool = False,
    ) -> dict[str, Any]:
        """
        创建订单。

        POST ``/api/v5/trade/order``

        Parameters
        ----------
        symbol : str
            交易币种，如 ``"BTC"``（内部转换为 ``"BTC-USDT-SWAP"``）。
        side : str
            ``"buy"`` 或 ``"sell"``。
        qty : str
            下单数量（合约张数或币数量，取决于 instId）。
        td_mode : str
            交易模式，默认 ``"cross"``（全仓）。
        ord_type : str
            订单类型，默认 ``"market"``。
        reduce_only : bool
            是否只减仓。

        Returns
        -------
        Dict[str, Any]
            OKX 原始响应：``{"code": "0", "msg": "", "data": [{"ordId": "...", ...}]}``
            出错时返回：``{"code": "...", "msg": "...", "data": []}``
        """
        if not self.credentials:
            logger.error("[OKXClient] create_order 失败：客户端未配置凭证")
            return {"code": "-1", "msg": "client_not_configured", "data": []}

        inst_id = self._get_inst_id(symbol)
        path = "/api/v5/trade/order"
        body: dict[str, Any] = {
            "instId": inst_id,
            "tdMode": td_mode,
            "side": side,
            "ordType": ord_type,
            "sz": qty,
        }
        if reduce_only:
            body["reduceOnly"] = True

        body_text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        headers = self._make_auth_headers("POST", path, body_text)
        url = f"{self.REST_BASE}{path}"

        try:
            session = self._ensure_session()
            async with session.post(
                url,
                headers=headers,
                data=body_text,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()
                if data.get("code") != "0":
                    logger.error(
                        f"[OKXClient] create_order 错误: {data.get('msg')} "
                        f"| symbol={symbol} side={side} qty={qty}"
                    )
                else:
                    rows = data.get("data", [])
                    ord_id = rows[0].get("ordId") if rows else "N/A"
                    logger.info(
                        f"[OKXClient] create_order 成功: {symbol} {side} {qty} "
                        f"| ordId={ord_id}"
                    )
                return data

        except aiohttp.ClientError as e:
            logger.error(f"[OKXClient] create_order 网络错误: {e}")
            return {"code": "network_error", "msg": str(e), "data": []}
        except Exception as e:
            logger.error(f"[OKXClient] create_order 异常: {e}", exc_info=True)
            return {"code": "exception", "msg": str(e), "data": []}

    async def query_order(
        self,
        symbol: str,
        ord_id: str,
    ) -> dict[str, Any]:
        """
        查询订单状态。

        GET ``/api/v5/trade/order?instId={inst_id}&ordId={ord_id}``

        Parameters
        ----------
        symbol : str
            交易币种，如 ``"BTC"``。
        ord_id : str
            OKX 交易所订单 ID（``ordId``）。

        Returns
        -------
        Dict[str, Any]
            OKX 原始响应：
            ``{"code": "0", "msg": "", "data": [{"state": "filled", "accFillSz": "...", ...}]}``
        """
        if not self.credentials:
            logger.error("[OKXClient] query_order 失败：客户端未配置凭证")
            return {"code": "-1", "msg": "client_not_configured", "data": []}

        inst_id = self._get_inst_id(symbol)
        # OKX 签名要求 request_path 包含 query string
        request_path = f"/api/v5/trade/order?instId={inst_id}&ordId={ord_id}"
        headers = self._make_auth_headers("GET", request_path)
        url = f"{self.REST_BASE}{request_path}"

        try:
            session = self._ensure_session()
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
                if data.get("code") != "0":
                    logger.error(
                        f"[OKXClient] query_order 错误: {data.get('msg')} "
                        f"| ord_id={ord_id} symbol={symbol}"
                    )
                else:
                    rows = data.get("data", [{}])
                    state = rows[0].get("state", "unknown") if rows else "unknown"
                    logger.debug(
                        f"[OKXClient] query_order 成功: ord_id={ord_id} state={state}"
                    )
                return data

        except aiohttp.ClientError as e:
            logger.error(f"[OKXClient] query_order 网络错误: {e}")
            return {"code": "network_error", "msg": str(e), "data": []}
        except Exception as e:
            logger.error(f"[OKXClient] query_order 异常: {e}", exc_info=True)
            return {"code": "exception", "msg": str(e), "data": []}


# ═══════════════════════════════════════════════════════════════
# 工厂函数
# ═══════════════════════════════════════════════════════════════

_okx_client_instance: OKXClient | None = None


def get_okx_client() -> OKXClient:
    """
    从交易所配置读取凭证，返回 OKXClient 实例（单例）。

    优先顺序：
    1. 环境变量 ``OKX_API_KEY`` / ``OKX_API_SECRET`` / ``OKX_API_PASSPHRASE``
    2. ``data/exchange_configs.json`` 中的第一个活跃 OKX 配置
       （复用 ``exchange_config.py`` 的 Fernet 解密逻辑）
    3. 如果都没有，返回降级客户端（仅行情可用，交易方法返回错误）

    Returns
    -------
    OKXClient
        已配置凭证的客户端（交易可用），或降级客户端（仅行情）。
    """
    global _okx_client_instance

    if _okx_client_instance is not None:
        return _okx_client_instance

    credentials = _load_credentials_from_env()
    if not credentials:
        credentials = _load_credentials_from_config()

    if credentials:
        logger.info("[OKXClient] 已加载凭证，交易功能可用")
        _okx_client_instance = OKXClient(credentials=credentials, demo=True)
    else:
        logger.warning(
            "[OKXClient] 未找到 OKX 凭证，返回降级客户端（仅行情可用）。"
            "如需交易，请配置环境变量 OKX_API_KEY / OKX_API_SECRET / OKX_API_PASSPHRASE，"
            "或通过前端 ExchangeConfigPanel 添加交易所配置。"
        )
        _okx_client_instance = OKXClient(credentials=None, demo=True)

    return _okx_client_instance
