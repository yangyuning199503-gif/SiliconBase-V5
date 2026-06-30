/**
 * SubAgent流水线面板组件
 * 
 * 展示SubAgent流水线的执行进度和状态
 */
import React from 'react'
import { motion } from 'framer-motion'
import { 
  Workflow, 
  ChevronRight, 
  CheckCircle2, 
  XCircle, 
  Loader2,
  Clock,
  SkipForward,
  Play,
  PauseCircle
} from 'lucide-react'
import type { 
  PipelineStep, 
  PipelineStepStatus,
  SubAgentPipelinePanelProps 
} from '../types/subagent'

// 获取状态配置
const getStatusConfig = (status: PipelineStepStatus) => {
  switch (status) {
    case 'running':
      return {
        icon: <Loader2 className="w-4 h-4 animate-spin" />,
        label: '执行中',
        color: 'text-emerald-400',
        bgColor: 'bg-emerald-500/10 border-emerald-500/30',
        dotColor: 'bg-emerald-400'
      }
    case 'completed':
      return {
        icon: <CheckCircle2 className="w-4 h-4" />,
        label: '已完成',
        color: 'text-blue-400',
        bgColor: 'bg-blue-500/10 border-blue-500/30',
        dotColor: 'bg-blue-400'
      }
    case 'failed':
      return {
        icon: <XCircle className="w-4 h-4" />,
        label: '失败',
        color: 'text-red-400',
        bgColor: 'bg-red-500/10 border-red-500/30',
        dotColor: 'bg-red-400'
      }
    case 'skipped':
      return {
        icon: <SkipForward className="w-4 h-4" />,
        label: '已跳过',
        color: 'text-slate-400',
        bgColor: 'bg-slate-500/10 border-slate-500/30',
        dotColor: 'bg-slate-400'
      }
    case 'paused':
      return {
        icon: <PauseCircle className="w-4 h-4" />,
        label: '已暂停',
        color: 'text-yellow-400',
        bgColor: 'bg-yellow-500/10 border-yellow-500/30',
        dotColor: 'bg-yellow-400'
      }
    default:
      return {
        icon: <Clock className="w-4 h-4" />,
        label: '等待中',
        color: 'text-slate-500',
        bgColor: 'bg-slate-700/30 border-slate-600/30',
        dotColor: 'bg-slate-500'
      }
  }
}

// 步骤类型标签
const getStepTypeLabel = (type: PipelineStep['step_type']) => {
  switch (type) {
    case 'parallel':
      return '并行'
    case 'conditional':
      return '条件'
    default:
      return '顺序'
  }
}

// 单个步骤卡片
interface StepCardProps {
  step: PipelineStep
  isActive: boolean
  isLast: boolean
  onClick?: () => void
  onPause?: (stepId: string) => void      // 【新增】暂停
  onResume?: (stepId: string) => void     // 【新增】恢复
  onAdjust?: (stepId: string) => void     // 【新增】调整
  onCancel?: (stepId: string) => void     // 【新增】取消
}

