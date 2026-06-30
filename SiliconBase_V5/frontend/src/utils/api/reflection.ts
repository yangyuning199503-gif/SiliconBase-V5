/**
 * 反思系统API
 * 
 * 【API端点】
 * - GET /api/reflection/status - 获取反思系统状态
 * - PUT /api/reflection/status - 更新反思系统状态
 * - GET /api/reflections - 获取反思记录列表
 * - POST /api/reflections/{id}/feedback - 提交反思反馈
 * - POST /api/reflections/{id}/archive - 归档反思
 * - GET /api/reflections/stats - 获取反思统计
 */

import type { Reflection as ReflectionRecord, ReflectionStats, ReflectionType } from '../../components/ReflectionPanel';
import { fetchAPI, handleError } from './index';

// Export the type with an alias to avoid conflicts
export type { ReflectionRecord, ReflectionType, ReflectionStats };

// 反思系统状态响应
export interface ReflectionStatusResponse {
  enabled: boolean;
  config?: {
    auto_reflect: boolean;
    min_confidence: number;
    max_reflections_per_day: number;
  };
}

// 反思列表查询参数
export interface GetReflectionsParams {
  task_id?: string;
  session_id?: string;
  type?: ReflectionType;
  status?: 'active' | 'archived';
  limit?: number;
  offset?: number;
}

// 反思反馈请求参数
export interface ReflectionFeedbackParams {
  rating: number;
  feedback?: string;
}

// 反思反馈响应
export interface ReflectionFeedbackResponse {
  success: boolean;
  message: string;
  updated_reflection: ReflectionRecord;
}

// 反思系统配置
export interface ReflectionConfig {
  enabled: boolean;
  auto_reflect: boolean;
  min_confidence: number;
  max_reflections_per_day: number;
  reflection_types: ReflectionType[];
}

