/**
 * API 核心模块
 * 提供统一的 fetch 封装、token 注入、自动刷新、错误处理
 */

import { getApiUrl } from '../../config/ports';

/**
 * API 错误类
 */
export class APIError extends Error {
  status: number;
  data?: unknown;

  constructor(message: string, status: number = 500, data?: unknown) {
    super(message);
    this.name = 'APIError';
    this.status = status;
    this.data = data;
  }
}

/**
 * 处理未授权：统一登出并派发事件
 */
export function handleUnauthorized(): void {
  console.warn('[API] Token 失效，执行统一登出');

  // 清除认证信息
  localStorage.removeItem('silicon_token');
  localStorage.removeItem('silicon_refresh_token');
  localStorage.removeItem('silicon_user');
  localStorage.removeItem('silicon_token_expires_at');

  // 派发认证过期事件，供全局监听器处理（避免直接操作 window.location）
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('auth:session_expired', {
      detail: { reason: 'token_expired' },
    }));
  }
}

/**
 * 处理 API 错误，返回可读的错误信息
 */
export function handleAPIError(error: unknown, fallbackMessage?: string): string {
  let message: string;
  if (error instanceof APIError) {
    message = error.message || fallbackMessage || `请求失败 (${error.status})`;
  } else if (error instanceof Error) {
    message = error.message || fallbackMessage || '发生未知错误';
  } else {
    message = fallbackMessage || '发生未知错误';
  }
  return message;
}

/**
 * 获取认证 token
 */
export function getAuthToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('silicon_token');
}

/**
 * 设置认证 token
 */
export function setAuthToken(token: string): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem('silicon_token', token);
}

/**
 * 获取刷新 token
 */
export function getRefreshToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('silicon_refresh_token');
}

/**
 * 刷新认证 token
 */