const StepCard: React.FC<StepCardProps> = ({ 
  step, 
  isActive, 
  isLast, 
  onClick,
  onPause,
  onResume,
  onAdjust,
  onCancel
}) => {
  const config = getStatusConfig(step.status)
  
  // 【新增】处理干预操作
  const handlePause = (e: React.MouseEvent) => {
    e.stopPropagation()
    onPause?.(step.step_id)
  }
  
  const handleResume = (e: React.MouseEvent) => {
    e.stopPropagation()
    onResume?.(step.step_id)
  }
  
  const handleAdjust = (e: React.MouseEvent) => {
    e.stopPropagation()
    onAdjust?.(step.step_id)
  }
  
  const handleCancel = (e: React.MouseEvent) => {
    e.stopPropagation()
    onCancel?.(step.step_id)
  }
  
  return (
    <div className="relative flex items-stretch">
      {/* 步骤卡片 */}
      <motion.div
        layout
        onClick={onClick}
        className={`
          flex-1 rounded-lg border p-4 cursor-pointer
          transition-all duration-200
          ${config.bgColor}
          ${isActive ? 'ring-2 ring-cyan-500/50 ring-offset-2 ring-offset-slate-800' : ''}
          ${onClick ? 'hover:scale-[1.02]' : ''}
        `}
      >
        <div className="flex items-start gap-3">
          {/* 状态图标 */}
          <div className={`flex-shrink-0 ${config.color}`}>
            {config.icon}
          </div>

          {/* 内容 */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-white font-medium text-sm">
                {step.agent_name}
              </span>
              <span className={`
                text-xs px-1.5 py-0.5 rounded
                ${config.color} bg-white/5
              `}>
                {config.label}
              </span>
              <span className="text-xs text-slate-500">
                {getStepTypeLabel(step.step_type)}
              </span>
            </div>
            
            <p className="text-slate-400 text-sm truncate">
              {step.task}
            </p>

            {/* 条件显示 */}
            {step.condition && (
              <div className="mt-2 flex items-center gap-1 text-xs text-slate-500">
                <span>条件:</span>
                <code className="px-1 py-0.5 bg-slate-700/50 rounded">
                  {step.condition}
                </code>
              </div>
            )}

            {/* 依赖显示 */}
            {step.depends_on.length > 0 && (
              <div className="mt-1 flex items-center gap-1 text-xs text-slate-500">
                <span>依赖:</span>
                {step.depends_on.map(dep => (
                  <span 
                    key={dep}
                    className="px-1 py-0.5 bg-slate-700/50 rounded text-slate-400"
                  >
                    {dep}
                  </span>
                ))}
              </div>
            )}

            {/* 进度条 */}
            {step.status === 'running' && step.progress !== undefined && (
              <div className="mt-3">
                <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: `${step.progress}%` }}
                    transition={{ duration: 0.5 }}
                    className="h-full bg-emerald-400"
                  />
                </div>
                <div className="flex justify-between text-xs text-slate-500 mt-1">
                  <span>进度</span>
                  <span>{step.progress}%</span>
                </div>
              </div>
            )}

            {/* 输出预览 */}
            {step.output && step.status === 'completed' && (
              <div className="mt-2 p-2 bg-slate-900/50 rounded text-xs text-slate-400 line-clamp-2">
                {step.output}
              </div>
            )}

            {/* 错误信息 */}
            {step.error && step.status === 'failed' && (
              <div className="mt-2 p-2 bg-red-900/20 border border-red-500/20 rounded text-xs text-red-400">
                {step.error}
              </div>
            )}

            {/* 【新增】操作按钮 */}
            {step.status === 'running' && (
              <div className="mt-3 flex items-center gap-2">
                <button
                  onClick={handlePause}
                  className="flex items-center gap-1 px-2 py-1 rounded bg-yellow-500/20 text-yellow-400 text-xs hover:bg-yellow-500/30 transition-colors"
                  title="暂停执行"
                >
                  <PauseCircle className="w-3 h-3" />
                  暂停
                </button>
                <button
                  onClick={handleAdjust}
                  className="flex items-center gap-1 px-2 py-1 rounded bg-blue-500/20 text-blue-400 text-xs hover:bg-blue-500/30 transition-colors"
                  title="调整方向"
                >
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                  </svg>
                  调整
                </button>
                <button
                  onClick={handleCancel}
                  className="flex items-center gap-1 px-2 py-1 rounded bg-red-500/20 text-red-400 text-xs hover:bg-red-500/30 transition-colors"
                  title="取消执行"
                >
                  <XCircle className="w-3 h-3" />
                  取消
                </button>
              </div>
            )}
            
            {/* 【新增】暂停状态下的恢复按钮 */}
            {step.status === 'paused' && (
              <div className="mt-3 flex items-center gap-2">
                <button
                  onClick={handleResume}
                  className="flex items-center gap-1 px-2 py-1 rounded bg-emerald-500/20 text-emerald-400 text-xs hover:bg-emerald-500/30 transition-colors"
                  title="恢复执行"
                >
                  <Play className="w-3 h-3" />
                  恢复
                </button>
                <button
                  onClick={handleCancel}
                  className="flex items-center gap-1 px-2 py-1 rounded bg-red-500/20 text-red-400 text-xs hover:bg-red-500/30 transition-colors"
                  title="取消执行"
                >
                  <XCircle className="w-3 h-3" />
                  取消
                </button>
              </div>
            )}
          </div>
        </div>
      </motion.div>

      {/* 连接线 */}
      {!isLast && (
        <div className="flex items-center px-2">
          <ChevronRight className="w-5 h-5 text-slate-600" />
        </div>
      )}
    </div>
  )
}

