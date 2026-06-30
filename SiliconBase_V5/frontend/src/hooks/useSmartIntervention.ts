/**
 * 智能干预建议 Hook
 * 【Week 4】管理AI主动建议的干预
 */
import { useState, useEffect, useCallback, useRef } from 'react'

export type SuggestionType = 
  | 'loop_detected' 
  | 'tool_failing' 
  | 'goal_drift' 
  | 'timeout_warning' 
  | 'resource_exhausted'

export type SuggestedAction = 'PAUSE' | 'REPLAN' | 'ADJUST' | 'CANCEL' | 'CONTINUE'

export interface InterventionSuggestion {
  id: string
  type: SuggestionType
  reason: string
  confidence: number
  suggested_action: SuggestedAction
  target_runtime_id?: string
  target_task_id?: string
  metadata?: {
    round_count?: number
    threshold?: number
    tool_name?: string
    failure_count?: number
    elapsed?: number
    estimated?: number
    drift?: number
    memory_percent?: number
    cpu_percent?: number
  }
  timestamp: number
  accepted?: boolean
  dismissed?: boolean
}

export interface UseSmartInterventionOptions {
  /** 新建议回调 */
  onNewSuggestion?: (suggestion: InterventionSuggestion) => void
  /** 建议接受回调 */
  onSuggestionAccepted?: (suggestion: InterventionSuggestion) => void
  /** 建议忽略回调 */
  onSuggestionIgnored?: (suggestion: InterventionSuggestion) => void
  /** 最大保留建议数 */
  maxSuggestions?: number
  /** 自动清理时间（毫秒） */
  autoClearTimeout?: number
  /** 最低置信度阈值 */
  minConfidence?: number
}

export interface UseSmartInterventionReturn {
  /** 活跃建议列表 */
  suggestions: InterventionSuggestion[]
  /** 接受建议 */
  acceptSuggestion: (id: string) => void
  /** 忽略建议 */
  ignoreSuggestion: (id: string) => void
  /** 延迟提醒 */
  snoozeSuggestion: (id: string, minutes: number) => void
  /** 添加建议（模拟或从WebSocket接收） */
  addSuggestion: (suggestion: Omit<InterventionSuggestion, 'id' | 'timestamp'>) => void
  /** 清空所有建议 */
  clearSuggestions: () => void
  /** 是否有未处理的高置信度建议 */
  hasHighConfidenceSuggestions: boolean
  /** 统计信息 */
  stats: {
    total: number
    accepted: number
    ignored: number
    snoozed: number
  }
}

/**
 * 智能干预建议 Hook
 * 
 * @param options - 配置选项
 * @returns 建议列表和控制函数
 * 
 * @example
 * ```tsx
 * const { suggestions, acceptSuggestion, ignoreSuggestion } = useSmartIntervention({
 *   onNewSuggestion: (suggestion) => {
 *     toast.warning(`AI建议: ${suggestion.reason}`)
 *   },
 *   minConfidence: 0.7
 * })
 * ```
 */
