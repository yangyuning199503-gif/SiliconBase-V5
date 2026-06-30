/**
 * 增强版3槽位长任务面板
 * Phase 4.5: 前端槽位显示增强
 * 
 * 功能：
 * - 支持增强槽位任务类型
 * - 集成验收面板
 * - 支持子代理流式输出显示
 * - 支持检查点操作
 */

import React, { useState, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  Clock,
  Loader2,
  RefreshCw,
  AlertCircle,
  CheckCircle2
} from 'lucide-react';
import { EnhancedSlotCard } from './EnhancedSlotCard';
import type { EnhancedSlotTask, SlotStatus } from '../types/slot';

// ========== 组件 Props ==========

interface EnhancedSlotsPanelProps {
  // 槽位数据（增强类型）
  tasks?: EnhancedSlotTask[];
  
  // 传统槽位数据（向后兼容）
  slots?: Array<{
    slot_id: number;
    task_id?: string;
    task_name?: string;
    status: 'idle' | 'running' | 'paused' | 'error';
    progress: number;
    description?: string;
  }>;
  
  // 回调函数
  onPause?: (slotId: number) => Promise<void>;
  onResume?: (slotId: number, confirmation?: string) => Promise<void>;
  onStop?: (slotId: number) => Promise<void>;
  onApprove?: (slotId: number) => Promise<void>;
  onReject?: (slotId: number, feedback: string) => Promise<void>;
  onCreateTask?: (slotId: number) => void;
  onResumeFromCheckpoint?: (slotId: number, checkpointId: string) => Promise<void>;
  onRefresh?: () => Promise<void>;
  
  // 状态
  loading?: boolean;
  error?: string | null;
  
  // 样式
  className?: string;
}

// ========== 辅助函数 ==========

// 将传统槽位数据转换为增强槽位数据
const convertToEnhancedTask = (
  slot: NonNullable<EnhancedSlotsPanelProps['slots']>[number],
  index: number
): EnhancedSlotTask => {
  const statusMap: Record<string, SlotStatus> = {
    'idle': 'idle',
    'running': 'running',
    'paused': 'paused',
    'error': 'failed'
  };

  return {
    slot_id: slot.slot_id || index + 1,
    task_type: 'workflow',
    status: statusMap[slot.status] || 'idle',
    progress: {
      current: Math.floor((slot.progress / 100) * 10),
      total: 10,
      percentage: slot.progress
    },
    task_id: slot.task_id,
    task_name: slot.task_name,
    description: slot.description,
    controls: {
      can_pause: slot.status === 'running',
      can_resume: slot.status === 'paused',
      can_cancel: slot.status !== 'idle',
      can_approve: false,
      can_reject: false
    }
  };
};

// 默认控制状态
const getDefaultControls = (status: SlotStatus): EnhancedSlotTask['controls'] => ({
  can_pause: status === 'running',
  can_resume: status === 'paused',
  can_cancel: status !== 'idle',
  can_approve: status === 'waiting_approval',
  can_reject: status === 'waiting_approval'
});

// 创建默认空槽位
const createEmptySlot = (slotId: number): EnhancedSlotTask => ({
  slot_id: slotId,
  task_type: 'workflow',
  status: 'idle',
  progress: {
    current: 0,
    total: 0,
    percentage: 0
  },
  controls: getDefaultControls('idle')
});

// ========== 状态摘要组件 ==========

interface StatusSummaryProps {
  tasks: EnhancedSlotTask[];
}

const StatusSummary: React.FC<StatusSummaryProps> = ({ tasks }) => {
  const counts = {
    running: tasks.filter(t => t.status === 'running').length,
    paused: tasks.filter(t => t.status === 'paused').length,
    waiting_approval: tasks.filter(t => t.status === 'waiting_approval').length,
    idle: tasks.filter(t => t.status === 'idle').length,
    completed: tasks.filter(t => t.status === 'completed').length,
    failed: tasks.filter(t => t.status === 'failed').length
  };

  return (
    <div className="flex flex-wrap items-center gap-3 text-xs">
      {counts.running > 0 && (
        <div className="flex items-center gap-1">
          <div className="w-2 h-2 rounded-full bg-emerald-400" />
          <span className="text-slate-400">
            运行中: {counts.running}
          </span>
        </div>
      )}
      {counts.paused > 0 && (
        <div className="flex items-center gap-1">
          <div className="w-2 h-2 rounded-full bg-yellow-400" />
          <span className="text-slate-400">
            已暂停: {counts.paused}
          </span>
        </div>
      )}
      {counts.waiting_approval > 0 && (
        <div className="flex items-center gap-1">
          <div className="w-2 h-2 rounded-full bg-purple-400" />
          <span className="text-slate-400">
            待验收: {counts.waiting_approval}
          </span>
        </div>
      )}
      {counts.completed > 0 && (
        <div className="flex items-center gap-1">
          <div className="w-2 h-2 rounded-full bg-blue-400" />
          <span className="text-slate-400">
            已完成: {counts.completed}
          </span>
        </div>
      )}
      {counts.failed > 0 && (
        <div className="flex items-center gap-1">
          <div className="w-2 h-2 rounded-full bg-red-400" />
          <span className="text-slate-400">
            失败: {counts.failed}
          </span>
        </div>
      )}
      <div className="flex items-center gap-1">
        <div className="w-2 h-2 rounded-full bg-slate-400" />
        <span className="text-slate-400">
          空闲: {counts.idle}
        </span>
      </div>
    </div>
  );
};

