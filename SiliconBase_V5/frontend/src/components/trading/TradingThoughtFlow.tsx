/**
 * 交易思维流组件
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 * 显示AI交易决策的思维过程
 * 
 * 参考：components/ThinkingFlow.tsx
 */

import React from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { 
  Brain, 
  TrendingUp, 
  Newspaper, 
  Activity,
  Shield,
  CheckCircle2,
  AlertTriangle,
  XCircle,
} from 'lucide-react'

// 思维步骤类型
export type ThoughtStepType = 
  | 'market_analysis'    // 市场分析
  | 'news_check'         // 消息检查
  | 'indicator_check'    // 指标检查
  | 'risk_assessment'    // 风险评估
  | 'decision'           // 决策
  | 'execution'          // 执行
  | 'interrupted'        // 被拦截
  | 'rejected'           // 被拒绝

export interface ThoughtStep {
  id: string
  type: ThoughtStepType
  content: string
  timestamp: number
  details?: Record<string, any>
}

interface TradingThoughtFlowProps {
  steps: ThoughtStep[]
  className?: string
  maxHeight?: string
  isActive?: boolean
}

// 步骤类型配置
const STEP_TYPE_CONFIG: Record<ThoughtStepType, {
  label: string
  icon: React.ReactNode
  bgColor: string
  borderColor: string
  textColor: string
}> = {
  market_analysis: {
    label: '市场分析',
    icon: <Activity className="w-4 h-4" />,
    bgColor: 'bg-blue-900/30',
    borderColor: 'border-blue-700',
    textColor: 'text-blue-400'
  },
  news_check: {
    label: '消息检查',
    icon: <Newspaper className="w-4 h-4" />,
    bgColor: 'bg-amber-900/30',
    borderColor: 'border-amber-700',
    textColor: 'text-amber-400'
  },
  indicator_check: {
    label: '指标分析',
    icon: <TrendingUp className="w-4 h-4" />,
    bgColor: 'bg-purple-900/30',
    borderColor: 'border-purple-700',
    textColor: 'text-purple-400'
  },
  risk_assessment: {
    label: '风险评估',
    icon: <Shield className="w-4 h-4" />,
    bgColor: 'bg-orange-900/30',
    borderColor: 'border-orange-700',
    textColor: 'text-orange-400'
  },
  decision: {
    label: '交易决策',
    icon: <Brain className="w-4 h-4" />,
    bgColor: 'bg-cyan-900/30',
    borderColor: 'border-cyan-700',
    textColor: 'text-cyan-400'
  },
  execution: {
    label: '订单执行',
    icon: <CheckCircle2 className="w-4 h-4" />,
    bgColor: 'bg-green-900/30',
    borderColor: 'border-green-700',
    textColor: 'text-green-400'
  },
  interrupted: {
    label: '决策被拦截',
    icon: <AlertTriangle className="w-4 h-4" />,
    bgColor: 'bg-orange-900/30',
    borderColor: 'border-orange-700',
    textColor: 'text-orange-400'
  },
  rejected: {
    label: '决策被拒绝',
    icon: <XCircle className="w-4 h-4" />,
    bgColor: 'bg-red-900/30',
    borderColor: 'border-red-700',
    textColor: 'text-red-400'
  }
}

export const TradingThoughtFlow: React.FC<TradingThoughtFlowProps> = ({
  steps,
  className = '',
  maxHeight = '300px',
  isActive = false
}) => {
  const containerRef = React.useRef<HTMLDivElement>(null)
  
  // 自动滚动到最新
  React.useEffect(() => {
    if (containerRef.current && steps.length > 0) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [steps])

  if (steps.length === 0) {
    return (
      <div className={`bg-gray-800/50 rounded-xl border border-gray-700 p-4 ${className}`}>
        <div className="flex items-center gap-2 text-gray-500">
          <Brain className="w-5 h-5" />
          <span className="text-sm">等待AI分析...</span>
        </div>
        {isActive && (
          <motion.div 
            className="mt-2 h-1 bg-gray-700 rounded-full overflow-hidden"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
          >
            <motion.div
              className="h-full bg-cyan-400"
              animate={{ x: ['-100%', '100%'] }}
              transition={{ duration: 1.5, repeat: Infinity, ease: 'linear' }}
            />
          </motion.div>
        )}
      </div>
    )
  }

  return (
    <div 
      ref={containerRef}
      className={`bg-gray-800/50 rounded-xl border border-gray-700 overflow-hidden ${className}`}
      style={{ maxHeight }}
    >
      {/* 头部 */}
      <div className="sticky top-0 bg-gray-800/95 backdrop-blur-sm border-b border-gray-700 p-3 z-10">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Brain className="w-5 h-5 text-cyan-400" />
            <span className="text-sm font-medium text-gray-200">AI思维流</span>
            {isActive && (
              <span className="flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-2 w-2 rounded-full bg-cyan-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-cyan-500"></span>
              </span>
            )}
          </div>
          <span className="text-xs text-gray-500">{steps.length} 步</span>
        </div>
      </div>

      {/* 步骤列表 */}
      <div className="p-3 space-y-2">
        <AnimatePresence initial={false}>
          {steps.map((step, index) => {
            const config = STEP_TYPE_CONFIG[step.type]
            const time = new Date(step.timestamp).toLocaleTimeString('zh-CN', {
              hour: '2-digit',
              minute: '2-digit',
              second: '2-digit'
            })

            return (
              <motion.div
                key={step.id}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ 
                  delay: index * 0.03,
                  duration: 0.3,
                  ease: 'easeOut'
                }}
                className={`
                  flex gap-3 p-3 rounded-lg border
                  ${config.bgColor} ${config.borderColor}
                  hover:brightness-110 transition-all
                `}
              >
                {/* 图标 */}
                <div className={`flex-shrink-0 mt-0.5 ${config.textColor}`}>
                  {config.icon}
                </div>

                {/* 内容 */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`text-xs font-medium ${config.textColor}`}>
                      {config.label}
                    </span>
                    <span className="text-xs text-gray-500">{time}</span>
                  </div>
                  <p className="text-sm text-gray-200 leading-relaxed">
                    {step.content}
                  </p>
                  {step.details && Object.keys(step.details).length > 0 && (
                    <div className="mt-2 text-xs text-gray-400 bg-black/20 rounded p-2">
                      {Object.entries(step.details).map(([key, value]) => (
                        <div key={key} className="flex justify-between">
                          <span>{key}:</span>
                          <span className="text-gray-300">{String(value)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </motion.div>
            )
          })}
        </AnimatePresence>
      </div>
    </div>
  )
}

// 自定义Hook管理思维流状态
export function useTradingThoughtFlow() {
  const [steps, setSteps] = React.useState<ThoughtStep[]>([])
  const [isActive, setIsActive] = React.useState(false)

  const addStep = React.useCallback((step: Omit<ThoughtStep, 'id' | 'timestamp'>) => {
    const newStep: ThoughtStep = {
      ...step,
      id: `thought_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      timestamp: Date.now()
    }
    setSteps(prev => [...prev, newStep].slice(-50)) // 保留最近50条
  }, [])

  const clearSteps = React.useCallback(() => {
    setSteps([])
  }, [])

  const startFlow = React.useCallback(() => {
    setIsActive(true)
    setSteps([])
  }, [])

  const stopFlow = React.useCallback(() => {
    setIsActive(false)
  }, [])

  return {
    steps,
    isActive,
    addStep,
    clearSteps,
    startFlow,
    stopFlow
  }
}

export default TradingThoughtFlow
