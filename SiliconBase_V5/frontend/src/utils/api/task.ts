/**
 * 任务管理 API
 * 提供任务暂停、恢复、状态查询等功能
 *
 * 【静默失败阻断规则】绝对禁止违反！
 * - 所有错误必须抛出异常，禁止返回null或默认值
 * - HTTP错误必须抛出APIError
 * - 所有错误日志自动标记 [SILENT_FAILURE_BLOCKED]
 */

import { fetchAPI, APIError } from "./core";
import type { TaskListItem, TaskStatus } from "../../types";

// 简单的日志工具
const logger = {
  error: (...args: any[]) => console.error("[SILENT_FAILURE_BLOCKED]", ...args),
  info: (...args: any[]) => console.info("[TaskAPI]", ...args),
};

/**
 * 任务状态枚举（后端 TaskResponse.status 的字符串值）
 */
export type TaskState =
  | "pending"
  | "ready"
  | "running"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled"
  | "archived"
  | "interrupted"
  | "awaiting_confirmation"
  | "confirming_understanding"
  | "confirmed";

/**
 * 任务接口
 * 注意：/api/tasks 列表端点实际返回的字段和类型与此不完全一致，
 * 列表项请参见 types/index.ts 中的 TaskListItem。
 */
export interface Task {
  id: string;
  user_id: string;
  title: string;
  description: string;
  status: TaskState;
  priority: number;
  task_type: string;
  parent_id?: string;
  created_at: string;
  updated_at: string;
  started_at?: string;
  completed_at?: string;
  deadline?: string;
  retry_count: number;
  max_retries: number;
  is_compressed: boolean;
  compressed_summary?: string;
  result?: Record<string, any>;
  error?: string;
  metadata: Record<string, any>;
  progress?: number;
}

/**
 * 暂停任务请求参数
 */
export interface PauseTaskParams {
  /** 暂停原因 */
  reason?: string;
  /** 用户提出的新需求 */
  new_requirements?: string;
  /** 会话ID（用于同步阶段锚点） */
  session_id?: string;
}

/**
 * 暂停任务响应
 */
export interface PauseTaskResponse {
  success: boolean;
  task_id: string;
  checkpoint_id?: string;
  phase_count?: number; // 【新增】已保存的阶段锚点数量
  message?: string;
  requires_ai_confirmation?: boolean;
  ai_prompt?: string;
  error?: string;
}

/**
 * 恢复任务请求参数
 */
export interface ResumeTaskParams {
  /** AI对需求理解的确认内容 */
  ai_confirmation?: string;
  /** 是否已确认AI理解需求 */
  confirmed_understanding?: boolean;
  /** 会话ID（用于同步阶段锚点和工作记忆） */
  session_id?: string;
}

/**
 * 恢复任务响应
 */
export interface ResumeTaskResponse {
  success: boolean;
  task_id: string;
  message?: string;
  requires_ai_confirmation?: boolean;
  ai_prompt?: string;
  error?: string;
}

/**
 * 任务状态响应
 */
export interface TaskStatusResponse {
  task_id: string;
  status: TaskState;
  progress: number;
  checkpoint_id?: string;
  paused_at?: string;
  pause_reason?: string;
}

/**
 * 任务控制面板属性
 */
export interface TaskControlPanelProps {
  taskId: string;
  sessionId: string;
  initialStatus?: TaskState;
  onStatusChange?: (status: TaskState) => void;
}

/**
 * 创建任务请求参数
 */
export interface CreateTaskParams {
  title: string;
  description?: string;
  priority?: "urgent" | "high" | "normal" | "low";
  task_type?: string;
  parent_id?: string;
  depends_on?: string[];
  memory_ids?: string[];
  deadline?: string;
  max_retries?: number;
  metadata?: Record<string, any>;
}

/**
 * 创建任务响应
 */
export interface CreateTaskResponse {
  id: string;
  message?: string;
}

/**
 * 任务列表过滤参数
 */
