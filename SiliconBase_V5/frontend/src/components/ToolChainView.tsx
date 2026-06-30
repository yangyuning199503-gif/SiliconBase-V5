/**
 * 工具调用链展示组件 - "中书省+尚书省" (Tool Chain Visualization)
 * 
 * 功能：
 * - 显示完整的工具调用规划链
 * - 展示每个节点的参数、状态和执行结果
 * - 参考唐朝三省六部制，中书省决策、尚书省执行
 */
import React from 'react';
import { motion } from 'framer-motion';
import { 
  Wrench, 
  ArrowRight, 
  CheckCircle2, 
  XCircle, 
  Clock, 
  Circle,
  Play,
  RotateCcw,
  FileJson,
  Clock3,
  Activity
} from 'lucide-react';

// 链节点状态
export type ChainNodeStatus = 'planned' | 'executing' | 'completed' | 'failed' | 'waiting';

// 链节点接口
export interface ChainNode {
  id: string;
  tool: string;
  params: Record<string, any>;
  status: ChainNodeStatus;
  result?: {
    success: boolean;
    data?: any;
    message?: string;
  };
  executionTime?: number; // 执行耗时(毫秒)
  startTime?: number;
  endTime?: number;
  retryCount?: number;
  worldModelPrediction?: string; // 世界模型预测
}

// 工具链视图属性
interface ToolChainViewProps {
  nodes: ChainNode[];
  className?: string;
  showParams?: boolean;
  showTiming?: boolean;
  onNodeClick?: (node: ChainNode) => void;
  onRetry?: (nodeId: string) => void;
}

// 状态配置
const STATUS_CONFIG: Record<ChainNodeStatus, { 
  label: string; 
  color: string;
  bgColor: string;
  borderColor: string;
  icon: React.ReactNode;
  pulse?: boolean;
}> = {
  planned: { 
    label: '已规划', 
    color: 'text-slate-400',
    bgColor: 'bg-slate-500/10',
    borderColor: 'border-slate-500/30',
    icon: <Circle className="w-4 h-4" />
  },
  waiting: { 
    label: '等待中', 
    color: 'text-blue-400',
    bgColor: 'bg-blue-500/10',
    borderColor: 'border-blue-500/30',
    icon: <Clock className="w-4 h-4" />
  },
  executing: { 
    label: '执行中', 
    color: 'text-amber-400',
    bgColor: 'bg-amber-500/10',
    borderColor: 'border-amber-500/50',
    icon: <Play className="w-4 h-4" />,
    pulse: true
  },
  completed: { 
    label: '成功', 
    color: 'text-emerald-400',
    bgColor: 'bg-emerald-500/10',
    borderColor: 'border-emerald-500/30',
    icon: <CheckCircle2 className="w-4 h-4" />
  },
  failed: { 
    label: '失败', 
    color: 'text-red-400',
    bgColor: 'bg-red-500/10',
    borderColor: 'border-red-500/30',
    icon: <XCircle className="w-4 h-4" />
  }
};

/**
 * 格式化时间
 */
