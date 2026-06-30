/**
 * API配置中心
 * 使用统一系统配置
 */

import { API_BASE_URL, WS_BASE_URL } from './system';

// 导出基础URL
export { API_BASE_URL, WS_BASE_URL };

// 语音API配置
export const VOICE_API_URL = API_BASE_URL;

// 导出常用端点构建函数
export const buildApiUrl = (endpoint: string): string => {
  const normalizedEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  // 使用相对路径，让Vite代理转发到后端
  // 避免跨域问题，开发时走代理，生产环境直接使用
  return normalizedEndpoint;
};

export const buildHealthUrl = (): string => {
  return '/health';
};

export const buildVoiceUrl = (path: string = '/voice_ptt'): string => {
  return path.startsWith('/') ? path : `/${path}`;
};

export const buildWsUrl = (path: string = '/ws'): string => {
  // WebSocket使用相对路径协议，让Vite代理处理
  // 使用相对协议 //host/path，浏览器会自动选择ws://或wss://
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}${normalizedPath}`;
};
