// Agent类型
export interface Agent {
  id: string;
  name: string;
  icon: string;
  color: string;
  description: string;
}

// 上传文件类型
export interface UploadedFile {
  id: string;
  name: string;
  type: string;
  size: number;
  url?: string;
}

// 消息角色类型
export type MessageRole = "user" | "assistant" | "system" | "tool";

// 后端 MessageResponse 的严格类型（来自 OpenAPI 生成）
export type BackendMessageResponse = import('../generated/api-types').components['schemas']['api__session_api__MessageResponse']

// 【阶段2.2新增】记忆元数据类型
export interface MemoryMetadata {
  /** 检索到的记忆数量 */
  memory_count?: number | null;
  /** 使用的记忆ID列表 */
  memory_ids?: string[] | null;
  /** 记忆相关性评分（0-1之间） */
  relevance_score?: number | null;
  /** 记忆类型列表 */
  memory_types?: string[] | null;
}

// AI 思维流步骤类型统一集合
export type AIStepType =
  | "thinking"
  | "tool"
  | "result"
  | "complete"
  | "execution_complete"
  | "planning"
  | "analyzing"
  | "delegating";

// 【Week 2】AI思维流步骤（用于关联到消息）
export interface MessageAIStep {
  id: string;
  type: AIStepType;
  content: string;
  timestamp: number;
  metadata?: {
    toolName?: string;
    duration?: number;
    subagentName?: string;
  };
}

// 前端消息 UI 类型
// ├─ 基础字段：语义来自后端 MessageResponse，但可选性放宽以兼容本地构造
// └─ 扩展字段：timestamp/agent/type/msgType/toolCall/aiSteps 等为前端 UI 独有
export interface Message extends MemoryMetadata {
  // ===== 基础字段（来自 BackendMessageResponse） =====
  id?: string;
  session_id?: string;
  role: MessageRole;
  content: string;
  content_type?: string;
  metadata?: Record<string, unknown>;
  thinking?: string;
  memory_id?: string;
  created_at?: string;

  // ===== 前端 UI 扩展字段 =====
  timestamp?: number;
  agent?: string;
  type?: "text" | "voice" | "chat";
  msgType?: "task_started" | "task_breakdown" | "task_control" | "quick_chat" | "normal";
  toolCall?: ToolCall;
  toolResult?: ToolResult;
  isThinking?: boolean;
  round?: number;
  attachments?: UploadedFile[];
  aiSteps?: MessageAIStep[];
  aiStepsCount?: number;
}

// 工具调用
export interface ToolCall {
  id: string;
  tool: string;
  params: Record<string, unknown>;
  status: "pending" | "executing" | "success" | "error";
  progress?: number;
}

// 工具结果
export interface ToolResult {
  tool: string;
  success: boolean;
  data?: unknown;
  error?: string;
  executionTime?: number;
  params?: Record<string, unknown>;
  summary?: string;
}

// 任务列表项（后端 /api/tasks 轻量返回）
// 后端实际只返回：id, title, description, status, progress, priority, created_at
// 注意：priority 可能是字符串（"medium"/"high" 等）或数字；created_at 可能是 ISO 字符串或毫秒时间戳
export interface TaskListItem {
  id: string;
  title?: string;
  description?: string;
  status: string;
  progress?: number;
  priority?: string | number;
  created_at?: string | number;
}

// 任务状态（与后端 TaskStatus 枚举对齐）
export interface TaskStatus {
  id: string;
  name?: string;
  description?: string;
  status:
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
  progress?: number;
  startTime?: number;
  elapsedTime?: number;
  type?: string;
  intent?: string;
  priority?: number;
  created_at?: number;
  is_current?: boolean;
}

// WebSocket 消息数据类型
// 后端在 api/schemas.py 中定义了 WebSocketMessage / MessageType / UserInputMessage 等模型，
// 但这些模型未被纳入 OpenAPI，实际发送时多处绕过 schema 直接构造字典。
// 因此 payload 结构高度动态，暂时保留 any 作为通用容器，待后端统一 WS 发送路径后再类型化。
export interface WebSocketMessageData extends MemoryMetadata {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any;
  content?: string;
  message?: string;
  success?: boolean;
  agent?: string;
  session_id?: string;
  status?: string;
}

// 客户端 -> 服务端 WebSocket 消息类型
// 应与后端 MessageType 枚举保持一致
export type ClientWebSocketMessageType =
  | "auth"
  | "chat"
  | "voice"
  | "command"
  | "user_input"
  | "ping"
  | "mode_switch_request"
  | "confirm_response"
  | "accept_weak_proposal"
  | "dismiss_weak_proposal"
  | "timeout_weak_proposal"
  // 对齐相关：当前后端未直接支持这些字符串，保留以兼容现有前端逻辑
  | "clarification_response"
  | "confirmation_response"
  | "clarification_timeout"
  | "clarification_cancelled"
  | "confirmation_cancelled";