// 反思系统API
export const reflectionAPI = {
  /**
   * 获取反思系统状态
   */
  async getStatus(): Promise<ReflectionStatusResponse> {
    try {
      const response = await fetchAPI<{ success: boolean; data: ReflectionStatusResponse }>(
        '/api/reflection/status'
      );
      return response.data;
    } catch (error) {
      return handleError(error, '获取反思状态失败');
    }
  },

  /**
   * 更新反思系统状态
   */
  async updateStatus(enabled: boolean): Promise<{ success: boolean; message: string }> {
    try {
      const response = await fetchAPI<{ success: boolean; message: string }>(
        '/api/reflection/status',
        {
          method: 'PUT',
          body: JSON.stringify({ enabled })
        }
      );
      return response;
    } catch (error) {
      return handleError(error, '更新反思状态失败');
    }
  },

  /**
   * 获取反思系统配置
   */
  async getConfig(): Promise<ReflectionConfig> {
    try {
      const response = await fetchAPI<{ success: boolean; data: ReflectionConfig }>(
        '/api/reflection/config'
      );
      return response.data;
    } catch (error) {
      return handleError(error, '获取反思配置失败');
    }
  },

  /**
   * 更新反思系统配置
   */
  async updateConfig(config: Partial<ReflectionConfig>): Promise<ReflectionConfig> {
    try {
      const response = await fetchAPI<{ success: boolean; data: ReflectionConfig }>(
        '/api/reflection/config',
        {
          method: 'PUT',
          body: JSON.stringify(config)
        }
      );
      return response.data;
    } catch (error) {
      return handleError(error, '更新反思配置失败');
    }
  },

  /**
   * 获取反思记录列表
   */
  async getReflections(params?: GetReflectionsParams): Promise<{ reflections: ReflectionRecord[]; total: number }> {
    try {
      const queryParams = new URLSearchParams();
      if (params?.task_id) queryParams.set('task_id', params.task_id);
      if (params?.session_id) queryParams.set('session_id', params.session_id);
      if (params?.type) queryParams.set('type', params.type);
      if (params?.status) queryParams.set('status', params.status);
      if (params?.limit) queryParams.set('limit', params.limit.toString());
      if (params?.offset !== undefined) queryParams.set('offset', params.offset.toString());

      const response = await fetchAPI<{ success: boolean; data: { reflections: ReflectionRecord[]; total: number } }>(
        `/api/reflections?${queryParams.toString()}`
      );
      return response.data;
    } catch (error) {
      return handleError(error, '获取反思记录失败');
    }
  },

  /**
   * 获取单个反思详情
   */
  async getReflection(reflectionId: string): Promise<ReflectionRecord> {
    try {
      const response = await fetchAPI<{ success: boolean; data: ReflectionRecord }>(
        `/api/reflections/${encodeURIComponent(reflectionId)}`
      );
      return response.data;
    } catch (error) {
      return handleError(error, '获取反思详情失败');
    }
  },

  /**
   * 提交反思反馈
   */
  async submitFeedback(
    reflectionId: string, 
    params: ReflectionFeedbackParams
  ): Promise<ReflectionFeedbackResponse> {
    try {
      const response = await fetchAPI<ReflectionFeedbackResponse>(
        `/api/reflections/${encodeURIComponent(reflectionId)}/feedback`,
        {
          method: 'POST',
          body: JSON.stringify(params)
        }
      );
      return response;
    } catch (error) {
      return handleError(error, '提交反馈失败');
    }
  },

  /**
   * 归档反思
   */
  async archiveReflection(reflectionId: string): Promise<{ success: boolean; message: string }> {
    try {
      const response = await fetchAPI<{ success: boolean; message: string }>(
        `/api/reflections/${encodeURIComponent(reflectionId)}/archive`,
        {
          method: 'POST'
        }
      );
      return response;
    } catch (error) {
      return handleError(error, '归档反思失败');
    }
  },

  /**
   * 批量归档反思
   */
  async archiveReflectionsBatch(reflectionIds: string[]): Promise<{ success: boolean; archived: number }> {
    try {
      const response = await fetchAPI<{ success: boolean; archived: number }>(
        '/api/reflections/batch-archive',
        {
          method: 'POST',
          body: JSON.stringify({ ids: reflectionIds })
        }
      );
      return response;
    } catch (error) {
      return handleError(error, '批量归档失败');
    }
  },

  /**
   * 取消归档反思
   */
  async unarchiveReflection(reflectionId: string): Promise<{ success: boolean; message: string }> {
    try {
      const response = await fetchAPI<{ success: boolean; message: string }>(
        `/api/reflections/${encodeURIComponent(reflectionId)}/unarchive`,
        {
          method: 'POST'
        }
      );
      return response;
    } catch (error) {
      return handleError(error, '取消归档失败');
    }
  },

  /**
   * 获取反思统计
   */
  async getStats(): Promise<ReflectionStats> {
    try {
      const response = await fetchAPI<{ success: boolean; data: ReflectionStats }>(
        '/api/reflections/stats'
      );
      return response.data;
    } catch (error) {
      return handleError(error, '获取反思统计失败');
    }
  },

  /**
   * 获取任务相关的反思
   */
  async getTaskReflections(taskId: string): Promise<ReflectionRecord[]> {
    const result = await this.getReflections({ task_id: taskId });
    return result.reflections;
  },

  /**
   * 获取会话相关的反思
   */
  async getSessionReflections(sessionId: string): Promise<ReflectionRecord[]> {
    const result = await this.getReflections({ session_id: sessionId });
    return result.reflections;
  },

  /**
   * 触发手动反思
   */
  async triggerManualReflection(taskId?: string): Promise<{ success: boolean; reflection_id: string }> {
    try {
      const response = await fetchAPI<{ success: boolean; reflection_id: string }>(
        '/api/reflections/trigger',
        {
          method: 'POST',
          body: JSON.stringify({ task_id: taskId })
        }
      );
      return response;
    } catch (error) {
      return handleError(error, '触发反思失败');
    }
  },

  /**
   * 删除反思
   */
  async deleteReflection(reflectionId: string): Promise<{ success: boolean; message: string }> {
    try {
      const response = await fetchAPI<{ success: boolean; message: string }>(
        `/api/reflections/${encodeURIComponent(reflectionId)}`,
        {
          method: 'DELETE'
        }
      );
      return response;
    } catch (error) {
      return handleError(error, '删除反思失败');
    }
  }
};

export default reflectionAPI;
