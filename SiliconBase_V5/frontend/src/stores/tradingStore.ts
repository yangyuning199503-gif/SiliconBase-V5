/**
 * 交易状态管理 (Trading Store)
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 * 使用 Zustand 管理交易相关的全局状态
 *
 * 功能:
 * - 币种管理 (添加/删除/切换)
 * - 市场数据 (价格/K线)
 * - 交易数据 (历史/持仓/信号)
 * - WebSocket 连接管理
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";
import { fetchAPI } from "../utils/api/index";
import { buildWsUrl } from "../config/api";

// ═══════════════════════════════════════════════════════════════
// 类型定义
// ═══════════════════════════════════════════════════════════════

export interface TradingSymbol {
  symbol: string;
  base: string;
  quote: string;
  name: string;
  isCustom: boolean;
  enabled: boolean;
  icon?: string;
}

export interface KLineData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface TradeMarker {
  id: string;
  time: number;
  price: number;
  type: "buy" | "sell";
  source: "ai" | "manual";
  strategy?: string;
  quantity?: number;
  pnl?: number;
}

export interface TradeRecord {
  id: string;
  symbol: string;
  action: "buy" | "sell";
  price: number;
  quantity: number;
  total: number;
  fee: number;
  timestamp: number;
  source: "ai" | "manual";
  strategy?: string;
  pnl?: number;
}

export interface PositionInfo {
  symbol: string;
  side: "long" | "short" | "none";
  quantity: number;
  entryPrice: number;
  markPrice: number;
  unrealizedPnl: number;
  realizedPnl: number;
  margin: number;
  leverage: number;
  updateTime: number;
}

export interface PriceInfo {
  symbol: string;
  price: number;
  change24h: number;
  change24hPercent: number;
  high24h: number;
  low24h: number;
  volume24h: number;
  timestamp: number;
}

export interface TradeSignal {
  id: string;
  symbol: string;
  action: "buy" | "sell";
  price: number;
  quantity: number;
  strategy: string;
  confidence: number;
  reason: string;
  timestamp: number;
}

export interface MCPCall {
  tool_name: string;
  symbol?: string;
  success?: boolean;
  duration_ms?: number;
  result_summary?: string;
  timestamp: number;
}

export interface CommanderReport {
  timestamp: number;
  active_agents: number;
  total_positions: number;
  daily_pnl: number;
  risk_exposure: number;
  market_sentiment: string;
  ai_thoughts: string;
}

export interface ErrorEvent {
  id: string;
  type: string;
  message: string;
  timestamp: number;
  details?: any;
}

export type WebSocketMessage =
  | { type: "price_update"; symbol: string; data: PriceInfo }
  | {
      type: "market_data_update";
      symbol: string;
      price: number;
      change_24h_percent: number;
      source: string;
      timestamp: number;
    }
  | { type: "kline_update"; symbol: string; interval: string; data: KLineData }
  | { type: "trade_signal"; symbol: string; signal: TradeSignal }
  | { type: "trade_execution"; symbol: string; trade: TradeRecord }
  | { type: "position_update"; symbol: string; data: PositionInfo }
  | {
      type: "risk_alert";
      level: "warning" | "critical";
      message: string;
      symbol?: string;
    }
  | { type: "strategy_signal"; symbol: string; signal: TradeSignal }
  | { type: "batch_update"; updates: WebSocketMessage[] }
  | { type: "error"; message: string }
  | {
      type: "connected";
      connection_id: string;
      symbol: string;
      timestamp: number;
    }
  | { type: "pong"; timestamp: number }
  | {
      type: "simulation_status";
      is_simulation: boolean;
      executor_type: string;
      timestamp: number;
    }
  | {
      type: "ai_decision_blocked";
      data: {
        action: string;
        reason: string;
        current_state: string;
        timestamp: number;
      };
    }
  | {
      type: "mcp_call_start";
      tool_name: string;
      symbol?: string;
      timestamp: number;
    }
  | {
      type: "mcp_call_complete";
      tool_name: string;
      success?: boolean;
      duration_ms?: number;
      result_summary?: string;
      symbol?: string;
      timestamp: number;
    }
  | {
      type: "commander_report";
      timestamp: number;
      active_agents: number;
      total_positions: number;
      daily_pnl: number;
      risk_exposure: number;
      market_sentiment: string;
      ai_thoughts: string;
    };

// ═══════════════════════════════════════════════════════════════
// Store 状态定义
// ═══════════════════════════════════════════════════════════════

interface TradingState {
  // ═══════════════════════════════════════════════════════════
  // 币种管理
  // ═══════════════════════════════════════════════════════════
  symbols: TradingSymbol[];
  activeSymbol: string;
  isLoadingSymbols: boolean;

  // ═══════════════════════════════════════════════════════════
  // 市场数据
  // ═══════════════════════════════════════════════════════════
  currentPrice: PriceInfo | null;
  priceChange24h: number;
  klines: KLineData[];
  currentInterval: string;

  // ═══════════════════════════════════════════════════════════
  // 交易数据
  // ═══════════════════════════════════════════════════════════
  trades: TradeRecord[];
  markers: TradeMarker[];
  signals: TradeSignal[];
  position: PositionInfo | null;

  // ═══════════════════════════════════════════════════════════
  // WebSocket
  // ═══════════════════════════════════════════════════════════
  wsConnection: WebSocket | null;
  wsConnected: boolean;
  wsReconnectCount: number;
  wsError: string | null;

  // ═══════════════════════════════════════════════════════════
  // AI 策略
  // ═══════════════════════════════════════════════════════════
  strategyStatus: "idle" | "running" | "paused";
  strategyConfig: {
    autoTrade: boolean;
    maxPosition: number;
    stopLoss: number;
    takeProfit: number;
  };

  // ═══════════════════════════════════════════════════════════
  // V2 智能系统状态
  // ═══════════════════════════════════════════════════════════
  aiPrediction: {
    successProbability: number;
    expectedPnl: number;
    riskScore: number;
    recommendedAction: string;
  } | null;
  currentStrategy: string | null;
  strategyConfidence: number;

  // ═══════════════════════════════════════════════════════════
  // 交易环境与风控
  // ═══════════════════════════════════════════════════════════
  simulationStatus: { is_simulation: boolean; executor_type: string } | null;
  aiBlockedEvents: Array<{
    action: string;
    reason: string;
    current_state: string;
    timestamp: number;
  }>;
  accountBalance: number | null;
  persistentWarnings: Array<{
    id: string;
    level: string;
    message: string;
    timestamp: number;
  }>;

  // ═══════════════════════════════════════════════════════════
  // 【P3新增】AI 决策追溯与可视化
  // ═══════════════════════════════════════════════════════════
  mcpCalls: MCPCall[];
  commanderReports: CommanderReport[];
  errorEvents: ErrorEvent[];
}

interface TradingActions {
  // ═══════════════════════════════════════════════════════════
  // 币种操作
  // ═══════════════════════════════════════════════════════════
  setSymbols: (symbols: TradingSymbol[]) => void;
  addSymbol: (symbol: string, name?: string) => Promise<void>;
  removeSymbol: (symbol: string) => Promise<void>;
  setActiveSymbol: (symbol: string) => void;

  // ═══════════════════════════════════════════════════════════
  // 数据更新
  // ═══════════════════════════════════════════════════════════
  setCurrentPrice: (price: PriceInfo) => void;
  setKlines: (klines: KLineData[]) => void;
  addKline: (kline: KLineData) => void;
  setCurrentInterval: (interval: string) => void;
  fetchKlines: (symbol: string, interval: string) => Promise<void>;

  // ═══════════════════════════════════════════════════════════
  // 交易数据
  // ═══════════════════════════════════════════════════════════
  setTrades: (trades: TradeRecord[]) => void;
  addTrade: (trade: TradeRecord) => void;
  setMarkers: (markers: TradeMarker[]) => void;
  addMarker: (marker: TradeMarker) => void;
  setSignals: (signals: TradeSignal[]) => void;
  addSignal: (signal: TradeSignal) => void;
  setPosition: (position: PositionInfo | null) => void;

  // ═══════════════════════════════════════════════════════════
  // WebSocket 操作
  // ═══════════════════════════════════════════════════════════
  connect: (symbol: string) => void;
  disconnect: () => void;
  sendMessage: (message: any) => void;
  handleWebSocketMessage: (message: WebSocketMessage) => void;

  // ═══════════════════════════════════════════════════════════
  // 策略操作
  // ═══════════════════════════════════════════════════════════
  setStrategyStatus: (status: "idle" | "running" | "paused") => void;
  updateStrategyConfig: (
    config: Partial<TradingState["strategyConfig"]>,
  ) => void;

  // ═══════════════════════════════════════════════════════════
  // V2 API 操作
  // ═══════════════════════════════════════════════════════════
  fetchTradingStatus: (symbol: string) => Promise<void>;
  fetchTradingSummary: () => Promise<void>;

  // ═══════════════════════════════════════════════════════════
  // 交易环境与风控
  // ═══════════════════════════════════════════════════════════
  setSimulationStatus: (
    status: { is_simulation: boolean; executor_type: string } | null,
  ) => void;
  addAiBlockedEvent: (event: {
    action: string;
    reason: string;
    current_state: string;
    timestamp: number;
  }) => void;
  clearAiBlockedEvents: () => void;
  fetchAccountBalance: () => Promise<void>;
  setAccountBalance: (balance: number | null) => void;
  addPersistentWarning: (warning: {
    id: string;
    level: string;
    message: string;
    timestamp: number;
  }) => void;
  removePersistentWarning: (id: string) => void;
  clearPersistentWarnings: () => void;

  // ═══════════════════════════════════════════════════════════
  // 【P3新增】AI 决策追溯与可视化
  // ═══════════════════════════════════════════════════════════
  addMcpCall: (call: MCPCall) => void;
  clearMcpCalls: () => void;
  addCommanderReport: (report: CommanderReport) => void;
  clearCommanderReports: () => void;
  addErrorEvent: (event: ErrorEvent) => void;
  clearErrorEvents: () => void;

  // ═══════════════════════════════════════════════════════════
  // 重置
  // ═══════════════════════════════════════════════════════════
  reset: () => void;
}

// ═══════════════════════════════════════════════════════════════
// 默认配置
// ═══════════════════════════════════════════════════════════════

const DEFAULT_SYMBOLS: TradingSymbol[] = [
  {
    symbol: "BTC",
    base: "BTC",
    quote: "USDT",
    name: "Bitcoin",
    isCustom: false,
    enabled: true,
  },
  {
    symbol: "ETH",
    base: "ETH",
    quote: "USDT",
    name: "Ethereum",
    isCustom: false,
    enabled: true,
  },
  {
    symbol: "SOL",
    base: "SOL",
    quote: "USDT",
    name: "Solana",
    isCustom: false,
    enabled: true,
  },
];

const INITIAL_STATE: Omit<TradingState, keyof TradingActions> = {
  symbols: DEFAULT_SYMBOLS,
  activeSymbol: "BTC",
  isLoadingSymbols: false,

  currentPrice: null,
  priceChange24h: 0,
  klines: [],
  currentInterval: "1h",

  trades: [],
  markers: [],
  signals: [],
  position: null,

  wsConnection: null,
  wsConnected: false,
  wsReconnectCount: 0,
  wsError: null,

  strategyStatus: "idle",
  strategyConfig: {
    autoTrade: false,
    maxPosition: 1000,
    stopLoss: 3,
    takeProfit: 6,
  },

  // V2 智能系统状态
  aiPrediction: null,
  currentStrategy: null,
  strategyConfidence: 0,

  simulationStatus: null,
  aiBlockedEvents: [],
  accountBalance: null,
  persistentWarnings: [],

  // 【P3新增】AI 决策追溯与可视化
  mcpCalls: [],
  commanderReports: [],
  errorEvents: [],
};

// ═══════════════════════════════════════════════════════════════
// Store 创建
// ═══════════════════════════════════════════════════════════════

export const useTradingStore = create<TradingState & TradingActions>()(
  persist(
    (set, get) => ({
      ...INITIAL_STATE,

      // ═══════════════════════════════════════════════════════
      // 币种操作
      // ═══════════════════════════════════════════════════════
      setSymbols: (symbols) => set({ symbols }),

      addSymbol: async (symbol: string, name?: string) => {
        try {
          const newSymbol = await fetchAPI<TradingSymbol>(
            `/api/trading/symbols?symbol=${symbol}&name=${name || ""}`,
            {
              method: "POST",
            },
          );
          set((state) => ({
            symbols: [...state.symbols, newSymbol],
          }));
        } catch (error) {
          console.error("添加币种失败:", error);
          throw error;
        }
      },

      removeSymbol: async (symbol: string) => {
        try {
          await fetchAPI(`/api/trading/symbols/${symbol}`, {
            method: "DELETE",
          });
          set((state) => ({
            symbols: state.symbols.filter((s) => s.symbol !== symbol),
            // 如果删除的是当前选中的币种，切换到第一个
            activeSymbol:
              state.activeSymbol === symbol
                ? state.symbols.find((s) => s.symbol !== symbol)?.symbol ||
                  "BTC"
                : state.activeSymbol,
          }));
        } catch (error) {
          console.error("删除币种失败:", error);
          throw error;
        }
      },

      setActiveSymbol: (symbol) => {
        const state = get();
        if (state.activeSymbol !== symbol) {
          // 断开旧币种的 WebSocket
          state.disconnect();
          // 更新选中币种，同时重置相关状态
          set({
            activeSymbol: symbol,
            klines: [],
            trades: [],
            markers: [],
            signals: [],
            position: null,
            aiPrediction: null,
            currentStrategy: null,
            strategyConfidence: 0,
            currentPrice: null,
          });
          // 获取初始K线数据
          setTimeout(() => {
            get().fetchKlines?.(symbol, get().currentInterval);
            get().fetchTradingStatus?.(symbol);
            get().connect(symbol);
          }, 100);
        }
      },

      // ═══════════════════════════════════════════════════════
      // 数据更新
      // ═══════════════════════════════════════════════════════
      setCurrentPrice: (price) => {
        set({ currentPrice: price });
      },

      setKlines: (klines) => set({ klines }),

      addKline: (kline) =>
        set((state) => {
          // 检查是否已存在相同时间的K线
          const exists = state.klines.find((k) => k.time === kline.time);
          if (exists) {
            // 更新现有K线
            return {
              klines: state.klines.map((k) =>
                k.time === kline.time ? kline : k,
              ),
            };
          }
          // 添加新K线，保持最大数量限制
          const newKlines = [...state.klines, kline];
          if (newKlines.length > 1000) {
            newKlines.shift();
          }
          return { klines: newKlines };
        }),

      setCurrentInterval: (interval) => {
        set({ currentInterval: interval });
        // 重新获取K线数据
        const state = get();
        if (state.activeSymbol) {
          state.fetchKlines(state.activeSymbol, interval);
        }
      },

      // 获取K线数据 - 统一使用方案C基础API
      fetchKlines: async (symbol: string, interval: string) => {
        try {
          const data = await fetchAPI<KLineData[]>(
            `/api/trading/klines/${symbol}?interval=${interval}&limit=500`,
          );
          set({ klines: data, markers: [] });
        } catch (error) {
          console.error("获取K线数据失败:", error);
        }
      },

      // ═══════════════════════════════════════════════════════
      // 交易数据
      // ═══════════════════════════════════════════════════════
      setTrades: (trades) => set({ trades }),

      addTrade: (trade) =>
        set((state) => ({
          trades: [trade, ...state.trades].slice(0, 100),
        })),

      setMarkers: (markers) => set({ markers }),

      addMarker: (marker) =>
        set((state) => ({
          markers: [...state.markers, marker].slice(0, 200),
        })),

      setSignals: (signals) => set({ signals }),

      addSignal: (signal) =>
        set((state) => ({
          signals: [signal, ...state.signals].slice(0, 50),
        })),

      setPosition: (position) => set({ position }),

      // ═══════════════════════════════════════════════════════
      // 交易状态获取 - 使用方案C trading_mode_api
      // ═══════════════════════════════════════════════════════
      fetchTradingStatus: async (_symbol: string) => {
        try {
          // 通过 trading_mode_api 获取AI交易状态
          const data = await fetchAPI<any>("/api/trading/mode/ai/status", {
            silent: true,
          }).catch(() => null);
          if (data) {
            set({
              currentStrategy: data.current_strategy || null,
              strategyConfidence: data.ai_confidence || 0,
              // 持仓信息需要从其他端点获取或WebSocket推送
            });

            // 更新策略状态
            if (data.is_running) {
              set({ strategyStatus: "running" });
            }
          }

          // 获取World Model预测
          try {
            const predictionData = await fetchAPI<any>(
              `/api/trading/mode/prediction?symbol=${_symbol}&action=buy`,
              { silent: true },
            ).catch(() => null);
            if (predictionData?.available) {
              set({
                aiPrediction: {
                  successProbability: predictionData.success_probability,
                  expectedPnl: predictionData.expected_pnl,
                  riskScore: predictionData.risk_score,
                  recommendedAction: predictionData.recommended_action,
                },
              });
            }
          } catch (predError) {
            console.error("获取预测失败:", predError);
          }
        } catch (error) {
          console.error("获取交易状态失败:", error);
        }
      },

      fetchTradingSummary: async () => {
        try {
          // 通过 trading_mode_api 获取模式状态
          const data = await fetchAPI<any>("/api/trading/mode/status", {
            silent: true,
          }).catch(() => null);
          if (data) {
            console.log("[TradingStore] 交易模式状态:", data);
          }
        } catch (error) {
          console.error("获取交易摘要失败:", error);
        }
      },

      // ═══════════════════════════════════════════════════════
      // WebSocket 操作
      // ═══════════════════════════════════════════════════════
      connect: (symbol: string) => {
        const state = get();

        // 如果已有连接，先断开
        if (state.wsConnection) {
          state.disconnect();
        }

        try {
          // 交易数据 WebSocket URL 统一走 buildWsUrl，不再使用独立 8602 端口
          const token = localStorage.getItem("silicon_token");
          const wsUrl = `${buildWsUrl(`/ws/trading/${symbol}`)}${token ? `?token=${token}` : ""}`;
          const ws = new WebSocket(wsUrl);

          ws.onopen = () => {
            console.log(`[TradingWS] 已连接到 ${symbol}`);
            set({
              wsConnection: ws,
              wsConnected: true,
              wsError: null,
              wsReconnectCount: 0,
            });
          };

          ws.onmessage = (event) => {
            try {
              const message = JSON.parse(event.data);
              get().handleWebSocketMessage(message);
            } catch (error) {
              console.error("[TradingWS] 解析消息失败:", error);
            }
          };

          ws.onclose = () => {
            // 【修复】如果当前 WebSocket 已被替换（如 connect() 主动关闭了旧连接），忽略旧连接的 onclose
            if (get().wsConnection !== ws) {
              return;
            }

            console.log(`[TradingWS] 连接已关闭: ${symbol}`);
            set({ wsConnection: null, wsConnected: false });

            // 自动重连 (最多5次)
            const reconnectCount = get().wsReconnectCount;
            if (reconnectCount < 5) {
              set({ wsReconnectCount: reconnectCount + 1 });
              setTimeout(() => {
                console.log(`[TradingWS] 尝试重连 (${reconnectCount + 1}/5)`);
                get().connect(symbol);
              }, 3000);
            }
          };

          ws.onerror = (error) => {
            console.error("[TradingWS] 连接错误:", error);
            set({ wsError: "WebSocket 连接错误" });
          };
        } catch (error) {
          console.error("[TradingWS] 创建连接失败:", error);
          set({ wsError: "创建 WebSocket 连接失败" });
        }
      },

      disconnect: () => {
        const { wsConnection } = get();
        if (wsConnection) {
          wsConnection.close();
          set({ wsConnection: null, wsConnected: false });
        }
      },

      sendMessage: (message) => {
        const { wsConnection, wsConnected } = get();
        if (wsConnection && wsConnected) {
          wsConnection.send(JSON.stringify(message));
        }
      },

      handleWebSocketMessage: (message) => {
        switch (message.type) {
          case "price_update":
            get().setCurrentPrice(message.data);
            break;

          case "market_data_update":
            get().setCurrentPrice({
              symbol: message.symbol,
              price: message.price,
              change24h: 0,
              change24hPercent: message.change_24h_percent,
              high24h: 0,
              low24h: 0,
              volume24h: 0,
              timestamp: message.timestamp,
            });
            set({ priceChange24h: message.change_24h_percent });
            break;

          case "kline_update":
            get().addKline(message.data);
            break;

          case "trade_signal":
            get().addSignal(message.signal);
            // 同时添加一个标记
            get().addMarker({
              id: `signal_${Date.now()}`,
              time: message.signal.timestamp,
              price: message.signal.price,
              type: message.signal.action,
              source: "ai",
              strategy: message.signal.strategy,
              quantity: message.signal.quantity,
            });
            break;

          case "trade_execution":
            get().addTrade(message.trade);
            get().addMarker({
              id: message.trade.id,
              time: message.trade.timestamp,
              price: message.trade.price,
              type: message.trade.action,
              source: message.trade.source,
              strategy: message.trade.strategy,
              quantity: message.trade.quantity,
              pnl: message.trade.pnl,
            });
            break;

          case "position_update":
            get().setPosition(message.data);
            break;

          case "risk_alert":
            // 风险告警 - 显示给用户
            console.warn(`[TradingAlert] ${message.level}: ${message.message}`);
            // 存储为持久化告警（用户手动关闭）
            set((state) => ({
              persistentWarnings: [
                {
                  id: `warn_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
                  level: message.level,
                  message: message.message,
                  timestamp: Date.now(),
                },
                ...state.persistentWarnings,
              ].slice(0, 20),
            }));
            break;

          case "simulation_status":
            set({
              simulationStatus: {
                is_simulation: message.is_simulation,
                executor_type: message.executor_type,
              },
            });
            break;

          case "ai_decision_blocked":
            set((state) => ({
              aiBlockedEvents: [message.data, ...state.aiBlockedEvents].slice(
                0,
                20,
              ),
            }));
            break;

          case "connected":
            console.log(`[TradingWS] 连接已建立: ${message.connection_id}`);
            break;

          case "pong":
            // 心跳响应
            break;

          case "strategy_signal":
            get().addSignal(message.signal);
            break;

          case "batch_update":
            if (message.updates && Array.isArray(message.updates)) {
              message.updates.forEach((update) => {
                get().handleWebSocketMessage(update);
              });
            }
            break;

          // 【P3新增】MCP 调用事件
          case "mcp_call_start":
            get().addMcpCall({
              tool_name: message.tool_name,
              symbol: message.symbol,
              timestamp: message.timestamp || Date.now(),
            });
            break;

          case "mcp_call_complete":
            get().addMcpCall({
              tool_name: message.tool_name,
              symbol: message.symbol,
              success: message.success,
              duration_ms: message.duration_ms,
              result_summary: message.result_summary,
              timestamp: message.timestamp || Date.now(),
            });
            // 如果失败，记录为错误事件
            if (message.success === false) {
              get().addErrorEvent({
                id: `mcp_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
                type: "mcp_call_failed",
                message: `MCP ${message.tool_name} 调用失败: ${message.result_summary || "未知错误"}`,
                timestamp: Date.now(),
                details: message,
              });
            }
            break;

          // 【P3新增】指挥官报告
          case "commander_report":
            get().addCommanderReport({
              timestamp: message.timestamp,
              active_agents: message.active_agents,
              total_positions: message.total_positions,
              daily_pnl: message.daily_pnl,
              risk_exposure: message.risk_exposure,
              market_sentiment: message.market_sentiment,
              ai_thoughts: message.ai_thoughts,
            });
            break;

          case "error":
            set({ wsError: message.message || "WebSocket 错误" });
            get().addErrorEvent({
              id: `ws_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
              type: "websocket_error",
              message: message.message || "WebSocket 错误",
              timestamp: Date.now(),
            });
            break;

          default:
            console.log("[TradingWS] 未知消息类型:", message);
        }
      },

      // ═══════════════════════════════════════════════════════
      // 策略操作
      // ═══════════════════════════════════════════════════════
      setStrategyStatus: (status) => set({ strategyStatus: status }),

      updateStrategyConfig: (config) =>
        set((state) => ({
          strategyConfig: { ...state.strategyConfig, ...config },
        })),

      // ═══════════════════════════════════════════════════════
      // 交易环境与风控
      // ═══════════════════════════════════════════════════════
      setSimulationStatus: (status) => set({ simulationStatus: status }),

      addAiBlockedEvent: (event) =>
        set((state) => ({
          aiBlockedEvents: [event, ...state.aiBlockedEvents].slice(0, 20),
        })),

      clearAiBlockedEvents: () => set({ aiBlockedEvents: [] }),

      fetchAccountBalance: async () => {
        try {
          const data = await fetchAPI<any>(
            "/api/trading/mode/manual/positions",
            { silent: true },
          ).catch(() => null);
          if (data && typeof data.equity === "number") {
            set({ accountBalance: data.equity });
          } else if (
            data &&
            Array.isArray(data.positions) &&
            data.positions.length > 0
          ) {
            // 后端返回positions数组，计算权益
            const equity = data.positions.reduce(
              (sum: number, p: any) => sum + (p.unrealized_pnl || 0),
              0,
            );
            set({ accountBalance: equity });
          }
        } catch (error) {
          console.error("获取账户余额失败:", error);
        }
      },

      setAccountBalance: (balance) => set({ accountBalance: balance }),

      addPersistentWarning: (warning) =>
        set((state) => ({
          persistentWarnings: [warning, ...state.persistentWarnings].slice(
            0,
            20,
          ),
        })),

      removePersistentWarning: (id) =>
        set((state) => ({
          persistentWarnings: state.persistentWarnings.filter(
            (w) => w.id !== id,
          ),
        })),

      clearPersistentWarnings: () => set({ persistentWarnings: [] }),

      // ═══════════════════════════════════════════════════════
      // 【P3新增】AI 决策追溯与可视化
      // ═══════════════════════════════════════════════════════
      addMcpCall: (call) =>
        set((state) => ({
          mcpCalls: [call, ...state.mcpCalls].slice(0, 100),
        })),

      clearMcpCalls: () => set({ mcpCalls: [] }),

      addCommanderReport: (report) =>
        set((state) => ({
          commanderReports: [report, ...state.commanderReports].slice(0, 50),
        })),

      clearCommanderReports: () => set({ commanderReports: [] }),

      addErrorEvent: (event) =>
        set((state) => ({
          errorEvents: [event, ...state.errorEvents].slice(0, 50),
        })),

      clearErrorEvents: () => set({ errorEvents: [] }),

      // ═══════════════════════════════════════════════════════
      // 重置
      // ═══════════════════════════════════════════════════════
      reset: () => {
        get().disconnect();
        set(INITIAL_STATE);
      },
    }),
    {
      name: "trading-storage",
      partialize: (state) => ({
        symbols: state.symbols,
        activeSymbol: state.activeSymbol,
        currentInterval: state.currentInterval,
        strategyConfig: state.strategyConfig,
      }),
    },
  ),
);

// ═══════════════════════════════════════════════════════════════
// 辅助 Hooks
// ═══════════════════════════════════════════════════════════════

export function useActiveSymbol() {
  return useTradingStore((state) => ({
    symbol: state.activeSymbol,
    setSymbol: state.setActiveSymbol,
  }));
}

export function useTradingData() {
  return useTradingStore((state) => ({
    price: state.currentPrice,
    klines: state.klines,
    trades: state.trades,
    markers: state.markers,
    signals: state.signals,
    position: state.position,
  }));
}

export function useWebSocketStatus() {
  return useTradingStore((state) => ({
    connected: state.wsConnected,
    error: state.wsError,
    connect: state.connect,
    disconnect: state.disconnect,
  }));
}

export default useTradingStore;
