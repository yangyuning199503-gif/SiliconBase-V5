/**
 * 策略展示面板 (StrategyPanel)
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 * 显示当前AI指挥官的最新报告、市场分析摘要
 */

import React from 'react'
import { useTradingStore } from '../../stores/tradingStore'

const StrategyPanel: React.FC = () => {
  const commanderReports = useTradingStore((state) => state.commanderReports)
  const currentStrategy = useTradingStore((state) => state.currentStrategy)
  const strategyConfidence = useTradingStore((state) => state.strategyConfidence)
  const strategyStatus = useTradingStore((state) => state.strategyStatus)

  const latestReport = commanderReports[0]

  const formatTime = (ts: number) => {
    if (!ts) return '--'
    const d = new Date(ts * 1000)
    return d.toLocaleTimeString()
  }

  const formatPnl = (pnl: number) => {
    if (pnl === undefined || pnl === null) return '--'
    const sign = pnl >= 0 ? '+' : ''
    return `${sign}${pnl.toFixed(2)} USDT`
  }

  return (
    <div className="strategy-panel" style={{ padding: '16px', border: '1px solid #e0e0e0', borderRadius: '8px', background: '#fafafa' }}>
      <h3 style={{ margin: '0 0 12px 0', fontSize: '16px', color: '#333' }}>🧠 AI 策略面板</h3>
      
      <div style={{ marginBottom: '12px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: '14px', color: '#666' }}>策略状态</span>
          <span style={{
            fontSize: '14px',
            fontWeight: 600,
            color: strategyStatus === 'running' ? '#52c41a' : strategyStatus === 'paused' ? '#faad14' : '#999'
          }}>
            {strategyStatus === 'running' ? '运行中' : strategyStatus === 'paused' ? '已暂停' : '空闲'}
          </span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '8px' }}>
          <span style={{ fontSize: '14px', color: '#666' }}>当前策略</span>
          <span style={{ fontSize: '14px', fontWeight: 500, color: '#333' }}>{currentStrategy || '无'}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '8px' }}>
          <span style={{ fontSize: '14px', color: '#666' }}>置信度</span>
          <span style={{ fontSize: '14px', fontWeight: 500, color: '#333' }}>{strategyConfidence ? `${(strategyConfidence * 100).toFixed(1)}%` : '--'}</span>
        </div>
      </div>

      {latestReport && (
        <div style={{ borderTop: '1px solid #e8e8e8', paddingTop: '12px' }}>
          <div style={{ fontSize: '13px', color: '#888', marginBottom: '8px' }}>
            最新指挥官报告 <span style={{ marginLeft: '8px' }}>{formatTime(latestReport.timestamp)}</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '13px' }}>
            <div style={{ background: '#fff', padding: '8px', borderRadius: '4px', border: '1px solid #f0f0f0' }}>
              <div style={{ color: '#888' }}>活跃代理</div>
              <div style={{ fontWeight: 600, color: '#333', marginTop: '4px' }}>{latestReport.active_agents}</div>
            </div>
            <div style={{ background: '#fff', padding: '8px', borderRadius: '4px', border: '1px solid #f0f0f0' }}>
              <div style={{ color: '#888' }}>总持仓</div>
              <div style={{ fontWeight: 600, color: '#333', marginTop: '4px' }}>{latestReport.total_positions}</div>
            </div>
            <div style={{ background: '#fff', padding: '8px', borderRadius: '4px', border: '1px solid #f0f0f0' }}>
              <div style={{ color: '#888' }}>日盈亏</div>
              <div style={{ fontWeight: 600, color: latestReport.daily_pnl >= 0 ? '#52c41a' : '#f5222d', marginTop: '4px' }}>
                {formatPnl(latestReport.daily_pnl)}
              </div>
            </div>
            <div style={{ background: '#fff', padding: '8px', borderRadius: '4px', border: '1px solid #f0f0f0' }}>
              <div style={{ color: '#888' }}>风险敞口</div>
              <div style={{ fontWeight: 600, color: '#333', marginTop: '4px' }}>{latestReport.risk_exposure?.toFixed(2) ?? '--'}</div>
            </div>
          </div>
          {latestReport.ai_thoughts && (
            <div style={{ marginTop: '10px', padding: '8px', background: '#f6ffed', borderRadius: '4px', fontSize: '12px', color: '#389e0d', lineHeight: 1.5 }}>
              💡 {latestReport.ai_thoughts}
            </div>
          )}
        </div>
      )}

      {!latestReport && (
        <div style={{ textAlign: 'center', padding: '20px', color: '#999', fontSize: '13px' }}>
          等待指挥官报告...
        </div>
      )}
    </div>
  )
}

export default StrategyPanel
