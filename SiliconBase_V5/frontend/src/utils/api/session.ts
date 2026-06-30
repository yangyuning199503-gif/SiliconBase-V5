/**
 * 会话管理API
 * Phase 1 Week 2 - Session API封装
 * Phase 1 - 静默失败阻断修复
 */

import { fetchAPI } from "./index";
import type {
  Session,
  SessionMode,
  SessionStatus,
  SessionListResponse,
  MessageListResponse,
  CreateSessionParams,
  UpdateSessionParams,
  GetMessagesParams,
  SendMessageParams,
  SendMessageResponse,
  GetSessionsParams,
  BackendSessionResponse,
  BackendSessionListResponse,
  BackendMessageListResponse,
} from "../../types/session";
import type { Message, MessageRole, BackendMessageResponse } from "../../types";


// 简单的日志工具（如果没有统一logger，使用console.error）
const logger = {
  error: (...args: any[]) => console.error(...args),
};

export const sessionAPI = {
  /**
   * 创建新会话
   * @param params - 创建会话参数
   * @returns 创建的会话
   */
  async createSession(params: CreateSessionParams): Promise<Session> {
    try {
      const backendSession = await fetchAPI<BackendSessionResponse>("/api/sessions", {
        method: "POST",
        body: {
          mode: params.mode,
          title: params.title || this.generateDefaultTitle(params.mode),
          initial_context: params.metadata || {},
        },
      });
      const session = adaptSession(backendSession);

      // 静默失败阻断检查
      if (!session) {
        logger.error("[SILENT_FAILURE_BLOCKED] createSession返回空值");
        throw new Error("创建会话失败：返回空值");
      }

      if (!session.id) {
        logger.error(
          "[SILENT_FAILURE_BLOCKED] createSession返回数据缺少id字段",
        );
        throw new Error("创建会话失败：返回数据格式错误，缺少id");
      }

      return session;
    } catch (error) {
      logger.error("[SILENT_FAILURE_BLOCKED] 创建会话异常:", error);
      throw error;
    }
  },

  /**
   * 获取会话列表
   * @param params - 查询参数
   * @returns 会话列表分页响应
   */
  async getSessions(params?: GetSessionsParams): Promise<SessionListResponse> {
    try {
      const queryParams = new URLSearchParams();

      if (params?.mode) queryParams.set("mode", params.mode);
      if (params?.status) queryParams.set("status", params.status);
      if (params?.limit) queryParams.set("limit", params.limit.toString());
      if (params?.offset !== undefined)
        queryParams.set("offset", params.offset.toString());

      const query = queryParams.toString();
      const backendData = await fetchAPI<BackendSessionListResponse>(
        `/api/sessions${query ? "?" + query : ""}`,
      );
      const data: SessionListResponse = {
        ...backendData,
        items: backendData.items.map(adaptSession),
      };

      // 静默失败阻断检查
      if (!data) {
        logger.error("[SILENT_FAILURE_BLOCKED] getSessions返回空值");
        throw new Error("获取会话列表失败：返回空值");
      }

      if (!data.items || !Array.isArray(data.items)) {
        logger.error(
          "[SILENT_FAILURE_BLOCKED] getSessions返回数据缺少items数组",
        );
        throw new Error("获取会话列表失败：返回数据格式错误");
      }

      return data;
    } catch (error) {
      logger.error("[SILENT_FAILURE_BLOCKED] 获取会话列表异常:", error);
      throw error;
    }
  },

  /**
   * 获取单个会话详情
   * @param sessionId - 会话ID
   * @returns 会话详情
   */
  async getSession(sessionId: string): Promise<Session> {
    try {
      const backendSession = await fetchAPI<BackendSessionResponse>(
        `/api/sessions/${encodeURIComponent(sessionId)}`,
      );
      const session = adaptSession(backendSession);

      // 静默失败阻断检查
      if (!session) {
        logger.error(
          "[SILENT_FAILURE_BLOCKED] getSession返回空值，sessionId:",
          sessionId,
        );
        throw new Error("获取会话详情失败：返回空值");
      }

      if (!session.id) {
        logger.error("[SILENT_FAILURE_BLOCKED] getSession返回数据缺少id字段");
        throw new Error("获取会话详情失败：返回数据格式错误");
      }

      return session;
    } catch (error) {
      logger.error("[SILENT_FAILURE_BLOCKED] 获取会话详情异常:", error);
      throw error;
    }
  },

  /**
   * 更新会话
   * @param sessionId - 会话ID
   * @param params - 更新参数
   * @returns 更新后的会话
   */
  async updateSession(
    sessionId: string,
    params: UpdateSessionParams,
  ): Promise<Session> {
    try {
      const backendSession = await fetchAPI<BackendSessionResponse>(
        `/api/sessions/${encodeURIComponent(sessionId)}`,
        {
          method: "PUT",
          body: params,
        },
      );
      const session = adaptSession(backendSession);

      // 静默失败阻断检查
      if (!session) {
        logger.error(
          "[SILENT_FAILURE_BLOCKED] updateSession返回空值，sessionId:",
          sessionId,
        );
        throw new Error("更新会话失败：返回空值");
      }

      if (!session.id) {
        logger.error(
          "[SILENT_FAILURE_BLOCKED] updateSession返回数据缺少id字段",
        );
        throw new Error("更新会话失败：返回数据格式错误");
      }

      return session;
    } catch (error) {
      logger.error("[SILENT_FAILURE_BLOCKED] 更新会话异常:", error);
      throw error;
    }
  },

  /**
   * 删除会话
   * @param sessionId - 会话ID
   * @returns 是否成功
   */
  async deleteSession(
    sessionId: string,
  ): Promise<{ success: boolean; id: string }> {
    try {
      const response = await fetchAPI<{ success: boolean; id: string }>(
        `/api/sessions/${encodeURIComponent(sessionId)}`,
        {
          method: "DELETE",
        },
      );

      // 静默失败阻断检查
      if (!response) {
        logger.error(
          "[SILENT_FAILURE_BLOCKED] deleteSession返回空值，sessionId:",
          sessionId,
        );
        throw new Error("删除会话失败：返回空值");
      }

      // 验证关键字段
      if (typeof response.success !== "boolean") {
        logger.error(
          "[SILENT_FAILURE_BLOCKED] deleteSession返回数据缺少success字段:",
          response,
        );
        throw new Error("删除会话失败：返回数据格式错误，缺少success");
      }

      // 验证id字段（静默失败阻断规则）
      if (!response.id) {
        logger.error(
          "[SILENT_FAILURE_BLOCKED] deleteSession返回数据缺少id字段:",
          response,
        );
        throw new Error("删除会话失败：返回数据格式错误，缺少id");
      }

      return response;
    } catch (error) {
      logger.error("[SILENT_FAILURE_BLOCKED] 删除会话异常:", error);
      throw error;
    }
  },

  /**
   * 批量删除会话
   * @param sessionIds - 会话ID列表
   * @returns 删除结果
   */
  async deleteSessionsBatch(
    sessionIds: string[],
  ): Promise<{ success: boolean; deleted: number }> {
    try {
      const response = await fetchAPI<{ success: boolean; deleted: number }>(
        "/api/sessions/batch",
        {
          method: "DELETE",
          body: { ids: sessionIds },
        },
      );

      // 静默失败阻断检查
      if (!response) {
        logger.error("[SILENT_FAILURE_BLOCKED] deleteSessionsBatch返回空值");
        throw new Error("批量删除会话失败：返回空值");
      }

      // 验证关键字段
      if (typeof response.success !== "boolean") {
        logger.error(
          "[SILENT_FAILURE_BLOCKED] deleteSessionsBatch返回数据缺少success字段:",
          response,
        );
        throw new Error("批量删除会话失败：返回数据格式错误，缺少success");
      }

      if (typeof response.deleted !== "number") {
        logger.error(
          "[SILENT_FAILURE_BLOCKED] deleteSessionsBatch返回数据缺少deleted字段:",
          response,
        );
        throw new Error("批量删除会话失败：返回数据格式错误，缺少deleted");
      }

      return response;
    } catch (error) {
      logger.error("[SILENT_FAILURE_BLOCKED] 批量删除会话异常:", error);
      throw error;
    }
  },

  /**
   * 获取会话消息列表
   * @param params - 查询参数
   * @returns 消息列表分页响应
   */
  async getMessages(params: GetMessagesParams): Promise<MessageListResponse> {
    try {
      const queryParams = new URLSearchParams();

      if (params.limit) queryParams.set("limit", params.limit.toString());
      if (params.before_id) queryParams.set("before_id", params.before_id);

      const query = queryParams.toString();
      const backendData = await fetchAPI<BackendMessageListResponse>(
        `/api/sessions/${encodeURIComponent(params.session_id)}/messages${query ? "?" + query : ""}`,
      );
      const data: MessageListResponse = {
        items: backendData.items.map(adaptMessage),
        has_more: backendData.has_more,
        next_cursor: backendData.next_cursor ?? undefined,
      };

      // 静默失败阻断检查
      if (!data) {
        logger.error(
          "[SILENT_FAILURE_BLOCKED] getMessages返回空值，sessionId:",
          params.session_id,
        );
        throw new Error("获取消息列表失败：返回空值");
      }

      if (!data.items || !Array.isArray(data.items)) {
        logger.error(
          "[SILENT_FAILURE_BLOCKED] getMessages返回数据缺少items数组",
        );
        throw new Error("获取消息列表失败：返回数据格式错误");
      }

      return data;
    } catch (error) {
      logger.error("[SILENT_FAILURE_BLOCKED] 获取消息列表异常:", error);
      throw error;
    }
  },

  /**
   * 发送消息
   * @param params - 发送消息参数
   * @returns 发送结果
   */
  async sendMessage(params: SendMessageParams): Promise<SendMessageResponse> {
    try {
      const data = await fetchAPI<SendMessageResponse>(
        `/api/sessions/${encodeURIComponent(params.session_id)}/messages`,
        {
          method: "POST",
          body: {
            role: "user", // ✅ 添加必需的role字段
            content: params.content,
            content_type: "text", // ✅ 添加必需的content_type字段
            attachments: params.attachments,
          },
        },
      );

      // 静默失败阻断检查
      if (!data) {
        logger.error(
          "[SILENT_FAILURE_BLOCKED] sendMessage返回空值，sessionId:",
          params.session_id,
        );
        throw new Error("发送消息失败：返回空值");
      }

      // 后端已返回 message_id
      if (!data.message_id) {
        logger.error(
          "[SILENT_FAILURE_BLOCKED] sendMessage返回数据缺少message_id字段",
        );
        throw new Error("发送消息失败：返回数据格式错误");
      }

      return data;
    } catch (error) {
      logger.error("[SILENT_FAILURE_BLOCKED] 发送消息异常:", error);
      throw error;
    }
  },

  /**
   * 生成会话标题（调用后端AI）
   * @param sessionId - 会话ID
   * @returns 生成的标题
   */
  async generateTitle(sessionId: string): Promise<string | null> {
    try {
      const data = await fetchAPI<{
        title?: string;
      }>("/api/sessions/generate-title", {
        method: "POST",
        body: { session_id: sessionId },
      });
      return data?.title || null;
    } catch (error) {
      logger.error("[SILENT_FAILURE_BLOCKED] 生成标题失败:", error);
      return null;
    }
  },

  /**
   * 生成默认标题
   * @param mode - 会话模式
   * @returns 默认标题
   */
  generateDefaultTitle(mode: SessionMode): string {
    const now = new Date();
    const dateStr = now.toLocaleDateString("zh-CN", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
    return mode === "daily" ? `日常会话 ${dateStr}` : `专注会话 ${dateStr}`;
  },

  /**
   * 中断会话中的 AgentLoop
   */
  async interruptSession(sessionId: string): Promise<{ success: boolean; message: string }> {
    try {
      const response = await fetchAPI<{ success: boolean; message: string }>(
        `/api/sessions/${encodeURIComponent(sessionId)}/interrupt`,
        { method: "POST" },
      );

      if (!response) {
        logger.error("[SILENT_FAILURE_BLOCKED] interruptSession返回空值");
        throw new Error("中断会话失败：返回空值");
      }

      return response;
    } catch (error) {
      logger.error("[SILENT_FAILURE_BLOCKED] 中断会话异常:", error);
      throw error;
    }
  },

  /**
   * 获取会话状态：是否正在运行 AgentLoop
   */
  async getSessionStatus(sessionId: string): Promise<{ running: boolean; status: string }> {
    try {
      const response = await fetchAPI<{ running: boolean; status: string }>(
        `/api/sessions/${encodeURIComponent(sessionId)}/status`,
      );

      if (!response) {
        logger.error("[SILENT_FAILURE_BLOCKED] getSessionStatus返回空值");
        throw new Error("获取会话状态失败：返回空值");
      }

      return response;
    } catch (error) {
      logger.error("[SILENT_FAILURE_BLOCKED] 获取会话状态异常:", error);
      throw error;
    }
  },
};

/**
 * 将后端 MessageResponse 转换为前端 UI Message 类型
 */
function adaptMessage(backend: BackendMessageResponse): Message {
  return {
    id: backend.id,
    session_id: backend.session_id,
    role: backend.role as MessageRole,
    content: backend.content,
    content_type: backend.content_type,
    metadata: backend.metadata ?? undefined,
    thinking: backend.thinking ?? undefined,
    memory_id: backend.memory_id ?? undefined,
    created_at: backend.created_at ?? undefined,
  };
}

/**
 * 将后端 SessionResponse 转换为前端 UI Session 类型
 */
function adaptSession(backend: BackendSessionResponse): Session {
  return {
    id: backend.id,
    title: backend.title ?? undefined,
    mode: backend.mode as SessionMode,
    status: backend.status as SessionStatus,
    created_at: backend.created_at ?? undefined,
    updated_at: backend.updated_at ?? undefined,
    message_count: backend.message_count,
    last_message_at: backend.last_message_at ?? undefined,
    metadata: backend.metadata ?? undefined,
    user_id: backend.user_id,
    last_message_preview: backend.last_message_preview ?? undefined,
  };
}

// 导出类型
export type {
  Session,
  SessionListResponse,
  MessageListResponse,
  CreateSessionParams,
  UpdateSessionParams,
  GetMessagesParams,
  SendMessageParams,
  SendMessageResponse,
  GetSessionsParams,
} from "../../types/session";
