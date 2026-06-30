/**
 * 决策追溯面板 (DecisionHistory)
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 * 列出最近的AI决策（时间、动作、置信度、理由）
 */

import React from 'react'
import { useTradingStore } from '../../stores/tradingStore'

const DecisionHistory: React.FC = () => {
  const signals = useTradingStore((state) => state.signals)
  const mcpCalls = useTradingStore((state) => state.mcpCalls)

  const formatTime = (ts: number) => {
    if (!ts) return '--'
    const d = new Date(ts * 1000)
    return d.toLocaleTimeString()
  }

  return (
    <div className="decision-history" style={{ padding: '16px', border: '1px solid #e0e0e0', borderRadius: '8px', background: '#fafafa' }}>
      <h3 style={{ margin: '0 0 12px 0', fontSize: '16px', color: '#333' }}>📜 决策追溯</h3>

      {/* AI 交易信号 */}
      <div style={{ marginBottom: '16px' }}>
        <div style={{ fontSize: '13px', color: '#888', marginBottom: '8px', fontWeight: 500 }}>交易信号</div>
        {signals.length === 0 && (
          <div style={{ textAlign: 'center', padding: '12px', color: '#bbb', fontSize: '12px' }}>暂无交易信号</div>
        )}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {signals.slice(0, 10).map((signal) => (
            <div
              key={signal.id}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '8px 10px',
                background: '#fff',
                borderRadius: '4px',
                border: '1px solid #f0f0f0',
                fontSize: '12px',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{
                  display: 'inline-block',
                  width: '8px',
                  height: '8px',
                  borderRadius: '50%',
                  background: signal.action === 'buy' ? '#52c41a' : signal.action === 'sell' ? '#f5222d' : '#999',
                }} />
                <span style={{ fontWeight: 500, color: '#333' }}>{signal.symbol}</span>
                <span style={{ color: '#666' }}>{signal.action.toUpperCase()}</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <span style={{ color: '#888' }}>置信度 {signal.confidence ? `${(signal.confidence * 100).toFixed(0)}%` : '--'}</span>
                <span style={{ color: '#aaa' }}>{formatTime(signal.timestamp)}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* MCP 调用记录 */}
      <div>
        <div style={{ fontSize: '13px', color: '#888', marginBottom: '8px', fontWeight: 500 }}>MCP 调用</div>
        {mcpCalls.length === 0 && (
          <div style={{ textAlign: 'center', padding: '12px', color: '#bbb', fontSize: '12px' }}>暂无 MCP 调用记录</div>
        )}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {mcpCalls.slice(0, 10).map((call, idx) => (
            <div
              key={`${call.tool_name}_${idx}`}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '8px 10px',
                background: '#fff',
                borderRadius: '4px',
                border: '1px solid #f0f0f0',
                fontSize: '12px',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{
                  display: 'inline-block',
                  width: '8px',
                  height: '8px',
                  borderRadius: '50%',
                  background: call.success === undefined ? '#faad14' : call.success ? '#52c41a' : '#f5222d',
                }} />
                <span style={{ fontWeight: 500, color: '#333' }}>{call.tool_name}</span>
                {call.symbol && <span style={{ color: '#888' }}>{call.symbol}</span>}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                {call.duration_ms !== undefined && (
                  <span style={{ color: '#888' }}>{call.duration_ms}ms</span>
                )}
                <span style={{ color: '#aaa' }}>{formatTime(call.timestamp)}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export default DecisionHistory
