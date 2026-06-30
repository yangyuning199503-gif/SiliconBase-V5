/**
 * 思维流面板组件 - V2增强版
 * 
 * 功能：
 * - 展示AI思考过程的各个步骤
 * - 支持多种步骤类型：llm、tool、reflection、memory、decision、error
 * - 使用动画效果增强用户体验
 */
import React from 'react';
import { motion } from 'framer-motion';
import { 
  Brain, 
  Wrench, 
  Lightbulb, 
  Database, 
  GitBranch, 
  AlertCircle,
  Clock
} from 'lucide-react';

// 步骤类型定义
export type ThinkingStepType = 'llm' | 'tool' | 'reflection' | 'memory' | 'decision' | 'error';

// 步骤类型配置
const STEP_TYPES: Record<ThinkingStepType, { 
  label: string; 
  color: string; 
  icon: React.ReactNode;
  bgColor: string;
  borderColor: string;
}> = {
  llm: { 
    label: 'AI思考', 
    color: 'blue',
    icon: <Brain className="w-4 h-4" />,
    bgColor: 'bg-blue-900/30',
    borderColor: 'border-blue-700'
  },
  tool: { 
    label: '工具调用', 
    color: 'green',
    icon: <Wrench className="w-4 h-4" />,
    bgColor: 'bg-green-900/30',
    borderColor: 'border-green-700'
  },
  reflection: { 
    label: '反思', 
    color: 'purple',
    icon: <Lightbulb className="w-4 h-4" />,
    bgColor: 'bg-purple-900/30',
    borderColor: 'border-purple-700'
  },
  memory: { 
    label: '记忆检索', 
    color: 'yellow',
    icon: <Database className="w-4 h-4" />,
    bgColor: 'bg-yellow-900/30',
    borderColor: 'border-yellow-700'
  },
  decision: { 
    label: '决策', 
    color: 'orange',
    icon: <GitBranch className="w-4 h-4" />,
    bgColor: 'bg-orange-900/30',
    borderColor: 'border-orange-700'
  },
  error: { 
    label: '错误', 
    color: 'red',
    icon: <AlertCircle className="w-4 h-4" />,
    bgColor: 'bg-red-900/30',
    borderColor: 'border-red-700'
  }
};

// 思考步骤接口
export interface ThinkingStep {
  id: string;
  type: ThinkingStepType;
  content: string;
  timestamp: number;
  details?: Record<string, any>;
  duration?: number;  // 执行耗时(ms)
}

// 思维流属性接口
interface ThinkingFlowProps {
  steps: ThinkingStep[];
  className?: string;
  showDetails?: boolean;
  maxHeight?: string;
}

/**
 * 格式化时间戳
 */
function formatTime(timestamp: number): string {
  const date = new Date(timestamp);
  return date.toLocaleTimeString('zh-CN', { 
    hour: '2-digit', 
    minute: '2-digit', 
    second: '2-digit',
    hour12: false 
  });
}

/**
 * 格式化持续时间
 */
function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/**
 * 思考步骤卡片组件
 */
const ThinkingStepCard: React.FC<{ step: ThinkingStep; showDetails: boolean }> = ({ 
  step, 
  showDetails 
}) => {
  const config = STEP_TYPES[step.type];
  
  return (
    <motion.div
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 20 }}
      className={`p-3 rounded-lg border ${config.bgColor} ${config.borderColor} mb-3`}
    >
      {/* 头部信息 */}
      <div className="flex items-center gap-2 mb-2">
        <span className={`text-${config.color}-400`}>
          {config.icon}
        </span>
        <span className="font-medium text-white text-sm">
          {config.label}
        </span>
        <span className="text-xs text-sb-text-secondary ml-auto flex items-center gap-1">
          <Clock className="w-3 h-3" />
          {formatTime(step.timestamp)}
        </span>
        {step.duration && step.duration > 0 && (
          <span className="text-xs text-sb-text-secondary">
            ({formatDuration(step.duration)})
          </span>
        )}
      </div>
      
      {/* 内容 */}
      <div className="text-sm text-gray-300 whitespace-pre-wrap">
        {step.content}
      </div>
      
      {/* 详细信息 */}
      {showDetails && step.details && Object.keys(step.details).length > 0 && (
        <motion.div 
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: 'auto' }}
          className="mt-2 p-2 bg-black/30 rounded text-xs overflow-auto max-h-40"
        >
          <pre className="text-gray-400 font-mono">
            {JSON.stringify(step.details, null, 2)}
          </pre>
        </motion.div>
      )}
    </motion.div>
  );
};

