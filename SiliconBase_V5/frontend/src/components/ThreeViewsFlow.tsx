/**
 * 三省六部式思维流透视镜 - 统一整合组件
 * 
 * 功能：
 * - 任务拆解可视化 (太子)
 * - 工具调用链展示 (中书省+尚书省)
 * - 用户确认节点 (门下省-封驳)
 * - 实时执行日志 (六部档案)
 * 
 * 参考唐朝三省六部制度，实现流程的完整透明化
 */
import React, { useState, useCallback, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Crown,
  Building2,
  Shield,
  ScrollText,
  X,
  Maximize2,
  Minimize2,
  Activity,
  Eye
} from 'lucide-react';

import { 
  TaskBreakdown, 
  TaskBreakdownCompact, 
  useTaskBreakdown
} from './TaskBreakdown';
import { 
  ToolChainView, 
  ToolChainViewCompact, 
  useToolChain
} from './ToolChainView';
import { 
  UserConfirmationQueue,
  useUserConfirmation,
  RiskLevel 
} from './UserConfirmation';
import { 
  ExecutionLog, 
  ExecutionLogCompact, 
  useExecutionLog
} from './ExecutionLog';

// WebSocket消息类型
interface WebSocketMessage {
  type: string;
  session_id?: string;
  data?: any;
  timestamp?: number;
}

// 三省六部思维流属性
interface ThreeViewsFlowProps {
  className?: string;
  defaultExpanded?: boolean;
  showHeader?: boolean;
  onClose?: () => void;
  sendWebSocketMessage?: (message: any) => void;
}

// 面板类型
type PanelType = 'task' | 'chain' | 'confirmation' | 'log';

/**
 * 三省六部思维流主组件
 */
