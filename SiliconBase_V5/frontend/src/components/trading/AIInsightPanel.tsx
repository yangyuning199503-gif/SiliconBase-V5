/**
 * AI 洞察面板
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 * 显示 World Model 预测和策略分析
 * 
 * 功能:
 * - World Model 预测结果展示
 * - 当前策略信息显示
 * - 风险评分可视化
 * - 策略置信度指示
 * 
 * 作者: SiliconBase Team
 * 日期: 2026-04-09
 */

import React, { useEffect } from 'react'
import { motion } from 'framer-motion'
import { 
  Brain, 
  TrendingUp, 
  TrendingDown, 
  AlertTriangle, 
  CheckCircle2,
  Activity,
  Target,
  Shield
} from 'lucide-react'
import { useTradingStore } from '../../stores/tradingStore'

export const AIInsightPanel: React.FC = () => {
  const { 
    aiPrediction, 
    currentStrategy, 
    strategyConfidence,
    activeSymbol,
    fetchTradingStatus 
  } = useTradingStore()
  
  const [lastUpdate, setLastUpdate] = React.useState<Date | null>(null)
  const [isStale, setIsStale] = React.useState(false)

  // 定期刷新交易状态
  useEffect(() => {
    if (!activeSymbol) return
    
    // 初始加载
    fetchTradingStatus(activeSymbol).then(() => {
      setLastUpdate(new Date())
    })
    
    // 每 10 秒刷新一次
    const interval = setInterval(() => {
      fetchTradingStatus(activeSymbol).then(() => {
        setLastUpdate(new Date())
        setIsStale(false)
      })
    }, 10000)
    
    // 检查数据是否过期（超过30秒）
    const staleCheck = setInterval(() => {
      if (lastUpdate && Date.now() - lastUpdate.getTime() > 30000) {
        setIsStale(true)
      }
    }, 5000)
    
    return () => {
      clearInterval(interval)
      clearInterval(staleCheck)
    }
  }, [activeSymbol, fetchTradingStatus])

  // 获取风险等级颜色
  const getRiskColor = (score: number) => {
    if (score < 0.3) return 'text-green-400'
    if (score < 0.6) return 'text-yellow-400'
    return 'text-red-400'
  }

  // 获取风险等级标签
  const getRiskLabel = (score: number) => {
    if (score < 0.3) return '低风险'
    if (score < 0.6) return '中等风险'
    return '高风险'
  }

  // 获取置信度颜色
  const getConfidenceColor = (confidence: number) => {
    if (confidence >= 0.7) return 'text-green-400'
    if (confidence >= 0.4) return 'text-yellow-400'
    return 'text-red-400'
  }

  return (
    <div className="bg-gray-800 rounded-xl border border-gray-700 p-4 h-full">
      {/* 标题 */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Brain className="w-5 h-5 text-blue-400" />
          <h3 className="text-lg font-semibold text-white">AI 智能分析</h3>
        </div>
        {lastUpdate && (
          <div className={`text-xs ${isStale ? 'text-red-400' : 'text-gray-500'}`}>
            {isStale ? '数据过期' : '实时'}
            <span className="ml-1">
              {lastUpdate.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
            </span>
          </div>
        )}
      </div>

      {/* World Model 预测 */}
      {aiPrediction ? (
        <motion.div 
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-3 mb-6"
        >
          <div className="text-sm text-gray-400 mb-2">World Model 预测</div>
          
          {/* 成功概率 */}
          <div className="flex items-center justify-between p-2 bg-gray-700/50 rounded-lg">
            <div className="flex items-center gap-2">
              <Target className="w-4 h-4 text-blue-400" />
              <span className="text-sm text-gray-300">成功概率</span>
            </div>
            <span className={`font-medium ${getConfidenceColor(aiPrediction.successProbability)}`}>
              {(aiPrediction.successProbability * 100).toFixed(1)}%
            </span>
          </div>

          {/* 预期收益 */}
          <div className="flex items-center justify-between p-2 bg-gray-700/50 rounded-lg">
            <div className="flex items-center gap-2">
              {aiPrediction.expectedPnl >= 0 ? (
                <TrendingUp className="w-4 h-4 text-green-400" />
              ) : (
                <TrendingDown className="w-4 h-4 text-red-400" />
              )}
              <span className="text-sm text-gray-300">预期收益</span>
            </div>
            <span className={`font-medium ${aiPrediction.expectedPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {aiPrediction.expectedPnl >= 0 ? '+' : ''}{aiPrediction.expectedPnl.toFixed(2)}%
            </span>
          </div>

          {/* 风险评分 */}
          <div className="flex items-center justify-between p-2 bg-gray-700/50 rounded-lg">
            <div className="flex items-center gap-2">
              <Shield className={`w-4 h-4 ${getRiskColor(aiPrediction.riskScore)}`} />
              <span className="text-sm text-gray-300">风险评分</span>
            </div>
            <span className={`font-medium ${getRiskColor(aiPrediction.riskScore)}`}>
              {getRiskLabel(aiPrediction.riskScore)}
            </span>
          </div>

          {/* 建议行动 */}
          <div className="flex items-center justify-between p-2 bg-gray-700/50 rounded-lg">
            <div className="flex items-center gap-2">
              <Activity className="w-4 h-4 text-purple-400" />
              <span className="text-sm text-gray-300">建议行动</span>
            </div>
            <span className="font-medium text-white">
              {aiPrediction.recommendedAction === 'open_long' ? '买入做多' :
               aiPrediction.recommendedAction === 'open_short' ? '卖出做空' :
               aiPrediction.recommendedAction === 'close' ? '平仓' : '观望'}
            </span>
          </div>
        </motion.div>
      ) : (
        <div className="text-center py-6 text-gray-500 mb-6">
          <Brain className="w-8 h-8 mx-auto mb-2 opacity-50" />
          <p className="text-sm">World Model 预测加载中...</p>
        </div>
      )}

      {/* 分隔线 */}
      <div className="border-t border-gray-700 my-4" />

      {/* 当前策略 */}
      <div>
        <div className="text-sm text-gray-400 mb-3">当前策略</div>
        
        {currentStrategy ? (
          <motion.div 
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="space-y-3"
          >
            {/* 策略名称 */}
            <div className="flex items-center justify-between p-2 bg-blue-500/10 border border-blue-500/20 rounded-lg">
              <span className="text-sm text-blue-300">策略类型</span>
              <span className="font-medium text-white">{currentStrategy}</span>
            </div>

            {/* 置信度 */}
            <div className="p-2 bg-gray-700/50 rounded-lg">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-gray-300">策略置信度</span>
                <span className={`font-medium ${getConfidenceColor(strategyConfidence)}`}>
                  {(strategyConfidence * 100).toFixed(1)}%
                </span>
              </div>
              {/* 置信度进度条 */}
              <div className="h-2 bg-gray-600 rounded-full overflow-hidden">
                <motion.div 
                  initial={{ width: 0 }}
                  animate={{ width: `${strategyConfidence * 100}%` }}
                  transition={{ duration: 0.5 }}
                  className={`h-full rounded-full ${
                    strategyConfidence >= 0.7 ? 'bg-green-400' :
                    strategyConfidence >= 0.4 ? 'bg-yellow-400' : 'bg-red-400'
                  }`}
                />
              </div>
            </div>

            {/* 状态指示 */}
            <div className="flex items-center justify-between p-2 bg-gray-700/50 rounded-lg">
              <span className="text-sm text-gray-300">系统状态</span>
              <div className="flex items-center gap-1.5">
                <div className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
                <span className="text-sm text-green-400">运行中</span>
              </div>
            </div>
          </motion.div>
        ) : (
          <div className="text-center py-4 text-gray-500">
            <p className="text-sm">暂无活跃策略</p>
          </div>
        )}
      </div>

      {/* 风险提示 */}
      {aiPrediction && aiPrediction.riskScore > 0.6 && (
        <motion.div 
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          className="mt-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg"
        >
          <div className="flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 text-red-400 flex-shrink-0 mt-0.5" />
            <div>
              <div className="text-sm text-red-400 font-medium">风险提示</div>
              <div className="text-xs text-red-300/80 mt-1">
                当前市场风险较高，建议谨慎操作或降低仓位。
              </div>
            </div>
          </div>
        </motion.div>
      )}

      {/* 成功提示 */}
      {aiPrediction && aiPrediction.successProbability > 0.7 && aiPrediction.riskScore < 0.4 && (
        <motion.div 
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          className="mt-4 p-3 bg-green-500/10 border border-green-500/20 rounded-lg"
        >
          <div className="flex items-start gap-2">
            <CheckCircle2 className="w-4 h-4 text-green-400 flex-shrink-0 mt-0.5" />
            <div>
              <div className="text-sm text-green-400 font-medium">机会提示</div>
              <div className="text-xs text-green-300/80 mt-1">
                World Model 预测当前为 favorable 条件，可考虑入场。
              </div>
            </div>
          </div>
        </motion.div>
      )}
    </div>
  )
}

export default AIInsightPanel