// 主组件
export const SubAgentPipelinePanel: React.FC<SubAgentPipelinePanelProps & {
  onStepPause?: (stepId: string) => void     // 【新增】暂停步骤
  onStepResume?: (stepId: string) => void    // 【新增】恢复步骤
  onStepAdjust?: (stepId: string) => void    // 【新增】调整步骤
  onStepCancel?: (stepId: string) => void    // 【新增】取消步骤
}> = ({
  pipeline,
  currentStepId,
  onStepClick,
  onStepPause,
  onStepResume,
  onStepAdjust,
  onStepCancel,
  className = ''
}) => {
  // 计算统计
  const stats = {
    total: pipeline.steps.length,
    completed: pipeline.steps.filter(s => s.status === 'completed').length,
    running: pipeline.steps.filter(s => s.status === 'running').length,
    failed: pipeline.steps.filter(s => s.status === 'failed').length,
    pending: pipeline.steps.filter(s => s.status === 'pending').length
  }

  // 计算总体进度
  const progress = Math.round(
    (stats.completed / stats.total) * 100
  )

  return (
    <div className={`bg-slate-800/50 rounded-xl border border-white/10 ${className}`}>
      {/* 头部 */}
      <div className="px-4 py-3 border-b border-white/10">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Workflow className="w-5 h-5 text-cyan-400" />
            <div>
              <h3 className="text-white font-semibold">
                {pipeline.name || 'SubAgent流水线'}
              </h3>
              {pipeline.description && (
                <p className="text-slate-500 text-xs">
                  {pipeline.description}
                </p>
              )}
            </div>
          </div>
          
          {/* 状态徽章 */}
          <div className="flex items-center gap-2">
            {stats.running > 0 && (
              <span className="flex items-center gap-1 px-2 py-1 bg-emerald-500/10 text-emerald-400 rounded text-xs">
                <Play className="w-3 h-3" />
                执行中
              </span>
            )}
            {stats.failed > 0 && (
              <span className="flex items-center gap-1 px-2 py-1 bg-red-500/10 text-red-400 rounded text-xs">
                <XCircle className="w-3 h-3" />
                {stats.failed} 失败
              </span>
            )}
            {stats.completed === stats.total && (
              <span className="flex items-center gap-1 px-2 py-1 bg-blue-500/10 text-blue-400 rounded text-xs">
                <CheckCircle2 className="w-3 h-3" />
                完成
              </span>
            )}
          </div>
        </div>

        {/* 总体进度条 */}
        <div className="mt-3">
          <div className="flex justify-between text-xs text-slate-400 mb-1">
            <span>总体进度</span>
            <span>{stats.completed}/{stats.total} 步骤</span>
          </div>
          <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${progress}%` }}
              transition={{ duration: 0.5 }}
              className={`
                h-full rounded-full
                ${stats.failed > 0 ? 'bg-gradient-to-r from-emerald-400 to-red-400' : 'bg-emerald-400'}
              `}
            />
          </div>
        </div>
      </div>

      {/* 步骤列表 */}
      <div className="p-4 space-y-3 overflow-x-auto">
        <div className="flex items-stretch min-w-max">
          {pipeline.steps.map((step, index) => (
            <StepCard
              key={step.step_id}
              step={step}
              isActive={currentStepId === step.step_id}
              isLast={index === pipeline.steps.length - 1}
              onClick={() => onStepClick?.(step)}
              onPause={onStepPause}
              onResume={onStepResume}
              onAdjust={onStepAdjust}
              onCancel={onStepCancel}
            />
          ))}
        </div>
      </div>

      {/* 底部统计 */}
      <div className="px-4 py-2 border-t border-white/10">
        <div className="flex items-center justify-between text-xs">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1.5">
              <div className="w-2 h-2 rounded-full bg-emerald-400" />
              <span className="text-slate-400">完成 {stats.completed}</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-slate-400">运行 {stats.running}</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-2 h-2 rounded-full bg-slate-500" />
              <span className="text-slate-400">等待 {stats.pending}</span>
            </div>
            {stats.failed > 0 && (
              <div className="flex items-center gap-1.5">
                <div className="w-2 h-2 rounded-full bg-red-400" />
                <span className="text-slate-400">失败 {stats.failed}</span>
              </div>
            )}
          </div>
          
          {pipeline.created_at && (
            <span className="text-slate-600">
              创建于 {new Date(pipeline.created_at).toLocaleTimeString('zh-CN')}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

export default SubAgentPipelinePanel