/**
 * 思维流面板组件
 */
export const ThinkingFlow: React.FC<ThinkingFlowProps> = ({ 
  steps, 
  className = '',
  showDetails = true,
  maxHeight = '400px'
}) => {
  if (!steps || steps.length === 0) {
    return (
      <div className={`p-4 text-center text-sb-text-secondary ${className}`}>
        <Brain className="w-8 h-8 mx-auto mb-2 opacity-30" />
        <p className="text-sm">暂无思考记录</p>
      </div>
    );
  }

  return (
    <div className={`space-y-2 ${className}`}>
      {/* 头部统计 */}
      <div className="flex items-center justify-between px-2 py-2 border-b border-white/5">
        <div className="flex items-center gap-2">
          <Brain className="w-4 h-4 text-sb-cyan" />
          <span className="text-sm font-medium text-white">思维流</span>
          <span className="text-xs text-sb-text-secondary">({steps.length} 步)</span>
        </div>
        <div className="flex gap-1">
          {(Object.keys(STEP_TYPES) as ThinkingStepType[]).map(type => {
            const count = steps.filter(s => s.type === type).length;
            if (count === 0) return null;
            const config = STEP_TYPES[type];
            return (
              <span 
                key={type} 
                className={`text-xs px-2 py-0.5 rounded-full bg-${config.color}-500/20 text-${config.color}-400`}
              >
                {config.label} {count}
              </span>
            );
          })}
        </div>
      </div>
      
      {/* 步骤列表 */}
      <div 
        className="overflow-y-auto px-2 py-2"
        style={{ maxHeight }}
      >
        {steps.map((step, index) => (
          <motion.div
            key={step.id}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.05 }}
          >
            <ThinkingStepCard step={step} showDetails={showDetails} />
          </motion.div>
        ))}
      </div>
    </div>
  );
};

/**
 * 思维流面板 - 紧凑版
 * 用于空间有限的场景
 */
export const ThinkingFlowCompact: React.FC<ThinkingFlowProps> = ({ 
  steps, 
  className = ''
}) => {
  if (!steps || steps.length === 0) {
    return null;
  }

  const latestStep = steps[steps.length - 1];
  const config = STEP_TYPES[latestStep.type];

  return (
    <div className={`flex items-center gap-2 px-3 py-2 bg-sb-bg-secondary rounded-lg border border-white/5 ${className}`}>
      <span className={`text-${config.color}-400`}>
        {config.icon}
      </span>
      <span className="text-sm text-white truncate flex-1">
        {config.label}: {latestStep.content.slice(0, 50)}
        {latestStep.content.length > 50 ? '...' : ''}
      </span>
      <span className="text-xs text-sb-text-secondary">
        {steps.length} 步
      </span>
    </div>
  );
};

/**
 * 思维流钩子 - 用于管理思维步骤状态
 */
export function useThinkingFlow() {
  const [steps, setSteps] = React.useState<ThinkingStep[]>([]);
  const [isThinking, setIsThinking] = React.useState(false);

  const addStep = React.useCallback((step: Omit<ThinkingStep, 'id' | 'timestamp'>) => {
    const newStep: ThinkingStep = {
      ...step,
      id: `step_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      timestamp: Date.now()
    };
    setSteps(prev => [...prev, newStep]);
  }, []);

  const updateLastStep = React.useCallback((updates: Partial<ThinkingStep>) => {
    setSteps(prev => {
      if (prev.length === 0) return prev;
      const last = prev[prev.length - 1];
      return [
        ...prev.slice(0, -1),
        { ...last, ...updates }
      ];
    });
  }, []);

  const clearSteps = React.useCallback(() => {
    setSteps([]);
  }, []);

  const startThinking = React.useCallback(() => {
    setIsThinking(true);
    setSteps([]);
  }, []);

  const stopThinking = React.useCallback(() => {
    setIsThinking(false);
  }, []);

  return {
    steps,
    isThinking,
    addStep,
    updateLastStep,
    clearSteps,
    startThinking,
    stopThinking
  };
}

export default ThinkingFlow;
