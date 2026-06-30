/**
 * 槽位类型定义
 * Phase 4.5: 前端槽位显示增强
 */

// ========== 增强槽位任务类型 ==========

export type SlotTaskType = 'workflow' | 'subagent' | 'hybrid';

export type SlotStatus = 'running' | 'paused' | 'completed' | 'failed' | 'waiting_approval' | 'idle';

export type VerificationState = 'pending' | 'ai_passed' | 'ai_failed' | 'human_approved' | 'human_rejected';

export type StepType = 'tool' | 'subagent';

// 进度信息
export interface SlotProgress {
  current: number;
  total: number;
  percentage: number;
}

// 工作流信息
export interface WorkflowInfo {
  execution_id: string;
  workflow_name: string;
  current_step_name: string;
  current_step_type: StepType;
}

// 子代理信息
export interface SubagentInfo {
  agent_name: string;
  stream_output: string[];
  current_thought: string;
}

// 验收状态
export interface VerificationStatus {
  state: VerificationState;
  confidence: number;
  concerns: string[];
  requires_human: boolean;
}

// 检查点信息
export interface CheckpointInfo {
  checkpoint_id: string;
  created_at: string;
  can_resume: boolean;
}

// 控制按钮状态
export interface SlotControls {
  can_pause: boolean;
  can_resume: boolean;
  can_cancel: boolean;
  can_approve: boolean;
  can_reject: boolean;
}

// 增强槽位任务（用于融合后的槽位系统）
export interface EnhancedSlotTask {
  slot_id: number;
  task_type: SlotTaskType;
  status: SlotStatus;
  progress: SlotProgress;
  
  // 工作流信息
  workflow_info?: WorkflowInfo;
  
  // 子代理信息
  subagent_info?: SubagentInfo;
  
  // 验收状态
  verification_status?: VerificationStatus;
  
  // 检查点信息
  checkpoint?: CheckpointInfo;
  
  // 控制按钮状态
  controls: SlotControls;
  
  // 基础字段（向后兼容）
  task_id?: string;
  task_name?: string;
  description?: string;
  created_at?: string;
  ai_understanding?: string;
}

// ========== 基础槽位任务类型（向后兼容） ==========

export interface SlotTask {
  slot_id: number;
  task_id?: string;
  task_name?: string;
  task_type?: string;
  status: 'idle' | 'running' | 'paused' | 'error';
  progress: number;
  ai_understanding?: string;
  created_at?: string;
  description?: string;
  // SubAgent相关字段
  has_subagent_pipeline?: boolean;
  subagent_pipeline_name?: string;
}

// ========== API 请求/响应类型 ==========

// 暂停槽位请求
export interface PauseSlotRequest {
  slot_id: number;
  reason?: string;
}

// 恢复槽位请求
export interface ResumeSlotRequest {
  slot_id: number;
  ai_confirmation?: string;
  use_checkpoint?: boolean;
  checkpoint_id?: string;
}

// 验收决策请求
export interface VerificationDecisionRequest {
  slot_id: number;
  decision: 'approve' | 'reject';
  feedback?: string;
}

// 槽位操作响应
export interface SlotOperationResponse {
  success: boolean;
  message?: string;
  checkpoint_id?: string;
  task?: EnhancedSlotTask;
}

// ========== WebSocket 消息类型 ==========

// 槽位更新消息
export interface SlotUpdateMessage {
  type: 'slot_update';
  data: {
    slot_id: number;
    task: EnhancedSlotTask;
  };
  timestamp: number;
}

// 子代理流式输出消息
export interface SubagentStreamMessage {
  type: 'subagent_stream';
  data: {
    slot_id: number;
    output: string;
    thought?: string;
    agent_name?: string;
  };
  timestamp: number;
}

// 验收请求消息
export interface VerificationRequestMessage {
  type: 'verification_request';
  data: {
    slot_id: number;
    ai_result: {
      passed: boolean;
      confidence: number;
      concerns: string[];
    };
    requires_human: boolean;
  };
  timestamp: number;
}

// ========== 组件 Props 类型 ==========

export interface VerificationPanelProps {
  task: EnhancedSlotTask;
  onApprove: () => void;
  onReject: (feedback: string) => void;
  onRequestAIReview?: () => void;
  className?: string;
}

export interface EnhancedSlotCardProps {
  task: EnhancedSlotTask;
  onPause?: (slotId: number) => void;
  onResume?: (slotId: number, confirmation?: string) => void;
  onStop?: (slotId: number) => void;
  onApprove?: (slotId: number) => void;
  onReject?: (slotId: number, feedback: string) => void;
  onCreateTask?: (slotId: number) => void;
  className?: string;
}

export interface StreamOutputViewerProps {
  outputs: string[];
  currentThought?: string;
  agentName?: string;
  maxHeight?: number;
  autoScroll?: boolean;
  className?: string;
}

export interface CheckpointViewerProps {
  checkpoint?: CheckpointInfo;
  onResumeFromCheckpoint?: (checkpointId: string) => void;
  className?: string;
}
