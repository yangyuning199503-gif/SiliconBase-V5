/**
 * 交易模式 API 服务
 * 提供AI交易、自动交易、手动交易的控制接口
 */

import { fetchAPI, APIError } from './core';

const logger = {
  error: (...args: any[]) => console.error('[TradingModeAPI]', ...args),
  info: (...args: any[]) => console.info('[TradingModeAPI]', ...args),
};

export interface AITradingConfig {
  symbols: string[];
  ai_check_interval: number;
  risk_profile: 'conservative' | 'moderate' | 'aggressive';
  auto_execute: boolean;
}

export interface AITradingStatus {
  success: boolean;
  is_running: boolean;
  mode: 'idle' | 'ai' | 'paused' | 'error';
  symbols: string[];
  decision_count: number;
  last_decision_time?: number;
  error_message?: string;
}

export interface AIInterveneRequest {
  action: 'pause' | 'resume' | 'close_all' | 'approve' | 'reject';
  reason: string;
}

// ============================================
// 全自动量化交易接口
// ============================================

export interface AutoTradingConfig {
  strategy: string;
  symbols: string[];
  leverage: number;
  demo_mode: boolean;
}

export interface AutoTradingStatus {
  success: boolean;
  is_running: boolean;
  pid?: number;
  runtime?: number;
  state?: {
    strategy?: string;
    [key: string]: any;
  };
  report?: {
    content_preview?: string;
    [key: string]: any;
  };
}

// ============================================
// 手动交易接口
// ============================================

export interface ManualPosition {
  symbol: string;
  side: 'buy' | 'sell';
  quantity: number;
  entry_price: number;
  mark_price: number;
  unrealized_pnl: number;
  leverage: number;
}

export interface ManualOrderRequest {
  symbol: string;
  side: 'buy' | 'sell';
  type: 'market' | 'limit';
  price?: number;
  amount: number;
  leverage: number;
}

export interface ManualOrderResponse {
  success: boolean;
  order_id?: string;
  status?: string;
  executed_price?: number;
  message?: string;
}

export interface ClosePositionRequest {
  symbol: string;
  side: 'long' | 'short';
  quantity?: number;
}

export interface ModeStatus {
  success: boolean;
  mode: 'auto' | 'ai' | 'manual';
  is_active: boolean;
  status_message?: string;
  auto_pid?: number;
  auto_runtime?: number;
  auto_strategy?: string;
  decision_count?: number;
}

export interface PendingDecision {
  pending_id: string;
  symbol: string;
  action: string;
  direction?: string;
  size?: number;
  leverage?: number;
  reasoning: string;
  confidence: number;
  timestamp: number;
}

export interface PendingDecisionsResponse {
  success: boolean;
  count: number;
  decisions: PendingDecision[];
}

export interface TradingPrediction {
  success: boolean;
  success_probability: number;
  expected_pnl: number;
  risk_score: number;
  recommended_action: string;
  reasoning: string;
  available: boolean;
}

export interface AutoTradingSchedulerStatus {
  status: string;
  current_session?: Record<string, any>;
  stats: Record<string, any>;
  circuit_breaker: Record<string, any>;
  config: Record<string, any>;
}

export interface ModeSwitchRequest {
  mode: 'auto' | 'ai' | 'manual';
}

export interface TradingSymbol {
  symbol: string;
  base_asset: string;
  quote_asset: string;
  enabled: boolean;
}

export interface PriceInfo {
  symbol: string;
  price: number;
  timestamp: number;
}

