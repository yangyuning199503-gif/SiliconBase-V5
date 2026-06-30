import { useState, useEffect, useCallback, useRef } from 'react';
import { useWebSocket } from './useWebSocket';
import { authFetch } from '../utils/api';

/**
 * 语音状态类型
 */
export type VoiceState = 'idle' | 'awake' | 'speaking' | 'listening';

/**
 * 语音状态数据
 */
export interface VoiceStateData {
  awake: boolean;
  is_speaking: boolean;
  is_listening: boolean;
  protected_until: number | null;
  is_protected: boolean;
}

/**
 * 完整的语音状态信息
 */
export interface VoiceStateInfo extends VoiceStateData {
  state: VoiceState;
  timestamp: string;
}

/**
 * useVoiceState Hook 返回类型
 */
export interface UseVoiceStateReturn {
  /** 当前语音状态 */
  state: VoiceState;
  /** 是否处于唤醒状态 */
  isAwake: boolean;
  /** 是否正在播报 */
  isSpeaking: boolean;
  /** 是否正在识别 */
  isListening: boolean;
  /** 是否处于保护期 */
  isProtected: boolean;
  /** 保护期剩余秒数 */
  protectedCountdown: number;
  /** WebSocket 是否连接 */
  isConnected: boolean;
  /** 是否发生错误（降级到轮询或同步失败） */
  hasError: boolean;
  /** 最后更新时间 */
  lastUpdateTime: Date | null;
  /** 手动刷新状态（轮询模式下使用） */
  refreshState: () => Promise<void>;
}

/**
 * 语音状态同步 Hook
 * 
 * 功能：
 * 1. 通过 WebSocket 实时接收语音状态变化
 * 2. WebSocket 断开时自动降级到轮询模式
 * 3. 管理保护期倒计时
 * 4. 提供完整的状态信息
 * 
 * @param enablePolling - 是否启用 WebSocket 断开时的轮询降级（默认 true）
 * @param pollingInterval - 轮询间隔（毫秒，默认 3000ms）
 * @returns UseVoiceStateReturn
 */
export function useVoiceState(
  enablePolling: boolean = true,
  pollingInterval: number = 3000
): UseVoiceStateReturn {
  const { lastMessage, isConnected } = useWebSocket();
  
  // 状态
  const [state, setState] = useState<VoiceState>('idle');
  const [isAwake, setIsAwake] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [isProtected, setIsProtected] = useState(false);
  const [protectedCountdown, setProtectedCountdown] = useState(0);
  const [hasError, setHasError] = useState(false);
  const [lastUpdateTime, setLastUpdateTime] = useState<Date | null>(null);
  
  // 保护期结束时间戳
  const protectedUntilRef = useRef<number | null>(null);
  
  // 轮询定时器
  const pollingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  
  /**
   * 处理 WebSocket 消息
   */
  useEffect(() => {
    if (!lastMessage) return;

    if (lastMessage.type === 'voice_state_change') {
      const data = lastMessage.data;
      if (!data) {
        console.error('[SILENT_FAILURE_BLOCKED] voice_state_change消息缺少data')
        return
      }
      
      // 从data中获取state，默认为idle
      const voiceState = (data.state as VoiceState) || 'idle'
      console.log('[useVoiceState] 收到状态变化:', voiceState, data);
      
      // 更新基本状态
      setState(voiceState);
      setIsAwake(data.awake ?? false);
      setIsSpeaking(data.is_speaking ?? false);
      setIsListening(data.is_listening ?? false);
      setLastUpdateTime(new Date());
      setHasError(false);
      
      // 处理保护期
      const protectedUntil = data?.protected_until as number | undefined;
      if (protectedUntil && protectedUntil > Date.now()) {
        protectedUntilRef.current = protectedUntil;
        setIsProtected(true);
        setProtectedCountdown(Math.ceil((protectedUntil - Date.now()) / 1000));
      } else {
        protectedUntilRef.current = null;
        setIsProtected(false);
        setProtectedCountdown(0);
      }
    }
  }, [lastMessage]);

  /**
   * 保护期倒计时
   */
  useEffect(() => {
    if (!isProtected || !protectedUntilRef.current) return;

    const interval = setInterval(() => {
      const remaining = Math.ceil((protectedUntilRef.current! - Date.now()) / 1000);
      
      if (remaining <= 0) {
        setIsProtected(false);
        setProtectedCountdown(0);
        protectedUntilRef.current = null;
        clearInterval(interval);
      } else {
        setProtectedCountdown(remaining);
      }
    }, 100);

    return () => clearInterval(interval);
  }, [isProtected]);

  /**
   * 轮询模式（WebSocket 断开时的降级处理）
   */
  const refreshState = useCallback(async () => {
    try {
      const response = await authFetch('/api/voice/status');
      if (response.ok) {
        const data = await response.json();
        
        // 根据 API 返回更新状态
        if (data.enabled !== undefined) {
          setHasError(false);
          // 这里可以根据实际 API 响应调整
        }
      }
    } catch (error) {
      console.error('[useVoiceState] 轮询获取状态失败:', error);
      setHasError(true);
    }
  }, []);

  /**
   * WebSocket 断开时的降级处理
   */
  useEffect(() => {
    if (!enablePolling) return;

    if (!isConnected) {
      // WebSocket 断开，启动轮询
      console.log('[useVoiceState] WebSocket 断开，启动轮询模式');
      
      // 立即执行一次
      refreshState();
      
      // 定时轮询
      pollingTimerRef.current = setInterval(refreshState, pollingInterval);
      
      // 5秒后标记为错误状态
      const errorTimer = setTimeout(() => {
        setHasError(true);
      }, 5000);
      
      return () => {
        if (pollingTimerRef.current) {
          clearInterval(pollingTimerRef.current);
        }
        clearTimeout(errorTimer);
      };
    } else {
      // WebSocket 连接恢复，停止轮询
      if (pollingTimerRef.current) {
        clearInterval(pollingTimerRef.current);
        pollingTimerRef.current = null;
      }
      setHasError(false);
    }
  }, [isConnected, enablePolling, pollingInterval, refreshState]);

  /**
   * 清理
   */
  useEffect(() => {
    return () => {
      if (pollingTimerRef.current) {
        clearInterval(pollingTimerRef.current);
      }
    };
  }, []);

  return {
    state,
    isAwake,
    isSpeaking,
    isListening,
    isProtected,
    protectedCountdown,
    isConnected,
    hasError,
    lastUpdateTime,
    refreshState,
  };
}

export default useVoiceState;
