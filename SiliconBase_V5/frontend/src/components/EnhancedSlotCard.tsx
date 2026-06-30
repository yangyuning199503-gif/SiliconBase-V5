/**
 * 增强版槽位卡片组件
 * Phase 4.5: 前端槽位显示增强
 * 
 * 功能：
 * - 子代理流式输出显示区域
 * - 验收状态显示
 * - 检查点信息展示
 * - 控制按钮状态（暂停/恢复/确认/拒绝）
 */

import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Play,
  Pause,
  Square,
  AlertCircle,
  Clock,
  Loader2,
  Bot,
  CheckCircle2,
  Plus,
  Activity,
  ChevronDown,
  ChevronUp,
  Save,
  RotateCcw,
  Terminal,
  Brain,
  Shield,
  AlertTriangle
} from 'lucide-react';
import { VerificationPanel } from './VerificationPanel';
import type { EnhancedSlotTask, SlotStatus, SlotTaskType } from '../types/slot';

// ========== 组件 Props ==========

interface EnhancedSlotCardProps {
  task: EnhancedSlotTask;
  onPause?: (slotId: number) => void;
  onResume?: (slotId: number, confirmation?: string) => void;
  onStop?: (slotId: number) => void;
  onApprove?: (slotId: number) => void;
  onReject?: (slotId: number, feedback: string) => void;
  onCreateTask?: (slotId: number) => void;
  onResumeFromCheckpoint?: (slotId: number, checkpointId: string) => void;
  className?: string;
}

// ========== 辅助函数 ==========

// 获取状态标签
const getStatusLabel = (status: SlotStatus): string => {
  switch (status) {
    case 'running':
      return '运行中';
    case 'paused':
      return '已暂停';
    case 'completed':
      return '已完成';
    case 'failed':
      return '失败';
    case 'waiting_approval':
      return '等待验收';
    case 'idle':
      return '空闲';
    default:
      return '未知';
  }
};

// 获取状态颜色类
const getStatusColorClass = (status: SlotStatus): string => {
  switch (status) {
    case 'running':
      return 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20';
    case 'paused':
      return 'text-yellow-400 bg-yellow-400/10 border-yellow-400/20';
    case 'completed':
      return 'text-blue-400 bg-blue-400/10 border-blue-400/20';
    case 'failed':
      return 'text-red-400 bg-red-400/10 border-red-400/20';
    case 'waiting_approval':
      return 'text-purple-400 bg-purple-400/10 border-purple-400/20';
    case 'idle':
      return 'text-slate-400 bg-slate-400/10 border-slate-400/20';
    default:
      return 'text-slate-400 bg-slate-400/10 border-slate-400/20';
  }
};

// 获取进度条颜色
const getProgressColorClass = (status: SlotStatus): string => {
  switch (status) {
    case 'running':
      return 'bg-emerald-400';
    case 'paused':
      return 'bg-yellow-400';
    case 'completed':
      return 'bg-blue-400';
    case 'failed':
      return 'bg-red-400';
    case 'waiting_approval':
      return 'bg-purple-400';
    case 'idle':
      return 'bg-slate-400';
    default:
      return 'bg-slate-400';
  }
};

// 获取状态图标
const getStatusIcon = (status: SlotStatus) => {
  switch (status) {
    case 'running':
      return <Loader2 className="w-4 h-4 animate-spin" />;
    case 'paused':
      return <Pause className="w-4 h-4" />;
    case 'completed':
      return <CheckCircle2 className="w-4 h-4" />;
    case 'failed':
      return <AlertCircle className="w-4 h-4" />;
    case 'waiting_approval':
      return <Shield className="w-4 h-4" />;
    case 'idle':
      return <Clock className="w-4 h-4" />;
    default:
      return <Clock className="w-4 h-4" />;
  }
};

// 获取任务类型标签
const getTaskTypeLabel = (type?: SlotTaskType): string => {
  switch (type) {
    case 'workflow':
      return '工作流';
    case 'subagent':
      return '子代理';
    case 'hybrid':
      return '混合';
    default:
      return '未知';
  }
};

