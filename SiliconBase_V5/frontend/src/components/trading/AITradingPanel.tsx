/**
 * AITradingPanel.tsx
 * AI辅助交易面板组件
 *
 * 功能:
 * - 显示AI决策过程（reasoning）
 * - 显示置信度和建议操作
 * - 人工干预按钮（确认/拒绝/暂停）
 * - 实时接收AI决策推送
 */

import React, { useState, useEffect, useCallback, useRef } from "react";
import {
  Brain,
  Play,
  Square,
  Pause,
  RotateCcw,
  CheckCircle,
  XCircle,
  AlertTriangle,
  TrendingUp,
  TrendingDown,
  Minus,
  Activity,
  MessageSquare,
  Clock,
} from "lucide-react";
import { tradingModeApi } from "../../utils/api/tradingMode";
import {
  TradingThoughtFlow,
  useTradingThoughtFlow,
} from "./TradingThoughtFlow";
import { useNotifications } from "../../hooks/useNotifications";
import { useTradingStore } from "../../stores/tradingStore";
import { buildWsUrl } from "../../config/api";

// 类型定义
interface AIDecision {
  id: string;
  timestamp: number;
  symbol: string;
  action: "buy" | "sell" | "hold";
  confidence: number;
  reasoning: string;
  suggested_size?: number;
  executed: boolean;
  user_approved?: boolean;
}

interface AITradingStatus {
  is_running: boolean;
  mode: "idle" | "ai" | "paused" | "error";
  symbols: string[];
  decision_count: number;
  last_decision_time?: number;
  error_message?: string;
}

// 倒计时hook
function useCountdown(expiresAt: number | undefined) {
  const [remaining, setRemaining] = useState<number>(0);
  useEffect(() => {
    if (!expiresAt) return;
    const update = () => {
      const r = Math.max(0, Math.ceil((expiresAt - Date.now()) / 1000));
      setRemaining(r);
    };
    update();
    const t = setInterval(update, 1000);
    return () => clearInterval(t);
  }, [expiresAt]);
  return remaining;
}

