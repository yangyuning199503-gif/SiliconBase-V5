/**
 * 消息关联思维流
 * 【Week 2】显示单条AI消息的思维过程
 */
import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { 
  BrainCircuit, X, ChevronDown, ChevronUp,
  Loader2, Wrench, CheckCircle, Terminal,
  Sparkles, Zap, Bot, Clock
} from 'lucide-react'
import { MessageAIStep } from '../types'
import { XSSProtection } from '../utils/xssProtection'

export interface MessageThinkingFlowProps {
  steps: MessageAIStep[]
  isOpen: boolean
  onClose: () => void
}

export function MessageThinkingFlow({ steps, isOpen, onClose }: MessageThinkingFlowProps) {
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set())
  
  if (!isOpen || steps.length === 0) return null
  
  const toggleStep = (id: string) => {
    setExpandedSteps(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }
  
  const getStepIcon = (type: string) => {
    const className = 'w-3.5 h-3.5'
    switch (type) {
      case 'thinking': return <Loader2 className={`${className} animate-spin`} />
      case 'tool': return <Wrench className={className} />
      case 'result': return <CheckCircle className={className} />
      case 'complete': return <Terminal className={className} />
      case 'planning': return <Sparkles className={className} />
      case 'analyzing': return <Zap className={className} />
      case 'delegating': return <Bot className={className} />
      default: return <BrainCircuit className={className} />
    }
  }
  
  const getStepColor = (type: string) => {
    switch (type) {
      case 'thinking': return { bg: 'bg-cyan-500/10', border: 'border-cyan-500/30', text: 'text-cyan-400' }
      case 'tool': return { bg: 'bg-amber-500/10', border: 'border-amber-500/30', text: 'text-amber-400' }
      case 'result': return { bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', text: 'text-emerald-400' }
      case 'complete': return { bg: 'bg-violet-500/10', border: 'border-violet-500/30', text: 'text-violet-400' }
      case 'planning': return { bg: 'bg-blue-500/10', border: 'border-blue-500/30', text: 'text-blue-400' }
      case 'analyzing': return { bg: 'bg-rose-500/10', border: 'border-rose-500/30', text: 'text-rose-400' }
      case 'delegating': return { bg: 'bg-indigo-500/10', border: 'border-indigo-500/30', text: 'text-indigo-400' }
      default: return { bg: 'bg-slate-500/10', border: 'border-slate-500/30', text: 'text-slate-400' }
    }
  }
  
  const getStepLabel = (type: string) => {
    switch (type) {
      case 'thinking': return '思考'
      case 'tool': return '工具'
      case 'result': return '结果'
      case 'complete': return '完成'
      case 'planning': return '规划'
      case 'analyzing': return '分析'
      case 'delegating': return '委派'
      default: return 'AI'
    }
  }
  
  // 计算总耗时
  const totalDuration = steps.reduce((sum, step) => sum + (step.metadata?.duration || 0), 0)
  
  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: 'auto' }}
          exit={{ opacity: 0, height: 0 }}
          className="mt-3 rounded-xl bg-slate-950/50 border border-white/10 overflow-hidden"
        >
          {/* 头部 */}
          <div className="px-3 py-2 border-b border-white/10 flex items-center justify-between bg-white/[0.02]">
            <div className="flex items-center gap-2">
              <BrainCircuit className="w-4 h-4 text-cyan-400" />
              <span className="text-sm font-medium text-slate-300">思考过程</span>
              <span className="px-1.5 py-0.5 bg-cyan-500/20 rounded text-[10px] text-cyan-400">
                {steps.length} 步
              </span>
              {totalDuration > 0 && (
                <span className="text-[10px] text-slate-500 flex items-center gap-0.5">
                  <Clock className="w-3 h-3" />
                  {(totalDuration / 1000).toFixed(1)}s
                </span>
              )}
            </div>
            <button
              onClick={onClose}
              className="p-1 rounded hover:bg-white/10 text-slate-500 hover:text-slate-300 transition-colors"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
          
          {/* 步骤列表 */}
          <div className="p-3 space-y-2 max-h-[300px] overflow-y-auto">
            {steps.map((step, index) => {
              const isExpanded = expandedSteps.has(step.id)
              const hasLongContent = step.content.length > 80
              const colors = getStepColor(step.type)
              
              return (
                <motion.div
                  key={step.id}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: index * 0.03 }}
                  className={`relative rounded-lg border ${colors.bg} ${colors.border}`}
                >
                  {/* 步骤头部 */}
                  <button
                    onClick={() => hasLongContent && toggleStep(step.id)}
                    className="w-full px-2.5 py-2 flex items-center gap-2 text-left"
                  >
                    <span className={`p-1 rounded ${colors.bg} ${colors.text}`}>
                      {getStepIcon(step.type)}
                    </span>
                    <span className={`text-[11px] font-medium ${colors.text}`}>
                      {getStepLabel(step.type)}
                    </span>
                    
                    {/* 元数据标签 */}
                    {step.metadata?.toolName && (
                      <span className="px-1 py-0.5 bg-amber-500/20 rounded text-[9px] text-amber-400">
                        {step.metadata.toolName}
                      </span>
                    )}
                    {step.metadata?.subagentName && (
                      <span className="px-1 py-0.5 bg-indigo-500/20 rounded text-[9px] text-indigo-400">
                        @{step.metadata.subagentName}
                      </span>
                    )}
                    
                    <span className="text-[9px] text-slate-600 font-mono ml-auto">
                      {new Date(step.timestamp).toLocaleTimeString('zh-CN', {
                        hour: '2-digit', minute: '2-digit', second: '2-digit'
                      })}
                    </span>
                    
                    {hasLongContent && (
                      <span className="text-[9px] text-slate-600">
                        {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                      </span>
                    )}
                  </button>
                  
                  {/* 步骤内容 */}
                  <div className="px-2.5 pb-2">
                    <div className={`text-[11px] leading-relaxed text-slate-400 font-mono
                                    ${isExpanded ? '' : 'line-clamp-2'}`}>
                      {XSSProtection.escape(step.content)}
                    </div>
                    
                    {/* 耗时信息 */}
                    {step.metadata?.duration && (
                      <div className="mt-1.5 flex items-center gap-1.5 text-[9px] text-slate-600">
                        <Clock className="w-3 h-3" />
                        <span>{(step.metadata.duration / 1000).toFixed(2)}s</span>
                      </div>
                    )}
                    
                    {hasLongContent && !isExpanded && (
                      <button
                        onClick={() => toggleStep(step.id)}
                        className="mt-1.5 text-[9px] text-cyan-500/70 hover:text-cyan-400 transition-colors"
                      >
                        展开详情...
                      </button>
                    )}
                  </div>
                  
                  {/* 连接线 */}
                  {index < steps.length - 1 && (
                    <div className="absolute left-4 -bottom-2 w-px h-2 bg-white/10" />
                  )}
                </motion.div>
              )
            })}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

export default MessageThinkingFlow