// 获取任务类型颜色
const getTaskTypeColorClass = (type?: SlotTaskType): string => {
  switch (type) {
    case 'workflow':
      return 'text-cyan-400 bg-cyan-400/10';
    case 'subagent':
      return 'text-violet-400 bg-violet-400/10';
    case 'hybrid':
      return 'text-pink-400 bg-pink-400/10';
    default:
      return 'text-slate-400 bg-slate-400/10';
  }
};

// ========== 流式输出查看器组件 ==========

interface StreamOutputViewerProps {
  outputs: string[];
  currentThought?: string;
  agentName?: string;
  maxHeight?: number;
}

const StreamOutputViewer: React.FC<StreamOutputViewerProps> = ({
  outputs,
  currentThought,
  agentName,
  maxHeight = 200
}) => {
  const scrollRef = useRef<HTMLDivElement>(null);

  // 自动滚动到底部
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [outputs, currentThought]);

  if (outputs.length === 0 && !currentThought) {
    return (
      <div className="text-center py-4 text-slate-500 text-sm">
        <Terminal className="w-5 h-5 mx-auto mb-2 opacity-50" />
        <p>暂无输出</p>
      </div>
    );
  }

  return (
    <div className="bg-slate-900/50 rounded-lg border border-white/5 overflow-hidden">
      {/* 头部 */}
      <div className="flex items-center justify-between px-3 py-2 bg-slate-800/50 border-b border-white/5">
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-slate-400" />
          <span className="text-slate-300 text-sm">
            {agentName || '子代理'} 输出
          </span>
        </div>
        <span className="text-slate-500 text-xs">
          {outputs.length} 条输出
        </span>
      </div>

      {/* 内容区域 */}
      <div
        ref={scrollRef}
        className="p-3 space-y-2 overflow-y-auto"
        style={{ maxHeight }}
      >
        {/* 当前思考 */}
        {currentThought && (
          <motion.div
            initial={{ opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-start gap-2 p-2 bg-violet-500/10 rounded border border-violet-500/20"
          >
            <Brain className="w-4 h-4 text-violet-400 flex-shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <p className="text-violet-300 text-xs mb-1">思考中...</p>
              <p className="text-slate-300 text-sm whitespace-pre-wrap break-words">
                {currentThought}
              </p>
            </div>
          </motion.div>
        )}

        {/* 历史输出 */}
        {outputs.map((output, index) => (
          <motion.div
            key={index}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="text-sm text-slate-400 whitespace-pre-wrap break-words"
          >
            {output}
          </motion.div>
        ))}
      </div>
    </div>
  );
};

// ========== 检查点查看器组件 ==========

interface CheckpointViewerProps {
  checkpoint?: {
    checkpoint_id: string;
    created_at: string;
    can_resume: boolean;
  };
  onResumeFromCheckpoint?: () => void;
}

const CheckpointViewer: React.FC<CheckpointViewerProps> = ({
  checkpoint,
  onResumeFromCheckpoint
}) => {
  if (!checkpoint) {
    return null;
  }

  const formattedTime = new Date(checkpoint.created_at).toLocaleString('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  });

  return (
    <div className="bg-slate-900/50 rounded-lg p-3 border border-white/5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Save className="w-4 h-4 text-cyan-400" />
          <div>
            <p className="text-slate-300 text-sm">检查点</p>
            <p className="text-slate-500 text-xs">创建于 {formattedTime}</p>
          </div>
        </div>
        {checkpoint.can_resume && onResumeFromCheckpoint && (
          <button
            onClick={onResumeFromCheckpoint}
            className="flex items-center gap-1 px-2 py-1 bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-400 rounded text-xs transition-all"
          >
            <RotateCcw className="w-3 h-3" />
            恢复
          </button>
        )}
      </div>
    </div>
  );
};

// ========== 工作流信息组件 ==========

interface WorkflowInfoPanelProps {
  workflowInfo?: {
    execution_id: string;
    workflow_name: string;
    current_step_name: string;
    current_step_type: 'tool' | 'subagent';
  };
}

const WorkflowInfoPanel: React.FC<WorkflowInfoPanelProps> = ({ workflowInfo }) => {
  if (!workflowInfo) {
    return null;
  }

  return (
    <div className="bg-slate-900/50 rounded-lg p-3 border border-white/5">
      <div className="flex items-center gap-2 mb-2">
        <Activity className="w-4 h-4 text-cyan-400" />
        <span className="text-slate-300 text-sm font-medium">
          {workflowInfo.workflow_name}
        </span>
      </div>
      <div className="flex items-center gap-2 text-xs">
        <span className="text-slate-500">当前步骤:</span>
        <span className="text-slate-300">{workflowInfo.current_step_name}</span>
        <span className={`
          px-1.5 py-0.5 rounded text-[10px]
          ${workflowInfo.current_step_type === 'subagent' 
            ? 'bg-violet-500/20 text-violet-400' 
            : 'bg-cyan-500/20 text-cyan-400'}
        `}>
          {workflowInfo.current_step_type === 'subagent' ? '子代理' : '工具'}
        </span>
      </div>
    </div>
  );
};

// ========== AI确认对话框组件 ==========

interface AIConfirmDialogProps {
  isOpen: boolean;
  taskName?: string;
  onConfirm: (confirmation: string) => void;
  onCancel: () => void;
}

const AIConfirmDialog: React.FC<AIConfirmDialogProps> = ({
  isOpen,
  taskName,
  onConfirm,
  onCancel
}) => {
  const [confirmation, setConfirmation] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleConfirm = async () => {
    if (!confirmation.trim()) return;
    setIsSubmitting(true);
    try {
      await onConfirm(confirmation);
      setConfirmation('');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4"
          onClick={onCancel}
        >
          <motion.div
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.9, opacity: 0 }}
            className="bg-slate-800 rounded-xl border border-yellow-500/30 p-6 w-full max-w-lg shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            {/* 标题 */}
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-yellow-500/20 flex items-center justify-center">
                <Bot className="w-5 h-5 text-yellow-400" />
              </div>
              <div>
                <h4 className="text-white font-semibold">AI理解确认</h4>
                <p className="text-slate-400 text-sm">{taskName}</p>
              </div>
            </div>

            {/* 警告提示 */}
            <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-lg p-4 mb-4">
              <p className="text-yellow-400 text-sm flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                <span>
                  <strong>重要提示：</strong>AI必须确认百分百理解用户需求后才能恢复任务。
                </span>
              </p>
            </div>

            {/* 输入 */}
            <div className="mb-4">
              <label className="block text-slate-300 text-sm mb-2">
                AI理解确认内容 <span className="text-red-400">*</span>
              </label>
              <textarea
                value={confirmation}
                onChange={(e) => setConfirmation(e.target.value)}
                placeholder="请详细描述对任务的完整理解..."
                className="w-full h-32 bg-slate-900 border border-white/10 rounded-lg px-3 py-2 text-white text-sm placeholder:text-slate-600 focus:outline-none focus:border-yellow-500/50 resize-none"
              />
              <p className="text-slate-500 text-xs mt-1">
                至少输入20个字符
              </p>
            </div>

            {/* 按钮 */}
            <div className="flex justify-end gap-3">
              <button
                onClick={onCancel}
                className="px-4 py-2 text-slate-400 hover:text-white text-sm transition-all"
              >
                取消
              </button>
              <button
                onClick={handleConfirm}
                disabled={isSubmitting || confirmation.trim().length < 20}
                className="flex items-center gap-1.5 px-4 py-2 bg-yellow-500 hover:bg-yellow-600 disabled:bg-slate-600 disabled:cursor-not-allowed text-slate-900 font-medium rounded-lg text-sm transition-all"
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    处理中...
                  </>
                ) : (
                  <>
                    <CheckCircle2 className="w-4 h-4" />
                    确认恢复
                  </>
                )}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};

