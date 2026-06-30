/**
 * Session Store 使用示例
 * Phase 1 Week 2 - 展示如何在组件中使用 sessionStore
 */

import React, { useEffect, useCallback } from "react";
import { useSessionStore } from "./sessionStore";
import type { SessionMode } from "../types/session";

// ═══════════════════════════════════════════════════════════════════
// 示例工具函数 - 保留供参考
// ═══════════════════════════════════════════════════════════════════

/**
 * 发送消息处理函数示例
 * 展示如何正确使用 sessionStore 的 sendMessage 方法
 */
export const handleSendMessageExample = async (
  _sendMessage: (content: string) => Promise<void>,
  content: string,
) => {
  if (!content.trim()) return;

  try {
    await _sendMessage(content);
  } catch (error) {
    // 错误已在 store 中处理，这里可以添加额外的 UI 提示
    console.error("发送失败:", error);
  }
};

// ═══════════════════════════════════════════════════════════════════
// 示例 1: 基础使用 - 在聊天面板中
// ═══════════════════════════════════════════════════════════════════

export const ChatPanelExample: React.FC = () => {
  // 从 store 中获取需要的状态和方法
  const {
    currentSession,
    messages,
    isLoadingMessages,
    messagesError,
    hasMoreMessages,
    loadMoreMessages,
    clearErrors,
  } = useSessionStore();

  // 清除错误
  useEffect(() => {
    if (messagesError) {
      const timer = setTimeout(clearErrors, 5000);
      return () => clearTimeout(timer);
    }
  }, [messagesError, clearErrors]);

  // 加载更多消息
  const handleLoadMore = useCallback(async () => {
    if (hasMoreMessages && !isLoadingMessages) {
      await loadMoreMessages();
    }
  }, [hasMoreMessages, isLoadingMessages, loadMoreMessages]);

  return (
    <div className="chat-panel">
      {/* 会话标题 */}
      <div className="chat-header">
        <h3>{currentSession?.title || "未选择会话"}</h3>
        <span className="mode-badge">
          {currentSession?.mode === "daily" ? "日常模式" : "专注模式"}
        </span>
      </div>

      {/* 错误提示 */}
      {messagesError && (
        <div className="error-banner">
          {messagesError}
          <button onClick={clearErrors}>×</button>
        </div>
      )}

      {/* 消息列表 */}
      <div className="messages-container">
        {hasMoreMessages && (
          <button
            onClick={handleLoadMore}
            disabled={isLoadingMessages}
            className="load-more-btn"
          >
            {isLoadingMessages ? "加载中..." : "加载更多消息"}
          </button>
        )}

        {messages.map((message) => (
          <div key={message.id} className={`message ${message.role}`}>
            <div className="message-content">{message.content}</div>
            <span className="message-time">
              {new Date(message.timestamp || 0).toLocaleTimeString()}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════
// 示例 2: 会话列表组件
// ═══════════════════════════════════════════════════════════════════

export const SessionListExample: React.FC = () => {
  const {
    sessions,
    currentSessionId,
    isLoadingSessions,
    sessionsError,
    hasMoreSessions,
    loadSessions,
    switchSession,
    createSession,
    deleteSession,
    updateSessionTitle,
  } = useSessionStore();

  // 初始加载
  useEffect(() => {
    loadSessions(true);
  }, [loadSessions]);

  // 创建新会话
  const handleCreateSession = useCallback(
    async (mode: SessionMode) => {
      try {
        await createSession(mode);
      } catch (error) {
        console.error("创建会话失败:", error);
      }
    },
    [createSession],
  );

  // 切换会话
  const handleSwitchSession = useCallback(
    async (sessionId: string) => {
      try {
        await switchSession(sessionId);
      } catch (error) {
        console.error("切换会话失败:", error);
      }
    },
    [switchSession],
  );

  // 删除会话
  const handleDeleteSession = useCallback(
    async (sessionId: string) => {
      if (window.confirm("确定要删除这个会话吗？")) {
        try {
          await deleteSession(sessionId);
        } catch (error) {
          console.error("删除会话失败:", error);
        }
      }
    },
    [deleteSession],
  );

  // 重命名会话
  const handleRename = useCallback(
    async (sessionId: string, currentTitle: string) => {
      const newTitle = window.prompt("请输入新标题:", currentTitle);
      if (newTitle && newTitle !== currentTitle) {
        try {
          await updateSessionTitle(sessionId, newTitle);
        } catch (error) {
          console.error("重命名失败:", error);
        }
      }
    },
    [updateSessionTitle],
  );

  return (
    <div className="session-list">
      {/* 操作按钮 */}
      <div className="session-actions">
        <button onClick={() => handleCreateSession("daily")}>
          + 新建日常会话
        </button>
        <button onClick={() => handleCreateSession("focus")}>
          + 新建专注会话
        </button>
      </div>

      {/* 错误提示 */}
      {sessionsError && <div className="error-message">{sessionsError}</div>}

      {/* 会话列表 */}
      <div className="sessions">
        {sessions.map((session) => (
          <div
            key={session.id}
            className={`session-item ${session.id === currentSessionId ? "active" : ""}`}
            onClick={() => handleSwitchSession(session.id)}
          >
            <div className="session-info">
              <span className={`mode-icon ${session.mode}`}>
                {session.mode === "daily" ? "🌅" : "🎯"}
              </span>
              <span className="session-title">{session.title}</span>
              <span className="message-count">({session.message_count})</span>
            </div>
            <div className="session-meta">
              <span className="update-time">
                {new Date(
                  session.updated_at || Date.now(),
                ).toLocaleDateString()}
              </span>
              <div className="session-actions">
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleRename(session.id, session.title || "");
                  }}
                >
                  重命名
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDeleteSession(session.id);
                  }}
                >
                  删除
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* 加载更多 */}
      {hasMoreSessions && (
        <button
          onClick={() => loadSessions(false)}
          disabled={isLoadingSessions}
          className="load-more"
        >
          {isLoadingSessions ? "加载中..." : "加载更多"}
        </button>
      )}
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════
// 示例 3: 完整聊天页面
// ═══════════════════════════════════════════════════════════════════

export const ChatPageExample: React.FC = () => {
  // 组合使用多个 store 状态
  const currentSessionId = useSessionStore((state) => state.currentSessionId);
  const currentSession = useSessionStore((state) => state.currentSession);

  // 如果当前没有会话，自动创建一个
  useEffect(() => {
    if (!currentSessionId) {
      useSessionStore.getState().createSession("daily");
    }
  }, [currentSessionId]);

  return (
    <div className="chat-page">
      <aside className="sidebar">
        <SessionListExample />
      </aside>
      <main className="main-content">
        {currentSession ? (
          <ChatPanelExample />
        ) : (
          <div className="empty-state">
            <p>选择一个会话或创建新会话开始聊天</p>
          </div>
        )}
      </main>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════
// 示例 4: 在 Hook 中使用
// ═══════════════════════════════════════════════════════════════════

import { useState } from "react";

export function useSessionMessages() {
  const messages = useSessionStore((state) => state.messages);
  const isLoading = useSessionStore((state) => state.isLoadingMessages);
  const error = useSessionStore((state) => state.messagesError);
  const loadMore = useSessionStore((state) => state.loadMoreMessages);
  const hasMore = useSessionStore((state) => state.hasMoreMessages);

  return {
    messages,
    isLoading,
    error,
    hasMore,
    loadMore,
  };
}

export function useCurrentSession() {
  const session = useSessionStore((state) => state.currentSession);
  const sessionId = useSessionStore((state) => state.currentSessionId);
  const switchSession = useSessionStore((state) => state.switchSession);
  const createSession = useSessionStore((state) => state.createSession);

  return {
    session,
    sessionId,
    switchSession,
    createSession,
  };
}

// ═══════════════════════════════════════════════════════════════════
// 示例 5: 与 WebSocket 集成
// ═══════════════════════════════════════════════════════════════════

export function useSessionWebSocket() {
  const addMessage = useSessionStore((state) => state.addMessage);
  const updateMessage = useSessionStore((state) => state.updateMessage);
  const currentSessionId = useSessionStore((state) => state.currentSessionId);

  useEffect(() => {
    // 假设有一个 WebSocket 连接
    const ws = new WebSocket("ws://localhost:8600/ws");

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      // 只处理当前会话的消息
      if (data.session_id !== currentSessionId) return;

      switch (data.type) {
        case "message":
          // 添加新消息
          addMessage({
            id: data.message_id,
            role: data.role,
            content: data.content,
            timestamp: Date.now(),
          });
          break;

        case "message_update":
          // 更新消息（如流式响应）
          updateMessage(data.message_id, {
            content: data.content,
          });
          break;

        default:
          break;
      }
    };

    return () => {
      ws.close();
    };
  }, [currentSessionId, addMessage, updateMessage]);
}

// ═══════════════════════════════════════════════════════════════════
// 示例 6: 错误处理和重试
// ═══════════════════════════════════════════════════════════════════

export function useSessionWithRetry() {
  const [retryCount, setRetryCount] = useState(0);
  const loadSessions = useSessionStore((state) => state.loadSessions);
  const sessionsError = useSessionStore((state) => state.sessionsError);
  const clearErrors = useSessionStore((state) => state.clearErrors);

  const loadWithRetry = useCallback(async () => {
    try {
      await loadSessions(true);
      setRetryCount(0);
    } catch (error) {
      if (retryCount < 3) {
        setRetryCount((prev) => prev + 1);
        // 延迟重试
        setTimeout(() => loadWithRetry(), 1000 * (retryCount + 1));
      }
    }
  }, [loadSessions, retryCount]);

  useEffect(() => {
    loadWithRetry();
  }, [loadWithRetry]);

  return {
    retryCount,
    error: sessionsError,
    clearErrors,
    retry: loadWithRetry,
  };
}

export default ChatPanelExample;
