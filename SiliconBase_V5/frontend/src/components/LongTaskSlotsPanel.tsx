/**
 * 3槽位长任务面板
 * 大纲要求：长期任务的3个面板，用户查看和暂停恢复，AI可修改
 */
import React, { useState } from 'react';
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
  ChevronUp
} from 'lucide-react';
import { SubAgentMonitor } from './SubAgentMonitor';

export interface SlotTask {
  slot_id: number;
  task_id?: string;
  task_name?: string;
  task_type?: string;
  status: 'idle' | 'running' | 'paused' | 'error';
  progress: number;
  ai_understanding?: string;
  created_at?: number;
  description?: string;
  // SubAgent相关字段
  has_subagent_pipeline?: boolean;
  subagent_pipeline_name?: string;
}

export interface LongTaskSlotsPanelProps {
  slots: SlotTask[];
  onPause: (slotId: number) => void;
  onResume: (slotId: number, aiConfirmation: string) => void;
  onStop: (slotId: number) => void;
  onCreateTask?: (slotId: number) => void;
  loading?: boolean;
}

// 获取状态标签
const getStatusLabel = (status: SlotTask['status']): string => {
  switch (status) {
    case 'running':
      return '运行中';
    case 'paused':
      return '已暂停';
    case 'error':
      return '错误';
    case 'idle':
      return '空闲';
    default:
      return '未知';
  }
};

// 获取状态颜色类
const getStatusColorClass = (status: SlotTask['status']): string => {
  switch (status) {
    case 'running':
      return 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20';
    case 'paused':
      return 'text-yellow-400 bg-yellow-400/10 border-yellow-400/20';
    case 'error':
      return 'text-red-400 bg-red-400/10 border-red-400/20';
    case 'idle':
      return 'text-slate-400 bg-slate-400/10 border-slate-400/20';
    default:
      return 'text-slate-400 bg-slate-400/10 border-slate-400/20';
  }
};

// 获取进度条颜色
const getProgressColorClass = (status: SlotTask['status']): string => {
  switch (status) {
    case 'running':
      return 'bg-emerald-400';
    case 'paused':
      return 'bg-yellow-400';
    case 'error':
      return 'bg-red-400';
    case 'idle':
      return 'bg-slate-400';
    default:
      return 'bg-slate-400';
  }
};

// 获取状态图标
const getStatusIcon = (status: SlotTask['status']) => {
  switch (status) {
    case 'running':
      return <Loader2 className="w-4 h-4 animate-spin" />;
    case 'paused':
      return <Pause className="w-4 h-4" />;
    case 'error':
      return <AlertCircle className="w-4 h-4" />;
    case 'idle':
      return <Clock className="w-4 h-4" />;
    default:
      return <Clock className="w-4 h-4" />;
  }
};

// AI确认对话框组件
interface AIConfirmDialogProps {
  slot: SlotTask;
  onConfirm: (confirmation: string) => void;
  onCancel: () => void;
}

