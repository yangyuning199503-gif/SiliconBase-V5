/**
 * 统一系统配置
 * 前后端共享配置
 * 
 * 【注意】端口配置已迁移到 ports.ts
 * 导入: import { API_PORT, WS_PORT, getApiUrl, getWsUrl } from './ports'
 */

import { getApiUrl, getWsUrl, getFrontendUrl, PORTS } from './ports';

// 向后兼容：系统配置对象
export const SYSTEM_CONFIG = {
  server: {
    host: PORTS.api.host,
    api_port: PORTS.api.port,
    websocket_port: PORTS.websocket.port,
    frontend_port: PORTS.frontend.port,
  },
  urls: {
    backend: getApiUrl(),
    websocket: getWsUrl(),
    frontend: getFrontendUrl(),
  },
  auth: {
    default_username: '',
    default_password: '',
    require_password_change: false,
  },
};

// 导出常用配置 (向后兼容)
export const API_BASE_URL = SYSTEM_CONFIG.urls.backend;
export const WS_BASE_URL = SYSTEM_CONFIG.urls.websocket;
export const FRONTEND_URL = SYSTEM_CONFIG.urls.frontend;
export const DEFAULT_USERNAME = SYSTEM_CONFIG.auth.default_username;
export const DEFAULT_PASSWORD = SYSTEM_CONFIG.auth.default_password;

// 重新导出端口配置
export { PORTS, getApiUrl, getWsUrl, getFrontendUrl, getPortInfo } from './ports';
