/**
 * 智能干预建议组件
 * 【Week 4】当AI检测到需要干预的场景时，主动建议用户
 */
import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { 
  RefreshCw, PauseCircle, PlayCircle, 
  XCircle, Edit3, ChevronDown, Bot, BrainCircuit,
  TrendingUp, Clock, Wrench, Target, Zap, X
} from 'lucide-react'

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
}

export interface SmartInterventionSuggesterProps {
  suggestion: InterventionSuggestion
  onAccept: (suggestion: InterventionSuggestion) => void
  onIgnore: (suggestion: InterventionSuggestion) => void
  onSnooze: (suggestion: InterventionSuggestion, minutes: number) => void
  className?: string
}

export function SmartInterventionSuggester({
  suggestion,
  onAccept,
  onIgnore,
  onSnooze,
  className = ''
}: SmartInterventionSuggesterProps) {
  const [isExpanded, setIsExpanded] = useState(false)
  const [showSnoozeOptions, setShowSnoozeOptions] = useState(false)
  
  const getSuggestionConfig = (type: SuggestionType) => {
    switch (type) {
      case 'loop_detected':
        return {
          icon: <RefreshCw className="w-5 h-5" />,
          title: '检测到循环',
          color: 'text-orange-400',
          bgColor: 'bg-orange-500/10',
          borderColor: 'border-orange-500/30',
          gradient: 'from-orange-500/20 to-red-500/20'
        }
      case 'tool_failing':
        return {
          icon: <Wrench className="w-5 h-5" />,
          title: '工具多次失败',
          color: 'text-red-400',
          bgColor: 'bg-red-500/10',
          borderColor: 'border-red-500/30',
          gradient: 'from-red-500/20 to-pink-500/20'
        }
      case 'goal_drift':
        return {
          icon: <Target className="w-5 h-5" />,
          title: '目标偏离',
          color: 'text-purple-400',
          bgColor: 'bg-purple-500/10',
          borderColor: 'border-purple-500/30',
          gradient: 'from-purple-500/20 to-indigo-500/20'
        }
      case 'timeout_warning':
        return {
          icon: <Clock className="w-5 h-5" />,
          title: '执行超时',
          color: 'text-yellow-400',
          bgColor: 'bg-yellow-500/10',
          borderColor: 'border-yellow-500/30',
          gradient: 'from-yellow-500/20 to-orange-500/20'
        }
      case 'resource_exhausted':
        return {
          icon: <Zap className="w-5 h-5" />,
          title: '资源不足',
          color: 'text-rose-400',
          bgColor: 'bg-rose-500/10',
          borderColor: 'border-rose-500/30',
          gradient: 'from-rose-500/20 to-red-500/20'
        }
      default:
        return {
          icon: <BrainCircuit className="w-5 h-5" />,
          title: '智能建议',
          color: 'text-cyan-400',
          bgColor: 'bg-cyan-500/10',
          borderColor: 'border-cyan-500/30',
          gradient: 'from-cyan-500/20 to-blue-500/20'
        }
    }
  }
  
  const getActionConfig = (action: SuggestedAction) => {
    switch (action) {
      case 'PAUSE':
        return {
          icon: <PauseCircle className="w-4 h-4" />,
          label: '暂停检查',
          color: 'text-yellow-400',
          bgColor: 'bg-yellow-500/20 hover:bg-yellow-500/30'
        }
      case 'REPLAN':
        return {
          icon: <RefreshCw className="w-4 h-4" />,
          label: '重新规划',
          color: 'text-purple-400',
          bgColor: 'bg-purple-500/20 hover:bg-purple-500/30'
        }
      case 'ADJUST':
        return {
          icon: <Edit3 className="w-4 h-4" />,
          label: '调整方向',
          color: 'text-blue-400',
          bgColor: 'bg-blue-500/20 hover:bg-blue-500/30'
        }
      case 'CANCEL':
        return {
          icon: <XCircle className="w-4 h-4" />,
          label: '取消任务',
          color: 'text-red-400',
          bgColor: 'bg-red-500/20 hover:bg-red-500/30'
        }
      case 'CONTINUE':
        return {
          icon: <PlayCircle className="w-4 h-4" />,
          label: '继续观察',
          color: 'text-emerald-400',
          bgColor: 'bg-emerald-500/20 hover:bg-emerald-500/30'
        }
    }
  }
  
  const config = getSuggestionConfig(suggestion.type)
  const actionConfig = getActionConfig(suggestion.suggested_action)
  
  // 格式化元数据显示
  const formatMetadata = () => {
    const { metadata } = suggestion
    if (!metadata) return null
    
    const items = []
    
    if (metadata.round_count !== undefined) {
      items.push(`执行轮次: ${metadata.round_count}`)
    }
    if (metadata.tool_name) {
      items.push(`工具: ${metadata.tool_name} (失败${metadata.failure_count}次)`)
    }
    if (metadata.drift !== undefined) {
      items.push(`偏离度: ${(metadata.drift * 100).toFixed(0)}%`)
    }
    if (metadata.elapsed !== undefined && metadata.estimated !== undefined) {
      items.push(`用时: ${metadata.elapsed.toFixed(0)}s / 预估${metadata.estimated.toFixed(0)}s`)
    }
    if (metadata.memory_percent !== undefined) {
      items.push(`内存: ${metadata.memory_percent.toFixed(1)}%`)
    }
    if (metadata.cpu_percent !== undefined) {
      items.push(`CPU: ${metadata.cpu_percent.toFixed(1)}%`)
    }
    
    return items
  }
  
  const metadataItems = formatMetadata()
  
  return (
    <motion.div
      initial={{ opacity: 0, y: -20, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, x: 100, scale: 0.9 }}
      className={`relative overflow-hidden rounded-xl border ${config.borderColor} ${className}`}
    >
      {/* 渐变背景 */}
      <div className={`absolute inset-0 bg-gradient-to-br ${config.gradient} opacity-50`} />
      
      {/* 扫描线动画 */}
      <motion.div
        className="absolute inset-0 bg-gradient-to-r from-transparent via-white/10 to-transparent"
        animate={{ x: ['-100%', '100%'] }}
        transition={{ duration: 3, repeat: Infinity, ease: 'linear' }}
      />
      
      <div className="relative p-4">
        {/* 头部 */}
        <div className="flex items-start gap-3">
          {/* 图标 */}
          <div className={`flex-shrink-0 p-2 rounded-lg ${config.bgColor} ${config.color}`}>
            {config.icon}
          </div>
          
          {/* 内容 */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span className={`text-sm font-semibold ${config.color}`}>
                {config.title}
              </span>
              
              {/* 置信度徽章 */}
              <div className="flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-white/10">
                <TrendingUp className="w-3 h-3 text-slate-400" />
                <span className="text-[10px] text-slate-400">
                  {(suggestion.confidence * 100).toFixed(0)}% 置信度
                </span>
              </div>

              <button
                onClick={() => setIsExpanded(v => !v)}
                className="ml-auto p-1 rounded hover:bg-white/10 transition-colors"
                title={isExpanded ? '收起' : '展开'}
              >
                <ChevronDown className={`w-4 h-4 text-slate-400 transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
              </button>
            </div>
            
            <p className="text-sm text-slate-300 mb-2">
              {suggestion.reason}
            </p>
            
            {/* 元数据详情 */}
            {metadataItems && metadataItems.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-3">
                {metadataItems.map((item, index) => (
                  <span 
                    key={index}
                    className="px-2 py-0.5 rounded text-[10px] bg-white/5 text-slate-500"
                  >
                    {item}
                  </span>
                ))}
              </div>
            )}
            
            {/* 建议操作 */}
            <div className="flex items-center gap-2">
              <button
                onClick={() => onAccept(suggestion)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg 
                           text-xs font-medium transition-all ${actionConfig.bgColor} ${actionConfig.color}`}
              >
                {actionConfig.icon}
                {actionConfig.label}
              </button>
              
              <button
                onClick={() => setShowSnoozeOptions(!showSnoozeOptions)}
                className="px-3 py-1.5 rounded-lg text-xs text-slate-400 
                           hover:text-slate-300 hover:bg-white/5 transition-colors"
              >
                稍后提醒
              </button>
              
              <button
                onClick={() => onIgnore(suggestion)}
                className="p-1.5 rounded-lg text-slate-500 hover:text-slate-300 
                           hover:bg-white/5 transition-colors ml-auto"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            
            {/* 稍后提醒选项 */}
            <AnimatePresence>
              {showSnoozeOptions && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  className="flex items-center gap-2 mt-2 overflow-hidden"
                >
                  {[1, 5, 15].map(minutes => (
                    <button
                      key={minutes}
                      onClick={() => {
                        onSnooze(suggestion, minutes)
                        setShowSnoozeOptions(false)
                      }}
                      className="px-2 py-1 rounded text-[10px] bg-white/5 
                                 text-slate-400 hover:text-slate-300 
                                 hover:bg-white/10 transition-colors"
                    >
                      {minutes}分钟后
                    </button>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>

            {/* 展开详情 */}
            <AnimatePresence>
              {isExpanded && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  className="mt-3 pt-3 border-t border-white/5 overflow-hidden"
                >
                  <div className="space-y-1 text-[10px] text-slate-500">
                    {suggestion.target_runtime_id && (
                      <div><span className="text-slate-400">运行时ID:</span> {suggestion.target_runtime_id}</div>
                    )}
                    {suggestion.target_task_id && (
                      <div><span className="text-slate-400">任务ID:</span> {suggestion.target_task_id}</div>
                    )}
                    <div><span className="text-slate-400">检测时间:</span> {new Date(suggestion.timestamp).toLocaleString('zh-CN')}</div>
                    {suggestion.metadata?.threshold !== undefined && (
                      <div><span className="text-slate-400">阈值:</span> {suggestion.metadata.threshold}</div>
                    )}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
        
        {/* 底部提示 */}
        <div className="flex items-center gap-1 mt-3 pt-3 border-t border-white/5">
          <Bot className="w-3 h-3 text-slate-500" />
          <span className="text-[10px] text-slate-500">
            AI 检测到异常并建议干预
          </span>
        </div>
      </div>
    </motion.div>
  )
}

export interface SmartInterventionPanelProps {
  suggestions: InterventionSuggestion[]
  onAccept: (suggestion: InterventionSuggestion) => void
  onIgnore: (suggestion: InterventionSuggestion) => void
  onSnooze: (suggestion: InterventionSuggestion, minutes: number) => void
  className?: string
}

export function SmartInterventionPanel({
  suggestions,
  onAccept,
  onIgnore,
  onSnooze,
  className = ''
}: SmartInterventionPanelProps) {
  if (suggestions.length === 0) return null
  
  return (
    <div className={`space-y-3 ${className}`}>
      <div className="flex items-center gap-2 px-1">
        <BrainCircuit className="w-4 h-4 text-cyan-400" />
        <span className="text-sm font-medium text-slate-300">
          智能干预建议
        </span>
        <span className="px-1.5 py-0.5 rounded-full bg-cyan-500/20 text-[10px] text-cyan-400">
          {suggestions.length}
        </span>
      </div>
      
      <AnimatePresence mode="popLayout">
        {suggestions.map(suggestion => (
          <SmartInterventionSuggester
            key={suggestion.id}
            suggestion={suggestion}
            onAccept={onAccept}
            onIgnore={onIgnore}
            onSnooze={onSnooze}
          />
        ))}
      </AnimatePresence>
    </div>
  )
}

export default SmartInterventionPanel
