/**
 * 工作流管理 API
 * 提供工作流的创建、执行、状态查询等功能
 * 
 * 【静默失败阻断规则】绝对禁止违反！
 * - 所有错误必须抛出异常，禁止返回null或默认值
 * - HTTP错误必须抛出APIError
 * - 所有错误日志自动标记 [SILENT_FAILURE_BLOCKED]
 */

import { fetchAPI } from './core';

// 简单的日志工具
const logger = {
  error: (...args: any[]) => console.error('[SILENT_FAILURE_BLOCKED]', '[WorkflowAPI]', ...args),
  info: (...args: any[]) => console.info('[WorkflowAPI]', ...args),
  debug: (...args: any[]) => console.debug('[WorkflowAPI]', ...args),
};

/**
 * 步骤类别
 */
export type StepCategory = 'check' | 'launch' | 'action' | 'transform' | 'verify' | 'save';

/**
 * 执行模式
 */
export type ExecutionMode = 'sequential' | 'parallel' | 'conditional';

/**
 * 执行策略
 */
export type ExecutionStrategy = 'sequential' | 'parallel' | 'adaptive';

/**
 * 执行状态
 */
export type ExecutionStatus = 'pending' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled';

/**
 * 步骤状态
 */
export type StepStatus = 'pending' | 'ready' | 'running' | 'completed' | 'failed' | 'skipped' | 'paused' | 'verifying';

/**
 * 工作流步骤
 */
export interface WorkflowStep {
  step_id?: string;
  name: string;
  description?: string;
  tool_id: string;
  tool_params?: Record<string, any>;
  inputs?: Record<string, string>;
  outputs?: Record<string, string>;
  output_mapping?: Record<string, string>;
  is_critical?: boolean;
  step_category?: StepCategory;
  execution_mode?: ExecutionMode;
  condition?: string;
  on_success?: string;
  on_failure?: string;
  requires_confirmation?: boolean;
  confirmation_message?: string;
  allow_modification?: boolean;
  timeout?: number;
  max_retries?: number;
}

/**
 * 工作流定义
 */
export interface Workflow {
  workflow_id: string;
  name: string;
  description: string;
  step_count: number;
  created_at: number;
  created_by: string;
  version: string;
}

/**
 * 工作流详情
 */
export interface WorkflowDetail extends Workflow {
  steps: WorkflowStep[];
  variables: Record<string, any>;
  execution_strategy: ExecutionStrategy;
  max_retries: number;
  timeout_per_step: number;
  perception_config: Record<string, any>;
}

/**
 * 创建工作流请求
 */
export interface CreateWorkflowRequest {
  workflow_id?: string;
  name: string;
  description?: string;
  steps: WorkflowStep[];
  variables?: Record<string, any>;
  execution_strategy?: ExecutionStrategy;
  max_retries?: number;
  timeout_per_step?: number;
  perception_config?: Record<string, any>;
}

/**
 * 创建工作流响应
 */
export interface CreateWorkflowResponse {
  workflow_id: string;
  name: string;
  description: string;
  step_count: number;
  created_at: number;
  created_by: string;
  version: string;
}

/**
 * 执行工作流请求
 */
export interface ExecuteWorkflowRequest {
  initial_vars?: Record<string, any>;
  mode?: 'default' | 'slot' | 'agent_loop';
}

/**
 * 执行工作流响应
 */
export interface ExecuteWorkflowResponse {
  success: boolean;
  execution_id: string;
  workflow_id: string;
  status: ExecutionStatus;
  message: string;
  slot_id?: number;
}

/**
 * 当前步骤信息
 */
export interface CurrentStepInfo {
  step_id: string;
  name: string;
  status: StepStatus;
}

/**
 * 执行状态响应
 */
export interface ExecutionStatusResponse {
  execution_id: string;
  workflow_id: string;
  status: ExecutionStatus;
  current_step: number;
  total_steps: number;
  progress: number;
  variables: Record<string, any>;
  current_step_info?: CurrentStepInfo;
  can_modify: boolean;
  created_at: number;
  started_at?: number;
  completed_at?: number;
}

/**
 * 修改执行请求
 */
export interface ModifyExecutionRequest {
  skip_steps?: string[];
  modify_params?: Record<string, Record<string, any>>;
  add_steps?: Array<{
    index: number;
    step: WorkflowStep;
  }>;
  update_variables?: Record<string, any>;
}

/**
 * 修改执行响应
 */
export interface ModifyExecutionResponse {
  success: boolean;
  execution_id: string;
  message: string;
  modifications_applied: string[];
}

/**
 * 执行操作响应
 */
export interface ExecutionActionResponse {
  success: boolean;
  execution_id: string;
  status: ExecutionStatus;
  message: string;
}

/**
 * 工作流列表响应
 */
export interface WorkflowListResponse {
  success: boolean;
  workflows: Workflow[];
  total: number;
}

/**
 * 工作流API封装
 */
