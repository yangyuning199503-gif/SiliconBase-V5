/**
 * 任务拆解可视化组件 - "太子" (Task Planning Visualization)
 * 
 * 功能：
 * - 显示任务被拆解为哪些步骤
 * - 支持步骤状态的实时更新
 * - 参考唐朝太子监国制度，体现任务规划的重要性
 */
import React from 'react';
import { motion } from 'framer-motion';
import { 
  Crown, 
  CheckCircle2, 
  Circle, 
  Clock, 
  AlertCircle,
  ChevronRight,
  Layers
} from 'lucide-react';

// 步骤状态类型
export type StepStatus = 'pending' | 'executing' | 'completed' | 'failed' | 'skipped';

// 任务步骤接口
export interface TaskStep {
  id: string;
  index: number;
  name: string;
  tool?: string;
  status: StepStatus;
  description?: string;
  estimatedTime?: number; // 预估执行时间(秒)
}

// 任务拆解属性接口
interface TaskBreakdownProps {
  steps: TaskStep[];
  title?: string;
  className?: string;
  showProgress?: boolean;
  onStepClick?: (step: TaskStep) => void;
}

// 状态配置
const STATUS_CONFIG: Record<StepStatus, { 
  label: string; 
  color: string; 
  icon: React.ReactNode;
  bgColor: string;
  borderColor: string;
}> = {
  pending: { 
    label: '待执行', 
    color: 'text-slate-400',
    icon: <Circle className="w-4 h-4" />,
    bgColor: 'bg-slate-500/10',
    borderColor: 'border-slate-500/30'
  },
  executing: { 
    label: '执行中', 
    color: 'text-amber-400',
    icon: <Clock className="w-4 h-4 animate-pulse" />,
    bgColor: 'bg-amber-500/10',
    borderColor: 'border-amber-500/50'
  },
  completed: { 
    label: '已完成', 
    color: 'text-emerald-400',
    icon: <CheckCircle2 className="w-4 h-4" />,
    bgColor: 'bg-emerald-500/10',
    borderColor: 'border-emerald-500/30'
  },
  failed: { 
    label: '失败', 
    color: 'text-red-400',
    icon: <AlertCircle className="w-4 h-4" />,
    bgColor: 'bg-red-500/10',
    borderColor: 'border-red-500/30'
  },
  skipped: { 
    label: '已跳过', 
    color: 'text-slate-500',
    icon: <ChevronRight className="w-4 h-4" />,
    bgColor: 'bg-slate-500/5',
    borderColor: 'border-slate-500/20'
  }
};

/**
 * 步骤卡片组件
 */
