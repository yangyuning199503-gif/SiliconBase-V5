/**
 * 交易监控面板页面
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 * 方案C：场景化区分 - 支持三种交易模式
 * 
 * 交易模式:
 * - 全自动量化 (auto): 专业策略，24/7自动运行
 * - AI辅助交易 (ai): AI实时决策，消息驱动
 * - 手动交易 (manual): K线分析，自主决策
 * 
 * 特性:
 * - 模式切换
 * - 动态币种管理 (添加/删除任意币种)
 * - 实时 WebSocket 数据推送
 * - K线图 + AI买入/卖出标记
 * - 交易历史 + 持仓面板
 */

import React, { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { 
  TrendingUp, 
  TrendingDown, 
  Plus, 
  Trash2, 
  Wallet,
  History,
  Bot,
  AlertTriangle,
  Settings,
  ChevronDown,
  X,
  Eye,
  EyeOff,
  BarChart3,
  List,
  Shield,
} from 'lucide-react'

// Store
import { useTradingStore, TradingSymbol } from '../stores/tradingStore'

// Components
import KLineChart from '../components/trading/KLineChart'
import AIInsightPanel from '../components/trading/AIInsightPanel'

// 【新增】方案C：三种交易模式组件
import TradingModeSelector, { TradingMode } from '../components/trading/TradingModeSelector'
import AutoTradingPanel from '../components/trading/AutoTradingPanel'
import AITradingPanel from '../components/trading/AITradingPanel'
import tradingModeApi from '../utils/api/tradingMode'
import { fetchAPI } from '../utils/api/index'
import { useNotifications } from '../hooks/useNotifications'
import { exchangeConfigService } from '../services/exchangeConfig'

// ═══════════════════════════════════════════════════════════════
// 子组件 (先内联定义，后续拆分到单独文件)
// ═══════════════════════════════════════════════════════════════

/**
 * 币种选择器组件
 */
const SymbolSelector: React.FC = () => {
  const { 
    symbols, 
    activeSymbol, 
    setActiveSymbol, 
    addSymbol, 
    removeSymbol 
  } = useTradingStore()
  const { showNotification } = useNotifications()
  
  const [isOpen, setIsOpen] = useState(false)
  const [showAddModal, setShowAddModal] = useState(false)
  const [newSymbol, setNewSymbol] = useState('')
  const [isAdding, setIsAdding] = useState(false)
  
  const activeSymObj = symbols.find((s) => s.symbol === activeSymbol)
  
  const handleAddSymbol = async () => {
    if (!newSymbol.trim()) return
    
    setIsAdding(true)
    try {
      await addSymbol(newSymbol.toUpperCase())
      setNewSymbol('')
      setShowAddModal(false)
      showNotification({ type: 'success', title: '添加成功', message: `${newSymbol.toUpperCase()} 已添加到监控列表` })
    } catch (error) {
      showNotification({ type: 'error', title: '添加失败', message: (error as Error).message })
    } finally {
      setIsAdding(false)
    }
  }
  
  const handleRemoveSymbol = async (symbol: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (confirm(`确定要删除 ${symbol} 吗?`)) {
      await removeSymbol(symbol)
    }
  }
  
  return (
    <div className="relative">
      {/* 主选择器 */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 px-4 py-2 bg-gray-800 hover:bg-gray-700 
                   rounded-lg border border-gray-700 transition-colors"
      >
        <span className="text-lg font-bold text-white">
          {activeSymObj?.symbol || activeSymbol}
        </span>
        <span className="text-sm text-gray-400">
          {activeSymObj?.name || ''}
        </span>
        <ChevronDown className={`w-4 h-4 text-gray-400 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
      </button>
      
      {/* 下拉列表 */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className="absolute top-full left-0 mt-2 w-64 bg-gray-800 border border-gray-700 
                       rounded-lg shadow-xl z-50 overflow-hidden"
          >
            <div className="max-h-80 overflow-y-auto">
              {symbols.map((symbol) => (
                <div
                  key={symbol.symbol}
                  onClick={() => {
                    setActiveSymbol(symbol.symbol)
                    setIsOpen(false)
                  }}
                  className={`flex items-center justify-between px-4 py-3 cursor-pointer
                             hover:bg-gray-700 transition-colors
                             ${symbol.symbol === activeSymbol ? 'bg-blue-900/30 border-l-2 border-blue-500' : ''}`}
                >
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 
                                    flex items-center justify-center text-xs font-bold text-white">
                      {symbol.symbol.slice(0, 2)}
                    </div>
                    <div>
                      <div className="font-medium text-white">{symbol.symbol}</div>
                      <div className="text-xs text-gray-400">{symbol.name}</div>
                    </div>
                  </div>
                  
                  {/* 删除按钮 */}
                  <button
                    onClick={(e) => handleRemoveSymbol(symbol.symbol, e)}
                    className="p-1.5 hover:bg-red-500/20 rounded-lg text-gray-500 
                               hover:text-red-400 transition-colors"
                    title="删除币种"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
            
            {/* 添加按钮 */}
            <div className="p-3 border-t border-gray-700">
              <button
                onClick={() => {
                  setIsOpen(false)
                  setShowAddModal(true)
                }}
                className="flex items-center justify-center gap-2 w-full px-4 py-2 
                           bg-blue-600 hover:bg-blue-500 rounded-lg text-white 
                           transition-colors"
              >
                <Plus className="w-4 h-4" />
                <span>添加币种</span>
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      
      {/* 添加币种弹窗 */}
      <AnimatePresence>
        {showAddModal && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
            onClick={() => setShowAddModal(false)}
          >
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              className="bg-gray-800 rounded-xl p-6 w-96 border border-gray-700"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-white">添加币种</h3>
                <button
                  onClick={() => setShowAddModal(false)}
                  className="p-1 hover:bg-gray-700 rounded-lg"
                >
                  <X className="w-5 h-5 text-gray-400" />
                </button>
              </div>
              
              <div className="mb-4">
                <label className="block text-sm text-gray-400 mb-2">币种代码</label>
                <input
                  type="text"
                  value={newSymbol}
                  onChange={(e) => setNewSymbol(e.target.value.toUpperCase())}
                  placeholder="例如: DOGE, SHIB, ADA..."
                  className="w-full px-4 py-2 bg-gray-900 border border-gray-700 rounded-lg 
                             text-white placeholder-gray-500 focus:outline-none 
                             focus:border-blue-500"
                  onKeyPress={(e) => e.key === 'Enter' && handleAddSymbol()}
                />
                <p className="text-xs text-gray-500 mt-2">
                  输入币种代码，如 DOGE, SHIB, ADA 等
                </p>
              </div>
              
              <div className="flex gap-3">
                <button
                  onClick={() => setShowAddModal(false)}
                  className="flex-1 px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg 
                             text-white transition-colors"
                >
                  取消
                </button>
                <button
                  onClick={handleAddSymbol}
                  disabled={!newSymbol.trim() || isAdding}
                  className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 
                             disabled:cursor-not-allowed rounded-lg text-white transition-colors"
                >
                  {isAdding ? '添加中...' : '添加'}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

/**
 * 价格显示组件
 */
const PriceDisplay: React.FC = () => {
  const { currentPrice } = useTradingStore()
  
  if (!currentPrice) {
    return (
      <div className="flex items-center gap-4">
        <div className="text-2xl font-bold text-gray-500">--</div>
      </div>
    )
  }
  
  const isPositive = currentPrice.change24h >= 0
  
  return (
    <div className="flex items-center gap-6">
      <div>
        <div className="text-3xl font-bold text-white">
          ${currentPrice.price.toLocaleString('en-US', { minimumFractionDigits: 2 })}
        </div>
      </div>
      
      <div className={`flex items-center gap-1 px-3 py-1 rounded-full text-sm font-medium
                      ${isPositive ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
        {isPositive ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
        <span>{isPositive ? '+' : ''}{currentPrice.change24hPercent.toFixed(2)}%</span>
      </div>
      
      <div className="text-sm text-gray-400">
        <span>24h高: </span>
        <span className="text-gray-300">${currentPrice.high24h.toLocaleString()}</span>
        <span className="mx-2">|</span>
        <span>24h低: </span>
        <span className="text-gray-300">${currentPrice.low24h.toLocaleString()}</span>
      </div>
    </div>
  )
}



/**
 * 持仓面板组件（支持全局持仓 + 色盲友好）
 */
const PositionPanel: React.FC = () => {
  const { position, activeSymbol, accountBalance } = useTradingStore()
  const [allPositions, setAllPositions] = useState<any[]>([])
  const [closing, setClosing] = useState(false)
  const { showNotification: showPositionNotification } = useNotifications()
  
  // 获取全局持仓
  useEffect(() => {
    const fetchAll = async () => {
      try {
        const res = await tradingModeApi.getManualPositions()
        if (res.positions) setAllPositions(res.positions)
      } catch (e) { /* ignore */ }
    }
    fetchAll()
    const t = setInterval(fetchAll, 5000)
    return () => clearInterval(t)
  }, [])
  
  const displayPositions = allPositions.length > 0 ? allPositions : (position && position.side !== 'none' ? [{ ...position, symbol: activeSymbol }] : [])
  
  if (displayPositions.length === 0) {
    return (
      <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Wallet className="w-5 h-5 text-blue-400" />
            <h3 className="text-white font-semibold">持仓</h3>
          </div>
          {accountBalance !== null && (
            <span className="text-xs text-gray-400">余额 ${accountBalance.toFixed(2)}</span>
          )}
        </div>
        <div className="text-center py-8 text-gray-500">
          <p>当前无持仓</p>
          <p className="text-sm mt-1">AI 交易开始后将显示持仓信息</p>
        </div>
      </div>
    )
  }
  
  const handleClosePosition = async (pos: any) => {
    if (!confirm(`确认平仓 ${pos.symbol || activeSymbol} ${pos.side === 'long' || pos.side === 'buy' ? '做多' : '做空'}持仓？\n数量: ${pos.quantity || pos.size}\n未实现盈亏: ${(pos.unrealizedPnl || pos.unrealized_pnl || 0) >= 0 ? '+' : ''}$${Math.abs(pos.unrealizedPnl || pos.unrealized_pnl || 0).toFixed(2)}`)) {
      return
    }
    setClosing(true)
    try {
      await tradingModeApi.closePosition({
        symbol: pos.symbol || activeSymbol,
        side: pos.side === 'buy' ? 'long' : pos.side === 'sell' ? 'short' : pos.side,
        quantity: pos.quantity || pos.size,
      })
      showPositionNotification({ type: 'success', title: '平仓成功', message: `${pos.symbol || activeSymbol} 持仓已平仓` })
    } catch (error) {
      console.error('平仓失败:', error)
      showPositionNotification({ type: 'error', title: '平仓失败', message: (error as Error).message })
    } finally {
      setClosing(false)
    }
  }
  
  return (
    <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Wallet className="w-5 h-5 text-blue-400" />
          <h3 className="text-white font-semibold">持仓</h3>
        </div>
        {accountBalance !== null && (
          <span className="text-xs text-gray-400">余额 ${accountBalance.toFixed(2)}</span>
        )}
      </div>
      
      <div className="space-y-3 max-h-80 overflow-y-auto">
        {displayPositions.map((pos: any, idx: number) => {
          const pnl = pos.unrealizedPnl || pos.unrealized_pnl || 0
          const isProfit = pnl >= 0
          const side = pos.side === 'buy' ? 'long' : pos.side === 'sell' ? 'short' : pos.side
          return (
            <div key={idx} className="bg-gray-900 rounded-lg p-3">
              <div className="flex items-center justify-between mb-2">
                <span className="font-semibold text-white">{pos.symbol || activeSymbol}</span>
                <span className={`px-2 py-0.5 rounded text-xs font-medium
                                ${side === 'long' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
                  {side === 'long' ? '做多' : '做空'}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div><span className="text-gray-500">数量:</span> <span className="text-white">{pos.quantity || pos.size}</span></div>
                <div><span className="text-gray-500">杠杆:</span> <span className="text-white">{pos.leverage}x</span></div>
              </div>
              <div className="flex justify-between items-center pt-2 border-t border-gray-700 mt-2">
                <span className="text-gray-400">未实现盈亏</span>
                <span className={`font-bold ${isProfit ? 'text-green-400' : 'text-red-400'}`}>
                  {isProfit ? '▲ +' : '▼ -'}${Math.abs(pnl).toFixed(2)}
                </span>
              </div>
              <button 
                onClick={() => handleClosePosition(pos)}
                disabled={closing}
                className="w-full mt-2 px-3 py-1.5 bg-red-600 hover:bg-red-500 disabled:bg-red-800 rounded-lg 
                           text-white font-medium transition-colors text-xs"
              >
                {closing ? '平仓中...' : '平仓'}
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}

/**
 * 交易历史组件
 */
const TradeHistory: React.FC = () => {
  const { trades, activeSymbol } = useTradingStore()
  
  // 筛选当前币种的交易
  const symbolTrades = trades.filter((t) => t.symbol === activeSymbol)
  
  return (
    <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
      <div className="flex items-center gap-2 mb-4">
        <History className="w-5 h-5 text-blue-400" />
        <h3 className="text-white font-semibold">交易历史</h3>
        <span className="ml-auto text-xs text-gray-500">{symbolTrades.length} 笔</span>
      </div>
      
      <div className="space-y-2 max-h-64 overflow-y-auto">
        {symbolTrades.length === 0 ? (
          <div className="text-center py-6 text-gray-500">
            <p>暂无交易记录</p>
          </div>
        ) : (
          symbolTrades.slice(0, 10).map((trade) => (
            <div
              key={trade.id}
              className="flex items-center justify-between p-3 bg-gray-900 rounded-lg"
            >
              <div className="flex items-center gap-3">
                <div className={`w-8 h-8 rounded-full flex items-center justify-center
                               ${trade.action === 'buy' ? 'bg-green-500/20' : 'bg-red-500/20'}`}>
                  {trade.action === 'buy' ? (
                    <TrendingUp className={`w-4 h-4 ${trade.action === 'buy' ? 'text-green-400' : 'text-red-400'}`} />
                  ) : (
                    <TrendingDown className="w-4 h-4 text-red-400" />
                  )}
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-white font-medium">
                      {trade.action === 'buy' ? '买入' : '卖出'}
                    </span>
                    {trade.source === 'ai' && (
                      <span className="px-1.5 py-0.5 bg-blue-500/20 rounded text-xs text-blue-400">
                        🤖 AI
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-gray-500">
                    {new Date(trade.timestamp * 1000).toLocaleString()}
                  </div>
                </div>
              </div>
              <div className="text-right">
                <div className="text-white font-medium">
                  ${trade.price.toLocaleString()}
                </div>
                <div className="text-xs text-gray-500">
                  {trade.quantity} {trade.symbol}
                </div>
                {trade.pnl !== undefined && (
                  <div className={`text-xs ${trade.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    PnL: {trade.pnl >= 0 ? '▲ +' : '▼ -'}${Math.abs(trade.pnl).toFixed(2)}
                  </div>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

/**
 * AI 信号日志组件
 */
const AISignalLog: React.FC = () => {
  const { signals, activeSymbol } = useTradingStore()
  
  // 筛选当前币种的信号
  const symbolSignals = signals.filter((s) => s.symbol === activeSymbol)
  
  return (
    <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
      <div className="flex items-center gap-2 mb-4">
        <Bot className="w-5 h-5 text-blue-400" />
        <h3 className="text-white font-semibold">AI 信号</h3>
        <span className="ml-auto text-xs text-gray-500">{symbolSignals.length} 条</span>
      </div>
      
      <div className="space-y-2 max-h-64 overflow-y-auto">
        {symbolSignals.length === 0 ? (
          <div className="text-center py-6 text-gray-500">
            <p>暂无 AI 信号</p>
            <p className="text-sm mt-1">启动 AI 交易后将显示信号</p>
          </div>
        ) : (
          symbolSignals.slice(0, 10).map((signal, index) => (
            <div
              key={`${signal.id}_${index}`}
              className="p-3 bg-gray-900 rounded-lg border-l-2 border-blue-500"
            >
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2">
                  <span className={`text-sm font-medium
                                  ${signal.action === 'buy' ? 'text-green-400' : 'text-red-400'}`}>
                    {signal.action === 'buy' ? '买入信号' : '卖出信号'}
                  </span>
                  <span className="px-1.5 py-0.5 bg-gray-700 rounded text-xs text-gray-400">
                    {signal.strategy}
                  </span>
                </div>
                <span className="text-xs text-gray-500">
                  置信度 {(signal.confidence * 100).toFixed(0)}%
                </span>
              </div>
              <div className="text-sm text-gray-300 mb-1">
                价格: ${signal.price.toLocaleString()} • 数量: {signal.quantity}
              </div>
              <div className="text-xs text-gray-500">
                {signal.reason}
              </div>
              <div className="text-xs text-gray-600 mt-1">
                {new Date(signal.timestamp * 1000).toLocaleString()}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

/**
 * 连接状态组件
 */
const ConnectionStatus: React.FC = () => {
  const { wsConnected, wsError } = useTradingStore()
  
  if (wsError) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 bg-red-500/20 rounded-full" title={wsError}>
        <AlertTriangle className="w-4 h-4 text-red-400" />
        <span className="text-xs text-red-400">连接错误</span>
      </div>
    )
  }
  
  return (
    <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full
                    ${wsConnected ? 'bg-green-500/20' : 'bg-yellow-500/20'}`}>
      <div className={`w-2 h-2 rounded-full ${wsConnected ? 'bg-green-400' : 'bg-yellow-400'} ${wsConnected ? 'animate-pulse' : ''}`} />
      <span className={`text-xs ${wsConnected ? 'text-green-400' : 'text-yellow-400'}`}>
        {wsConnected ? '实时连接' : '连接中...'}
      </span>
    </div>
  )
}

/**
 * 风险告警 Toast 组件
 */
const RiskAlertToast: React.FC = () => {
  const { wsError } = useTradingStore()
  const [isVisible, setIsVisible] = React.useState(false)
  const [message, setMessage] = React.useState('')
  const [level, setLevel] = React.useState<'warning' | 'critical'>('warning')
  
  React.useEffect(() => {
    if (wsError && wsError.includes('[')) {
      // 解析风险等级
      if (wsError.includes('[CRITICAL]') || wsError.includes('[critical]')) {
        setLevel('critical')
      } else {
        setLevel('warning')
      }
      setMessage(wsError.replace(/\[.*?\]\s*/, ''))
      setIsVisible(true)
      
      // 5秒后自动隐藏
      const timer = setTimeout(() => {
        setIsVisible(false)
      }, 5000)
      
      return () => clearTimeout(timer)
    }
  }, [wsError])
  
  if (!isVisible) return null
  
  return (
    <motion.div
      initial={{ opacity: 0, y: -50, x: '-50%' }}
      animate={{ opacity: 1, y: 0, x: '-50%' }}
      exit={{ opacity: 0, y: -50, x: '-50%' }}
      className={`fixed top-20 left-1/2 z-50 px-6 py-4 rounded-xl shadow-2xl 
                  flex items-center gap-3 min-w-[400px]
                  ${level === 'critical' 
                    ? 'bg-red-600 border border-red-400' 
                    : 'bg-yellow-600 border border-yellow-400'}`}
    >
      <AlertTriangle className="w-6 h-6 text-white" />
      <div className="flex-1">
        <div className="font-bold text-white">
          {level === 'critical' ? '严重风险警告' : '风险提示'}
        </div>
        <div className="text-white/90 text-sm">{message}</div>
      </div>
      <button 
        onClick={() => setIsVisible(false)}
        className="p-1 hover:bg-white/20 rounded"
      >
        <X className="w-5 h-5 text-white" />
      </button>
    </motion.div>
  )
}

// ═══════════════════════════════════════════════════════════════
// 主页面组件
// ═══════════════════════════════════════════════════════════════

const TradingDashboardPage: React.FC = () => {
  const { 
    activeSymbol, 
    connect, 
    disconnect,
    fetchKlines,
    fetchAccountBalance,
    simulationStatus,
    persistentWarnings,
    removePersistentWarning,
  } = useTradingStore()
  
  const [isLoading, setIsLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  
  // 【新增】当前交易模式
  const [tradingMode, setTradingMode] = useState<TradingMode>('manual')
  
  // 【新增】视图模式（简洁/专业）
  const [viewMode, setViewMode] = useState<'simple' | 'pro'>('pro')
  
  // 【新增】交易所配置状态
  const [exchangeConfigured, setExchangeConfigured] = useState(false)
  
  // 【新增】移动端Tab
  const [mobileTab, setMobileTab] = useState<'chart' | 'trade' | 'positions'>('chart')
  
  // 组件挂载时连接 WebSocket
  useEffect(() => {
    // 获取币种列表和初始数据
    const loadData = async () => {
      setIsLoading(true)
      setError(null)
      try {
        // 获取币种列表
        const symbols = await fetchAPI<TradingSymbol[]>('/api/trading/symbols').catch(() => null)
        if (symbols) {
          useTradingStore.getState().setSymbols(symbols)
        }
        
        // 获取初始K线数据
        if (activeSymbol) {
          await fetchKlines(activeSymbol, '1h')
        }
        
        // 获取账户余额
        await fetchAccountBalance()
        
        // 检查交易所配置
        try {
          const modeInfo = await exchangeConfigService.getTradingMode()
          setExchangeConfigured(modeInfo.has_live_config)
        } catch (e) {
          setExchangeConfigured(false)
        }
      } catch (error) {
        console.error('加载数据失败:', error)
        setError('加载数据失败，请刷新页面重试')
      } finally {
        setIsLoading(false)
      }
    }
    
    loadData()
    
    // 连接 WebSocket
    if (activeSymbol) {
      connect(activeSymbol)
    }
    
    // 轮询余额
    const balanceInterval = setInterval(() => {
      fetchAccountBalance()
    }, 10000)
    
    // 组件卸载时断开连接
    return () => {
      disconnect()
      clearInterval(balanceInterval)
    }
  }, [activeSymbol, connect, disconnect, fetchKlines, fetchAccountBalance])
  
  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-900 text-white flex items-center justify-center">
        <div className="text-center">
          <div className="w-12 h-12 border-3 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <div className="text-xl">加载交易面板...</div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-900 text-white flex items-center justify-center">
        <div className="text-center">
          <div className="text-red-400 text-xl mb-4">⚠️ {error}</div>
          <button 
            onClick={() => window.location.reload()}
            className="px-6 py-3 bg-blue-600 rounded-lg hover:bg-blue-500 transition-colors"
          >
            刷新页面
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-900 text-white overflow-y-auto pb-20 md:pb-0">
      {/* 风险告警 Toast */}
      <RiskAlertToast />
      
      {/* 持久化告警列表 */}
      {persistentWarnings.length > 0 && (
        <div className="fixed top-20 right-4 z-40 space-y-2 max-w-sm">
          {persistentWarnings.map((w) => (
            <motion.div
              key={w.id}
              initial={{ opacity: 0, x: 50 }}
              animate={{ opacity: 1, x: 0 }}
              className={`p-3 rounded-lg shadow-lg border ${
                w.level === 'critical' ? 'bg-red-900/90 border-red-500' : 'bg-yellow-900/90 border-yellow-500'
              }`}
            >
              <div className="flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 text-white flex-shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-white">{w.message}</p>
                </div>
                <button onClick={() => removePersistentWarning(w.id)} className="text-white/70 hover:text-white">
                  <X className="w-4 h-4" />
                </button>
              </div>
            </motion.div>
          ))}
        </div>
      )}
      
      {/* 顶部导航栏 */}
      <header className="bg-gray-800 border-b border-gray-700 px-4 md:px-6 py-3 md:py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-lg md:text-xl font-bold">交易监控</h1>
            {/* 当前模式徽章 */}
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${
              tradingMode === 'auto' ? 'bg-blue-500/20 text-blue-300 border border-blue-500/40' :
              tradingMode === 'ai' ? 'bg-purple-500/20 text-purple-300 border border-purple-500/40' :
              'bg-green-500/20 text-green-300 border border-green-500/40'
            }`}>
              {tradingMode === 'auto' ? '全自动' : tradingMode === 'ai' ? 'AI辅助' : '手动'}
            </span>
            <SymbolSelector />
            <div className="hidden md:block">
              <PriceDisplay />
            </div>
          </div>
          <div className="flex items-center gap-3">
            {/* 交易所配置状态 */}
            <div className={`flex items-center gap-1.5 px-2 py-1 rounded text-xs ${
              exchangeConfigured ? 'bg-green-500/10 text-green-400' : 'bg-yellow-500/10 text-yellow-400'
            }`}>
              <Shield className="w-3 h-3" />
              {exchangeConfigured ? '已配置' : '未配置'}
            </div>
            {/* 视图模式切换 */}
            <button
              onClick={() => setViewMode(viewMode === 'pro' ? 'simple' : 'pro')}
              className="hidden md:flex items-center gap-1 px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded text-xs text-gray-300 transition-colors"
            >
              {viewMode === 'pro' ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
              {viewMode === 'pro' ? '简洁' : '专业'}
            </button>
            <ConnectionStatus />
            <button className="p-2 hover:bg-gray-700 rounded-lg transition-colors">
              <Settings className="w-5 h-5 text-gray-400" />
            </button>
          </div>
        </div>
      </header>
      
      {/* 模拟/实盘横幅 */}
      {simulationStatus && (
        <div className={`px-4 md:px-6 py-2 border-l-4 ${
          simulationStatus.is_simulation 
            ? 'bg-green-900/20 border-green-500 text-green-300' 
            : 'bg-red-900/20 border-red-500 text-red-300'
        }`}>
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium">
              {simulationStatus.is_simulation ? '🛡️ 模拟盘环境 - 交易不涉及真实资金' : '⚠️ 实盘交易 - 真实资金风险'}
            </p>
            <span className="text-xs opacity-75 hidden md:inline">执行器：{simulationStatus.executor_type}</span>
          </div>
        </div>
      )}
      
      {/* 主内容区域 */}
      <main className="p-4 md:p-6">
        {/* 【新增】方案C：交易模式选择器 */}
        <div className={`mb-6 ${viewMode === 'simple' && tradingMode !== 'manual' ? 'hidden' : ''}`}>
          <TradingModeSelector 
            currentMode={tradingMode} 
            onModeChange={setTradingMode} 
          />
        </div>
        
        {/* 【新增】根据模式显示不同面板 */}
        <div className="mt-4 md:mt-6">
          {tradingMode === 'auto' && <AutoTradingPanel />}
          {tradingMode === 'ai' && <AITradingPanel />}
          {tradingMode === 'manual' && (
            <div>
              {/* 移动端Tab内容 */}
              <div className="md:hidden">
                {mobileTab === 'chart' && (
                  <div className="space-y-4">
                    <KLineChart symbol={activeSymbol} interval="1h" />
                    {viewMode === 'pro' && <AIInsightPanel />}
                  </div>
                )}
                {mobileTab === 'trade' && (
                  <div className="space-y-4">
                    <AIInsightPanel />
                    {viewMode === 'pro' && <AISignalLog />}
                  </div>
                )}
                {mobileTab === 'positions' && (
                  <div className="space-y-4">
                    <PositionPanel />
                    {viewMode === 'pro' && <TradeHistory />}
                  </div>
                )}
              </div>
              
              {/* 桌面端布局 */}
              <div className="hidden md:grid grid-cols-12 gap-6">
                {/* 左侧: K线图 (占据8列) */}
                <div className="col-span-12 lg:col-span-8">
                  <KLineChart symbol={activeSymbol} interval="1h" />
                </div>
                
                {/* 右侧: 信息面板 (占据4列) */}
                <div className="col-span-12 lg:col-span-4 space-y-4">
                  {/* 简洁模式下隐藏部分面板 */}
                  {viewMode === 'pro' && <AIInsightPanel />}
                  <PositionPanel />
                  {viewMode === 'pro' && <TradeHistory />}
                  {viewMode === 'pro' && <AISignalLog />}
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
      
      {/* 移动端底部导航 */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 bg-gray-800 border-t border-gray-700 z-50">
        <div className="flex items-center justify-around py-2">
          <button 
            onClick={() => setMobileTab('chart')}
            className={`flex flex-col items-center gap-0.5 px-4 py-1 rounded ${mobileTab === 'chart' ? 'text-blue-400' : 'text-gray-400'}`}
          >
            <BarChart3 className="w-5 h-5" />
            <span className="text-xs">行情</span>
          </button>
          <button 
            onClick={() => setMobileTab('trade')}
            className={`flex flex-col items-center gap-0.5 px-4 py-1 rounded ${mobileTab === 'trade' ? 'text-blue-400' : 'text-gray-400'}`}
          >
            <TrendingUp className="w-5 h-5" />
            <span className="text-xs">交易</span>
          </button>
          <button 
            onClick={() => setMobileTab('positions')}
            className={`flex flex-col items-center gap-0.5 px-4 py-1 rounded ${mobileTab === 'positions' ? 'text-blue-400' : 'text-gray-400'}`}
          >
            <List className="w-5 h-5" />
            <span className="text-xs">持仓</span>
          </button>
        </div>
      </nav>
    </div>
  )
}

export default TradingDashboardPage