function formatTime(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/**
 * 格式化参数
 */
function formatParams(params: Record<string, any>): string {
  try {
    const entries = Object.entries(params);
    if (entries.length === 0) return '{}';
    if (entries.length <= 2) {
      return entries.map(([k, v]) => `${k}: ${typeof v === 'string' ? `"${v.slice(0, 20)}"` : v}`).join(', ');
    }
    return `{${entries.length} 个参数}`;
  } catch (error) {
    console.error('[ToolChainView] 格式化参数失败:', error);
    return '{}';
  }
}

/**
 * 链节点卡片
 */
const ChainNodeCard: React.FC<{
  node: ChainNode;
  index: number;
  isLast: boolean;
  showParams: boolean;
  showTiming: boolean;
  onClick?: (node: ChainNode) => void;
  onRetry?: (nodeId: string) => void;
}> = ({ node, index, isLast, showParams, showTiming, onClick, onRetry }) => {
  const config = STATUS_CONFIG[node.status];
  const [expanded, setExpanded] = React.useState(false);
  
  return (
    <div className="relative">
      {/* 连接线 */}
      {!isLast && (
        <div className="absolute left-[27px] top-[56px] w-0.5 h-8 bg-gradient-to-b from-white/20 to-white/5" />
      )}
      
      {/* 节点卡片 */}
      <motion.div
        initial={{ opacity: 0, x: -10 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ delay: index * 0.1 }}
        className={`relative p-3 rounded-lg border ${config.bgColor} ${config.borderColor}
                    ${onClick ? 'cursor-pointer' : ''} transition-all hover:brightness-110`}
        onClick={() => onClick?.(node)}
      >
        {/* 头部 */}
        <div className="flex items-start gap-3">
          {/* 序号和状态 */}
          <div className={`flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center
                           ${config.bgColor} ${config.color} border ${config.borderColor}
                           ${config.pulse ? 'animate-pulse' : ''}`}>
            {config.icon}
          </div>
          
          {/* 内容 */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-white">{node.tool}</span>
              <span className={`text-xs px-1.5 py-0.5 rounded ${config.bgColor} ${config.color}`}>
                {config.label}
              </span>
              {(node.retryCount ?? 0) > 0 && (
                <span className="text-xs text-amber-400 flex items-center gap-0.5">
                  <RotateCcw className="w-3 h-3" />
                  {node.retryCount}
                </span>
              )}
            </div>
            
            {/* 参数预览 */}
            {showParams && Object.keys(node.params).length > 0 && (
              <div className="mt-1.5">
                <button
                  onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}
                  className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300"
                >
                  <FileJson className="w-3 h-3" />
                  {expanded ? '收起参数' : formatParams(node.params)}
                </button>
                
                {expanded && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    className="mt-2 p-2 rounded bg-black/30 overflow-x-auto"
                  >
                    <pre className="text-xs text-slate-400 font-mono">
                      {JSON.stringify(node.params, null, 2)}
                    </pre>
                  </motion.div>
                )}
              </div>
            )}
            
            {/* 执行时间和结果 */}
            <div className="flex items-center gap-3 mt-2">
              {showTiming && node.executionTime !== undefined && (
                <span className="text-xs text-slate-500 flex items-center gap-1">
                  <Clock3 className="w-3 h-3" />
                  {formatTime(node.executionTime)}
                </span>
              )}
              
              {node.result && (
                <span className={`text-xs flex items-center gap-1 ${
                  node.result.success ? 'text-emerald-400' : 'text-red-400'
                }`}>
                  {node.result.success ? <CheckCircle2 className="w-3 h-3" /> : <XCircle className="w-3 h-3" />}
                  {node.result.message || (node.result.success ? '成功' : '失败')}
                </span>
              )}
              
              {node.status === 'failed' && onRetry && (
                <button
                  onClick={(e) => { e.stopPropagation(); onRetry(node.id); }}
                  className="text-xs text-amber-400 hover:text-amber-300 flex items-center gap-1"
                >
                  <RotateCcw className="w-3 h-3" />
                  重试
                </button>
              )}
            </div>
            
            {/* 世界模型预测 */}
            {node.worldModelPrediction && (
              <div className="mt-2 p-2 rounded bg-blue-500/10 border border-blue-500/20">
                <div className="flex items-center gap-1 text-xs text-blue-400 mb-1">
                  <Activity className="w-3 h-3" />
                  <span>世界模型预测</span>
                </div>
                <p className="text-xs text-slate-400 line-clamp-2">
                  {node.worldModelPrediction}
                </p>
              </div>
            )}
          </div>
        </div>
      </motion.div>
    </div>
  );
};

/**
 * 箭头连接组件
 */
export const ChainArrow: React.FC<{ 
  animated?: boolean;
  className?: string;
}> = ({ animated = false, className = '' }) => (
  <div className={`flex justify-center py-1 ${className}`}>
    <ArrowRight className={`w-4 h-4 text-slate-600 rotate-90 ${
      animated ? 'animate-bounce' : ''
    }`} />
  </div>
);

/**
 * 工具链视图组件
 */
