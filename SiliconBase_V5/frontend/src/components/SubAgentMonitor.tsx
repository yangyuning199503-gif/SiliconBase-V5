/**
 * SubAgent监控组件
 * 
 * 整合显示SubAgent的执行状态、代理树和流式事件
 * 用于在长任务面板中展示SubAgent执行情况
 */
import React, { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { 
  Bot, 
  TreePine, 
  Terminal, 
  Workflow,
  ChevronDown,
  ChevronUp,
  Activity,
  X
} from 'lucide-react'
import { useWebSocket } from '../hooks/useWebSocket'
import AgentTreeView from './AgentTreeView'
import StreamEventViewer from './StreamEventViewer'
import SubAgentPipelinePanel from './SubAgentPipelinePanel'
import type { 
  StreamEvent, 
  AgentTree,
  Pipeline
} from '../types/subagent'

export interface SubAgentMonitorProps {
  slot_id: number
  task_id?: string
  className?: string
  onClose?: () => void
}

type ViewMode = 'pipeline' | 'tree' | 'events'

export const SubAgentMonitor: React.FC<SubAgentMonitorProps> = ({
  slot_id,
  task_id,
  className = '',
  onClose
}) => {
  const { lastMessage } = useWebSocket()
  const [viewMode, setViewMode] = useState<ViewMode>('pipeline')
  const [isExpanded, setIsExpanded] = useState(true)
  
  // SubAgent信息状态
  const [events, setEvents] = useState<StreamEvent[]>([])
  const [agentTree, setAgentTree] = useState<AgentTree | null>(null)
  const [pipeline, setPipeline] = useState<Pipeline | null>(null)
  const [currentStepId, setCurrentStepId] = useState<string>()

  // 处理WebSocket消息
  useEffect(() => {
    if (!lastMessage) return

    const { type, data } = lastMessage

    // 处理SubAgent流式事件
    if (type === 'subagent_stream' && data?.slot_id === slot_id) {
      const event = data.event as StreamEvent
      setEvents(prev => [...prev, event].slice(-200)) // 保留最近200条
    }

    // 处理代理树更新
    if (type === 'agent_tree_update' && data?.slot_id === slot_id) {
      setAgentTree(data.tree as AgentTree)
    }

    // 处理流水线状态更新
    if (type === 'pipeline_status' && data?.slot_id === slot_id) {
      setPipeline(data.pipeline as Pipeline)
      setCurrentStepId(data.current_step)
    }

    // 处理长任务SubAgent信息
    if (type === 'longtask_subagent_info' && data?.slot_id === slot_id) {
      // 保留此分支以处理未来可能的状态更新
    }
  }, [lastMessage, slot_id])

  // 模拟数据（用于演示）
  useEffect(() => {
    // 如果有task_id，模拟一些初始数据
    if (task_id && !pipeline) {
      setPipeline({
        pipeline_id: `pipeline_${task_id}`,
        name: '代码生成流水线',
        description: '自动编排的代码生成、审查和测试流程',
        steps: [
          {
            step_id: 'plan',
            agent_name: 'planner',
            task: '规划代码架构',
            step_type: 'sequential',
            status: 'completed',
            depends_on: [],
            progress: 100
          },
          {
            step_id: 'generate',
            agent_name: 'code_generator',
            task: '生成核心代码',
            step_type: 'sequential',
            status: 'running',
            depends_on: ['plan'],
            progress: 65
          },
          {
            step_id: 'review',
            agent_name: 'code_reviewer',
            task: '代码审查',
            step_type: 'sequential',
            status: 'pending',
            depends_on: ['generate']
          },
          {
            step_id: 'test',
            agent_name: 'tester',
            task: '生成测试用例',
            step_type: 'conditional',
            status: 'pending',
            depends_on: ['review'],
            condition: 'review_passed'
          }
        ],
        context: { task_id },
        created_at: Date.now()
      })
      setCurrentStepId('generate')

      // 模拟代理树
      setAgentTree({
        root: {
          runtime_id: 'root_001',
          name: '任务协调器',
          status: 'running',
          stage: 'coordinating',
          progress: 65,
          children: [
            {
              runtime_id: 'agent_001',
              name: 'planner',
              status: 'completed',
              stage: 'completed',
              progress: 100,
              children: []
            },
            {
              runtime_id: 'agent_002',
              name: 'code_generator',
              status: 'running',
              stage: 'executing',
              progress: 65,
              children: [
                {
                  runtime_id: 'agent_002_1',
                  name: 'code_generator_child',
                  status: 'running',
                  stage: 'generating',
                  progress: 40,
                  children: []
                }
              ]
            },
            {
              runtime_id: 'agent_003',
              name: 'code_reviewer',
              status: 'pending',
              stage: 'waiting',
              children: []
            }
          ]
        },
        total_nodes: 5,
        max_depth: 2
      })

      // 模拟一些初始事件
      setEvents([
        {
          type: 'thought',
          content: '开始分析任务需求...',
          timestamp: Date.now() - 30000,
          agent_name: 'planner'
        },
        {
          type: 'complete',
          content: '架构规划完成，确定了3个核心模块',
          timestamp: Date.now() - 25000,
          agent_name: 'planner'
        },
        {
          type: 'child_delegate',
          content: '委派给 code_generator 生成核心代码',
          timestamp: Date.now() - 20000,
          agent_name: '任务协调器'
        },
        {
          type: 'thought',
          content: '正在生成用户认证模块代码...',
          timestamp: Date.now() - 15000,
          agent_name: 'code_generator'
        },
        {
          type: 'tool_call',
          content: '调用文件写入工具',
          timestamp: Date.now() - 10000,
          agent_name: 'code_generator',
          data: { file: 'auth.py' }
        },
        {
          type: 'progress',
          content: '代码生成进度 65%',
          timestamp: Date.now() - 5000,
          agent_name: 'code_generator',
          data: { progress: 65 }
        }
      ])
    }
  }, [task_id, pipeline])

  // 如果没有SubAgent信息，显示提示
  if (!pipeline && !agentTree) {
    return (
      <div className={`bg-slate-800/30 rounded-lg border border-white/5 p-4 ${className}`}>
        <div className="flex items-center gap-2 text-slate-500">
          <Bot className="w-4 h-4" />
          <span className="text-sm">此任务未启用SubAgent流水线</span>
        </div>
      </div>
    )
  }

  return (
    <div className={`bg-slate-800/50 rounded-xl border border-cyan-500/20 ${className}`}>
      {/* 头部 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/10">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-cyan-500/20 flex items-center justify-center">
            <Activity className="w-4 h-4 text-cyan-400" />
          </div>
          <div>
            <h4 className="text-white font-medium text-sm">SubAgent执行监控</h4>
            <p className="text-slate-500 text-xs">
              {agentTree?.total_nodes || 0} 个代理 · {events.length} 条事件
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1">
          {/* 视图切换 */}
          <div className="flex items-center bg-slate-700/50 rounded-lg p-0.5">
            <button
              onClick={() => setViewMode('pipeline')}
              className={`
                px-2 py-1 rounded text-xs flex items-center gap-1 transition-colors
                ${viewMode === 'pipeline' ? 'bg-slate-600 text-white' : 'text-slate-400 hover:text-white'}
              `}
              title="流水线视图"
            >
              <Workflow className="w-3 h-3" />
              流水线
            </button>
            <button
              onClick={() => setViewMode('tree')}
              className={`
                px-2 py-1 rounded text-xs flex items-center gap-1 transition-colors
                ${viewMode === 'tree' ? 'bg-slate-600 text-white' : 'text-slate-400 hover:text-white'}
              `}
              title="代理树视图"
            >
              <TreePine className="w-3 h-3" />
              代理树
            </button>
            <button
              onClick={() => setViewMode('events')}
              className={`
                px-2 py-1 rounded text-xs flex items-center gap-1 transition-colors
                ${viewMode === 'events' ? 'bg-slate-600 text-white' : 'text-slate-400 hover:text-white'}
              `}
              title="事件日志"
            >
              <Terminal className="w-3 h-3" />
              日志
            </button>
          </div>

          {/* 展开/折叠按钮 */}
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="p-1.5 text-slate-400 hover:text-white hover:bg-slate-700/50 rounded-lg transition-colors"
          >
            {isExpanded ? (
              <ChevronUp className="w-4 h-4" />
            ) : (
              <ChevronDown className="w-4 h-4" />
            )}
          </button>

          {/* 关闭按钮 */}
          {onClose && (
            <button
              onClick={onClose}
              className="p-1.5 text-slate-400 hover:text-white hover:bg-slate-700/50 rounded-lg transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* 内容区域 */}
      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
            className="p-4"
          >
            {/* 流水线视图 */}
            {viewMode === 'pipeline' && pipeline && (
              <SubAgentPipelinePanel
                pipeline={pipeline}
                currentStepId={currentStepId}
                onStepClick={(step) => console.log('Step clicked:', step)}
              />
            )}

            {/* 代理树视图 */}
            {viewMode === 'tree' && agentTree && (
              <AgentTreeView
                tree={agentTree}
                onNodeClick={(node) => console.log('Node clicked:', node)}
              />
            )}

            {/* 事件日志视图 */}
            {viewMode === 'events' && (
              <StreamEventViewer
                events={events}
                maxEvents={50}
                autoScroll={true}
              />
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* 折叠时显示摘要 */}
      {!isExpanded && (
        <div className="px-4 py-2 border-t border-white/10">
          <div className="flex items-center gap-4 text-xs">
            {pipeline && (
              <>
                <div className="flex items-center gap-1.5">
                  <Workflow className="w-3 h-3 text-slate-400" />
                  <span className="text-slate-400">
                    {pipeline.steps.filter(s => s.status === 'completed').length}/{pipeline.steps.length} 步骤完成
                  </span>
                </div>
                <div className="h-3 w-px bg-slate-700" />
              </>
            )}
            {agentTree && (
              <>
                <div className="flex items-center gap-1.5">
                  <TreePine className="w-3 h-3 text-slate-400" />
                  <span className="text-slate-400">
                    {agentTree.total_nodes} 个代理
                  </span>
                </div>
                <div className="h-3 w-px bg-slate-700" />
              </>
            )}
            <div className="flex items-center gap-1.5">
              <Terminal className="w-3 h-3 text-slate-400" />
              <span className="text-slate-400">
                {events.length} 条事件
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default SubAgentMonitor
