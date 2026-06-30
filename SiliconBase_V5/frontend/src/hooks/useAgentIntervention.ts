/**
 * 代理干预Hooks
 * 
 * 提供父代理干预的React Hooks
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import { agentApi, AgentTaskInfo, AgentInterventionResponse } from '../utils/api/agent';

// 简单的日志工具
const logger = {
  error: (...args: any[]) => console.error('[useAgentIntervention]', ...args),
  info: (...args: any[]) => console.info('[useAgentIntervention]', ...args),
};

/**
 * 父代理干预状态
 */
export interface AgentInterventionState {
  /** 是否正在处理干预请求 */
  isIntervening: boolean
  /** 最后干预结果 */
  lastIntervention: AgentInterventionResponse | null
  /** 错误信息 */
  error: string | null
}

/**
 * 父代理干预Hook
 * 
 * @param taskId - 任务ID
 * @param onStatusChange - 状态变更回调
 * @returns 干预控制函数和状态
 */
export function useAgentIntervention(
  taskId: string | null,
  onStatusChange?: (status: AgentTaskInfo) => void
) {
  const [state, setState] = useState<AgentInterventionState>({
    isIntervening: false,
    lastIntervention: null,
    error: null
  });
  
  const wsRef = useRef<WebSocket | null>(null);
  
  // 建立WebSocket连接监听状态
  useEffect(() => {
    if (!taskId || !onStatusChange) return;
    
    const ws = agentApi.watchStatus(taskId, onStatusChange);
    wsRef.current = ws;
    
    return () => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.close();
      }
    };
  }, [taskId, onStatusChange]);
  
  /**
   * 暂停代理
   */
  const pause = useCallback(async () => {
    if (!taskId) {
      setState(prev => ({ ...prev, error: '任务ID未设置' }));
      return null;
    }
    
    setState(prev => ({ ...prev, isIntervening: true, error: null }));
    
    try {
      const result = await agentApi.pause(taskId);
      setState(prev => ({ ...prev, isIntervening: false, lastIntervention: result }));
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : '暂停失败';
      logger.error('暂停失败:', error);
      setState(prev => ({ ...prev, isIntervening: false, error: message }));
      return null;
    }
  }, [taskId]);
  
  /**
   * 恢复代理
   */
  const resume = useCallback(async () => {
    if (!taskId) {
      setState(prev => ({ ...prev, error: '任务ID未设置' }));
      return null;
    }
    
    setState(prev => ({ ...prev, isIntervening: true, error: null }));
    
    try {
      const result = await agentApi.resume(taskId);
      setState(prev => ({ ...prev, isIntervening: false, lastIntervention: result }));
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : '恢复失败';
      logger.error('恢复失败:', error);
      setState(prev => ({ ...prev, isIntervening: false, error: message }));
      return null;
    }
  }, [taskId]);
  
  /**
   * 取消代理
   */
  const cancel = useCallback(async () => {
    if (!taskId) {
      setState(prev => ({ ...prev, error: '任务ID未设置' }));
      return null;
    }
    
    setState(prev => ({ ...prev, isIntervening: true, error: null }));
    
    try {
      const result = await agentApi.cancel(taskId);
      setState(prev => ({ ...prev, isIntervening: false, lastIntervention: result }));
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : '取消失败';
      logger.error('取消失败:', error);
      setState(prev => ({ ...prev, isIntervening: false, error: message }));
      return null;
    }
  }, [taskId]);
  
  /**
   * 切换模式
   */
  const switchMode = useCallback(async (mode: 'fast' | 'slow' | 'interactive') => {
    if (!taskId) {
      setState(prev => ({ ...prev, error: '任务ID未设置' }));
      return null;
    }
    
    setState(prev => ({ ...prev, isIntervening: true, error: null }));
    
    try {
      const result = await agentApi.switchMode(taskId, mode);
      setState(prev => ({ ...prev, isIntervening: false, lastIntervention: result }));
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : '模式切换失败';
      logger.error('模式切换失败:', error);
      setState(prev => ({ ...prev, isIntervening: false, error: message }));
      return null;
    }
  }, [taskId]);
  
  /**
   * 追加指令
   */
  const appendInstruction = useCallback(async (instruction: string) => {
    if (!taskId) {
      setState(prev => ({ ...prev, error: '任务ID未设置' }));
      return null;
    }
    
    setState(prev => ({ ...prev, isIntervening: true, error: null }));
    
    try {
      const result = await agentApi.appendInstruction(taskId, instruction);
      setState(prev => ({ ...prev, isIntervening: false, lastIntervention: result }));
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : '追加指令失败';
      logger.error('追加指令失败:', error);
      setState(prev => ({ ...prev, isIntervening: false, error: message }));
      return null;
    }
  }, [taskId]);
  
  /**
   * 清除错误
   */
  const clearError = useCallback(() => {
    setState(prev => ({ ...prev, error: null }));
  }, []);
  
  return {
    ...state,
    pause,
    resume,
    cancel,
    switchMode,
    appendInstruction,
    clearError,
    isAvailable: taskId !== null
  };
}

export default useAgentIntervention;
