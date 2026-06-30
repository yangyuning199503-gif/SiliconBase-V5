/**
 * 统一干预控制 API
 * 整合循环中断、任务暂停、交易暂停等功能
 * 
 * 已迁移到 fetchAPI（core.ts），统一错误处理。
 */

import { fetchAPI } from './core';

const logger = {
  error: (...args: any[]) => console.error('[InterventionAPI]', ...args),
  info: (...args: any[]) => console.info('[InterventionAPI]', ...args),
};

export interface InterventionResult {
  success: boolean;
  message: string;
}

/**
 * 中断AgentLoop循环
 */
export async function interruptLoop(
  sessionId: string,
  reason: string = '用户请求中断循环',
  graceful: boolean = true
): Promise<InterventionResult> {
  try {
    const data = await fetchAPI<{ message?: string }>(`/api/sessions/${sessionId}/interrupt`, {
      method: 'POST',
      body: { reason, graceful },
    });
    logger.info('循环中断成功:', data);
    return { success: true, message: data.message || '已请求中断循环' };
  } catch (error) {
    const msg = error instanceof Error ? error.message : '网络错误';
    logger.error('中断循环请求失败:', error);
    return { success: false, message: `中断请求失败: ${msg}` };
  }
}

/**
 * 暂停任务
 */
export async function pauseTask(taskId: string, reason: string = '用户暂停'): Promise<InterventionResult> {
  try {
    const data = await fetchAPI<{ message?: string }>(`/api/tasks/${taskId}/pause`, {
      method: 'POST',
      body: { reason },
    });
    logger.info('任务暂停成功:', data);
    return { success: true, message: data.message || '任务已暂停' };
  } catch (error) {
    const msg = error instanceof Error ? error.message : '网络错误';
    logger.error('暂停任务请求失败:', error);
    return { success: false, message: `暂停请求失败: ${msg}` };
  }
}

/**
 * 恢复任务
 */
export async function resumeTask(
  taskId: string,
  aiConfirmation?: string
): Promise<InterventionResult> {
  try {
    const data = await fetchAPI<{ message?: string }>(`/api/tasks/${taskId}/resume`, {
      method: 'POST',
      body: {
        ai_confirmation: aiConfirmation,
        confirmed_understanding: !!aiConfirmation,
      },
    });
    logger.info('任务恢复成功:', data);
    return { success: true, message: data.message || '任务已恢复' };
  } catch (error) {
    const msg = error instanceof Error ? error.message : '网络错误';
    logger.error('恢复任务请求失败:', error);
    return { success: false, message: `恢复请求失败: ${msg}` };
  }
}

/**
 * 取消任务
 */
export async function cancelTask(taskId: string, reason: string = '用户取消'): Promise<InterventionResult> {
  try {
    await fetchAPI(`/api/tasks/${taskId}/cancel`, {
      method: 'POST',
      body: { reason },
    });
    logger.info('任务取消成功:', taskId);
    return { success: true, message: '任务已取消' };
  } catch (error) {
    const msg = error instanceof Error ? error.message : '网络错误';
    logger.error('取消任务请求失败:', error);
    return { success: false, message: `取消请求失败: ${msg}` };
  }
}

/**
 * 暂停AI交易
 */
export async function pauseAITrading(): Promise<InterventionResult> {
  try {
    const data = await fetchAPI<{ status_message?: string }>('/api/trading/mode/ai/pause', {
      method: 'POST',
    });
    logger.info('AI交易暂停成功:', data);
    return { success: true, message: data.status_message || 'AI交易已暂停' };
  } catch (error) {
    const msg = error instanceof Error ? error.message : '网络错误';
    logger.error('暂停AI交易请求失败:', error);
    return { success: false, message: `暂停请求失败: ${msg}` };
  }
}

/**
 * 恢复AI交易
 */
export async function resumeAITrading(): Promise<InterventionResult> {
  try {
    const data = await fetchAPI<{ status_message?: string }>('/api/trading/mode/ai/resume', {
      method: 'POST',
    });
    logger.info('AI交易恢复成功:', data);
    return { success: true, message: data.status_message || 'AI交易已恢复' };
  } catch (error) {
    const msg = error instanceof Error ? error.message : '网络错误';
    logger.error('恢复AI交易请求失败:', error);
    return { success: false, message: `恢复请求失败: ${msg}` };
  }
}

/**
 * 停止AI交易
 */
export async function stopAITrading(): Promise<InterventionResult> {
  try {
    const data = await fetchAPI<{ status_message?: string }>('/api/trading/mode/ai/stop', {
      method: 'POST',
    });
    logger.info('AI交易停止成功:', data);
    return { success: true, message: data.status_message || 'AI交易已停止' };
  } catch (error) {
    const msg = error instanceof Error ? error.message : '网络错误';
    logger.error('停止AI交易请求失败:', error);
    return { success: false, message: `停止请求失败: ${msg}` };
  }
}

/**
 * 统一的干预入口
 */
export const interventionApi = {
  interruptLoop,
  pauseTask,
  resumeTask,
  cancelTask,
  pauseAITrading,
  resumeAITrading,
  stopAITrading,
};

export default interventionApi;
