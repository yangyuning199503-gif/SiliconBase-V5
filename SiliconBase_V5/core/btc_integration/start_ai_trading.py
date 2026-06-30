#!/usr/bin/env python3
"""
AI交易启动器
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
一键启动AI驱动的交易系统

用法:
    python start_ai_trading.py --symbols BTC,ETH --mode live
    python start_ai_trading.py --mode dry-run  # 模拟模式

功能:
- 启动AI指挥官
- 启动消息监控
- 启动交易子代理
- 提供REST API接口
"""

import argparse
import asyncio
import contextlib
import os
import signal
import sys

# 导入新组件
from core.btc_integration.ai_trading_commander import AITradingCommander
from core.diagnostic import safe_create_task
from core.logger import logger

# 尝试导入FastAPI（用于REST接口）
try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import PlainTextResponse
    API_AVAILABLE = True
except ImportError:
    API_AVAILABLE = False
    logger.warning("[StartAITrading] FastAPI不可用，REST API禁用")

# 全局指挥官实例
commander: AITradingCommander | None = None

# 【P1修复】WebSocket 心跳参数从环境变量读取
WS_PING_INTERVAL = float(os.getenv("UVICORN_WS_PING_INTERVAL", "30.0"))
WS_PING_TIMEOUT = float(os.getenv("UVICORN_WS_PING_TIMEOUT", "60.0"))


def setup_signal_handlers():
    """设置信号处理器"""
    def signal_handler(sig, frame):
        logger.info("[StartAITrading] 收到中断信号，正在停止...")
        if commander:
            commander.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


async def start_rest_api(host: str = "0.0.0.0", port: int = 18080):
    """启动REST API"""
    if not API_AVAILABLE:
        logger.warning("[StartAITrading] FastAPI不可用，跳过API启动")
        return

    import uvicorn

    app = FastAPI(title="AI Trading API", version="1.0.0")

    @app.get("/")
    async def root():
        return {
            "service": "AI Trading System",
            "status": "running" if commander and commander._running else "stopped"
        }

    @app.get("/status")
    async def get_status():
        """获取系统状态"""
        if not commander:
            raise HTTPException(status_code=503, detail="指挥官未启动")
        return commander.get_status()

    @app.get("/report")
    async def get_report():
        """获取最新报告"""
        if not commander or not commander.latest_report:
            raise HTTPException(status_code=404, detail="报告不存在")
        return commander.latest_report.to_dict()

    @app.get("/report.md")
    async def get_report_md():
        """获取Markdown格式报告"""
        if not commander or not commander.latest_report:
            raise HTTPException(status_code=404, detail="报告不存在")
        return PlainTextResponse(content=commander.latest_report.to_markdown())

    @app.post("/intervene")
    async def intervene(action: str, symbols: str = "", reason: str = ""):
        """
        人工干预

        Args:
            action: pause, resume, close_all, emergency_close
            symbols: 逗号分隔的币种列表，空表示全部
            reason: 干预原因
        """
        if not commander:
            raise HTTPException(status_code=503, detail="指挥官未启动")

        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()] or None

        await commander.intervene(action, symbol_list, reason)

        return {"status": "ok", "action": action, "symbols": symbol_list}

    @app.post("/start_agent")
    async def start_agent(symbol: str):
        """启动交易子代理"""
        if not commander:
            raise HTTPException(status_code=503, detail="指挥官未启动")

        agent = await commander.start_subagent(symbol.upper())
        return {"status": "ok", "symbol": symbol, "runtime_id": agent.runtime_id}

    @app.post("/stop_agent")
    async def stop_agent(symbol: str):
        """停止交易子代理"""
        if not commander:
            raise HTTPException(status_code=503, detail="指挥官未启动")

        await commander.stop_subagent(symbol.upper())
        return {"status": "ok", "symbol": symbol}

    @app.get("/events")
    async def get_events(
        event_type: str = "",
        limit: int = 100,
        since: float = 0
    ):
        """获取最近事件"""
        from core.btc_integration.event_bus import EventType, event_bus

        evt_type = None
        if event_type:
            with contextlib.suppress(ValueError):
                evt_type = EventType(event_type)

        events = event_bus.get_recent_events(
            event_type=evt_type,
            since=since if since > 0 else None,
            limit=limit
        )

        return {
            "events": [e.to_dict() for e in events],
            "count": len(events),
            "total_published": event_bus.get_stats()["published"]
        }

    logger.info(f"[StartAITrading] 启动REST API: http://{host}:{port}")

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        ws_ping_interval=WS_PING_INTERVAL,
        ws_ping_timeout=WS_PING_TIMEOUT,
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    """主函数"""
    global commander

    parser = argparse.ArgumentParser(description="AI Trading System")
    parser.add_argument(
        "--symbols",
        default="BTC",
        help="交易币种，逗号分隔 (默认: BTC)"
    )
    parser.add_argument(
        "--mode",
        choices=["live", "dry-run", "backtest"],
        default="dry-run",
        help="运行模式 (默认: dry-run)"
    )
    parser.add_argument(
        "--api-host",
        default="0.0.0.0",
        help="API监听地址"
    )
    parser.add_argument(
        "--api-port",
        type=int,
        default=18080,
        help="API监听端口"
    )
    parser.add_argument(
        "--no-api",
        action="store_true",
        help="禁用REST API"
    )
    parser.add_argument(
        "--report-interval",
        type=int,
        default=300,
        help="报告生成间隔（秒）"
    )

    args = parser.parse_args()

    # 解析币种
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    logger.info("[StartAITrading] 启动AI交易系统")
    logger.info(f"  币种: {symbols}")
    logger.info(f"  模式: {args.mode}")

    # 设置信号处理
    setup_signal_handlers()

    # 创建并启动指挥官
    commander = AITradingCommander(
        symbols=symbols,
        auto_start=(args.mode != "backtest"),
        report_interval=args.report_interval
    )

    # 启动任务
    tasks = []

    # 指挥官主任务
    tasks.append(safe_create_task(commander.start(), name="start"))

    # REST API
    if not args.no_api and API_AVAILABLE:
        tasks.append(asyncio.create_task(
            start_rest_api(args.api_host, args.api_port)
        ))

    # 等待所有任务
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("[StartAITrading] 任务被取消")
    finally:
        if commander:
            await commander.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
