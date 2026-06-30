/**
 * Session Store - 会话状态管理
 * Phase 1 Week 2 - Zustand Session Store
 * 【阶段2.2增强】支持记忆元数据字段存储
 *
 * 功能：
 * - 管理当前会话和会话列表
 * - 消息加载和发送
 * - 持久化当前会话ID
 * - 【阶段2.2新增】消息记忆元数据存储与保留
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";
import { sessionAPI } from "../utils/api/session";
import { getAuthUser } from "../utils/auth";
import type {
  Session,
  SessionListResponse,
  MessageListResponse,
} from "../utils/api/session";
import type {
  SessionMode,
  Message,
  UploadedFile,
} from "../types";

// 默认分页大小
const DEFAULT_PAGE_SIZE = 20;
const STORAGE_KEY = "siliconbase-session-storage";

/**
 * 确保消息有稳定 id，用于 React key 与状态映射。
 */
const ensureMessageId = (message: Message): Message => ({
  ...message,
  id:
    message.id ||
    `${message.role}-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
});

/**
 * Session State 接口
 */
export interface SessionState {
  // ═══════════════════════════════════════════════════════════════════
  // 当前会话（持久化）
  // ═══════════════════════════════════════════════════════════════════
  currentSessionId: string | null;
  currentSession: Session | null;

  // ═══════════════════════════════════════════════════════════════════
  // 会话列表（不持久化，从后端获取）
  // ═══════════════════════════════════════════════════════════════════
  sessions: Session[];
  isLoadingSessions: boolean;
  sessionsError: string | null;
  sessionsTotal: number;
  sessionsPage: number;
  hasMoreSessions: boolean;

  // ═══════════════════════════════════════════════════════════════════
  // 当前会话消息（不持久化，从后端获取）
  // ═══════════════════════════════════════════════════════════════════
  messages: Message[];
  hasMoreMessages: boolean;
  isLoadingMessages: boolean;
  messagesError: string | null;
  messagesPage: number;

  // ═══════════════════════════════════════════════════════════════════
  // Actions
  // ═══════════════════════════════════════════════════════════════════
  createSession: (mode: SessionMode, title?: string) => Promise<Session>;
  loadSessions: (reset?: boolean) => Promise<void>;
  switchSession: (sessionId: string) => Promise<void>;
  loadMoreMessages: () => Promise<void>;
  addMessage: (message: Message) => void;
  updateMessage: (id: string, updates: Partial<Message>) => void;
  sendMessage: (
    content: string,
    type?: "text" | "voice" | "chat" | "auto",
    files?: UploadedFile[],
  ) => Promise<void>;
  deleteSession: (sessionId: string) => Promise<void>;
  updateSessionTitle: (sessionId: string, title: string) => Promise<void>;
  generateSessionTitle: (sessionId: string) => Promise<string | null>;
  clearCurrentMessages: () => void;
  clearErrors: () => void;
}

/**
 * 创建 Session Store
 */
export const useSessionStore = create<SessionState>()(
  persist(
    (set, get) => ({
      // ═══════════════════════════════════════════════════════════════════
      // 初始状态
      // ═══════════════════════════════════════════════════════════════════
      currentSessionId: null,
      currentSession: null,

      sessions: [],
      isLoadingSessions: false,
      sessionsError: null,
      sessionsTotal: 0,
      sessionsPage: 1,
      hasMoreSessions: false,

      messages: [],
      hasMoreMessages: false,
      isLoadingMessages: false,
      messagesError: null,
      messagesPage: 1,

      // ═══════════════════════════════════════════════════════════════════
      // Actions Implementation
      // ═══════════════════════════════════════════════════════════════════

      /**
       * 创建新会话
       */
      createSession: async (
        mode: SessionMode,
        title?: string,
      ): Promise<Session> => {
        set({ sessionsError: null });

        try {
          console.log("[SessionStore] 创建新会话:", { mode, title });

          const session = await sessionAPI.createSession({ mode, title });

          set((state: SessionState) => ({
            sessions: [session, ...state.sessions],
            currentSessionId: session.id,
            currentSession: session,
            messages: [],
            messagesPage: 1,
            hasMoreMessages: false,
            messagesError: null,
          }));

          console.log("[SessionStore] 会话创建成功:", session.id);
          return session;
        } catch (error) {
          const errorMessage =
            error instanceof Error ? error.message : "创建会话失败";

          console.error("[SessionStore] 创建会话失败:", errorMessage);
          set({ sessionsError: errorMessage });
          throw error;
        }
      },

      /**
       * 加载会话列表
       */
      loadSessions: async (reset: boolean = true): Promise<void> => {
        const { sessionsPage, sessions, currentSessionId } = get();

        set({
          isLoadingSessions: true,
          sessionsError: null,
        });

        try {
          const page = reset ? 1 : sessionsPage;
          const limit = DEFAULT_PAGE_SIZE;

          console.log("[SessionStore] 加载会话列表:", { page, limit });

          const response: SessionListResponse = await sessionAPI.getSessions({
            status: "active",
            limit,
            offset: (page - 1) * limit,
          });

          const newSessions = reset
            ? response.items
            : [...sessions, ...response.items];

          // 【修复】验证当前会话是否在新加载的列表中
          // 如果不在，说明当前会话不属于当前用户，需要清除
          let newCurrentSessionId = currentSessionId;
          let newCurrentSession = get().currentSession;

          if (reset && currentSessionId && newSessions.length > 0) {
            const sessionExists = newSessions.some(
              (s) => s.id === currentSessionId,
            );
            if (!sessionExists) {
              console.warn(
                "[SessionStore] 当前会话不在用户会话列表中，清除当前会话:",
                currentSessionId,
              );
              newCurrentSessionId = null;
              newCurrentSession = null;
            }
          }

          const loadedCount = (page - 1) * limit + response.items.length;
          set({
            sessions: newSessions,
            sessionsTotal: response.total,
            sessionsPage: page + 1,
            hasMoreSessions: loadedCount < response.total,
            isLoadingSessions: false,
            currentSessionId: newCurrentSessionId,
            currentSession: newCurrentSession,
          });

          console.log("[SessionStore] 会话列表加载成功:", {
            count: response.items.length,
            total: response.total,
          });
        } catch (error) {
          const errorMessage =
            error instanceof Error ? error.message : "加载会话列表失败";

          console.error("[SessionStore] 加载会话列表失败:", errorMessage);
          set({
            isLoadingSessions: false,
            sessionsError: errorMessage,
          });
        }
      },

      /**
       * 切换当前会话
       */
      switchSession: async (sessionId: string): Promise<void> => {
        const { currentSessionId } = get();

        // 如果切换到相同会话，直接返回
        if (currentSessionId === sessionId) {
          console.log("[SessionStore] 已是当前会话:", sessionId);
          return;
        }

        set({
          isLoadingMessages: true,
          messagesError: null,
          messages: [],
          messagesPage: 1,
          hasMoreMessages: false,
        });

        try {
          console.log("[SessionStore] 切换会话:", {
            from: currentSessionId,
            to: sessionId,
          });

          // 并行获取会话详情和消息列表
          const [sessionDetail, messagesResponse] = await Promise.all([
            sessionAPI.getSession(sessionId),
            sessionAPI.getMessages({
              session_id: sessionId,
              limit: DEFAULT_PAGE_SIZE,
            }),
          ]);

          set({
            currentSessionId: sessionId,
            currentSession: sessionDetail,
            // 后端返回最新在前，前端内部统一为 chronological（旧→新）
            messages: [...messagesResponse.items].reverse().map(ensureMessageId),
            hasMoreMessages: messagesResponse.has_more,
            isLoadingMessages: false,
            messagesPage: 2, // 下次加载从第2页开始
          });

          console.log("[SessionStore] 会话切换成功:", {
            sessionId,
            messageCount: messagesResponse.items.length,
          });
        } catch (error) {
          const errorMessage =
            error instanceof Error ? error.message : "切换会话失败";

          console.error("[SessionStore] 切换会话失败:", errorMessage);
          set({
            isLoadingMessages: false,
            messagesError: errorMessage,
          });
        }
      },

      /**
       * 加载更多历史消息
       */
      loadMoreMessages: async (): Promise<void> => {
        const {
          currentSessionId,
          messages,
          messagesPage,
          hasMoreMessages,
          isLoadingMessages,
        } = get();

        // 没有更多消息或正在加载中，直接返回
        if (!currentSessionId || !hasMoreMessages || isLoadingMessages) {
          return;
        }

        set({ isLoadingMessages: true });

        try {
          // 获取最旧一条消息的ID作为分页标记（chronological 顺序下第一条为最旧）
          const oldestMessage = messages[0];

          console.log("[SessionStore] 加载更多消息:", {
            sessionId: currentSessionId,
            beforeId: oldestMessage?.id,
            page: messagesPage,
          });

          const response: MessageListResponse = await sessionAPI.getMessages({
            session_id: currentSessionId,
            limit: DEFAULT_PAGE_SIZE,
            before_id: oldestMessage?.id,
          });

          set({
            // 后端返回的最新在前，反转为旧→新后 prepend 到现有消息前
            messages: [
              ...response.items.reverse().map(ensureMessageId),
              ...messages,
            ],
            hasMoreMessages: response.has_more,
            messagesPage: messagesPage + 1,
            isLoadingMessages: false,
          });

          console.log("[SessionStore] 更多消息加载成功:", {
            loaded: response.items.length,
            total: messages.length + response.items.length,
          });
        } catch (error) {
          const errorMessage =
            error instanceof Error ? error.message : "加载消息失败";

          console.error("[SessionStore] 加载更多消息失败:", errorMessage);
          set({
            isLoadingMessages: false,
            messagesError: errorMessage,
          });
        }
      },

      /**
       * 添加消息到当前会话（本地操作，不调用API）
       * 【阶段2.2增强】保留记忆元数据字段
       */
      addMessage: (message: Message): void => {
        const messageWithId = ensureMessageId(message);
        set((state: SessionState) => ({
          // 内部保持 chronological（旧→新），新消息 append
          messages: [...state.messages, messageWithId],
        }));
        console.log("[SessionStore] 本地添加消息:", messageWithId.id, {
          hasMemoryMetadata: !!(
            message.memory_count ||
            message.memory_ids ||
            message.relevance_score
          ),
        });
      },


      /**
       * 更新消息
       * 【阶段2.2增强】确保记忆元数据字段在更新时保留
       */
      updateMessage: (id: string, updates: Partial<Message>): void => {
        set((state: SessionState) => ({
          messages: state.messages.map((msg: Message) => {
            if (msg.id !== id) return msg;

            // 合并更新，保留已有的记忆元数据字段
            const updated: Message = {
              ...msg,
              ...updates,
              // 如果更新中未提供记忆字段，保留原值
              memory_count:
                updates.memory_count !== undefined
                  ? updates.memory_count
                  : msg.memory_count,
              memory_ids:
                updates.memory_ids !== undefined
                  ? updates.memory_ids
                  : msg.memory_ids,
              relevance_score:
                updates.relevance_score !== undefined
                  ? updates.relevance_score
                  : msg.relevance_score,
              memory_types:
                updates.memory_types !== undefined
                  ? updates.memory_types
                  : msg.memory_types,
            };

            return updated;
          }),
        }));
        console.log("[SessionStore] 更新消息:", {
          id,
          updates: Object.keys(updates),
        });
      },


      /**
       * 发送消息
       * Phase 5 Week 9 - 自动标题生成
       */
      sendMessage: async (
        content: string,
        type?: "text" | "voice" | "chat" | "auto",
        files?: UploadedFile[],
      ): Promise<void> => {
        const { currentSessionId, currentSession, messages } = get();

        if (!currentSessionId) {
          const error = "没有活动的会话";
          console.error("[SessionStore]", error);
          set({ messagesError: error });
          throw new Error(error);
        }

        set({ messagesError: null });

        try {
          console.log("[SessionStore] 发送消息:", {
            sessionId: currentSessionId,
            contentLength: content.length,
            type,
            filesCount: files?.length,
          });

          // 先添加用户消息到本地（乐观更新）
          const userMessage: Message = {
            id: `temp-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
            role: "user",
            content,
            type: (type === "auto" ? "text" : type) || "text",
            timestamp: Date.now(),
            attachments: files,
            // 用户消息无记忆元数据
            memory_count: null,
            memory_ids: null,
            relevance_score: null,
            memory_types: null,
          };

          get().addMessage(userMessage);

          // 调用API发送消息
          const response = await sessionAPI.sendMessage({
            session_id: currentSessionId,
            content,
          });

          // 更新临时消息ID
          set((state: SessionState) => ({
            messages: state.messages.map((msg: Message) =>
              msg.id === userMessage.id
                ? { ...msg, id: response.message_id }
                : msg,
            ),
            // 更新会话的最后消息时间
            currentSession: currentSession
              ? { ...currentSession, last_message_at: new Date().toISOString() }
              : null,
          }));

          console.log("[SessionStore] 消息发送成功:", response.message_id);

          // Phase 5 Week 9 - 自动标题生成逻辑
          // 计算对话轮数（用户消息数）
          const userMessageCount = messages.filter(
            (m) => m.role === "user",
          ).length;
          const currentTitle = currentSession?.title || "";
          const isDefaultTitle =
            currentTitle.includes("日常会话") ||
            currentTitle.includes("专注会话") ||
            currentTitle.includes("新对话") ||
            currentTitle.match(/^\d{1,2}月\d{1,2}日/);

          // 达到3轮对话且标题为默认标题时，自动生成新标题
          if (userMessageCount >= 3 && isDefaultTitle) {
            console.log(
              "[SessionStore] 触发自动生成标题，当前轮数:",
              userMessageCount,
            );
            // 延迟执行，不阻塞当前操作
            setTimeout(() => {
              get().generateSessionTitle(currentSessionId);
            }, 1000);
          }
        } catch (error) {
          const errorMessage =
            error instanceof Error ? error.message : "发送消息失败";

          console.error("[SessionStore] 发送消息失败:", errorMessage);
          set({ messagesError: errorMessage });
          throw error;
        }
      },

      /**
       * 删除会话
       */
      deleteSession: async (sessionId: string): Promise<void> => {
        const { currentSessionId, sessions } = get();

        try {
          console.log("[SessionStore] 删除会话:", sessionId);

          await sessionAPI.deleteSession(sessionId);

          // 从列表中移除
          const updatedSessions = sessions.filter(
            (s: Session) => s.id !== sessionId,
          );

          set({
            sessions: updatedSessions,
            // 如果删除的是当前会话，清空当前会话状态
            ...(currentSessionId === sessionId
              ? {
                  currentSessionId: null,
                  currentSession: null,
                  messages: [],
                  hasMoreMessages: false,
                }
              : {}),
          });

          console.log("[SessionStore] 会话删除成功:", sessionId);
        } catch (error) {
          const errorMessage =
            error instanceof Error ? error.message : "删除会话失败";

          console.error("[SessionStore] 删除会话失败:", errorMessage);
          set({ sessionsError: errorMessage });
          throw error;
        }
      },

      /**
       * 更新会话标题
       */
      updateSessionTitle: async (
        sessionId: string,
        title: string,
      ): Promise<void> => {
        const { sessions, currentSession } = get();

        try {
          console.log("[SessionStore] 更新会话标题:", { sessionId, title });

          const updatedSession = await sessionAPI.updateSession(sessionId, {
            title,
          });

          set({
            sessions: sessions.map((s: Session) =>
              s.id === sessionId ? { ...s, ...updatedSession } : s,
            ),
            currentSession:
              currentSession?.id === sessionId
                ? { ...currentSession, ...updatedSession }
                : currentSession,
          });

          console.log("[SessionStore] 会话标题更新成功");
        } catch (error) {
          const errorMessage =
            error instanceof Error ? error.message : "更新标题失败";

          console.error("[SessionStore] 更新标题失败:", errorMessage);
          set({ sessionsError: errorMessage });
          throw error;
        }
      },

      /**
       * 自动生成会话标题
       * Phase 5 Week 9 - 用户体验优化
       * 基于对话内容调用AI生成有意义的标题
       */
      generateSessionTitle: async (
        sessionId: string,
      ): Promise<string | null> => {
        try {
          console.log("[SessionStore] 自动生成会话标题:", sessionId);

          // 调用后端API生成标题
          const generatedTitle = await sessionAPI.generateTitle(sessionId);

          if (generatedTitle) {
            // 更新本地状态
            await get().updateSessionTitle(sessionId, generatedTitle);
            console.log("[SessionStore] 自动生成标题成功:", generatedTitle);
            return generatedTitle;
          }

          return null;
        } catch (error) {
          console.error("[SessionStore] 自动生成标题失败:", error);
          return null;
        }
      },

      /**
       * 清空当前会话消息
       */
      clearCurrentMessages: (): void => {
        set({
          messages: [],
          hasMoreMessages: false,
          messagesPage: 1,
        });
        console.log("[SessionStore] 清空当前会话消息");
      },

      /**
       * 清除错误状态
       */
      clearErrors: (): void => {
        set({
          sessionsError: null,
          messagesError: null,
        });
      },
    }),
    {
      // ═══════════════════════════════════════════════════════════════════
      // 持久化配置
      // ═══════════════════════════════════════════════════════════════════
      name: STORAGE_KEY,

      /**
       * 只持久化 currentSessionId
       * - 会话列表会在页面加载后重新获取
       * - 消息不缓存，每次从后端拉取
       */
      partialize: (state: SessionState) => ({
        currentSessionId: state.currentSessionId,
      }),

      /**
       * 【修复】重新加载存储后验证会话
       * 如果持久化的会话不属于当前用户，清除它
       */
      onRehydrateStorage: () => (state) => {
        if (state && state.currentSessionId) {
          console.log(
            "[SessionStore] 从存储恢复会话ID:",
            state.currentSessionId,
          );
          // 延迟验证，等待用户信息加载完成
          setTimeout(() => {
            const currentUser = getAuthUser();
            if (!currentUser) {
              console.warn("[SessionStore] 用户未登录，清除恢复的会话ID");
              state.currentSessionId = null;
              state.currentSession = null;
            }
          }, 100);
        }
      },
    },
  ),
);

// ═══════════════════════════════════════════════════════════════════
// 导出类型和辅助函数
// ═══════════════════════════════════════════════════════════════════

/**
 * 获取当前会话ID的选择器（用于组件外部使用）
 */
export const getCurrentSessionId = (): string | null => {
  return useSessionStore.getState().currentSessionId;
};

/**
 * 获取当前会话的选择器
 */
export const getCurrentSession = (): Session | null => {
  return useSessionStore.getState().currentSession;
};

/**
 * 获取当前消息列表的选择器
 */
export const getCurrentMessages = (): Message[] => {
  return useSessionStore.getState().messages;
};

/**
 * 创建新会话的快捷函数
 */
export const createNewSession = async (
  mode: SessionMode,
  title?: string,
): Promise<Session> => {
  return useSessionStore.getState().createSession(mode, title);
};

/**
 * 发送消息的快捷函数
 */
export const sendChatMessage = async (content: string): Promise<void> => {
  return useSessionStore.getState().sendMessage(content);
};