// ========== 主组件 ==========

export const EnhancedSlotCard: React.FC<EnhancedSlotCardProps> = ({
  task,
  onPause,
  onResume,
  onStop,
  onApprove,
  onReject,
  onCreateTask,
  onResumeFromCheckpoint,
  className = ''
}) => {
  const [isLoading, setIsLoading] = useState(false);
  const [showDetails, setShowDetails] = useState(false);
  const [showAIConfirmDialog, setShowAIConfirmDialog] = useState(false);

  const handlePause = async () => {
    if (!onPause) return;
    setIsLoading(true);
    try {
      await onPause(task.slot_id);
    } finally {
      setIsLoading(false);
    }
  };

  const handleStop = async () => {
    if (!onStop) return;
    setIsLoading(true);
    try {
      await onStop(task.slot_id);
    } finally {
      setIsLoading(false);
    }
  };

  const handleResume = async (confirmation?: string) => {
    if (!onResume) return;
    setIsLoading(true);
    try {
      await onResume(task.slot_id, confirmation);
      setShowAIConfirmDialog(false);
    } finally {
      setIsLoading(false);
    }
  };

  const handleApprove = async () => {
    if (!onApprove) return;
    setIsLoading(true);
    try {
      await onApprove(task.slot_id);
    } finally {
      setIsLoading(false);
    }
  };

  const handleReject = async (feedback: string) => {
    if (!onReject) return;
    setIsLoading(true);
    try {
      await onReject(task.slot_id, feedback);
    } finally {
      setIsLoading(false);
    }
  };

  const handleResumeFromCheckpoint = () => {
    if (!onResumeFromCheckpoint || !task.checkpoint) return;
    setIsLoading(true);
    try {
      onResumeFromCheckpoint(task.slot_id, task.checkpoint.checkpoint_id);
    } finally {
      setIsLoading(false);
    }
  };

  const isActive = task.status === 'running' || task.status === 'paused' || task.status === 'waiting_approval';
  const showVerification = task.status === 'waiting_approval' || task.verification_status;

  return (
    <>
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: task.slot_id * 0.1 }}
        className={`
          relative rounded-xl border p-4 transition-all
          ${task.status === 'idle'
            ? 'bg-slate-800/30 border-slate-700/50'
            : 'bg-slate-800/50 border-white/10 hover:border-white/20'
          }
          ${className}
        `}
      >
        {/* 槽位编号标记 */}
        <div className="absolute -top-3 -left-3 w-8 h-8 rounded-full bg-slate-700 border border-white/10 flex items-center justify-center text-white font-semibold text-sm">
          {task.slot_id}
        </div>

        {/* 槽位内容 */}
        <div className="mt-2">
          {/* 任务名称或空闲提示 */}
          <div className="mb-3">
            {task.status === 'idle' ? (
              <div className="text-center py-8">
                <div className="w-12 h-12 rounded-full bg-slate-700/50 flex items-center justify-center mx-auto mb-3">
                  <Plus className="w-6 h-6 text-slate-500" />
                </div>
                <p className="text-slate-500 text-sm">槽位空闲</p>
                <p className="text-slate-600 text-xs mt-1">等待分配任务</p>
              </div>
            ) : (
              <>
                <div className="flex items-start justify-between mb-2">
                  <h4 className="text-white font-medium truncate pr-2 flex-1">
                    {task.task_name || '未命名任务'}
                  </h4>
                  {task.task_type && (
                    <span className={`
                      px-2 py-0.5 rounded text-[10px] flex-shrink-0
                      ${getTaskTypeColorClass(task.task_type)}
                    `}>
                      {getTaskTypeLabel(task.task_type)}
                    </span>
                  )}
                </div>
                {task.description && (
                  <p className="text-slate-500 text-xs line-clamp-2">
                    {task.description}
                  </p>
                )}
              </>
            )}
          </div>

          {/* 状态标签和进度条 - 仅在非空闲状态显示 */}
          {task.status !== 'idle' && (
            <>
              {/* 状态标签 */}
              <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs mb-3 ${getStatusColorClass(task.status)}`}>
                {getStatusIcon(task.status)}
                <span>{getStatusLabel(task.status)}</span>
              </div>

              {/* 进度条 */}
              <div className="mb-4">
                <div className="flex justify-between text-xs text-slate-400 mb-1">
                  <span>进度</span>
                  <span className="text-white font-medium">
                    {task.progress.percentage}%
                  </span>
                </div>
                <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: `${task.progress.percentage}%` }}
                    transition={{ duration: 0.5 }}
                    className={`h-full ${getProgressColorClass(task.status)}`}
                  />
                </div>
                <div className="flex justify-between text-xs text-slate-500 mt-1">
                  <span>步骤 {task.progress.current}/{task.progress.total}</span>
                </div>
              </div>

              {/* 工作流信息 */}
              {task.workflow_info && (
                <div className="mb-3">
                  <WorkflowInfoPanel workflowInfo={task.workflow_info} />
                </div>
              )}

              {/* 检查点信息 */}
              {task.checkpoint && (
                <div className="mb-3">
                  <CheckpointViewer
                    checkpoint={task.checkpoint}
                    onResumeFromCheckpoint={handleResumeFromCheckpoint}
                  />
                </div>
              )}
            </>
          )}

          {/* 操作按钮 */}
          <div className="flex items-center justify-center gap-2">
            {task.status === 'idle' && onCreateTask && (
              <button
                onClick={() => onCreateTask(task.slot_id)}
                disabled={isLoading}
                className="flex items-center gap-1.5 px-4 py-2 bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-400 rounded-lg text-sm transition-all"
              >
                <Plus className="w-4 h-4" />
                创建任务
              </button>
            )}

            {task.status === 'running' && task.controls.can_pause && (
              <>
                <button
                  onClick={handlePause}
                  disabled={isLoading}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-yellow-500/20 hover:bg-yellow-500/30 text-yellow-400 rounded-lg text-sm transition-all disabled:opacity-50"
                >
                  {isLoading ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Pause className="w-3.5 h-3.5" />
                  )}
                  暂停
                </button>
                {task.controls.can_cancel && (
                  <button
                    onClick={handleStop}
                    disabled={isLoading}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-red-500/20 hover:bg-red-500/30 text-red-400 rounded-lg text-sm transition-all disabled:opacity-50"
                  >
                    {isLoading ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Square className="w-3.5 h-3.5" />
                    )}
                    停止
                  </button>
                )}
              </>
            )}

            {task.status === 'paused' && task.controls.can_resume && (
              <>
                <button
                  onClick={() => setShowAIConfirmDialog(true)}
                  disabled={isLoading}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-400 rounded-lg text-sm transition-all disabled:opacity-50"
                >
                  {isLoading ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Play className="w-3.5 h-3.5" />
                  )}
                  恢复
                </button>
                <button
                  onClick={handleStop}
                  disabled={isLoading}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-red-500/20 hover:bg-red-500/30 text-red-400 rounded-lg text-sm transition-all disabled:opacity-50"
                >
                  {isLoading ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Square className="w-3.5 h-3.5" />
                  )}
                  停止
                </button>
              </>
            )}

            {(task.status === 'failed' || task.status === 'completed') && task.controls.can_cancel && (
              <button
                onClick={handleStop}
                disabled={isLoading}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-500/20 hover:bg-slate-500/30 text-slate-400 rounded-lg text-sm transition-all disabled:opacity-50"
              >
                {isLoading ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <CheckCircle2 className="w-3.5 h-3.5" />
                )}
                清除
              </button>
            )}
          </div>

          {/* 详情展开按钮 - 仅在活跃状态显示 */}
          {isActive && (
            <div className="mt-3">
              <button
                onClick={() => setShowDetails(!showDetails)}
                className={`
                  w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm
                  transition-all duration-200
                  ${showDetails
                    ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30'
                    : 'bg-slate-700/30 hover:bg-slate-700/50 text-slate-300 border border-transparent'}
                `}
              >
                <Activity className="w-4 h-4" />
                <span>
                  {showDetails ? '隐藏详情' : '查看详情'}
                </span>
                {showDetails ? (
                  <ChevronUp className="w-4 h-4" />
                ) : (
                  <ChevronDown className="w-4 h-4" />
                )}
              </button>

              {/* 详情面板 */}
              <AnimatePresence>
                {showDetails && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    exit={{ opacity: 0, height: 0 }}
                    transition={{ duration: 0.3 }}
                    className="mt-3 space-y-3"
                  >
                    {/* 子代理流式输出 */}
                    {task.subagent_info && (
                      <StreamOutputViewer
                        outputs={task.subagent_info.stream_output}
                        currentThought={task.subagent_info.current_thought}
                        agentName={task.subagent_info.agent_name}
                      />
                    )}

                    {/* 验收面板 */}
                    {showVerification && onApprove && onReject && (
                      <VerificationPanel
                        task={task}
                        onApprove={handleApprove}
                        onReject={handleReject}
                      />
                    )}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          )}
        </div>
      </motion.div>

      {/* AI确认对话框 */}
      <AIConfirmDialog
        isOpen={showAIConfirmDialog}
        taskName={task.task_name}
        onConfirm={handleResume}
        onCancel={() => setShowAIConfirmDialog(false)}
      />
    </>
  );
};

export default EnhancedSlotCard;
