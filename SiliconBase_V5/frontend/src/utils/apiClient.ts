/**
 * API 客户端工具（兼容层）
 * 
 * ⚠️ 已弃用：新项目代码请直接使用 utils/api/core.ts 中的 fetchAPI。
 * 本文件保留仅为兼容旧组件，未来会逐步迁移并删除。
 */

import { APIError } from './api/core';
import { getAuthHeaders } from './auth';

/**
 * 带认证的 fetch 请求（兼容旧代码）
 * 自动添加 Authorization header 和 credentials
 * 
 * 内部统一走 fetchAPI，但返回原始 Response 以保持兼容。
 * 非 2xx 响应会抛出 APIError。
 */
export async function fetchWithAuth(
  url: string,
  options: RequestInit = {}
): Promise<Response> {
  const headers = {
    ...getAuthHeaders(),
    ...(options.headers || {}),
  };

  // 对于文件上传等请求，如果 headers 里已经有 Content-Type，不要覆盖
  // 但注意：旧 fetchWithAuth 不会自动 JSON 序列化 body，这里保持同样行为
  const response = await fetch(url, {
    ...options,
    headers,
    credentials: 'include',
  });

  if (!response.ok) {
    let errorMessage = `HTTP ${response.status}`;
    let errorData: any = null;
    try {
      errorData = await response.clone().json();
      errorMessage = errorData.message || errorData.error || errorData.detail || errorMessage;
    } catch {
      // 忽略解析失败
    }
    throw new APIError(errorMessage, response.status, errorData);
  }

  return response;
}

/**
 * 带认证的 GET 请求
 */
export async function get(url: string, options: RequestInit = {}): Promise<Response> {
  return fetchWithAuth(url, { ...options, method: 'GET' });
}

/**
 * 带认证的 POST 请求
 */
export async function post(
  url: string,
  data?: unknown,
  options: RequestInit = {}
): Promise<Response> {
  return fetchWithAuth(url, {
    ...options,
    method: 'POST',
    body: data ? JSON.stringify(data) : undefined,
  });
}

/**
 * 带认证的 PUT 请求
 */
export async function put(
  url: string,
  data?: unknown,
  options: RequestInit = {}
): Promise<Response> {
  return fetchWithAuth(url, {
    ...options,
    method: 'PUT',
    body: data ? JSON.stringify(data) : undefined,
  });
}

/**
 * 带认证的 DELETE 请求
 */
export async function del(url: string, options: RequestInit = {}): Promise<Response> {
  return fetchWithAuth(url, { ...options, method: 'DELETE' });
}
