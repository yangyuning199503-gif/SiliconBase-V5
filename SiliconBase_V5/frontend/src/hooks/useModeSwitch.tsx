import { useState, useEffect, useCallback, useRef } from 'react';
import { useWebSocket } from './useWebSocket';

/**
 * Agent模式类型
 */
export type AgentMode = 'daily' | 'focus';

/**
 * 切换状态类型
 */
export type SwitchState = 'idle' | 'switching' | 'completed' | 'failed';

/**
 * 模式切换上下文
 */
export interface ModeSwitchContext {
  goal: string;
  progress: string;
  working_memory_summary: string;
}

/**
 * useModeSwitch Hook 返回类型
 */
export interface UseModeSwitchReturn {
  /** 当前模式 */
  mode: AgentMode;
  /** 是否正在切换 */
  switching: boolean;
  /** 切换进度 0-1 */
  progress: number;
  /** 切换后的上下文 */
  context: ModeSwitchContext | null;
  /** 切换状态 */
  switchState: SwitchState;
  /** WebSocket是否连接 */
  isConnected: boolean;
  /** 是否有错误 */
  hasError: boolean;
  /** 错误信息 */
  errorMessage: string | null;
}

/**
 * 模式切换状态管理 Hook
 * 
 * 功能：
 * 1. 通过WebSocket实时接收模式切换状态
 * 2. 管理切换动画和进度
 * 3. 显示恢复的上下文
 * 4. 处理切换失败
 * 
 * @returns UseModeSwitchReturn
 */
export function useModeSwitch(): UseModeSwitchReturn {
  const { lastMessage, isConnected } = useWebSocket();
  
  // 当前模式
  const [mode, setMode] = useState<AgentMode>('daily');
  
  // 切换状态
  const [switchState, setSwitchState] = useState<SwitchState>('idle');
  
  // 切换进度 0-1
  const [progress, setProgress] = useState(0);
  
  // 切换上下文
  const [context, setContext] = useState<ModeSwitchContext | null>(null);
  
  // 错误状态
  const [hasError, setHasError] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  
  // 超时计时器
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const SWITCH_TIMEOUT = 30000; // 30秒超时

  /**
   * 清除超时计时器
   */
  const clearTimeoutTimer = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  /**
   * 设置超时计时器
   */
  const startTimeoutTimer = useCallback(() => {
    clearTimeoutTimer();
    timeoutRef.current = setTimeout(() => {
      setHasError(true);
      setErrorMessage('模式切换超时');
      setSwitchState('failed');
      setSwitching(false);
    }, SWITCH_TIMEOUT);
  }, [clearTimeoutTimer]);

  /**
   * 辅助函数：设置switching状态
   */
  const setSwitching = useCallback((value: boolean) => {
    if (value) {
      setSwitchState('switching');
    }
  }, []);

  /**
   * 处理WebSocket消息
   */
  useEffect(() => {
    if (!lastMessage) return;

    const data = lastMessage.data;
    if (!data) return;

    switch (lastMessage.type) {
      case 'mode_switching':
        // 正在切换中
        setSwitching(true);
        setProgress(data.progress as number);
        setHasError(false);
        setErrorMessage(null);
        startTimeoutTimer();
        console.log(`[useModeSwitch] 正在切换: ${data.from_mode} -> ${data.to_mode}, 进度: ${data.progress}`);
        break;

      case 'mode_switched':
        // 切换完成
        clearTimeoutTimer();
        setMode(data.mode as AgentMode);
        setContext(data.context as ModeSwitchContext);
        setSwitchState('completed');
        setProgress(1);
        setHasError(false);
        setErrorMessage(null);
        
        // 3秒后重置为idle状态
        setTimeout(() => {
          setSwitchState('idle');
          setProgress(0);
        }, 3000);
        
        console.log(`[useModeSwitch] 切换完成: ${data.mode}`, data.context);
        break;

      case 'mode_switch_failed':
        // 切换失败
        clearTimeoutTimer();
        setHasError(true);
        setErrorMessage(data.error as string);
        setSwitchState('failed');
        setSwitching(false);
        console.error(`[useModeSwitch] 切换失败: ${data.error}`);
        break;
    }
  }, [lastMessage, startTimeoutTimer, clearTimeoutTimer, setSwitching]);

  /**
   * WebSocket断开处理
   */
  useEffect(() => {
    if (!isConnected) {
      setHasError(true);
      setErrorMessage('连接断开，正在重试...');
    } else if (hasError && errorMessage === '连接断开，正在重试...') {
      // 连接恢复，清除连接错误
      setHasError(false);
      setErrorMessage(null);
    }
  }, [isConnected, hasError, errorMessage]);

  /**
   * 清理
   */
  useEffect(() => {
    return () => {
      clearTimeoutTimer();
    };
  }, [clearTimeoutTimer]);

  return {
    mode,
    switching: switchState === 'switching',
    progress,
    context,
    switchState,
    isConnected,
    hasError,
    errorMessage,
  };
}

export default useModeSwitch;
