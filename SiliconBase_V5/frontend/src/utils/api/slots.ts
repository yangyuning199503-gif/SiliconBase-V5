/**
 * 任务槽位（Slots）API
 * 对应后端 /api/tasks/slots/* 端点
 */

import { fetchAPI, handleError } from "./index";

export interface SlotStatus {
  slot_id: number;
  status: 'idle' | 'running' | 'paused' | 'error';
  task_id?: string;
  task_name?: string;
  task_type?: string;
  progress: number;
  created_at?: number;
  updated_at?: number;
  started_at?: number;
  paused_at?: number;
  resumed_at?: number;
  ai_understanding?: string;
  user_requirements?: string;
  error_message?: string;
}

export interface SlotTaskCreateResponse {
  success: boolean;
  slot_id: number;
  task_id?: string;
  message: string;
  status?: string;
}

export const slotAPI = {
  /**
   * 获取所有槽位列表
   */
  async getSlots(): Promise<SlotStatus[]> {
    try {
      const response = await fetchAPI<{ success: boolean; slots: SlotStatus[]; timestamp: number }>(
        "/api/tasks/slots",
      );
      return response.slots || [];
    } catch (error) {
      return handleError(error, "获取槽位列表失败");
    }
  },

  /**
   * 获取槽位状态
   */
  async getSlot(slotId: number): Promise<SlotStatus> {
    try {
      return await fetchAPI<SlotStatus>(`/api/tasks/slots/${slotId}`);
    } catch (error) {
      return handleError(error, "获取槽位状态失败");
    }
  },

  /**
   * 在槽位中创建任务
   */
  async createTask(slotId: number, taskData: {
    task_name: string;
    task_type: string;
    params?: Record<string, any>;
    user_requirements?: string;
    metadata?: Record<string, any>;
  }): Promise<SlotTaskCreateResponse> {
    try {
      return await fetchAPI<SlotTaskCreateResponse>(
        `/api/tasks/slots/${slotId}/create`,
        {
          method: "POST",
          body: taskData,
        },
      );
    } catch (error) {
      return handleError(error, "槽位创建任务失败");
    }
  },

  /**
   * 暂停槽位任务
   */
  async pause(slotId: number, reason: string = "用户暂停"): Promise<{ success: boolean; slot_id: number; task_id?: string; message: string }> {
    try {
      return await fetchAPI<{ success: boolean; slot_id: number; task_id?: string; message: string }>(
        `/api/tasks/slots/${slotId}/pause`,
        {
          method: "POST",
          body: { reason },
        },
      );
    } catch (error) {
      return handleError(error, "暂停槽位任务失败");
    }
  },

  /**
   * 恢复槽位任务
   */
  async resume(slotId: number, aiConfirmation: string): Promise<{ success: boolean; slot_id: number; task_id?: string; message: string; requires_confirmation?: boolean }> {
    try {
      return await fetchAPI<{ success: boolean; slot_id: number; task_id?: string; message: string; requires_confirmation?: boolean }>(
        `/api/tasks/slots/${slotId}/resume`,
        {
          method: "POST",
          body: { ai_confirmation: aiConfirmation },
        },
      );
    } catch (error) {
      return handleError(error, "恢复槽位任务失败");
    }
  },

  /**
   * 修改槽位任务
   */
  async modify(slotId: number, newParams: Record<string, any>): Promise<{ success: boolean; slot_id: number; task_id?: string; updated_params: Record<string, any>; message: string }> {
    try {
      return await fetchAPI<{ success: boolean; slot_id: number; task_id?: string; updated_params: Record<string, any>; message: string }>(
        `/api/tasks/slots/${slotId}/modify`,
        {
          method: "POST",
          body: { new_params: newParams },
        },
      );
    } catch (error) {
      return handleError(error, "修改槽位任务失败");
    }
  },

  /**
   * 停止槽位任务
   */
  async stop(slotId: number): Promise<{ success: boolean; slot_id: number; message: string }> {
    try {
      return await fetchAPI<{ success: boolean; slot_id: number; message: string }>(
        `/api/tasks/slots/${slotId}/stop`,
        { method: "POST" },
      );
    } catch (error) {
      return handleError(error, "停止槽位任务失败");
    }
  },

  /**
   * 完成槽位任务
   */
  async complete(slotId: number, result?: Record<string, any>): Promise<{ success: boolean; slot_id: number; task_id?: string; message: string }> {
    try {
      return await fetchAPI<{ success: boolean; slot_id: number; task_id?: string; message: string }>(
        `/api/tasks/slots/${slotId}/complete`,
        {
          method: "POST",
          body: { result },
        },
      );
    } catch (error) {
      return handleError(error, "完成槽位任务失败");
    }
  },

  /**
   * 更新槽位任务进度
   */
  async updateProgress(slotId: number, progress: number): Promise<{ success: boolean; slot_id: number; task_id?: string; progress: number; message: string }> {
    try {
      return await fetchAPI<{ success: boolean; slot_id: number; task_id?: string; progress: number; message: string }>(
        `/api/tasks/slots/${slotId}/progress`,
        {
          method: "POST",
          body: { progress },
        },
      );
    } catch (error) {
      return handleError(error, "更新槽位进度失败");
    }
  },

  /**
   * 提交槽位 AI 理解确认
   */
  async submitUnderstanding(slotId: number, understanding: string): Promise<{ success: boolean; slot_id: number; message: string }> {
    try {
      return await fetchAPI<{ success: boolean; slot_id: number; message: string }>(
        `/api/tasks/slots/${slotId}/understanding`,
        {
          method: "POST",
          body: { understanding },
        },
      );
    } catch (error) {
      return handleError(error, "提交理解确认失败");
    }
  },

  /**
   * 获取槽位 AI 摘要
   */
  async getAISummary(slotId: number): Promise<string> {
    try {
      const response = await fetchAPI<{ success: boolean; data: string }>(
        `/api/tasks/slots/${slotId}/ai-summary`,
      );
      return response.data || "";
    } catch (error) {
      return handleError(error, "获取槽位 AI 摘要失败");
    }
  },

  /**
   * 获取所有槽位 AI 摘要
   */
  async getAllAISummaries(): Promise<string> {
    try {
      const response = await fetchAPI<{ success: boolean; data: string }>(
        "/api/tasks/slots/ai-summary",
      );
      return response.data || "";
    } catch (error) {
      return handleError(error, "获取槽位摘要列表失败");
    }
  },
};

export default slotAPI;