export function useSmartIntervention(
  options: UseSmartInterventionOptions = {}
): UseSmartInterventionReturn {
  const {
    onNewSuggestion,
    onSuggestionAccepted,
    onSuggestionIgnored,
    maxSuggestions = 5,
    autoClearTimeout = 10 * 60 * 1000, // 10分钟
    minConfidence = 0.6
  } = options
  
  const [suggestions, setSuggestions] = useState<InterventionSuggestion[]>([])
  const [stats, setStats] = useState({ total: 0, accepted: 0, ignored: 0, snoozed: 0 })
  const suggestionIdRef = useRef(0)
  const snoozedSuggestions = useRef<Set<string>>(new Set())
  
  // 生成唯一ID
  const generateId = useCallback(() => {
    suggestionIdRef.current += 1
    return `smart_suggestion_${Date.now()}_${suggestionIdRef.current}`
  }, [])
  
  // 添加建议
  const addSuggestion = useCallback((
    suggestion: Omit<InterventionSuggestion, 'id' | 'timestamp'>
  ) => {
    // 过滤低置信度建议
    if (suggestion.confidence < minConfidence) {
      return
    }
    
    const newSuggestion: InterventionSuggestion = {
      ...suggestion,
      id: generateId(),
      timestamp: Date.now()
    }
    
    // 检查是否已被延迟
    if (snoozedSuggestions.current.has(newSuggestion.id)) {
      return
    }
    
    setSuggestions(prev => {
      // 检查是否已有类似建议（同类型、同目标）
      const similarExists = prev.some(s => 
        s.type === newSuggestion.type && 
        s.target_runtime_id === newSuggestion.target_runtime_id &&
        !s.dismissed && !s.accepted
      )
      
      if (similarExists) {
        return prev
      }
      
      const updated = [newSuggestion, ...prev].slice(0, maxSuggestions)
      return updated
    })
    
    setStats(prev => ({ ...prev, total: prev.total + 1 }))
    onNewSuggestion?.(newSuggestion)
  }, [generateId, maxSuggestions, minConfidence, onNewSuggestion])
  
  // 接受建议
  const acceptSuggestion = useCallback((id: string) => {
    setSuggestions(prev => 
      prev.map(s => s.id === id ? { ...s, accepted: true } : s)
    )
    setStats(prev => ({ ...prev, accepted: prev.accepted + 1 }))
    
    const suggestion = suggestions.find(s => s.id === id)
    if (suggestion) {
      onSuggestionAccepted?.(suggestion)
    }
  }, [suggestions, onSuggestionAccepted])
  
  // 忽略建议
  const ignoreSuggestion = useCallback((id: string) => {
    setSuggestions(prev => 
      prev.map(s => s.id === id ? { ...s, dismissed: true } : s)
    )
    setStats(prev => ({ ...prev, ignored: prev.ignored + 1 }))
    
    const suggestion = suggestions.find(s => s.id === id)
    if (suggestion) {
      onSuggestionIgnored?.(suggestion)
    }
  }, [suggestions, onSuggestionIgnored])
  
  // 延迟提醒
  const snoozeSuggestion = useCallback((id: string, minutes: number) => {
    snoozedSuggestions.current.add(id)
    setStats(prev => ({ ...prev, snoozed: prev.snoozed + 1 }))
    
    // 延迟后恢复
    setTimeout(() => {
      snoozedSuggestions.current.delete(id)
      const suggestion = suggestions.find(s => s.id === id)
      if (suggestion && !suggestion.accepted && !suggestion.dismissed) {
        // 重新触发建议
        addSuggestion(suggestion)
      }
    }, minutes * 60 * 1000)
    
    // 暂时从列表中移除
    setSuggestions(prev => prev.filter(s => s.id !== id))
  }, [suggestions, addSuggestion])
  
  // 清空所有建议
  const clearSuggestions = useCallback(() => {
    setSuggestions([])
  }, [])
  
  // 自动清理过期建议
  useEffect(() => {
    if (autoClearTimeout <= 0) return
    
    const interval = setInterval(() => {
      const now = Date.now()
      setSuggestions(prev => 
        prev.filter(s => {
          // 保留已接受或已忽略的建议（用于统计）
          if (s.accepted || s.dismissed) {
            return now - s.timestamp < autoClearTimeout * 2  // 统计信息保留更久
          }
          return now - s.timestamp < autoClearTimeout
        })
      )
    }, 30000) // 每30秒检查一次
    
    return () => clearInterval(interval)
  }, [autoClearTimeout])
  
  // 监听全局智能建议事件（从WebSocket或其他来源）
  useEffect(() => {
    const handleSmartSuggestion = (event: CustomEvent<InterventionSuggestion>) => {
      addSuggestion(event.detail)
    }
    
    window.addEventListener('smart_intervention_suggestion', handleSmartSuggestion as EventListener)
    
    return () => {
      window.removeEventListener('smart_intervention_suggestion', handleSmartSuggestion as EventListener)
    }
  }, [addSuggestion])
  
  // 计算高置信度建议
  const hasHighConfidenceSuggestions = suggestions.some(
    s => s.confidence > 0.8 && !s.accepted && !s.dismissed
  )
  
  // 只返回未处理的活跃建议
  const activeSuggestions = suggestions.filter(
    s => !s.accepted && !s.dismissed
  )
  
  return {
    suggestions: activeSuggestions,
    acceptSuggestion,
    ignoreSuggestion,
    snoozeSuggestion,
    addSuggestion,
    clearSuggestions,
    hasHighConfidenceSuggestions,
    stats
  }
}

export default useSmartIntervention