export interface KLineData {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface TradeRecord {
  id: string;
  symbol: string;
  side: 'buy' | 'sell';
  price: number;
  amount: number;
  timestamp: number;
}

export interface PositionInfo {
  symbol: string;
  side: 'long' | 'short';
  size: number;
  entry_price: number;
  mark_price: number;
  unrealized_pnl: number;
  leverage: number;
}

export interface AccountInfo {
  total_equity: number;
  available_balance: number;
  margin_balance: number;
  unrealized_pnl: number;
}

export interface AutoTradingSession {
  id: string;
  started_at: string;
  ended_at?: string;
  status: string;
  pnl?: number;
}

export const tradingModeApi = {
  // ============================================
  // 模式切换
  // ============================================

  async switchMode(mode: ModeSwitchRequest['mode']): Promise<ModeStatus> {
    try {
      const response = await fetchAPI<ModeStatus>('/api/trading/mode/switch', {
        method: 'POST',
        body: { mode },
      });
      return response || { success: false, mode, is_active: false };
    } catch (error) {
      logger.error('切换交易模式失败:', error);
      throw error;
    }
  },

  // ============================================
  // AI交易 API
  // ============================================
  
  async getModeStatus(): Promise<ModeStatus> {
    try {
      const response = await fetchAPI<ModeStatus>('/api/trading/mode/status');
      return response || { success: false, mode: 'manual', is_active: false };
    } catch (error) {
      logger.error('获取交易模式状态失败:', error);
      throw error;
    }
  },

  async getAITradingStatus(): Promise<AITradingStatus> {
    try {
      const response = await fetchAPI<AITradingStatus>('/api/trading/mode/ai/status');
      return response || { success: false, is_running: false, mode: 'idle', symbols: [], decision_count: 0 };
    } catch (error) {
      logger.error('获取AI交易状态失败:', error);
      throw error;
    }
  },

  async startAITrading(config: AITradingConfig): Promise<AITradingStatus> {
    try {
      logger.info('启动AI交易:', config);
      const response = await fetchAPI<AITradingStatus>('/api/trading/mode/ai/start', {
        method: 'POST',
        body: config,
      });
      
      if (!response || !response.success) {
        throw new APIError(response?.error_message || '启动AI交易失败', 0, response);
      }
      
      return response;
    } catch (error) {
      logger.error('启动AI交易失败:', error);
      throw error;
    }
  },

  async stopAITrading(): Promise<AITradingStatus> {
    try {
      logger.info('停止AI交易');
      const response = await fetchAPI<AITradingStatus>('/api/trading/mode/ai/stop', {
        method: 'POST',
      });
      
      if (!response || !response.success) {
        throw new APIError('停止AI交易失败', 0, response);
      }
      
      return response;
    } catch (error) {
      logger.error('停止AI交易失败:', error);
      throw error;
    }
  },

  async pauseAITrading(): Promise<AITradingStatus> {
    try {
      logger.info('暂停AI交易');
      const response = await fetchAPI<AITradingStatus>('/api/trading/mode/ai/pause', {
        method: 'POST',
      });
      
      if (!response || !response.success) {
        throw new APIError('暂停AI交易失败', 0, response);
      }
      
      return response;
    } catch (error) {
      logger.error('暂停AI交易失败:', error);
      throw error;
    }
  },

  async resumeAITrading(): Promise<AITradingStatus> {
    try {
      logger.info('恢复AI交易');
      const response = await fetchAPI<AITradingStatus>('/api/trading/mode/ai/resume', {
        method: 'POST',
      });
      
      if (!response || !response.success) {
        throw new APIError('恢复AI交易失败', 0, response);
      }
      
      return response;
    } catch (error) {
      logger.error('恢复AI交易失败:', error);
      throw error;
    }
  },

  async interveneAI(request: AIInterveneRequest): Promise<AITradingStatus> {
    try {
      logger.info('干预AI交易:', request);
      const response = await fetchAPI<AITradingStatus>('/api/trading/mode/ai/intervene', {
        method: 'POST',
        body: request,
      });
      
      if (!response || !response.success) {
        throw new APIError('干预AI交易失败', 0, response);
      }
      
      return response;
    } catch (error) {
      logger.error('干预AI交易失败:', error);
      throw error;
    }
  },

  async getPendingDecisions(): Promise<PendingDecisionsResponse> {
    try {
      const response = await fetchAPI<PendingDecisionsResponse>('/api/trading/mode/ai/pending');
      return response || { success: true, count: 0, decisions: [] };
    } catch (error) {
      logger.error('获取待确认决策列表失败:', error);
      throw error;
    }
  },

  async getTradingPrediction(symbol: string, action: string = 'buy'): Promise<TradingPrediction> {
    try {
      const response = await fetchAPI<TradingPrediction>(`/api/trading/mode/prediction?symbol=${symbol}&action=${action}`);
      return response || { success: true, success_probability: 0.5, expected_pnl: 0, risk_score: 0.5, recommended_action: 'hold', reasoning: '', available: false };
    } catch (error) {
      logger.error('获取交易预测失败:', error);
      throw error;
    }
  },

  async confirmAIDecision(pendingId: string): Promise<AITradingStatus> {
    try {
      logger.info('确认AI决策:', pendingId);
      const response = await fetchAPI<AITradingStatus>('/api/trading/mode/ai/confirm', {
        method: 'POST',
        body: { pending_id: pendingId },
      });
      return response || { success: false, is_running: false, mode: 'idle', symbols: [], decision_count: 0 };
    } catch (error) {
      logger.error('确认AI决策失败:', error);
      throw error;
    }
  },

  async rejectAIDecision(pendingId: string, reason?: string): Promise<AITradingStatus> {
    try {
      logger.info('拒绝AI决策:', pendingId);
      const response = await fetchAPI<AITradingStatus>('/api/trading/mode/ai/reject', {
        method: 'POST',
        body: { pending_id: pendingId, reason },
      });
      return response || { success: false, is_running: false, mode: 'idle', symbols: [], decision_count: 0 };
    } catch (error) {
      logger.error('拒绝AI决策失败:', error);
      throw error;
    }
  },

  // ============================================
  // 全自动量化 API
  // ============================================
  
  async getAutoTradingStatus(): Promise<AutoTradingStatus> {
    try {
      const response = await fetchAPI<AutoTradingStatus>('/api/trading/mode/auto/status');
      return response || { success: false, is_running: false };
    } catch (error) {
      logger.error('获取全自动量化状态失败:', error);
      throw error;
    }
  },

  async getAutoTradingSchedulerStatus(): Promise<AutoTradingSchedulerStatus> {
    try {
      const response = await fetchAPI<AutoTradingSchedulerStatus>('/api/auto-trading/status');
      return response || { status: 'unknown', stats: {}, circuit_breaker: {}, config: {} };
    } catch (error) {
      logger.error('获取24h调度器状态失败:', error);
      throw error;
    }
  },

  async startAutoTrading(config: AutoTradingConfig): Promise<AutoTradingStatus> {
    try {
      logger.info('启动全自动量化:', config);
      const response = await fetchAPI<AutoTradingStatus>('/api/trading/mode/auto/start', {
        method: 'POST',
        body: config,
      });
      
      if (!response || !response.success) {
        throw new APIError('启动全自动量化失败', 0, response);
      }
      
      return response;
    } catch (error) {
      logger.error('启动全自动量化失败:', error);
      throw error;
    }
  },

  async stopAutoTrading(): Promise<AutoTradingStatus> {
    try {
      logger.info('停止全自动量化');
      const response = await fetchAPI<AutoTradingStatus>('/api/trading/mode/auto/stop', {
        method: 'POST',
      });
      
      if (!response || !response.success) {
        throw new APIError('停止全自动量化失败', 0, response);
      }
      
      return response;
    } catch (error) {
      logger.error('停止全自动量化失败:', error);
      throw error;
    }
  },

  // ============================================
  // 手动交易 API
  // ============================================
  
  async getManualPositions(): Promise<{ success: boolean; positions?: ManualPosition[]; total_equity?: number; available_balance?: number; mode?: string }> {
    try {
      const response = await fetchAPI<{ success: boolean; positions?: ManualPosition[]; total_equity?: number; available_balance?: number; mode?: string }>('/api/trading/mode/manual/positions');
      return response || { success: false };
    } catch (error) {
      logger.error('获取手动交易持仓失败:', error);
      throw error;
    }
  },

  async placeManualOrder(order: ManualOrderRequest): Promise<ManualOrderResponse> {
    try {
      logger.info('手动下单:', order);
      const response = await fetchAPI<ManualOrderResponse>('/api/trading/mode/manual/order', {
        method: 'POST',
        body: order,
      });
      
      if (!response || !response.success) {
        throw new APIError(response?.message || '下单失败', 0, response);
      }
      
      return response;
    } catch (error) {
      logger.error('手动下单失败:', error);
      throw error;
    }
  },

  async closePosition(request: ClosePositionRequest): Promise<ManualOrderResponse> {
    try {
      logger.info('平仓:', request);
      const response = await fetchAPI<ManualOrderResponse>('/api/trading/position/close', {
        method: 'POST',
        body: request,
      });
      
      if (!response || !response.success) {
        throw new APIError(response?.message || '平仓失败', 0, response);
      }
      
      return response;
    } catch (error) {
      logger.error('平仓失败:', error);
      throw error;
    }
  },

  // ============================================
  // 24小时自动交易 API
  // ============================================

  async startAutoTradingScheduler(): Promise<{ success: boolean; message: string }> {
    try {
      logger.info('启动24小时自动交易');
      return await fetchAPI<{ success: boolean; message: string }>('/api/auto-trading/start', {
        method: 'POST',
      });
    } catch (error) {
      logger.error('启动自动交易失败:', error);
      throw error;
    }
  },

  async stopAutoTradingScheduler(): Promise<{ success: boolean; message: string }> {
    try {
      logger.info('停止24小时自动交易');
      return await fetchAPI<{ success: boolean; message: string }>('/api/auto-trading/stop', {
        method: 'POST',
      });
    } catch (error) {
      logger.error('停止自动交易失败:', error);
      throw error;
    }
  },

  async pauseAutoTradingScheduler(): Promise<{ success: boolean; message: string }> {
    try {
      logger.info('暂停24小时自动交易');
      return await fetchAPI<{ success: boolean; message: string }>('/api/auto-trading/pause', {
        method: 'POST',
      });
    } catch (error) {
      logger.error('暂停自动交易失败:', error);
      throw error;
    }
  },

  async resumeAutoTradingScheduler(): Promise<{ success: boolean; message: string }> {
    try {
      logger.info('恢复24小时自动交易');
      return await fetchAPI<{ success: boolean; message: string }>('/api/auto-trading/resume', {
        method: 'POST',
      });
    } catch (error) {
      logger.error('恢复自动交易失败:', error);
      throw error;
    }
  },

  async restartAutoTradingScheduler(): Promise<{ success: boolean; message: string }> {
    try {
      logger.info('重启24小时自动交易');
      return await fetchAPI<{ success: boolean; message: string }>('/api/auto-trading/restart', {
        method: 'POST',
      });
    } catch (error) {
      logger.error('重启自动交易失败:', error);
      throw error;
    }
  },

  async cleanupAutoTradingScheduler(): Promise<{ success: boolean; message: string }> {
    try {
      logger.info('强制清理自动交易资源');
      return await fetchAPI<{ success: boolean; message: string }>('/api/auto-trading/cleanup', {
        method: 'POST',
      });
    } catch (error) {
      logger.error('清理自动交易资源失败:', error);
      throw error;
    }
  },

  async getAutoTradingLogs(limit: number = 100): Promise<any[]> {
    try {
      const response = await fetchAPI<{ logs?: any[] }>(`/api/auto-trading/logs?limit=${limit}`);
      return response.logs || [];
    } catch (error) {
      logger.error('获取自动交易日志失败:', error);
      throw error;
    }
  },

  async getAutoTradingStats(): Promise<Record<string, any>> {
    try {
      return await fetchAPI<Record<string, any>>('/api/auto-trading/stats');
    } catch (error) {
      logger.error('获取自动交易统计失败:', error);
      throw error;
    }
  },

  async getAutoTradingSessions(): Promise<AutoTradingSession[]> {
    try {
      const response = await fetchAPI<{ sessions?: AutoTradingSession[] }>('/api/auto-trading/sessions');
      return response.sessions || [];
    } catch (error) {
      logger.error('获取自动交易会话历史失败:', error);
      throw error;
    }
  },

  async getAutoTradingHealth(): Promise<{ status: string }> {
    try {
      return await fetchAPI<{ status: string }>('/api/auto-trading/health');
    } catch (error) {
      logger.error('获取自动交易健康状态失败:', error);
      throw error;
    }
  },

  // ============================================
  // 交易数据 API
  // ============================================

  async getSymbols(): Promise<TradingSymbol[]> {
    try {
      return await fetchAPI<TradingSymbol[]>('/api/trading/symbols');
    } catch (error) {
      logger.error('获取币种列表失败:', error);
      throw error;
    }
  },

  async addSymbol(symbol: TradingSymbol): Promise<TradingSymbol> {
    try {
      return await fetchAPI<TradingSymbol>('/api/trading/symbols', {
        method: 'POST',
        body: symbol,
      });
    } catch (error) {
      logger.error('添加币种失败:', error);
      throw error;
    }
  },

  async deleteSymbol(symbol: string): Promise<{ success: boolean }> {
    try {
      return await fetchAPI<{ success: boolean }>(`/api/trading/symbols/${encodeURIComponent(symbol)}`, {
        method: 'DELETE',
      });
    } catch (error) {
      logger.error('删除币种失败:', error);
      throw error;
    }
  },

  async getPrice(symbol: string): Promise<PriceInfo> {
    try {
      return await fetchAPI<PriceInfo>(`/api/trading/price/${encodeURIComponent(symbol)}`);
    } catch (error) {
      logger.error('获取价格失败:', error);
      throw error;
    }
  },

  async getKlines(symbol: string, interval: string = '1h', limit: number = 100): Promise<KLineData[]> {
    try {
      return await fetchAPI<KLineData[]>(`/api/trading/klines/${encodeURIComponent(symbol)}?interval=${interval}&limit=${limit}`);
    } catch (error) {
      logger.error('获取K线失败:', error);
      throw error;
    }
  },

  async getTrades(symbol: string, limit: number = 50): Promise<TradeRecord[]> {
    try {
      return await fetchAPI<TradeRecord[]>(`/api/trading/trades/${encodeURIComponent(symbol)}?limit=${limit}`);
    } catch (error) {
      logger.error('获取交易历史失败:', error);
      throw error;
    }
  },

  async getPosition(symbol: string): Promise<PositionInfo> {
    try {
      return await fetchAPI<PositionInfo>(`/api/trading/position/${encodeURIComponent(symbol)}`);
    } catch (error) {
      logger.error('获取持仓失败:', error);
      throw error;
    }
  },

  async getAccount(): Promise<AccountInfo> {
    try {
      return await fetchAPI<AccountInfo>('/api/trading/account');
    } catch (error) {
      logger.error('获取账户信息失败:', error);
      throw error;
    }
  },
};

export default tradingModeApi;
