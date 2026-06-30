#!/usr/bin/env python3
"""
交易WebSocket独立服务器
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
运行在8602端口，避免与主WebSocket(8600)冲突

功能:
- 提供交易实时数据推送
- 支持多币种订阅
- 真实行情数据转发
"""

import asyncio
import os
import time

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from api.trading_ws import handle_symbol_websocket
from core.logger import logger

# 【P1修复】WebSocket 心跳参数从环境变量读取
trading_ws_app = FastAPI(title="Trading WebSocket Server")
WS_PING_INTERVAL = float(os.getenv("UVICORN_WS_PING_INTERVAL", "30.0"))
WS_PING_TIMEOUT = float(os.getenv("UVICORN_WS_PING_TIMEOUT", "60.0"))

# CORS配置
trading_ws_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@trading_ws_app.websocket("/ws/trading/{symbol}")
async def trading_websocket_endpoint(websocket: WebSocket, symbol: str):
    """交易WebSocket端点"""
    await handle_symbol_websocket(websocket, symbol)


@trading_ws_app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "service": "trading_ws", "timestamp": int(time.time())}


async def start_trading_ws_server(host: str = "0.0.0.0", port: int = 8602):
    """启动交易WebSocket服务器"""
    config = uvicorn.Config(
        trading_ws_app,
        host=host,
        port=port,
        log_level="info",
        ws_ping_interval=WS_PING_INTERVAL,
        ws_ping_timeout=WS_PING_TIMEOUT,
    )
    server = uvicorn.Server(config)
    logger.info(f"[TradingWS] 服务器启动于 {host}:{port}")
    await server.serve()


if __name__ == "__main__":
    asyncio.run(start_trading_ws_server())
