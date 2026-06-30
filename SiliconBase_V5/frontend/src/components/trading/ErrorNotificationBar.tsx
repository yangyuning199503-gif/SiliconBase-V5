/**
 * 错误通知栏 (ErrorNotificationBar)
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 * 聚合最近的错误事件，点击可展开详情
 */

import React, { useState } from 'react'
import { useTradingStore } from '../../stores/tradingStore'

const ErrorNotificationBar: React.FC = () => {
  const errorEvents = useTradingStore((state) => state.errorEvents)
  const clearErrorEvents = useTradingStore((state) => state.clearErrorEvents)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const formatTime = (ts: number) => {
    if (!ts) return '--'
    const d = new Date(ts)
    return d.toLocaleTimeString()
  }

  if (errorEvents.length === 0) {
    return (
      <div style={{ padding: '10px 16px', border: '1px solid #d9f7be', borderRadius: '8px', background: '#f6ffed', color: '#52c41a', fontSize: '13px' }}>
        ✅ 系统运行正常，暂无错误事件
      </div>
    )
  }

  return (
    <div className="error-notification-bar" style={{ border: '1px solid #ffccc7', borderRadius: '8px', background: '#fff2f0', overflow: 'hidden' }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '10px 16px',
        background: '#fff1f0',
        borderBottom: '1px solid #ffccc7',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '14px', fontWeight: 600, color: '#cf1322' }}>
          ⚠️ 错误通知 ({errorEvents.length})
        </div>
        <button
          onClick={clearErrorEvents}
          style={{
            fontSize: '12px',
            color: '#cf1322',
            background: 'transparent',
            border: '1px solid #ffccc7',
            borderRadius: '4px',
            padding: '4px 10px',
            cursor: 'pointer',
          }}
        >
          清空全部
        </button>
      </div>

      <div style={{ maxHeight: '240px', overflowY: 'auto' }}>
        {errorEvents.map((event) => (
          <div
            key={event.id}
            style={{
              padding: '8px 16px',
              borderBottom: '1px solid #ffccc7',
              cursor: 'pointer',
            }}
            onClick={() => setExpandedId(expandedId === event.id ? null : event.id)}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontSize: '12px', color: '#cf1322', fontWeight: 500 }}>[{event.type}]</span>
                <span style={{ fontSize: '13px', color: '#333' }}>{event.message}</span>
              </div>
              <span style={{ fontSize: '11px', color: '#aaa', whiteSpace: 'nowrap' }}>{formatTime(event.timestamp)}</span>
            </div>
            {expandedId === event.id && event.details && (
              <div style={{
                marginTop: '8px',
                padding: '8px',
                background: '#fff',
                borderRadius: '4px',
                fontSize: '12px',
                color: '#666',
                fontFamily: 'monospace',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
              }}>
                {JSON.stringify(event.details, null, 2)}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

export default ErrorNotificationBar
