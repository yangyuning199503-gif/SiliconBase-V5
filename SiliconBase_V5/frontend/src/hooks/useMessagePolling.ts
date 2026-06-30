/**
 * useMessagePolling - 消息轮询 Hook
 * Phase 2 Week 4 - WebSocket 备用方案
 * 
 * 功能：
 * - 当 WebSocket 不可用时，使用轮询获取新消息
 * - 支持自动轮询和手动刷新
 * - 智能轮询间隔调整（有消息时加快，无消息时减慢）
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import { sessionAPI } from '../utils/api/session'
import type { Message } from '../types'

interface UseMessagePollingOptions {
  sessionId: string | null
  enabled?: boolean
  initialPollInterval?: number
  fastPollInterval?: number
  slowPollInterval?: number
}

interface UseMessagePollingReturn {
  isPolling: boolean
  lastPollTime: number | null
  pollCount: number
  newMessages: Message[]
  refresh: () => Promise<void>
  startPolling: () => void
  stopPolling: () => void
}

export function useMessagePolling({
  sessionId,
  enabled = true,
  initialPollInterval = 2000,  // 初始轮询间隔：2秒
  fastPollInterval = 1000,     // 快速轮询：1秒（有新消息时）
  slowPollInterval = 5000,     // 慢速轮询：5秒（长时间无消息时）
}: UseMessagePollingOptions): UseMessagePollingReturn {
  
  const [isPolling, setIsPolling] = useState(false)
  const [lastPollTime, setLastPollTime] = useState<number | null>(null)
  const [pollCount, setPollCount] = useState(0)
  const [newMessages, setNewMessages] = useState<Message[]>([])
  
  const pollIntervalRef = useRef(initialPollInterval)
  const lastMessageIdRef = useRef<string | null>(null)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const isMountedRef = useRef(true)
  
  // 执行轮询
  const poll = useCallback(async () => {
    if (!sessionId || !isMountedRef.current) return
    
    try {
      // 获取最新消息
      const response = await sessionAPI.getMessages({
        session_id: sessionId,
        limit: 10, // 只获取最新的10条
      })
      
      if (!isMountedRef.current) return
      
      setLastPollTime(Date.now())
      setPollCount(prev => prev + 1)
      
      // 检测新消息
      if (response.items.length > 0) {
        const latestMessage = response.items[0]
        
        // 如果有新消息
        if (lastMessageIdRef.current && latestMessage.id !== lastMessageIdRef.current) {
          // 找出所有新消息
          const lastIndex = response.items.findIndex(
            msg => msg.id === lastMessageIdRef.current
          )
          
          if (lastIndex > 0) {
            const newMsgs = response.items.slice(0, lastIndex)
            setNewMessages(prev => [...newMsgs, ...prev].slice(0, 50))
            
            // 有新消息，加快轮询速度
            pollIntervalRef.current = fastPollInterval
            console.log('[MessagePolling] 检测到新消息，加快轮询速度')
          }
        } else if (!lastMessageIdRef.current) {
          // 首次加载，只记录最新的消息ID
          pollIntervalRef.current = slowPollInterval
        }
        
        // 更新最后消息ID
        lastMessageIdRef.current = latestMessage.id || null
      }
      
      // 连续无新消息，减慢轮询速度
      if (pollCount > 0 && pollCount % 10 === 0) {
        pollIntervalRef.current = Math.min(
          pollIntervalRef.current * 1.2,
          slowPollInterval
        )
      }
      
    } catch (error) {
      console.error('[MessagePolling] 轮询失败:', error)
      // 出错时增加轮询间隔
      pollIntervalRef.current = Math.min(
        pollIntervalRef.current * 1.5,
        30000 // 最大30秒
      )
    }
  }, [sessionId, fastPollInterval, slowPollInterval, pollCount])
  
  // 手动刷新
  const refresh = useCallback(async () => {
    await poll()
  }, [poll])
  
  // 开始轮询
  const startPolling = useCallback(() => {
    if (!sessionId || isPolling) return
    
    setIsPolling(true)
    pollIntervalRef.current = initialPollInterval
    
    const scheduleNext = async () => {
      if (!isMountedRef.current) return
      
      await poll()
      
      if (isMountedRef.current && isPolling) {
        timeoutRef.current = setTimeout(scheduleNext, pollIntervalRef.current)
      }
    }
    
    scheduleNext()
    console.log('[MessagePolling] 开始轮询，间隔:', pollIntervalRef.current, 'ms')
  }, [sessionId, isPolling, poll, initialPollInterval])
  
  // 停止轮询
  const stopPolling = useCallback(() => {
    setIsPolling(false)
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current)
      timeoutRef.current = null
    }
    console.log('[MessagePolling] 停止轮询')
  }, [])
  
  // 监听 sessionId 变化
  useEffect(() => {
    if (enabled && sessionId) {
      lastMessageIdRef.current = null // 重置最后消息ID
      startPolling()
    } else {
      stopPolling()
    }
    
    return () => {
      stopPolling()
    }
  }, [sessionId, enabled, startPolling, stopPolling])
  
  // 组件卸载清理
  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
      stopPolling()
    }
  }, [stopPolling])
  
  return {
    isPolling,
    lastPollTime,
    pollCount,
    newMessages,
    refresh,
    startPolling,
    stopPolling,
  }
}

/**
 * 使用示例：
 * 
 * function ChatComponent() {
 *   const { currentSessionId } = useSessionStore()
 *   const { newMessages, isPolling, refresh } = useMessagePolling({
 *     sessionId: currentSessionId,
 *     enabled: !webSocketConnected, // WebSocket 断开时启用轮询
 *   })
 *   
 *   // 处理新消息
 *   useEffect(() => {
 *     if (newMessages.length > 0) {
 *       // 将新消息添加到消息列表
 *       newMessages.forEach(msg => addMessage(msg))
 *     }
 *   }, [newMessages])
 *   
 *   return (
 *     <div>
 *       {isPolling && <span>轮询中...</span>}
 *       <button onClick={refresh}>刷新</button>
 *     </div>
 *   )
 * }
 */

export default useMessagePolling