// 决策卡片组件（避免在map中调用hook）
const DecisionCard: React.FC<{
  decision: AIDecision & { expires_at?: number; showDetails?: boolean };
  onToggleDetails: () => void;
  onApprove: () => void;
  onReject: () => void;
  configAutoExecute: boolean;
  statusMode: string;
  simulationStatus: { is_simulation: boolean } | null;
}> = ({
  decision,
  onToggleDetails,
  onApprove,
  onReject,
  configAutoExecute,
  statusMode,
  simulationStatus,
}) => {
  const remaining = useCountdown(decision.expires_at);
  const isExpired = decision.expires_at ? remaining <= 0 : false;

  const getActionIcon = (action: string) => {
    switch (action) {
      case "buy":
        return <TrendingUp className="w-5 h-5 text-green-400" />;
      case "sell":
        return <TrendingDown className="w-5 h-5 text-red-400" />;
      default:
        return <Minus className="w-5 h-5 text-gray-400" />;
    }
  };
  const getActionText = (action: string) => {
    switch (action) {
      case "buy":
        return "买入";
      case "sell":
        return "卖出";
      default:
        return "持仓";
    }
  };
  const getConfidenceColor = (confidence: number) => {
    if (confidence >= 0.8) return "text-green-400";
    if (confidence >= 0.6) return "text-yellow-400";
    return "text-red-400";
  };

  return (
    <div className="p-4 hover:bg-gray-700/50 transition-colors">
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <div className="flex items-center gap-3 mb-2 flex-wrap">
            {getActionIcon(decision.action)}
            <span className="font-semibold text-white">
              {getActionText(decision.action)} {decision.symbol}
            </span>
            <span
              className={`text-sm ${getConfidenceColor(decision.confidence)}`}
            >
              置信度: {(decision.confidence * 100).toFixed(1)}%
            </span>
            <span className="text-xs text-gray-500">
              {new Date(decision.timestamp).toLocaleTimeString()}
            </span>
            {!decision.executed && decision.expires_at && (
              <span
                className={`text-xs px-2 py-0.5 rounded ${isExpired ? "bg-red-500/20 text-red-400" : "bg-yellow-500/20 text-yellow-400"}`}
              >
                {isExpired
                  ? "已超时"
                  : `剩余 ${Math.floor(remaining / 60)}:${(remaining % 60).toString().padStart(2, "0")}`}
              </span>
            )}
          </div>
          <div className="bg-gray-900 rounded-lg p-3 mb-3">
            <p className="text-sm text-gray-300 whitespace-pre-wrap">
              {decision.reasoning}
            </p>
          </div>
          {decision.suggested_size && (
            <p className="text-sm text-gray-400 mb-2">
              建议仓位: {decision.suggested_size}
            </p>
          )}
          <button
            onClick={onToggleDetails}
            className="text-xs text-purple-400 hover:text-purple-300 mb-2"
          >
            {decision.showDetails ? "收起详情" : "查看详情"}
          </button>
          {decision.showDetails && (
            <div className="bg-gray-900/50 rounded-lg p-3 mb-3 text-sm space-y-1">
              <div className="flex justify-between">
                <span className="text-gray-500">币种:</span>
                <span className="text-white">{decision.symbol}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">动作:</span>
                <span className="text-white">
                  {getActionText(decision.action)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">置信度:</span>
                <span className="text-white">
                  {(decision.confidence * 100).toFixed(1)}%
                </span>
              </div>
              {decision.suggested_size && (
                <div className="flex justify-between">
                  <span className="text-gray-500">建议数量:</span>
                  <span className="text-white">{decision.suggested_size}</span>
                </div>
              )}
              <div className="flex justify-between">
                <span className="text-gray-500">模式:</span>
                <span className="text-white">
                  {simulationStatus?.is_simulation !== false
                    ? "模拟盘"
                    : "实盘"}
                </span>
              </div>
            </div>
          )}
          {decision.executed ? (
            <div
              className={`flex items-center gap-1.5 text-sm ${decision.user_approved ? "text-green-400" : "text-red-400"}`}
            >
              {decision.user_approved ? (
                <>
                  <CheckCircle className="w-4 h-4" />
                  <span>已执行</span>
                </>
              ) : (
                <>
                  <XCircle className="w-4 h-4" />
                  <span>已拒绝</span>
                </>
              )}
            </div>
          ) : (
            !configAutoExecute &&
            statusMode === "ai" &&
            !isExpired && (
              <div className="flex gap-2">
                <button
                  onClick={onApprove}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600 hover:bg-green-500 rounded-lg text-sm text-white transition-colors"
                >
                  <CheckCircle className="w-4 h-4" /> 确认执行
                </button>
                <button
                  onClick={onReject}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-red-600 hover:bg-red-500 rounded-lg text-sm text-white transition-colors"
                >
                  <XCircle className="w-4 h-4" /> 拒绝
                </button>
              </div>
            )
          )}
        </div>
      </div>
    </div>
  );
};

export const AITradingPanel: React.FC = () => {
  const [status, setStatus] = useState<AITradingStatus>({
    is_running: false,
    mode: "idle",
    symbols: ["BTC", "ETH"],
    decision_count: 0,
  });
  const [decisions, setDecisions] = useState<
    (AIDecision & { expires_at?: number; showDetails?: boolean })[]
  >([]);
  const [isLoading, setIsLoading] = useState(false);
  const [config, setConfig] = useState({
    symbols: ["BTC", "ETH"],
    ai_check_interval: 4,
    risk_profile: "moderate" as "conservative" | "moderate" | "aggressive",
    auto_execute: false,
  });
  const wsRef = useRef<WebSocket | null>(null);
  const { showNotification } = useNotifications();
  const { aiBlockedEvents, clearAiBlockedEvents, simulationStatus } =
    useTradingStore();

  // 思维流管理
  const {
    steps,
    isActive: isThinking,
    addStep,
    startFlow,
    stopFlow,
  } = useTradingThoughtFlow();

  // 获取状态
  const fetchStatus = useCallback(async () => {
    try {
      const response = await tradingModeApi.getAITradingStatus();
      setStatus(response);
    } catch (error) {
      console.error("获取AI交易状态失败:", error);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  // WebSocket连接
  useEffect(() => {
    if (!status.is_running) {
      wsRef.current?.close();
      return;
    }

    // 交易模式 WebSocket 统一使用 buildWsUrl，不再硬编码 localhost:8600
    const token = localStorage.getItem("silicon_token");
    const wsUrl = `${buildWsUrl("/api/trading/mode/ws/ai")}${token ? `?token=${token}` : ""}`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log("AI交易WebSocket已连接");
    };

    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        if (message.type === "ai_decision" && message.data) {
          const newDecision: AIDecision & { expires_at?: number } = {
            id: `decision_${Date.now()}`,
            timestamp: message.timestamp,
            ...message.data,
            executed: false,
            expires_at: Date.now() + 300_000, // 5分钟倒计时
          };
          setDecisions((prev) => [newDecision, ...prev].slice(0, 50)); // 保留最近50条

          // 添加思维步骤
          addStep({
            type: "decision",
            content: `AI决策: ${newDecision.action === "buy" ? "买入" : newDecision.action === "sell" ? "卖出" : "持仓"} ${newDecision.symbol}，置信度 ${(newDecision.confidence * 100).toFixed(1)}%`,
            details: { reasoning: newDecision.reasoning },
          });
        } else if (message.type === "market_analysis" && message.data) {
          addStep({
            type: "market_analysis",
            content: message.data.summary || "市场分析中...",
            details: message.data.indicators,
          });
        } else if (message.type === "risk_check" && message.data) {
          addStep({
            type: "risk_assessment",
            content: `风险评估: ${message.data.risk_level || "正常"}`,
            details: { risk_score: message.data.risk_score },
          });
        } else if (message.type === "ai_decision_blocked" && message.data) {
          addStep({
            type: "interrupted",
            content: `AI决策被拦截: ${message.data.action}，原因: ${message.data.reason === "visual_state_mismatch" ? "页面状态不匹配" : message.data.reason}`,
            details: { current_state: message.data.current_state },
          });
        }
      } catch (error) {
        console.error("解析WebSocket消息失败:", error);
      }
    };

    ws.onerror = (event) => {
      console.error("AI交易WebSocket错误事件:", event.type);
    };

    ws.onclose = () => {
      console.log("AI交易WebSocket已关闭");
    };

    wsRef.current = ws;

    return () => {
      ws.close();
    };
  }, [status.is_running]);

  const handleStart = async () => {
    setIsLoading(true);
    try {
      const response = await tradingModeApi.startAITrading(config);
      setStatus({
        is_running: true,
        mode: "ai",
        symbols: config.symbols,
        decision_count: response.decision_count || 0,
      });
      // 启动思维流
      startFlow();
      addStep({
        type: "market_analysis",
        content: "AI指挥官启动，开始市场分析...",
      });
    } catch (error) {
      showNotification({
        type: "error",
        title: "启动失败",
        message: (error as Error).message,
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleStop = async () => {
    setIsLoading(true);
    try {
      await tradingModeApi.stopAITrading();
      setStatus((prev) => ({ ...prev, is_running: false, mode: "idle" }));
      // 停止思维流
      stopFlow();
      addStep({
        type: "execution",
        content: "AI指挥官已停止",
      });
    } catch (error) {
      showNotification({
        type: "error",
        title: "停止失败",
        message: (error as Error).message,
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handlePause = async () => {
    setIsLoading(true);
    try {
      await tradingModeApi.pauseAITrading();
      setStatus((prev) => ({ ...prev, mode: "paused" }));
    } catch (error) {
      showNotification({
        type: "error",
        title: "暂停失败",
        message: (error as Error).message,
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleResume = async () => {
    setIsLoading(true);
    try {
      await tradingModeApi.resumeAITrading();
      setStatus((prev) => ({ ...prev, mode: "ai" }));
    } catch (error) {
      showNotification({
        type: "error",
        title: "恢复失败",
        message: (error as Error).message,
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleApproveDecision = async (decisionId: string) => {
    try {
      await tradingModeApi.interveneAI({
        action: "approve",
        reason: "用户确认执行",
      });
      setDecisions((prev) =>
        prev.map((d) =>
          d.id === decisionId
            ? { ...d, user_approved: true, executed: true }
            : d,
        ),
      );
    } catch (error) {
      showNotification({
        type: "error",
        title: "确认执行失败",
        message: (error as Error).message,
      });
    }
  };

  const handleRejectDecision = async (decisionId: string) => {
    try {
      await tradingModeApi.interveneAI({
        action: "close_all",
        reason: "用户拒绝执行",
      });
      setDecisions((prev) =>
        prev.map((d) =>
          d.id === decisionId ? { ...d, user_approved: false } : d,
        ),
      );
    } catch (error) {
      showNotification({
        type: "error",
        title: "拒绝执行失败",
        message: (error as Error).message,
      });
    }
  };

  return (
    <div className="space-y-6">
      {/* 状态卡片 */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Brain className="w-5 h-5 text-purple-400" />
            <span className="text-gray-400 text-sm">AI状态</span>
          </div>
          <div className="flex items-center gap-2">
            <div
              className={`w-2.5 h-2.5 rounded-full ${
                status.mode === "ai"
                  ? "bg-green-500 animate-pulse"
                  : status.mode === "paused"
                    ? "bg-yellow-500"
                    : status.mode === "error"
                      ? "bg-red-500"
                      : "bg-gray-500"
              }`}
            />
            <span
              className={`text-lg font-semibold ${
                status.mode === "ai"
                  ? "text-green-400"
                  : status.mode === "paused"
                    ? "text-yellow-400"
                    : status.mode === "error"
                      ? "text-red-400"
                      : "text-gray-400"
              }`}
            >
              {status.mode === "ai"
                ? "运行中"
                : status.mode === "paused"
                  ? "已暂停"
                  : status.mode === "error"
                    ? "错误"
                    : "空闲"}
            </span>
          </div>
        </div>

        <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Activity className="w-5 h-5 text-blue-400" />
            <span className="text-gray-400 text-sm">决策次数</span>
          </div>
          <p className="text-lg font-semibold text-white">
            {status.decision_count}
          </p>
        </div>

        <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Clock className="w-5 h-5 text-yellow-400" />
            <span className="text-gray-400 text-sm">最后决策</span>
          </div>
          <p className="text-lg font-semibold text-white">
            {status.last_decision_time
              ? new Date(status.last_decision_time).toLocaleTimeString()
              : "--"}
          </p>
        </div>

        <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
          <div className="flex items-center gap-2 mb-2">
            <TrendingUp className="w-5 h-5 text-green-400" />
            <span className="text-gray-400 text-sm">监控币种</span>
          </div>
          <p className="text-lg font-semibold text-white">
            {status.symbols.join(", ")}
          </p>
        </div>
      </div>

      {/* 控制按钮 */}
      <div className="flex flex-wrap gap-4">
        {!status.is_running ? (
          <button
            onClick={handleStart}
            disabled={isLoading}
            className="flex items-center gap-2 px-6 py-3 bg-purple-600 hover:bg-purple-500 disabled:bg-gray-700 disabled:cursor-not-allowed rounded-xl text-white font-medium transition-colors"
          >
            <Play className="w-5 h-5" />
            {isLoading ? "启动中..." : "启动AI指挥官"}
          </button>
        ) : (
          <>
            <button
              onClick={handleStop}
              disabled={isLoading}
              className="flex items-center gap-2 px-6 py-3 bg-red-600 hover:bg-red-500 disabled:bg-gray-700 disabled:cursor-not-allowed rounded-xl text-white font-medium transition-colors"
            >
              <Square className="w-5 h-5" />
              停止
            </button>

            {status.mode === "ai" ? (
              <button
                onClick={handlePause}
                className="flex items-center gap-2 px-6 py-3 bg-yellow-600 hover:bg-yellow-500 rounded-xl text-white font-medium transition-colors"
              >
                <Pause className="w-5 h-5" />
                暂停AI
              </button>
            ) : (
              <button
                onClick={handleResume}
                className="flex items-center gap-2 px-6 py-3 bg-green-600 hover:bg-green-500 rounded-xl text-white font-medium transition-colors"
              >
                <RotateCcw className="w-5 h-5" />
                恢复AI
              </button>
            )}
          </>
        )}
      </div>

      {/* 配置面板 */}
      {!status.is_running && (
        <div className="bg-gray-800 rounded-xl border border-gray-700 p-6">
          <h3 className="text-lg font-semibold text-white mb-4">AI配置</h3>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-gray-400 mb-2">
                监控币种
              </label>
              <input
                type="text"
                value={config.symbols.join(", ")}
                onChange={(e) =>
                  setConfig({
                    ...config,
                    symbols: e.target.value.split(",").map((s) => s.trim()),
                  })
                }
                className="w-full px-4 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white focus:border-purple-500 focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-sm text-gray-400 mb-2">
                AI检查间隔
              </label>
              <select
                value={config.ai_check_interval}
                onChange={(e) =>
                  setConfig({
                    ...config,
                    ai_check_interval: parseInt(e.target.value),
                  })
                }
                className="w-full px-4 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white focus:border-purple-500 focus:outline-none"
              >
                <option value={2}>2周期</option>
                <option value={4}>4周期</option>
                <option value={6}>6周期</option>
                <option value={8}>8周期</option>
              </select>
            </div>

            <div>
              <label className="block text-sm text-gray-400 mb-2">
                风险偏好
              </label>
              <select
                value={config.risk_profile}
                onChange={(e) =>
                  setConfig({ ...config, risk_profile: e.target.value as any })
                }
                className="w-full px-4 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white focus:border-purple-500 focus:outline-none"
              >
                <option value="conservative">保守</option>
                <option value="moderate">稳健</option>
                <option value="aggressive">激进</option>
              </select>
            </div>

            <div>
              <label className="block text-sm text-gray-400 mb-2">
                执行模式
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={config.auto_execute}
                  onChange={(e) =>
                    setConfig({ ...config, auto_execute: e.target.checked })
                  }
                  className="w-4 h-4 rounded border-gray-600 bg-gray-700 text-purple-600"
                />
                <span className="text-gray-300">
                  自动执行AI决策（无需人工确认）
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 思维流 */}
      {status.is_running && (
        <TradingThoughtFlow
          steps={steps}
          isActive={isThinking}
          maxHeight="300px"
        />
      )}

      {/* AI拦截事件 */}
      {aiBlockedEvents.length > 0 && (
        <div className="bg-orange-900/20 border border-orange-500/30 rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-orange-400 flex items-center gap-2">
              <AlertTriangle className="w-4 h-4" />
              AI决策拦截记录 ({aiBlockedEvents.length})
            </h3>
            <button
              onClick={clearAiBlockedEvents}
              className="text-xs text-orange-400/70 hover:text-orange-400"
            >
              清除全部
            </button>
          </div>
          <div className="space-y-2 max-h-40 overflow-y-auto">
            {aiBlockedEvents.map((evt, idx) => (
              <div
                key={idx}
                className="bg-orange-950/30 rounded-lg p-2 text-xs"
              >
                <div className="flex items-center gap-2 text-orange-300">
                  <Clock className="w-3 h-3" />
                  {new Date(evt.timestamp * 1000).toLocaleTimeString()}
                </div>
                <p className="text-orange-200/80 mt-1">
                  动作: {evt.action} | 原因:{" "}
                  {evt.reason === "visual_state_mismatch"
                    ? "页面状态不匹配"
                    : evt.reason}{" "}
                  | 当前页面: {evt.current_state}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 决策列表 */}
      <div className="bg-gray-800 rounded-xl border border-gray-700 overflow-hidden">
        <div className="p-4 border-b border-gray-700">
          <h3 className="text-lg font-semibold text-white flex items-center gap-2">
            <MessageSquare className="w-5 h-5 text-purple-400" />
            AI决策记录
          </h3>
        </div>

        <div className="divide-y divide-gray-700 max-h-96 overflow-y-auto">
          {decisions.length === 0 ? (
            <div className="p-8 text-center text-gray-500">
              <Brain className="w-12 h-12 mx-auto mb-3 opacity-50" />
              <p>暂无AI决策记录</p>
              <p className="text-sm mt-1">启动AI指挥官后将显示实时决策</p>
            </div>
          ) : (
            decisions.map((decision) => (
              <DecisionCard
                key={decision.id}
                decision={decision}
                onToggleDetails={() =>
                  setDecisions((prev) =>
                    prev.map((d) =>
                      d.id === decision.id
                        ? { ...d, showDetails: !d.showDetails }
                        : d,
                    ),
                  )
                }
                onApprove={() => handleApproveDecision(decision.id)}
                onReject={() => handleRejectDecision(decision.id)}
                configAutoExecute={config.auto_execute}
                statusMode={status.mode}
                simulationStatus={simulationStatus}
              />
            ))
          )}
        </div>
      </div>

      {/* 说明 */}
      <div className="bg-purple-500/10 border border-purple-500/30 rounded-xl p-4 flex items-start gap-3">
        <AlertTriangle className="w-5 h-5 text-purple-400 flex-shrink-0 mt-0.5" />
        <div>
          <h4 className="text-sm font-medium text-purple-400 mb-1">
            AI交易说明
          </h4>
          <p className="text-sm text-gray-400">
            AI指挥官根据市场状态动态生成交易策略，不依赖固化策略库。
            {config.auto_execute
              ? "当前为自动执行模式，AI决策将直接执行。"
              : "当前为人工确认模式，每笔交易需要您确认后才执行。"}
            AI决策可能较慢，请耐心等待。
          </p>
        </div>
      </div>
    </div>
  );
};

export default AITradingPanel;
