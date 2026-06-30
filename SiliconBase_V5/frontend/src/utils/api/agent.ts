/**
 * 父代理干预API封装
 *
 * 提供父代理任务的暂停、恢复、调整、取消等操作
 *
 * 【静默失败阻断规则】绝对禁止违反！
 * - 所有错误必须抛出异常，禁止返回null或默认值
 * - HTTP错误必须抛出APIError
 * - 所有错误日志自动标记 [SILENT_FAILURE_BLOCKED]
 */

import { fetchAPI, APIError } from "./core";
import { buildWsUrl } from "../../config/api";

// 简单的日志工具
const logger = {
  error: (...args: any[]) => console.error("[SILENT_FAILURE_BLOCKED]", ...args),
  info: (...args: any[]) => console.info("[AgentAPI]", ...args),
};

/**
 * 代理干预类型
 */
export type AgentInterventionType = "PAUSE" | "RESUME" | "CANCEL";

/**
 * 代理任务信息
 */
export interface AgentTaskInfo {
  task_id: string;
  status: "running" | "paused" | "completed" | "failed" | "cancelled";
  mode?: "fast" | "slow" | "interactive";
  progress?: number;
  current_step?: string;
  subtasks?: string[];
}

/**
 * 干预响应
 */
export interface AgentInterventionResponse {
  success: boolean;
  message: string;
  status?: string;
}

/**
 * 提交代理干预请求
 *
 * @param taskId - 任务ID
 * @param type - 干预类型
 * @returns 干预响应
 */
export async function interveneAgent(
  taskId: string,
  type: AgentInterventionType,
): Promise<AgentInterventionResponse> {
  logger.info(`提交干预: ${taskId}`, { type });

  try {
    const response = await fetchAPI<{ message?: string; status?: string }>(
      `/api/agent/intervene`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: { task_id: taskId, type },
      },
    );

    logger.info(`干预成功: ${taskId}`, response);

    return {
      success: true,
      message: response.message || "干预已提交",
      status: response.status,
    };
  } catch (error) {
    const message = error instanceof APIError ? error.message : "干预请求失败";
    logger.error("干预异常:", error);
    throw new APIError(message, error instanceof APIError ? error.status : 500);
  }
}

/**
 * 暂停代理任务
 *
 * @param taskId - 任务ID
 * @returns 干预响应
 */
export async function pauseAgent(
  taskId: string,
): Promise<AgentInterventionResponse> {
  return interveneAgent(taskId, "PAUSE");
}

/**
 * 恢复代理任务
 *
 * @param taskId - 任务ID
 * @returns 干预响应
 */
export async function resumeAgent(
  taskId: string,
): Promise<AgentInterventionResponse> {
  return interveneAgent(taskId, "RESUME");
}

/**
 * 取消代理任务
 *
 * @param taskId - 任务ID
 * @returns 干预响应
 */
export async function cancelAgent(
  taskId: string,
): Promise<AgentInterventionResponse> {
  return interveneAgent(taskId, "CANCEL");
}

/**
 * 切换代理模式
 *
 * @param taskId - 任务ID
 * @param mode - 新模式
 * @returns 干预响应
 */
export async function switchAgentMode(
  taskId: string,
  mode: "fast" | "slow" | "interactive",
): Promise<AgentInterventionResponse> {
  logger.info(`切换模式: ${taskId} -> ${mode}`);

  try {
    const response = await fetchAPI<{ message?: string; status?: string }>(
      `/api/agent/mode`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: { task_id: taskId, mode },
      },
    );

    logger.info(`模式切换成功: ${taskId}`, response);

    return {
      success: true,
      message: response.message || "模式已切换",
      status: response.status,
    };
  } catch (error) {
    const message = error instanceof APIError ? error.message : "模式切换失败";
    logger.error("模式切换异常:", error);
    throw new APIError(message, error instanceof APIError ? error.status : 500);
  }
}

/**
 * 获取代理任务状态
 *
 * @param taskId - 任务ID
 * @returns 代理任务信息
 */
export async function getAgentStatus(taskId: string): Promise<AgentTaskInfo> {
  try {
    const response = await fetchAPI(
      `/api/agent/status?task_id=${encodeURIComponent(taskId)}`,
    );

    return response as AgentTaskInfo;
  } catch (error) {
    logger.error("获取状态失败:", error);
    throw error;
  }
}

/**
 * 向正在运行的任务追加指令
 *
 * @param taskId - 任务ID
 * @param instruction - 追加的指令
 * @returns 干预响应
 */
export async function appendInstruction(
  taskId: string,
  instruction: string,
): Promise<AgentInterventionResponse> {
  logger.info(`追加指令: ${taskId}`, { instruction });

  try {
    const response = await fetchAPI<{ message?: string }>(
      `/api/agent/instruction`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: { task_id: taskId, instruction },
      },
    );

    logger.info(`指令已追加: ${taskId}`, response);

    return {
      success: true,
      message: response.message || "指令已追加",
    };
  } catch (error) {
    const message = error instanceof APIError ? error.message : "追加指令失败";
    logger.error("追加指令异常:", error);
    throw new APIError(message, error instanceof APIError ? error.status : 500);
  }
}

/**
 * 监听代理状态变更（WebSocket）
 *
 * @param taskId - 任务ID
 * @param onStatusChange - 状态变更回调
 * @returns WebSocket连接
 */
export function watchAgentStatus(
  taskId: string,
  onStatusChange: (status: AgentTaskInfo) => void,
): WebSocket {
  const token = localStorage.getItem("silicon_token");
  const ws = new WebSocket(
    `${buildWsUrl(`/ws/task/${encodeURIComponent(taskId)}`)}${token ? `?token=${token}` : ""}`,
  );

  ws.onopen = () => {
    logger.info(`WebSocket连接已建立: ${taskId}`);
  };

  ws.onmessage = (event) => {
    try {
      const status = JSON.parse(event.data) as AgentTaskInfo;
      onStatusChange(status);
    } catch (error) {
      logger.error("解析WebSocket消息失败:", error);
    }
  };

  ws.onerror = (error) => {
    logger.error("WebSocket错误:", error);
  };

  ws.onclose = () => {
    logger.info(`WebSocket连接已关闭: ${taskId}`);
  };

  return ws;
}

// 导出API对象
export const agentApi = {
  intervene: interveneAgent,
  pause: pauseAgent,
  resume: resumeAgent,
  cancel: cancelAgent,
  switchMode: switchAgentMode,
  getStatus: getAgentStatus,
  appendInstruction,
  watchStatus: watchAgentStatus,
};

export default agentApi;