export interface ListTasksFilters {
  status?: string;
  task_type?: string;
  parent_id?: string;
  limit?: number;
  offset?: number;
}

/**
 * 任务列表响应
 */
export interface ListTasksResponse {
  tasks: TaskListItem[];
  total: number;
  limit: number;
  offset: number;
}

/**
 * 任务API封装
 */
export const taskApi = {
  /**
   * 创建新任务（仅添加到待办，不会自动执行）
   * @param params - 创建参数
   * @returns 创建结果
   */
  async createTask(params: CreateTaskParams): Promise<CreateTaskResponse> {
    try {
      logger.info("创建任务", params);

      const response = await fetchAPI<CreateTaskResponse>("/api/tasks", {
        method: "POST",
        body: {
          title: params.title,
          description: params.description,
          priority: params.priority || "normal",
          task_type: params.task_type || "custom",
          parent_id: params.parent_id,
          depends_on: params.depends_on,
          memory_ids: params.memory_ids,
          deadline: params.deadline,
          max_retries: params.max_retries ?? 3,
          metadata: params.metadata || {},
        },
      });

      if (!response) {
        logger.error("createTask返回空值");
        throw new Error("创建任务失败：返回空值");
      }

      if (!response.id) {
        logger.error("createTask返回数据缺少id字段:", response);
        throw new Error("创建任务失败：返回数据格式错误");
      }

      return response;
    } catch (error) {
      logger.error("创建任务异常:", error);
      throw error;
    }
  },

  /**
   * 获取任务列表
   * @param filters - 过滤参数
   * @returns 任务列表
   */
  async listTasks(filters: ListTasksFilters = {}): Promise<ListTasksResponse> {
    try {
      const query = new URLSearchParams();
      if (filters.status) query.set("status", filters.status);
      if (filters.task_type) query.set("task_type", filters.task_type);
      if (filters.parent_id) query.set("parent_id", filters.parent_id);
      if (filters.limit !== undefined) query.set("limit", String(filters.limit));
      if (filters.offset !== undefined) query.set("offset", String(filters.offset));

      const queryString = query.toString();
      const url = queryString ? `/api/tasks?${queryString}` : "/api/tasks";

      const response = await fetchAPI<ListTasksResponse>(url);

      if (!response) {
        logger.error("listTasks返回空值");
        throw new Error("获取任务列表失败：返回空值");
      }

      return {
        tasks: response.tasks || [],
        total: response.total ?? 0,
        limit: response.limit ?? 100,
        offset: response.offset ?? 0,
      };
    } catch (error) {
      logger.error("获取任务列表异常:", error);
      throw error;
    }
  },

  /**
   * 暂停任务
   * @param taskId - 任务ID
   * @param params - 暂停参数
   * @returns 暂停结果
   */
  async pauseTask(
    taskId: string,
    params: PauseTaskParams = {},
  ): Promise<PauseTaskResponse> {
    try {
      logger.info(`暂停任务: ${taskId}`, params);

      // 【修复新增】构建请求头，传递session_id以同步阶段锚点
      const headers: Record<string, string> = {};
      if (params.session_id) {
        headers["X-Session-Id"] = params.session_id;
      }

      const response = await fetchAPI<PauseTaskResponse>(
        `/api/tasks/${encodeURIComponent(taskId)}/pause`,
        {
          method: "POST",
          headers, // 【修复新增】传递包含X-Session-Id的请求头
          body: {
            reason: params.reason || "用户暂停",
            new_requirements: params.new_requirements,
          },
        },
      );

      // 静默失败阻断检查
      if (!response) {
        logger.error("pauseTask返回空值，taskId:", taskId);
        throw new Error("暂停任务失败：返回空值");
      }

      if (typeof response.success !== "boolean") {
        logger.error("pauseTask返回数据格式错误，缺少success字段:", response);
        throw new Error("暂停任务失败：返回数据格式错误");
      }

      return response;
    } catch (error) {
      logger.error("暂停任务异常:", error);

      if (error instanceof APIError) {
        throw error;
      }

      throw new APIError(
        error instanceof Error ? error.message : "暂停任务失败",
        0,
        null,
      );
    }
  },

  /**
   * 恢复任务
   * @param taskId - 任务ID
   * @param params - 恢复参数
   * @returns 恢复结果
   */
  async resumeTask(
    taskId: string,
    params: ResumeTaskParams = {},
  ): Promise<ResumeTaskResponse> {
    try {
      logger.info(`恢复任务: ${taskId}`, params);

      // 构建请求头，传递session_id以同步阶段锚点和工作记忆
      const headers: Record<string, string> = {};
      if (params.session_id) {
        headers["X-Session-Id"] = params.session_id;
      }

      const response = await fetchAPI<ResumeTaskResponse>(
        `/api/tasks/${encodeURIComponent(taskId)}/resume`,
        {
          method: "POST",
          headers,
          body: {
            ai_confirmation: params.ai_confirmation,
            confirmed_understanding: params.confirmed_understanding || false,
          },
        },
      );

      // 静默失败阻断检查
      if (!response) {
        logger.error("resumeTask返回空值，taskId:", taskId);
        throw new Error("恢复任务失败：返回空值");
      }

      if (typeof response.success !== "boolean") {
        logger.error("resumeTask返回数据格式错误，缺少success字段:", response);
        throw new Error("恢复任务失败：返回数据格式错误");
      }

      return response;
    } catch (error) {
      logger.error("恢复任务异常:", error);

      if (error instanceof APIError) {
        throw error;
      }

      throw new APIError(
        error instanceof Error ? error.message : "恢复任务失败",
        0,
        null,
      );
    }
  },

  /**
   * 获取任务详情
   * @param taskId - 任务ID
   * @returns 任务详情
   */
  async getTask(taskId: string): Promise<Task> {
    try {
      logger.info(`获取任务详情: ${taskId}`);

      const response = await fetchAPI<{ task: Task }>(
        `/api/tasks/${encodeURIComponent(taskId)}`,
      );

      // 静默失败阻断检查
      if (!response) {
        logger.error("getTask返回空值，taskId:", taskId);
        throw new Error("获取任务详情失败：返回空值");
      }

      if (!response.task) {
        logger.error("getTask返回数据缺少task字段:", response);
        throw new Error("获取任务详情失败：返回数据格式错误");
      }

      return response.task;
    } catch (error) {
      logger.error("获取任务详情异常:", error);
      throw error;
    }
  },

  /**
   * 获取任务状态
   * @param taskId - 任务ID
   * @returns 任务状态
   */
  async getTaskStatus(taskId: string): Promise<TaskStatusResponse> {
    try {
      logger.info(`获取任务状态: ${taskId}`);

      const task = await this.getTask(taskId);

      return {
        task_id: task.id,
        status: task.status,
        progress: task.progress || 0,
        paused_at: task.metadata?.paused_at,
        pause_reason: task.metadata?.pause_reason,
      };
    } catch (error) {
      logger.error("获取任务状态异常:", error);
      throw error;
    }
  },

  /**
   * 取消任务
   * @param taskId - 任务ID
   * @param reason - 取消原因
   * @returns 取消结果
   */
  async cancelTask(
    taskId: string,
    reason?: string,
  ): Promise<{ success: boolean }> {
    try {
      logger.info(`取消任务: ${taskId}`, { reason });

      const response = await fetchAPI<{ success: boolean }>(
        `/api/tasks/${encodeURIComponent(taskId)}/cancel`,
        {
          method: "POST",
          body: reason ? { reason } : undefined,
        },
      );

      // 静默失败阻断检查
      if (!response) {
        logger.error("cancelTask返回空值，taskId:", taskId);
        throw new Error("取消任务失败：返回空值");
      }

      if (typeof response.success !== "boolean") {
        logger.error("cancelTask返回数据格式错误，缺少success字段:", response);
        throw new Error("取消任务失败：返回数据格式错误");
      }

      return response;
    } catch (error) {
      logger.error("取消任务异常:", error);
      throw error;
    }
  },

  /**
   * 完成任务
   * @param taskId - 任务ID
   * @param result - 执行结果
   * @param triggerCompression - 是否触发语义压缩
   * @returns 完成结果
   */
  async completeTask(
    taskId: string,
    result?: Record<string, any>,
    triggerCompression: boolean = true,
  ): Promise<{ success: boolean; message?: string }> {
    try {
      logger.info(`完成任务: ${taskId}`, { triggerCompression });

      const url = triggerCompression
        ? `/api/tasks/${encodeURIComponent(taskId)}/complete`
        : `/api/tasks/${encodeURIComponent(taskId)}/complete?trigger_compression=false`;
      const response = await fetchAPI<{ success: boolean; message?: string }>(
        url,
        {
          method: "POST",
          body: result,
        },
      );

      if (!response) {
        logger.error("completeTask返回空值，taskId:", taskId);
        throw new Error("完成任务失败：返回空值");
      }

      if (typeof response.success !== "boolean") {
        logger.error(
          "completeTask返回数据格式错误，缺少success字段:",
          response,
        );
        throw new Error("完成任务失败：返回数据格式错误");
      }

      return response;
    } catch (error) {
      logger.error("完成任务异常:", error);
      throw error;
    }
  },

  /**
   * 标记任务失败
   * @param taskId - 任务ID
   * @param errorMessage - 错误信息
   * @returns 标记结果
   */
  async failTask(
    taskId: string,
    errorMessage?: string,
  ): Promise<{ success: boolean; message?: string }> {
    try {
      logger.info(`标记任务失败: ${taskId}`, { errorMessage });

      const response = await fetchAPI<{ success: boolean; message?: string }>(
        `/api/tasks/${encodeURIComponent(taskId)}/fail`,
        {
          method: "POST",
          body: { error: errorMessage || "用户手动标记失败" },
        },
      );

      if (!response) {
        logger.error("failTask返回空值，taskId:", taskId);
        throw new Error("标记任务失败失败：返回空值");
      }

      if (typeof response.success !== "boolean") {
        logger.error("failTask返回数据格式错误，缺少success字段:", response);
        throw new Error("标记任务失败失败：返回数据格式错误");
      }

      return response;
    } catch (error) {
      logger.error("标记任务失败异常:", error);
      throw error;
    }
  },

  /**
   * 压缩任务（语义归档）
   * @param taskId - 任务ID
   * @param force - 是否强制重新压缩
   * @returns 压缩结果
   */
  async compressTask(
    taskId: string,
    force: boolean = false,
  ): Promise<{ success: boolean; summary?: string }> {
    try {
      logger.info(`压缩任务: ${taskId}`, { force });

      const response = await fetchAPI<{ success: boolean; summary?: string }>(
        `/api/tasks/${encodeURIComponent(taskId)}/compress`,
        {
          method: "POST",
          body: { force },
        },
      );

      if (!response) {
        logger.error("compressTask返回空值，taskId:", taskId);
        throw new Error("压缩任务失败：返回空值");
      }

      if (typeof response.success !== "boolean") {
        logger.error(
          "compressTask返回数据格式错误，缺少success字段:",
          response,
        );
        throw new Error("压缩任务失败：返回数据格式错误");
      }

      return response;
    } catch (error) {
      logger.error("压缩任务异常:", error);
      throw error;
    }
  },

  /**
   * 更新任务（PATCH）
   */
  async updateTask(
    taskId: string,
    updates: Partial<Task>,
  ): Promise<Task> {
    try {
      const response = await fetchAPI<{ task: Task }>(
        `/api/tasks/${encodeURIComponent(taskId)}`,
        {
          method: "PATCH",
          body: updates,
        },
      );
      return response.task;
    } catch (error) {
      logger.error("更新任务异常:", error);
      throw error;
    }
  },

  /**
   * 删除任务
   */
  async deleteTask(taskId: string): Promise<{ success: boolean }> {
    try {
      return await fetchAPI<{ success: boolean }>(
        `/api/tasks/${encodeURIComponent(taskId)}`,
        { method: "DELETE" },
      );
    } catch (error) {
      logger.error("删除任务异常:", error);
      throw error;
    }
  },

  /**
   * 归档任务
   */
  async archiveTask(taskId: string): Promise<{ success: boolean; message?: string }> {
    try {
      return await fetchAPI<{ success: boolean; message?: string }>(
        `/api/tasks/${encodeURIComponent(taskId)}/archive`,
        { method: "POST" },
      );
    } catch (error) {
      logger.error("归档任务异常:", error);
      throw error;
    }
  },

  /**
   * 添加任务依赖
   */
  async addDependency(taskId: string, dependsOn: string): Promise<{ success: boolean }> {
    try {
      return await fetchAPI<{ success: boolean }>(
        `/api/tasks/${encodeURIComponent(taskId)}/dependencies`,
        {
          method: "POST",
          body: { depends_on: dependsOn },
        },
      );
    } catch (error) {
      logger.error("添加任务依赖异常:", error);
      throw error;
    }
  },

  /**
   * 移除任务依赖
   */
  async removeDependency(taskId: string, dependsOn: string): Promise<{ success: boolean }> {
    try {
      return await fetchAPI<{ success: boolean }>(
        `/api/tasks/${encodeURIComponent(taskId)}/dependencies/${encodeURIComponent(dependsOn)}`,
        { method: "DELETE" },
      );
    } catch (error) {
      logger.error("移除任务依赖异常:", error);
      throw error;
    }
  },

  /**
   * 获取任务依赖
   */
  async getDependencies(taskId: string): Promise<Task[]> {
    try {
      const response = await fetchAPI<{ dependencies: Task[] }>(
        `/api/tasks/${encodeURIComponent(taskId)}/dependencies`,
      );
      return response.dependencies || [];
    } catch (error) {
      logger.error("获取任务依赖异常:", error);
      throw error;
    }
  },

  /**
   * 获取任务执行计划
   */
  async getExecutionPlan(): Promise<Record<string, any>> {
    try {
      return await fetchAPI<Record<string, any>>("/api/tasks/plan/execution");
    } catch (error) {
      logger.error("获取任务执行计划异常:", error);
      throw error;
    }
  },

  /**
   * 批量压缩任务
   */
  async batchCompress(taskIds: string[]): Promise<{ success: boolean; compressed: number }> {
    try {
      return await fetchAPI<{ success: boolean; compressed: number }>(
        "/api/tasks/batch/compress",
        {
          method: "POST",
          body: { task_ids: taskIds },
        },
      );
    } catch (error) {
      logger.error("批量压缩任务异常:", error);
      throw error;
    }
  },

  /**
   * 搜索相似任务
   */
  async searchSimilar(query: string, limit: number = 10): Promise<Task[]> {
    try {
      const response = await fetchAPI<{ tasks: Task[] }>(
        "/api/tasks/search/similar",
        {
          method: "POST",
          body: { query, limit },
        },
      );
      return response.tasks || [];
    } catch (error) {
      logger.error("搜索相似任务异常:", error);
      throw error;
    }
  },

  /**
   * 智能推荐下一个任务
   */
  async getNextSuggestion(): Promise<Task | null> {
    try {
      const response = await fetchAPI<{ task?: Task }>(
        "/api/tasks/suggestions/next",
      );
      return response.task || null;
    } catch (error) {
      logger.error("获取任务推荐异常:", error);
      throw error;
    }
  },

  /**
   * 获取任务树
   */
  async getTaskTree(rootTaskId: string): Promise<Record<string, any>> {
    try {
      return await fetchAPI<Record<string, any>>(
        `/api/tasks/tree/${encodeURIComponent(rootTaskId)}`,
      );
    } catch (error) {
      logger.error("获取任务树异常:", error);
      throw error;
    }
  },

  /**
   * 获取任务统计信息
   */
  async getTaskStats(): Promise<Record<string, any>> {
    try {
      return await fetchAPI<Record<string, any>>("/api/tasks/stats/overview");
    } catch (error) {
      logger.error("获取任务统计异常:", error);
      throw error;
    }
  },

  /**
   * 清理旧任务
   */
  async cleanupTasks(days: number = 30): Promise<{ success: boolean; deleted: number }> {
    try {
      return await fetchAPI<{ success: boolean; deleted: number }>(
        "/api/tasks/cleanup",
        {
          method: "POST",
          body: { days },
        },
      );
    } catch (error) {
      logger.error("清理旧任务异常:", error);
      throw error;
    }
  },

  /**
   * 任务 API 健康检查
   */
  async healthCheck(): Promise<{ status: string }> {
    try {
      return await fetchAPI<{ status: string }>("/api/tasks/health/check");
    } catch (error) {
      logger.error("任务健康检查异常:", error);
      throw error;
    }
  },

  /**
   * 获取任务执行进度
   */
  async getTaskProgress(taskId: string): Promise<{ progress: number; checkpoints: any[] }> {
    try {
      return await fetchAPI<{ progress: number; checkpoints: any[] }>(
        `/api/tasks/${encodeURIComponent(taskId)}/progress`,
      );
    } catch (error) {
      logger.error("获取任务进度异常:", error);
      throw error;
    }
  },

  /**
   * 列出任务的所有断点
   */
  async getCheckpoints(taskId: string): Promise<any[]> {
    try {
      const response = await fetchAPI<{ checkpoints: any[] }>(
        `/api/tasks/${encodeURIComponent(taskId)}/checkpoints`,
      );
      return response.checkpoints || [];
    } catch (error) {
      logger.error("获取任务断点异常:", error);
      throw error;
    }
  },

  /**
   * 手动创建断点
   */
  async createCheckpoint(taskId: string, data?: Record<string, any>): Promise<{ success: boolean; checkpoint_id: string }> {
    try {
      return await fetchAPI<{ success: boolean; checkpoint_id: string }>(
        `/api/tasks/${encodeURIComponent(taskId)}/checkpoints`,
        {
          method: "POST",
          body: data || {},
        },
      );
    } catch (error) {
      logger.error("创建任务断点异常:", error);
      throw error;
    }
  },
};

