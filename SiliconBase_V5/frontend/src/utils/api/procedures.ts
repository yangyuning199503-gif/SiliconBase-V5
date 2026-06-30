/**
 * 任务流程（Procedures）API
 * 对应后端 /api/tasks/procedures/* 端点
 */

import { fetchAPI, handleError } from "./index";

export interface ProcedureStep {
  step_id: string;
  step_number: number;
  description: string;
  tool_name: string;
  expected_result?: string;
}

export interface Procedure {
  procedure_id: string;
  id?: string; // 向后兼容
  name: string;
  intent: string;
  description: string;
  steps: ProcedureStep[];
  step_count: number;
  success_rate: number;
  usage_count: number;
  success_count?: number;
  avg_execution_time?: number;
  is_active: boolean;
  tags: string[];
  parameters?: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface ProcedureRecording {
  is_recording: boolean;
  recording_id?: string;
  operation_count: number;
  duration_seconds: number;
}

export interface ProcedureRecordingStatus {
  is_recording: boolean;
  recording_id?: string;
  operation_count: number;
  duration_seconds: number;
}

export interface ProcedureSessionStatus {
  session_id: string;
  task_id?: string;
  intent?: string;
  mode: string;
  procedure_id?: string;
  recording_id?: string;
  created_at?: string;
}

export const procedureAPI = {
  /**
   * 开始流程录制
   */
  async startRecording(): Promise<{ success: boolean; recording_id: string; message: string }> {
    try {
      return await fetchAPI<{ success: boolean; recording_id: string; message: string }>(
        "/api/tasks/procedures/recordings/start",
        { method: "POST" },
      );
    } catch (error) {
      return handleError(error, "开始流程录制失败");
    }
  },

  /**
   * 停止流程录制
   */
  async stopRecording(): Promise<{ success: boolean; procedure_id?: string; message: string }> {
    try {
      return await fetchAPI<{ success: boolean; procedure_id?: string; message: string }>(
        "/api/tasks/procedures/recordings/stop",
        { method: "POST" },
      );
    } catch (error) {
      return handleError(error, "停止流程录制失败");
    }
  },

  /**
   * 获取录制状态
   */
  async getRecordingStatus(): Promise<ProcedureRecordingStatus> {
    try {
      return await fetchAPI<ProcedureRecordingStatus>(
        "/api/tasks/procedures/recordings/status",
      );
    } catch (error) {
      return handleError(error, "获取录制状态失败");
    }
  },

  /**
   * 获取流程列表
   */
  async getProcedures(): Promise<Procedure[]> {
    try {
      const response = await fetchAPI<{ procedures: Procedure[]; total_count: number }>(
        "/api/tasks/procedures",
      );
      return response.procedures || [];
    } catch (error) {
      return handleError(error, "获取流程列表失败");
    }
  },

  /**
   * 搜索流程
   */
  async searchProcedures(query: string): Promise<Procedure[]> {
    try {
      const response = await fetchAPI<{ intent: string; procedures: Procedure[]; total_count: number }>(
        `/api/tasks/procedures/search?intent=${encodeURIComponent(query)}`,
      );
      return response.procedures || [];
    } catch (error) {
      return handleError(error, "搜索流程失败");
    }
  },

  /**
   * 获取流程详情
   */
  async getProcedure(procedureId: string): Promise<Procedure> {
    try {
      return await fetchAPI<Procedure>(
        `/api/tasks/procedures/${encodeURIComponent(procedureId)}`,
      );
    } catch (error) {
      return handleError(error, "获取流程详情失败");
    }
  },

  /**
   * 执行流程
   * @param procedureId - 流程ID
   * @param sessionId - 任务会话ID
   * @param parameters - 运行时参数
   */
  async executeProcedure(
    procedureId: string,
    sessionId: string,
    parameters?: Record<string, any>,
  ): Promise<{ success: boolean; session_id: string; procedure_id: string; message: string }> {
    try {
      return await fetchAPI<{ success: boolean; session_id: string; procedure_id: string; message: string }>(
        `/api/tasks/procedures/${encodeURIComponent(procedureId)}/execute`,
        {
          method: "POST",
          body: { session_id: sessionId, parameters },
        },
      );
    } catch (error) {
      return handleError(error, "执行流程失败");
    }
  },

  /**
   * 删除流程
   */
  async deleteProcedure(procedureId: string): Promise<{ success: boolean; message: string }> {
    try {
      return await fetchAPI<{ success: boolean; message: string }>(
        `/api/tasks/procedures/${encodeURIComponent(procedureId)}`,
        { method: "DELETE" },
      );
    } catch (error) {
      return handleError(error, "删除流程失败");
    }
  },

  /**
   * 暂停流程会话
   */
  async pauseSession(sessionId: string): Promise<{ success: boolean; message: string }> {
    try {
      return await fetchAPI<{ success: boolean; message: string }>(
        `/api/tasks/procedures/sessions/${encodeURIComponent(sessionId)}/pause`,
        { method: "POST" },
      );
    } catch (error) {
      return handleError(error, "暂停流程会话失败");
    }
  },

  /**
   * 恢复流程会话
   */
  async resumeSession(sessionId: string): Promise<{ success: boolean; message: string }> {
    try {
      return await fetchAPI<{ success: boolean; message: string }>(
        `/api/tasks/procedures/sessions/${encodeURIComponent(sessionId)}/resume`,
        { method: "POST" },
      );
    } catch (error) {
      return handleError(error, "恢复流程会话失败");
    }
  },

  /**
   * 获取流程会话状态
   */
  async getSessionStatus(sessionId: string): Promise<ProcedureSessionStatus> {
    try {
      return await fetchAPI<ProcedureSessionStatus>(
        `/api/tasks/procedures/sessions/${encodeURIComponent(sessionId)}/status`,
      );
    } catch (error) {
      return handleError(error, "获取流程会话状态失败");
    }
  },
};

export default procedureAPI;
