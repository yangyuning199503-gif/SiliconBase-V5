import { useState, useEffect, useCallback } from 'react';
import { buildHealthUrl } from '../config/api';

interface SystemStatus {
  isBackendConnected: boolean;
  cpuUsage: number;
  memoryUsage: number;
  activeTasks: number;
}

interface UseSystemStatusOptions {
  pollInterval?: number;
}

export const useSystemStatus = (options: UseSystemStatusOptions = {}) => {
  const { pollInterval = 5000 } = options;
  
  const [status, setStatus] = useState<SystemStatus>({
    isBackendConnected: false,
    cpuUsage: 0,
    memoryUsage: 0,
    activeTasks: 0,
  });

  const checkBackend = useCallback(async () => {
    try {
      // 注意：health 端点没有 /api 前缀
      const response = await fetch(buildHealthUrl(), { 
        method: 'GET',
        signal: AbortSignal.timeout(3000)
      });
      const isConnected = response.ok;
      setStatus(prev => ({ ...prev, isBackendConnected: isConnected }));
    } catch (error) {
      console.error('[SystemStatus] 后端健康检查失败:', error);
      setStatus(prev => ({ ...prev, isBackendConnected: false }));
    }
  }, []);

  useEffect(() => {
    checkBackend();
    if (pollInterval > 0) {
      const interval = setInterval(checkBackend, pollInterval);
      return () => clearInterval(interval);
    }
  }, [checkBackend, pollInterval]);

  return { ...status, checkBackend };
};