async function refreshAuthToken(): Promise<boolean> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return false;

  try {
    const response = await fetch(`${getApiUrl('/api/auth/refresh')}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ refresh_token: refreshToken }),
      credentials: 'include',
    });

    if (!response.ok) {
      return false;
    }

    const data = await response.json();
    if (data.access_token) {
      setAuthToken(data.access_token);
      if (data.refresh_token) {
        localStorage.setItem('silicon_refresh_token', data.refresh_token);
      }
      if (data.expires_at) {
        localStorage.setItem('silicon_token_expires_at', String(data.expires_at));
      }
      return true;
    }
    return false;
  } catch (error) {
    console.error('[API] Token 刷新失败:', error);
    return false;
  }
}

// 全局单 Promise 刷新锁，避免并发刷新竞态
let refreshPromise: Promise<string | null> | null = null;

async function performTokenRefresh(): Promise<string | null> {
  try {
    const refreshed = await refreshAuthToken();
    return refreshed ? getAuthToken() : null;
  } finally {
    refreshPromise = null;
  }
}

/**
 * 请求选项扩展
 * - body 支持直接传入对象（自动 JSON 序列化）
 * - silent: 静默模式（调用方自行处理错误）
 * - timeout: 自定义超时时间（毫秒）
 */
export interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: BodyInit | object | null;
  silent?: boolean;
  timeout?: number;
}

/**
 * 解析响应数据
 */
async function parseResponse<T>(response: Response): Promise<T> {
  const contentType = response.headers.get('content-type') || '';
  const contentLength = response.headers.get('content-length');

  // 204 No Content 或空响应
  if (response.status === 204 || contentLength === '0') {
    return {} as T;
  }

  if (contentType.includes('application/json')) {
    try {
      return (await response.json()) as T;
    } catch {
      return {} as T;
    }
  }

  // 非 JSON 响应，返回文本（调用方按需处理）
  return (await response.text()) as unknown as T;
}

/**
 * 统一的 API 请求封装
 * - 自动注入 Authorization token
 * - 自动将对象 body 序列化为 JSON
 * - 401 时自动刷新 token（单 Promise 锁，避免并发竞态）
 * - 网络错误时自动重试
 * - 统一的错误处理
 */
export async function fetchAPI<T>(
  endpoint: string,
  options: RequestOptions = {},
): Promise<T> {
  const url = getApiUrl(endpoint);

  // 规范化 headers
  const headers: Record<string, string> = {};
  if (options.headers) {
    if (options.headers instanceof Headers) {
      options.headers.forEach((value, key) => {
        headers[key] = value;
      });
    } else if (Array.isArray(options.headers)) {
      options.headers.forEach(([key, value]) => {
        headers[key] = value;
      });
    } else {
      Object.assign(headers, options.headers as Record<string, string>);
    }
  }

  // 自动注入 token
  const token = getAuthToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  // 自动序列化 JSON body
  let body: BodyInit | undefined = options.body as BodyInit | undefined;
  if (
    body !== undefined &&
    body !== null &&
    typeof body === 'object' &&
    !(body instanceof FormData) &&
    !(body instanceof URLSearchParams) &&
    !(body instanceof Blob) &&
    !(body instanceof ArrayBuffer)
  ) {
    if (!headers['Content-Type'] && !headers['content-type']) {
      headers['Content-Type'] = 'application/json';
    }
    body = JSON.stringify(body);
  }

  const requestTimeout = options.timeout ?? 30000;

  const fetchOptions: RequestInit = {
    ...options,
    headers,
    body,
    credentials: options.credentials ?? 'include',
  };

  const MAX_RETRIES = 2;
  let lastError: Error | null = null;

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), requestTimeout);

      const response = await fetch(url, {
        ...fetchOptions,
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      // 请求成功
      if (response.ok) {
        return await parseResponse<T>(response);
      }

      // 401 未授权：尝试刷新 token
      if (response.status === 401) {
        if (!refreshPromise) {
          refreshPromise = performTokenRefresh();
        }
        const newToken = await refreshPromise;

        if (newToken) {
          // 使用新 token 重试原请求
          return fetchAPI<T>(endpoint, options);
        } else {
          handleUnauthorized();
          throw new APIError('登录已过期，请重新登录', 401);
        }
      }

      // 其他错误：解析后端返回的错误信息
      let errorMessage = `请求失败 (${response.status})`;
      let errorData: unknown = null;
      try {
        const contentType = response.headers.get('content-type') || '';
        if (contentType.includes('application/json')) {
          errorData = await response.json();
        } else {
          errorData = await response.text();
        }
        const data = errorData as Record<string, unknown> | string;
        if (typeof data === 'string') {
          errorMessage = data || errorMessage;
        } else {
          errorMessage =
            (data.detail as string) ||
            (data.message as string) ||
            response.statusText ||
            errorMessage;
        }
      } catch {
        // 忽略解析错误，使用默认错误信息
      }

      throw new APIError(errorMessage, response.status, errorData);
    } catch (error) {
      // 处理超时/取消
      if (error instanceof DOMException && error.name === 'AbortError') {
        lastError = new Error('请求超时，请稍后重试');
      } else if (error instanceof APIError) {
        throw error;
      } else if (error instanceof Error) {
        lastError = error;
      } else {
        lastError = new Error(String(error));
      }

      // 网络错误时重试（非最后一次）
      if (attempt < MAX_RETRIES) {
        const delay = Math.min(1000 * Math.pow(2, attempt), 4000);
        await new Promise((resolve) => setTimeout(resolve, delay));
        continue;
      }
    }
  }

  throw lastError || new APIError('请求失败', 500);
}

/**
 * 兼容性 API 对象（保留旧用法）
 */
export const api = {
  get: <T>(endpoint: string, options?: RequestOptions) =>
    fetchAPI<T>(endpoint, { ...options, method: 'GET' }),
  post: <T>(endpoint: string, body?: object, options?: RequestOptions) =>
    fetchAPI<T>(endpoint, { ...options, method: 'POST', body }),
  put: <T>(endpoint: string, body?: object, options?: RequestOptions) =>
    fetchAPI<T>(endpoint, { ...options, method: 'PUT', body }),
  patch: <T>(endpoint: string, body?: object, options?: RequestOptions) =>
    fetchAPI<T>(endpoint, { ...options, method: 'PATCH', body }),
  delete: <T>(endpoint: string, options?: RequestOptions) =>
    fetchAPI<T>(endpoint, { ...options, method: 'DELETE' }),
};