export const ThreeViewsFlow: React.FC<ThreeViewsFlowProps> = ({
  className = '',
  defaultExpanded = true,
  showHeader = true,
  onClose,
  sendWebSocketMessage
}) => {
  // 状态管理
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const [activePanels, setActivePanels] = useState<Set<PanelType>>(
    new Set(['task', 'chain', 'log'])
  );
  const [isTransparent, setIsTransparent] = useState(false);
  
  // 使用各子组件的hooks
  const taskBreakdown = useTaskBreakdown();
  const toolChain = useToolChain();
  const userConfirmation = useUserConfirmation();
  const executionLog = useExecutionLog();
  
  // 处理WebSocket消息
  useEffect(() => {
    const handleWebSocketMessage = (event: CustomEvent<WebSocketMessage>) => {
      const { type, data } = event.detail;
      
      switch (type) {
        // 任务拆解
        case 'task_breakdown':
          if (data?.steps) {
            taskBreakdown.updateSteps(data.steps.map((s: any, idx: number) => ({
              id: s.id || `step_${idx}`,
              index: s.id || idx + 1,
              name: s.name,
              tool: s.tool,
              status: s.status || 'pending',
              description: s.description,
              estimatedTime: s.estimated_time
            })));
            executionLog.addInfo('任务已拆解', { steps_count: data.steps.length });
          }
          break;
          
        // 步骤状态更新
        case 'step_status_update':
          if (data?.step_id && data?.status) {
            taskBreakdown.updateStepStatus(data.step_id, data.status);
            executionLog.addAction(`步骤状态更新: ${data.status}`, { step_id: data.step_id });
          }
          break;
          
        // 工具链规划
        case 'tool_chain_planned':
          if (data?.chain) {
            const nodes = data.chain.map((c: any, idx: number) => ({
              id: c.id || `chain_${idx}`,
              tool: c.tool,
              params: c.params || {},
              status: c.status || 'planned',
              worldModelPrediction: c.world_model_prediction
            }));
            toolChain.setNodes(nodes);
            executionLog.addInfo('工具链已规划', { nodes_count: nodes.length });
          }
          break;
          
        // 工具节点更新
        case 'tool_node_update':
          if (data?.node_id) {
            toolChain.updateNode(data.node_id, {
              status: data.status,
              result: data.result,
              executionTime: data.execution_time,
              retryCount: data.retry_count
            });
          }
          break;
          
        // 用户确认请求
        case 'user_confirmation_required':
          if (data?.step && data?.tool) {
            userConfirmation.requestConfirmation({
              step: data.step,
              tool: data.tool,
              params: data.params || {},
              riskLevel: (data.risk_level || 'medium') as RiskLevel,
              description: data.description,
              timeout: data.timeout
            }).then(confirmed => {
              // 发送确认结果到后端
              sendWebSocketMessage?.({
                type: 'user_confirmation_response',
                confirmed,
                step: data.step,
                timestamp: Date.now()
              });
              executionLog.addAction(`用户${confirmed ? '确认' : '拒绝'}执行: ${data.step}`);
            });
            executionLog.addWarning(`需要用户确认: ${data.step}`, { 
              risk_level: data.risk_level,
              timeout: data.timeout 
            });
          }
          break;
          
        // AI思考
        case 'thinking':
          if (data?.content) {
            executionLog.addThinking(data.content, { 
              round: data.round,
              intent: data.intent 
            });
          }
          break;
          
        // 执行中
        case 'executing':
          if (data?.tool) {
            executionLog.addTool(`调用工具: ${data.tool}`, {
              params: data.params,
              round: data.round
            });
            toolChain.updateNodeStatus(data.tool, 'executing');
          }
          break;
          
        // 工具结果
        case 'tool_result':
          if (data?.tool) {
            const success = data.success;
            executionLog.addSuccess(
              `工具执行${success ? '成功' : '失败'}: ${data.tool}`,
              { message: data.message, data: data.data },
              data.execution_time
            );
            toolChain.updateNodeStatus(
              data.tool, 
              success ? 'completed' : 'failed',
              { success, message: data.message, data: data.data }
            );
          }
          break;
          
        // 任务完成
        case 'completed':
          executionLog.addSuccess(
            data?.success ? '任务完成' : '任务失败',
            data
          );
          break;
          
        // 任务开始
        case 'start':
          executionLog.addInfo('任务开始', data);
          break;
          
        // 错误
        case 'error':
          executionLog.addError(data?.message || '发生错误', data);
          break;
      }
    };
    
    // 监听WebSocket消息事件
    window.addEventListener('websocket-message', handleWebSocketMessage as EventListener);
    return () => {
      window.removeEventListener('websocket-message', handleWebSocketMessage as EventListener);
    };
  }, [taskBreakdown, toolChain, userConfirmation, executionLog, sendWebSocketMessage]);
  
  // 切换面板显示
  const togglePanel = useCallback((panel: PanelType) => {
    setActivePanels(prev => {
      const next = new Set(prev);
      if (next.has(panel)) {
        next.delete(panel);
      } else {
        next.add(panel);
      }
      return next;
    });
  }, []);
  
  // 面板配置
  const panels: { type: PanelType; label: string; icon: React.ReactNode; color: string }[] = [
    { type: 'task', label: '太子监国', icon: <Crown className="w-4 h-4" />, color: 'text-amber-400' },
    { type: 'chain', label: '中书尚书', icon: <Building2 className="w-4 h-4" />, color: 'text-indigo-400' },
    { type: 'confirmation', label: '门下封驳', icon: <Shield className="w-4 h-4" />, color: 'text-red-400' },
    { type: 'log', label: '六部档案', icon: <ScrollText className="w-4 h-4" />, color: 'text-slate-400' }
  ];

  return (
    <div 
      className={`rounded-lg overflow-hidden transition-all duration-300 ${
        isTransparent ? 'bg-transparent' : 'bg-slate-950/90 backdrop-blur-xl'
      } border border-white/10 shadow-2xl ${className}`}
    >
      {/* 头部 */}
      {showHeader && (
        <div className="px-4 py-3 border-b border-white/5 bg-gradient-to-r from-amber-500/5 via-indigo-500/5 to-purple-500/5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Eye className="w-5 h-5 text-cyan-400" />
              <span className="text-sm font-medium text-white">三省六部流程透视镜</span>
              
              {/* 面板切换按钮 */}
              <div className="flex items-center gap-1 ml-4">
                {panels.map(panel => (
                  <button
                    key={panel.type}
                    onClick={() => togglePanel(panel.type)}
                    className={`flex items-center gap-1 px-2 py-1 rounded text-xs transition-all ${
                      activePanels.has(panel.type)
                        ? `bg-white/10 ${panel.color}`
                        : 'text-slate-500 hover:text-slate-300'
                    }`}
                    title={panel.label}
                  >
                    {panel.icon}
                    <span className="hidden sm:inline">{panel.label}</span>
                  </button>
                ))}
              </div>
            </div>
            
            <div className="flex items-center gap-1">
              {/* 透明度切换 */}
              <button
                onClick={() => setIsTransparent(!isTransparent)}
                className={`p-1.5 rounded transition-colors ${isTransparent ? 'text-cyan-400' : 'text-slate-500 hover:text-slate-300'}`}
                title={isTransparent ? '不透明' : '透明'}
              >
                <Activity className="w-4 h-4" />
              </button>
              
              {/* 展开/收起 */}
              <button
                onClick={() => setIsExpanded(!isExpanded)}
                className="p-1.5 rounded text-slate-500 hover:text-slate-300 transition-colors"
                title={isExpanded ? '收起' : '展开'}
              >
                {isExpanded ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
              </button>
              
              {/* 关闭 */}
              {onClose && (
                <button
                  onClick={onClose}
                  className="p-1.5 rounded text-slate-500 hover:text-red-400 transition-colors"
                  title="关闭"
                >
                  <X className="w-4 h-4" />
                </button>
              )}
            </div>
          </div>
          
          {/* 状态概览 */}
          <div className="flex items-center gap-4 mt-2 text-xs">
            <span className="text-slate-500">
              任务: <span className="text-amber-400">{taskBreakdown.steps.length}</span> 步骤
            </span>
            <span className="text-slate-500">
              工具: <span className="text-indigo-400">{toolChain.nodes.length}</span> 节点
            </span>
            <span className="text-slate-500">
              日志: <span className="text-slate-300">{executionLog.count}</span> 条
            </span>
            {userConfirmation.count > 0 && (
              <span className="text-amber-400 animate-pulse">
                {userConfirmation.count} 个待确认
              </span>
            )}
          </div>
        </div>
      )}
      
      {/* 内容区 */}
      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="p-4 space-y-4 max-h-[70vh] overflow-y-auto scrollbar-thin">
              {/* 待确认队列 - 优先显示 */}
              {activePanels.has('confirmation') && userConfirmation.count > 0 && (
                <UserConfirmationQueue 
                  confirmations={userConfirmation.confirmations}
                  className="sticky top-0 z-10"
                />
              )}
              
              {/* 任务拆解 */}
              {activePanels.has('task') && taskBreakdown.steps.length > 0 && (
                <TaskBreakdown 
                  steps={taskBreakdown.steps}
                  showProgress={true}
                  onStepClick={(step) => executionLog.addInfo(`查看步骤: ${step.name}`)}
                />
              )}
              
              {/* 工具调用链 */}
              {activePanels.has('chain') && toolChain.nodes.length > 0 && (
                <ToolChainView 
                  nodes={toolChain.nodes}
                  showParams={true}
                  showTiming={true}
                  onNodeClick={(node) => executionLog.addInfo(`查看工具节点: ${node.tool}`)}
                  onRetry={(nodeId) => {
                    executionLog.addAction(`重试工具节点: ${nodeId}`);
                    sendWebSocketMessage?.({ type: 'retry_tool', node_id: nodeId });
                  }}
                />
              )}
              
              {/* 执行日志 */}
              {activePanels.has('log') && (
                <ExecutionLog 
                  entries={executionLog.entries}
                  maxHeight="200px"
                  showControls={true}
                  onClear={executionLog.clear}
                  onExport={executionLog.exportLog}
                />
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      
      {/* 紧凑状态条 */}
      {!isExpanded && (
        <div className="px-4 py-2 flex items-center gap-4">
          <TaskBreakdownCompact steps={taskBreakdown.steps} className="flex-1" />
          <ToolChainViewCompact nodes={toolChain.nodes} />
          <ExecutionLogCompact entries={executionLog.entries} />
        </div>
      )}
    </div>
  );
};

/**
 * 浮动面板版本
 */
export const ThreeViewsFlowFloating: React.FC<{
  className?: string;
}> = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [position, setPosition] = useState({ x: 20, y: 100 });
  const [isDragging, setIsDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0 });
  const panelStart = useRef({ x: 0, y: 0 });
  
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('.no-drag')) return;
    setIsDragging(true);
    dragStart.current = { x: e.clientX, y: e.clientY };
    panelStart.current = { ...position };
  }, [position]);
  
  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (!isDragging) return;
    const dx = e.clientX - dragStart.current.x;
    const dy = e.clientY - dragStart.current.y;
    setPosition({
      x: Math.max(0, panelStart.current.x + dx),
      y: Math.max(0, panelStart.current.y + dy)
    });
  }, [isDragging]);
  
  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
  }, []);
  
  useEffect(() => {
    if (isDragging) {
      window.addEventListener('mousemove', handleMouseMove);
      window.addEventListener('mouseup', handleMouseUp);
    }
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, handleMouseMove, handleMouseUp]);
  
  if (!isOpen) {
    return (
      <motion.button
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{ opacity: 1, scale: 1 }}
        onClick={() => setIsOpen(true)}
        className="fixed bottom-20 right-4 z-50
                   flex items-center gap-2 px-3 py-2
                   bg-slate-900/80 backdrop-blur-md
                   border border-white/10 rounded-lg
                   text-xs text-slate-300
                   hover:border-cyan-500/30 hover:text-white
                   transition-all shadow-xl group"
        style={{ left: position.x, top: position.y }}
      >
        <Eye className="w-4 h-4 text-cyan-400" />
        <span>三省六部</span>
      </motion.button>
    );
  }
  
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="fixed z-50 w-96"
      style={{ left: position.x, top: position.y }}
      onMouseDown={handleMouseDown}
    >
      <ThreeViewsFlow
        showHeader={true}
        onClose={() => setIsOpen(false)}
        className={`${isDragging ? 'cursor-grabbing' : 'cursor-grab'}`}
      />
    </motion.div>
  );
};

/**
 * 发送WebSocket消息的辅助函数
 */
export const sendWebSocketMessage = (message: any) => {
  const event = new CustomEvent('websocket-send', { detail: message });
  window.dispatchEvent(event);
};

/**
 * 使用三省六部思维流的Hook
 */
export function useThreeViewsFlow() {
  const taskBreakdown = useTaskBreakdown();
  const toolChain = useToolChain();
  const userConfirmation = useUserConfirmation();
  const executionLog = useExecutionLog();
  
  const reset = useCallback(() => {
    taskBreakdown.clearSteps();
    toolChain.clearNodes();
    userConfirmation.clearAll();
    executionLog.clear();
  }, [taskBreakdown, toolChain, userConfirmation, executionLog]);
  
  return {
    taskBreakdown,
    toolChain,
    userConfirmation,
    executionLog,
    reset,
    // 便捷方法
    logStart: (instruction: string) => {
      executionLog.addInfo('任务开始', { instruction });
    },
    logComplete: (success: boolean, answer?: string) => {
      executionLog.addSuccess(success ? '任务完成' : '任务失败', { answer });
    },
    logError: (error: string) => {
      executionLog.addError(error);
    }
  };
}

export default ThreeViewsFlow;
