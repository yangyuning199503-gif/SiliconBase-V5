/**
 * 子代理状态实时推送 Hook
 * 【Week 2 Day 5-6】通过 WebSocket 接收子代理状态更新
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { getAuthToken } from '../utils/auth'

export type SubAgentStatus = 'pending' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled'

export interface SubAgentStatusData {
  runtime_id: string
  status: SubAgentStatus
  progress?: number
  current_step?: string
  error?: string
  timestamp?: number
}

export interface UseSubAgentStatusOptions {
  /** 状态变更回调 */
  onStatusChange?: (status: SubAgentStatusData) => void
  /** 连接成功回调 */
  onConnect?: () => void
  /** 连接断开回调 */
  onDisconnect?: () => void
  /** 错误回调 */
  onError?: (error: string) => void
  /** 任务完成回调 */
  onComplete?: (status: SubAgentStatusData) => void
}

export interface UseSubAgentStatusReturn {
  /** 当前状态 */
  status: SubAgentStatusData | null
  /** 是否已连接 */
  isConnected: boolean
  /** 是否正在连接 */
  isConnecting: boolean
  /** 错误信息 */
  error: string | null
  /** 手动断开连接 */
  disconnect: () => void
  /** 重新连接 */
  reconnect: () => void
}

/**
 * 子代理状态实时推送 Hook
 * 
 * @param runtimeId - 子代理运行时ID
 * @param options - 回调选项
 * @returns 状态和控制函数
 * 
 * @example
 * ```tsx
 * const { status, isConnected } = useSubAgentStatus('abc123', {
 *   onStatusChange: (newStatus) => console.log('状态更新:', newStatus),
 *   onComplete: () => console.log('任务完成')
 * })
 * ```
 */
export function useSubAgentStatus(
  runtimeId: string | null,
  options: UseSubAgentStatusOptions = {}
): UseSubAgentStatusReturn {
  const { onStatusChange, onConnect, onDisconnect, onError, onComplete } = options
  
  const [status, setStatus] = useState<SubAgentStatusData | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const [isConnecting, setIsConnecting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pingIntervalRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  
  // 清理函数
  const cleanup = useCallback(() => {
    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current)
      pingIntervalRef.current = null
    }
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
    if (wsRef.current) {
      try {
        wsRef.current.close()
      } catch {
        // 忽略关闭错误
      }
      wsRef.current = null
    }
  }, [])
  
  // 连接 WebSocket
  const connect = useCallback(() => {
    const authToken = getAuthToken()
    if (!runtimeId || !authToken) return
    
    // 避免重复连接
    if (wsRef.current?.readyState === WebSocket.OPEN) return
    if (isConnecting) return
    
    setIsConnecting(true)
    setError(null)
    
    const wsUrl = `ws://${window.location.host}/ws/subagent/${encodeURIComponent(runtimeId)}${authToken ? `?token=${authToken}` : ''}`
    
    try {
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws
      
      ws.onopen = () => {
        console.log(`[useSubAgentStatus] WebSocket 已连接: ${runtimeId}`)
        setIsConnected(true)
        setIsConnecting(false)
        onConnect?.()
        
        // 启动心跳
        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send('ping')
          }
        }, 30000) // 30秒心跳
      }
      
      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data)
          
          switch (message.type) {
            case 'connected':
              // 初始连接成功
              if (message.data) {
                setStatus(message.data)
              }
              break
              
            case 'status_update':
              // 状态更新
              if (message.data) {
                setStatus(message.data)
                onStatusChange?.(message.data)
              }
              break
              
            case 'completed':
              // 任务完成
              if (message.data) {
                setStatus(message.data)
                onComplete?.(message.data)
              }
              // 延迟断开连接
              setTimeout(() => {
                cleanup()
                setIsConnected(false)
              }, 1000)
              break
              
            case 'error':
              // 服务器错误
              console.error('[useSubAgentStatus] 服务器错误:', message.error)
              setError(message.error || '服务器错误')
              onError?.(message.error || '服务器错误')
              break
              
            case 'pong':
              // 心跳响应，忽略
              break
          }
        } catch (err) {
          console.error('[useSubAgentStatus] 解析消息失败:', err)
        }
      }
      
      ws.onerror = (err) => {
        console.error('[useSubAgentStatus] WebSocket 错误:', err)
        setError('连接错误')
        setIsConnecting(false)
        onError?.('连接错误')
      }
      
      ws.onclose = (event) => {
        console.log(`[useSubAgentStatus] WebSocket 已关闭: ${runtimeId}, code=${event.code}`)
        setIsConnected(false)
        setIsConnecting(false)
        cleanup()
        onDisconnect?.()
        
        // 非正常关闭时尝试重连（除非任务已完成）
        if (event.code !== 1000 && event.code !== 4004) {
          reconnectTimerRef.current = setTimeout(() => {
            console.log(`[useSubAgentStatus] 尝试重连: ${runtimeId}`)
            connect()
          }, 3000) // 3秒后重连
        }
      }
      
    } catch (err) {
      console.error('[useSubAgentStatus] 创建 WebSocket 失败:', err)
      setError('创建连接失败')
      setIsConnecting(false)
    }
  }, [runtimeId, onStatusChange, onConnect, onDisconnect, onError, onComplete, cleanup])
  
  // 断开连接
  const disconnect = useCallback(() => {
    cleanup()
    setIsConnected(false)
    setStatus(null)
  }, [cleanup])
  
  // 重新连接
  const reconnect = useCallback(() => {
    disconnect()
    // 延迟一下再连接，避免立即重连
    setTimeout(connect, 100)
  }, [disconnect, connect])
  
  // 建立连接
  useEffect(() => {
    if (!runtimeId) {
      disconnect()
      return
    }
    
    connect()
    
    return () => {
      disconnect()
    }
  }, [runtimeId, connect, disconnect])
  
  // 组件卸载时清理
  useEffect(() => {
    return () => {
      cleanup()
    }
  }, [cleanup])
  
  return {
    status,
    isConnected,
    isConnecting,
    error,
    disconnect,
    reconnect
  }
}

export default useSubAgentStatus