const StepCard: React.FC<{ 
  step: TaskStep; 
  isLast: boolean;
  onClick?: (step: TaskStep) => void;
}> = ({ step, isLast, onClick }) => {
  const config = STATUS_CONFIG[step.status];
  
  return (
    <motion.div
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      className={`relative flex items-start gap-3 p-3 rounded-lg border ${config.bgColor} ${config.borderColor}
                  ${onClick ? 'cursor-pointer hover:brightness-110' : ''} transition-all`}
      onClick={() => onClick?.(step)}
    >
      {/* 步骤序号 */}
      <div className={`flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold
                       ${config.bgColor} ${config.color} border ${config.borderColor}`}>
        {step.index}
      </div>
      
      {/* 内容区 */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-white truncate">
            {step.name}
          </span>
          <span className={`text-xs ${config.color} flex items-center gap-1`}>
            {config.icon}
            {config.label}
          </span>
        </div>
        
        {step.description && (
          <p className="text-xs text-slate-400 mt-1 truncate">
            {step.description}
          </p>
        )}
        
        {step.tool && (
          <div className="flex items-center gap-1 mt-1.5">
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/5 text-slate-500">
              工具: {step.tool}
            </span>
            {step.estimatedTime && step.status === 'pending' && (
              <span className="text-[10px] text-slate-500">
                预计 {step.estimatedTime}s
              </span>
            )}
          </div>
        )}
      </div>
      
      {/* 连接线 */}
      {!isLast && (
        <div className="absolute left-[21px] top-[42px] w-0.5 h-4 bg-white/10" />
      )}
    </motion.div>
  );
};

/**
 * 进度条组件
 */
const ProgressBar: React.FC<{ steps: TaskStep[] }> = ({ steps }) => {
  const total = steps.length;
  const completed = steps.filter(s => s.status === 'completed').length;
  const executing = steps.filter(s => s.status === 'executing').length;
  const progress = total > 0 ? ((completed + (executing ? 0.5 : 0)) / total) * 100 : 0;
  
  return (
    <div className="mb-4">
      <div className="flex items-center justify-between text-xs mb-2">
        <span className="text-slate-400">执行进度</span>
        <span className="text-slate-300">
          {completed}/{total} 步骤
          {executing > 0 && <span className="text-amber-400 ml-1">({executing} 执行中)</span>}
        </span>
      </div>
      <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${progress}%` }}
          transition={{ duration: 0.5 }}
          className="h-full bg-gradient-to-r from-amber-500 to-emerald-500 rounded-full"
        />
      </div>
    </div>
  );
};

/**
 * 任务拆解可视化组件
 */
export const TaskBreakdown: React.FC<TaskBreakdownProps> = ({ 
  steps, 
  title = "任务规划",
  className = '',
  showProgress = true,
  onStepClick
}) => {
  if (!steps || steps.length === 0) {
    return (
      <div className={`p-4 rounded-lg bg-slate-900/50 border border-white/5 ${className}`}>
        <div className="flex items-center gap-2 text-slate-500">
          <Layers className="w-4 h-4" />
          <span className="text-sm">暂无任务规划</span>
        </div>
      </div>
    );
  }

  // 按index排序
  const sortedSteps = [...steps].sort((a, b) => a.index - b.index);

  return (
    <div className={`rounded-lg bg-slate-900/50 border border-white/5 overflow-hidden ${className}`}>
      {/* 头部 - 太子标识 */}
      <div className="px-4 py-3 border-b border-white/5 bg-gradient-to-r from-amber-500/10 to-transparent">
        <div className="flex items-center gap-2">
          <Crown className="w-4 h-4 text-amber-400" />
          <span className="text-sm font-medium text-white">{title}</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400">
            太子监国
          </span>
        </div>
      </div>
      
      {/* 内容区 */}
      <div className="p-4">
        {showProgress && <ProgressBar steps={sortedSteps} />}
        
        <div className="space-y-2">
          {sortedSteps.map((step, index) => (
            <StepCard
              key={step.id}
              step={step}
              isLast={index === sortedSteps.length - 1}
              onClick={onStepClick}
            />
          ))}
        </div>
      </div>
    </div>
  );
};

/**
 * 紧凑版任务拆解
 */
export const TaskBreakdownCompact: React.FC<{
  steps: TaskStep[];
  className?: string;
}> = ({ steps, className = '' }) => {
  if (!steps || steps.length === 0) return null;
  
  const sortedSteps = [...steps].sort((a, b) => a.index - b.index);
  const currentStep = sortedSteps.find(s => s.status === 'executing') || sortedSteps[0];
  const completedCount = sortedSteps.filter(s => s.status === 'completed').length;
  
  return (
    <div className={`flex items-center gap-3 px-3 py-2 rounded-lg bg-slate-900/50 border border-white/5 ${className}`}>
      <Crown className="w-4 h-4 text-amber-400" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm text-white truncate">
            {currentStep.name}
          </span>
          <span className="text-xs text-slate-400">
            ({completedCount}/{sortedSteps.length})
          </span>
        </div>
        <div className="h-1 bg-white/5 rounded-full mt-1.5 overflow-hidden">
          <div 
            className="h-full bg-amber-500 rounded-full transition-all duration-300"
            style={{ width: `${(completedCount / sortedSteps.length) * 100}%` }}
          />
        </div>
      </div>
    </div>
  );
};

/**
 * 使用任务拆解的Hook
 */
export function useTaskBreakdown() {
  const [steps, setSteps] = React.useState<TaskStep[]>([]);
  
  const updateSteps = React.useCallback((newSteps: TaskStep[]) => {
    setSteps(newSteps);
  }, []);
  
  const updateStepStatus = React.useCallback((stepId: string, status: StepStatus) => {
    setSteps(prev => prev.map(step => 
      step.id === stepId ? { ...step, status } : step
    ));
  }, []);
  
  const addStep = React.useCallback((step: Omit<TaskStep, 'id'>) => {
    const newStep: TaskStep = {
      ...step,
      id: `step_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
    };
    setSteps(prev => [...prev, newStep]);
  }, []);
  
  const clearSteps = React.useCallback(() => {
    setSteps([]);
  }, []);
  
  const getProgress = React.useCallback(() => {
    if (steps.length === 0) return 0;
    return (steps.filter(s => s.status === 'completed').length / steps.length) * 100;
  }, [steps]);
  
  return {
    steps,
    updateSteps,
    updateStepStatus,
    addStep,
    clearSteps,
    getProgress,
    isComplete: steps.every(s => s.status === 'completed' || s.status === 'skipped'),
    isExecuting: steps.some(s => s.status === 'executing')
  };
}

export default TaskBreakdown;
