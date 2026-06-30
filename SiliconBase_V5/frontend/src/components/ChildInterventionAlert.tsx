/**
 * 子代理干预通知组件
 * 【Week 3】当子代理被干预时，在主聊天界面显示通知
 */
import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { 
  AlertTriangle, PauseCircle, PlayCircle, 
  XCircle, Edit3, ChevronRight, Bot, X
} from 'lucide-react'

export type InterventionType = 'PAUSE' | 'RESUME' | 'ADJUST' | 'REPLAN' | 'CANCEL'

export interface ChildIntervention {
  id: string
  child_id: string
  child_name: string
  intervention_type: InterventionType
  reason?: string
  timestamp: number
}

export interface ChildInterventionAlertProps {
  interventions: ChildIntervention[]
  onDismiss?: (id: string) => void
  onViewDetail?: (intervention: ChildIntervention) => void
  onInterveneOther?: (childId: string, action: InterventionType) => void
  className?: string
}

export function ChildInterventionAlert({
  interventions,
  onDismiss,
  onViewDetail,
  onInterveneOther,
  className = ''
}: ChildInterventionAlertProps) {
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  
  // 自动清理旧的通知（5分钟后）
  useEffect(() => {
    const now = Date.now()
    const timeout = 5 * 60 * 1000 // 5分钟
    
    interventions.forEach(intervention => {
      if (now - intervention.timestamp > timeout) {
        handleDismiss(intervention.id)
      }
    })
  }, [interventions])
  
  const handleDismiss = (id: string) => {
    setDismissed(prev => new Set(prev).add(id))
    onDismiss?.(id)
  }
  
  const getInterventionConfig = (type: InterventionType) => {
    switch (type) {
      case 'PAUSE':
        return {
          icon: <PauseCircle className="w-5 h-5" />,
          color: 'text-yellow-400',
          bgColor: 'bg-yellow-500/10',
          borderColor: 'border-yellow-500/30',
          label: '已暂停'
        }
      case 'RESUME':
        return {
          icon: <PlayCircle className="w-5 h-5" />,
          color: 'text-emerald-400',
          bgColor: 'bg-emerald-500/10',
          borderColor: 'border-emerald-500/30',
          label: '已恢复'
        }
      case 'CANCEL':
        return {
          icon: <XCircle className="w-5 h-5" />,
          color: 'text-red-400',
          bgColor: 'bg-red-500/10',
          borderColor: 'border-red-500/30',
          label: '已取消'
        }
      case 'ADJUST':
        return {
          icon: <Edit3 className="w-5 h-5" />,
          color: 'text-blue-400',
          bgColor: 'bg-blue-500/10',
          borderColor: 'border-blue-500/30',
          label: '已调整'
        }
      case 'REPLAN':
        return {
          icon: <AlertTriangle className="w-5 h-5" />,
          color: 'text-purple-400',
          bgColor: 'bg-purple-500/10',
          borderColor: 'border-purple-500/30',
          label: '重新规划'
        }
      default:
        return {
          icon: <Bot className="w-5 h-5" />,
          color: 'text-slate-400',
          bgColor: 'bg-slate-500/10',
          borderColor: 'border-slate-500/30',
          label: '干预'
        }
    }
  }
  
  const visibleInterventions = interventions.filter(i => !dismissed.has(i.id))
  
  if (visibleInterventions.length === 0) return null
  
  return (
    <div className={`space-y-2 ${className}`}>
      <AnimatePresence mode="popLayout">
        {visibleInterventions.map((intervention) => {
          const config = getInterventionConfig(intervention.intervention_type)
          
          return (
            <motion.div
              key={intervention.id}
              layout
              initial={{ opacity: 0, y: -20, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, x: 100, scale: 0.9 }}
              className={`relative overflow-hidden rounded-lg border ${config.borderColor} ${config.bgColor} p-3`}
            >
              {/* 扫描线动画 */}
              <motion.div
                className="absolute inset-0 bg-gradient-to-r from-transparent via-white/5 to-transparent"
                animate={{ x: ['-100%', '100%'] }}
                transition={{ duration: 2, repeat: Infinity, ease: 'linear' }}
              />
              
              <div className="relative flex items-start gap-3">
                {/* 图标 */}
                <div className={`flex-shrink-0 ${config.color}`}>
                  {config.icon}
                </div>
                
                {/* 内容 */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`text-sm font-medium ${config.color}`}>
                      子代理 {config.label}
                    </span>
                    <span className="text-xs text-slate-500">
                      @{intervention.child_name}
                    </span>
                  </div>
                  
                  {intervention.reason && (
                    <p className="text-xs text-slate-400 line-clamp-2 mb-2">
                      原因: {intervention.reason}
                    </p>
                  )}
                  
                  {/* 操作按钮 */}
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => onViewDetail?.(intervention)}
                      className="flex items-center gap-1 text-xs text-slate-400 hover:text-white transition-colors"
                    >
                      查看详情
                      <ChevronRight className="w-3 h-3" />
                    </button>
                    
                    {/* 快速干预其他子代理 */}
                    {intervention.intervention_type !== 'CANCEL' && (
                      <>
                        <span className="text-slate-600">|</span>
                        <button
                          onClick={() => onInterveneOther?.(intervention.child_id, 'PAUSE')}
                          className="text-xs text-yellow-400/70 hover:text-yellow-400 transition-colors"
                        >
                          暂停其他
                        </button>
                      </>
                    )}
                  </div>
                </div>
                
                {/* 关闭按钮 */}
                <button
                  onClick={() => handleDismiss(intervention.id)}
                  className="flex-shrink-0 p-1 rounded hover:bg-white/10 text-slate-500 hover:text-slate-300 transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </motion.div>
          )
        })}
      </AnimatePresence>
    </div>
  )
}

export default ChildInterventionAlert
