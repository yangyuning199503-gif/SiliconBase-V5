/**
 * 流式事件查看器组件
 * 
 * 实时显示SubAgent的流式执行事件
 */
import React, { useRef, useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { 
  Brain, 
  Wrench, 
  CheckCircle2, 
  AlertCircle,
  Loader2,
  PauseCircle,
  PlayCircle,
  Terminal,
  ChevronDown,
  ChevronUp,
  Clock,
  Filter
} from 'lucide-react'
import type { StreamEvent, StreamEventType, StreamEventViewerProps } from '../types/subagent'

// 事件类型配置
const eventTypeConfig: Record<StreamEventType, { 
  icon: React.ReactNode
  label: string
  color: string
  bgColor: string
}> = {
  thought: {
    icon: <Brain className="w-4 h-4" />,
    label: '思考',
    color: 'text-cyan-400',
    bgColor: 'bg-cyan-500/10 border-cyan-500/20'
  },
  tool_call: {
    icon: <Wrench className="w-4 h-4" />,
    label: '工具调用',
    color: 'text-amber-400',
    bgColor: 'bg-amber-500/10 border-amber-500/20'
  },
  tool_result: {
    icon: <Terminal className="w-4 h-4" />,
    label: '工具结果',
    color: 'text-emerald-400',
    bgColor: 'bg-emerald-500/10 border-emerald-500/20'
  },
  progress: {
    icon: <Loader2 className="w-4 h-4" />,
    label: '进度',
    color: 'text-blue-400',
    bgColor: 'bg-blue-500/10 border-blue-500/20'
  },
  child_delegate: {
    icon: <ChevronDown className="w-4 h-4" />,
    label: '子代理',
    color: 'text-purple-400',
    bgColor: 'bg-purple-500/10 border-purple-500/20'
  },
  complete: {
    icon: <CheckCircle2 className="w-4 h-4" />,
    label: '完成',
    color: 'text-green-400',
    bgColor: 'bg-green-500/10 border-green-500/20'
  },
  error: {
    icon: <AlertCircle className="w-4 h-4" />,
    label: '错误',
    color: 'text-red-400',
    bgColor: 'bg-red-500/10 border-red-500/20'
  },
  paused: {
    icon: <PauseCircle className="w-4 h-4" />,
    label: '暂停',
    color: 'text-yellow-400',
    bgColor: 'bg-yellow-500/10 border-yellow-500/20'
  },
  resumed: {
    icon: <PlayCircle className="w-4 h-4" />,
    label: '恢复',
    color: 'text-emerald-400',
    bgColor: 'bg-emerald-500/10 border-emerald-500/20'
  }
}

// 单个事件组件
interface EventItemProps {
  event: StreamEvent
  isExpanded: boolean
  onToggle: () => void
  index: number
}

const EventItem: React.FC<EventItemProps> = ({ event, isExpanded, onToggle, index }) => {
  const config = eventTypeConfig[event.type] || eventTypeConfig.thought
  const timestamp = new Date(event.timestamp).toLocaleTimeString('zh-CN', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, delay: index * 0.02 }}
      className={`
        rounded-lg border p-3 transition-all duration-200
        ${config.bgColor}
        ${isExpanded ? 'ring-1 ring-white/10' : ''}
      `}
    >
      {/* 头部 */}
      <div 
        className="flex items-start gap-3 cursor-pointer"
        onClick={onToggle}
      >
        {/* 图标 */}
        <div className={`flex-shrink-0 ${config.color}`}>
          {config.icon}
        </div>

        {/* 内容 */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className={`text-xs font-medium ${config.color}`}>
              {config.label}
            </span>
            {event.agent_name && (
              <span className="text-xs text-slate-500">
                · {event.agent_name}
              </span>
            )}
            <span className="text-xs text-slate-600 ml-auto">
              {timestamp}
            </span>
          </div>
          
          <p className={`
            text-sm text-slate-300 
            ${isExpanded ? '' : 'line-clamp-2'}
          `}>
            {event.content}
          </p>
        </div>

        {/* 展开按钮 */}
        {event.data && Object.keys(event.data).length > 0 && (
          <button className="flex-shrink-0 text-slate-500 hover:text-white transition-colors">
            {isExpanded ? (
              <ChevronUp className="w-4 h-4" />
            ) : (
              <ChevronDown className="w-4 h-4" />
            )}
          </button>
        )}
      </div>

      {/* 展开的数据详情 */}
      <AnimatePresence>
        {isExpanded && event.data && Object.keys(event.data).length > 0 && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
            className="mt-3 pt-3 border-t border-white/10"
          >
            <pre className="text-xs text-slate-400 overflow-x-auto">
              {JSON.stringify(event.data, null, 2)}
            </pre>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

// 主组件
export const StreamEventViewer: React.FC<StreamEventViewerProps> = ({
  events,
  maxEvents = 100,
  autoScroll = true,
  filter,
  className = ''
}) => {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [expandedEvents, setExpandedEvents] = useState<Set<number>>(new Set())
  const [activeFilter, setActiveFilter] = useState<StreamEventType[]>(filter || [])
  const [isPaused, setIsPaused] = useState(false)

  // 过滤事件
  const filteredEvents = activeFilter.length > 0
    ? events.filter(e => activeFilter.includes(e.type))
    : events

  // 限制事件数量
  const displayedEvents = filteredEvents.slice(-maxEvents)

  // 自动滚动
  useEffect(() => {
    if (autoScroll && !isPaused && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [displayedEvents, autoScroll, isPaused])

  // 切换展开状态
  const toggleExpanded = (index: number) => {
    setExpandedEvents(prev => {
      const newSet = new Set(prev)
      if (newSet.has(index)) {
        newSet.delete(index)
      } else {
        newSet.add(index)
      }
      return newSet
    })
  }

  // 切换过滤器
  const toggleFilter = (type: StreamEventType) => {
    setActiveFilter(prev => {
      if (prev.includes(type)) {
        return prev.filter(t => t !== type)
      }
      return [...prev, type]
    })
  }

  // 清除过滤器
  const clearFilter = () => {
    setActiveFilter([])
  }

  return (
    <div className={`bg-slate-800/50 rounded-xl border border-white/10 ${className}`}>
      {/* 头部 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/10">
        <div className="flex items-center gap-2">
          <Terminal className="w-5 h-5 text-cyan-400" />
          <h3 className="text-white font-semibold">执行日志</h3>
          <span className="text-slate-500 text-xs">
            ({filteredEvents.length} 条事件)
          </span>
        </div>
        
        <div className="flex items-center gap-2">
          {/* 暂停按钮 */}
          <button
            onClick={() => setIsPaused(!isPaused)}
            className={`
              p-1.5 rounded-lg transition-colors
              ${isPaused ? 'bg-yellow-500/20 text-yellow-400' : 'hover:bg-slate-700/50 text-slate-400'}
            `}
            title={isPaused ? '继续滚动' : '暂停滚动'}
          >
            {isPaused ? <PlayCircle className="w-4 h-4" /> : <PauseCircle className="w-4 h-4" />}
          </button>

          {/* 过滤器按钮 */}
          <div className="relative group">
            <button
              className={`
                p-1.5 rounded-lg transition-colors flex items-center gap-1
                ${activeFilter.length > 0 ? 'bg-cyan-500/20 text-cyan-400' : 'hover:bg-slate-700/50 text-slate-400'}
              `}
            >
              <Filter className="w-4 h-4" />
              {activeFilter.length > 0 && (
                <span className="text-xs">{activeFilter.length}</span>
              )}
            </button>

            {/* 过滤器下拉菜单 */}
            <div className="absolute right-0 top-full mt-2 w-48 bg-slate-800 rounded-lg border border-white/10 shadow-xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-10">
              <div className="p-2">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs text-slate-400">过滤事件类型</span>
                  {activeFilter.length > 0 && (
                    <button
                      onClick={clearFilter}
                      className="text-xs text-cyan-400 hover:text-cyan-300"
                    >
                      清除
                    </button>
                  )}
                </div>
                {Object.entries(eventTypeConfig).map(([type, config]) => (
                  <button
                    key={type}
                    onClick={() => toggleFilter(type as StreamEventType)}
                    className={`
                      w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs
                      transition-colors
                      ${activeFilter.includes(type as StreamEventType) 
                        ? 'bg-slate-700 text-white' 
                        : 'text-slate-400 hover:bg-slate-700/50'}
                    `}
                  >
                    <span className={config.color}>{config.icon}</span>
                    <span>{config.label}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 事件列表 */}
      <div 
        ref={scrollRef}
        className="p-4 space-y-2 max-h-[400px] overflow-y-auto"
      >
        {displayedEvents.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-slate-500">
            <Clock className="w-12 h-12 mb-3 opacity-30" />
            <p className="text-sm">等待事件...</p>
            {activeFilter.length > 0 && (
              <p className="text-xs mt-1">过滤器可能隐藏了事件</p>
            )}
          </div>
        ) : (
          <AnimatePresence initial={false}>
            {displayedEvents.map((event, index) => (
              <EventItem
                key={`${event.timestamp}-${index}`}
                event={event}
                isExpanded={expandedEvents.has(index)}
                onToggle={() => toggleExpanded(index)}
                index={index}
              />
            ))}
          </AnimatePresence>
        )}
      </div>

      {/* 底部统计 */}
      {displayedEvents.length > 0 && (
        <div className="px-4 py-2 border-t border-white/10 flex items-center justify-between text-xs">
          <div className="flex items-center gap-3">
            {Object.entries(
              displayedEvents.reduce((acc, e) => {
                acc[e.type] = (acc[e.type] || 0) + 1
                return acc
              }, {} as Record<string, number>)
            ).slice(0, 4).map(([type, count]) => {
              const config = eventTypeConfig[type as StreamEventType]
              return (
                <div key={type} className="flex items-center gap-1">
                  <span className={config.color}>{config.icon}</span>
                  <span className="text-slate-500">{count}</span>
                </div>
              )
            })}
          </div>
          <span className="text-slate-600">
            显示最近 {displayedEvents.length} 条
          </span>
        </div>
      )}
    </div>
  )
}

export default StreamEventViewer