export const workflowApi = {
  // ═══════════════════════════════════════════════════════════
  // 工作流管理
  // ═══════════════════════════════════════════════════════════

  /**
   * 获取工作流列表
   * @returns 工作流列表
   */
  async listWorkflows(): Promise<WorkflowListResponse> {
    try {
      logger.info('获取工作流列表');
      
      const response = await fetchAPI<WorkflowListResponse>('/api/tasks/workflows');
      
      if (!response) {
        logger.error('listWorkflows返回空值');
        throw new Error('获取工作流列表失败：返回空值');
      }
      
      return response;
    } catch (error) {
      logger.error('获取工作流列表异常:', error);
      throw error;
    }
  },

  /**
   * 创建工作流
   * @param request - 创建工作流请求
   * @returns 创建的工作流
   */
  async createWorkflow(request: CreateWorkflowRequest): Promise<CreateWorkflowResponse> {
    try {
      logger.info('创建工作流:', request.name);
      
      const response = await fetchAPI<CreateWorkflowResponse>('/api/tasks/workflows', {
        method: 'POST',
        body: request,
      });
      
      if (!response) {
        logger.error('createWorkflow返回空值');
        throw new Error('创建工作流失败：返回空值');
      }
      
      if (!response.workflow_id) {
        logger.error('createWorkflow返回数据缺少workflow_id:', response);
        throw new Error('创建工作流失败：返回数据格式错误');
      }
      
      return response;
    } catch (error) {
      logger.error('创建工作流异常:', error);
      throw error;
    }
  },

  /**
   * 获取工作流详情
   * @param workflowId - 工作流ID
   * @returns 工作流详情
   */
  async getWorkflow(workflowId: string): Promise<WorkflowDetail> {
    try {
      logger.info(`获取工作流详情: ${workflowId}`);
      
      const response = await fetchAPI<WorkflowDetail>(`/api/tasks/workflows/${encodeURIComponent(workflowId)}`);
      
      if (!response) {
        logger.error('getWorkflow返回空值，workflowId:', workflowId);
        throw new Error('获取工作流详情失败：返回空值');
      }
      
      if (!response.workflow_id) {
        logger.error('getWorkflow返回数据缺少workflow_id:', response);
        throw new Error('获取工作流详情失败：返回数据格式错误');
      }
      
      return response;
    } catch (error) {
      logger.error('获取工作流详情异常:', error);
      throw error;
    }
  },

  /**
   * 删除工作流
   * @param workflowId - 工作流ID
   * @returns 删除结果
   */
  async deleteWorkflow(workflowId: string): Promise<{ success: boolean; message: string }> {
    try {
      logger.info(`删除工作流: ${workflowId}`);
      
      const response = await fetchAPI<{ success: boolean; message: string }>(
        `/api/tasks/workflows/${encodeURIComponent(workflowId)}`,
        {
          method: 'DELETE',
        }
      );
      
      if (!response) {
        logger.error('deleteWorkflow返回空值，workflowId:', workflowId);
        throw new Error('删除工作流失败：返回空值');
      }
      
      return response;
    } catch (error) {
      logger.error('删除工作流异常:', error);
      throw error;
    }
  },

  // ═══════════════════════════════════════════════════════════
  // 工作流执行
  // ═══════════════════════════════════════════════════════════

  /**
   * 执行工作流
   * @param workflowId - 工作流ID
   * @param request - 执行请求
   * @returns 执行结果
   */
  async executeWorkflow(
    workflowId: string,
    request: ExecuteWorkflowRequest = {}
  ): Promise<ExecuteWorkflowResponse> {
    try {
      logger.info(`执行工作流: ${workflowId}`, request);
      
      const response = await fetchAPI<ExecuteWorkflowResponse>(
        `/api/tasks/workflows/${encodeURIComponent(workflowId)}/execute`,
        {
          method: 'POST',
          body: request,
        }
      );
      
      if (!response) {
        logger.error('executeWorkflow返回空值，workflowId:', workflowId);
        throw new Error('执行工作流失败：返回空值');
      }
      
      if (typeof response.success !== 'boolean') {
        logger.error('executeWorkflow返回数据格式错误，缺少success字段:', response);
        throw new Error('执行工作流失败：返回数据格式错误');
      }
      
      return response;
    } catch (error) {
      logger.error('执行工作流异常:', error);
      throw error;
    }
  },

  /**
   * 获取执行状态
   * @param executionId - 执行实例ID
   * @returns 执行状态
   */
  async getExecutionStatus(executionId: string): Promise<ExecutionStatusResponse> {
    try {
      logger.debug(`获取执行状态: ${executionId}`);
      
      const response = await fetchAPI<ExecutionStatusResponse>(
        `/api/tasks/workflows/executions/${encodeURIComponent(executionId)}`
      );
      
      if (!response) {
        logger.error('getExecutionStatus返回空值，executionId:', executionId);
        throw new Error('获取执行状态失败：返回空值');
      }
      
      if (!response.execution_id) {
        logger.error('getExecutionStatus返回数据缺少execution_id:', response);
        throw new Error('获取执行状态失败：返回数据格式错误');
      }
      
      return response;
    } catch (error) {
      logger.error('获取执行状态异常:', error);
      throw error;
    }
  },

  /**
   * 轮询执行状态
   * @param executionId - 执行实例ID
   * @param interval - 轮询间隔（毫秒）
   * @param onUpdate - 状态更新回调
   * @param shouldStop - 停止轮询条件函数
   * @returns 最终状态
   */
  async pollExecutionStatus(
    executionId: string,
    interval: number = 2000,
    onUpdate?: (status: ExecutionStatusResponse) => void,
    shouldStop?: (status: ExecutionStatusResponse) => boolean
  ): Promise<ExecutionStatusResponse> {
    const stopStatuses: ExecutionStatus[] = ['completed', 'failed', 'cancelled'];
    
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const status = await this.getExecutionStatus(executionId);
      
      // 调用更新回调
      if (onUpdate) {
        onUpdate(status);
      }
      
      // 检查是否停止轮询
      if (shouldStop && shouldStop(status)) {
        return status;
      }
      
      // 默认停止条件
      if (stopStatuses.includes(status.status)) {
        return status;
      }
      
      // 等待后再次查询
      await new Promise(resolve => setTimeout(resolve, interval));
    }
  },

  // ═══════════════════════════════════════════════════════════
  // 执行控制
  // ═══════════════════════════════════════════════════════════

  /**
   * 暂停执行
   * @param executionId - 执行实例ID
   * @param reason - 暂停原因
   * @returns 暂停结果
   */
  async pauseExecution(
    executionId: string,
    reason: string = '用户暂停'
  ): Promise<ExecutionActionResponse> {
    try {
      logger.info(`暂停执行: ${executionId}`, { reason });
      
      const response = await fetchAPI<ExecutionActionResponse>(
        `/api/tasks/workflows/executions/${encodeURIComponent(executionId)}/pause`,
        {
          method: 'POST',
          body: { reason },
        }
      );
      
      if (!response) {
        logger.error('pauseExecution返回空值，executionId:', executionId);
        throw new Error('暂停执行失败：返回空值');
      }
      
      if (typeof response.success !== 'boolean') {
        logger.error('pauseExecution返回数据格式错误，缺少success字段:', response);
        throw new Error('暂停执行失败：返回数据格式错误');
      }
      
      return response;
    } catch (error) {
      logger.error('暂停执行异常:', error);
      throw error;
    }
  },

  /**
   * 恢复执行
   * @param executionId - 执行实例ID
   * @returns 恢复结果
   */
  async resumeExecution(executionId: string): Promise<ExecutionActionResponse> {
    try {
      logger.info(`恢复执行: ${executionId}`);
      
      const response = await fetchAPI<ExecutionActionResponse>(
        `/api/tasks/workflows/executions/${encodeURIComponent(executionId)}/resume`,
        {
          method: 'POST',
        }
      );
      
      if (!response) {
        logger.error('resumeExecution返回空值，executionId:', executionId);
        throw new Error('恢复执行失败：返回空值');
      }
      
      if (typeof response.success !== 'boolean') {
        logger.error('resumeExecution返回数据格式错误，缺少success字段:', response);
        throw new Error('恢复执行失败：返回数据格式错误');
      }
      
      return response;
    } catch (error) {
      logger.error('恢复执行异常:', error);
      throw error;
    }
  },

  /**
   * 修改执行
   * @param executionId - 执行实例ID
   * @param request - 修改请求
   * @returns 修改结果
   */
  async modifyExecution(
    executionId: string,
    request: ModifyExecutionRequest
  ): Promise<ModifyExecutionResponse> {
    try {
      logger.info(`修改执行: ${executionId}`, request);
      
      const response = await fetchAPI<ModifyExecutionResponse>(
        `/api/tasks/workflows/executions/${encodeURIComponent(executionId)}/modify`,
        {
          method: 'POST',
          body: request,
        }
      );
      
      if (!response) {
        logger.error('modifyExecution返回空值，executionId:', executionId);
        throw new Error('修改执行失败：返回空值');
      }
      
      if (typeof response.success !== 'boolean') {
        logger.error('modifyExecution返回数据格式错误，缺少success字段:', response);
        throw new Error('修改执行失败：返回数据格式错误');
      }
      
      return response;
    } catch (error) {
      logger.error('修改执行异常:', error);
      throw error;
    }
  },

  /**
   * 取消执行
   * @param executionId - 执行实例ID
   * @returns 取消结果
   */
  async cancelExecution(executionId: string): Promise<ExecutionActionResponse> {
    try {
      logger.info(`取消执行: ${executionId}`);
      
      const response = await fetchAPI<ExecutionActionResponse>(
        `/api/tasks/workflows/executions/${encodeURIComponent(executionId)}/cancel`,
        {
          method: 'POST',
        }
      );
      
      if (!response) {
        logger.error('cancelExecution返回空值，executionId:', executionId);
        throw new Error('取消执行失败：返回空值');
      }
      
      if (typeof response.success !== 'boolean') {
        logger.error('cancelExecution返回数据格式错误，缺少success字段:', response);
        throw new Error('取消执行失败：返回数据格式错误');
      }
      
      return response;
    } catch (error) {
      logger.error('取消执行异常:', error);
      throw error;
    }
  },
};

export default workflowApi;
