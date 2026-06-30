/**
 * API 封装入口
 *
 * 【统一导出规则】
 * 所有请求函数统一从 core.ts 的 fetchAPI 导出，禁止在此文件内重复实现 fetch 逻辑。
 * 旧文件中的 `authFetch` / `fetchWithAuth` 等功能已通过 `skipAuth` / 直接返回 Response 替代。
 */

import { getAuthToken } from "../auth";

export {
  fetchAPI,
  handleAPIError,
  handleUnauthorized,
  APIError,
  api,
} from "./core";

export type { FetchOptions } from "../../config/api.config";

// ═══════════════════════════════════════════════════════════════════
// 轻量级认证 fetch（兼容旧代码）
// 需要原始 Response 的场景使用 fetchAPI 的 skipAuth=false 并自行处理
// ═══════════════════════════════════════════════════════════════════
export async function authFetch(url: string, options: RequestInit = {}) {
  const token = getAuthToken();
  const headers: Record<string, string> = {
    ...((options.headers as Record<string, string>) || {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  const response = await fetch(url, { ...options, headers });
  return response;
}

// ═══════════════════════════════════════════════════════════════════
// 错误处理辅助函数（兼容旧 handleError 签名）
// ═══════════════════════════════════════════════════════════════════
export function handleError(error: any, defaultMessage: string): never {
  const message = error instanceof Error ? error.message : defaultMessage;
  console.error(defaultMessage, error);
  throw new Error(message);
}

// ═══════════════════════════════════════════════════════════════════
// 导出各模块 API
// ═══════════════════════════════════════════════════════════════════
export * from "./config";
export * from "./metrics";
export * from "./tools";
export * from "./cost";
export * from "./features";
export * from "./gamification";
export * from "./voice";
export * from "./advancedModels";
export * from "./stats";
export * from "./threeViews";

// memory 模块导出（避免与 procedureLearning 等命名冲突）
export {
  memoryAPI,
  type Memory,
  type CreateMemoryParams,
  type MemoryListResponse,
  type SearchResponse as MemorySearchResponse,
  type EvolutionRecord,
  type EvolutionResponse,
  type EvolutionHistoryResponse,
  type ExecutionMemory,
  type ExecutionStats,
} from "./memory";

export * from "./siliconLife";
export * from "./session";

export * from "./phaseAnchor";

// reflection 模块与 metrics 模块有命名冲突，需要单独处理
export {
  reflectionAPI,
  type ReflectionRecord as Reflection,
  type ReflectionType,
  type ReflectionStats,
  type ReflectionConfig,
  type GetReflectionsParams,
  type ReflectionFeedbackParams,
  type ReflectionFeedbackResponse,
} from "./reflection";

export * from "./tonePreference";

// task 模块导出（避免与 procedureLearning 的 resumeTask 冲突）
export { taskApi } from "./task";

// chat 模块导出
export { chatApi, type SendChatParams, type SendChatResponse, type StreamChatCallbacks } from "./chat";

export * from "./agent";
export * from "./subagent";
export * from "./globalView";

// intervention 模块导出
export { interventionApi, type InterventionResult } from "./intervention";

export * from "./workflow";
export * from "./tradingMode";
export * from "./prompt";
export * from "./toolMarket";
export * from "./slots";
export * from "./procedures";