// ========== 主组件 ==========

export const EnhancedSlotsPanel: React.FC<EnhancedSlotsPanelProps> = ({
  tasks,
  slots,
  onPause,
  onResume,
  onStop,
  onApprove,
  onReject,
  onCreateTask,
  onResumeFromCheckpoint,
  onRefresh,
  loading = false,
  error = null,
  className = ''
}) => {
  const [isRefreshing, setIsRefreshing] = useState(false);

  // 处理刷新
  const handleRefresh = useCallback(async () => {
    if (!onRefresh || isRefreshing) return;
    setIsRefreshing(true);
    try {
      await onRefresh();
    } finally {
      setIsRefreshing(false);
    }
  }, [onRefresh, isRefreshing]);

  // 标准化槽位数据
  const normalizedTasks: EnhancedSlotTask[] = [1, 2, 3].map((slotId, index) => {
    // 优先使用增强类型数据
    if (tasks && tasks.length > 0) {
      const existingTask = tasks.find(t => t.slot_id === slotId);
      if (existingTask) {
        // 确保 controls 存在
        return {
          ...existingTask,
          controls: existingTask.controls || getDefaultControls(existingTask.status)
        };
      }
    }
    
    // 向后兼容：转换传统槽位数据
    if (slots && slots.length > 0) {
      const existingSlot = slots.find(s => s.slot_id === slotId);
      if (existingSlot) {
        return convertToEnhancedTask(existingSlot, index);
      }
    }
    
    // 返回空槽位
    return createEmptySlot(slotId);
  });

  return (
    <div className={`enhanced-slots-panel ${className}`}>
      {/* 面板标题 */}
      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <div>
          <h3 className="text-white font-semibold flex items-center gap-2">
            <Clock className="w-5 h-5 text-cyan-400" />
            长期任务 - 3槽位面板
            <span className="text-xs font-normal text-slate-500 bg-slate-800 px-2 py-0.5 rounded-full">
              Phase 4.5
            </span>
          </h3>
          <p className="text-slate-400 text-sm mt-1">
            支持工作流、子代理和混合任务，集成验收流程
          </p>
        </div>
        
        <div className="flex items-center gap-3">
          {/* 状态摘要 */}
          <StatusSummary tasks={normalizedTasks} />
          
          {/* 刷新按钮 */}
          {onRefresh && (
            <button
              onClick={handleRefresh}
              disabled={isRefreshing || loading}
              className="flex items-center gap-1 px-3 py-1.5 bg-slate-700/50 hover:bg-slate-700 text-slate-300 rounded-lg text-sm transition-all disabled:opacity-50"
            >
              {isRefreshing ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <RefreshCw className="w-4 h-4" />
              )}
              刷新
            </button>
          )}
        </div>
      </div>

      {/* 错误提示 */}
      {error && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg"
        >
          <p className="text-red-400 text-sm flex items-center gap-2">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            <span>{error}</span>
          </p>
        </motion.div>
      )}

      {/* 3槽位网格布局 */}
      <div 
        className="slots-grid"
        style={{ 
          display: 'grid', 
          gridTemplateColumns: 'repeat(3, 1fr)', 
          gap: '20px' 
        }}
      >
        {normalizedTasks.map((task) => (
          <EnhancedSlotCard
            key={task.slot_id}
            task={task}
            onPause={onPause}
            onResume={onResume}
            onStop={onStop}
            onApprove={onApprove}
            onReject={onReject}
            onCreateTask={onCreateTask}
            onResumeFromCheckpoint={onResumeFromCheckpoint}
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

      {/* 功能说明 */}
      <div className="mt-4 p-3 bg-slate-800/30 rounded-lg border border-white/5">
        <p className="text-slate-500 text-xs flex items-start gap-2">
          <CheckCircle2 className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span>
            <strong className="text-slate-400">Phase 4.5 增强功能：</strong>
            支持工作流与子代理融合执行、AI自动验收、人工确认流程、检查点保存与恢复、
            子代理流式输出实时显示
          </span>
        </p>
      </div>

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

// 导出兼容的默认组件
export default EnhancedSlotsPanel;

// 为了向后兼容，同时提供 LongTaskSlotsPanel 的增强版本
export { EnhancedSlotsPanel as LongTaskSlotsPanel };