const AIConfirmDialog: React.FC<AIConfirmDialogProps> = ({ slot, onConfirm, onCancel }) => {
  const [confirmation, setConfirmation] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleConfirm = async () => {
    if (!confirmation.trim()) {
      return;
    }
    setIsSubmitting(true);
    try {
      await onConfirm(confirmation);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
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
        {/* 标题区域 */}
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-full bg-yellow-500/20 flex items-center justify-center">
            <Bot className="w-5 h-5 text-yellow-400" />
          </div>
          <div>
            <h4 className="text-white font-semibold">AI理解确认</h4>
            <p className="text-slate-400 text-sm">槽位 {slot.slot_id} - {slot.task_name}</p>
          </div>
        </div>

        {/* 警告提示 */}
        <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-lg p-4 mb-4">
          <p className="text-yellow-400 text-sm flex items-start gap-2">
            <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
            <span>
              <strong>重要提示：</strong>AI必须确认百分百理解用户需求后才能恢复任务。
              请AI在此详细描述对当前任务的理解，确认无误后方可继续执行。
            </span>
          </p>
        </div>

        {/* 任务信息回顾 */}
        <div className="bg-slate-900/50 rounded-lg p-3 mb-4">
          <p className="text-slate-400 text-xs mb-1">当前任务描述：</p>
          <p className="text-slate-300 text-sm line-clamp-3">
            {slot.description || '暂无描述'}
          </p>
        </div>

        {/* AI确认输入 */}
        <div className="mb-4">
          <label className="block text-slate-300 text-sm mb-2">
            AI理解确认内容 <span className="text-red-400">*</span>
          </label>
          <textarea
            value={confirmation}
            onChange={(e) => setConfirmation(e.target.value)}
            placeholder="请AI在此输入对任务的完整理解，包括但不限于：任务目标、执行步骤、预期产出、注意事项等..."
            className="w-full h-32 bg-slate-900 border border-white/10 rounded-lg px-3 py-2 text-white text-sm placeholder:text-slate-600 focus:outline-none focus:border-yellow-500/50 resize-none"
          />
          <p className="text-slate-500 text-xs mt-1">
            字数要求：至少输入20个字符
          </p>
        </div>

        {/* 操作按钮 */}
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
  );
};

// 单个槽位卡片组件
interface SlotCardProps {
  slot: SlotTask;
  onPause: (slotId: number) => void;
  onResume: (slotId: number, aiConfirmation: string) => void;
  onStop: (slotId: number) => void;
  onCreateTask?: (slotId: number) => void;
}

const SlotCard: React.FC<SlotCardProps> = ({ 
  slot, 
  onPause, 
  onResume, 
  onStop, 
  onCreateTask 
}) => {
  const [showConfirmDialog, setShowConfirmDialog] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [showSubAgentMonitor, setShowSubAgentMonitor] = useState(false);

  const handlePause = async () => {
    setIsLoading(true);
    try {
      await onPause(slot.slot_id);
    } finally {
      setIsLoading(false);
    }
  };

  const handleStop = async () => {
    setIsLoading(true);
    try {
      await onStop(slot.slot_id);
    } finally {
      setIsLoading(false);
    }
  };

  const handleResumeConfirm = async (confirmation: string) => {
    setIsLoading(true);
    try {
      await onResume(slot.slot_id, confirmation);
      setShowConfirmDialog(false);
    } finally {
      setIsLoading(false);
    }
  };

  const handleCreateTask = () => {
    onCreateTask?.(slot.slot_id);
  };

  return (
    <>
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: slot.slot_id * 0.1 }}
        className={`
          relative rounded-xl border p-4 transition-all
          ${slot.status === 'idle' 
            ? 'bg-slate-800/30 border-slate-700/50' 
            : 'bg-slate-800/50 border-white/10 hover:border-white/20'
          }
        `}
      >
        {/* 槽位编号标记 */}
        <div className="absolute -top-3 -left-3 w-8 h-8 rounded-full bg-slate-700 border border-white/10 flex items-center justify-center text-white font-semibold text-sm">
          {slot.slot_id}
        </div>

        {/* 槽位内容 */}
        <div className="mt-2">
          {/* 任务名称或空闲提示 */}
          <div className="mb-3">
            {slot.status === 'idle' ? (
              <div className="text-center py-8">
                <div className="w-12 h-12 rounded-full bg-slate-700/50 flex items-center justify-center mx-auto mb-3">
                  <Plus className="w-6 h-6 text-slate-500" />
                </div>
                <p className="text-slate-500 text-sm">槽位空闲</p>
                <p className="text-slate-600 text-xs mt-1">等待分配任务</p>
              </div>
            ) : (
              <>
                <h4 className="text-white font-medium truncate pr-2">
                  {slot.task_name || '未命名任务'}
                </h4>
                {slot.task_type && (
                  <p className="text-slate-500 text-xs mt-1">
                    类型: {slot.task_type}
                  </p>
                )}
              </>
            )}
          </div>

          {/* 状态标签和进度条 - 仅在非空闲状态显示 */}
          {slot.status !== 'idle' && (
            <>
              {/* 状态标签 */}
              <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs mb-3 ${getStatusColorClass(slot.status)}`}>
                {getStatusIcon(slot.status)}
                <span>{getStatusLabel(slot.status)}</span>
              </div>

              {/* 进度条 */}
              <div className="mb-4">
                <div className="flex justify-between text-xs text-slate-400 mb-1">
                  <span>进度</span>
                  <span className="text-white font-medium">{slot.progress}%</span>
                </div>
                <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: `${slot.progress}%` }}
                    transition={{ duration: 0.5 }}
                    className={`h-full ${getProgressColorClass(slot.status)}`}
                  />
                </div>
              </div>
            </>
          )}

          {/* 操作按钮 */}
          <div className="flex items-center justify-center gap-2">
            {slot.status === 'idle' && onCreateTask && (
              <button
                onClick={handleCreateTask}
                disabled={isLoading}
                className="flex items-center gap-1.5 px-4 py-2 bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-400 rounded-lg text-sm transition-all"
              >
                <Plus className="w-4 h-4" />
                创建任务
              </button>
            )}

            {slot.status === 'running' && (
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

            {slot.status === 'paused' && (
              <>
                <button
                  onClick={() => setShowConfirmDialog(true)}
                  disabled={isLoading}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-400 rounded-lg text-sm transition-all disabled:opacity-50"
                >
                  {isLoading ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Play className="w-3.5 h-3.5" />
                  )}
                  恢复
                  <span className="text-xs opacity-70">(需AI确认)</span>
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

            {slot.status === 'error' && (
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
                清除错误
              </button>
            )}
          </div>

          {/* AI理解确认状态指示（仅在暂停状态显示） */}
          {slot.status === 'paused' && slot.ai_understanding && (
            <div className="mt-3 p-2 bg-slate-900/50 rounded-lg border border-white/5">
              <p className="text-xs text-slate-400 flex items-center gap-1">
                <Bot className="w-3 h-3" />
                上次AI确认: {slot.ai_understanding.slice(0, 50)}...
              </p>
            </div>
          )}

          {/* SubAgent监控按钮（仅在运行中或已暂停状态显示） */}
          {(slot.status === 'running' || slot.status === 'paused') && slot.task_id && (
            <div className="mt-3">
              <button
                onClick={() => setShowSubAgentMonitor(!showSubAgentMonitor)}
                className={`
                  w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm
                  transition-all duration-200
                  ${showSubAgentMonitor 
                    ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30' 
                    : 'bg-slate-700/30 hover:bg-slate-700/50 text-slate-300 border border-transparent'}
                `}
              >
                <Activity className="w-4 h-4" />
                <span>
                  {showSubAgentMonitor ? '隐藏执行详情' : '查看执行详情'}
                </span>
                {showSubAgentMonitor ? (
                  <ChevronUp className="w-4 h-4" />
                ) : (
                  <ChevronDown className="w-4 h-4" />
                )}
              </button>

              {/* SubAgent监控面板 */}
              <AnimatePresence>
                {showSubAgentMonitor && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    exit={{ opacity: 0, height: 0 }}
                    transition={{ duration: 0.3 }}
                    className="mt-3"
                  >
                    <SubAgentMonitor
                      slot_id={slot.slot_id}
                      task_id={slot.task_id}
                      onClose={() => setShowSubAgentMonitor(false)}
                    />
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          )}
        </div>
      </motion.div>

      {/* AI确认对话框 */}
      <AnimatePresence>
        {showConfirmDialog && (
          <AIConfirmDialog
            slot={slot}
            onConfirm={handleResumeConfirm}
            onCancel={() => setShowConfirmDialog(false)}
          />
        )}
      </AnimatePresence>
    </>
  );
};

// 主组件
export const LongTaskSlotsPanel: React.FC<LongTaskSlotsPanelProps> = ({
  slots,
  onPause,
  onResume,
  onStop,
  onCreateTask,
  loading
}) => {
  // 确保总是显示3个槽位
  const normalizedSlots: SlotTask[] = [1, 2, 3].map(slotId => {
    const existingSlot = slots.find(s => s.slot_id === slotId);
    return existingSlot || {
      slot_id: slotId,
      status: 'idle' as const,
      progress: 0
    };
  });

  return (
    <div className="long-task-slots-panel">
      {/* 面板标题 */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-white font-semibold flex items-center gap-2">
            <Clock className="w-5 h-5 text-cyan-400" />
            长期任务 - 3槽位面板
          </h3>
          <p className="text-slate-400 text-sm mt-1">
            管理长期运行任务，支持暂停和恢复操作
          </p>
        </div>
        
        {/* 槽位状态摘要 */}
        <div className="flex items-center gap-3 text-xs">
          <div className="flex items-center gap-1">
            <div className="w-2 h-2 rounded-full bg-emerald-400" />
            <span className="text-slate-400">
              运行中: {normalizedSlots.filter(s => s.status === 'running').length}
            </span>
          </div>
          <div className="flex items-center gap-1">
            <div className="w-2 h-2 rounded-full bg-yellow-400" />
            <span className="text-slate-400">
              已暂停: {normalizedSlots.filter(s => s.status === 'paused').length}
            </span>
          </div>
          <div className="flex items-center gap-1">
            <div className="w-2 h-2 rounded-full bg-slate-400" />
            <span className="text-slate-400">
              空闲: {normalizedSlots.filter(s => s.status === 'idle').length}
            </span>
          </div>
        </div>
      </div>

      {/* 3槽位网格布局 */}
      <div 
        className="slots-grid"
        style={{ 
          display: 'grid', 
          gridTemplateColumns: 'repeat(3, 1fr)', 
          gap: '20px' 
        }}
      >
        {normalizedSlots.map((slot) => (
          <SlotCard
            key={slot.slot_id}
            slot={slot}
            onPause={onPause}
            onResume={onResume}
            onStop={onStop}
            onCreateTask={onCreateTask}
          />
        ))}
      </div>

      {/* 全局加载状态 */}
      {loading && (
        <div className="mt-4 flex items-center justify-center gap-2 text-slate-400 text-sm">
          <Loader2 className="w-4 h-4 animate-spin" />
          <span>处理中...</span>
        </div>
      )}

      {/* 响应式样式 */}
      <style>{`
        @media (max-width: 1024px) {
          .slots-grid {
            grid-template-columns: repeat(2, 1fr) !important;
          }
        }
        @media (max-width: 640px) {
          .slots-grid {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>
    </div>
  );
};

export default LongTaskSlotsPanel;
