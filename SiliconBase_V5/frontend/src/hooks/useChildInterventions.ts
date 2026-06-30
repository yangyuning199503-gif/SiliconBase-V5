/**
 * 子代理干预事件监听 Hook
 * 【Week 3】监听子代理干预通知并显示给父代理
 */
import { useState, useEffect, useCallback, useRef } from 'react'

export type InterventionType = 'PAUSE' | 'RESUME' | 'ADJUST' | 'REPLAN' | 'CANCEL'

export interface ChildIntervention {
  id: string
  child_id: string
  child_name: string
  intervention_type: InterventionType
  reason?: string
  timestamp: number
}

export interface UseChildInterventionsOptions {
  /** 新干预回调 */
  onNewIntervention?: (intervention: ChildIntervention) => void
  /** 最大保留数量 */
  maxInterventions?: number
  /** 自动清理时间（毫秒） */
  autoClearTimeout?: number
}

export interface UseChildInterventionsReturn {
  /** 干预事件列表 */
  interventions: ChildIntervention[]
  /** 添加干预事件（模拟或从WebSocket接收） */
  addIntervention: (intervention: Omit<ChildIntervention, 'id' | 'timestamp'>) => void
  /** 移除干预事件 */
  removeIntervention: (id: string) => void
  /** 清空所有干预事件 */
  clearInterventions: () => void
  /** 是否有未处理的干预 */
  hasInterventions: boolean
}

/**
 * 子代理干预事件监听 Hook
 * 
 * @param options - 配置选项
 * @returns 干预事件列表和控制函数
 * 
 * @example
 * ```tsx
 * const { interventions, addIntervention, removeIntervention } = useChildInterventions({
 *   onNewIntervention: (intervention) => {
 *     toast.info(`子代理 ${intervention.child_name} 被${intervention.intervention_type}`)
 *   }
 * })
 * ```
 */
export function useChildInterventions(
  options: UseChildInterventionsOptions = {}
): UseChildInterventionsReturn {
  const { 
    onNewIntervention, 
    maxInterventions = 10,
    autoClearTimeout = 5 * 60 * 1000 // 5分钟
  } = options
  
  const [interventions, setInterventions] = useState<ChildIntervention[]>([])
  const interventionIdRef = useRef(0)
  
  // 生成唯一ID
  const generateId = useCallback(() => {
    interventionIdRef.current += 1
    return `intervention_${Date.now()}_${interventionIdRef.current}`
  }, [])
  
  // 添加干预事件
  const addIntervention = useCallback((
    intervention: Omit<ChildIntervention, 'id' | 'timestamp'>
  ) => {
    const newIntervention: ChildIntervention = {
      ...intervention,
      id: generateId(),
      timestamp: Date.now()
    }
    
    setInterventions(prev => {
      // 限制最大数量
      const updated = [newIntervention, ...prev].slice(0, maxInterventions)
      return updated
    })
    
    onNewIntervention?.(newIntervention)
  }, [generateId, maxInterventions, onNewIntervention])
  
  // 移除干预事件
  const removeIntervention = useCallback((id: string) => {
    setInterventions(prev => prev.filter(i => i.id !== id))
  }, [])
  
  // 清空所有干预事件
  const clearInterventions = useCallback(() => {
    setInterventions([])
  }, [])
  
  // 自动清理过期的干预事件
  useEffect(() => {
    if (autoClearTimeout <= 0) return
    
    const interval = setInterval(() => {
      const now = Date.now()
      setInterventions(prev => 
        prev.filter(i => now - i.timestamp < autoClearTimeout)
      )
    }, 10000) // 每10秒检查一次
    
    return () => clearInterval(interval)
  }, [autoClearTimeout])
  
  // 监听全局事件（从WebSocket或其他来源）
  useEffect(() => {
    const handleChildIntervention = (event: CustomEvent<ChildIntervention>) => {
      addIntervention(event.detail)
    }
    
    // 监听自定义事件
    window.addEventListener('child_intervention', handleChildIntervention as EventListener)
    
    return () => {
      window.removeEventListener('child_intervention', handleChildIntervention as EventListener)
    }
  }, [addIntervention])
  
  const hasInterventions = interventions.length > 0
  
  return {
    interventions,
    addIntervention,
    removeIntervention,
    clearInterventions,
    hasInterventions
  }
}

export default useChildInterventions
