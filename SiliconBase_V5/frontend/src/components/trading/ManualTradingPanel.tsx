/**
 * ManualTradingPanel.tsx
 * 手动交易面板组件
 *
 * 功能:
 * - K线图展示（待接入lightweight-charts）
 * - 买卖下单
 * - 持仓显示
 * - 实时价格推送
 */

import React, { useState, useEffect, useCallback, useRef } from "react";
import { TrendingUp, TrendingDown, Wallet, Settings } from "lucide-react";
import { tradingModeApi, ManualPosition } from "../../utils/api/tradingMode";
import KLineChart from "./KLineChart";
import { useNotifications } from "../../hooks/useNotifications";
import { useTradingStore } from "../../stores/tradingStore";
import { buildWsUrl } from "../../config/api";

interface Position {
  symbol: string;
  side: "long" | "short";
  size: number;
  entryPrice: number;
  markPrice: number;
  pnl: number;
  pnlPercent: number;
  leverage: number;
}

// 后端字段转前端字段
function transformPosition(backend: ManualPosition): Position {
  return {
    symbol: backend.symbol,
    side: backend.side === "buy" ? "long" : "short",
    size: backend.quantity,
    entryPrice: backend.entry_price,
    markPrice: backend.mark_price,
    pnl: backend.unrealized_pnl,
    pnlPercent:
      ((backend.mark_price - backend.entry_price) / backend.entry_price) * 100,
    leverage: backend.leverage,
  };
}

interface OrderForm {
  side: "buy" | "sell";
  type: "market" | "limit";
  price?: number;
  amount: number;
  leverage: number;
}

const INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"];

