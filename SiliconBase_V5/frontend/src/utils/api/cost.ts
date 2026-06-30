/**
 * 成本统计 API
 * 对应后端 /api/cost/* 端点
 */

import { fetchAPI, handleError } from "./index";

export interface BudgetStatus {
  daily_budget: number;
  monthly_budget: number;
  daily_used: number;
  monthly_used: number;
  daily_remaining: number;
  monthly_remaining: number;
  daily_percent: number;
  monthly_percent: number;
  alert_level: string;
}

export interface UsageStats {
  overall: Record<string, any>;
  by_model: Array<Record<string, any>>;
  by_day: Array<Record<string, any>>;
  period: Record<string, string>;
}

export interface CostRecord {
  id: number;
  model: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  input_cost: number;
  output_cost: number;
  total_cost: number;
  request_type: string;
  created_at: string;
  metadata?: Record<string, any>;
}

export interface ModelPricing {
  model: string;
  input_price: number;
  output_price: number;
}

export interface BudgetConfig {
  daily_budget: number;
  monthly_budget: number;
}

export interface TokenCountResult {
  text: string;
  model: string;
  token_count: number;
  encoding: string;
}

export interface MessageTokenCountResult {
  model: string;
  message_count: number;
  token_count: number;
}

export const costAPI = {
  /**
   * 获取当前预算状态
   */
  async getBudgetStatus(): Promise<BudgetStatus> {
    try {
      return await fetchAPI<BudgetStatus>("/api/cost/status");
    } catch (error) {
      return handleError(error, "获取预算状态失败");
    }
  },

  /**
   * 获取使用统计
   */
  async getUsageStats(days: number = 30): Promise<UsageStats> {
    try {
      return await fetchAPI<UsageStats>(`/api/cost/stats?days=${days}`);
    } catch (error) {
      return handleError(error, "获取使用统计失败");
    }
  },

  /**
   * 生成完整成本报告
   */
  async getCostReport(): Promise<Record<string, any>> {
    try {
      return await fetchAPI<Record<string, any>>("/api/cost/report");
    } catch (error) {
      return handleError(error, "生成成本报告失败");
    }
  },

  /**
   * 获取详细使用记录
   */
  async getUsageRecords(params?: {
    limit?: number;
    offset?: number;
    model?: string;
    start_date?: string;
    end_date?: string;
  }): Promise<CostRecord[]> {
    try {
      const query = new URLSearchParams();
      if (params?.limit) query.set("limit", params.limit.toString());
      if (params?.offset !== undefined) query.set("offset", params.offset.toString());
      if (params?.model) query.set("model", params.model);
      if (params?.start_date) query.set("start_date", params.start_date);
      if (params?.end_date) query.set("end_date", params.end_date);
      const qs = query.toString();
      return await fetchAPI<CostRecord[]>(`/api/cost/usage${qs ? "?" + qs : ""}`);
    } catch (error) {
      return handleError(error, "获取使用记录失败");
    }
  },

  /**
   * 更新预算设置
   */
  async updateBudget(config: BudgetConfig): Promise<{ success: boolean; message: string }> {
    try {
      return await fetchAPI<{ success: boolean; message: string }>("/api/cost/budget", {
        method: "POST",
        body: config,
      });
    } catch (error) {
      return handleError(error, "更新预算设置失败");
    }
  },

  /**
   * 获取模型定价列表
   */
  async getModelPricing(): Promise<ModelPricing[]> {
    try {
      return await fetchAPI<ModelPricing[]>("/api/cost/models");
    } catch (error) {
      return handleError(error, "获取模型定价失败");
    }
  },

  /**
   * 计算文本 Token 数量
   */
  async countTokens(text: string, model: string = "gpt-4"): Promise<TokenCountResult> {
    try {
      return await fetchAPI<TokenCountResult>("/api/cost/count", {
        method: "POST",
        body: { text, model },
      });
    } catch (error) {
      return handleError(error, "Token 计数失败");
    }
  },

  /**
   * 计算消息列表 Token 数量
   */
  async countMessageTokens(
    messages: Array<Record<string, string>>,
    model: string = "gpt-4",
  ): Promise<MessageTokenCountResult> {
    try {
      return await fetchAPI<MessageTokenCountResult>(`/api/cost/count-messages?model=${encodeURIComponent(model)}`, {
        method: "POST",
        body: messages,
      });
    } catch (error) {
      return handleError(error, "消息 Token 计数失败");
    }
  },
};

export default costAPI;