export const ToolChainView: React.FC<ToolChainViewProps> = ({
  nodes,
  className = '',
  showParams = true,
  showTiming = true,
  onNodeClick,
  onRetry
}) => {
  if (!nodes || nodes.length === 0) {
    return (
      <div className={`p-4 rounded-lg bg-slate-900/50 border border-white/5 ${className}`}>
        <div className="flex items-center gap-2 text-slate-500">
          <Wrench className="w-4 h-4" />
          <span className="text-sm">暂无工具调用链</span>
        </div>
      </div>
    );
  }

  const executingCount = nodes.filter(n => n.status === 'executing').length;
  const completedCount = nodes.filter(n => n.status === 'completed').length;
  const failedCount = nodes.filter(n => n.status === 'failed').length;
  const totalTime = nodes.reduce((sum, n) => sum + (n.executionTime || 0), 0);

  return (
    <div className={`rounded-lg bg-slate-900/50 border border-white/5 overflow-hidden ${className}`}>
      {/* 头部 - 中书省+尚书省标识 */}
      <div className="px-4 py-3 border-b border-white/5 bg-gradient-to-r from-indigo-500/10 to-purple-500/10">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Wrench className="w-4 h-4 text-indigo-400" />
            <span className="text-sm font-medium text-white">工具调用链</span>
            <div className="flex gap-1">
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-400">
                中书省
              </span>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-400">
                尚书省
              </span>
            </div>
          </div>
          
          {/* 统计 */}
          <div className="flex items-center gap-3 text-xs">
            {executingCount > 0 && (
              <span className="text-amber-400 flex items-center gap-1">
                <Play className="w-3 h-3" />
                {executingCount} 执行中
              </span>
            )}
            <span className="text-emerald-400">{completedCount} 成功</span>
            {failedCount > 0 && <span className="text-red-400">{failedCount} 失败</span>}
            {totalTime > 0 && (
              <span className="text-slate-400 flex items-center gap-1">
                <Clock3 className="w-3 h-3" />
                {formatTime(totalTime)}
              </span>
            )}
          </div>
        </div>
      </div>
      
      {/* 节点列表 */}
      <div className="p-4 space-y-2">
        {nodes.map((node, index) => (
          <ChainNodeCard
            key={node.id}
            node={node}
            index={index}
            isLast={index === nodes.length - 1}
            showParams={showParams}
            showTiming={showTiming}
            onClick={onNodeClick}
            onRetry={onRetry}
          />
        ))}
      </div>
    </div>
  );
};

/**
 * 紧凑版工具链视图
 */
export const ToolChainViewCompact: React.FC<{
  nodes: ChainNode[];
  className?: string;
}> = ({ nodes, className = '' }) => {
  if (!nodes || nodes.length === 0) return null;
  
  const currentNode = nodes.find(n => n.status === 'executing') || nodes[nodes.length - 1];
  const completedCount = nodes.filter(n => n.status === 'completed').length;
  
  return (
    <div className={`flex items-center gap-3 px-3 py-2 rounded-lg bg-slate-900/50 border border-white/5 ${className}`}>
      <Wrench className="w-4 h-4 text-indigo-400" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm text-white truncate">{currentNode.tool}</span>
          <span className="text-xs text-slate-400">
            ({completedCount}/{nodes.length})
          </span>
        </div>
        <div className="flex gap-1 mt-1">
          {nodes.map((n, i) => (
            <div
              key={n.id}
              className={`h-1 flex-1 rounded-full ${
                n.status === 'completed' ? 'bg-emerald-500' :
                n.status === 'executing' ? 'bg-amber-500 animate-pulse' :
                n.status === 'failed' ? 'bg-red-500' :
                'bg-white/10'
              }`}
              title={`${i + 1}. ${n.tool}`}
            />
          ))}
        </div>
      </div>
    </div>
  );
};

/**
 * 使用工具链的Hook
 */
export function useToolChain() {
  const [nodes, setNodes] = React.useState<ChainNode[]>([]);
  
  const addNode = React.useCallback((node: Omit<ChainNode, 'id'>) => {
    const newNode: ChainNode = {
      ...node,
      id: `chain_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
    };
    setNodes(prev => [...prev, newNode]);
    return newNode.id;
  }, []);
  
  const updateNode = React.useCallback((nodeId: string, updates: Partial<ChainNode>) => {
    setNodes(prev => prev.map(node => 
      node.id === nodeId ? { ...node, ...updates } : node
    ));
  }, []);
  
  const updateNodeStatus = React.useCallback((nodeId: string, status: ChainNodeStatus, result?: ChainNode['result']) => {
    setNodes(prev => prev.map(node => {
      if (node.id !== nodeId) return node;
      const updates: Partial<ChainNode> = { status };
      if (result) updates.result = result;
      if (status === 'completed' || status === 'failed') {
        updates.endTime = Date.now();
        if (node.startTime) {
          updates.executionTime = Date.now() - node.startTime;
        }
      }
      if (status === 'executing') {
        updates.startTime = Date.now();
      }
      return { ...node, ...updates };
    }));
  }, []);
  
  const clearNodes = React.useCallback(() => {
    setNodes([]);
  }, []);
  
  const getCurrentNode = React.useCallback(() => {
    return nodes.find(n => n.status === 'executing');
  }, [nodes]);
  
  const getCompletedNodes = React.useCallback(() => {
    return nodes.filter(n => n.status === 'completed');
  }, [nodes]);
  
  return {
    nodes,
    setNodes,
    addNode,
    updateNode,
    updateNodeStatus,
    clearNodes,
    getCurrentNode,
    getCompletedNodes,
    isComplete: nodes.every(n => n.status === 'completed' || n.status === 'failed'),
    hasFailed: nodes.some(n => n.status === 'failed')
  };
}

export default ToolChainView;
