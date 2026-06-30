/**
 * 统计报告 API
 * 对应后端 /api/stats/* 端点
 */

import { fetchAPI, handleError } from "./index";

export interface FailureStats {
  total: number;
  by_category: Record<string, number>;
  by_tool: Record<string, number>;
  recent: Array<{
    id: string;
    timestamp: string;
    category: string;
    tool?: string;
    error: string;
  }>;
}

export interface DailyReport {
  date: string;
  summary: string;
  details: string;
}

export interface RecordFailureRequest {
  category: string;
  error: string;
  tool?: string;
  task_id?: string;
  session_id?: string;
  metadata?: Record<string, any>;
}

export const statsAPI = {
  /**
   * 获取失败统计数据
   */
  async getFailures(): Promise<FailureStats> {
    try {
      const response = await fetchAPI<{ success: boolean; data: FailureStats }>(
        "/api/stats/failures",
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取失败统计失败");
    }
  },

  /**
   * 生成每日失败分析报告
   */
  async getDailyReport(date?: string): Promise<DailyReport> {
    try {
      const query = date ? `?date=${encodeURIComponent(date)}` : "";
      const response = await fetchAPI<{ success: boolean; data: DailyReport }>(
        `/api/stats/daily-report${query}`,
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取每日报告失败");
    }
  },

  /**
   * 记录一次失败（供 AgentLoop 调用）
   */
  async recordFailure(request: RecordFailureRequest): Promise<{ success: boolean; id: string }> {
    try {
      return await fetchAPI<{ success: boolean; id: string }>("/api/stats/record-failure", {
        method: "POST",
        body: request,
      });
    } catch (error) {
      return handleError(error, "记录失败失败");
    }
  },

  /**
   * 健康检查
   */
  async healthCheck(): Promise<{ status: string }> {
    try {
      return await fetchAPI<{ status: string }>("/api/stats/health");
    } catch (error) {
      return handleError(error, "健康检查失败");
    }
  },
};

export default statsAPI;
