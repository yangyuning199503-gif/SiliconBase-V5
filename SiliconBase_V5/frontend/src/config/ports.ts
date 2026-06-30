/**
 * 端口配置中心
 * 与后端 config/system_ports.py 保持一致
 *
 * 【配置优先级】
 * 1. 环境变量 (VITE_*)
 * 2. 运行时注入配置 (window.__SILICONBASE_CONFIG__)
 * 3. 默认配置
 */

// 默认端口配置
const DEFAULT_PORTS = {
  api: {
    port: 8600,
    host: "127.0.0.1",
    scheme: "http",
  },
  websocket: {
    port: 8600,
    host: "127.0.0.1",
    scheme: "ws",
  },
  frontend: {
    port: 5173,
    host: "127.0.0.1",
    scheme: "http",
  },
};

// 从环境变量读取配置
const getEnvConfig = () => {
  return {
    api: {
      port: parseInt(
        import.meta.env.VITE_API_PORT || String(DEFAULT_PORTS.api.port),
        10,
      ),
      host: import.meta.env.VITE_API_HOST || DEFAULT_PORTS.api.host,
      scheme: import.meta.env.VITE_API_SCHEME || DEFAULT_PORTS.api.scheme,
    },
    websocket: {
      port: parseInt(
        import.meta.env.VITE_WS_PORT || String(DEFAULT_PORTS.websocket.port),
        10,
      ),
      host: import.meta.env.VITE_WS_HOST || DEFAULT_PORTS.websocket.host,
      scheme: import.meta.env.VITE_WS_SCHEME || DEFAULT_PORTS.websocket.scheme,
    },
    frontend: {
      port: parseInt(
        import.meta.env.VITE_FRONTEND_PORT ||
          String(DEFAULT_PORTS.frontend.port),
        10,
      ),
      host: import.meta.env.VITE_FRONTEND_HOST || DEFAULT_PORTS.frontend.host,
      scheme:
        import.meta.env.VITE_FRONTEND_SCHEME || DEFAULT_PORTS.frontend.scheme,
    },
  };
};

// 从运行时注入配置读取 (如果后端提供了配置)
const getRuntimeConfig = () => {
  if (
    typeof window !== "undefined" &&
    (window as any).__SILICONBASE_CONFIG__?.server
  ) {
    const cfg = (window as any).__SILICONBASE_CONFIG__.server;
    return {
      api: {
        port: cfg.api_port || DEFAULT_PORTS.api.port,
        host: cfg.api_host || DEFAULT_PORTS.api.host,
        scheme: cfg.api_scheme || DEFAULT_PORTS.api.scheme,
      },
      websocket: {
        port: cfg.websocket_port || DEFAULT_PORTS.websocket.port,
        host: cfg.websocket_host || DEFAULT_PORTS.websocket.host,
        scheme: cfg.websocket_scheme || DEFAULT_PORTS.websocket.scheme,
      },
    };
  }
  return null;
};

// 合并配置 (优先级: 环境变量 > 运行时配置 > 默认配置)
const envConfig = getEnvConfig();
const runtimeConfig = getRuntimeConfig();

export const PORTS = {
  api: {
    ...DEFAULT_PORTS.api,
    ...runtimeConfig?.api,
    ...envConfig.api,
  },
  websocket: {
    ...DEFAULT_PORTS.websocket,
    ...runtimeConfig?.websocket,
    ...envConfig.websocket,
  },
  frontend: {
    ...DEFAULT_PORTS.frontend,
    ...envConfig.frontend,
  },
};

// 便捷函数
export const getApiUrl = (path: string = ""): string => {
  const { scheme, host, port } = PORTS.api;
  const base = `${scheme}://${host}:${port}`;
  return path ? `${base}${path.startsWith("/") ? path : `/${path}`}` : base;
};

export const getWsUrl = (path: string = ""): string => {
  const { scheme, host, port } = PORTS.websocket;
  const base = `${scheme}://${host}:${port}`;
  return path ? `${base}${path.startsWith("/") ? path : `/${path}`}` : base;
};

export const getFrontendUrl = (path: string = ""): string => {
  const { scheme, host, port } = PORTS.frontend;
  const base = `${scheme}://${host}:${port}`;
  return path ? `${base}${path.startsWith("/") ? path : `/${path}`}` : base;
};

// 向后兼容的导出
export const API_PORT = PORTS.api.port;
export const API_HOST = PORTS.api.host;
export const WS_PORT = PORTS.websocket.port;
export const WS_HOST = PORTS.websocket.host;

// Vite 代理配置使用的目标地址
export const API_PROXY_TARGET = `${PORTS.api.scheme}://${PORTS.api.host}:${PORTS.api.port}`;
export const WS_PROXY_TARGET = `${PORTS.websocket.scheme}://${PORTS.websocket.host}:${PORTS.websocket.port}`;

// 端口信息汇总
export const getPortInfo = () => ({
  api: {
    ...PORTS.api,
    url: getApiUrl(),
  },
  websocket: {
    ...PORTS.websocket,
    url: getWsUrl(),
  },
  frontend: {
    ...PORTS.frontend,
    url: getFrontendUrl(),
  },
});

// 调试输出
console.log("[Ports Config] 当前端口配置:", getPortInfo());