export const ManualTradingPanel: React.FC = () => {
  const [activeSymbol, _setActiveSymbol] = useState("BTC");
  const [activeInterval, setActiveInterval] = useState("1h");
  const [currentPrice, setCurrentPrice] = useState<number | null>(null);
  const [priceChange24h, setPriceChange24h] = useState(0);
  const [positions, setPositions] = useState<Position[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [orderForm, setOrderForm] = useState<OrderForm>({
    side: "buy",
    type: "market",
    amount: 0.1,
    leverage: 1,
  });
  const wsRef = useRef<WebSocket | null>(null);
  const { showNotification } = useNotifications();
  const { accountBalance, simulationStatus } = useTradingStore();

  // WebSocket连接（价格推送）
  useEffect(() => {
    // 交易数据 WebSocket 统一使用 buildWsUrl，不再硬编码 8602 端口
    const token = localStorage.getItem("silicon_token");
    const wsUrl = `${buildWsUrl(`/ws/trading/${activeSymbol}`)}${token ? `?token=${token}` : ""}`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log("手动交易WebSocket已连接");
    };

    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        if (message.type === "price_update" && message.data) {
          setCurrentPrice(message.data.price);
          setPriceChange24h(message.data.change24h || 0);
        }
      } catch (error) {
        console.error("解析WebSocket消息失败:", error);
      }
    };

    ws.onerror = (event) => {
      console.error("手动交易WebSocket错误事件:", event.type);
    };

    wsRef.current = ws;

    return () => {
      ws.close();
    };
  }, [activeSymbol]);

  // 获取持仓
  const fetchPositions = useCallback(async () => {
    try {
      const response = await tradingModeApi.getManualPositions();
      if (response.positions) {
        setPositions(response.positions.map(transformPosition));
      } else {
        setPositions([]);
      }
    } catch (error) {
      console.error("获取持仓失败:", error);
    }
  }, []);

  useEffect(() => {
    fetchPositions();
    const interval = setInterval(fetchPositions, 5000);
    return () => clearInterval(interval);
  }, [fetchPositions]);

  const handlePlaceOrder = async () => {
    const sideText = orderForm.side === "buy" ? "买入" : "卖出";
    const simText =
      simulationStatus?.is_simulation !== false ? "【模拟盘】" : "【实盘】";
    if (
      !window.confirm(
        `${simText} 确认${sideText}？\n\n` +
          `币种: ${activeSymbol}\n` +
          `数量: ${orderForm.amount}\n` +
          `杠杆: ${orderForm.leverage}x\n` +
          `类型: ${orderForm.type === "market" ? "市价" : "限价"}\n` +
          `${orderForm.type === "limit" ? `价格: $${orderForm.price}\n` : ""}` +
          `预计保证金: $${((orderForm.amount * (currentPrice || 0)) / orderForm.leverage).toFixed(2)}`,
      )
    ) {
      return;
    }
    setIsLoading(true);
    try {
      await tradingModeApi.placeManualOrder({
        symbol: activeSymbol,
        side: orderForm.side,
        type: orderForm.type,
        price: orderForm.price,
        amount: orderForm.amount,
        leverage: orderForm.leverage,
      });
      showNotification({
        type: "success",
        title: "下单成功",
        message: `${sideText} ${activeSymbol} 订单已提交`,
      });
      // 刷新持仓
      fetchPositions();
    } catch (error) {
      showNotification({
        type: "error",
        title: "下单失败",
        message: (error as Error).message,
      });
    } finally {
      setIsLoading(false);
    }
  };

  const totalPnl = positions.reduce((sum, p) => sum + p.pnl, 0);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* 左侧：图表区域 */}
      <div className="lg:col-span-2 space-y-4">
        {/* 价格头部 */}
        <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
          <div className="flex items-center justify-between flex-wrap gap-4">
            <div className="flex items-center gap-4">
              <h2 className="text-2xl font-bold text-white">
                {activeSymbol}/USDT
              </h2>
              <div className="flex gap-2">
                {INTERVALS.map((interval) => (
                  <button
                    key={interval}
                    onClick={() => setActiveInterval(interval)}
                    className={`px-3 py-1 rounded-lg text-sm font-medium transition-colors ${
                      activeInterval === interval
                        ? "bg-blue-600 text-white"
                        : "bg-gray-700 text-gray-300 hover:bg-gray-600"
                    }`}
                  >
                    {interval}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex items-center gap-6">
              <div>
                <p className="text-3xl font-bold text-white">
                  {currentPrice ? `$${currentPrice.toLocaleString()}` : "--"}
                </p>
              </div>
              <div
                className={`flex items-center gap-1 px-3 py-1 rounded-full text-sm font-medium ${
                  priceChange24h >= 0
                    ? "bg-green-500/20 text-green-400"
                    : "bg-red-500/20 text-red-400"
                }`}
              >
                {priceChange24h >= 0 ? (
                  <TrendingUp className="w-4 h-4" />
                ) : (
                  <TrendingDown className="w-4 h-4" />
                )}
                <span>
                  {priceChange24h >= 0 ? "+" : ""}
                  {priceChange24h.toFixed(2)}%
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* K线图 */}
        <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
          <KLineChart symbol={activeSymbol} interval={activeInterval} />
        </div>
      </div>

      {/* 右侧：交易面板 */}
      <div className="space-y-4">
        {/* 下单面板 */}
        <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-white">下单</h3>
            <button className="p-1.5 text-gray-400 hover:text-white">
              <Settings className="w-4 h-4" />
            </button>
          </div>

          {/* 余额展示 */}
          {accountBalance !== null && (
            <div className="mb-3 px-3 py-2 bg-gray-900 rounded-lg flex justify-between items-center">
              <span className="text-sm text-gray-400">可用余额</span>
              <span className="text-sm font-medium text-white">
                ${accountBalance.toFixed(2)} USDT
              </span>
            </div>
          )}

          {/* 买卖切换 */}
          <div className="grid grid-cols-2 gap-2 mb-4">
            <button
              onClick={() => setOrderForm({ ...orderForm, side: "buy" })}
              className={`py-2 rounded-lg font-medium transition-colors ${
                orderForm.side === "buy"
                  ? "bg-green-600 text-white"
                  : "bg-gray-700 text-gray-300 hover:bg-gray-600"
              }`}
            >
              买入
            </button>
            <button
              onClick={() => setOrderForm({ ...orderForm, side: "sell" })}
              className={`py-2 rounded-lg font-medium transition-colors ${
                orderForm.side === "sell"
                  ? "bg-red-600 text-white"
                  : "bg-gray-700 text-gray-300 hover:bg-gray-600"
              }`}
            >
              卖出
            </button>
          </div>

          {/* 订单类型 */}
          <div className="flex gap-2 mb-4">
            {(["market", "limit"] as const).map((type) => (
              <button
                key={type}
                onClick={() => setOrderForm({ ...orderForm, type })}
                className={`flex-1 py-2 rounded-lg text-sm font-medium transition-colors ${
                  orderForm.type === type
                    ? "bg-blue-600 text-white"
                    : "bg-gray-700 text-gray-300 hover:bg-gray-600"
                }`}
              >
                {type === "market" ? "市价" : "限价"}
              </button>
            ))}
          </div>

          {/* 价格输入（限价单） */}
          {orderForm.type === "limit" && (
            <div className="mb-4">
              <label className="block text-sm text-gray-400 mb-2">
                价格 (USDT)
              </label>
              <div className="relative">
                <input
                  type="number"
                  value={orderForm.price || ""}
                  onChange={(e) =>
                    setOrderForm({
                      ...orderForm,
                      price: parseFloat(e.target.value),
                    })
                  }
                  className="w-full px-4 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white focus:border-blue-500 focus:outline-none"
                  placeholder="输入价格"
                />
                <span className="absolute right-4 top-1/2 -translate-y-1/2 text-gray-500 text-sm">
                  USDT
                </span>
              </div>
            </div>
          )}

          {/* 数量输入 */}
          <div className="mb-4">
            <label className="block text-sm text-gray-400 mb-2">数量</label>
            <div className="relative">
              <input
                type="number"
                value={orderForm.amount}
                onChange={(e) =>
                  setOrderForm({
                    ...orderForm,
                    amount: parseFloat(e.target.value),
                  })
                }
                className="w-full px-4 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white focus:border-blue-500 focus:outline-none"
                step={0.01}
                min={0.001}
              />
              <span className="absolute right-4 top-1/2 -translate-y-1/2 text-gray-500 text-sm">
                {activeSymbol}
              </span>
            </div>
          </div>

          {/* 杠杆选择 */}
          <div className="mb-4">
            <label className="block text-sm text-gray-400 mb-2">杠杆</label>
            <div className="grid grid-cols-5 gap-2">
              {[1, 3, 5, 10, 20].map((lev) => (
                <button
                  key={lev}
                  onClick={() => setOrderForm({ ...orderForm, leverage: lev })}
                  className={`py-1.5 rounded-lg text-sm font-medium transition-colors ${
                    orderForm.leverage === lev
                      ? "bg-blue-600 text-white"
                      : "bg-gray-700 text-gray-300 hover:bg-gray-600"
                  }`}
                >
                  {lev}x
                </button>
              ))}
            </div>
          </div>

          {/* 预估信息 */}
          <div className="bg-gray-900 rounded-lg p-3 mb-4 space-y-2">
            <div className="flex justify-between text-sm">
              <span className="text-gray-500">名义价值</span>
              <span className="text-white">
                ${(orderForm.amount * (currentPrice || 0)).toFixed(2)}
              </span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-gray-500">保证金</span>
              <span className="text-white">
                $
                {(
                  (orderForm.amount * (currentPrice || 0)) /
                  orderForm.leverage
                ).toFixed(2)}
              </span>
            </div>
          </div>

          {/* 下单按钮 */}
          <button
            onClick={handlePlaceOrder}
            disabled={isLoading}
            className={`w-full py-3 rounded-xl font-semibold transition-colors ${
              orderForm.side === "buy"
                ? "bg-green-600 hover:bg-green-500"
                : "bg-red-600 hover:bg-red-500"
            } disabled:bg-gray-700 disabled:cursor-not-allowed text-white`}
          >
            {isLoading
              ? "提交中..."
              : `${orderForm.side === "buy" ? "买入" : "卖出"} ${activeSymbol}`}
          </button>
        </div>

        {/* 持仓面板 */}
        <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-white flex items-center gap-2">
              <Wallet className="w-4 h-4" />
              持仓
            </h3>
            <span
              className={`text-sm font-medium ${totalPnl >= 0 ? "text-green-400" : "text-red-400"}`}
            >
              总盈亏: {totalPnl >= 0 ? "▲ +" : "▼ -"}
              {Math.abs(totalPnl).toFixed(2)} USDT
            </span>
          </div>

          {positions.length === 0 ? (
            <div className="text-center py-6 text-gray-500">
              <p>暂无持仓</p>
            </div>
          ) : (
            <div className="space-y-3">
              {positions.map((position, idx) => (
                <div key={idx} className="bg-gray-900 rounded-lg p-3">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-white">
                        {position.symbol}
                      </span>
                      <span
                        className={`px-2 py-0.5 rounded text-xs ${
                          position.side === "long"
                            ? "bg-green-500/20 text-green-400"
                            : "bg-red-500/20 text-red-400"
                        }`}
                      >
                        {position.side === "long" ? "做多" : "做空"}
                      </span>
                      <span className="text-xs text-gray-500">
                        {position.leverage}x
                      </span>
                    </div>
                    <span
                      className={`font-medium ${
                        position.pnl >= 0 ? "text-green-400" : "text-red-400"
                      }`}
                    >
                      {position.pnl >= 0 ? "▲ +" : "▼ -"}
                      {Math.abs(position.pnl).toFixed(2)} USDT
                    </span>
                  </div>

                  <div className="grid grid-cols-2 gap-2 text-sm">
                    <div>
                      <span className="text-gray-500">数量:</span>
                      <span className="text-white ml-1">
                        {position.size} {position.symbol}
                      </span>
                    </div>
                    <div>
                      <span className="text-gray-500">开仓价:</span>
                      <span className="text-white ml-1">
                        ${position.entryPrice.toLocaleString()}
                      </span>
                    </div>
                    <div>
                      <span className="text-gray-500">标记价:</span>
                      <span className="text-white ml-1">
                        ${position.markPrice.toLocaleString()}
                      </span>
                    </div>
                    <div>
                      <span className="text-gray-500">盈亏率:</span>
                      <span
                        className={`ml-1 ${position.pnlPercent >= 0 ? "text-green-400" : "text-red-400"}`}
                      >
                        {position.pnlPercent >= 0 ? "▲ +" : "▼ -"}
                        {Math.abs(position.pnlPercent).toFixed(2)}%
                      </span>
                    </div>
                  </div>

                  {/* 平仓按钮 */}
                  <button
                    className="w-full mt-3 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm text-white transition-colors"
                    onClick={() => console.log("平仓:", position.symbol)}
                  >
                    平仓
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default ManualTradingPanel;
