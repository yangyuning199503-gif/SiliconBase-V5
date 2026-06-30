/**
 * 监控指标API
 */
import { fetchAPI, handleError } from './index';

export interface SystemMetrics {
  cpu_percent: number;
  memory: {
    percent: number;
    used: number;  // 字节，需要转换为 GB
    total: number;  // 字节
    available?: number;
  };
  disk: {
    percent: number;
    used: number;  // 字节
    total: number;  // 字节
  };
  timestamp: number;
}

export interface TaskMetrics {
  queue_size: number;
  completed_today: number;
  failed_today: number;
  current_task: {
    id: string;
    type: string;
    status: string;
  } | null;
  average_wait_time: number;
}

export interface MemoryMetrics {
  short_term_count: number;
  long_term_count: number;
  evolution_count: number;
  vector_entries: number;
  last_cleanup: number | null;
}

export interface Reflection {
  id: string;
  created_at: string;
  scene: string;
  content: string;
  rating: number;
}

export const metricsAPI = {
  /**
   * 获取系统资源指标
   */
  async getSystemMetrics(): Promise<SystemMetrics> {
    try {
      const response = await fetchAPI<{ success: boolean; data: SystemMetrics }>('/api/metrics/system');
      return response.data;
    } catch (error) {
      return handleError(error, '获取系统指标失败');
    }
  },

  /**
   * 获取任务队列指标
   */
  async getTaskMetrics(): Promise<TaskMetrics> {
    try {
      const response = await fetchAPI<{ success: boolean; data: TaskMetrics }>('/api/metrics/tasks');
      return response.data;
    } catch (error) {
      return handleError(error, '获取任务指标失败');
    }
  },

  /**
   * 获取记忆库统计
   */
  async getMemoryMetrics(): Promise<MemoryMetrics> {
    try {
      const response = await fetchAPI<{ success: boolean; data: MemoryMetrics }>('/api/metrics/memory');
      return response.data;
    } catch (error) {
      return handleError(error, '获取记忆指标失败');
    }
  },

  /**
   * 获取反思记录
   */
  async getReflections(): Promise<{ reflections: Reflection[] }> {
    try {
      const response = await fetchAPI<{ success: boolean; data: { reflections: Reflection[] } }>('/api/metrics/reflections');
      return response.data || { reflections: [] };
    } catch (error) {
      return handleError(error, '获取反思记录失败');
    }
  },
};
