/**
 * 子代理干预API封装
 * 
 * 提供子代理的暂停、恢复、调整、取消等操作
 * 
 * 【静默失败阻断规则】绝对禁止违反！
 * - 所有错误必须抛出异常，禁止返回null或默认值
 * - HTTP错误必须抛出APIError
 * - 所有错误日志自动标记 [SILENT_FAILURE_BLOCKED]
 */

import { fetchAPI, APIError } from './core';

// 简单的日志工具
const logger = {
  error: (...args: any[]) => console.error('[SILENT_FAILURE_BLOCKED]', ...args),
  info: (...args: any[]) => console.info('[SubAgentAPI]', ...args),
};

/**
 * 子代理干预类型
 */
export type InterventionType = 'PAUSE' | 'RESUME' | 'ADJUST' | 'CANCEL' | 'REPLAN'

/**
 * 干预请求参数
 */
export interface InterventionParams {
  type: InterventionType
  reason?: string
  new_task?: string      // 用于REPLAN类型
  adjustment?: string    // 用于ADJUST类型
}

/**
 * 干预响应
 */
export interface InterventionResponse {
  success: boolean
  message: string
  status?: string
}

/**
 * 子代理状态
 */
export type SubAgentStatus = 
  | 'pending' 
  | 'running' 
  | 'paused' 
  | 'completed' 
  | 'failed' 
  | 'cancelled'

/**
 * 子代理信息
 */
export interface SubAgentInfo {
  runtime_id: string
  name: string
  status: SubAgentStatus
  progress?: number
  current_step?: string
  error?: string
}

/**
 * 提交干预请求
 * 
 * @param runtimeId - 子代理运行时ID
 * @param params - 干预参数
 * @returns 干预响应
 */
export async function interveneSubAgent(
  runtimeId: string,
  params: InterventionParams
): Promise<InterventionResponse> {
  logger.info(`提交干预: ${runtimeId}`, { type: params.type, reason: params.reason });
  
  try {
    const response = await fetchAPI<{ message?: string; status?: string }>(
      `/api/subagents/${encodeURIComponent(runtimeId)}/intervene`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(params)
      }
    );
    
    logger.info(`干预成功: ${runtimeId}`, response);
    
    return {
      success: true,
      message: response.message || '干预已提交',
      status: response.status
    };
  } catch (error) {
    const message = error instanceof APIError ? error.message : '干预请求失败';
    logger.error('干预异常:', error);
    throw new APIError(message, error instanceof APIError ? error.status : 500);
  }
}

/**
 * 暂停子代理
 * 
 * @param runtimeId - 子代理运行时ID
 * @param reason - 暂停原因
 * @returns 干预响应
 */
export async function pauseSubAgent(
  runtimeId: string,
  reason: string = '用户暂停'
): Promise<InterventionResponse> {
  return interveneSubAgent(runtimeId, { type: 'PAUSE', reason });
}

/**
 * 恢复子代理
 * 
 * @param runtimeId - 子代理运行时ID
 * @returns 干预响应
 */
export async function resumeSubAgent(
  runtimeId: string
): Promise<InterventionResponse> {
  return interveneSubAgent(runtimeId, { type: 'RESUME' });
}

/**
 * 调整子代理方向
 * 
 * @param runtimeId - 子代理运行时ID
 * @param adjustment - 调整建议
 * @returns 干预响应
 */
export async function adjustSubAgent(
  runtimeId: string,
  adjustment: string
): Promise<InterventionResponse> {
  return interveneSubAgent(runtimeId, { 
    type: 'ADJUST', 
    reason: adjustment,
    adjustment 
  });
}

/**
 * 重新规划子代理任务
 * 
 * @param runtimeId - 子代理运行时ID
 * @param newTask - 新任务描述
 * @returns 干预响应
 */
export async function replanSubAgent(
  runtimeId: string,
  newTask: string
): Promise<InterventionResponse> {
  return interveneSubAgent(runtimeId, {
    type: 'REPLAN',
    reason: '重新规划任务',
    new_task: newTask
  });
}

/**
 * 取消子代理
 * 
 * @param runtimeId - 子代理运行时ID
 * @returns 干预响应
 */
export async function cancelSubAgent(
  runtimeId: string
): Promise<InterventionResponse> {
  return interveneSubAgent(runtimeId, { type: 'CANCEL', reason: '用户取消' });
}

/**
 * 获取子代理状态
 * 
 * @param runtimeId - 子代理运行时ID
 * @returns 子代理信息
 */
export async function getSubAgentStatus(runtimeId: string): Promise<SubAgentInfo> {
  try {
    const response = await fetchAPI(
      `/api/subagents/${encodeURIComponent(runtimeId)}/status`
    );
    
    return response as SubAgentInfo;
  } catch (error) {
    logger.error('获取状态失败:', error);
    throw error;
  }
}

/**
 * 批量干预多个子代理
 * 
 * @param runtimeIds - 子代理运行时ID列表
 * @param params - 干预参数
 * @returns 每个子代理的干预结果
 */
export async function batchInterveneSubAgents(
  runtimeIds: string[],
  params: InterventionParams
): Promise<Map<string, InterventionResponse>> {
  const results = new Map<string, InterventionResponse>();
  
  // 并行发送所有干预请求
  const promises = runtimeIds.map(async (runtimeId) => {
    try {
      const result = await interveneSubAgent(runtimeId, params);
      results.set(runtimeId, result);
    } catch (error) {
      results.set(runtimeId, {
        success: false,
        message: error instanceof Error ? error.message : '干预失败'
      });
    }
  });
  
  await Promise.all(promises);
  
  return results;
}

// 导出API对象
export const subagentApi = {
  intervene: interveneSubAgent,
  pause: pauseSubAgent,
  resume: resumeSubAgent,
  adjust: adjustSubAgent,
  replan: replanSubAgent,
  cancel: cancelSubAgent,
  getStatus: getSubAgentStatus,
  batchIntervene: batchInterveneSubAgents
};

export default subagentApi;
