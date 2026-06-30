/**
 * API 配置文件
 * 
 * 【静默失败阻断规则】
 * - HTTP错误必须抛出APIError，不能返回默认值
 * - JSON解析失败必须报错，不能返回null
 * - 401错误必须触发登出，不能静默重试
 */

import { API_BASE_URL } from './api';

/**
 * API配置对象
 */
export const apiConfig = {
  /** API基础URL */
  apiBaseUrl: import.meta.env.DEV ? '' : API_BASE_URL,
  
  /** 默认请求超时（毫秒） */
  defaultTimeout: 5000,
  
  /** 最大重试次数 */
  maxRetries: 2,
  
  /** 重试延迟基数（毫秒） */
  retryDelayBase: 500,
  
  /** 是否启用请求日志 */
  enableLogging: true,
  
  /** 是否启用静默失败阻断 */
  enableSilentFailureBlock: true,
} as const;

/**
 * 获取完整API URL
 * @param endpoint API端点
 * @returns 完整URL
 */
export function getFullApiUrl(endpoint: string): string {
  const normalizedEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  return `${apiConfig.apiBaseUrl}${normalizedEndpoint}`;
}

/**
 * Fetch选项接口
 */
export interface FetchOptions extends Omit<RequestInit, 'body'> {
  /** 超时时间（毫秒） */
  timeout?: number;
  /** 重试次数 */
  retries?: number;
  /** 请求体 */
  body?: any;
  /** 是否跳过认证 */
  skipAuth?: boolean;
  /** 是否静默处理错误（不触发全局 toast） */
  silent?: boolean;
}

export default apiConfig;