// 服务端 -> 客户端 WebSocket 消息类型
export type ServerWebSocketMessageType =
  // 内部信令
  | "pong"
  | "connected"
  // 基础消息类型
  | "message"
  | "thinking"
  | "tool_call"
  | "tool_result"
  | "reply"
  | "chat_response"
  | "error"
  | "stream_start"
  | "stream_chunk"
  | "stream_end"
  | "system_status"
  | "active_tasks"
  | "task_update"
  // 对齐相关类型
  | "clarification_needed"
  | "confirmation_needed"
  | "alignment_started"
  | "alignment_result"
  // 任务执行类型
  | "completed"
  | "executing"
  | "entering_task_loop"
  | "task_complete"
  // 学习和观察模式
  | "learning"
  | "chat_alignment_reply"
  | "quick_chat_reply"
  | "task_started"
  | "task_breakdown"
  | "task_control_reply"
  | "input_ack"
  | "intervention_ack"
  | "terminated"
  | "execution_complete"
  | "observer_mode"
  | "observer_mode_exit"
  // 弱连接提议
  | "weak_proposal"
  | "weak_proposal_accepted"
  // 语音状态
  | "voice_state_change"
  // 模式切换
  | "mode_switching"
  | "mode_switched"
  | "mode_switch_failed"
  // 感知触发
  | "perception_triggered"
  // SubAgent 监控
  | "subagent_stream"
  | "agent_tree_update"
  | "pipeline_status"
  | "longtask_subagent_info";

// 全部 WebSocket 消息类型（入站 + 出站）
export type WebSocketMessageType =
  | ClientWebSocketMessageType
  | ServerWebSocketMessageType;

// 客户端发送的 WebSocket 消息结构
// 前端发送的消息类型多样且后端未定义统一 schema，暂时使用 any 作为通用容器。
export interface ClientWebSocketMessage {
  type: ClientWebSocketMessageType;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any;
}

// 【阶段2.2增强】WebSocket消息结构（主要用于服务端推送）
export interface WebSocketMessage {
  type: ServerWebSocketMessageType;
  data?: WebSocketMessageData;
  message?: string;
  timestamp?: number;
  session_id?: string;
}

// 系统状态
export interface SystemStatus {
  cpu: number;
  memory: number;
  disk: number;
  activeTasks: number;
  currentAgent: string;
  uptime: number;
}

// 用户设置
export interface UserSettings {
  theme: "dark" | "light" | "auto";
  language: string;
  /** @deprecated 由 enable_voice 替代 */
  voiceEnabled: boolean;
  /** @deprecated 不再使用 */
  autoSpeak: boolean;
  messageDisplayMode: "compact" | "comfortable";
}

// AI状态类型
export type AIStatus =
  | "idle"
  | "listening"
  | "thinking"
  | "executing"
  | "observing"
  | "error";

// AI思维流步骤
export interface AIStep {
  id: string;
  type: AIStepType;
  content: string;
  timestamp: number;
  metadata?: {
    toolName?: string;
    duration?: number;
    subagentName?: string;
    progress?: number;
    screenshot?: string;
  };
  // 运行时扩展字段，用于临时附加结果数据
  data?: unknown;
}

// 对齐请求类型
export type AlignmentType = "clarification" | "confirmation";

// 澄清请求消息
export interface ClarificationNeededMessage {
  type: "clarification_needed";
  request_id: string;
  question: string;
  options?: string[];
  timeout?: number;
  timestamp: number;
}

// 确认请求消息
export interface ConfirmationNeededMessage {
  type: "confirmation_needed";
  request_id: string;
  question: string;
  message: string;
  timeout?: number;
  timestamp: number;
}

// 对齐响应消息
export interface AlignmentResponseMessage {
  type: "clarification_response" | "confirmation_response";
  request_id: string;
  response: string | boolean;
  timestamp: number;
}

// 【阶段2.2新增】AI响应消息类型（带记忆元数据）
export interface AIResponseMessage {
  type: "reply";
  timestamp: number;
  data: {
    role: "assistant";
    content: string;
    agent?: string;
    success?: boolean;
    // 记忆元数据
    memory_count?: number | null;
    memory_ids?: string[] | null;
    relevance_score?: number | null;
    memory_types?: string[] | null;
  };
}

// 【阶段2.2新增】记忆溯源信息（用于UI展示）
export interface MemoryAttribution {
  /** 记忆ID */
  id: string;
  /** 记忆内容摘要 */
  summary: string;
  /** 记忆类型 */
  type: string;
  /** 相关性评分（0-1） */
  relevance_score?: number;
  /** 创建时间 */
  created_at?: number;
  /** 记忆来源 */
  source?: string;
}

// 【阶段2.2新增】带记忆溯源的消息（用于前端展示）
export interface MessageWithAttribution extends Message {
  /** 记忆溯源列表 */
  memory_attributions?: MemoryAttribution[];
  /** 是否显示记忆溯源 */
  show_attribution?: boolean;
}

// 导出会话相关类型
export * from "./session";

// 导出槽位相关类型（Phase 4.5）
export * from "./slot";
