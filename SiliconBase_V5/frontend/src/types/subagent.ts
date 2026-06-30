/**
 * SubAgent 相关类型定义
 * 
 * 用于增强版SubAgent系统的可视化
 */

// ========== 流式事件类型 ==========

export type StreamEventType = 
  | 'thought'      // AI思考过程
  | 'tool_call'    // 准备调用工具
  | 'tool_result'  // 工具执行结果
  | 'progress'     // 进度更新
  | 'child_delegate' // 委派给子代理
  | 'complete'     // 任务完成
  | 'error'        // 错误
  | 'paused'       // 已暂停
  | 'resumed'      // 已恢复

// 流式事件
export interface StreamEvent {
  type: StreamEventType
  content: string
  data?: Record<string, any>
  timestamp: number
  runtime_id?: string
  agent_name?: string
}

// ========== 代理树类型 ==========

// 代理节点
export interface AgentNode {
  runtime_id: string
  name: string
  description?: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  stage?: string
  progress?: number
  children: AgentNode[]
  parent_runtime_id?: string
  start_time?: number
  end_time?: number
  metadata?: Record<string, any>
}

// 代理树
export interface AgentTree {
  root: AgentNode
  total_nodes: number
  max_depth: number
}

// ========== 流水线类型 ==========

export type PipelineStepType = 'sequential' | 'parallel' | 'conditional'

export type PipelineStepStatus = 
  | 'pending'      // 等待执行
  | 'running'      // 执行中
  | 'completed'    // 已完成
  | 'failed'       // 失败
  | 'skipped'      // 已跳过
  | 'paused'       // 已暂停

// 流水线步骤
export interface PipelineStep {
  step_id: string
  agent_name: string
  task: string
  step_type: PipelineStepType
  status: PipelineStepStatus
  condition?: string
  depends_on: string[]
  on_complete?: string
  
  // 运行时信息
  runtime_id?: string
  output?: string
  error?: string
  start_time?: number
  end_time?: number
  progress?: number
}

// 流水线事件
export interface PipelineEvent {
  step: string
  runtime_id: string
  type: StreamEventType | 'pipeline_complete' | 'pipeline_paused' | 'pipeline_resumed' | 'step_started' | 'step_completed'
  content: string
  data?: Record<string, any>
  timestamp: number
}

// 流水线定义
export interface Pipeline {
  pipeline_id: string
  name: string
  description?: string
  steps: PipelineStep[]
  context?: Record<string, any>
  created_at: number
}

// 流水线执行结果
export interface PipelineResult {
  pipeline_id: string
  success: boolean
  steps_results: Record<string, {
    status: PipelineStepStatus
    output?: string
    error?: string
    execution_time: number
  }>
  total_execution_time: number
  completed_at: number
}

// ========== WebSocket消息扩展 ==========

// SubAgent流式事件消息
export interface SubAgentStreamMessage {
  type: 'subagent_stream'
  data: {
    task_id?: string
    slot_id?: number
    pipeline_id?: string
    event: StreamEvent
  }
  timestamp: number
}

// 代理树更新消息
export interface AgentTreeUpdateMessage {
  type: 'agent_tree_update'
  data: {
    task_id?: string
    slot_id?: number
    tree: AgentTree
  }
  timestamp: number
}

// 流水线状态更新消息
export interface PipelineStatusMessage {
  type: 'pipeline_status'
  data: {
    task_id?: string
    slot_id?: number
    pipeline: Pipeline
    current_step?: string
  }
  timestamp: number
}

// 长任务SubAgent关联信息
export interface LongTaskSubAgentInfo {
  // 关联的长任务槽位
  slot_id: number
  task_id: string
  
  // SubAgent信息
  has_pipeline: boolean
  pipeline_id?: string
  pipeline_name?: string
  
  // 代理树
  has_agent_tree: boolean
  agent_tree?: AgentTree
  
  // 当前执行状态
  current_agent?: string
  current_stage?: string
  
  // 执行统计
  total_agents: number
  completed_agents: number
  failed_agents: number
  
  // 最近事件
  recent_events: StreamEvent[]
}

// ========== 组件Props类型 ==========

export interface AgentTreeViewProps {
  tree: AgentTree
  onNodeClick?: (node: AgentNode) => void
  onNodeExpand?: (node: AgentNode) => void
  expandedNodes?: string[]
  selectedNode?: string
  className?: string
}

export interface StreamEventViewerProps {
  events: StreamEvent[]
  maxEvents?: number
  autoScroll?: boolean
  filter?: StreamEventType[]
  className?: string
}

export interface SubAgentPipelinePanelProps {
  pipeline: Pipeline
  currentStepId?: string
  onStepClick?: (step: PipelineStep) => void
  className?: string
}

export interface LongTaskSubAgentPanelProps {
  slot_id: number
  task_id?: string
  subagent_info?: LongTaskSubAgentInfo
  onViewTree?: () => void
  onViewEvents?: () => void
  onViewPipeline?: () => void
  className?: string
}
