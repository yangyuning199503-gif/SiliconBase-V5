/**
 * 会话管理类型定义
 * Phase 1 Week 2 - Session Store Types
 */

import type { Message } from "./index";

// 后端 SessionResponse 的严格类型（来自 OpenAPI 生成）
export type BackendSessionResponse = import('../generated/api-types').components['schemas']['SessionResponse']

// 后端 MessageListResponse 的严格类型（来自 OpenAPI 生成）
export type BackendMessageListResponse = import('../generated/api-types').components['schemas']['MessageListResponse']

// 后端 SessionListResponse 的严格类型（来自 OpenAPI 生成）
export type BackendSessionListResponse = import('../generated/api-types').components['schemas']['SessionListResponse']

// 会话模式类型（与后端 SessionMode 枚举对齐）
export type SessionMode = "daily" | "focus" | "analysis" | "debug";

// 会话状态
export type SessionStatus = "active" | "archived" | "deleted";

// 前端会话 UI 类型
// ├─ 基础字段：语义来自后端 SessionResponse，但可选性放宽以兼容本地构造
// └─ 扩展字段：last_message_preview 等为前端展示用
export interface Session {
  // ===== 基础字段（来自 BackendSessionResponse） =====
  id: string;
  title?: string;
  mode: SessionMode;
  status: SessionStatus;
  created_at?: string;
  updated_at?: string;
  message_count: number;
  last_message_at?: string;
  metadata?: Record<string, any>;
  user_id?: string;
  // ===== 前端 UI 扩展字段 =====
  last_message_preview?: string;
}

// 通用分页响应（保留供其他模块使用）
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
}

// 前端会话列表响应：items 为 UI Session 类型
export interface SessionListResponse {
  items: Session[];
  total: number;
  limit: number;
  offset: number;
}

// 前端消息列表响应：items 为 UI Message 类型
export interface MessageListResponse {
  items: Message[];
  has_more: boolean;
  next_cursor?: string;
}

// 创建会话请求参数
export interface CreateSessionParams {
  mode: SessionMode;
  title?: string;
  metadata?: Record<string, any>;
}

// 更新会话请求参数
export interface UpdateSessionParams {
  title?: string;
  status?: SessionStatus;
  metadata?: Record<string, any>;
}

// 获取消息列表参数
export interface GetMessagesParams {
  session_id: string;
  limit?: number;
  before_id?: string; // 用于分页，获取某条消息之前的消息
}

// 发送消息请求参数
export interface SendMessageParams {
  session_id: string;
  content: string;
  role?: "user" | "assistant" | "system" | "tool"; // 消息角色（默认'user'）
  content_type?: string; // 内容类型（默认'text'）
  attachments?: Array<{
    id: string;
    name: string;
    type: string;
    url: string;
  }>;
}

// 发送消息响应（与后端 AddMessageResponse 对齐）
export interface SendMessageResponse {
  message_id: string;
  session_id: string;
  created_at?: string;
}

// 会话API错误类型
export interface SessionAPIError {
  code: string;
  message: string;
  details?: Record<string, any>;
}

// 会话排序选项
export type SessionSortBy = "updated_at" | "created_at" | "last_message_at";
export type SessionSortOrder = "asc" | "desc";

// 获取会话列表参数（仅保留后端支持的字段）
export interface GetSessionsParams {
  mode?: SessionMode;
  status?: SessionStatus;
  limit?: number;
  offset?: number;
}
