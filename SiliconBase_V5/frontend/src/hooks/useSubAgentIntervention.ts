/**
 * 子代理干预Hooks
 * 
 * 提供子代理干预的React Hooks
 */

import { useState, useCallback } from 'react';
import { subagentApi, SubAgentInfo, InterventionResponse, InterventionParams } from '../utils/api/subagent';

// 简单的日志工具
const logger = {
  error: (...args: any[]) => console.error('[useSubAgentIntervention]', ...args),
  info: (...args: any[]) => console.info('[useSubAgentIntervention]', ...args),
};

/**
 * 子代理干预Hook
 * 
 * @returns 子代理干预控制函数和状态
 */
export function useSubAgentIntervention() {
  const [state, setState] = useState<{
    isIntervening: boolean
    lastIntervention: InterventionResponse | null
    error: string | null
  }>({
    isIntervening: false,
    lastIntervention: null,
    error: null
  });
  
  /**
   * 暂停子代理
   */
  const pause = useCallback(async (runtimeId: string, reason?: string) => {
    setState(prev => ({ ...prev, isIntervening: true, error: null }));
    
    try {
      const result = await subagentApi.pause(runtimeId, reason);
      setState(prev => ({ ...prev, isIntervening: false, lastIntervention: result }));
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : '暂停失败';
      logger.error('暂停失败:', error);
      setState(prev => ({ ...prev, isIntervening: false, error: message }));
      return null;
    }
  }, []);
  
  /**
   * 恢复子代理
   */
  const resume = useCallback(async (runtimeId: string) => {
    setState(prev => ({ ...prev, isIntervening: true, error: null }));
    
    try {
      const result = await subagentApi.resume(runtimeId);
      setState(prev => ({ ...prev, isIntervening: false, lastIntervention: result }));
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : '恢复失败';
      logger.error('恢复失败:', error);
      setState(prev => ({ ...prev, isIntervening: false, error: message }));
      return null;
    }
  }, []);
  
  /**
   * 调整子代理
   */
  const adjust = useCallback(async (runtimeId: string, adjustment: string) => {
    setState(prev => ({ ...prev, isIntervening: true, error: null }));
    
    try {
      const result = await subagentApi.adjust(runtimeId, adjustment);
      setState(prev => ({ ...prev, isIntervening: false, lastIntervention: result }));
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : '调整失败';
      logger.error('调整失败:', error);
      setState(prev => ({ ...prev, isIntervening: false, error: message }));
      return null;
    }
  }, []);
  
  /**
   * 重新规划子代理
   */
  const replan = useCallback(async (runtimeId: string, newTask: string) => {
    setState(prev => ({ ...prev, isIntervening: true, error: null }));
    
    try {
      const result = await subagentApi.replan(runtimeId, newTask);
      setState(prev => ({ ...prev, isIntervening: false, lastIntervention: result }));
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : '重新规划失败';
      logger.error('重新规划失败:', error);
      setState(prev => ({ ...prev, isIntervening: false, error: message }));
      return null;
    }
  }, []);
  
  /**
   * 取消子代理
   */
  const cancel = useCallback(async (runtimeId: string) => {
    setState(prev => ({ ...prev, isIntervening: true, error: null }));
    
    try {
      const result = await subagentApi.cancel(runtimeId);
      setState(prev => ({ ...prev, isIntervening: false, lastIntervention: result }));
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : '取消失败';
      logger.error('取消失败:', error);
      setState(prev => ({ ...prev, isIntervening: false, error: message }));
      return null;
    }
  }, []);
  
  /**
   * 获取子代理状态
   */
  const getStatus = useCallback(async (runtimeId: string): Promise<SubAgentInfo | null> => {
    try {
      return await subagentApi.getStatus(runtimeId);
    } catch (error) {
      logger.error('获取状态失败:', error);
      return null;
    }
  }, []);
  
  /**
   * 批量干预子代理
   */
  const batchIntervene = useCallback(async (
    runtimeIds: string[],
    type: 'PAUSE' | 'RESUME' | 'ADJUST' | 'CANCEL',
    extra?: string
  ) => {
    setState(prev => ({ ...prev, isIntervening: true, error: null }));
    
    try {
      const params: InterventionParams = { type };
      
      if (extra) {
        if (type === 'ADJUST') {
          params.adjustment = extra;
        } else {
          params.reason = extra;
        }
      }
      
      const results = await subagentApi.batchIntervene(runtimeIds, params);
      setState(prev => ({ ...prev, isIntervening: false }));
      
      // 检查是否有失败
      let hasError = false;
      results.forEach((result, id) => {
        if (!result.success) {
          hasError = true;
          logger.error(`子代理 ${id} 干预失败:`, result.message);
        }
      });
      
      if (hasError) {
        setState(prev => ({ ...prev, error: '部分子代理干预失败' }));
      }
      
      return results;
    } catch (error) {
      const message = error instanceof Error ? error.message : '批量干预失败';
      logger.error('批量干预失败:', error);
      setState(prev => ({ ...prev, isIntervening: false, error: message }));
      return null;
    }
  }, []);
  
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
    adjust,
    replan,
    cancel,
    getStatus,
    batchIntervene,
    clearError
  };
}

export default useSubAgentIntervention;
