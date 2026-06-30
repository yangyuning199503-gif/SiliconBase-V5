/**
 * AI思维流面板 - 几何风格，可拖动，透明背景（增强XSS防护）
 * 【Week 2】增强版：支持实时预览条和进度显示
 */
import { useRef, useEffect, useState, useCallback, useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { 
  Bot, Loader2, Wrench, CheckCircle, Terminal, 
  X, Minus, GripVertical, BrainCircuit, Sparkles,
  ChevronRight, ChevronLeft, Clock, Zap
} from 'lucide-react'
import { XSSProtection } from '../utils/xssProtection'
import type { AIStep } from '../types'

// 【Week 2】步骤类型扩展
export type AIStepType = 'thinking' | 'tool' | 'result' | 'complete' | 'execution_complete' | 'planning' | 'analyzing' | 'delegating'

export interface AIChatPanelProps {
  steps: AIStep[]
  isProcessing: boolean
  currentPhase?: string        // 【Week 2】当前阶段
  progress?: number            // 【Week 2】总进度 0-100
  estimatedTime?: number       // 【Week 2】预估剩余时间(秒)
  onStepClick?: (step: AIStep) => void  // 【Week 2】点击步骤回调
}

export default function AIChatPanel({ 
  steps = [], 
  isProcessing = false,
  currentPhase,
  progress,
  estimatedTime,
  onStepClick
}: AIChatPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [minimized, setMinimized] = useState(true)
  const [showPanel, setShowPanel] = useState(true)
  const showPanelRef = useRef(showPanel)

  // 同步 showPanel 到 ref，避免自动显示 effect 依赖 showPanel
  useEffect(() => {
    showPanelRef.current = showPanel
  }, [showPanel])
  
  // 【Week 2】显示当前步骤索引（用于步骤导航）
  const [currentStepIndex, setCurrentStepIndex] = useState(0)
  
  // 拖动状态 - 初始位置为屏幕正中间（考虑面板宽度320px）
  const [position, setPosition] = useState(() => {
    const windowWidth = window.innerWidth
    const windowHeight = window.innerHeight
    const panelWidth = 320 // w-80 = 20rem = 320px
    // 居中计算：(屏幕宽度 - 面板宽度) / 2，再减去左侧导航栏宽度(64px)的一半偏移
    const centerX = (windowWidth - panelWidth) / 2 - 32
    const centerY = windowHeight / 2 - 200 // 垂直偏上一点
    return { x: Math.max(centerX, 80), y: Math.max(centerY, 100) }
  })
  const [isDragging, setIsDragging] = useState(false)
  const dragStart = useRef({ x: 0, y: 0 })
  const panelStart = useRef({ x: 0, y: 0 })

  // 自动滚动到最新步骤
  useEffect(() => {
    if (scrollRef.current && !minimized) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [steps, minimized])

  // 步骤导航：滚动到当前选中步骤
  useEffect(() => {
    if (steps.length === 0) return
    const safeIndex = Math.min(Math.max(currentStepIndex, 0), steps.length - 1)
    if (safeIndex !== currentStepIndex) {
      setCurrentStepIndex(safeIndex)
    }
    const stepEl = scrollRef.current?.querySelectorAll('[data-step-index]')[safeIndex] as HTMLElement | undefined
    if (stepEl && scrollRef.current) {
      stepEl.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [currentStepIndex, steps.length])

  // 有步骤时自动显示（用户主动关闭后不应再次打扰）
  useEffect(() => {
    if (steps.length > 0 && !showPanelRef.current) {
      setShowPanel(true)
    }
  }, [steps])

  // 拖动逻辑
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('.no-drag')) return
    setIsDragging(true)
    dragStart.current = { x: e.clientX, y: e.clientY }
    panelStart.current = { ...position }
  }, [position])

  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (!isDragging) return
    const dx = e.clientX - dragStart.current.x
    const dy = e.clientY - dragStart.current.y
    setPosition({
      x: panelStart.current.x + dx,
      y: panelStart.current.y + dy
    })
  }, [isDragging])

  const handleMouseUp = useCallback(() => {
    setIsDragging(false)
  }, [])

  useEffect(() => {
    if (isDragging) {
      window.addEventListener('mousemove', handleMouseMove)
      window.addEventListener('mouseup', handleMouseUp)
    }
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isDragging, handleMouseMove, handleMouseUp])

  const toggleExpand = (id: string) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // 【Week 2】获取步骤图标
  const getStepIcon = (type: AIStepType, className = 'w-3 h-3') => {
    switch (type) {
      case 'thinking': return <Loader2 className={`${className} animate-spin`} />
      case 'tool': return <Wrench className={className} />
      case 'result': return <CheckCircle className={className} />
      case 'complete': return <Terminal className={className} />
      case 'planning': return <Sparkles className={className} />
      case 'analyzing': return <Zap className={className} />
      case 'delegating': return <Bot className={className} />
      default: return <Bot className={className} />
    }
  }

  // 【Week 2】获取步骤颜色
  const getStepColor = (type: AIStepType) => {
    switch (type) {
      case 'thinking': return { bg: 'bg-cyan-500/10', border: 'border-cyan-500/30', text: 'text-cyan-400', glow: 'shadow-cyan-500/20', bar: 'bg-cyan-400' }
      case 'tool': return { bg: 'bg-amber-500/10', border: 'border-amber-500/30', text: 'text-amber-400', glow: 'shadow-amber-500/20', bar: 'bg-amber-400' }
      case 'result': return { bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', text: 'text-emerald-400', glow: 'shadow-emerald-500/20', bar: 'bg-emerald-400' }
      case 'complete': return { bg: 'bg-violet-500/10', border: 'border-violet-500/30', text: 'text-violet-400', glow: 'shadow-violet-500/20', bar: 'bg-violet-400' }
      case 'planning': return { bg: 'bg-blue-500/10', border: 'border-blue-500/30', text: 'text-blue-400', glow: 'shadow-blue-500/20', bar: 'bg-blue-400' }
      case 'analyzing': return { bg: 'bg-rose-500/10', border: 'border-rose-500/30', text: 'text-rose-400', glow: 'shadow-rose-500/20', bar: 'bg-rose-400' }
      case 'delegating': return { bg: 'bg-indigo-500/10', border: 'border-indigo-500/30', text: 'text-indigo-400', glow: 'shadow-indigo-500/20', bar: 'bg-indigo-400' }
      default: return { bg: 'bg-white/5', border: 'border-white/10', text: 'text-slate-400', glow: 'shadow-white/10', bar: 'bg-slate-400' }
    }
  }

  // 【Week 2】获取步骤标签
  const getStepLabel = (type: AIStepType) => {
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

  // 【Week 2】格式化预估时间
  const formatEstimatedTime = (seconds?: number): string => {
    if (!seconds || seconds <= 0) return ''
    if (seconds < 60) return `${Math.ceil(seconds)}秒`
    if (seconds < 3600) return `${Math.ceil(seconds / 60)}分钟`
    return `${Math.floor(seconds / 3600)}小时${Math.ceil((seconds % 3600) / 60)}分钟`
  }

  // 【Week 2】获取当前活跃的步骤
  const currentStep = useMemo(() => {
    if (steps.length === 0) return null
    // 找到最后一个非完成的步骤
    for (let i = steps.length - 1; i >= 0; i--) {
      if (steps[i].type !== 'complete') {
        return steps[i]
      }
    }
    return steps[steps.length - 1]
  }, [steps])

  // 【Week 2】计算实际进度
  const actualProgress = useMemo(() => {
    if (progress !== undefined) return progress
    if (steps.length === 0) return 0
    const completeSteps = steps.filter(s => s.type === 'complete').length
    return Math.min((completeSteps / Math.max(steps.length, 1)) * 100, 99)
  }, [progress, steps])

  // 不显示面板时，显示恢复按钮（左下角）
  if (!showPanel) {
    return (
      <motion.button
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{ opacity: 1, scale: 1 }}
        onClick={() => setShowPanel(true)}
        className="fixed bottom-4 left-4 z-40 
                   flex items-center gap-2 px-3 py-2 
                   bg-slate-900/60 backdrop-blur-sm 
                   border border-white/10 rounded-lg
                   text-xs text-slate-400 hover:text-white
                   hover:border-white/20 transition-all
                   shadow-lg"
      >
        <BrainCircuit className="w-4 h-4 text-cyan-400" />
        <span>思维流</span>
        {steps.length > 0 && (
          <span className="ml-1 px-1.5 py-0.5 bg-cyan-500/20 rounded text-[10px] text-cyan-400">
            {steps.length}
          </span>
        )}
      </motion.button>
    )
  }

  // 【Week 2】最小化状态 - 增强版预览条
  if (minimized) {
    const colors = currentStep ? getStepColor(currentStep.type) : getStepColor('thinking')
    
    return (
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="fixed bottom-20 z-50"
        style={{ left: '80px', minWidth: '280px' }}
      >
        <div 
          className="relative overflow-hidden
                     bg-slate-900/90 backdrop-blur-xl
                     border border-white/10 rounded-xl
                     shadow-2xl hover:border-cyan-500/30 
                     transition-all cursor-pointer group"
          onClick={() => setMinimized(false)}
        >
          {/* 【Week 2】进度条背景 */}
          <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-white/5">
            <motion.div 
              className={`h-full ${colors.bar}`}
              initial={{ width: 0 }}
              animate={{ width: `${actualProgress}%` }}
              transition={{ duration: 0.5, ease: 'easeOut' }}
            />
          </div>
          
          <div className="px-3 py-2.5 flex items-center gap-3">
            {/* 【Week 2】动态图标 */}
            <div className="relative flex-shrink-0">
              <div className={`w-8 h-8 rounded-lg ${colors.bg} ${colors.border} border 
                             flex items-center justify-center`}>
                {currentStep ? getStepIcon(currentStep.type, 'w-4 h-4') : 
                  <BrainCircuit className="w-4 h-4 text-cyan-400" />}
              </div>
              {isProcessing && (
                <span className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 bg-cyan-400 rounded-full animate-pulse" />
              )}
            </div>
            
            {/* 【Week 2】中间内容区 */}
            <div className="flex-1 min-w-0">
              {/* 阶段标签 */}
              <div className="flex items-center gap-2 mb-0.5">
                <span className={`text-[10px] font-medium ${colors.text}`}>
                  {currentPhase || (currentStep ? getStepLabel(currentStep.type) : isProcessing ? '思考中' : '就绪')}
                </span>
                {estimatedTime && estimatedTime > 0 && (
                  <span className="text-[9px] text-slate-500 flex items-center gap-0.5">
                    <Clock className="w-2.5 h-2.5" />
                    约{formatEstimatedTime(estimatedTime)}
                  </span>
                )}
              </div>
              
              {/* 【Week 2】当前步骤预览 */}
              <div className="text-xs text-slate-300 truncate">
                {currentStep ? (
                  <span className="flex items-center gap-1">
                    {currentStep.metadata?.toolName && (
                      <span className="text-amber-400">[{currentStep.metadata.toolName}]</span>
                    )}
                    {currentStep.metadata?.subagentName && (
                      <span className="text-indigo-400">@{currentStep.metadata.subagentName}</span>
                    )}
                    <span className="truncate">{XSSProtection.escape(currentStep.content.slice(0, 50))}</span>
                    {currentStep.content.length > 50 && '...'}
                  </span>
                ) : (
                  <span className="text-slate-500">{isProcessing ? '准备中...' : '等待输入...'}</span>
                )}
              </div>
              
              {/* 【Week 2】进度文本 */}
              {steps.length > 0 && (
                <div className="flex items-center gap-2 mt-1">
                  <div className="flex-1 h-1 bg-white/5 rounded-full overflow-hidden">
                    <div 
                      className={`h-full ${colors.bar} rounded-full`}
                      style={{ width: `${actualProgress}%` }}
                    />
                  </div>
                  <span className="text-[9px] text-slate-500 font-mono">
                    {Math.round(actualProgress)}%
                  </span>
                </div>
              )}
            </div>
            
            {/* 【Week 2】右侧操作区 */}
            <div className="flex items-center gap-1 flex-shrink-0">
              {/* 步骤数 */}
              {steps.length > 0 && (
                <span className="px-1.5 py-0.5 bg-cyan-500/20 rounded text-[10px] text-cyan-400 font-medium">
                  {steps.length}
                </span>
              )}
              
              {/* 展开按钮 */}
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  setMinimized(false)
                }}
                className="p-1.5 rounded-lg hover:bg-white/10 
                           text-slate-500 hover:text-cyan-400 
                           transition-colors"
                title="展开面板"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
          
          {/* 【Week 2】动画扫描线效果 */}
          {isProcessing && (
            <motion.div
              className="absolute inset-0 bg-gradient-to-r from-transparent via-cyan-400/5 to-transparent"
              animate={{ x: ['-100%', '100%'] }}
              transition={{ duration: 2, repeat: Infinity, ease: 'linear' }}
            />
          )}
        </div>
      </motion.div>
    )
  }

  return (
    <motion.div
      ref={panelRef}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      style={{ 
        position: 'fixed', 
        left: position.x || 16, 
        top: position.y || 100,
        zIndex: 50 
      }}
      className={`w-80 ${isDragging ? 'cursor-grabbing' : 'cursor-grab'}`}
      onMouseDown={handleMouseDown}
    >
      {/* 几何边框背景 */}
      <div className="relative">
        {/* 背景网格线 */}
        <div className="absolute inset-0 overflow-hidden rounded-xl pointer-events-none opacity-30">
          <svg width="100%" height="100%" className="absolute inset-0">
            <defs>
              <pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">
                <path d="M 20 0 L 0 0 0 20" fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth="0.5"/>
              </pattern>
            </defs>
            <rect width="100%" height="100%" fill="url(#grid)" />
          </svg>
        </div>

        {/* 主容器 - 几何切割风格 */}
        <div className="relative bg-slate-950/40 backdrop-blur-xl border border-white/10 rounded-xl overflow-hidden"
             style={{ clipPath: 'polygon(0 0, calc(100% - 20px) 0, 100% 20px, 100% 100%, 20px 100%, 0 calc(100% - 20px))' }}>
          
          {/* 装饰角标 */}
          <div className="absolute top-0 left-0 w-4 h-4 border-t border-l border-cyan-500/50" />
          <div className="absolute top-0 right-0 w-4 h-4 border-t border-r border-cyan-500/50" style={{ transform: 'translateX(20px)' }} />
          <div className="absolute bottom-0 left-0 w-4 h-4 border-b border-l border-cyan-500/50" />
          <div className="absolute bottom-0 right-0 w-4 h-4 border-b border-r border-cyan-500/50" />

          {/* 头部 - 可拖动区域 */}
          <div className="px-3 py-2.5 border-b border-white/5 flex items-center justify-between bg-white/[0.02]">
            <div className="flex items-center gap-2">
              <GripVertical className="w-4 h-4 text-slate-600" />
              <div className="relative">
                <BrainCircuit className="w-4 h-4 text-cyan-400" />
                {isProcessing && (
                  <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 bg-cyan-400 rounded-full animate-pulse" />
                )}
              </div>
              <span className="text-xs font-medium text-slate-300 tracking-wide">AI THINKING</span>
            </div>
            
            <div className="flex items-center gap-0.5 no-drag">
              <button
                onClick={() => setMinimized(true)}
                className="p-1.5 rounded hover:bg-white/10 text-slate-500 hover:text-slate-300 transition-colors"
                title="最小化"
              >
                <Minus className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => setShowPanel(false)}
                className="p-1.5 rounded hover:bg-white/10 text-slate-500 hover:text-red-400 transition-colors"
                title="关闭"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          {/* 步骤导航 */}
          {steps.length > 0 && (
            <div className="px-3 py-1.5 border-b border-white/5 bg-white/[0.02] flex items-center justify-between no-drag">
              <button
                onClick={() => setCurrentStepIndex(i => Math.max(0, i - 1))}
                disabled={currentStepIndex <= 0}
                className="p-1 rounded hover:bg-white/10 text-slate-400 hover:text-white disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
              >
                <ChevronLeft className="w-3.5 h-3.5" />
              </button>
              <span className="text-[10px] text-slate-400 font-mono">
                STEP {currentStepIndex + 1} / {steps.length}
              </span>
              <button
                onClick={() => setCurrentStepIndex(i => Math.min(steps.length - 1, i + 1))}
                disabled={currentStepIndex >= steps.length - 1}
                className="p-1 rounded hover:bg-white/10 text-slate-400 hover:text-white disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
              >
                <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </div>
          )}

          {/* 内容区 */}
          <div 
            ref={scrollRef}
            className="max-h-[50vh] overflow-y-auto p-3 space-y-2 scrollbar-thin"
          >
            {steps.length === 0 ? (
              <div className="py-8 flex flex-col items-center justify-center text-slate-600">
                <div className="relative mb-3">
                  <div className="w-10 h-10 rounded-lg bg-slate-900/80 border border-white/5 flex items-center justify-center">
                    <Bot className="w-5 h-5 opacity-40" />
                  </div>
                  <div className="absolute -inset-1 border border-cyan-500/20 rounded-lg animate-pulse" />
                </div>
                <p className="text-[11px] text-slate-500 font-mono">WAITING FOR INPUT...</p>
              </div>
            ) : (
              <AnimatePresence mode="popLayout">
                {steps.map((step, index) => {
                  const isExpanded = expanded.has(step.id)
                  const hasLongContent = step.content.length > 100
                  const colors = getStepColor(step.type)
                  const isLatest = index === steps.length - 1
                  
                  return (
                    <motion.div
                      key={step.id}
                      data-step-index={index}
                      layout
                      initial={{ opacity: 0, x: -10, scale: 0.95 }}
                      animate={{ opacity: 1, x: 0, scale: 1 }}
                      exit={{ opacity: 0, scale: 0.9 }}
                      transition={{ delay: index * 0.02, duration: 0.2 }}
                      className={`relative rounded-lg border ${colors.bg} ${colors.border} 
                                  ${isExpanded ? colors.glow : ''} 
                                  ${index === currentStepIndex ? 'ring-1 ring-cyan-500/40' : ''}
                                  ${isLatest && isProcessing ? 'ring-1 ring-cyan-500/30' : ''}
                                  shadow-sm hover:border-opacity-50 transition-all`}
                    >
                      {/* 【Week 2】头部 - 可点击 */}
                      <button
                        onClick={() => {
                          if (hasLongContent) toggleExpand(step.id)
                          onStepClick?.(step)
                        }}
                        className="w-full px-2.5 py-2 flex items-center gap-2 text-left no-drag group"
                      >
                        <span className={`p-1 rounded ${colors.bg} ${colors.text} group-hover:scale-110 transition-transform`}>
                          {getStepIcon(step.type)}
                        </span>
                        <span className={`text-[11px] font-medium ${colors.text}`}>
                          {getStepLabel(step.type)}
                        </span>
                        
                        {/* 【Week 2】元数据显示 */}
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
                            {isExpanded ? '▼' : '▶'}
                          </span>
                        )}
                      </button>

                      {/* 【Week 2】内容 - 经过XSS防护处理 */}
                      <div className="px-2.5 pb-2">
                        <div className={`text-[11px] leading-relaxed text-slate-400 font-mono
                                        ${isExpanded ? '' : 'line-clamp-2'}`}>
                          {XSSProtection.escape(step.content)}
                        </div>
                        
                        {/* 【Week 2】元数据详情 */}
                        {step.metadata?.duration && (
                          <div className="mt-1.5 flex items-center gap-2 text-[9px] text-slate-600">
                            <Clock className="w-3 h-3" />
                            <span>耗时: {(step.metadata.duration / 1000).toFixed(1)}s</span>
                          </div>
                        )}
                        
                        {hasLongContent && !isExpanded && (
                          <button
                            onClick={() => toggleExpand(step.id)}
                            className="mt-1.5 text-[9px] text-cyan-500/70 hover:text-cyan-400 transition-colors no-drag"
                          >
                            展开详情...
                          </button>
                        )}
                      </div>

                      {/* 步骤线 */}
                      {index < steps.length - 1 && (
                        <div className="absolute left-4 -bottom-2 w-px h-2 bg-white/10" />
                      )}
                      
                      {/* 【Week 2】最新步骤指示器 */}
                      {isLatest && isProcessing && (
                        <motion.div
                          className="absolute -right-1 -top-1 w-2 h-2 bg-cyan-400 rounded-full"
                          animate={{ scale: [1, 1.2, 1], opacity: [1, 0.7, 1] }}
                          transition={{ duration: 1.5, repeat: Infinity }}
                        />
                      )}
                    </motion.div>
                  )
                })}
              </AnimatePresence>
            )}
          </div>

          {/* 【Week 2】底部状态条 - 增强版 */}
          <div className="px-3 py-2 border-t border-white/5 bg-white/[0.02] space-y-1.5">
            {/* 进度条 */}
            {steps.length > 0 && (
              <div className="flex items-center gap-2">
                <div className="flex-1 h-1 bg-white/5 rounded-full overflow-hidden">
                  <motion.div 
                    className="h-full bg-gradient-to-r from-cyan-500 to-blue-500 rounded-full"
                    initial={{ width: 0 }}
                    animate={{ width: `${actualProgress}%` }}
                    transition={{ duration: 0.5 }}
                  />
                </div>
                <span className="text-[10px] text-slate-500 font-mono min-w-[3rem] text-right">
                  {Math.round(actualProgress)}%
                </span>
              </div>
            )}
            
            {/* 状态信息 */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className={`w-1.5 h-1.5 rounded-full ${isProcessing ? 'bg-cyan-400 animate-pulse' : 'bg-slate-600'}`} />
                <span className="text-[10px] text-slate-500 font-mono">
                  {currentPhase || (isProcessing ? 'PROCESSING...' : 'IDLE')}
                </span>
                {estimatedTime && estimatedTime > 0 && (
                  <span className="text-[9px] text-slate-600 flex items-center gap-0.5">
                    <Clock className="w-2.5 h-2.5" />
                    约{formatEstimatedTime(estimatedTime)}
                  </span>
                )}
              </div>
              <span className="text-[10px] text-slate-600 font-mono">
                {steps.length} STEPS
              </span>
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  )
}
