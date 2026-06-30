/**
 * AI思维流预览条
 * 【Week 2】常驻显示AI思考状态，可嵌入到聊天界面
 */
import { motion } from 'framer-motion'
import { 
  BrainCircuit, Loader2, Wrench, CheckCircle, 
  Sparkles, Zap, Bot, Clock, ChevronRight
} from 'lucide-react'
import { XSSProtection } from '../utils/xssProtection'

export type PreviewStepType = 'thinking' | 'tool' | 'result' | 'complete' | 'execution_complete' | 'planning' | 'analyzing' | 'delegating' | 'idle'

export interface ThinkingPreviewBarProps {
  isProcessing: boolean
  currentStep?: {
    type: PreviewStepType
    content: string
    toolName?: string
    subagentName?: string
  }
  currentPhase?: string
  progress?: number
  estimatedTime?: number
  stepsCount?: number
  onExpand?: () => void
  className?: string
}

export function ThinkingPreviewBar({
  isProcessing,
  currentStep,
  currentPhase,
  progress,
  estimatedTime,
  stepsCount = 0,
  onExpand,
  className = ''
}: ThinkingPreviewBarProps) {
  
  // 获取图标
  const getIcon = () => {
    const type = currentStep?.type || 'idle'
    const className = 'w-4 h-4'
    
    switch (type) {
      case 'thinking': return <Loader2 className={`${className} animate-spin`} />
      case 'tool': return <Wrench className={className} />
      case 'result': return <CheckCircle className={className} />
      case 'planning': return <Sparkles className={className} />
      case 'analyzing': return <Zap className={className} />
      case 'delegating': return <Bot className={className} />
      default: return <BrainCircuit className={className} />
    }
  }
  
  // 获取颜色
  const getColors = () => {
    const type = currentStep?.type || 'idle'
    switch (type) {
      case 'thinking': return { text: 'text-cyan-400', bg: 'bg-cyan-500/10', border: 'border-cyan-500/30', bar: 'bg-cyan-400' }
      case 'tool': return { text: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/30', bar: 'bg-amber-400' }
      case 'result': return { text: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', bar: 'bg-emerald-400' }
      case 'complete': return { text: 'text-violet-400', bg: 'bg-violet-500/10', border: 'border-violet-500/30', bar: 'bg-violet-400' }
      case 'planning': return { text: 'text-blue-400', bg: 'bg-blue-500/10', border: 'border-blue-500/30', bar: 'bg-blue-400' }
      case 'analyzing': return { text: 'text-rose-400', bg: 'bg-rose-500/10', border: 'border-rose-500/30', bar: 'bg-rose-400' }
      case 'delegating': return { text: 'text-indigo-400', bg: 'bg-indigo-500/10', border: 'border-indigo-500/30', bar: 'bg-indigo-400' }
      default: return { text: 'text-slate-400', bg: 'bg-slate-500/10', border: 'border-slate-500/30', bar: 'bg-slate-400' }
    }
  }
  
  // 获取阶段标签
  const getPhaseLabel = () => {
    if (currentPhase) return currentPhase
    const type = currentStep?.type || 'idle'
    switch (type) {
      case 'thinking': return '思考中'
      case 'tool': return '调用工具'
      case 'result': return '处理结果'
      case 'complete': return '已完成'
      case 'planning': return '规划中'
      case 'analyzing': return '分析中'
      case 'delegating': return '委派中'
      default: return isProcessing ? '准备中' : '就绪'
    }
  }
  
  // 格式化时间
  const formatTime = (seconds?: number): string => {
    if (!seconds || seconds <= 0) return ''
    if (seconds < 60) return `${Math.ceil(seconds)}秒`
    if (seconds < 3600) return `${Math.ceil(seconds / 60)}分钟`
    return `${Math.floor(seconds / 3600)}小时${Math.ceil((seconds % 3600) / 60)}分钟`
  }
  
  const colors = getColors()
  const actualProgress = progress ?? (isProcessing ? Math.min((stepsCount / 10) * 100, 95) : 0)
  
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={`relative overflow-hidden rounded-xl border border-white/10 
                  bg-slate-900/90 backdrop-blur-xl shadow-lg cursor-pointer
                  hover:border-cyan-500/30 transition-all group ${className}`}
      onClick={onExpand}
    >
      {/* 顶部进度条 */}
      <div className="absolute top-0 left-0 right-0 h-0.5 bg-white/5">
        <motion.div 
          className={`h-full ${colors.bar}`}
          initial={{ width: 0 }}
          animate={{ width: `${actualProgress}%` }}
          transition={{ duration: 0.5 }}
        />
      </div>
      
      <div className="px-3 py-2.5 flex items-center gap-3">
        {/* 图标 */}
        <div className="relative flex-shrink-0">
          <div className={`w-9 h-9 rounded-lg ${colors.bg} ${colors.border} border 
                         flex items-center justify-center`}>
            {getIcon()}
          </div>
          {isProcessing && (
            <span className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 bg-cyan-400 rounded-full animate-pulse" />
          )}
        </div>
        
        {/* 内容区 */}
        <div className="flex-1 min-w-0">
          {/* 阶段标签 */}
          <div className="flex items-center gap-2 mb-0.5">
            <span className={`text-xs font-medium ${colors.text}`}>
              {getPhaseLabel()}
            </span>
            {estimatedTime && estimatedTime > 0 && (
              <span className="text-[10px] text-slate-500 flex items-center gap-0.5">
                <Clock className="w-3 h-3" />
                约{formatTime(estimatedTime)}
              </span>
            )}
          </div>
          
          {/* 当前步骤 */}
          <div className="text-sm text-slate-300 truncate">
            {currentStep?.content ? (
              <span className="flex items-center gap-1.5">
                {currentStep.toolName && (
                  <span className="text-[10px] px-1 py-0.5 bg-amber-500/20 rounded text-amber-400">
                    {currentStep.toolName}
                  </span>
                )}
                {currentStep.subagentName && (
                  <span className="text-[10px] px-1 py-0.5 bg-indigo-500/20 rounded text-indigo-400">
                    @{currentStep.subagentName}
                  </span>
                )}
                <span className="truncate">{XSSProtection.escape(currentStep.content.slice(0, 60))}</span>
                {currentStep.content.length > 60 && '...'}
              </span>
            ) : (
              <span className="text-slate-500">{isProcessing ? '正在准备...' : '等待您的输入...'}</span>
            )}
          </div>
          
          {/* 进度条 */}
          {stepsCount > 0 && (
            <div className="flex items-center gap-2 mt-1.5">
              <div className="flex-1 h-1 bg-white/5 rounded-full overflow-hidden">
                <div 
                  className={`h-full ${colors.bar} rounded-full transition-all duration-500`}
                  style={{ width: `${actualProgress}%` }}
                />
              </div>
              <span className="text-[10px] text-slate-500 font-mono">
                {Math.round(actualProgress)}%
              </span>
            </div>
          )}
        </div>
        
        {/* 右侧 */}
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {stepsCount > 0 && (
            <span className="px-2 py-0.5 bg-cyan-500/20 rounded-full text-xs text-cyan-400 font-medium">
              {stepsCount}
            </span>
          )}
          <ChevronRight className="w-4 h-4 text-slate-500 group-hover:text-cyan-400 transition-colors" />
        </div>
      </div>
      
      {/* 扫描线动画 */}
      {isProcessing && (
        <motion.div
          className="absolute inset-0 bg-gradient-to-r from-transparent via-cyan-400/5 to-transparent pointer-events-none"
          animate={{ x: ['-100%', '100%'] }}
          transition={{ duration: 2, repeat: Infinity, ease: 'linear' }}
        />
      )}
    </motion.div>
  )
}

export default ThinkingPreviewBar