/**
 * 将后端 /api/tasks 列表返回的原始项转换为前端 UI 状态对象
 * 后端可能返回 priority 为字符串（"medium"）或数字，created_at 为 ISO 字符串或毫秒时间戳
 */
export function adaptTaskListItem(raw: TaskListItem): TaskStatus {
  return {
    id: raw.id,
    name: raw.title || "未命名任务",
    description: raw.description || "",
    status: normalizeTaskState(raw.status),
    progress: raw.progress ?? 0,
    startTime: normalizeTimestamp(raw.created_at),
    elapsedTime: 0,
    priority: normalizePriority(raw.priority),
    created_at: normalizeTimestamp(raw.created_at),
  };
}

function normalizeTaskState(status: string): TaskStatus["status"] {
  const validStates: TaskStatus["status"][] = [
    "pending",
    "ready",
    "running",
    "paused",
    "completed",
    "failed",
    "cancelled",
    "archived",
    "interrupted",
    "awaiting_confirmation",
    "confirming_understanding",
    "confirmed",
  ];
  return validStates.includes(status as TaskStatus["status"])
    ? (status as TaskStatus["status"])
    : "pending";
}

function normalizePriority(priority: string | number | undefined): number {
  if (typeof priority === "number") return priority;
  switch (priority) {
    case "urgent":
      return 4;
    case "high":
      return 3;
    case "normal":
    case "medium":
      return 2;
    case "low":
      return 1;
    default:
      return 2;
  }
}

function normalizeTimestamp(ts: string | number | undefined): number {
  if (!ts) return Date.now();
  if (typeof ts === "number") return ts;
  const parsed = new Date(ts).getTime();
  return Number.isNaN(parsed) ? Date.now() : parsed;
}

export default taskApi;
