/**
 * AutoTradingPanel.tsx
 * 全自动量化面板组件
 * 
 * 功能:
 * - 显示全自动量化运行状态（只读监控）
 * - 启动/停止全自动量化
 * - 显示策略、持仓、盈亏信息
 */

import React, { useState, useEffect, useCallback } from 'react';
import { 
  Play, 
  Square, 
  RefreshCw, 
  Activity, 
  TrendingUp,
  Clock,
  Settings,
  AlertCircle,
  Zap,
  BarChart3,
  Terminal
} from 'lucide-react';

import { tradingModeApi, AutoTradingStatus as ApiAutoTradingStatus, AutoTradingConfig } from '../../utils/api/tradingMode';
import { useNotifications } from '../../hooks/useNotifications';

// 扩展API类型，添加前端需要的可选字段
interface AutoTradingStatus extends ApiAutoTradingStatus {
  strategy?: string;
  symbols?: string[];
  pnl?: number;        // 等待后端API提供
  pnl_percent?: number; // 等待后端API提供
  latest_signal?: {
    symbol?: string;
    side?: string;
    notional_usdt?: number;
    leverage?: number;
    [key: string]: any;
  };
}

export const AutoTradingPanel: React.FC = () => {
  const [status, setStatus] = useState<AutoTradingStatus | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [config, setConfig] = useState<AutoTradingConfig>({
    strategy: 'stage46_aggressive',
    symbols: ['BTC', 'ETH'],
    leverage: 3,
    demo_mode: true,
  });
  const [showConfig, setShowConfig] = useState(false);
  const { showNotification } = useNotifications();

  // 获取全自动量化状态
  const fetchStatus = useCallback(async () => {
    try {
      const response = await tradingModeApi.getAutoTradingStatus();
      // 转换后端字段到前端字段
      const newStatus: AutoTradingStatus = {
        ...response,
        strategy: response.state?.strategy || config.strategy,
        symbols: config.symbols, // 使用本地配置
      };
      setStatus(newStatus);
    } catch (error) {
      console.error('获取全自动量化状态失败:', error);
    }
  }, [config]);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 5000); // 每5秒刷新
    return () => clearInterval(interval);
  }, [fetchStatus]);

  const handleStart = async () => {
    setIsLoading(true);
    try {
      const response = await tradingModeApi.startAutoTrading(config);
      const newStatus: AutoTradingStatus = {
        ...response,
        strategy: response.state?.strategy || config.strategy,
        symbols: config.symbols,
      };
      setStatus(newStatus);
    } catch (error) {
      console.error('启动全自动量化失败:', error);
      showNotification({ type: 'error', title: '启动失败', message: (error as Error).message });
    } finally {
      setIsLoading(false);
    }
  };

  const handleStop = async () => {
    setIsLoading(true);
    try {
      await tradingModeApi.stopAutoTrading();
      setStatus(prev => prev ? { ...prev, is_running: false } : null);
    } catch (error) {
      console.error('停止全自动量化失败:', error);
      showNotification({ type: 'error', title: '停止失败', message: (error as Error).message });
    } finally {
      setIsLoading(false);
    }
  };

  const formatRuntime = (seconds?: number) => {
    if (!seconds) return '--';
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    return `${hours}小时${mins}分钟`;
  };

  return (
    <div className="space-y-6">
      {/* 状态卡片 */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Activity className="w-5 h-5 text-blue-400" />
            <span className="text-gray-400 text-sm">运行状态</span>
          </div>
          <div className="flex items-center gap-2">
            <div className={`w-2.5 h-2.5 rounded-full ${status?.is_running ? 'bg-green-500 animate-pulse' : 'bg-gray-500'}`} />
            <span className={`text-lg font-semibold ${status?.is_running ? 'text-green-400' : 'text-gray-400'}`}>
              {status?.is_running ? '运行中' : '已停止'}
            </span>
          </div>
          {status?.pid && (
            <p className="text-xs text-gray-500 mt-1">PID: {status.pid}</p>
          )}
          {typeof status?.state?.cycle_count === 'number' && (
            <p className="text-xs text-blue-400 mt-1">
              已完成 {status.state.cycle_count} 轮信号计算
            </p>
          )}
        </div>

        <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Clock className="w-5 h-5 text-purple-400" />
            <span className="text-gray-400 text-sm">运行时间</span>
          </div>
          <p className="text-lg font-semibold text-white">
            {formatRuntime(status?.runtime)}
          </p>
        </div>

        <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
          <div className="flex items-center gap-2 mb-2">
            <TrendingUp className="w-5 h-5 text-green-400" />
            <span className="text-gray-400 text-sm">累计盈亏</span>
          </div>
          <p className={`text-lg font-semibold ${(status?.pnl || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {(status?.pnl || 0) >= 0 ? '+' : ''}{status?.pnl?.toFixed(2) || '--'} USDT
          </p>
          {typeof status?.pnl_percent === 'number' && (
            <p className={`text-xs ${status.pnl_percent >= 0 ? 'text-green-500/70' : 'text-red-500/70'}`}>
              {status.pnl_percent >= 0 ? '+' : ''}{status.pnl_percent.toFixed(2)}%
            </p>
          )}
        </div>

        <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Settings className="w-5 h-5 text-yellow-400" />
            <span className="text-gray-400 text-sm">当前策略</span>
          </div>
          <p className="text-lg font-semibold text-white truncate">
            {status?.strategy || config.strategy}
          </p>
          <p className="text-xs text-gray-500 mt-1">
            {config.symbols.join(', ')}
          </p>
        </div>
      </div>

      {/* 最新信号卡片 */}
      {status?.latest_signal ? (
        <div className="bg-gray-800 rounded-xl border border-gray-700 p-5">
          <div className="flex items-center gap-2 mb-3">
            <Zap className="w-5 h-5 text-orange-400" />
            <h3 className="text-white font-semibold">最新信号</h3>
            <span className="text-xs text-gray-500 ml-auto">
              {status.latest_signal.symbol?.toUpperCase() || 'Unknown'}
            </span>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <p className="text-xs text-gray-400">方向</p>
              <p className={`text-lg font-semibold ${status.latest_signal.side === 'long' ? 'text-green-400' : status.latest_signal.side === 'short' ? 'text-red-400' : 'text-gray-400'}`}>
                {status.latest_signal.side === 'long' ? '做多' : status.latest_signal.side === 'short' ? '做空' : status.latest_signal.side || '—'}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-400">名义金额</p>
              <p className="text-lg font-semibold text-white">
                {status.latest_signal.notional_usdt ? `${status.latest_signal.notional_usdt} USDT` : '—'}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-400">杠杆</p>
              <p className="text-lg font-semibold text-white">
                {status.latest_signal.leverage ? `${status.latest_signal.leverage}x` : '—'}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-400">信号时间</p>
              <p className="text-lg font-semibold text-white">
                {status.state?.last_signal_time ? new Date(status.state.last_signal_time * 1000).toLocaleTimeString() : '—'}
              </p>
            </div>
          </div>
        </div>
      ) : status?.is_running ? (
        <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-5 flex items-center gap-3">
          <BarChart3 className="w-5 h-5 text-gray-500 animate-pulse" />
          <p className="text-gray-400 text-sm">等待首次信号计算...（每15分钟一轮）</p>
        </div>
      ) : null}

      {/* 错误提示 */}
      {status?.state?.last_error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
          <div>
            <h4 className="text-sm font-medium text-red-400 mb-1">运行异常</h4>
            <p className="text-sm text-red-300/80 font-mono">{status.state.last_error}</p>
          </div>
        </div>
      )}

      {/* 报告摘要 */}
      {status?.report?.shadow_exec && (
        <div className="bg-gray-800 rounded-xl border border-gray-700 p-5">
          <div className="flex items-center gap-2 mb-3">
            <Terminal className="w-5 h-5 text-cyan-400" />
            <h3 className="text-white font-semibold">Shadow 报告摘要</h3>
            <span className="text-xs text-gray-500 ml-auto">
              {status.report.shadow_exec.ts_utc || ''}
            </span>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <p className="text-gray-400">状态</p>
              <p className={`font-semibold ${status.report.shadow_exec.ok ? 'text-green-400' : 'text-red-400'}`}>
                {status.report.shadow_exec.ok ? '成功' : (status.report.shadow_exec.reason || '失败')}
              </p>
            </div>
            <div>
              <p className="text-gray-400">交易所</p>
              <p className="text-white font-semibold">{status.report.shadow_exec.exchange || '—'}</p>
            </div>
            <div>
              <p className="text-gray-400">模式</p>
              <p className="text-white font-semibold">{status.report.shadow_exec.demo ? '模拟盘' : '实盘'}</p>
            </div>
            <div>
              <p className="text-gray-400">预检</p>
              <p className="text-white font-semibold">{status.report.shadow_exec.precheck_no_submit ? '仅预览' : '可下单'}</p>
            </div>
          </div>
        </div>
      )}

      {/* 控制按钮 */}
      <div className="flex flex-wrap gap-4">
        {!status?.is_running ? (
          <button
            onClick={handleStart}
            disabled={isLoading}
            className="flex items-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:cursor-not-allowed rounded-xl text-white font-medium transition-colors"
          >
            <Play className="w-5 h-5" />
            {isLoading ? '启动中...' : '启动全自动交易'}
          </button>
        ) : (
          <button
            onClick={handleStop}
            disabled={isLoading}
            className="flex items-center gap-2 px-6 py-3 bg-red-600 hover:bg-red-500 disabled:bg-gray-700 disabled:cursor-not-allowed rounded-xl text-white font-medium transition-colors"
          >
            <Square className="w-5 h-5" />
            {isLoading ? '停止中...' : '停止交易'}
          </button>
        )}

        <button
          onClick={() => setShowConfig(!showConfig)}
          className="flex items-center gap-2 px-6 py-3 bg-gray-700 hover:bg-gray-600 rounded-xl text-white font-medium transition-colors"
        >
          <Settings className="w-5 h-5" />
          配置参数
        </button>

        <button
          onClick={fetchStatus}
          disabled={isLoading}
          className="flex items-center gap-2 px-6 py-3 bg-gray-700 hover:bg-gray-600 disabled:cursor-not-allowed rounded-xl text-white font-medium transition-colors"
        >
          <RefreshCw className={`w-5 h-5 ${isLoading ? 'animate-spin' : ''}`} />
          刷新状态
        </button>
      </div>

      {/* 配置面板 */}
      {showConfig && (
        <div className="bg-gray-800 rounded-xl border border-gray-700 p-6">
          <h3 className="text-lg font-semibold text-white mb-4">交易配置</h3>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-gray-400 mb-2">策略</label>
              <select
                value={config.strategy}
                onChange={(e) => setConfig({ ...config, strategy: e.target.value })}
                disabled={status?.is_running}
                className="w-full px-4 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white focus:border-blue-500 focus:outline-none disabled:opacity-50"
              >
                <option value="stage46_aggressive">Stage46 激进策略</option>
                <option value="stage46_conservative">Stage46 保守策略</option>
                <option value="mainline_shadow">Mainline Shadow</option>
                <option value="shortwave">Shortwave 策略</option>
              </select>
            </div>

            <div>
              <label className="block text-sm text-gray-400 mb-2">交易币种</label>
              <input
                type="text"
                value={config.symbols.join(', ')}
                onChange={(e) => setConfig({ ...config, symbols: e.target.value.split(',').map(s => s.trim()) })}
                disabled={status?.is_running}
                className="w-full px-4 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white focus:border-blue-500 focus:outline-none disabled:opacity-50"
                placeholder="BTC, ETH"
              />
            </div>

            <div>
              <label className="block text-sm text-gray-400 mb-2">杠杆倍数</label>
              <select
                value={config.leverage}
                onChange={(e) => setConfig({ ...config, leverage: parseInt(e.target.value) })}
                disabled={status?.is_running}
                className="w-full px-4 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white focus:border-blue-500 focus:outline-none disabled:opacity-50"
              >
                <option value={1}>1x</option>
                <option value={3}>3x</option>
                <option value={5}>5x</option>
                <option value={10}>10x</option>
                <option value={20}>20x</option>
              </select>
            </div>

            <div>
              <label className="block text-sm text-gray-400 mb-2">模式</label>
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={config.demo_mode}
                  onChange={(e) => setConfig({ ...config, demo_mode: e.target.checked })}
                  disabled={status?.is_running}
                  className="w-4 h-4 rounded border-gray-600 bg-gray-700 text-blue-600"
                />
                <span className="text-gray-300">模拟模式（推荐先使用模拟模式测试）</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 警告提示 */}
      <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-xl p-4 flex items-start gap-3">
        <AlertCircle className="w-5 h-5 text-yellow-400 flex-shrink-0 mt-0.5" />
        <div>
          <h4 className="text-sm font-medium text-yellow-400 mb-1">风险提示</h4>
          <p className="text-sm text-gray-400">
            全自动量化交易使用200+策略库进行24/7自动交易。请在启动前确保：
            1) 已配置交易所API密钥；2) 已选择适合的策略；3) 建议先使用模拟模式测试。
            交易有风险，投资需谨慎。
          </p>
        </div>
      </div>
    </div>
  );
};

export default AutoTradingPanel;
